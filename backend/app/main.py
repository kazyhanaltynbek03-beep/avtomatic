Warning: truncated output (original token count: 90094)
Total output lines: 6188

from dataclasses import asdict
import os, secrets, json, hashlib, uuid, io, base64, logging, threading, time
import hmac
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from decimal import Decimal
from fastapi import (
    FastAPI,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    UploadFile,
    File,
    Form,
    Query,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func, or_, and_, text, update, cast, String, case
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field, ValidationError
from .db import get_db, SessionLocal
from .models import *
from .security import *
from . import schemas as s, finance as f, importing, ai, action_engine, reporting_xlsx, marketplace_pipeline, canonical, wb_weekly, marketplace_costs, marketplace_returns, marketplace_matching, marketplace_product_report, daily_reports
from .system_secrets import load_config, save_config, delete_config, SecretStorageError
from .connectors import AccessRequired, connector, load_saved_credentials
from cryptography.fernet import Fernet, InvalidToken
from .product_studio import assess_performance, next_experiment
from . import kaspi_integrity
from . import report_cache

APP_STARTED_AT = datetime.now(timezone.utc)

app = FastAPI(
    title="QOR Business ERP",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
from .whatsapp_inbound import router as whatsapp_inbound_router
app.include_router(whatsapp_inbound_router)
logger = logging.getLogger(__name__)
SYNC_RUNNING_TIMEOUT_SECONDS = max(60, int(os.getenv("MARKETPLACE_SYNC_TIMEOUT_SECONDS", "1800")))
KASPI_JOB_RECOVERY_GRACE_SECONDS = min(
    SYNC_RUNNING_TIMEOUT_SECONDS,
    max(60, int(os.getenv("KASPI_JOB_RECOVERY_GRACE_SECONDS", "300"))),
)
KASPI_API_HISTORY_DAYS = max(1, int(os.getenv("KASPI_API_HISTORY_DAYS", "370")))
CLAUDE_SKILL_INSTALL_LOCK = threading.Lock()


def _kaspi_sync_paused_for(account_id, start=None, end=None):
    raw = os.getenv("KASPI_PAUSE_ACCOUNT_IDS", "")
    try:
        paused_ids = {int(value.strip()) for value in raw.split(",") if value.strip()}
    except ValueError:
        logger.error("Invalid KASPI_PAUSE_ACCOUNT_IDS; pausing no accounts")
        return False
    if int(account_id) not in paused_ids:
        return False
    # Keep long archive scans paused while allowing bounded dashboard periods.
    # This covers today/yesterday/week/month but never resumes the old backfill.
    if start is not None and end is not None and end >= start and (end - start).days <= 31:
        return False
    return True


def _pause_kaspi_job(db, account):
    settings = dict(account.integration_settings or {})
    job = dict(settings.get("kaspi_period_job") or {})
    if job.get("status") in {"running", "retry"}:
        job.update(status="paused", paused_at=now().isoformat(),
                   pause_reason="Остановлено по запросу; сохранённый курсор оставлен")
        settings["kaspi_period_job"] = job
        account.integration_settings = settings
        account.sync_status = "partial"
        account.sync_error = "KASPI_PERIOD_PAUSED: сохранённый курсор оставлен"
        account.last_sync = now()
        db.add(account)


def sync_status_for_display(account, at=None):
    """Hide abandoned running states after the last persisted sync heartbeat."""
    if getattr(account, "channel", None) == "Kaspi" and _kaspi_sync_paused_for(getattr(account, "id", None)):
        return "paused", "Фоновый обход остановлен; сохранённый курсор оставлен."
    status = account.sync_status or "never"
    error = account.sync_error or ""
    if status.lower() != "running":
        return status, error
    heartbeat = account.last_sync
    if heartbeat is not None and heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    reference = at or now()
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    if heartbeat is None or heartbeat < reference - timedelta(seconds=SYNC_RUNNING_TIMEOUT_SECONDS):
        return "failed", "SYNC_TIMEOUT: синхронизация давно не обновлялась; запустите её повторно"
    return status, error


def kaspi_period_status_for_display(account, start, end, report_mode="issued", at=None):
    """Show the selected bounded report state even if the long archive is paused.

    Returns status, message, and the selected period's successful sync time.
    The generic integration status continues to describe the full archive.
    """
    status, error = sync_status_for_display(account, at)
    if (getattr(account, "channel", None) != "Kaspi"
            or not _kaspi_sync_paused_for(getattr(account, "id", None))):
        return status, error, None

    settings = dict(getattr(account, "integration_settings", None) or {})
    period_key = _kaspi_period_sync_key(report_mode, start, end)
    coverage = dict(settings.get("kaspi_period_sync") or {})
    if coverage.get(period_key):
        try:
            synced_at = datetime.fromisoformat(str(coverage[period_key]))
            if synced_at.tzinfo is None:
                synced_at = synced_at.replace(tzinfo=timezone.utc)
        except ValueError:
            synced_at = None
        return "done", "", synced_at

    job = dict(settings.get("kaspi_period_job") or {})
    same_period = (
        job.get("start") == str(start)
        and job.get("end") == str(end)
        and job.get("mode", "issued") == report_mode
    )
    if same_period and job.get("status") in {"running", "retry"}:
        heartbeat = getattr(account, "last_sync", None)
        reference = at or now()
        if heartbeat is not None and heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        if heartbeat is not None and heartbeat >= reference - timedelta(seconds=SYNC_RUNNING_TIMEOUT_SECONDS):
            return "running", "", heartbeat
    return status, error, None


def _kaspi_issued_scan_start(today_local):
    """Configured backfill horizon, not a claim about Kaspi retention limits."""
    return today_local - timedelta(days=KASPI_API_HISTORY_DAYS)


def _kaspi_period_sync_key(report_mode, start, end):
    return kaspi_integrity.period_key(report_mode, start, end)


def _require_complete_kaspi_report(summary):
    if summary.get("sync_in_progress") or summary.get("sync_status") == "running":
        raise HTTPException(409, "Kaspi ещё синхронизируется. Дождитесь завершения и скачайте отчёт повторно.")
    if summary.get("sync_status") != "done" or not summary.get("source_complete"):
        raise HTTPException(409, "Полная синхронизация Kaspi не подтверждена. Проверьте статус и повторите выгрузку.")


def _resume_kaspi_jobs_once():
    """Recover durable API-read jobs after a restart, with a cross-process lease."""
    tasks = []
    with SessionLocal() as db:
        accounts = list(db.scalars(select(Account).where(
            Account.channel == "Kaspi", Account.active.is_(True), Account.mode == "api")))
        for account in accounts:
            settings = dict(account.integration_settings or {})
            job = dict(settings.get("kaspi_period_job") or {})
            job_start = date.fromisoformat(job["start"]) if job.get("start") else None
            job_end = date.fromisoformat(job["end"]) if job.get("end") else None
            if _kaspi_sync_paused_for(account.id, job_start, job_end):
                _pause_kaspi_job(db, account)
                db.commit()
                continue
            heartbeat = account.last_sync
            if heartbeat is not None and heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=timezone.utc)
            if not job and account.sync_status == "running" and heartbeat and heartbeat > now()-timedelta(seconds=SYNC_RUNNING_TIMEOUT_SECONDS):
                continue
            # Optional, explicitly targeted one-time backfill. Configuration is
            # non-secret; API credentials remain in the existing encrypted store.
            target_ids = {int(x) for x in os.getenv("KASPI_BACKFILL_ACCOUNT_IDS", "").split(",") if x.strip().isdigit()}
            configured_start, configured_end = os.getenv("KASPI_BACKFILL_START"), os.getenv("KASPI_BACKFILL_END")
            if account.id in target_ids and configured_start and configured_end:
                start_day, end_day = date.fromisoformat(configured_start), date.fromisoformat(configured_end)
                if end_day < start_day or (end_day-start_day).days > 366:
                    raise ValueError("Invalid configured Kaspi backfill period")
                target_key = _kaspi_period_sync_key("issued", start_day, end_day)
                current_is_target = job.get("start") == str(start_day) and job.get("end") == str(end_day)
                target_complete = bool((settings.get("kaspi_period_sync") or {}).get(target_key))
                current_is_active = job.get("status") in {"running", "retry"}
                if not current_is_target and not target_complete:
                    if current_is_active:
                        handoff_grace = max(60, int(os.getenv("KASPI_TARGET_HANDOFF_GRACE_SECONDS", "60")))
                        if heartbeat and heartbeat > now()-timedelta(seconds=handoff_grace):
                            continue
                        # Pause the unrelated current period at its last durable
                        # cursor, then prioritize the explicitly configured
                        # customer period. Lease replacement prevents the old
                        # worker from committing a second page after this point.
                        paused = list(settings.get("kaspi_period_paused_jobs") or [])
                        if not any(x.get("start") == job.get("start") and x.get("end") == job.get("end")
                                   for x in paused):
                            paused.append({**job, "status":"paused", "paused_at":now().isoformat()})
                        settings["kaspi_period_paused_jobs"] = paused[-20:]
                    owner = db.scalar(select(User).where(User.active.is_(True), User.role == "Owner").order_by(User.id))
                    if owner:
                        # The saved cursor for this exact period is reused.
                        job = {"start":str(start_day),"end":str(end_day),"mode":"issued","user_id":owner.id,
                               "status":"retry","retry_at":now().isoformat(),"batches":0,"records":0}
            if job.get("status") not in {"running", "retry"}:
                continue
            if job["status"] == "running" and heartbeat and heartbeat > now()-timedelta(seconds=KASPI_JOB_RECOVERY_GRACE_SECONDS):
                continue
            if job["status"] == "retry" and datetime.fromisoformat(job["retry_at"]) > now():
                continue
            lease = "KASPI_PERIOD_SYNC:" + uuid.uuid4().hex
            job["status"] = "running"
            settings["kaspi_period_job"] = job
            claimed = db.execute(update(Account).where(
                Account.id == account.id, Account.sync_error == account.sync_error,
                Account.last_sync == account.last_sync if account.last_sync else Account.last_sync.is_(None),
            ).values(sync_status="running", sync_error=lease, last_sync=now(), integration_settings=settings))
            if claimed.rowcount == 1:
                tasks.append((account.id, job["user_id"], date.fromisoformat(job["start"]),
                              date.fromisoformat(job["end"]), [], job["mode"], job["mode"] == "issued", lease))
        db.commit()
    for task in tasks:
        _background_kaspi_period_sync(*task)


def _kaspi_job_loop():
    while True:
        try:
            _resume_kaspi_jobs_once()
        except Exception:
            logger.exception("Kaspi recovery scan failed")
        time.sleep(60)


@app.on_event("startup")
def start_kaspi_job_recovery():
    if not os.getenv("PYTEST_CURRENT_TEST"):
        threading.Thread(target=_kaspi_job_loop, name="kaspi-recovery", daemon=True).start()
WB_DEFAULT_SYNC_SECTIONS = ("new_orders", "order", "sale")
WB_ALLOWED_SYNC_SECTIONS = frozenset(("new_orders", "order", "sale", "realization", "stocks", "products", "order_statuses"))


def _wb_weekly_loop():
    """Check the most recently completed week on a bounded server-side cadence."""
    from . import wb_weekly
    while True:
        try:
            start, end = wb_weekly.previous_week()
            # Fetch only the last completed week. Older periods are user-selected;
            # an automatic catch-up loop would spend the seller's strict Finance API quota.
            with SessionLocal() as db:
                accounts = db.scalars(select(Account).where(Account.channel == "Wildberries", Account.mode == "api", Account.active.is_(True)).order_by(Account.id)).all()
                system_owner = db.scalar(select(User).where(User.role == "Owner", User.active.is_(True)).order_by(User.id))
                for account in accounts:
                    try:
                        credentials = load_saved_credentials(db, account.id)
                        if not credentials.get("token"):
                            continue
                        wb_weekly.sync_week(db, account, credentials["token"], start, end,
                                            project_user=system_owner, trigger="scheduler")
                    except Exception as exc:
                        db.rollback()
                        logger.warning("WB weekly check skipped for account %s (%s)", account.id, type(exc).__name__)
        except Exception:
            logger.exception("WB weekly scheduler cycle failed")
        time.sleep(max(300, int(os.getenv("WB_WEEKLY_CHECK_SECONDS", "1800"))))


@app.on_event("startup")
def start_wb_weekly_scheduler():
    # Each web worker has a small daemon loop; the report row lease/DB lock makes
    # concurrent checks safe across Render workers and repeated deployments.
    thread = threading.Thread(target=_wb_weekly_loop, name="wb-weekly-reports", daemon=True)
    thread.start()


def _dashboard_report_cache_loop():
    """Keep standard dashboard periods warm outside the user's request path."""
    while True:
        refreshed = False
        try:
            with SessionLocal() as db:
                refreshed = report_cache.refresh_one(db)
        except Exception:
            logger.exception("Dashboard report cache refresh failed")
        # Move through missing/stale periods steadily, then check again in the
        # background. Dashboard requests still calculate a bounded headline on a
        # cold cache; AI KPI requests no longer need the full historical report.
        time.sleep(1 if refreshed else 10)


@app.on_event("startup")
def start_dashboard_report_cache():
    # Docker Compose runs a dedicated persistent report-cache-worker. Keep the
    # in-process loop for single-service hosts such as Render, but avoid running
    # two refreshers against the same database on VPS deployments.
    enabled = os.getenv("QOR_INPROCESS_REPORT_CACHE", "1").strip().lower() not in {"0", "false", "no"}
    if enabled and not os.getenv("PYTEST_CURRENT_TEST"):
        threading.Thread(target=_dashboard_report_cache_loop,
                         name="dashboard-report-cache", daemon=True).start()


@app.post("/api/internal/daily-report/run")
def run_scheduled_daily_report(request: Request):
    """Private endpoint for the Render Cron service; never expose a token in the URL."""
    expected = os.getenv("QOR_DAILY_REPORT_TRIGGER_TOKEN", "").strip()
    supplied = request.headers.get("authorization", "")
    if not expected or not hmac.compare_digest(supplied, f"Bearer {expected}"):
        raise HTTPException(404, "Not found")
    daily = daily_reports.run_due_daily_reports()
    alerts = daily_reports.run_due_whatsapp_alerts()
    return {**daily, "whatsapp_alerts": alerts}


@app.middleware("http")
async def security_headers(request, call_next):
    if int(request.headers.get("content-length", "0") or 0) > 6 * 1024 * 1024:
        return JSONResponse({"detail": "Максимум 6 МБ"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = (
        "no-store" if request.url.path.startswith("/api") else "no-cache"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    )
    return response


@app.exception_handler(IntegrityError)
async def integrity_handler(request, exc):
    return JSONResponse(
        status_code=409,
        content={
            "detail": "Дубликат записи либо запись используется в других документах"
        },
    )


@app.exception_handler(ValidationError)
async def validation_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "message": "Проверьте заполнение полей.", "detail": "Проверьте заполнение полей."},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request, exc):
    """Keep Pydantic internals out of API responses and browser error surfaces."""
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "message": "Проверьте параметры запроса.", "detail": "Проверьте параметры запроса."},
    )


def dump(obj):
    if isinstance(obj, dict):
        return jsonable_encoder(obj)
    result = jsonable_encoder({
        c.name: getattr(obj, c.name)
        for c in obj.__table__.columns
        if c.name not in ("password_hash", "token_hash", "path", "rows")
    })
    if isinstance(obj,Sale) and obj.cogs_pending: result["cogs"]=None
    if isinstance(obj, Product):
        specs = obj.specifications or {}
        result["description"] = specs.get("description", "")
        result["barcode"] = specs.get("barcode", "")
        result["purchase_cost"] = int(specs.get("purchase_cost") or 0)
        result["custom_fields"] = specs.get("custom_fields") or {}
        result["marketplace_stock_allocations"] = specs.get("marketplace_stock_allocations") or {}
    if isinstance(obj, Account):
        result.pop("integration_settings", None)
    return result


class Login(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=128)


@app.post("/api/auth/login")
def login(p: Login, request: Request, response: Response, db=Depends(get_db)):
    identity = hashlib.sha256(
        (
            p.email.lower() + ":" + (request.client.host if request.client else "")
        ).encode()
    ).hexdigest()
    count = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.identity == identity,
            LoginAttempt.created_at > now() - timedelta(minutes=15),
        )
    )
    if count >= 8:
        raise HTTPException(429, "Слишком много попыток. Повторите через 15 минут")
    db.add(LoginAttempt(identity=identity))
    db.commit()
    u = db.scalar(select(User).where(User.email == p.email.lower()))
    if not u or not u.active or not passwords.verify(p.password, u.password_hash):
        raise HTTPException(401, "Неверный логин или пароль")
    token = secrets.token_urlsafe(48)
    db.add(
        Session(
            token_hash=digest(token),
            user_id=u.id,
            expires_at=now() + timedelta(hours=12),
        )
    )
    audit(db, u, "login", "users", u.id)
    db.commit()
    response.set_cookie(
        "erp_session",
        token,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "true").lower() == "true",
        samesite="strict",
        max_age=43200,
        path="/",
    )
    return {"user": dump(u), "csrf": token, "permissions": list(PERMISSIONS[u.role])}


@app.get("/api/auth/me")
def me(request: Request, u=Depends(current_user)):
    return {
        "user": dump(u),
        "csrf": request.cookies.get("erp_session"),
        "permissions": list(PERMISSIONS[u.role]),
    }


@app.post("/api/auth/logout")
def logout(
    request: Request, response: Response, u=Depends(current_user), db=Depends(get_db)
):
    sess = db.scalar(
        select(Session).where(
            Session.token_hash == digest(request.cookies["erp_session"])
        )
    )
    if sess:
        db.delete(sess)
    db.commit()
    response.delete_cookie("erp_session")
    return {"ok": True}


@app.post("/api/auth/password")
def change_password(payload: dict, u=Depends(current_user), db=Depends(get_db)):
    if not passwords.verify(str(payload.get("old", "")), u.password_hash):
        raise HTTPException(403, "Неверный текущий пароль")
    new = str(payload.get("new", ""))
    if len(new) < 12 or len(new) > 128:
        raise HTTPException(422, "Пароль от 12 до 128 символов")
    u.password_hash = passwords.hash(new)
    for sess in db.scalars(select(Session).where(Session.user_id == u.id)):
        db.delete(sess)
    audit(db, u, "change_password", "users", u.id)
    db.commit()
    return {"ok": True}




DOC_KIND_LABELS = {
    "contract": "Договор", "invoice": "Счёт", "waybill": "Накладная",
    "act": "Акт", "commercial_offer": "Коммерческое предложение",
    "payment_invoice": "Счёт на оплату",
}

@app.get("/api/generated-documents/{doc_id}/pdf")
def generated_document_pdf(doc_id: int, u=Depends(current_user), db=Depends(get_db)):
    require(u, "documents")
    doc = db.get(GeneratedDocument, doc_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    scope(u, doc.company_id)
    company = db.get(Company, doc.company_id)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        raise HTTPException(503, "PDF renderer unavailable")
    font = "Helvetica"
    for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"):
        if os.path.exists(candidate):
            pdfmetrics.registerFont(TTFont("QORUnicode", candidate)); font = "QORUnicode"; break
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42, title=f"{DOC_KIND_LABELS.get(doc.kind, doc.kind)} {doc.number}")
    styles = getSampleStyleSheet(); styles["Title"].fontName = font; styles["Normal"].fontName = font
    styles["Title"].alignment = TA_CENTER
    story = [Paragraph(DOC_KIND_LABELS.get(doc.kind, doc.kind), styles["Title"]), Spacer(1, 12)]
    rows = [
        ["Номер", doc.number], ["Дата", str(doc.date)], ["Компания", company.name if company else str(doc.company_id)],
        ["БИН/ИИН", company.bin if company else ""], ["Контрагент", doc.counterparty or "—"],
        ["Сумма", f"{doc.amount/100:,.2f} ₸".replace(",", " ")], ["Статус", doc.status],
    ]
    table = Table(rows, colWidths=[120, 350])
    table.setStyle(TableStyle([("FONTNAME", (0,0), (-1,-1), font), ("GRID", (0,0), (-1,-1), .4, colors.grey), ("BACKGROUND", (0,0), (0,-1), colors.whitesmoke), ("VALIGN", (0,0), (-1,-1), "TOP"), ("PADDING", (0,0), (-1,-1), 7)]))
    story += [table, Spacer(1, 16)]
    payload = doc.payload or {}
    if payload:
        story.append(Paragraph("Дополнительные данные", styles["Normal"])); story.append(Spacer(1, 6))
        extra = [[str(k), str(v)] for k,v in payload.items() if v not in (None, "", [], {})]
        if extra:
            t2 = Table(extra, colWidths=[150, 320]); t2.setStyle(TableStyle([("FONTNAME", (0,0), (-1,-1), font), ("GRID", (0,0), (-1,-1), .3, colors.lightgrey), ("VALIGN", (0,0), (-1,-1), "TOP"), ("PADDING", (0,0), (-1,-1), 6)])); story.append(t2)
    story += [Spacer(1, 24), Paragraph("Сформировано в QOR AI Business ERP. Перед подписанием документ должен быть проверен ответственным сотрудником.", styles["Normal"])]
    pdf.build(story); buf.seek(0)
    safe = "".join(c for c in doc.number if c.isalnum() or c in "-_") or str(doc.id)
    return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="QOR-{safe}.pdf"'})


@app.get("/api/health")
def health(db=Depends(get_db)):
    db.execute(select(1))
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        expected_revision = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception:
        expected_revision = revision = None
    if revision != expected_revision:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "ok", "migration": "incompatible"},
        )
    return {"status": "ok", "database": "ok", "migration": "compatible"}


MODELS = {
    "companies": (Company, "companies", s.CompanyIn),
    "products": (Product, "catalog", s.ProductIn),
    "accounts": (Account, "accounts", s.AccountIn),
    "customers": (Customer, "sales", s.CustomerIn),
    "purchases": (Purchase, "inventory", None),
    "batches": (Batch, "inventory", None),
    "movements": (Movement, "inventory", None),
    "sales": (Sale, "sales", None),
    "returns": (Return, "sales", None),
    "expenses": (Expense, "finance", None),
    "cash": (CashEntry, "finance", None),
    "documents": (Document, "documents", None),
    "audit": (Audit, "audit", None),
    "users": (User, "users", s.UserIn),
    "jobs": (Job, "documents", None),
    "imports": (ImportRun, "imports", None),
    "niches": (Niche, "marketing", s.NicheIn),
    "counterparties": (Counterparty, "finance", s.CounterpartyIn),
    "bank_transactions": (BankTransaction, "finance", s.BankTransactionIn),
    "tax_rules": (TaxRule, "finance", s.TaxRuleIn),
    "generated_documents": (GeneratedDocument, "documents", s.GeneratedDocumentIn),
}


def model_info(entity):
    if entity not in MODELS:
        raise HTTPException(404, "Раздел не найден")
    return MODELS[entity]


def access_query(db, u, entity, search="", company_id=None, account_id=None):
    model, cap, _ = model_info(entity)
    require(u, cap)
    q = scope_query(select(model), model, u)
    if entity == "companies" and u.role != "Owner":
        q = q.where(Company.id.in_(u.company_ids))
    if entity == "users" and u.role != "Owner":
        q = q.where(User.role != "Owner")
    if entity == "imports":
        q = q.where(ImportRun.user_id == u.id)
    if entity == "jobs":
        q = q.where(Job.user_id == u.id)
    # Archived marketplace accounts stay available in the account manager for
    # reconnecting, while their old sales and raw events leave active views.
    if entity == "sales":
        q = q.where(Sale.account_id.in_(select(Account.id).where(Account.active.is_(True))))
    elif entity == "returns":
        q = q.join(Sale, Return.sale_id == Sale.id).where(
            Sale.account_id.in_(select(Account.id).where(Account.active.is_(True)))
        )
    elif entity == "expenses":
        q = q.where(or_(Expense.account_id.is_(None), Expense.account_id.in_(select(Account.id).where(Account.active.is_(True)))))
    if company_id and entity == "products":
        scope(u, company_id)
        q = q.where(Product.id.in_(select(ProductCompany.product_id).where(
            ProductCompany.company_id == company_id
        )))
    elif company_id and hasattr(model, "company_id"):
        scope(u, company_id)
        q = q.where(model.company_id == company_id)
    if account_id and hasattr(model, "account_id"):
        q = q.where(model.account_id == account_id)
    if search:
        cols = [
            getattr(model, k)
            for k in (
                "name",
                "sku",
                "reference",
                "description",
                "email",
                "action",
                "supplier",
            )
            if hasattr(model, k)
        ]
        if cols:
            search_terms = [c.ilike("%" + search[:100] + "%") for c in cols]
            if entity == "products":
                search_terms.append(cast(Product.specifications, String).ilike("%" + search[:100] + "%"))
            q = q.where(or_(*search_terms))
    return q


@app.get("/api/marketplace-records")
def marketplace_records(
    channel: str | None = None,
    company_id: int | None = None,
    account_id: int | None = None,
    status: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    u=Depends(current_user),
    db=Depends(get_db),
):
    """Return idempotent raw/staged records received from marketplace APIs.

    Marketplace ORDER/POSTING records are intentionally not booked as financial
    sales until a confirmed sale/payment/return event with sufficient accounting
    data exists. This endpoint makes successful sync visible instead of hiding it
    behind the financial sales table.
    """
    q = select(MarketplaceRecord).join(Account, Account.id == MarketplaceRecord.account_id).where(Account.active.is_(True))
    if u.role != "Owner":
        q = q.where(MarketplaceRecord.company_id.in_(u.company_ids or []))
    if company_id is not None:
        scope(u, company_id)
        q = q.where(MarketplaceRecord.company_id == company_id)
    if channel:
        q = q.where(Account.channel == channel)
    if account_id is not None:
        q = q.where(MarketplaceRecord.account_id == account_id)
    if status:
        q = q.where(or_(MarketplaceRecord.status.startswith("pending"),MarketplaceRecord.stage_status.in_(["pending_fifo","pending_fx","pending_mapping"])) if status == "pending" else MarketplaceRecord.status == status)
    count = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows=[]
    for rec in db.scalars(q.order_by(MarketplaceRecord.id.desc()).offset(offset).limit(limit)):
        payload = rec.payload or {}
        # Presentation is enriched from the canonical product mapping. Marketplace
        # sales payloads (notably WB statistics) often carry sellerArticle/nmId
        # but omit a human product name even though the catalogue endpoint has it.
        # Do not force users to re-map data that QOR already mapped during projection.
        display_product = None
        display_keys = marketplace_pipeline.identifiers(payload)
        if display_keys:
            mapped_ids = db.scalars(select(MarketplaceProductMapping.product_id).where(
                MarketplaceProductMapping.account_id == rec.account_id,
                MarketplaceProductMapping.company_id == rec.company_id,
                MarketplaceProductMapping.external_key.in_(display_keys)
            )).all()
            unique_ids = list(dict.fromkeys(mapped_ids))
            if len(unique_ids) == 1:
                display_product = db.get(Product, unique_ids[0])
        inferred_quantity = payload.get("quantity")
        if inferred_quantity is None and rec.source == "wildberries" and payload.get("record_type") == "sale":
            inferred_quantity = 1
        rows.append({
            "id": rec.id, "account_id": rec.account_id, "company_id": rec.company_id,
            "source": rec.source, "external_id": rec.external_id, "status": rec.status,
            "stage_status":rec.stage_status,"reason_code":rec.reason_code,
            "created_at": rec.created_at,
            "marketplace_status": payload.get("status") or payload.get("state") or payload.get("substatus") or "received",
            "reference": payload.get("code") or payload.get("posting_number") or payload.get("rid") or rec.external_id,
            "amount": next((payload[k] for k in ("total_price", "retailPriceWithDisc", "priceWithDisc", "finishedPrice", "amount", "retail_amount") if payload.get(k) is not None), None),
            "product_name": payload.get("product_name") or payload.get("name") or payload.get("title") or payload.get("subjectName") or ((payload.get("products") or [{}])[0].get("name") if payload.get("products") else None) or (display_product.name if display_product else None),
            "sku": payload.get("supplierArticle") or payload.get("vendorCode") or payload.get("offer_id") or payload.get("sku") or payload.get("nmId") or ((payload.get("products") or [{}])[0].get("offer_id") if payload.get("products") else None),
            "currency": payload.get("currency") or payload.get("currency_code") or ((payload.get("products") or [{}])[0].get("currency_code") if payload.get("products") else None) or ("KZT" if rec.source == "kaspi" else "RUB"),
            "quantity": inferred_quantity or sum(int(x.get("quantity") or 0) for x in (payload.get("products") or [])) or None,
            "projection_reason": payload.get("_qor_projection_reason", ""),
            "external_keys": list(dict.fromkeys(marketplace_pipeline.identifiers(payload) + [key for x in payload.get("products", []) for key in marketplace_pipeline.identifiers(x)])),
            "payload": payload,
        })
    return {"items": jsonable_encoder(rows), "total": count}


@app.get("/api/marketplace-orders")
def marketplace_orders_report(channel: str = Query(...), company_id: int | None = None,
    account_id: int | None = None, status_filter: str = "all",
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
    u=Depends(current_user), db=Depends(get_db)):
    """Marketplace order lifecycle view; values are operational, not booked cash."""
    require(u, "analytics")
    if channel not in ("Kaspi", "Wildberries"): raise HTTPException(422, "Поддерживаются Kaspi и Wildberries")
    aq=select(Account).where(Account.channel==channel,Account.active.is_(True))
    if u.role!="Owner": aq=aq.where(Account.company_id.in_(u.company_ids or []))
    if company_id is not None: scope(u,company_id); aq=aq.where(Account.company_id==company_id)
    if account_id is not None: aq=aq.where(Account.id==account_id)
    accounts=list(db.scalars(aq)); aids=[a.id for a in accounts]
    if not aids: return {"items":[],"total":0,"summary":{},"stores":[]}
    types=("order","order_entry") if channel=="Kaspi" else ("assembly_order","new_order","realization")
    records=list(db.scalars(select(MarketplaceRecord).where(MarketplaceRecord.account_id.in_(aids),
        MarketplaceRecord.payload["record_type"].as_string().in_(types)).order_by(MarketplaceRecord.id.desc())))
    accs={a.id:a for a in accounts}; rows=[]
    if channel=="Kaspi":
        orders={}; lines={}
        for rec in records:
            p=rec.payload or {}; oid=str(p.get("order_id") or "")
            if p.get("record_type")=="order": orders[(rec.account_id,oid)]=(rec,p)
            elif p.get("record_type")=="order_entry": lines.setdefault((rec.account_id,oid),[]).append(p)
        names={"APPROVED_BY_BANK":"Ожидает продавца","ACCEPTED_BY_MERCHANT":"Принят продавцом","COMPLETED":"Выдан покупателю","CANCELLED":"Отменён","CANCELLING":"Отмена в процессе","KASPI_DELIVERY_RETURN_REQUESTED":"Запрошен возврат","RETURNED":"Возвращён"}
        for (aid,oid),(rec,p) in orders.items():
            st=str(p.get("status") or ""); state=str(p.get("state") or "")
            label=names.get(st,st or "Статус не передан")
            if st=="ACCEPTED_BY_MERCHANT" and state: label += " · "+("Kaspi доставка" if state=="KASPI_DELIVERY" else "доставка продавца" if state=="DELIVERY" else state)
            group="returns" if st in ("CANCELLING","KASPI_DELIVERY_RETURN_REQUESTED","RETURNED") else "canceled" if st=="CANCELLED" else "delivered" if st=="COMPLETED" else "in_delivery" if st=="ACCEPTED_BY_MERCHANT" else "waiting"
            for line in lines.get((aid,oid)) or [None]:
                l=line or {}; rows.append({"account_id":aid,"store":accs[aid].name,"order_id":oid,"date":p.get("creation_date"),"product":l.get("product_name") or "—","sku":l.get("sku") or "","quantity":l.get("quantity"),"amount":l.get("total_price") or p.get("total_price"),"status":label,"group":group,"erp_status":"Проведено в ERP" if rec.status=="projected" else ("Ожидает проведения в ERP" if st=="COMPLETED" else "Не проводится до завершения заказа"),"finance_status":"Kaspi API заказа не подтверждает денежное зачисление","finance_amount":None})
    else:
        orders={}; finance={}
        for rec in records:
            p=rec.payload or {}; typ=p.get("record_type")
            if typ in ("assembly_order","new_order"):
                key=(rec.account_id,str(p.get("id") or p.get("rid") or ""))
                if typ=="assembly_order" or key not in orders: orders[key]=(rec,p)
            elif typ=="realization":
                k=str(p.get("srid") or p.get("rid") or "")
                if k: finance[(rec.account_id,k)]=p
        sup={"new":"Новый заказ","confirm":"Подтверждён, сборка","complete":"Передан в доставку","cancel":"Отменён продавцом","cancel_carrier":"Отменён перевозчиком"}
        wb={"waiting":"Ожидает передачи WB","sorted":"Сортируется","sold":"Выкуплен","canceled":"Отменён","canceled_by_client":"Отменён клиентом","declined_by_client":"Отклонён клиентом","defect":"Брак","ready_for_pickup":"В ПВЗ, ждёт покупателя","postponed_delivery":"Доставка перенесена","accepted_by_carrier":"Принят перевозчиком","sent_to_carrier":"Передан перевозчику","canceled_by_carrier":"Отменён перевозчиком"}
        for (aid,oid),(rec,p) in orders.items():
            s=str(p.get("supplierStatus") or ""); w=str(p.get("wbStatus") or ""); label=wb.get(w) or sup.get(s) or "Статус пока не передан"
            group="returns" if w=="defect" else "canceled" if "cancel" in (w or s) else "delivered" if w in ("sold","ready_for_pickup") else "in_delivery" if w in ("sorted","accepted_by_carrier","sent_to_carrier","postponed_delivery") or s=="complete" else "waiting"
            fp=finance.get((aid,str(p.get("rid") or "")))
            rows.append({"account_id":aid,"store":accs[aid].name,"order_id":str(p.get("id") or oid),"date":p.get("createdAt"),"product":p.get("article") or "—","sku":", ".join(map(str,p.get("skus") or [])),"quantity":1,"amount":None,"status":label,"group":group,"erp_status":"Заказ не считается продажей до подтверждения финансовой строки","finance_status":"Строка отчёта WB найдена" if fp else ("Ожидает строки финансового отчёта WB" if group=="delivered" else "Нет финансовой строки"),"finance_amount":(fp.get("forPay") or fp.get("ppvzForPay") or fp.get("retailAmount")) if fp else None})
    summary={k:sum(1 for r in rows if r["group"]==k) for k in ("in_delivery","delivered","waiting","canceled","returns")}
    if status_filter!="all": rows=[r for r in rows if r["group"]==status_filter]
    rows.sort(key=lambda r:str(r.get("date") or ""),reverse=True); total=len(rows)
    return {"items":rows[offset:offset+limit],"total":total,"summary":summary,"stores":[{"id":a.id,"name":a.name,"sync_status":a.sync_status,"last_sync":a.last_sync} for a in accounts]}


@app.get("/api/marketplace-products")
def marketplace_products(channel: str, company_id: int | None = None, account_id: int | None = None, start: date | None = None, end: date | None = None, limit: int = Query(100, ge=1, le=500), u=Depends(current_user), db=Depends(get_db)):
    """Fast catalogue cards. Avoid N+1 queries and never recalculate the whole ERP report."""
    if channel not in {"Kaspi", "Wildberries", "Ozon"}:
        raise HTTPException(422, "Неподдерживаемый маркетплейс")
    aq = select(Account).where(Account.channel == channel, Account.active.is_(True))
    if u.role != "Owner": aq = aq.where(Account.company_id.in_(u.company_ids or []))
    if company_id is not None:
        scope(u, company_id); aq = aq.where(Account.company_id == company_id)
    accounts = list(db.scalars(aq)); account_ids = [a.id for a in accounts]
    account_by_id = {a.id: a for a in accounts}
    if account_id is not None:
        if account_id not in account_by_id: raise HTTPException(404, "Кабинет маркетплейса не найден")
        account_ids = [account_id]
        account_by_id = {account_id: account_by_id[account_id]}
    if not account_ids: return {"items": [], "total": 0}

    mappings = list(db.scalars(select(MarketplaceProductMapping).where(MarketplaceProductMapping.account_id.in_(account_ids))))
    by_product = {}
    account_keys = {}
    for m in mappings:
        by_product.setdefault(m.product_id, set()).add(m.external_key)
        account_keys.setdefault((m.product_id, m.account_id), set()).add(m.external_key)
    product_ids = list(by_product)[:limit]
    if not product_ids:
        # Kaspi can return products attached to orders even when the seller has
        # not linked them to an ERP product yet. Keep those visible as observed
        # marketplace items instead of showing an empty catalogue.
        if channel == "Kaspi":
            observed = {}
            raw_q = select(MarketplaceRecord.account_id, MarketplaceRecord.payload).where(
                MarketplaceRecord.account_id.in_(account_ids), MarketplaceRecord.source == "kaspi",
                MarketplaceRecord.payload["record_type"].as_string() == "order_entry")
            for account_id, payload in db.execute(raw_q):
                p = payload or {}
                try:
                    day = marketplace_pipeline._day(p.get("order_creation_date"))
                    if start is not None and day < start: continue
                    if end is not None and day > end: continue
                except (ValueError, TypeError, KeyError):
                    day = None
                attrs = p.get("merchant_product_attributes") or p.get("product_attributes") or {}
                external = str(p.get("external_product_id") or p.get("sku") or p.get("product_name") or p.get("external_id"))
                images = marketplace_pipeline._media_urls(p)
                row = observed.setdefault(external, {"id":"kaspi:"+external,"sku":p.get("sku"),"article":p.get("sku"),
                    "name":p.get("product_name") or attrs.get("name") or "Kaspi товар",
                    "brand":attrs.get("brand"),"category":attrs.get("category"),"image_url":images[0] if images else None,
                    "images":images,"account_id":account_id,"account_name":account_by_id[account_id].name,"currency":getattr(account_by_id[account_id], "currency", None) or "KZT","sold_units":0,"revenue":0,
                    "lifetime_sold_units":0,"lifetime_revenue":0,"unconverted_sales":0,"cogs":0,"commission":0,
                    "logistics":0,"advertising":0,"profit":None,"stock_quantity":None,"specifications":{},
                    "source":"Kaspi order items"})
                try:
                    qty = int(p.get("quantity") or 0)
                    amount = float(p.get("total_price") or 0)
                except (TypeError, ValueError):
                    qty, amount = 0, 0
                row["lifetime_sold_units"] += qty
                row["lifetime_revenue"] += amount
                if (start is None or day is None or day >= start) and (end is None or day is None or day <= end):
                    row["sold_units"] += qty
                    row["revenue"] += amount
            rows = sorted(observed.values(), key=lambda x:(x["revenue"],x["sold_units"]), reverse=True)[:limit]
            return {"items":jsonable_encoder(rows),"total":len(observed),"catalog_scope":"products appearing in synced orders"}
        return {"items": [], "total": 0}
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(product_ids)))}
    sales = list(db.scalars(select(Sale).where(Sale.product_id.in_(product_ids), Sale.account_id.in_(account_ids))))
    sales_by_product = {}
    for sale in sales: sales_by_product.setdefault(sale.product_id, []).append(sale)

    # Build external-key -> product once, then scan WB sale records once. This
    # replaces product_count × raw_record_count work from the old endpoint.
    key_to_pid = {}
    for pid, keys in by_product.items():
        for key in keys: key_to_pid[str(key)] = pid
    wb_stats = {pid: {"pq": 0, "pr": 0, "lq": 0, "lr": 0, "bad": 0} for pid in product_ids}
    if channel == "Wildberries":
        raw_q = select(MarketplaceRecord.account_id, MarketplaceRecord.payload).where(
            MarketplaceRecord.account_id.in_(account_ids), MarketplaceRecord.source == "wildberries")
        for account_id, payload in db.execute(raw_q):
            p = payload or {}
            if str(p.get("record_type") or "").lower() != "sale": continue
            if str(p.get("saleID") or p.get("saleId") or "").upper().startswith("R") or p.get("isStorno"): continue
            pid = next((key_to_pid.get(str(k)) for k in marketplace_pipeline.identifiers(p) if str(k) in key_to_pid), None)
            if pid is None or pid not in wb_stats: continue
            st = wb_stats[pid]
            try:
                day = marketplace_pipeline._day(p.get("date"))
                amount = p.get("priceWithDisc") if p.get("priceWithDisc") is not None else p.get("finishedPrice")
                value = marketplace_pipeline._cents(amount, account_by_id[account_id], p.get("currency") or "RUB", db, p.get("date"))
            except (marketplace_pipeline.Pending, ValueError, TypeError, KeyError):
                st["bad"] += 1; continue
            st["lq"] += 1; st["lr"] += value
            if (start is None or day >= start) and (end is None or day <= end):
                st["pq"] += 1; st["pr"] += value

    out = []
    for pid in product_ids:
        product = products.get(pid)
        if not product: continue
        all_sales = sales_by_product.get(pid, [])
        period_sales = [x for x in all_sales if (start is None or x.date >= start) and (end is None or x.date <= end)]
        sale_costs, _, pending_ids = marketplace_costs.resolve_cost_overrides(db, period_sales, [], account_by_id)
        cogs = sum(sale_costs.get(x.id, x.cogs) for x in period_sales); commission = sum(x.commission for x in period_sales)
        logistics = sum(x.logistics for x in period_sales); advertising = sum(x.advertising for x in period_sales)
        if channel == "Wildberries":
            st = wb_stats[pid]; period_qty, period_revenue = st["pq"], st["pr"]
            lifetime_qty, lifetime_revenue, unconverted = st["lq"], st["lr"], st["bad"]
        else:
            period_qty = sum(x.quantity for x in period_sales); period_revenue = sum(x.revenue for x in period_sales)
            lifetime_qty = sum(x.quantity for x in all_sales); lifetime_revenue = sum(x.revenue for x in all_sales); unconverted = 0
        sku_specs = product.specifications or {}
        sku_unit_cost = int(sku_specs.get("purchase_cost") or 0)
        legacy_cost = marketplace_costs.latest_cost(db, account_ids[0], account_keys.get((pid, account_ids[0]), set()), end or business_today())
        effective_history = [x for x in (sku_specs.get("purchase_cost_history") or []) if isinstance(x, dict)]
        cost_day = end or business_today()
        dated_sku_costs = []
        for item in effective_history:
            try:
                effective = date.fromisoformat(str(item.get("effective_from")))
                unit_cost = int(item.get("unit_cost"))
                if effective <= cost_day:
                    dated_sku_costs.append((effective, unit_cost))
            except (AttributeError, TypeError, ValueError):
                continue
        sku_cost_at_period = max(dated_sku_costs, default=(None, sku_unit_cost), key=lambda item: item[0] or date.min)[1]
        sku_cost_history_applies = bool(dated_sku_costs)
        legacy_cost_applies = not sku_cost_history_applies and sku_unit_cost <= 0
        out.append({"id": product.id, "sku": product.sku, "article": product.article, "name": product.name, "brand": product.brand, "category": product.category,
            "image_url": (product.media or [None])[0], "images": product.media or [], "price": product.price, "currency": product.currency,
            "sold_units": period_qty, "revenue": period_revenue, "lifetime_sold_units": lifetime_qty, "lifetime_revenue": lifetime_revenue, "unconverted_sales": unconverted,
            "cogs": cogs, "commission": commission, "logistics": logistics, "advertising": advertising,
            "profit": None if any(x.id in pending_ids for x in period_sales) else sum(x.revenue for x in period_sales)-cogs-commission-logistics-advertising,
            "account_id": account_ids[0],
            # SKU purchase cost is the normal entry point. Legacy account-specific
            # history remains a read-only fallback for earlier sales.
            "unit_cost": (sku_cost_at_period if sku_cost_at_period > 0 else None) if sku_cost_history_applies else (legacy_cost.unit_cost if legacy_cost_applies and legacy_cost else (sku_unit_cost or None)),
            "cost_source": "SKU" if sku_cost_history_applies or sku_unit_cost else ("история кабинета" if legacy_cost_applies and legacy_cost else None),
            "cost_effective_from": str(max(dated_sku_costs, key=lambda item: item[0])[0]) if dated_sku_costs else (str(legacy_cost.effective_from) if legacy_cost_applies and legacy_cost else None),
            "stock_quantity": sum(int(v.get("quantity") or 0) for k,v in ((product.specifications or {}).get("marketplace_stock") or {}).items() if k.startswith(channel+":")),
            "specifications": product.specifications or {}})
    out.sort(key=lambda x: (x["revenue"], x["sold_units"]), reverse=True)
    return {"items": jsonable_encoder(out), "total": len(out)}



@app.put("/api/marketplace-products/cost")
def marketplace_product_cost_save(payload: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u, "finance", True)
    try:
        account_id = int(payload.get("account_id"))
        product_id = int(payload.get("product_id"))
        unit_cost = Decimal(str(payload.get("unit_cost"))).quantize(Decimal("0.01"))
        effective_from = date.fromisoformat(str(payload.get("effective_from")))
    except (TypeError, ValueError, ArithmeticError):
        raise HTTPException(422, "Укажите кабинет, себестоимость и дату начала действия")
    if not unit_cost.is_finite() or unit_cost <= 0 or unit_cost > Decimal("1000000000000"):
        raise HTTPException(422, "Себестоимость должна быть больше нуля")
    account = db.get(Account, account_id)
    product = db.get(Product, product_id)
    if not account or account.channel not in {"Kaspi", "Wildberries", "Ozon"} or not product:
        raise HTTPException(404, "Товар или кабинет маркетплейса не найден")
    scope_product(db, u, product.id, account.company_id)
    mappings = db.scalars(select(MarketplaceProductMapping).where(
        MarketplaceProductMapping.account_id == account.id,
        MarketplaceProductMapping.company_id == account.company_id,
        MarketplaceProductMapping.product_id == product.id,
    )).all()
    if not mappings:
        raise HTTPException(422, "Сначала свяжите карточку Kaspi с товаром ERP")
    amount = int(unit_cost * 100)
    for mapping in mappings:
        row = db.scalar(select(MarketplaceProductCost).where(
            MarketplaceProductCost.account_id == account.id,
            MarketplaceProductCost.external_key == mapping.external_key,
            MarketplaceProductCost.effective_from == effective_from,
        ))
        if row:
            row.unit_cost, row.updated_by = amount, u.id
        else:
            db.add(MarketplaceProductCost(
                company_id=account.company_id, account_id=account.id, external_key=mapping.external_key,
                product_name=product.name, unit_cost=amount, currency="KZT",
                effective_from=effective_from, updated_by=u.id,
            ))
    db.flush()
    audit(db, u, "update", "marketplace_product_costs", product.id, {
        "account_id": account.id, "product_id": product.id, "unit_cost": str(unit_cost),
        "effective_from": str(effective_from), "external_keys": [m.external_key for m in mappings],
    })
    db.commit()
    return {"saved": True, "account_id": account.id, "product_id": product.id,
            "unit_cost": str(unit_cost), "effective_from": str(effective_from)}


def _kaspi_commission_estimate(sales, expenses, api_bases, configured_rate=None):
    """Estimate missing Kaspi commission only from completed API order entries.

    A normal ERP Sale does not prove that Kaspi marked the order as issued.
    Explicit commission data for the same account/day takes precedence.
    """
    from decimal import Decimal, InvalidOperation

    raw_rate = configured_rate if configured_rate is not None else os.getenv("KASPI_COMMISSION_RATE")
    if raw_rate in (None, ""):
        return 0, None, False
    try:
        rate = Decimal(str(raw_rate))
        if not rate.is_finite() or rate < 0 or rate > 1:
            raise InvalidOperation
    except (InvalidOperation, ValueError, TypeError):
        return 0, None, False
    basis_points = int(rate * 10000)
    explicit_days = {
        (expense.account_id, expense.date)
        for expense in expenses
        if expense.category in {"Marketplace commission", "Marketplace commission VAT"}
    }
    sale_commission_days = {
        (sale.account_id, sale.date) for sale in sales if sale.commission > 0
    }
    actual_accounts = {account_id for account_id, _day in explicit_days | sale_commission_days}
    skipped = explicit_days | sale_commission_days
    estimated = 0
    suppressed = False
    for key, base in api_bases.items():
        if key in skipped:
            continue
        amount = (max(0, int(base or 0)) * basis_points + 5000) // 10000
        if key[0] in actual_accounts:
            suppressed = suppressed or amount > 0
        else:
            estimated += amount
    return estimated, str(rate), suppressed


def _return_statement_mapping(headers):
    aliases = {
        "external_return_id": ("return_id", "id возврата", "номер возврата", "rrd_id", "rrdid", "идентификатор операции", "operation id"),
        "external_order_id": ("order_id", "order", "заказ", "номер заказа", "номер исходного заказа", "srid", "тапсырыс №"),

        "financial_return_date": ("return date", "дата возврата", "дата возврата (алматы)", "дата операции", "rrd_date", "rrddate", "дата выплаты"),

        "amount": ("refund", "refund amount", "сумма возврата", "сумма операции", "сатып алушыға қайтарылған сома, ₸", "amount", "forpay"),
        "return_delivery_cost": ("kaspi ұстаған доставка = шығын, ₸", "расход доставки возврата", "return delivery cost"),

        "sku": ("sku", "артикул продавца", "vendorcode", "vendor code", "артикул", "тауар коду"),

        "product_name": ("товар", "название товара", "наименование", "product name"),
        "quantity": ("количество", "quantity", "шт.", "дана"),

        "reason": ("причина", "причина возврата", "reason"),
        "currency": ("валюта", "currency"),
    }
    normalized = {str(h).strip().lower().replace(" ", "_"): h for h in headers}
    result = {}
    for field, variants in aliases.items():
        for header in headers:
            key = str(header).strip().lower()
            if key in variants or key.replace(" ", "_") in variants:
                result[field] = header
                break
        if field not in result:
            for variant in variants:
                if variant.replace(" ", "_") in normalized:
                    result[field] = normalized[variant.replace(" ", "_")]
                    break
    return result




def _parse_kaspi_cabinet_returns(raw, filename, channel):
    """Read only the Kaspi cabinet's dedicated returns worksheet; omit buyer/city columns."""
    if channel != "Kaspi" or not (filename or "").lower().endswith(".xlsx"):
        return None
    try:
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        target = next((name for name in workbook.sheetnames
                       if re.sub(r"[^a-zа-яәіңғүұқөһ]", "", name.casefold()) in {"возвраттар", "возвраты", "returns"}), None)
        if not target:
            return None
        sheet = workbook[target]
        iterator = sheet.iter_rows(values_only=True)
        first = next(iterator, None)
        if not first:
            raise ValueError("Лист возвратов пуст")
        headers = [str(value).strip() if value is not None else "" for value in first]
        mapping = _return_statement_mapping(headers)
        required = ("external_order_id", "financial_return_date", "amount", "sku", "quantity")
        if any(key not in mapping for key in required):
            raise ValueError("На листе возвратов не найдены заказ, дата, сумма, SKU или количество")
        selected_fields = (*required, "product_name", "return_delivery_cost")
        selected_headers = [mapping[key] for key in selected_fields if mapping.get(key)]
        rows = []
        for source_row_number, values in enumerate(iterator, start=2):
            raw_row = {headers[index]: values[index] for index in range(min(len(headers), len(values))) if headers[index]}
            order_value = raw_row.get(mapping["external_order_id"])
            if order_value is None or not str(order_value).strip() or not str(order_value).strip().isdigit():
                # Exclude the workbook's БАРЛЫҒЫ row and explanatory notes.
                continue
            row = {header: raw_row.get(header) for header in selected_headers}
            row["_source_row_number"] = source_row_number
            rows.append(row)
        workbook.close()
        return selected_headers, rows, target
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Не удалось безопасно прочитать лист возвратов XLSX") from exc


@app.post("/api/marketplace-returns/financial-statement/preview")
async def preview_return_financial_statement(account_id: int = Form(...), file: UploadFile = File(...),
                                              u=Depends(current_user), db=Depends(get_db)):
    require(u, "finance")
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Магазин не найден")
    scope(u, account.company_id)
    if account.channel not in {"Kaspi", "Wildberries", "Ozon"}:
        raise HTTPException(422, "Выписку нужно связать с аккаунтом маркетплейса")
    if account.settlement_currency != "KZT":
        raise HTTPException(422, "Импорт суммы пока поддерживает только выписку в KZT")
    raw = await file.read()
    try:
        cabinet = _parse_kaspi_cabinet_returns(raw, file.filename or "statement.xlsx", account.channel)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if cabinet:
        headers, rows, sheet_name = cabinet
        return {"headers": headers, "sample": rows[:8], "row_count": len(rows),
                "suggested_mapping": _return_statement_mapping(headers),
                "kaspi_cabinet_returns": True, "sheet_name": sheet_name,
                "generated_return_id": True,
                "note": "Найдена детализация возвратов из кабинета Kaspi. Будут импортированы фактические даты, суммы и расходы обратной доставки; город и другие лишние данные не читаются."}
    headers, rows = importing.parse_file(raw, file.filename or "statement.xlsx")
    return {"headers": headers, "sample": rows[:8], "row_count": len(rows),
            "suggested_mapping": _return_statement_mapping(headers),
            "note": "Предпросмотр не меняет данные. Финансовый возврат появится только после явного импорта с датой и суммой."}


@app.post("/api/marketplace-returns/financial-statement/import")
async def import_return_financial_statement(account_id: int = Form(...), mapping: str = Form(...),
                                            file: UploadFile = File(...), u=Depends(current_user),
                                            db=Depends(get_db)):
    require(u, "finance", True)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Магазин не найден")
    scope(u, account.company_id)
    if account.channel not in {"Kaspi", "Wildberries", "Ozon"}:
        raise HTTPException(422, "Выписку нужно связать с аккаунтом маркетплейса")
    if account.settlement_currency != "KZT":
        raise HTTPException(422, "Импорт суммы пока поддерживает только выписку в KZT")
    try:
        column_map = json.loads(mapping)
    except (ValueError, TypeError):
        raise HTTPException(422, "Настройте сопоставление колонок")
    raw = await file.read()
    try:
        cabinet = _parse_kaspi_cabinet_returns(raw, file.filename or "statement.xlsx", account.channel)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    is_cabinet_returns = bool(cabinet)
    required_fields = {"external_order_id", "financial_return_date", "amount"}
    if not is_cabinet_returns:
        required_fields.add("external_return_id")
    if not isinstance(column_map, dict) or not required_fields.issubset(column_map) or any(not column_map.get(k) for k in required_fields):
        raise HTTPException(422, "Укажите исходный заказ, дату фактического возврата и сумму; для обычной выписки также нужен ID операции")
    if is_cabinet_returns:
        headers, source_rows, sheet_name = cabinet
    else:
        headers, source_rows = importing.parse_file(raw, file.filename or "statement.xlsx")
    if any(value not in headers for value in column_map.values() if value):
        raise HTTPException(422, "Сопоставление содержит колонку, которой нет в файле")
    from decimal import Decimal, InvalidOperation
    imported = updated = skipped = 0
    errors = []
    for row_number, source_row in enumerate(source_rows, start=2):
        mapped = {field: source_row.get(column) for field, column in column_map.items()}
        operation_id = str(mapped.get("external_return_id") or "").strip()
        order_id = str(mapped.get("external_order_id") or "").strip()
        if is_cabinet_returns and not operation_id:
            row_key = "|".join(str(mapped.get(key) or "") for key in (
                "external_order_id", "financial_return_date", "sku", "quantity", "amount"))
            operation_id = "cabinet:" + hashlib.sha256(
                f"{account.id}|{row_key}|{source_row.get('_source_row_number', row_number)}".encode("utf-8")
            ).hexdigest()[:48]
        day = importing._date(mapped.get("financial_return_date"))
        try:
            operation_day = date.fromisoformat(str(day))
            amount_decimal = Decimal(str(mapped.get("amount") or "").replace("\u00a0", "").replace("\u202f", "").replace(" ", "").replace(",", "."))
            amount = int((abs(amount_decimal) * 100).quantize(Decimal("1")))
            quantity = int(str(mapped.get("quantity") or "1").strip())
        except (ValueError, TypeError, InvalidOperation, OverflowError):
            errors.append({"row": row_number, "message": "Не удалось прочитать дату, сумму или количество"})
            continue
        if (not is_cabinet_returns and not operation_id) or not order_id or amount <= 0 or quantity <= 0:
            errors.append({"row": row_number, "message": "Нужны исходный заказ, положительная сумма и количество; ID операции требуется только для обычной выписки"})
            continue
        row_currency = str(mapped.get("currency") or "KZT").strip().upper()
        if row_currency not in {"KZT", "₸", "ТЕНГЕ", "ТГ"}:
            errors.append({"row": row_number, "message": "Поддерживается только выписка в KZT; конвертация валют не выполняется"})
            continue
        sku = str(mapped.get("sku") or "").strip()
        product_name = str(mapped.get("product_name") or "").strip()
        source = "kaspi_cabinet_returns" if is_cabinet_returns else "financial_statement_import"
        # Prefer linking to a single existing status observation by exact order
        # and SKU. Ambiguous or absent matches remain independent, auditable rows.
        existing = db.scalar(select(MarketplaceReturn).where(
            MarketplaceReturn.account_id == account.id,
            MarketplaceReturn.raw_data["financial_statement_return_id"].as_string() == operation_id,
        ))
        if existing is None:
            existing = db.scalar(select(MarketplaceReturn).where(
                MarketplaceReturn.account_id == account.id,
                MarketplaceReturn.source == source,
                MarketplaceReturn.external_return_id == operation_id,
            ))
        if existing is None:
            candidate_q = select(MarketplaceReturn).where(
                MarketplaceReturn.account_id == account.id,
                MarketplaceReturn.external_order_id == order_id,
                MarketplaceReturn.financial_status != "confirmed",
            )
            if sku: candidate_q = candidate_q.where(MarketplaceReturn.sku == sku)
            candidates = list(db.scalars(candidate_q.limit(2)))
            if len(candidates) == 1:
                existing = candidates[0]
        product_mapping = db.scalar(select(MarketplaceProductMapping).where(
            MarketplaceProductMapping.account_id == account.id,
            MarketplaceProductMapping.external_key.in_([sku, f"sku:{sku}"]),
        )) if sku else None
        product = db.get(Product, product_mapping.product_id) if product_mapping else None
        media = (product.media or []) if product else []
        if existing is None:
            existing = MarketplaceReturn(company_id=account.company_id, account_id=account.id,
                marketplace=account.channel, source=source, external_return_id=operation_id,
                external_order_id=order_id, detected_date=datetime.now(ZoneInfo("Asia/Almaty")).date(),
                accounted_status="unverified", return_status="financial_return_confirmed")
            db.add(existing)
            db.flush()
            db.add(MarketplaceReturnAudit(return_id=existing.id, user_id=u.id,
                action="financial_statement_imported", details={"source_file": (file.filename or "")[:160], "operation_id": operation_id}))
            imported += 1
        else:
            updated += 1
            db.add(MarketplaceReturnAudit(return_id=existing.id, user_id=u.id,
                action="financial_statement_matched", details={"source_file": (file.filename or "")[:160], "operation_id": operation_id}))
        existing.external_order_id = order_id
        existing.product_id = product.id if product else existing.product_id
        existing.product_name = product_name or (product.name if product else existing.product_name or "")
        existing.sku = sku or (product.sku if product else existing.sku or "")
        existing.image_url = (media[0] if media and isinstance(media[0], str) else existing.image_url or "")
        existing.quantity = quantity
        existing.financial_return_date = operation_day
        existing.amount = amount
        existing.currency = "KZT"
        existing.financial_status = "confirmed"
        existing.last_synced_at = datetime.now(timezone.utc)
        raw_extra = {"financial_statement": True, "financial_statement_return_id": operation_id,
                     "file_name": (file.filename or "")[:160]}
        if is_cabinet_returns:
            try:
                delivery_decimal = Decimal(str(mapped.get("return_delivery_cost") or "0").replace("\u00a0", "").replace("\u202f", "").replace(" ", "").replace(",", "."))
                delivery_tiyn = int((abs(delivery_decimal) * 100).quantize(Decimal("1")))
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                errors.append({"row": row_number, "message": "Некорректный расход обратной доставки"})
                continue
            raw_extra.update({"source_kind": "kaspi_cabinet_returns", "generated_return_id": True,
                              "return_delivery_cost_tiyn": delivery_tiyn, "source_sheet": sheet_name})
        existing.raw_data = {**(existing.raw_data or {}), **raw_extra}
    if errors and imported == 0 and updated == 0:
        raise HTTPException(422, {"message":"Ни одна строка не импортирована", "errors":errors[:20]})
    audit(db, u, "import_marketplace_returns", "marketplace_returns", details={
        "account_id":account.id, "source_file":(file.filename or "")[:160],
        "imported":imported, "updated":updated, "skipped":skipped, "errors":len(errors),
    })
    db.commit()
    return {"ok":True, "imported":imported, "updated":updated, "skipped":skipped,
            "errors":errors[:50], "message":"Данные записаны только в журнал возвратов; существующие финансовые отчёты не изменены."}


@app.post("/api/marketplace-returns/{marketplace_return_id}/inventory-match")
def match_marketplace_return_inventory(marketplace_return_id: int, u=Depends(current_user), db=Depends(get_db)):
    """Read-only match to an existing ERP return; never creates stock or financial entries."""
    require(u, "inventory")
    observation = db.get(MarketplaceReturn, marketplace_return_id)
    if not observation:
        raise HTTPException(404, "Возврат маркетплейса не найден")
    scope(u, observation.company_id)
    account = db.get(Account, observation.account_id)
    if not account or account.company_id != observation.company_id:
        raise HTTPException(409, "Магазин возврата не найден")
    matched = marketplace_returns.match_inventory_return(db, observation, account)
    if not matched:
        return {
            "matched": False,
            "message": "Не удалось однозначно сопоставить возврат с продажей и возвратом ERP. Остаток не изменён.",
        }
    return {
        "matched": True,
        "return_id": matched["id"],
        "status": matched["status"],
        "quantity": matched["quantity"],
        "message": "Найден возврат ERP. Изменение остатка выполняется только через подтверждение статуса.",
    }


@app.get("/api/marketplace-returns")
def get_marketplace_returns(
    marketplace: str = "all", company_id: int | None = None, account_id: int | None = None,
    start: date | None = None, end: date | None = None, search: str = "",
    return_status: str | None = None, financial_status: str | None = None,
    unknown_only: bool = False,
    offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
    u=Depends(current_user), db=Depends(get_db),
):
    """Separate return observations. This endpoint never reads or posts to P&L."""
    require(u, "sales")
    if marketplace not in {"all", "Kaspi", "Wildberries", "Ozon"}:
        raise HTTPException(422, "Неизвестный маркетплейс")
    if start and end and end < start:
        raise HTTPException(422, "Дата окончания раньше даты начала")
    if company_id is not None:
        scope(u, company_id)
    q = select(MarketplaceReturn, Account, Product).join(
        Account, MarketplaceReturn.account_id == Account.id
    ).outerjoin(Product, MarketplaceReturn.product_id == Product.id)
    if u.role != "Owner":
        q = q.where(MarketplaceReturn.company_id.in_(u.company_ids or []))
    if company_id is not None:
        q = q.where(MarketplaceReturn.company_id == company_id)
    if account_id is not None:
        account = db.get(Account, account_id)
        if not account:
            raise HTTPException(404, "Магазин не найден")
        scope(u, account.company_id)
        q = q.where(MarketplaceReturn.account_id == account_id)
    if marketplace != "all":
        q = q.where(MarketplaceReturn.marketplace == marketplace)
    if return_status:
        if return_status not in {"requested", "returned", "rejected", "financial_operation_reported", "financial_return_confirmed"}:
            raise HTTPException(422, "Неизвестный статус возврата")
        q = q.where(MarketplaceReturn.return_status == return_status)
    if financial_status:
        if financial_status not in {"confirmed", "unconfirmed"}:
            raise HTTPException(422, "Неизвестный финансовый статус возврата")
        q = q.where(MarketplaceReturn.financial_status == financial_status)
    if unknown_only:
        q = q.where(or_(MarketplaceReturn.financial_return_date.is_(None), MarketplaceReturn.amount.is_(None)))
    return_event_day = func.coalesce(MarketplaceReturn.financial_return_date, MarketplaceReturn.request_date)
    if start:
        q = q.where(or_(return_event_day >= start, return_event_day.is_(None)))
    if end:
        q = q.where(or_(return_event_day <= end, return_event_day.is_(None)))
    term = search.strip()[:120]
    if term:
        needle = f"%{term}%"
        q = q.where(or_(MarketplaceReturn.external_order_id.ilike(needle),
                        MarketplaceReturn.sku.ilike(needle), MarketplaceReturn.product_name.ilike(needle),
                        Account.name.ilike(needle)))
    rows = db.execute(q.order_by(MarketplaceReturn.detected_date.desc(), MarketplaceReturn.id.desc())
                      .offset(offset).limit(limit)).all()
    # Summary values are computed over the complete filtered set, independent of pagination.
    base = select(MarketplaceReturn).join(Account, MarketplaceReturn.account_id == Account.id)
    if u.role != "Owner": base = base.where(MarketplaceReturn.company_id.in_(u.company_ids or []))
    if company_id is not None: base = base.where(MarketplaceReturn.company_id == company_id)
    if account_id is not None: base = base.where(MarketplaceReturn.account_id == account_id)
    if marketplace != "all": base = base.where(MarketplaceReturn.marketplace == marketplace)
    if return_status: base = base.where(MarketplaceReturn.return_status == return_status)
    if financial_status: base = base.where(MarketplaceReturn.financial_status == financial_status)
    if unknown_only: base = base.where(or_(MarketplaceReturn.financial_return_date.is_(None), MarketplaceReturn.amount.is_(None)))
    base_event_day = func.coalesce(MarketplaceReturn.financial_return_date, MarketplaceReturn.request_date)
    if start: base = base.where(or_(base_event_day >= start, base_event_day.is_(None)))
    if end: base = base.where(or_(base_event_day <= end, base_event_day.is_(None)))
    if term:
        needle = f"%{term}%"
        base = base.where(or_(MarketplaceReturn.external_order_id.ilike(needle), MarketplaceReturn.sku.ilike(needle),
                              MarketplaceReturn.product_name.ilike(needle), Account.name.ilike(needle)))
    scoped_returns = base.subquery()
    agg = db.execute(select(
        func.count(),
        func.sum(case((scoped_returns.c.return_status == "requested", 1), else_=0)),
        func.sum(case((scoped_returns.c.financial_status == "confirmed", 1), else_=0)),
        func.sum(case(((scoped_returns.c.financial_status == "confirmed") & scoped_returns.c.amount.is_not(None), scoped_returns.c.amount), else_=0)),
        func.sum(case((scoped_returns.c.return_status == "rejected", 1), else_=0)),
        func.sum(case((scoped_returns.c.accounted_status == "yes", scoped_returns.c.amount), else_=0)),
        func.sum(case((scoped_returns.c.accounted_status == "no", scoped_returns.c.amount), else_=0)),
        func.sum(case((scoped_returns.c.accounted_status == "unverified", 1), else_=0)),
        func.sum(case(((scoped_returns.c.financial_return_date.is_(None)) | scoped_returns.c.amount.is_(None), 1), else_=0)),
    ).select_from(scoped_returns)).one()
    count = agg[0] or 0
    summary = {
        "requests": agg[1] or 0,
        "confirmed_count": agg[2] or 0,
        "confirmed_amount": agg[3] or 0,
        "pending_count": count - (agg[2] or 0),
        "rejected_count": agg[4] or 0,
        "accounted_amount": agg[5] or 0,
        "not_accounted_amount": agg[6] or 0,
        "unverified_accounting_count": agg[7] or 0,
        "unknown_count": agg[8] or 0,
        "existing_report_total": None, "adjusted_total": None, "test_mode": True,
    }
    integrations_q = select(Account).where(Account.channel.in_(["Kaspi", "Wildberries", "Ozon"]))
    if u.role != "Owner": integrations_q = integrations_q.where(Account.company_id.in_(u.company_ids or []))
    if company_id is not None: integrations_q = integrations_q.where(Account.company_id == company_id)
    if marketplace != "all": integrations_q = integrations_q.where(Account.channel == marketplace)
    integrations = [{"account_id": a.id, "marketplace": a.channel, "store": a.name,
                     "active": a.active, "mode": a.mode} for a in db.scalars(integrations_q)]
    return {"items": [marketplace_returns.serialize_return(r, a, p) for r, a, p in rows],
            "total": count, "offset": offset, "limit": limit, "summary": summary,
            "integrations": integrations}


@app.get("/api/marketplace-record-details")
def marketplace_record_details(
    channel: str, metric: str, start: date, end: date,
    company_id: int | None = None, account_id: int | None = None,
    u=Depends(current_user), db=Depends(get_db),
):
    """Read-only, account-scoped detail rows from already stored marketplace API records."""
    require(u, "analytics")
    if channel not in {"Kaspi", "Wildberries"}:
        raise HTTPException(422, "Подробный API-отчёт доступен для Kaspi и Wildberries")
    if metric not in {"sales", "returns", "logistics", "settlement"}:
        raise HTTPException(422, "Неизвестный показатель API-отчёта")
    if end < start:
        raise HTTPException(422, "Дата окончания раньше даты начала")
    aq = select(Account).where(Account.channel == channel, Account.active.is_(True))
    if u.role != "Owner": aq = aq.where(Account.company_id.in_(u.company_ids or []))
    if company_id is not None:
        scope(u, company_id)
        aq = aq.where(Account.company_id == company_id)
    if account_id is not None:
        aq = aq.where(Account.id == account_id)
    accounts = {a.id: a for a in db.scalars(aq)}
    if account_id is not None and account_id not in accounts:
        raise HTTPException(404, "Магазин выбранного маркетплейса не найден")
    if not accounts:
        return {"channel": channel, "metric": metric, "start": str(start), "end": str(end), "items": [],
                "note": "Нет активных API-магазинов в выбранной компании."}

    source_names = {"kaspi": ["kaspi"], "wildberries": ["wildberries", "wildberries_weekly"]}[channel.lower()]
    records = db.scalars(select(MarketplaceRecord).where(
        MarketplaceRecord.account_id.in_(accounts), MarketplaceRecord.source.in_(source_names)
    ).order_by(MarketplaceRecord.id.desc())).all()
    kaspi_order_codes = {}
    if channel == "Kaspi":
        kaspi_order_codes = {str((r.payload or {}).get("order_id")): str((r.payload or {}).get("code") or "")
                             for r in records if str((r.payload or {}).get("record_type") or "").lower() == "order"}
    output = []
    for rec in records:
        p = rec.payload or {}
        kind = str(p.get("record_type") or "").lower()
        event_date = None
        status = ""
        operation = ""
        reference = rec.external_id or ""
        product_name = str(p.get("product_name") or p.get("productName") or p.get("name") or p.get("title") or p.get("subjectName") or "")
        sku = str(p.get("sku") or p.get("supplierArticle") or p.get("vendorCode") or p.get("sa_name") or p.get("nmId") or "")
        quantity = p.get("quantity")
        amount = None
        currency = str(p.get("currency") or p.get("currency_name") or p.get("currencyName") or ("KZT" if channel == "Kaspi" else "RUB")).upper()
        include = False
        if channel == "Kaspi":
            status = str(p.get("order_status") or p.get("status") or "").upper()
            order_id = str(p.get("order_code") or p.get("code") or kaspi_order_codes.get(str(p.get("order_id") or "")) or p.get("order_id") or "")
            reference = order_id or reference
            if kind == "order_entry":
                returned = status in {"RETURNED", "KASPI_DELIVERY_RETURN_REQUESTED"}
                if metric == "returns" and returned:
                    include = True
                    event_date = p.get("returned_date") or p.get("return_date") or p.get("completed_date") or p.get("completion_date")
                    operation = "Заявка на возврат" if status == "KASPI_DELIVERY_RETURN_REQUESTED" else "Возвращённый заказ"
                    amount = None
                elif metric == "sales" and status == "COMPLETED":
                    include = True
                    event_date = p.get("completed_date") or p.get("completion_date") or p.get("completionDate")
                    operation = "Продажа по дате выдачи"
                    amount = p.get("total_price") or p.get("totalPrice")
                elif metric == "logistics" and kind == "order_entry" and (p.get("delivery_cost_for_seller") is not None or p.get("deliveryCostForSeller") is not None or p.get("deliveryCost") is not None):
                    include = True
                    event_date = p.get("completed_date") or p.get("completionDate")
                    operation = "Доставка по данным заказа API"
                    amount = p.get("deliveryCostForSeller") or p.get("deliveryCost")
                    quantity = None
                elif metric == "settlement":
                    include = False
            elif kind == "delivery_charge" and metric == "logistics" and str(p.get("order_status") or "").upper() == "COMPLETED":
                include = True
                event_date = p.get("completed_date") or p.get("completion_date")
                operation = "Доставка выданного заказа"
                amount = p.get("amount")
                status = str(p.get("order_status") or status).upper()
                quantity = None
            elif kind == "return_delivery_charge" and metric == "logistics" and str(p.get("order_status") or "").upper() == "RETURNED":
                include = True
                event_date = p.get("returned_date") or p.get("return_date")
                operation = "Обратная доставка"
                amount = p.get("amount")
                status = str(p.get("order_status") or status).upper()
                quantity = None
        else:
            operation = " ".join(str(p.get(key) or "") for key in (
                "docTypeName", "doc_type_name", "supplierOperName", "supplier_oper_name",
                "sellerOperName", "seller_oper_name")).strip()
            lower_operation = operation.lower()
            is_return = ("возврат" in lower_operation or "return" in lower_operation)
            is_sale = ("продаж" in lower_operation or lower_operation == "sale")
            event_date = p.get("rrdDate") or p.get("rr_dt") or p.get("rrDate") or p.get("saleDt") or p.get("sale_dt") or p.get("date")
            reference = str(p.get("rrdId") or p.get("rrd_id") or p.get("srid") or p.get("saleID") or reference)
            if metric == "returns" and kind in {"realization", ""} and is_return:
                include = True
            elif metric == "sales" and ((kind == "sale" and not str(p.get("saleID") or "").upper().startswith("R") and not p.get("isStorno")) or (kind in {"realization", ""} and is_sale)):
                include = True
                amount = p.get("priceWithDisc") if kind == "sale" else (p.get("retailAmount") or p.get("retail_amount"))
            elif metric == "logistics" and kind in {"realization", ""} and any(p.get(key) not in (None, "", 0, "0") for key in ("deliveryService", "deliveryRub", "delivery_rub", "rebillLogisticCost", "rebill_logistic_cost")):
                include = True
                amount = p.get("deliveryService") or p.get("deliveryRub") or p.get("delivery_rub") or p.get("rebillLogisticCost") or p.get("rebill_logistic_cost")
            elif metric == "settlement" and kind in {"realization", ""}:
                include = True
                amount = p.get("forPay") or p.get("ppvzForPay") or p.get("ppvz_for_pay")
        if not include:
            continue
        try:
            day = marketplace_pipeline._day(event_date, "Asia/Almaty" if channel == "Kaspi" else None) if event_date not in (None, "") else None
        except (ValueError, TypeError, KeyError, marketplace_pipeline.Pending):
            day = None
        if day is not None and not start <= day <= end:
            continue
        # Kaspi does not expose an actual refund amount/date in this order API.
        # Keep unknown event dates visible but never imply that order value is refund value.
        if channel == "Kaspi" and metric == "returns":
            amount = None
        output.append({"id": rec.id, "account_id": rec.account_id, "store": accounts[rec.account_id].name,
            "event_date": str(day) if day else None, "operation": operation or status or kind or "Операция API",
            "reference": reference, "product_name": product_name or "Товар не сопоставлен", "sku": sku,
            "quantity": quantity, "status": status or p.get("status") or "—", "amount": amount,
            "currency": currency, "source": rec.source})
    output.sort(key=lambda item: (item["event_date"] or "", item["id"]), reverse=True)
    note = ""
    if channel == "Kaspi" and metric == "returns":
        note = "Kaspi API подтверждает статус и состав заказа, но не фактическую сумму/дату возврата. Если дата возврата отсутствует, прежнее поведение относит заказ к периоду по дате выдачи; это резервная дата, не фактическая дата возврата. Сумма в сводке рассчитана по сумме заказа и не является подтверждённой суммой выплаты."
    elif channel == "Wildberries" and metric == "returns":
        note = "Возвраты взяты из финансовых строк WB по типу операции. Суммы показаны в исходной валюте отчёта; банковское зачисление здесь не подтверждается."
    elif metric == "settlement":
        note = "Начисление по строкам API-отчёта, а не подтверждение банковской выплаты."
    return {"channel": channel, "metric": metric, "start": str(start), "end": str(end), "items": output, "note": note}


@app.get("/api/marketplace-report.xlsx")
def marketplace_report_xlsx(channel: str, start: date, end: date,
                            company_id: int | None = None, account_id: int | None = None,
                            u=Depends(current_user), db=Depends(get_db)):
    """Export a separate API-sourced marketplace report without changing ERP calculations."""
    require(u, "analytics")
    if channel not in {"Kaspi", "Wildberries"}:
        raise HTTPException(422, "Отчёт API доступен для Kaspi и Wildberries")
    if end < start:
        raise HTTPException(422, "Дата окончания раньше даты начала")
    if channel == "Wildberries":
        # The official WB Finance export is the source of truth for this channel.
        # Keep the custom range in its isolated report namespace.
        period = "custom"
        _wb_finance_period_args(period, start, end)
        account = _wb_week_account(db, u, account_id)
        from .wb_weekly import build_report, create_xlsx
        report = build_report(db, account, start, end, period=period)
        if report.get("status") != "готов" or not report.get("row_count"):
            raise HTTPException(409, "Финансовый отчёт WB за период ещё не получен")
        raw = create_xlsx(report)
        filename = f"WB-API-{start}-{end}.xlsx"
    else:
        # Reuse the existing, read-only Kaspi API summary and detail selectors.
        # These are copies of current API/ERP fields; this export has no new
        # commissions, tax, return or profit formulas.
        summary = marketplace_summary(channel, start, end, company_id, account_id, u, db)
        sales = marketplace_record_details(channel, "sales", start, end, company_id, account_id, u, db)
        returns = marketplace_record_details(channel, "returns", start, end, company_id, account_id, u, db)
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from io import BytesIO
        book = Workbook(); overview = book.active; overview.title = "Итоги API"
        api_available = summary.get("api_data_available") is True
        overview.append(["Kaspi · отчёт по данным API"])
        overview.append(["Период", f"{start} — {end}"])
        overview.append(["Статус синхронизации", summary.get("sync_status")])
        overview.append(["Последняя синхронизация", str(summary.get("last_sync") or "—")])
        overview.append(["Данные API подтверждены", "Да" if api_available else "Нет"])
        report_complete = summary.get("sync_status") == "done" and summary.get("source_complete") is True
        overview.append(["Полнота источника", "Подтверждена" if report_complete else "Не подтверждена"])
        overview.append(["Статус файла", "Полный отчёт" if report_complete else "ПРЕДВАРИТЕЛЬНЫЙ — только сохранённые строки; цифры могут измениться после синхронизации"])
        if not report_complete:
            overview.append(["Предупреждение", "Синхронизация не завершена или полнота источника не подтверждена. Файл содержит только данные, сохранённые к моменту скачивания."])
        overview.append(["Показатель", "Значение", "Источник / смысл"])
        for label, key, note in [
            ("Продажи API, до возвратов", "api_gross_revenue", "Подтверждённые строки Kaspi API"),
            ("Продажи API, за вычетом возвратов", "api_revenue", "Поле сводки Kaspi API"),
            ("Продано, шт.", "api_units", "Количество из строк Kaspi API"),
            ("Возвраты API", "api_returns", "Фактическая сумма возврата не предоставляется API"),
            ("Возвраты, шт.", "api_return_units", "Количество из строк Kaspi API"),
            ("Доставка продавца API, выданные заказы", "api_logistics", "deliveryCostForSeller, только COMPLETED и по completionDate; отдельно от финансовой формулы QOR"),
            ("Обратная доставка API", "api_return_logistics", "Только отдельные returnDeliveryCostForSeller с датой возврата"),
            ("Возвращённые единицы без даты", "api_undated_return_units", "Не отнесены к периоду и не вычитаются из продаж"),
            ("Строки без конвертации", "api_unconverted", "Требуют проверки даты/суммы"),
        ]:
            value = summary.get(key) if api_available else None
            if key in {"api_gross_revenue", "api_revenue", "api_returns", "api_logistics", "api_return_logistics"} and value is not None:
                value = value / 100
            overview.append([label, value, note])
        for label, key, note in [
            ("Комиссия QOR", "commission", "Учтённые расходы и/или оценка текущей модели; не финансовая выписка Kaspi Pay."),
            ("Оценочная часть комиссии", "commission_estimated", "Оценка существующей модели QOR; не фактическая сумма списания Kaspi."),
            ("Логистика QOR", "logistics", "Уже учтённые в QOR расходы за период."),
            ("Обратная логистика QOR", "return_logistics", "Уже учтённые в QOR расходы за период."),
            ("Реклама QOR", "advertising", "Уже учтённые в QOR расходы за период."),
            ("Оценка суммы к перечислению", "kaspi_estimated_proceeds", "Расчётная оценка QOR, не подтверждение выплаты Kaspi Pay."),
            ("Прибыль QOR", "net_profit", "Существующий расчёт QOR; может быть пустым, если не хватает подтверждённых затрат."),
            ("Штрафы, учтённые в QOR", "marketplace_fines", "Только расходы с категорией «штраф/fine», уже внесённые в QOR. Kaspi API заказов штрафы не возвращает."),
        ]:
            value = summary.get(key)
            if value is not None:
                value = value / 100
            overview.append([label, value, note])
        sale_ws = book.create_sheet("Продажи API")
        headers = ["Дата выдачи", "Магазин", "ID заказа", "Товар", "SKU", "Количество", "Сумма API", "Валюта", "Статус"]
        sale_ws.append(headers)
        for item in sales.get("items", []):
            sale_ws.append([item.get("event_date"), item.get("store"), item.get("reference"), item.get("product_name"), item.get("sku"), item.get("quantity"), item.get("amount"), item.get("currency"), item.get("status")])
        return_ws = book.create_sheet("Возвраты API")
        return_ws.append(["Дата возврата API", "Магазин", "ID заказа", "Товар", "SKU", "Количество", "Сумма возврата", "Валюта", "Статус"])
        for item in returns.get("items", []):
            return_ws.append([item.get("event_date"), item.get("store"), item.get("reference"), item.get("product_name"), item.get("sku"), item.get("quantity"), item.get("amount"), item.get("currency"), item.get("status")])
        note_ws = book.create_sheet("Примечания")
        note_ws.append(["Показатель", "Источник", "Ограничение"])
        note_ws.append(["Суммы и продажи", "Kaspi API и действующая сводка QOR", "Экспорт не пересчитывает финансовые показатели"])
        note_ws.append(["Возвраты", "Статусы и позиции Kaspi API", "Kaspi API не подтверждает фактическую дату и сумму возврата; пустые суммы намеренно оставлены пустыми"])
        for ws in book.worksheets:
            ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions if ws.max_row > 1 else None
            header_rows = (1, 6) if ws.title == "Итоги API" else (1,)
            for row_no in header_rows:
                for cell in ws[row_no]:
                    cell.font = Font(bold=True, color="FFFFFF")
                    cell.fill = PatternFill("solid", fgColor="135B45")
                    cell.alignment = Alignment(vertical="center", wrap_text=True)
            for column in ws.columns:
                width = min(44, max(14, max(len(str(c.…40094 tokens truncated…PException(422, "Webhook verify token должен содержать от 16 до 256 символов без пробелов")
                config["webhook_verify_token"] = verify_token
            config.update({"phone_number_id": phone_id, "template_name": template,
                           "language": language, "graph_version": version,
                           "inbound_enabled": bool(p.get("inbound_enabled", config.get("inbound_enabled", False)))})
            save_config(db, "whatsapp_cloud", config)
        db.commit()
        status = daily_reports.provider_status(db)
    except SecretStorageError as exc:
        db.rollback()
        raise HTTPException(503, str(exc)) from exc
    audit(db, u, "update", "integration_secret", 2,
          {"provider": "whatsapp_cloud", "configured": status["configured"]})
    db.commit()
    return {**status, "inbound_enabled": bool(load_config("whatsapp_cloud", db).get("inbound_enabled")), "inbound_ready": all(bool(load_config("whatsapp_cloud", db).get(k)) for k in ("app_secret", "webhook_verify_token", "access_token", "phone_number_id"))}


@app.post("/api/settings/integrations/whatsapp/test")
def site_whatsapp_connection_test(u=Depends(current_user), db=Depends(get_db)):
    require(u, "settings", True)
    try:
        return daily_reports.test_whatsapp_connection(db)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, str(exc)[:220]) from exc


@app.get("/api/automation/daily-report")
def daily_report_settings_get(u=Depends(current_user), db=Depends(get_db)):
    require(u, "settings")
    obj = db.get(Setting, 1)
    recent = db.scalars(select(DailyReportDelivery).order_by(DailyReportDelivery.created_at.desc()).limit(10)).all()
    return {
        "enabled": bool(obj and obj.daily_report_enabled),
        "time": getattr(obj, "daily_report_time", "09:00"),
        "recipient": getattr(obj, "daily_report_recipient", ""),
        "consent": bool(getattr(obj, "daily_report_consent", False)),
        "ai_summary": bool(getattr(obj, "daily_report_ai_summary", False)),
        "provider": daily_reports.provider_status(db),
        "scheduler": "in_app",
        "recent": [{"date": str(x.report_date), "status": x.status, "error": x.error,
                    "sent_at": x.sent_at.isoformat() if x.sent_at else None}
                   for x in recent],
    }


@app.put("/api/automation/daily-report")
def daily_report_settings_save(p: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u, "settings", True)
    allowed = {"enabled", "time", "recipient", "consent", "ai_summary"}
    if set(p) - allowed:
        raise HTTPException(422, "Недопустимые поля настройки отчётов")
    obj = db.get(Setting, 1)
    if obj is None:
        raise HTTPException(503, "Настройки рабочего пространства не инициализированы")
    enabled = bool(p.get("enabled", obj.daily_report_enabled))
    consent = bool(p.get("consent", obj.daily_report_consent))
    recipient = str(p.get("recipient", obj.daily_report_recipient) or "").strip()
    schedule = str(p.get("time", obj.daily_report_time or "09:00")).strip()
    try:
        datetime.strptime(schedule, "%H:%M")
    except ValueError:
        raise HTTPException(422, "Укажите время в формате ЧЧ:ММ")
    if recipient and not daily_reports.PHONE_RE.fullmatch(recipient):
        raise HTTPException(422, "Введите номер получателя в международном формате, например +77001234567")
    if enabled and (not consent or not recipient):
        raise HTTPException(422, "Для включения укажите номер и подтвердите согласие получателя")
    if enabled and not daily_reports.provider_status(db)["configured"]:
        raise HTTPException(409, "Сначала подключите WhatsApp Business API в настройках сайта")
    obj.daily_report_enabled = enabled
    obj.daily_report_time = schedule
    obj.daily_report_recipient = recipient
    obj.daily_report_consent = consent
    obj.daily_report_ai_summary = bool(p.get("ai_summary", obj.daily_report_ai_summary))
    audit(db, u, "update", "daily_report_settings", 1,
          {"enabled": enabled, "time": schedule, "recipient_configured": bool(recipient),
           "consent": consent, "ai_summary": obj.daily_report_ai_summary})
    db.commit()
    return {"ok": True, "enabled": enabled, "time": schedule,
            "recipient": recipient, "consent": consent,
            "ai_summary": obj.daily_report_ai_summary,
            "provider": daily_reports.provider_status(db)}


@app.post("/api/ai/skills/install")
def install_claude_skills(u=Depends(current_user), db=Depends(get_db)):
    """Upload the bundled QOR Skills to the Anthropic workspace behind the server key."""
    require(u, "settings", True)
    if not CLAUDE_SKILL_INSTALL_LOCK.acquire(blocking=False):
        raise HTTPException(409, "Загрузка Skills уже выполняется")
    try:
        if ai.claude_skills_status(db)["enabled"]:
            raise HTTPException(409, "Все 11 Skills уже подключены")
        skills = ai.install_claude_skills(db=db)
        config = load_config("anthropic", db)
        config["skills_json"] = skills
        save_config(db, "anthropic", config)
        audit(db, u, "create", "claude_skills", 1)
        db.commit()
        return {"skills": skills, "configured": len(skills), "required": len(ai.CLAUDE_SKILL_KEYS)}
    finally:
        CLAUDE_SKILL_INSTALL_LOCK.release()


@app.post("/api/ai/skills/update")
def update_claude_skills(u=Depends(current_user), db=Depends(get_db)):
    """Publish new versions of all bundled QOR Skills in the configured Anthropic workspace."""
    require(u, "settings", True)
    if not ai.claude_skills_status(db)["enabled"]:
        raise HTTPException(409, "Сначала подключите все 11 Skills")
    if not CLAUDE_SKILL_INSTALL_LOCK.acquire(blocking=False):
        raise HTTPException(409, "Обновление Skills уже выполняется")
    try:
        skills = ai.install_claude_skills(update_existing=True, db=db)
        config = load_config("anthropic", db)
        config["skills_json"] = skills
        save_config(db, "anthropic", config)
        audit(db, u, "update", "claude_skills", len(skills))
        db.commit()
        return {"skills": skills, "configured": len(skills), "required": len(ai.CLAUDE_SKILL_KEYS)}
    finally:
        CLAUDE_SKILL_INSTALL_LOCK.release()


@app.put("/api/settings")
def save_settings(p: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u, "settings", True)
    if set(p) - {"business_name"}:
        raise HTTPException(
            422, "В этой версии валюта KZT, зона Asia/Almaty фиксированы"
        )
    obj = db.get(Setting, 1)
    obj.business_name = str(p.get("business_name", "QOR Business"))[:160]
    audit(db, u, "update", "settings", 1)
    db.commit()
    return dump(obj)


def _credential_cipher():
    # Production credentials are encrypted with a dedicated system secret, never
    # with an account password or database URL. Development retains a local-only
    # fallback so a fresh demo can run without copying a secret into source code.
    material = os.getenv("CREDENTIAL_ENCRYPTION_KEY")
    if not material:
        if os.getenv("APP_ENV", "development").lower() == "production":
            raise HTTPException(503, "Сервер интеграций не настроен: отсутствует CREDENTIAL_ENCRYPTION_KEY")
        material = os.getenv("OWNER_PASSWORD") or os.getenv("DATABASE_URL", "qor-local-dev")
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())
    return Fernet(key)


@app.put("/api/accounts/{id}/credentials")
def save_account_credentials(id: int, p: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u, "accounts", True)
    acc = db.get(Account, id)
    if not acc: raise HTTPException(404, "Аккаунт не найден")
    scope(u, acc.company_id)
    allowed = {"Kaspi": {"token"}, "Wildberries": {"token"}, "Ozon": {"client_id", "api_key"}}.get(acc.channel, set())
    if not allowed: raise HTTPException(422, "Для этого канала API-ключи не требуются")
    values = {k: str(p.get(k, "")).strip() for k in allowed}
    if any(not values[k] for k in allowed): raise HTTPException(422, "Заполните все данные подключения")
    # Store canonical per-account credential fields. Marketplace connections created in QOR
    # never depend on Render ENV variable names or Account.credential_ref.
    names = values
    enc = _credential_cipher().encrypt(json.dumps(names).encode()).decode()
    row = db.scalar(select(IntegrationSecret).where(IntegrationSecret.account_id == id))
    if row: row.encrypted_payload, row.key_hint = enc, "••••" + list(values.values())[0][-4:]
    else: db.add(IntegrationSecret(account_id=id, encrypted_payload=enc, key_hint="••••" + list(values.values())[0][-4:]))
    acc.mode = "api"
    acc.active = True
    audit(db, u, "credentials_update", "accounts", id, {"channel": acc.channel})
    db.commit()
    return {"ok": True, "channel": acc.channel, "configured": True, "hint": "••••" + list(values.values())[0][-4:]}

@app.delete("/api/accounts/{id}/credentials")
def delete_account_credentials(id: int, u=Depends(current_user), db=Depends(get_db)):
    require(u, "accounts", True)
    acc=db.get(Account,id)
    if not acc: raise HTTPException(404,"Аккаунт не найден")
    scope(u,acc.company_id)
    row=db.scalar(select(IntegrationSecret).where(IntegrationSecret.account_id==id))
    if row: db.delete(row)
    acc.active=False; acc.sync_status="never"; acc.sync_error=""
    audit(db,u,"credentials_delete","accounts",id,{"channel":acc.channel}); db.commit()
    return {"ok":True,"archived":True}


@app.get("/api/accounts/{id}/marketplace-settings")
def marketplace_settings_get(id: int, u=Depends(current_user), db=Depends(get_db)):
    require(u, "accounts")
    acc = db.get(Account, id)
    if not acc or acc.channel not in {"Kaspi", "Wildberries"}:
        raise HTTPException(404, "Интеграция не найдена")
    scope(u, acc.company_id)
    settings = acc.integration_settings or {}
    return {"channel": acc.channel, "auto_sync": bool(settings.get("auto_sync", False)),
            "kaspi_store_id": settings.get("kaspi_store_id", ""),
            "kaspi_merchant_id": settings.get("kaspi_merchant_id", ""),
            "kaspi_full_catalog_confirmed": bool(settings.get("kaspi_full_catalog_confirmed", False)),
            "kaspi_feed_configured": bool(settings.get("kaspi_feed_token_hash")),
            "wb_warehouse_id": str(settings.get("wb_warehouse_id", ""))}


@app.put("/api/accounts/{id}/marketplace-settings")
def marketplace_settings_save(id: int, p: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u, "accounts", True)
    acc = db.get(Account, id)
    if not acc or acc.channel not in {"Kaspi", "Wildberries"}:
        raise HTTPException(404, "Интеграция не найдена")
    scope(u, acc.company_id)
    settings = dict(acc.integration_settings or {})
    if acc.channel == "Kaspi":
        allowed = {"kaspi_store_id", "kaspi_merchant_id", "kaspi_full_catalog_confirmed", "auto_sync"}
        if set(p) - allowed:
            raise HTTPException(422, "Неизвестная настройка Kaspi")
        store = str(p.get("kaspi_store_id", settings.get("kaspi_store_id", ""))).strip()
        merchant = str(p.get("kaspi_merchant_id", settings.get("kaspi_merchant_id", ""))).strip()
        if len(store) > 120 or len(merchant) > 120:
            raise HTTPException(422, "Код магазина или продавца слишком длинный")
        settings.update({"kaspi_store_id": store, "kaspi_merchant_id": merchant,
                         "kaspi_full_catalog_confirmed": bool(p.get("kaspi_full_catalog_confirmed", settings.get("kaspi_full_catalog_confirmed", False)))})
    else:
        allowed = {"wb_warehouse_id", "auto_sync"}
        if set(p) - allowed:
            raise HTTPException(422, "Неизвестная настройка Wildberries")
        warehouse_id = str(p.get("wb_warehouse_id", settings.get("wb_warehouse_id", ""))).strip()[:40]
        if warehouse_id and not warehouse_id.isdigit():
            raise HTTPException(422, "ID склада WB должен быть числовым")
        settings["wb_warehouse_id"] = warehouse_id
    if "auto_sync" in p:
        settings["auto_sync"] = bool(p["auto_sync"])
    acc.integration_settings = settings
    audit(db, u, "marketplace_settings_update", "accounts", acc.id,
          {"channel": acc.channel, "keys": sorted(set(p) - {"auto_sync"})})
    db.commit()
    return {"ok": True, "channel": acc.channel, "auto_sync": bool(settings.get("auto_sync", False))}


@app.post("/api/accounts/{id}/kaspi/feed-url")
def kaspi_feed_url(id: int, request: Request, u=Depends(current_user), db=Depends(get_db)):
    require(u, "accounts", True)
    acc = db.get(Account, id)
    if not acc or acc.channel != "Kaspi" or not acc.active:
        raise HTTPException(404, "Активный магазин Kaspi не найден")
    scope(u, acc.company_id)
    settings = dict(acc.integration_settings or {})
    if not settings.get("kaspi_store_id") or not settings.get("kaspi_merchant_id"):
        raise HTTPException(422, "Сначала укажите код склада и merchant ID из кабинета Kaspi")
    if not settings.get("kaspi_full_catalog_confirmed"):
        raise HTTPException(409, "Подтвердите, что все товары действующего прайс-листа Kaspi будут связаны с QOR")
    token = secrets.token_urlsafe(32)
    settings["kaspi_feed_token_hash"] = hashlib.sha256(token.encode()).hexdigest()
    acc.integration_settings = settings
    audit(db, u, "kaspi_feed_token_rotated", "accounts", acc.id, {"channel": "Kaspi"})
    db.commit()
    base = str(request.base_url).rstrip("/")
    return {"feed_url": f"{base}/public/kaspi-feeds/{acc.id}/{token}.xml",
            "setup_note": "Добавьте эту ссылку в кабинете Kaspi → Товары → Прайс-лист → Автоматическая загрузка. Kaspi проверяет обновления примерно раз в час. Ссылка показывает только сопоставленные товары этого магазина."}


@app.get("/public/kaspi-feeds/{account_id}/{token}.xml")
def kaspi_public_feed(account_id: int, token: str, db=Depends(get_db)):
    acc = db.get(Account, account_id)
    if not acc or not acc.active or acc.channel != "Kaspi":
        raise HTTPException(404, "Прайс-лист не найден")
    settings = acc.integration_settings or {}
    expected = str(settings.get("kaspi_feed_token_hash") or "")
    actual = hashlib.sha256(token.encode()).hexdigest()
    if not expected or not hmac.compare_digest(expected, actual):
        raise HTTPException(404, "Прайс-лист не найден")
    if not settings.get("kaspi_full_catalog_confirmed") or not settings.get("kaspi_store_id") or not settings.get("kaspi_merchant_id"):
        raise HTTPException(409, "Настройки прайс-листа не завершены")
    mappings = db.scalars(select(MarketplaceProductMapping).where(
        MarketplaceProductMapping.account_id == acc.id,
        MarketplaceProductMapping.company_id == acc.company_id,
        MarketplaceProductMapping.channel == "Kaspi",
    )).all()
    product_ids = sorted({m.product_id for m in mappings})
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(product_ids), Product.active.is_(True))).all()} if product_ids else {}
    skus_by_product = {}
    for mapping in mappings:
        key = mapping.external_key
        if key.startswith("sku:"):
            sku = key[4:]
            if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", sku):
                skus_by_product.setdefault(mapping.product_id, set()).add(sku)
    root = ET.Element("kaspi_catalog", {"date": business_today().isoformat(), "xmlns": "kaspiShopping",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "kaspiShopping http://kaspi.kz/kaspishopping.xsd"})
    ET.SubElement(root, "company").text = acc.name
    ET.SubElement(root, "merchantid").text = str(settings["kaspi_merchant_id"])
    offers = ET.SubElement(root, "offers")
    physical_by_product = dict(db.execute(select(Batch.product_id, func.coalesce(func.sum(Batch.remaining), 0))
        .where(Batch.company_id == acc.company_id, Batch.product_id.in_(list(products)))
        .group_by(Batch.product_id)).all()) if products else {}
    allocated_elsewhere = {}
    for product_id, product in products.items():
        specs = product.specifications or {}
        allocation_map = specs.get("marketplace_stock_allocations") or {}
        for other_id, value in allocation_map.items():
            try:
                count = int(value.get("quantity", 0)) if isinstance(value, dict) else int(value or 0)
            except (TypeError, ValueError):
                count = 0
            if isinstance(value, dict):
                for size_amount in (value.get("sizes") or {}).values():
                    try: count += max(0, int(size_amount or 0))
                    except (TypeError, ValueError): pass
            allocated_elsewhere[product_id] = allocated_elsewhere.get(product_id, 0) + max(0, count)
    for product_id, product in products.items():
        skus = sorted(skus_by_product.get(product_id, set()))
        if not skus or product.price <= 0:
            continue
        specs = product.specifications or {}
        allocation_map = specs.get("marketplace_stock_allocations") or {}
        try:
            qty_value = allocation_map.get(str(acc.id), 0)
            qty = int(qty_value.get("quantity", 0)) if isinstance(qty_value, dict) else int(qty_value or 0)
        except (TypeError, ValueError):
            qty = 0
        qty = max(0, qty)
        physical = max(0, int(physical_by_product.get(product_id, 0) or 0) - int(specs.get("reserved_quantity") or 0))
        # Do not publish a platform allocation that exceeds the verified shared physical pool.
        if qty > physical or allocated_elsewhere.get(product_id, 0) > physical:
            qty = 0
        for sku in skus:
            offer = ET.SubElement(offers, "offer", {"sku": sku})
            ET.SubElement(offer, "model").text = product.name
            ET.SubElement(offer, "brand").text = product.brand or "Без бренда"
            availabilities = ET.SubElement(offer, "availabilities")
            ET.SubElement(availabilities, "availability", {
                "available": "yes" if qty > 0 else "no", "storeId": str(settings["kaspi_store_id"]), "stockCount": str(qty)})
            ET.SubElement(offer, "price").text = str((int(product.price) + 50) // 100)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=xml, media_type="application/xml", headers={"Cache-Control": "no-store"})


def _wb_mapped_ids(db, account_id, product_id):
    rows = db.scalars(select(MarketplaceProductMapping).where(
        MarketplaceProductMapping.account_id == account_id,
        MarketplaceProductMapping.product_id == product_id,
        MarketplaceProductMapping.channel == "Wildberries",
    )).all()
    nm_ids, chrt_ids = set(), set()
    for row in rows:
        key = row.external_key
        if key.startswith("product:"):
            parts = key.split(":")
            if len(parts) >= 2 and parts[1].isdigit(): nm_ids.add(int(parts[1]))
            if len(parts) >= 3 and parts[2].isdigit(): chrt_ids.add(int(parts[2]))
        elif key.startswith("size:") and key[5:].isdigit():
            chrt_ids.add(int(key[5:]))
    return rows, sorted(nm_ids), sorted(chrt_ids)


def sync_wb_product(db, account, product):
    settings = account.integration_settings or {}
    warehouse_id = str(settings.get("wb_warehouse_id") or "")
    if not warehouse_id:
        raise HTTPException(409, "Сначала выберите склад продавца Wildberries в настройках интеграции")
    if not account.active or account.mode != "api":
        raise HTTPException(409, "Интеграция Wildberries выключена")
    if account.settlement_currency != product.currency:
        raise HTTPException(409, f"Валюта магазина WB ({account.settlement_currency}) не совпадает с валютой товара ({product.currency})")
    mappings, nm_ids, chrt_ids = _wb_mapped_ids(db, account.id, product.id)
    if not mappings or not nm_ids or not chrt_ids:
        raise HTTPException(409, "Товар не сопоставлен с карточкой и размерами Wildberries")
    allocation_map = (product.specifications or {}).get("marketplace_stock_allocations") or {}
    own = allocation_map.get(str(account.id)) or {}
    sizes = own.get("sizes") or {} if isinstance(own, dict) else {}
    if not sizes:
        raise HTTPException(409, "Укажите отдельное распределение остатка по размерам WB в карточке товара")
    physical = int(db.scalar(select(func.coalesce(func.sum(Batch.remaining), 0)).where(
        Batch.company_id == account.company_id, Batch.product_id == product.id)) or 0)
    reserved = int((product.specifications or {}).get("reserved_quantity") or 0)
    usable = max(0, physical - reserved)
    all_allocations = 0
    for account_alloc in allocation_map.values():
        if not isinstance(account_alloc, dict): continue
        try: all_allocations += max(0, int(account_alloc.get("quantity", 0) or 0))
        except (TypeError, ValueError): pass
        for amount in (account_alloc.get("sizes") or {}).values():
            try: all_allocations += max(0, int(amount or 0))
            except (TypeError, ValueError): pass
    if all_allocations > usable:
        raise HTTPException(409, f"Распределено {all_allocations} шт., доступно на складе {usable}. Исправьте лимиты площадок")
    stock_rows = []
    for chrt_id in chrt_ids:
        try: amount = int(sizes.get(str(chrt_id), 0) or 0)
        except (TypeError, ValueError): raise HTTPException(422, "Остаток WB должен быть целым неотрицательным числом")
        if amount < 0: raise HTTPException(422, "Остаток WB не может быть отрицательным")
        stock_rows.append({"chrtId": chrt_id, "amount": amount})
    if sum(row["amount"] for row in stock_rows) > usable:
        raise HTTPException(409, "Выделение WB превышает доступный физический остаток")
    try:
        client = connector(account, load_saved_credentials(db, account.id))
        price_rows = []
        if int(product.price or 0) <= 0:
            raise HTTPException(409, "Перед синхронизацией укажите цену товара больше нуля")
        for nm_id in nm_ids:
            payload = client.product_prices(nm_id)
            data = payload.get("data") or payload
            goods = data.get("listGoods") or data.get("goods") or [] if isinstance(data, dict) else []
            good = next((g for g in goods if int(g.get("nmID") or g.get("nmId") or 0) == nm_id), None)
            if not good:
                raise HTTPException(409, f"WB не вернул текущие скидки nmID {nm_id}; цена не отправлена")
            discounts = {int(size.get("discount") or 0) for size in (good.get("sizes") or [])}
            if len(discounts) > 1:
                raise HTTPException(409, f"У nmID {nm_id} разные скидки по размерам. Сначала выровняйте их в кабинете WB")
            discount = next(iter(discounts), 0)
            price_rows.append({"nmID": nm_id, "price": (int(product.price) + 50) // 100, "discount": discount})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "Wildberries: " + str(exc)[:500])
    price_result = stock_result = None
    sync_errors = {}
    try:
        price_result = client.upload_prices(price_rows)
    except Exception as exc:
        sync_errors["price"] = str(exc)[:400]
    try:
        stock_result = client.update_seller_stocks(warehouse_id, stock_rows)
    except Exception as exc:
        sync_errors["stock"] = str(exc)[:400]
    audit(db, None, "wildberries_product_outbound_sync", "accounts", account.id,
          {"product_id": product.id, "nm_ids": nm_ids, "sizes": len(stock_rows), "stock_total": sum(x["amount"] for x in stock_rows),
           "price_submitted": price_result is not None, "stock_updated": stock_result is not None, "errors": sync_errors})
    db.commit()
    if sync_errors:
        raise HTTPException(422, "WB: " + "; ".join(f"{key}: {value}" for key, value in sync_errors.items()))
    return {"ok": True, "channel": "Wildberries", "product_id": product.id,
            "price_task": price_result, "stock_result": stock_result,
            "price_kzt": (int(product.price) + 50) // 100,
            "stock_total": sum(x["amount"] for x in stock_rows)}


def _auto_sync_wb_product(account_id, product_id):
    """Best-effort background sync after ERP commits; failures stay in service logs."""
    with SessionLocal() as db:
        account = db.get(Account, account_id)
        product = db.get(Product, product_id)
        if not account or not product or not (account.integration_settings or {}).get("auto_sync"):
            return
        try:
            sync_wb_product(db, account, product)
        except Exception:
            db.rollback()
            logger.exception("Automatic Wildberries product sync failed for account=%s product=%s", account_id, product_id)


def _schedule_wb_sync_for_product(tasks, product_id, company_id=None):
    if tasks is None: return
    with SessionLocal() as db:
        query = select(Account.id).join(
            MarketplaceProductMapping, MarketplaceProductMapping.account_id == Account.id
        ).where(
            MarketplaceProductMapping.product_id == product_id,
            Account.channel == "Wildberries", Account.active.is_(True)
        )
        if company_id is not None: query = query.where(Account.company_id == company_id)
        account_ids = set(db.scalars(query.distinct()).all())
        if not account_ids: return
        accounts = db.scalars(select(Account).where(Account.id.in_(account_ids))).all()
        eligible = [a.id for a in accounts if (a.integration_settings or {}).get("auto_sync")]
    for account_id in eligible:
        tasks.add_task(_auto_sync_wb_product, account_id, product_id)

@app.get("/api/accounts/{id}/wb/warehouses")
def wb_seller_warehouses(id: int, u=Depends(current_user), db=Depends(get_db)):
    require(u, "accounts")
    account = db.get(Account, id)
    if not account or account.channel != "Wildberries": raise HTTPException(404, "Магазин Wildberries не найден")
    scope(u, account.company_id)
    try:
        client = connector(account, load_saved_credentials(db, account.id))
        result = client.list_seller_warehouses()
        return {"items": result if isinstance(result, list) else result.get("warehouses", [])}
    except Exception as exc:
        raise HTTPException(422, "Не удалось получить склады продавца WB: " + str(exc)[:400])


@app.post("/api/accounts/{id}/wb/products/{product_id}/sync")
def wb_product_sync(id: int, product_id: int, p: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u, "accounts", True)
    account = db.get(Account, id)
    product = db.get(Product, product_id)
    if not account or account.channel != "Wildberries" or not product: raise HTTPException(404, "Магазин или товар не найден")
    scope_product(db, u, product.id, account.company_id)
    if p.get("confirm") is not True: raise HTTPException(428, "Подтвердите отправку текущей цены и распределённых остатков в Wildberries")
    return sync_wb_product(db, account, product)

@app.post("/api/accounts/{id}/kaspi/orders/{order_id}/status")
def kaspi_order_status(id: int, order_id: str, p: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u, "accounts", True)
    acc=db.get(Account,id)
    if not acc or acc.channel != "Kaspi": raise HTTPException(404,"Kaspi аккаунт не найден")
    scope(u,acc.company_id)
    creds=load_saved_credentials(db,acc.id)
    try:
        result=connector(acc,creds).update_order(order_id=order_id,status=p.get("status"),code=p.get("code"),cancellation_reason=p.get("cancellation_reason"),cancellation_comment=p.get("cancellation_comment"),number_of_space=p.get("number_of_space"),security_code=p.get("security_code"),send_code=bool(p.get("send_code",False)))
    except Exception as exc:
        raise HTTPException(422,str(exc)[:1000])
    audit(db,u,"kaspi_order_status","accounts",id,{"order_id":order_id,"status":p.get("status")}); db.commit()
    return {"ok":True,"result":result}


def _kaspi_api_context(account_id, user, db, write=False):
    require(user, "accounts", write)
    account = db.get(Account, account_id)
    if not account or account.channel != "Kaspi":
        raise HTTPException(404, "Kaspi аккаунт не найден")
    scope(user, account.company_id)
    if account.mode != "api":
        raise HTTPException(409, "Для операции включите режим API у Kaspi-аккаунта")
    try:
        credentials = load_saved_credentials(db, account.id)
    except AccessRequired as exc:
        raise HTTPException(409, str(exc))
    return account, connector(account, credentials)


@app.get("/api/accounts/{id}/kaspi/orders/{order_id}")
def kaspi_get_order(id: int, order_id: str, u=Depends(current_user), db=Depends(get_db)):
    _, client = _kaspi_api_context(id, u, db)
    try:
        return client.get_order(order_id)
    except Exception as exc:
        raise HTTPException(422, str(exc)[:500])


@app.get("/api/accounts/{id}/kaspi/orders/{order_id}/entries")
def kaspi_get_order_entries(id: int, order_id: str, page_size: int = Query(100, ge=1, le=100),
                            u=Depends(current_user), db=Depends(get_db)):
    _, client = _kaspi_api_context(id, u, db)
    try:
        return {"data": client.get_order_entries(order_id, page_size)}
    except Exception as exc:
        raise HTTPException(422, str(exc)[:500])


@app.get("/api/accounts/{id}/kaspi/catalog/categories")
def kaspi_catalog_categories(id: int, u=Depends(current_user), db=Depends(get_db)):
    _, client = _kaspi_api_context(id, u, db)
    try:
        return client.list_categories()
    except Exception as exc:
        raise HTTPException(422, str(exc)[:500])


@app.get("/api/accounts/{id}/kaspi/catalog/attributes")
def kaspi_catalog_attributes(id: int, category: str = Query(..., min_length=1, max_length=240),
                             u=Depends(current_user), db=Depends(get_db)):
    _, client = _kaspi_api_context(id, u, db)
    try:
        return client.list_category_attributes(category)
    except Exception as exc:
        raise HTTPException(422, str(exc)[:500])


@app.get("/api/accounts/{id}/kaspi/catalog/attribute-values")
def kaspi_catalog_attribute_values(id: int, category: str = Query(..., min_length=1, max_length=240),
                                  attribute: str = Query(..., min_length=1, max_length=240),
                                  u=Depends(current_user), db=Depends(get_db)):
    _, client = _kaspi_api_context(id, u, db)
    try:
        return client.list_attribute_values(category, attribute)
    except Exception as exc:
        raise HTTPException(422, str(exc)[:500])


@app.post("/api/accounts/{id}/kaspi/products/import")
def kaspi_import_products(id: int, payload: dict, u=Depends(current_user), db=Depends(get_db)):
    account, client = _kaspi_api_context(id, u, db, write=True)
    products = payload.get("products")
    try:
        result = client.import_products(products)
    except Exception as exc:
        raise HTTPException(422, str(exc)[:500])
    audit(db, u, "kaspi_product_import", "accounts", id, {"count": len(products or [])})
    db.commit()
    return {"ok": True, "submitted": len(products or []), "result": result}


@app.get("/api/accounts/{id}/kaspi/products/import/{import_code}")
def kaspi_product_import_status(id: int, import_code: str, u=Depends(current_user), db=Depends(get_db)):
    _, client = _kaspi_api_context(id, u, db)
    try:
        return client.get_product_import_status(import_code)
    except Exception as exc:
        raise HTTPException(422, str(exc)[:500])


@app.get("/api/accounts/{id}/kaspi/products/import/{import_code}/result")
def kaspi_product_import_result(id: int, import_code: str, u=Depends(current_user), db=Depends(get_db)):
    _, client = _kaspi_api_context(id, u, db)
    try:
        return client.get_product_import_result(import_code)
    except Exception as exc:
        raise HTTPException(422, str(exc)[:500])


def _stage_marketplace_records(db, acc, result):
    """Persist each external record once. Never invent a financial sale from an order payload."""
    inserted = 0
    updated = 0
    for item in result.records:
        external_id = str(item.get("external_id") or "").strip()
        if not external_id:
            continue
        row = db.scalar(select(MarketplaceRecord).where(
            MarketplaceRecord.account_id == acc.id,
            MarketplaceRecord.source == result.source,
            MarketplaceRecord.external_id == external_id,
        ))
        payload = jsonable_encoder(item)
        if row:
            old_payload = {k:v for k,v in (row.payload or {}).items() if not k.startswith('_qor_')}
            # Kaspi list responses can omit event fields that were present in a
            # code lookup. Keep established source facts when a later response
            # sends null; never synthesize one event date from another.
            merged = dict(old_payload)
            merged.update(payload)
            for field in (
                "completion_date", "completed_date", "returned_date", "return_date",
                "creation_date", "order_creation_date", "entries_complete", "entries_count",
                "quantity", "total_price", "sku", "external_product_id", "product_name",
            ):
                if payload.get(field) is None and old_payload.get(field) is not None:
                    merged[field] = old_payload[field]
            old_raw = old_payload.get("raw_attributes")
            new_raw = payload.get("raw_attributes")
            if isinstance(old_raw, dict) and isinstance(new_raw, dict):
                raw = dict(old_raw)
                raw.update({k: v for k, v in new_raw.items() if v is not None})
                merged["raw_attributes"] = raw
            if old_payload != merged:
                row.payload = merged
                # Revalidate revisions through canonical identity checks, never
                # leave a changed source silently marked as projected.
                row.status = 'received'
            updated += 1
        else:
            db.add(MarketplaceRecord(account_id=acc.id, company_id=acc.company_id, source=result.source, external_id=external_id, payload=payload))
            inserted += 1
    return inserted, updated


def _stage_marketplace_catalog_records(db, acc, result):
    """Idempotently stage WB catalogue pages without changing financial states."""
    inserted = updated = 0
    for item in result.records:
        if str(item.get("record_type") or "").lower() != "product":
            continue
        external_id = str(item.get("external_id") or "").strip()
        if not external_id:
            continue
        row = db.scalar(select(MarketplaceRecord).where(
            MarketplaceRecord.account_id == acc.id,
            MarketplaceRecord.source == "wildberries",
            MarketplaceRecord.external_id == external_id,
        ))
        payload = jsonable_encoder(item)
        if row:
            if (row.payload or {}) != payload:
                row.payload = payload
                updated += 1
            continue
        try:
            with db.begin_nested():
                db.add(MarketplaceRecord(account_id=acc.id, company_id=acc.company_id,
                    source="wildberries", external_id=external_id, payload=payload))
                db.flush()
            inserted += 1
        except IntegrityError:
            # A normal marketplace sync can stage the same card concurrently.
            row = db.scalar(select(MarketplaceRecord).where(
                MarketplaceRecord.account_id == acc.id,
                MarketplaceRecord.source == "wildberries",
                MarketplaceRecord.external_id == external_id,
            ))
            if row is None:
                raise
            if (row.payload or {}) != payload:
                row.payload = payload
                updated += 1
    return inserted, updated


def _background_kaspi_period_sync(account_id, user_id, start, end, extra_order_ids, report_mode="issued", status_only=False, expected_lease=None):
    """Refresh only a requested Kaspi creation-date window plus old open orders."""
    with SessionLocal() as db:
        acc = db.get(Account, account_id)
        user = db.get(User, user_id)
        if not acc:
            return
        warnings = []
        try:
            if not user or not user.active:
                raise AccessRequired("Пользователь отключён")
            require(user, "accounts", True)
            scope(user, acc.company_id)
            worker = connector(acc, load_saved_credentials(db, acc.id))
            lease = acc.sync_error
            if expected_lease is not None and lease != expected_lease:
                return
            job = dict((acc.integration_settings or {}).get("kaspi_period_job") or {})
            if job and (job.get("start") != str(start) or job.get("end") != str(end)):
                return
            today_local = datetime.now(ZoneInfo("Asia/Almaty"))
            sync_start = _kaspi_issued_scan_start(today_local.date()) if report_mode == "issued" else start
            local_start = datetime.combine(sync_start, datetime.min.time(), ZoneInfo("Asia/Almaty"))
            local_end = (today_local if end >= today_local.date() else
                         datetime.combine(end + timedelta(days=1), datetime.min.time(), ZoneInfo("Asia/Almaty")))
            event_start = datetime.combine(start, datetime.min.time(), ZoneInfo("Asia/Almaty"))
            # Keep only small per-order counts in memory. Loading every cached JSON
            # payload (including raw Kaspi attributes) on each resumed scan can
            # exceed the Render instance memory limit as history grows.
            cached_children_by_order = {}
            known_order_ids = []
            known_entry_counts = {}
            if status_only:
                entry_counts = {
                    str(order_id): int(count)
                    for order_id, count in db.execute(text(
                        "SELECT payload->>'order_id', count(*) FROM marketplace_records "
                        "WHERE account_id=:account_id AND source='kaspi' "
                        "AND payload->>'record_type'='order_entry' GROUP BY payload->>'order_id'"
                    ), {"account_id": acc.id})
                    if order_id
                }
                order_meta = db.execute(text(
                    "SELECT payload->>'order_id', payload->>'code', "
                    "payload->>'entries_complete', payload->>'entries_count' "
                    "FROM marketplace_records WHERE account_id=:account_id AND source='kaspi' "
                    "AND payload->>'record_type'='order'"
                ), {"account_id": acc.id})
                for order_id, code, complete, expected in order_meta:
                    count = entry_counts.get(str(order_id or ""), 0)
                    if code and count:
                        known_order_ids.append(str(code))
                    try:
                        expected_count = int(expected or 0)
                    except (TypeError, ValueError):
                        continue
                    if code and complete == "true" and count > 0 and count == expected_count:
                        known_entry_counts[str(code)] = count
            progress_key = _kaspi_period_sync_key(report_mode, start, end)
            settings = dict(acc.integration_settings or {})
            progress = dict(settings.get("kaspi_period_progress") or {})
            cursor = progress[progress_key] if progress_key in progress else json.dumps({"_qor_kaspi_cursor":1,"scope":"status_only" if status_only else "period",
                "scan_version":3,"state_index":0,"known_entry_counts":known_entry_counts,
                "start_ms":int(local_start.timestamp()*1000),"until_ms":int(local_end.timestamp()*1000)-1,
                "event_start_ms":int(event_start.timestamp()*1000),
                "event_end_ms":int(local_end.timestamp()*1000)-1,
                "page":0,"offset":0,"extra_ids":([] if status_only else extra_order_ids),"extra_offset":0,
                "known_order_ids":known_order_ids}, separators=(",", ":"))
            pages = records = inserted_total = updated_total = 0
            while cursor:
                if _kaspi_sync_paused_for(account_id, start, end):
                    db.refresh(acc)
                    _pause_kaspi_job(db, acc)
                    db.commit()
                    return
                # Do not occupy a pooled DB connection while waiting on Kaspi.
                db.commit()
                result = worker.fetch(cursor)
                db.refresh(acc)
                if acc.sync_error != lease or not acc.active:
                    db.rollback()
                    return
                if status_only:
                    # Fetch cached line/charge payloads only for the current
                    # API page, rather than retaining the entire account history.
                    page_order_ids = {
                        str((row or {}).get("order_id") or "")
                        for row in result.records
                        if (row or {}).get("record_type") == "order" and (row or {}).get("order_id")
                    }
                    cached_children_by_order = {}
                    if page_order_ids:
                        cached_payloads = db.scalars(select(MarketplaceRecord.payload).where(
                            MarketplaceRecord.account_id == acc.id,
                            MarketplaceRecord.source == "kaspi",
                            MarketplaceRecord.payload["record_type"].as_string().in_(
                                ["order_entry", "delivery_charge", "return_delivery_charge"]),
                            MarketplaceRecord.payload["order_id"].as_string().in_(page_order_ids),
                        )).all()
                        for child in cached_payloads:
                            child = child or {}
                            cached_children_by_order.setdefault(str(child.get("order_id") or ""), []).append(child)
                    present = {str(row.get("external_id") or "") for row in result.records}
                    propagated = []
                    for order in result.records:
                        op = order or {}
                        if op.get("record_type") != "order":
                            continue
                        oid = str(op.get("order_id") or "")
                        attrs = op.get("raw_attributes") or {}
                        for prior in cached_children_by_order.get(oid, []):
                            child = dict(prior)
                            child["order_status"] = op.get("status")
                            child["order_state"] = op.get("state")
                            child["completed_date"] = op.get("completion_date") or child.get("completed_date")
                            child["returned_date"] = op.get("returned_date") or child.get("returned_date")
                            if child.get("record_type") == "delivery_charge":
                                child["completed_date"] = op.get("completion_date")
                                if op.get("delivery_cost_for_seller") is not None:
                                    child["amount"] = op.get("delivery_cost_for_seller")
                            elif child.get("record_type") == "return_delivery_charge":
                                if op.get("return_delivery_cost_for_seller") is not None:
                                    child["amount"] = op.get("return_delivery_cost_for_seller")
                            if child.get("external_id") not in present:
                                propagated.append(child)
                                present.add(child.get("external_id"))
                        return_cost = op.get("return_delivery_cost_for_seller")
                        if return_cost not in (None, "", 0, 0.0, "0"):
                            ext = "return-delivery:" + oid
                            if ext not in present:
                                propagated.append({
                                    "external_id": ext, "record_type": "return_delivery_charge",
                                    "order_id": oid, "amount": return_cost, "currency": "KZT",
                                    "order_status": op.get("status"), "returned_date": op.get("returned_date"),
                                    "order_creation_date": op.get("creation_date"),
                                    "completion_date": op.get("completion_date"), "raw_attributes": attrs,
                                })
                                present.add(ext)
                    result.records.extend(propagated)
                inserted, updated = _stage_marketplace_records(db, acc, result)
                record_ids = [str(x.get("external_id")) for x in result.records if x.get("external_id")]
                projection = marketplace_pipeline.project_account(db, user, acc, external_ids=record_ids, reconcile_pending=False)
                pages += 1
                records += len(result.records)
                inserted_total += inserted
                updated_total += updated
                warnings.extend(result.warnings or [])
                cursor = result.next_cursor
                acc.last_sync = now()
                acc.sync_status = "running"
                acc.sync_error = lease
                progress[progress_key] = cursor
                settings = dict(acc.integration_settings or {})
                settings["kaspi_period_progress"] = dict(progress)
                position = json.loads(cursor) if cursor else {}
                type_counts = {}
                for record in result.records:
                    record_type = str(record.get("record_type") or "other")
                    type_counts[record_type] = type_counts.get(record_type, 0) + 1
                job.update(status="running", batches=int(job.get("batches") or 0)+1,
                           records=int(job.get("records") or 0)+len(result.records),
                           order_list_pages=int(job.get("order_list_pages") or 0)+1,
                           order_records_received=int(job.get("order_records_received") or 0)+type_counts.get("order", 0),
                           order_entries=int(job.get("order_entries") or 0)+type_counts.get("order_entry", 0),
                           scan_from=str(sync_start),
                           scan_through=datetime.fromtimestamp(position.get("until_ms", int(local_end.timestamp()*1000))/1000, ZoneInfo("Asia/Almaty")).date().isoformat(),
                           state=("ARCHIVE", "NEW", "SIGN_REQUIRED", "PICKUP", "DELIVERY", "KASPI_DELIVERY")[int(position.get("state_index") or 0)],
                           page=position.get("page", 0), page_count=position.get("page_count"),
                           offset=position.get("offset", 0), page_size=position.get("page_size"))
                settings["kaspi_period_job"] = dict(job)
                acc.integration_settings = settings
                db.commit()
                if pages >= 20000:
                    raise AccessRequired("Kaspi: превышен защитный лимит страниц диапазона")
            marketplace_pipeline.project_account(db, user, acc, external_ids=[])
            acc = db.get(Account, account_id)
            acc.last_sync = now()
            acc.sync_status = "partial" if warnings else "done"
            acc.sync_error = "; ".join(warnings)[:500]
            settings = dict(acc.integration_settings or {})
            progress = dict(settings.get("kaspi_period_progress") or {})
            progress.pop(progress_key, None)
            settings["kaspi_period_progress"] = progress
            job["status"] = "partial" if warnings else "done"
            settings["kaspi_period_job"] = dict(job)
            acc.integration_settings = settings
            if not warnings:
                coverage = dict(settings.get("kaspi_period_sync") or {})
                coverage[progress_key] = now().isoformat()
                settings["kaspi_period_sync"] = dict(list(coverage.items())[-100:])
                acc.integration_settings = settings
            audit(db, user, "sync_kaspi_period", "accounts", acc.id,
                  {"start":str(start),"end":str(end),"report_mode":report_mode,"status_only":status_only,"records":records,"pages":pages,
                   "inserted":inserted_total,"updated":updated_total})
            db.commit()
        except Exception as exc:
            logger.exception("Kaspi period sync failed for account %s", account_id)
            db.rollback()
            acc = db.get(Account, account_id)
            if acc and acc.sync_error == locals().get("lease"):
                acc.last_sync = now()
                acc.sync_status = "failed"
                acc.sync_error = str(getattr(exc, "detail", exc))[:500]
                settings = dict(acc.integration_settings or {})
                job = dict(settings.get("kaspi_period_job") or {})
                attempts = int(job.get("failures") or 0) + 1
                job.update(status="retry" if attempts < 3 else "failed", failures=attempts,
                           retry_at=(now()+timedelta(seconds=60)).isoformat())
                settings["kaspi_period_job"] = job
                acc.integration_settings = settings
                db.commit()


@app.post("/api/accounts/{id}/sync-kaspi-period")
def sync_kaspi_period(id: int, tasks: BackgroundTasks, start: date, end: date,
                      report_mode: str = Query(default="issued", regex="^(created|issued)$"),
                      force: bool = False,
                      u=Depends(current_user), db=Depends(get_db)):
    """Schedule a bounded Kaspi sync and refresh previously open/very recent orders."""
    require(u, "accounts", True)
    acc = db.get(Account, id)
    if not acc:
        raise HTTPException(404, "Интеграция не найдена")
    scope(u, acc.company_id)
    if acc.channel != "Kaspi" or acc.mode != "api" or not acc.active:
        raise HTTPException(409, "Активная API-интеграция Kaspi не найдена")
    if end < start or (end - start).days > 366:
        raise HTTPException(422, "Укажите корректный период не длиннее 367 дней")
    sync_is_running = sync_status_for_display(acc)[0] == "running"
    abandoned_kaspi_period_sync = (
        sync_is_running
        and acc.channel == "Kaspi"
        and str(acc.sync_error or "").startswith("KASPI_PERIOD_SYNC")
        and (acc.last_sync is None or acc.last_sync < now()-timedelta(minutes=5))
    )
    if sync_is_running and not abandoned_kaspi_period_sync:
        return {"ok":True,"status":"running","already_running":True,"account_id":acc.id,
                "start":str(start),"end":str(end),"report_mode":report_mode}
    local_today = datetime.now(ZoneInfo("Asia/Almaty")).date()
    if start > local_today:
        raise HTTPException(422, "Начало периода не может быть в будущем")
    bounded_end = min(end, local_today)
    if _kaspi_sync_paused_for(acc.id, start, bounded_end):
        _pause_kaspi_job(db, acc)
        db.commit()
        return {"ok":True,"status":"paused","account_id":acc.id,
                "saved_cursor":True,"start":str(start),"end":str(bounded_end),
                "message":"Архивная загрузка остановлена; уже сохранённые данные и курсор сохранены."}
    if report_mode == "issued" and bounded_end < _kaspi_issued_scan_start(local_today):
        raise HTTPException(422, "Этот период старше настроенного окна загрузки; увеличьте глубину истории")
    period_key = _kaspi_period_sync_key(report_mode, start, bounded_end)
    settings = dict(acc.integration_settings or {})
    cache = dict(settings.get("kaspi_period_sync") or {})
    cached_at = None
    if cache.get(period_key):
        try: cached_at = datetime.fromisoformat(str(cache[period_key]))
        except ValueError: cached_at = None
    age = (now() - cached_at).total_seconds() if cached_at else None
    cache_ttl = 5 * 60 if start == bounded_end == local_today else (10 * 60 if bounded_end == local_today - timedelta(days=1) else 3600)
    cache_fresh = cached_at is not None and age is not None and age < cache_ttl
    if cache_fresh and not force:
        return {"ok":True,"status":"cached","cached":True,"account_id":acc.id,"start":str(start),"end":str(bounded_end),"report_mode":report_mode}
    refresh_ids = set()
    status_only = report_mode == "issued"
    stale_period_claim = and_(
        Account.channel == "Kaspi",
        Account.sync_error.like("KASPI_PERIOD_SYNC%"),
        or_(Account.last_sync < now()-timedelta(minutes=5), Account.last_sync.is_(None)),
    )
    job = dict(settings.get("kaspi_period_job") or {})
    if job.get("start") != str(start) or job.get("end") != str(bounded_end) or job.get("status") == "done":
        # Keep the paused long-range archive job and its cursor available for
        # later resumption when a short dashboard period is requested.
        if job.get("status") == "paused" and job.get("start") and job.get("end"):
            old_start, old_end = date.fromisoformat(job["start"]), date.fromisoformat(job["end"])
            if _kaspi_sync_paused_for(acc.id, old_start, old_end):
                paused_jobs = list(settings.get("kaspi_period_paused_jobs") or [])
                if not any(x.get("start") == job.get("start") and x.get("end") == job.get("end")
                           for x in paused_jobs):
                    paused_jobs.append(dict(job))
                settings["kaspi_period_paused_jobs"] = paused_jobs[-20:]
        job = {"start":str(start), "end":str(bounded_end), "mode":report_mode,
               "user_id":u.id, "batches":0, "records":0}
    job.update(status="running", failures=0)
    settings["kaspi_period_job"] = job
    lease = "KASPI_PERIOD_SYNC:" + uuid.uuid4().hex
    claimed = db.execute(update(Account).where(Account.id == id,
        or_(Account.sync_status != "running", Account.last_sync < now()-timedelta(seconds=SYNC_RUNNING_TIMEOUT_SECONDS), Account.last_sync.is_(None), stale_period_claim))
        .values(sync_status="running", sync_error=lease, last_sync=now(), integration_settings=settings))
    if claimed.rowcount != 1:
        return {"ok":True,"status":"running","already_running":True,"account_id":acc.id,
                "start":str(start),"end":str(bounded_end),"report_mode":report_mode}
    db.commit()
    tasks.add_task(_background_kaspi_period_sync, acc.id, u.id, start, bounded_end, ([] if status_only else sorted(refresh_ids)), report_mode, status_only, lease)
    return {"ok":True,"status":"running","account_id":acc.id,"start":str(start),"end":str(bounded_end),
            "report_mode":report_mode,"old_orders_to_refresh":len(refresh_ids),"status_only":status_only}


@app.post("/api/accounts/{id}/sync-now")
def account_sync_now(id: int, tasks: BackgroundTasks, background: bool = False, sections: str | None = None,
                     u=Depends(current_user), db=Depends(get_db)):
    """Run marketplace sync immediately in the web process.

    Render free/web deployments do not require a separate queue worker for marketplace checks.
    The endpoint always finishes as success or error and persists the account status.
    """
    require(u, "accounts", True)
    acc = db.get(Account, id)
    if not acc:
        raise HTTPException(404, "Интеграция не найдена")
    scope(u, acc.company_id)
    if not acc.active:
        raise HTTPException(409, "Аккаунт отключён. Подключите его заново перед синхронизацией")
    claimed = db.execute(update(Account).where(Account.id == id,
        Account.active.is_(True),
        or_(Account.sync_status != 'running', Account.last_sync < now()-timedelta(seconds=SYNC_RUNNING_TIMEOUT_SECONDS), Account.last_sync.is_(None)))
        .values(sync_status='running', sync_error='', last_sync=now()))
    if claimed.rowcount != 1:
        raise HTTPException(409, 'Синхронизация уже выполняется')
    db.commit()
    selected_sections = None
    if acc.channel == "Wildberries" and acc.mode == "api":
        allowed = WB_ALLOWED_SYNC_SECTIONS
        selected_sections = [x.strip() for x in sections.split(",") if x.strip()] if sections else list(WB_DEFAULT_SYNC_SECTIONS)
        unknown = set(selected_sections) - allowed
        if not selected_sections or unknown:
            acc.sync_status = "failed"
            acc.sync_error = "Неизвестные разделы WB: " + ", ".join(sorted(unknown or {"пустой список"}))
            db.commit()
            raise HTTPException(422, acc.sync_error)
    if background and acc.mode == 'api':
        tasks.add_task(_background_marketplace_sync, acc.id, u.id, selected_sections)
        return {'ok':True, 'status':'running', 'account_id':acc.id,
                **({'sections': selected_sections, 'catalog_included': 'products' in selected_sections} if selected_sections is not None else {})}
    return _perform_marketplace_sync(db, u, acc, sections=selected_sections)


def _perform_marketplace_sync(db, u, acc, sections=None):
    account_id = acc.id
    try:
        creds = load_saved_credentials(db, acc.id)
        worker = connector(acc, creds)
        if acc.channel == "Wildberries" and acc.mode == "api":
            # WB is synchronized as independent durable streams. Each page is staged
            # and committed before the next remote request; no page payloads are kept
            # in memory after staging.
            import json as _json
            state = _json.loads(acc.sync_cursor) if acc.sync_cursor else {}
            if not isinstance(state, dict): state = {}
            section_state = state.setdefault('_sections', {})
            warnings, counts = [], {}
            total_records = total_inserted = total_updated = 0
            successful_sections = 0
            selected_sections = list(sections or worker.sections)
            for section in selected_sections:
                section_inserted = section_updated = section_pages = section_records = 0
                section_state[section] = {'status': 'running'}
                acc.sync_cursor = _json.dumps(state, separators=(',', ':'))
                db.commit()
                try:
                    for piece in worker.fetch_section_pages(section, _json.dumps(state, separators=(',', ':'))):
                        added, changed = _stage_marketplace_records(db, acc, piece)
                        section_inserted += added; section_updated += changed
                        section_pages += 1; section_records += len(piece.records)
                        total_records += len(piece.records); total_inserted += added; total_updated += changed
                        if piece.next_cursor:
                            next_state = _json.loads(piece.next_cursor)
                            if isinstance(next_state, dict):
                                # Preserve local durable section metadata while accepting
                                # remote cursors advanced by the connector.
                                next_state['_sections'] = section_state
                                state = next_state
                        section_state = state.setdefault('_sections', section_state)
                        section_state[section] = {'status':'running','pages':section_pages,'records':section_records}
                        acc.sync_cursor = _json.dumps(state, separators=(',', ':'))
                        db.commit()
                    successful_sections += 1
                    section_state[section] = {'status':'done','pages':section_pages,'records':section_records}
                    counts[section] = {'pages':section_pages,'records':section_records,'inserted':section_inserted,'updated':section_updated}
                    acc.sync_cursor = _json.dumps(state, separators=(',', ':'))
                    db.commit()
                except Exception as section_exc:
                    db.rollback()
                    acc = db.get(Account, account_id)
                    # Reload the last committed cursor so a failed page is retried rather
                    # than skipped. Persist a terminal state for this individual stream.
                    try:
                        state = _json.loads(acc.sync_cursor) if acc.sync_cursor else state
                    except (ValueError, TypeError):
                        pass
                    if not isinstance(state, dict): state = {}
                    section_state = state.setdefault('_sections', {})
                    message = str(section_exc)[:180]
                    section_state[section] = {'status':'failed','pages':section_pages,'records':section_records,'error':message}
                    acc.sync_cursor = _json.dumps(state, separators=(',', ':'))
                    warnings.append(f"{section}: {message}")
                    counts[section] = {'pages':section_pages,'records':section_records,'inserted':section_inserted,'updated':section_updated,'error':message}
                    db.commit()
                    logger.exception("WB section %s failed for account %s", section, account_id)
            # One idempotent ERP projection after all remote streams have finished.
            # This avoids scanning the full staging history six times per sync.
            financial_sections = any(section != 'order_statuses' for section in selected_sections)
            projection = marketplace_pipeline.project_account(db, u, acc) if total_records and financial_sections else {'projected':0,'pending_erp':0}
            acc = db.get(Account, account_id)
            acc.last_sync = now()
            acc.sync_status = 'failed' if successful_sections == 0 else ('partial' if warnings else 'done')
            acc.sync_error = '; '.join(warnings)[:500]
            audit(db, u, 'sync_now', 'accounts', account_id, {'channel':'Wildberries','sections':counts,'projection':projection})
            db.commit()
            return {'ok': successful_sections > 0, 'status':acc.sync_status,'account_id':account_id,
                    'sections':counts,'warnings':warnings,'records':total_records,
                    'staged_inserted':total_inserted,'staged_updated':total_updated,'erp_projection':projection}
        if acc.channel == "Kaspi" and acc.mode == "api":
            import json as _json
            cursor = acc.sync_cursor or None
            total_records = total_inserted = total_updated = 0
            incremental_projected = 0
            warnings = []
            # Project already-staged events from the active 7-day window first.
            # This recovers the recent rows saved before the incremental projector
            # was deployed, without waiting for the 90-day backfill to finish.
            try:
                cursor_state = _json.loads(cursor) if cursor else {}
            except (ValueError, TypeError):
                cursor_state = {}
            range_start = datetime.fromtimestamp(cursor_state["start_ms"] / 1000, timezone.utc).date() if cursor_state.get("start_ms") else (now() - timedelta(days=7)).date()
            range_end = datetime.fromtimestamp(cursor_state["until_ms"] / 1000, timezone.utc).date() if cursor_state.get("until_ms") else now().date()
            recent_projection = marketplace_pipeline.project_account(
                db, u, acc, date_from=range_start, date_to=range_end)
            incremental_projected += recent_projection.get("projected", 0)
            db.commit()
            recovery_attempt = 2 if "attempt=2" in (acc.sync_error or "") else (1 if "SYNC_RECOVERY_STARTED" in (acc.sync_error or "") else 0)
            recovery_in_progress = recovery_attempt > 0
            chunks = 0
            while True:
                result = worker.fetch(cursor)
                inserted, updated = _stage_marketplace_records(db, acc, result)
                batch_external_ids = [str(item.get("external_id") or "") for item in result.records
                                      if item.get("external_id")]
                if batch_external_ids:
                    batch_projection = marketplace_pipeline.project_account(
                        db, u, acc, external_ids=batch_external_ids)
                    incremental_projected += batch_projection.get("projected", 0)
                total_records += len(result.records)
                total_inserted += inserted
                total_updated += updated
                warnings.extend(result.warnings or [])
                cursor = result.next_cursor
                acc.sync_cursor = cursor or ""
                acc.last_sync = now()
                acc.sync_status = "running"
                acc.sync_error = (f"SYNC_RECOVERY_STARTED: attempt={recovery_attempt}" if recovery_in_progress
                                  else "; ".join(warnings)[-500:])
                db.commit()
                chunks += 1
                if not cursor:
                    break
                if chunks >= 20000:
                    raise AccessRequired("Kaspi: достигнут защитный лимит пачек синхронизации; повторите позже")
            projection = marketplace_pipeline.project_account(db, u, acc) if total_records else {"projected":0,"pending_erp":0}
            acc = db.get(Account, account_id)
            acc.last_sync = now()
            acc.sync_status = "partial" if warnings else "done"
            acc.sync_error = "; ".join(warnings)[:500]
            acc.sync_cursor = ""
            audit(db, u, "sync_now", "accounts", acc.id, {"channel":"Kaspi","records":total_records,"windows":chunks})
            db.commit()
            return {"ok":True,"status":acc.sync_status,"account_id":acc.id,"records":total_records,
                    "windows":chunks,"staged_inserted":total_inserted,"staged_updated":total_updated,
                    "incremental_projected":incremental_projected,
                    "warnings":warnings,"erp_projection":projection}
        result = worker.fetch(acc.sync_cursor or None)
        inserted, updated = _stage_marketplace_records(db, acc, result)
        db.flush()
        projection = marketplace_pipeline.project_account(db, u, acc)
        payload = __import__("fastapi").encoders.jsonable_encoder(asdict(result))
        payload["staged_inserted"] = inserted
        payload["staged_updated"] = updated
        payload["erp_projection"] = projection
        acc.last_sync = now()
        acc.sync_status = "partial" if result.warnings else "done"
        acc.sync_error = "; ".join(result.warnings or [])[:500]
        acc.sync_cursor = result.next_cursor or acc.sync_cursor or ""
        audit(db, u, "sync_now", "accounts", acc.id, {"channel": acc.channel, "records": len(result.records)})
        db.commit()
        return {"ok": True, "status": acc.sync_status, "account_id": acc.id, **payload}
    except Exception as exc:
        logger.exception("Marketplace sync failed for account %s", account_id)
        db.rollback()
        acc = db.get(Account, account_id)
        message = str(getattr(exc, "detail", exc))[:1000]
        if acc:
            acc.sync_status = "failed"
            acc.sync_error = message
            acc.last_sync = now()
            db.commit()
        raise HTTPException(422, message)



def _background_marketplace_sync(account_id, user_id, sections=None):
    with SessionLocal() as db:
        user = db.get(User, user_id)
        acc = db.get(Account, account_id)
        if not acc: return
        try:
            if not user or not user.active: raise HTTPException(403, 'Пользователь отключён')
            require(user, 'accounts', True)
            scope(user, acc.company_id)
            _perform_marketplace_sync(db, user, acc, sections=sections)
        except Exception as exc:
            logger.exception("Marketplace background sync failed for account %s", account_id)
            db.rollback()
            acc = db.get(Account, account_id)
            if acc:
                acc.sync_status = 'failed'
                acc.sync_error = str(getattr(exc, 'detail', exc))[:500]
                db.commit()


@app.get('/api/accounts/{id}/sync-status')
def account_sync_status(id: int, background_tasks: BackgroundTasks, u=Depends(current_user), db=Depends(get_db)):
    require(u, 'accounts')
    acc = db.get(Account, id)
    if not acc: raise HTTPException(404, 'Интеграция не найдена')
    scope(u, acc.company_id)
    recovery_attempt = 2 if "attempt=2" in (acc.sync_error or "") else (1 if "SYNC_RECOVERY_STARTED" in (acc.sync_error or "") else 0)
    last_sync = acc.last_sync
    if last_sync is not None and last_sync.tzinfo is None:
        last_sync = last_sync.replace(tzinfo=timezone.utc)
    if acc.sync_status == 'running' and (not last_sync or last_sync < now()-timedelta(seconds=SYNC_RUNNING_TIMEOUT_SECONDS)):
        # A worker can be killed by a deploy/restart. Mark the stale run and allow
        # at most two bounded recovery attempts for Kaspi.
        acc.sync_status = 'failed'
        prefix = f'SYNC_RECOVERY_STARTED: attempt={recovery_attempt}; ' if recovery_attempt else ''
        acc.sync_error = prefix + 'SYNC_TIMEOUT: синхронизация превысила лимит времени'
        db.commit()
    if (acc.channel == 'Kaspi' and acc.mode == 'api' and acc.sync_status == 'failed'
            and 'SYNC_TIMEOUT:' in (acc.sync_error or '') and recovery_attempt < 2):
        recovery_attempt += 1
        acc.sync_status = 'running'
        acc.last_sync = now()
        acc.sync_error = f'SYNC_RECOVERY_STARTED: attempt={recovery_attempt}'
        db.commit()
        background_tasks.add_task(_background_marketplace_sync, acc.id, u.id)
    counts = dict(db.execute(select(MarketplaceRecord.status, func.count()).where(
        MarketplaceRecord.account_id == id, MarketplaceRecord.company_id == acc.company_id).group_by(MarketplaceRecord.status)).all())
    return {'account_id':id, 'status':acc.sync_status, 'error':acc.sync_error,
            'last_sync':acc.last_sync, 'total_records':sum(counts.values()),
            'erp_projection':{'total_projected':counts.get('projected',0),
                              'pending_erp':sum(v for k,v in counts.items() if k.startswith('pending'))}}


@app.post("/api/accounts/{id}/test-connection")
def account_test_connection(id: int, u=Depends(current_user), db=Depends(get_db)):
    """Validate credentials through the same connector without staging ERP records."""
    require(u, "accounts", True)
    acc = db.get(Account, id)
    if not acc:
        raise HTTPException(404, "Интеграция не найдена")
    scope(u, acc.company_id)
    if not acc.active:
        raise HTTPException(409, "Аккаунт отключён. Подключите его заново")
    try:
        result = connector(acc, load_saved_credentials(db, acc.id)).test_connection()
        return {
            "ok": True,
            "account_id": acc.id,
            "channel": acc.channel,
            "message": result["message"],
            "records_checked": result["records_checked"],
        }
    except Exception as exc:
        message = str(getattr(exc, "detail", exc))[:500]
        raise HTTPException(422, message)


@app.get("/api/accounts/{id}/connection-status")
def account_connection_status(id: int, u=Depends(current_user), db=Depends(get_db)):
    require(u, "accounts")
    acc = db.get(Account, id)
    if not acc:
        raise HTTPException(404, "Аккаунт не найден")
    scope(u, acc.company_id)
    # Return secret NAMES only, never values.
    row = db.scalar(select(IntegrationSecret).where(IntegrationSecret.account_id == acc.id))
    credential_error = ""
    try:
        creds = load_saved_credentials(db, acc.id)
    except AccessRequired as exc:
        creds = {}
        credential_error = str(exc)
    status = connector(acc, creds).connection_status()
    return {**status, "account_id": acc.id, "channel": acc.channel, "sync_status": acc.sync_status,
            "last_sync": acc.last_sync, "sync_error": acc.sync_error, "saved_on_site": bool(row),
            "credential_hint": row.key_hint if row else "", "credential_error": credential_error}


def _validate_product_card(db, card):
    product = db.get(Product, card.product_id)
    errors=[]; warnings=[]
    if not product: errors.append("Товар не найден")
    if not card.title.strip(): errors.append("Название обязательно")
    if not card.description.strip(): errors.append("Описание обязательно")
    if not card.image_document_ids: errors.append("Нужно минимум одно изображение товара")
    facts={"brand": getattr(product,"brand",None), "country": getattr(product,"country",None), "weight": getattr(product,"weight_g",None), "volume": getattr(product,"volume_cm3",None)} if product else {}
    # Claims explicitly marked as sourced must match ERP facts. Unknown claims are rejected.
    for key,val in (card.characteristics or {}).items():
        if key in facts and facts[key] not in (None, "") and str(val).strip()!=str(facts[key]).strip(): errors.append(f"{key}: значение не совпадает с ERP")
        elif key in facts and facts[key] in (None, ""): errors.append(f"{key}: характеристика не подтверждена ERP")
    if card.marketplace not in {"kaspi","wildberries","ozon"}: errors.append("Неподдерживаемый marketplace")
    return {"marketplace":card.marketplace,"passed":not errors,"errors":errors,"warnings":warnings,"checked_at":datetime.now(timezone.utc).isoformat(),"rule_set":"qor-marketplace-safe-v1","note":"Финальная модерация выполняется самим marketplace; QOR не гарантирует принятие площадкой."}

@app.get("/api/product-studio/cards")
def product_cards(product_id: int | None = None, u=Depends(current_user), db=Depends(get_db)):
    require(u,"marketing")
    q=select(ProductCardVersion).order_by(ProductCardVersion.id.desc())
    if product_id: q=q.where(ProductCardVersion.product_id==product_id)
    rows=db.scalars(q).all(); out=[]
    for x in rows:
        scope(u,x.company_id); out.append(dump(x))
    return {"items":out}

@app.post("/api/product-studio/cards")
def product_card_create(p: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u,"marketing",True)
    product=db.get(Product,int(p.get("product_id") or 0))
    if not product: raise HTTPException(404,"Товар не найден")
    cid=int(p.get("company_id") or 0)
    if not cid: raise HTTPException(422,"company_id обязателен для карточки")
    scope_product(db,u,product.id,cid)
    mp=str(p.get("marketplace","kaspi")).lower()
    prev=db.scalar(select(func.max(ProductCardVersion.version)).where(ProductCardVersion.product_id==product.id,ProductCardVersion.marketplace==mp)) or 0
    obj=ProductCardVersion(company_id=cid,product_id=product.id,marketplace=mp,version=prev+1,title=str(p.get("title") or product.name)[:240],description=str(p.get("description") or ""),characteristics=p.get("characteristics") or {},image_document_ids=[int(x) for x in p.get("image_document_ids",[])],parent_version_id=p.get("parent_version_id"))
    db.add(obj); db.flush(); obj.validation=_validate_product_card(db,obj); obj.status="validated" if obj.validation["passed"] else "needs_fix"; audit(db,u,"create","product_card_versions",obj.id,{"marketplace":mp,"version":obj.version}); db.commit(); return dump(obj)

@app.post("/api/product-studio/cards/{id}/validate")
def product_card_validate(id:int,u=Depends(current_user),db=Depends(get_db)):
    require(u,"marketing",True); obj=db.get(ProductCardVersion,id)
    if not obj: raise HTTPException(404,"Карточка не найдена")
    scope(u,obj.company_id); obj.validation=_validate_product_card(db,obj); obj.status="validated" if obj.validation["passed"] else "needs_fix"; db.commit(); return dump(obj)

@app.post("/api/product-studio/cards/{id}/publish")
def product_card_publish(id:int,p:dict,u=Depends(current_user),db=Depends(get_db)):
    require(u,"marketing",True); obj=db.get(ProductCardVersion,id)
    if not obj: raise HTTPException(404,"Карточка не найдена")
    scope(u,obj.company_id); obj.validation=_validate_product_card(db,obj)
    if not obj.validation["passed"]: raise HTTPException(422,"Карточка не прошла QOR Validator")
    # Never fake marketplace publication. Until a live write adapter is connected, mark ready_for_publish only.
    obj.status="ready_for_publish"; obj.review_after=datetime.now(timezone.utc)+timedelta(days=max(1,int(p.get("review_days",7)))); obj.review_state="scheduled"; obj.optimization_policy={"auto_optimize":bool(p.get("auto_optimize",True)),"auto_publish":bool(p.get("auto_publish",False)),"rollback":bool(p.get("rollback",True)),"review_days":max(1,int(p.get("review_days",7))),"max_generations":max(1,min(10,int(p.get("max_generations",3))))}
    audit(db,u,"ready_for_publish","product_card_versions",obj.id,{"review_after":obj.review_after.isoformat()}); db.commit(); return dump(obj)

@app.post("/api/product-studio/cards/{id}/metrics")
def product_card_metrics(id:int,p:dict,u=Depends(current_user),db=Depends(get_db)):
    require(u,"marketing",True); obj=db.get(ProductCardVersion,id)
    if not obj: raise HTTPException(404,"Карточка не найдена")
    scope(u,obj.company_id); allowed={k:p[k] for k in ("impressions","views","clicks","orders","revenue","returns","ad_spend","conversion") if k in p}; obj.metrics={**(obj.metrics or {}),**allowed,"observed_at":datetime.now(timezone.utc).isoformat()}; db.commit(); return dump(obj)

@app.post("/api/product-studio/cards/{id}/optimize")
def product_card_optimize(id:int,u=Depends(current_user),db=Depends(get_db)):
    require(u,"marketing",True); obj=db.get(ProductCardVersion,id)
    if not obj: raise HTTPException(404,"Карточка не найдена")
    scope(u,obj.company_id); m=obj.metrics or {}
    if not m or not any(k in m for k in ("views","clicks","orders","conversion")): raise HTTPException(422,"Данные недостаточны для точного вывода")
    assessment=assess_performance(m)
    if assessment["decision"] == "insufficient_data": raise HTTPException(422,assessment["reason"])
    reason=assessment["reason"]; experiment=next_experiment(obj.version)
    prev=db.scalar(select(func.max(ProductCardVersion.version)).where(ProductCardVersion.product_id==obj.product_id,ProductCardVersion.marketplace==obj.marketplace)) or obj.version
    new=ProductCardVersion(company_id=obj.company_id,product_id=obj.product_id,marketplace=obj.marketplace,version=prev+1,title=obj.title,description=obj.description,characteristics=obj.characteristics,image_document_ids=obj.image_document_ids,status="optimization_draft",parent_version_id=obj.id,optimization_policy=obj.optimization_policy or {},review_state="idle",validation={"passed":False,"errors":[],"warnings":[reason],"requires_ai_regeneration":True,"experiment":experiment})
    db.add(new); db.flush(); audit(db,u,"optimize_proposal","product_card_versions",new.id,{"parent":obj.id,"reason":reason}); db.commit(); return dump(new)

@app.get("/api/ai/threads")
def ai_threads(u=Depends(current_user), db=Depends(get_db)):
    require(u, "ai")
    rows = db.scalars(select(AIThread).where(AIThread.user_id == u.id, AIThread.archived == False).order_by(AIThread.id.desc())).all()
    return {"items": [dump(x) for x in rows]}


@app.post("/api/ai/threads")
def ai_thread_create(p: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u, "ai", True)
    agent = str(p.get("agent", "rick"))
    if agent not in ai.AI_AGENTS:
        raise HTTPException(422, "Неизвестный AI-сотрудник")
    cid = p.get("company_id")
    if cid:
        f.get_company(db, u, int(cid))
    obj = AIThread(user_id=u.id, company_id=int(cid) if cid else None, agent=agent, title=str(p.get("title") or "Новый чат")[:180])
    db.add(obj); db.flush(); audit(db, u, "create", "ai_threads", obj.id); db.commit()
    return dump(obj)


@app.get("/api/ai/threads/{id}/messages")
def ai_thread_messages(id: int, u=Depends(current_user), db=Depends(get_db)):
    require(u, "ai")
    t = db.get(AIThread, id)
    if not t or t.user_id != u.id or t.archived:
        raise HTTPException(404, "Чат не найден")
    rows = db.scalars(select(AIMessage).where(AIMessage.thread_id == id).order_by(AIMessage.id)).all()
    return {"thread": dump(t), "items": [dump(x) for x in rows]}


@app.post("/api/ai/threads/{id}/messages")
def ai_thread_message(id: int, p: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u, "ai", True)
    t = db.get(AIThread, id)
    if not t or t.user_id != u.id or t.archived:
        raise HTTPException(404, "Чат не найден")
    role = str(p.get("role", "user"))
    if role not in ("user", "assistant"):
        raise HTTPException(422, "Некорректная роль")
    content = str(p.get("content", "")).strip()[:20000]
    attachments = p.get("attachments") or []
    if not content and not attachments:
        raise HTTPException(422, "Пустое сообщение")
    safe_attachments = []
    for item in attachments[:8]:
        did = int(item.get("document_id"))
        d = db.get(Document, did)
        if not d:
            raise HTTPException(404, "Вложение не найдено")
        scope(u, d.company_id)
        safe_attachments.append({"document_id": d.id, "name": d.name, "mime": d.mime})
    obj = AIMessage(thread_id=id, role=role, content=content, attachments=safe_attachments, meta=p.get("meta") or {})
    db.add(obj)
    if role == "user" and t.title == "Новый чат" and content:
        t.title = content.replace("\n", " ")[:70]
    db.commit()
    return dump(obj)


@app.patch("/api/ai/threads/{id}")
def ai_thread_update(id: int, p: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u, "ai", True)
    t = db.get(AIThread, id)
    if not t or t.user_id != u.id:
        raise HTTPException(404, "Чат не найден")
    if "title" in p: t.title = str(p["title"]).strip()[:180] or "Новый чат"
    if "agent" in p:
        if p["agent"] not in ai.AI_AGENTS: raise HTTPException(422, "Неизвестный AI-сотрудник")
        t.agent = p["agent"]
    if "archived" in p: t.archived = bool(p["archived"])
    db.commit(); return dump(t)


@app.get("/api/ai/actions")
def ai_actions(status: str | None = None, u=Depends(current_user), db=Depends(get_db)):
    require(u, "ai")
    q=select(AIAction).where(AIAction.user_id==u.id)
    if status: q=q.where(AIAction.status==status)
    rows=db.scalars(q.order_by(AIAction.id.desc()).limit(100)).all()
    return {"items":[dump(x) for x in rows],"catalog":action_engine.catalog()}

@app.post("/api/ai/actions/propose")
def ai_action_propose(p: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u,"ai",True)
    row=action_engine.propose(db,u,str(p.get("action_type","")),p.get("payload") or {},p.get("thread_id"),str(p.get("agent","rick")))
    return dump(row)

@app.post("/api/ai/actions/{id}/confirm")
def ai_action_confirm(id:int,tasks:BackgroundTasks,u=Depends(current_user),db=Depends(get_db)):
    require(u,"ai",True); row=db.get(AIAction,id)
    if not row: raise HTTPException(404,"Действие не найдено")
    return dump(action_engine.execute(db,u,row,tasks=tasks))

@app.post("/api/ai/actions/{id}/cancel")
def ai_action_cancel(id:int,u=Depends(current_user),db=Depends(get_db)):
    require(u,"ai",True); row=db.get(AIAction,id)
    if not row: raise HTTPException(404,"Действие не найдено")
    return dump(action_engine.cancel(db,u,row))

@app.get("/api/ai/plans")
def ai_plans(status: str | None = None, u=Depends(current_user), db=Depends(get_db)):
    require(u,"ai")
    q=select(AIActionPlan).where(AIActionPlan.user_id==u.id)
    if status: q=q.where(AIActionPlan.status==status)
    return {"items":[dump(x) for x in db.scalars(q.order_by(AIActionPlan.id.desc()).limit(50)).all()]}

@app.post("/api/ai/plans/propose")
def ai_plan_propose(p: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u,"ai",True)
    return dump(action_engine.propose_plan(db,u,p.get("title"),p.get("goal"),p.get("steps") or [],p.get("thread_id"),str(p.get("agent","rick"))))

@app.post("/api/ai/plans/{id}/confirm")
def ai_plan_confirm(id:int,tasks:BackgroundTasks,u=Depends(current_user),db=Depends(get_db)):
    require(u,"ai",True); row=db.get(AIActionPlan,id)
    if not row: raise HTTPException(404,"План не найден")
    return dump(action_engine.execute_plan(db,u,row,tasks=tasks))

@app.post("/api/ai/plans/{id}/cancel")
def ai_plan_cancel(id:int,u=Depends(current_user),db=Depends(get_db)):
    require(u,"ai",True); row=db.get(AIActionPlan,id)
    if not row: raise HTTPException(404,"План не найден")
    return dump(action_engine.cancel_plan(db,u,row))

@app.post("/api/jobs")
def enqueue(p: dict, tasks: BackgroundTasks, u=Depends(current_user), db=Depends(get_db)):
    kind = p.get("kind")
    payload = p.get("payload", {})
    if kind == "sync":
        raise HTTPException(410, "Marketplace sync перенесён в /api/accounts/{id}/sync-now")
    elif kind in ("assistant", "content", "designer"):
        require(u, "ai" if kind == "assistant" else "marketing", True)
        if kind == "assistant":
            require(u, "analytics")
        cid = payload.get("company_id")
        if cid:
            f.get_company(db, u, int(cid))
        if kind == "designer" and not cid:
            raise HTTPException(422, "Выберите компанию")
    else:
        raise HTTPException(422, "Неизвестное задание")
    job = Job(user_id=u.id, company_id=cid, kind=kind, payload=payload)
    db.add(job)
    db.flush()
    audit(db, u, "enqueue", "jobs", job.id)
    db.commit()
    if kind in ("assistant", "content", "designer"):
        # Return the job immediately; provider calls can take minutes. The worker
        # uses a fresh DB session after the HTTP response has been sent.
        from .worker import run_one
        tasks.add_task(run_one, job.id)
    return dump(job)


@app.get("/api/jobs/{id}")
def job_status(id: int, u=Depends(current_user), db=Depends(get_db)):
    job = db.get(Job, id)
    if not job or job.user_id != u.id:
        raise HTTPException(404, "Задание не найдено")
    stale_after = timedelta(hours=2) if job.kind == "marketplace_catalog_refresh" else timedelta(minutes=15)
    if (job.status == "running" and job.started_at
            and job.started_at < now() - stale_after):
        job.status = "failed"
        job.error = ("Загрузка каталога прервана сервером. Повторите задание: прогресс страниц сохранён."
                     if job.kind == "marketplace_catalog_refresh" else
                     "AI-задание прервано сервером. Проверьте подключение AI и повторите запрос.")
        db.commit()
    return dump(job)


@app.post("/api/jobs/{id}/retry")
def retry_job(id: int, tasks: BackgroundTasks, u=Depends(current_user), db=Depends(get_db)):
    job = db.get(Job, id)
    if not job or job.user_id != u.id:
        raise HTTPException(404, "Не найдено")
    if job.kind == "marketplace_catalog_refresh" and job.status in {"failed", "partial"} and job.attempts < 3:
        job.status = "queued"
        job.error = ""
        db.commit()
        tasks.add_task(_run_wb_product_catalog_refresh, job.id)
        return dump(job)
    if job.status != "failed" or job.attempts >= 3:
        raise HTTPException(409, "Повтор недоступен")
    if job.kind == "card_review":
        job.status = "queued"
        job.error = ""
        db.commit()
        return dump(job)
    payload = dict(job.payload or {})
    kind = job.kind
    db.delete(job)
    db.commit()
    return enqueue({"kind": kind, "payload": payload}, tasks, u, db)


@app.post("/api/documents/upload")
async def upload(
    company_id: int = Form(...),
    file: UploadFile = File(...),
    u=Depends(current_user),
    db=Depends(get_db),
):
    require(u, "documents", True)
    f.get_company(db, u, company_id)
    raw = await file.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "Максимум 5 МБ")
    ext = Path(file.filename or "").suffix.lower()
    allowed_types = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".csv": "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    if ext not in allowed_types:
        raise HTTPException(422, "Разрешены PDF, PNG, JPEG, WebP, CSV, XLSX")
    if ext in (".png", ".jpg", ".jpeg", ".webp"):
        from PIL import Image

        try:
            im = Image.open(io.BytesIO(raw))
            im.verify()
            if im.width * im.height > 25_000_000:
                raise ValueError()
        except Exception:
            raise HTTPException(422, "Некорректное или слишком большое изображение")
    if ext == ".pdf" and not raw.startswith(b"%PDF"):
        raise HTTPException(422, "Некорректный PDF")
    root = Path(os.getenv("UPLOAD_DIR", "./uploads"))
    root.mkdir(parents=True, exist_ok=True)
    path = root / (uuid.uuid4().hex + ext)
    path.write_bytes(raw)
    obj = Document(
        company_id=company_id,
        name=Path(file.filename).name[:200],
        path=str(path.resolve()),
        mime=allowed_types[ext],
        size=len(raw),
    )
    db.add(obj)
    db.flush()
    audit(db, u, "upload", "documents", obj.id)
    db.commit()
    return dump(obj)


@app.get("/api/documents/{id}/download")
def download(id: int, u=Depends(current_user), db=Depends(get_db)):
    require(u, "documents")
    d = db.get(Document, id)
    if not d:
        raise HTTPException(404, "Не найдено")
    scope(u, d.company_id)
    if not Path(d.path).exists():
        raise HTTPException(404, "Файл отсутствует в хранилище")
    return FileResponse(d.path, filename=d.name, media_type=d.mime)


@app.get("/api/sales/{id}/invoice")
def invoice(id: int, u=Depends(current_user), db=Depends(get_db)):
    require(u, "sales")
    sale = db.get(Sale, id)
    if not sale:
        raise HTTPException(404, "Не найдено")
    scope(u, sale.company_id)
    import html

    company = db.get(Company, sale.company_id)
    product = db.get(Product, sale.product_id)
    customer = db.get(Customer, sale.customer_id) if sale.customer_id else None
    esc = html.escape
    body = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><title>Счёт {esc(sale.reference)}</title><style>body{{font:16px Arial;max-width:800px;margin:60px auto}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #aaa;padding:14px}}</style><h1>Счёт на оплату № {esc(sale.reference)}</h1><p>Дата: {sale.date}</p><p>Поставщик: {esc(company.name)} · БИН/ИИН {esc(company.bin)}</p><p>Покупатель: {esc(customer.name) if customer else "Розничный покупатель"}</p><table><tr><th>Товар</th><th>Количество</th><th>Сумма KZT</th></tr><tr><td>{esc(product.name)}</td><td>{sale.quantity}</td><td>{sale.revenue / 100:,.2f}</td></tr></table><p>Управленческий документ. Банковские реквизиты и налоговые реквизиты необходимо дополнить перед отправкой.</p></html>"""
    return Response(
        body,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="invoice-{id}.html"'},
    )


@app.get("/api/import/fields/{kind}")
def import_fields(kind: str, u=Depends(current_user)):
    if kind not in importing.KINDS:
        raise HTTPException(404, "Нет такого типа")
    require(u, importing.KINDS[kind][0], True)
    return {
        "fields": importing.FIELDS[kind],
        "money_unit": "KZT (decimal); dates YYYY-MM-DD; IDs from directories",
    }


@app.post("/api/import/parse")
async def import_parse(file: UploadFile = File(...), sheet: str | None = Form(None), header_row: int | None = Form(None), u=Depends(current_user)):
    if not any(
        allowed(u, c, True) for c in ("catalog", "inventory", "sales", "finance")
    ):
        raise HTTPException(403, "Нет прав импорта")
    raw = await file.read(5 * 1024 * 1024 + 1)
    try:
        metadata = {}
        headers, rows = importing.parse_file(raw, file.filename, sheet, header_row, metadata)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            422, "Не удалось прочитать файл; проверьте формат и кодировку UTF-8"
        )
    return {"headers": headers, "rows": rows, "count": len(rows), **metadata}


@app.post("/api/import/preview")
def import_preview(p: dict, u=Depends(current_user), db=Depends(get_db)):
    if len(p.get("rows", [])) > 5000:
        raise HTTPException(413, "Максимум 5000 строк")
    run, normalized = importing.preview(db, u, p["kind"], p["rows"], p["mapping"], p.get("defaults"))
    db.commit()
    return {**dump(run), "preview": normalized[:30], "count": len(run.rows)}


@app.post("/api/import/{id}/confirm")
def import_confirm(id: int, u=Depends(current_user), db=Depends(get_db)):
    run = db.scalar(select(ImportRun).where(ImportRun.id == id).with_for_update())
    if not run:
        raise HTTPException(404, "Не найдено")
    count = importing.confirm(db, u, run)
    db.commit()
    return {"count": count}


@app.get("/api/import/{id}/errors")
def import_errors(id: int, u=Depends(current_user), db=Depends(get_db)):
    run = db.get(ImportRun, id)
    if not run or run.user_id != u.id:
        raise HTTPException(404, "Не найдено")
    return Response(
        importing.export_bytes(run.errors, ["row", "error"], "csv"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="errors.csv"'},
    )


@app.get("/api/export/{entity}")
def export(
    entity: str, format: str = "csv", start: date | None = None, end: date | None = None,
    company_id: int | None = None, u=Depends(current_user), db=Depends(get_db)
):
    if format not in ("csv", "xlsx"):
        raise HTTPException(422, "Формат csv или xlsx")
    aliases = {"bank": "cash", "reports": "sales", "b2b": "sales", "stock": "movements"}
    resolved = aliases.get(entity, entity)
    if start and end and end < start:
        raise HTTPException(422, "Дата окончания раньше даты начала")
    q = access_query(db, u, resolved, company_id=company_id)
    model = MODELS[resolved][0]
    if start and hasattr(model, "date"):
        q = q.where(model.date >= start)
    if end and hasattr(model, "date"):
        q = q.where(model.date <= end)
    if entity == "b2b":
        q = q.where(
            Sale.account_id.in_(select(Account.id).where(Account.channel == "B2B"))
        )
    data = [dump(x) for x in db.scalars(q.order_by(MODELS[resolved][0].id))]
    if len(data) > 50000:
        raise HTTPException(
            413, "Слишком большой экспорт; используйте резервную копию БД"
        )
    for row in data:
        for k, v in list(row.items()):
            if k in importing.MONEY | {
                "revenue",
                "cogs",
                "cost",
                "total",
                "total_cost",
                "remaining_cost",
                "returned_cost",
            } and isinstance(v, int):
                row[k] = str(__import__("decimal").Decimal(v) / 100)
    fields = (
        list(data[0])
        if data
        else [
            c.name
            for c in MODELS[resolved][0].__table__.columns
            if c.name not in ("password_hash", "token_hash", "path", "rows")
        ]
    )
    return Response(
        importing.export_bytes(data, fields, format),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{entity}.{format}"'},
    )


@app.get("/api/templates/{kind}")
def template(kind: str, format: str = "csv", u=Depends(current_user)):
    if kind not in importing.FIELDS:
        raise HTTPException(404, "Не найдено")
    return Response(
        importing.export_bytes([], importing.FIELDS[kind], format),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="template-{kind}.{format}"'
        },
    )


static = Path(os.getenv("FRONTEND_DIST", "../frontend/dist"))
if static.exists() and (static / "assets").exists():
    app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.head("/")
    def frontend_head():
        return Response(status_code=200)

    @app.get("/{path:path}")
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "API route not found")
        if path.startswith("public/kaspi-feeds/"):
            raise HTTPException(404, "Прайс-лист не найден")
        return FileResponse(static / "index.html")

