from dataclasses import asdict
import os, secrets, json, hashlib, uuid, io, base64, logging, threading, time
from pathlib import Path
from datetime import datetime, timedelta, timezone, date
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
from sqlalchemy import select, func, or_, text, update, cast, String
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field, ValidationError
from .db import get_db, SessionLocal
from .models import *
from .security import *
from . import schemas as s, finance as f, importing, ai, action_engine, reporting_xlsx, marketplace_pipeline, canonical, wb_weekly, marketplace_costs
from .connectors import AccessRequired, connector, load_saved_credentials
from cryptography.fernet import Fernet, InvalidToken
from .product_studio import assess_performance, next_experiment

app = FastAPI(
    title="QOR Business ERP",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
logger = logging.getLogger(__name__)
SYNC_RUNNING_TIMEOUT_SECONDS = max(60, int(os.getenv("MARKETPLACE_SYNC_TIMEOUT_SECONDS", "1800")))


def sync_status_for_display(account, at=None):
    """Hide abandoned running states after the last persisted sync heartbeat."""
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
WB_DEFAULT_SYNC_SECTIONS = ("new_orders", "order", "sale")
WB_ALLOWED_SYNC_SECTIONS = frozenset(("new_orders", "order", "sale", "realization", "stocks", "products"))


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
    if company_id and hasattr(model, "company_id"):
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
                MarketplaceRecord.account_id.in_(account_ids), MarketplaceRecord.source == "kaspi")
            for account_id, payload in db.execute(raw_q):
                p = payload or {}
                if p.get("record_type") != "order_entry":
                    continue
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
                    "source":"Kaspi order items","orders":[]})
                try:
                    qty = int(p.get("quantity") or 0)
                    amount = float(p.get("total_price") or 0)
                except (TypeError, ValueError):
                    qty, amount = 0, 0
                row["lifetime_sold_units"] += qty
                row["lifetime_revenue"] += amount
                row["orders"].append({"order_id":p.get("order_id"),"status":p.get("order_status"),
                    "date":day.isoformat() if day else None,"quantity":qty,"total_price":amount})
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
        out.append({"id": product.id, "sku": product.sku, "article": product.article, "name": product.name, "brand": product.brand, "category": product.category,
            "image_url": (product.media or [None])[0], "images": product.media or [], "price": product.price, "currency": product.currency,
            "sold_units": period_qty, "revenue": period_revenue, "lifetime_sold_units": lifetime_qty, "lifetime_revenue": lifetime_revenue, "unconverted_sales": unconverted,
            "cogs": cogs, "commission": commission, "logistics": logistics, "advertising": advertising,
            "profit": None if any(x.id in pending_ids for x in period_sales) else sum(x.revenue for x in period_sales)-cogs-commission-logistics-advertising,
            "account_id": account_ids[0],
            "unit_cost": (lambda row: str(Decimal(row.unit_cost) / 100) if row else None)(marketplace_costs.latest_cost(db, account_ids[0], account_keys.get((pid, account_ids[0]), set()), end or business_today())),
            "cost_effective_from": (lambda row: str(row.effective_from) if row else None)(marketplace_costs.latest_cost(db, account_ids[0], account_keys.get((pid, account_ids[0]), set()), end or business_today())),
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
    scope(u, account.company_id)
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

    raw_rate = configured_rate if configured_rate is not None else os.getenv("KASPI_COMMISSION_RATE", "0.12")
    try:
        rate = Decimal(str(raw_rate))
        if not rate.is_finite() or rate < 0 or rate > 1:
            raise InvalidOperation
    except (InvalidOperation, ValueError, TypeError):
        rate = Decimal("0.12")
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


@app.get("/api/marketplace-summary")
def marketplace_summary(channel: str, start: date, end: date, company_id: int | None = None, u=Depends(current_user), db=Depends(get_db)):
    """Fast marketplace page summary; bounded to the selected channel and period."""
    require(u, "analytics")
    if end < start:
        raise HTTPException(422, "Дата окончания раньше даты начала")
    if channel not in {"Kaspi", "Wildberries", "Ozon"}: raise HTTPException(422, "Неподдерживаемый маркетплейс")
    aq = select(Account).where(Account.channel == channel, Account.active.is_(True))
    if u.role != "Owner": aq = aq.where(Account.company_id.in_(u.company_ids or []))
    if company_id is not None: scope(u, company_id); aq = aq.where(Account.company_id == company_id)
    accounts = list(db.scalars(aq)); ids = [a.id for a in accounts]; by_id = {a.id:a for a in accounts}
    sync_in_progress = any(str(a.sync_status or '').lower() == 'running' for a in accounts)
    if not ids:
        return {'channel':channel,'start':str(start),'end':str(end),'revenue':0,'units':0,'api_gross_revenue':0,'api_revenue':0,'api_units':0,'api_returns':0,'api_return_units':0,'api_unconverted':0,'pending_sales':0,'pending_reasons':{},'financial_complete':True,'cogs':0,'costs':0,'commission':0,'logistics':0,'return_logistics':0,'kaspi_estimated_proceeds':None,'advertising':0,'returns':0,'return_units':0,'settlement_accrued':0,'settlement_rows':0,'settlement_unconverted':0,'net_profit':0,'margin':None,'sync_in_progress':False,'source_complete':True}

    sales = list(db.scalars(select(Sale).where(Sale.account_id.in_(ids), Sale.date >= start, Sale.date <= end)))
    period_returns = list(db.scalars(select(Return).join(Sale, Return.sale_id == Sale.id).where(Sale.account_id.in_(ids), Return.date >= start, Return.date <= end)))
    sale_cogs, return_cogs, pending_ids = marketplace_costs.resolve_cost_overrides(db, sales, period_returns, by_id)
    return_revenue = sum(x.revenue for x in period_returns); return_units = sum(x.quantity for x in period_returns)
    revenue = sum(x.revenue for x in sales) - return_revenue; units = sum(x.quantity for x in sales) - return_units
    restocked_returns = [x for x in period_returns if x.inventory_status == "restocked"]
    cogs = sum(sale_cogs.get(x.id, x.cogs) for x in sales) - sum(return_cogs.get(x.id, x.cogs) for x in restocked_returns); commission = sum(x.commission for x in sales)
    logistics = sum(x.logistics for x in sales); advertising = sum(x.advertising for x in sales)
    pending = sum(1 for x in sales if x.id in pending_ids)
    # Marketplace expenses may be posted independently from a Sale.
    expenses = list(db.scalars(select(Expense).where(Expense.account_id.in_(ids), Expense.date >= start, Expense.date <= end)))
    commission += sum(x.amount for x in expenses if x.category in {"Marketplace commission", "Marketplace commission VAT"})
    commission_estimated = 0
    commission_rate = None
    commission_estimate_suppressed = False
    logistics += sum(x.amount for x in expenses if x.category == "Marketplace logistics")
    return_logistics = sum(x.amount for x in expenses if x.category == "Marketplace return logistics")
    advertising += sum(x.amount for x in expenses if x.category == "Реклама")
    other = sum(x.amount for x in expenses if x.category not in {"Marketplace commission","Marketplace commission VAT","Marketplace logistics","Marketplace return logistics","Реклама"})

    api_gross_revenue=api_revenue=api_units=api_unconverted=api_returns=api_return_units=settlement_accrued=settlement_rows=settlement_unconverted=0
    raw_kaspi_commission_bases = {}
    raw_q = select(MarketplaceRecord.account_id, MarketplaceRecord.payload).where(MarketplaceRecord.account_id.in_(ids), MarketplaceRecord.source == channel.lower())
    for account_id, payload in db.execute(raw_q):
        p=payload or {}; typ=str(p.get('record_type') or '').lower(); src=channel.lower()
        try:
            if src=='wildberries' and typ=='sale' and not str(p.get('saleID') or '').upper().startswith('R') and not p.get('isStorno'):
                dt=p.get('date'); day=marketplace_pipeline._day(dt)
                if start<=day<=end:
                    api_units += 1; amount=p.get('priceWithDisc') if p.get('priceWithDisc') is not None else p.get('finishedPrice')
                    try: api_revenue += marketplace_pipeline._cents(amount,by_id[account_id],p.get('currency') or 'RUB',db,dt)
                    except marketplace_pipeline.Pending: api_unconverted += 1
            elif src=='wildberries' and typ=='realization':
                dt=p.get('rrDate') or p.get('rr_dt') or p.get('saleDt') or p.get('sale_dt'); day=marketplace_pipeline._day(dt)
                if start<=day<=end:
                    value=next((p.get(k) for k in ('forPay','ppvzForPay','ppvz_for_pay') if p.get(k) is not None), None)
                    if value is not None:
                        try: settlement_accrued += marketplace_pipeline._cents(wb_weekly.signed_wb_sale_amount(p, value),by_id[account_id],p.get('currency') or p.get('currency_name') or 'RUB',db,dt); settlement_rows += 1
                        except marketplace_pipeline.Pending: settlement_unconverted += 1
            elif src=='ozon' and typ=='posting' and str(p.get('status') or '').lower() in {'delivered','completed'}:
                dt=p.get('delivered_at') or p.get('shipment_date') or p.get('created_at'); day=marketplace_pipeline._day(dt)
                if start<=day<=end:
                    for x in p.get('products') or []:
                        qty=int(x.get('quantity') or 0); api_units+=qty
                        try: api_revenue += marketplace_pipeline._cents(marketplace_pipeline._number(x.get('price'))*qty,by_id[account_id],x.get('currency_code') or p.get('currency_code') or 'RUB',db,dt)
                        except marketplace_pipeline.Pending: api_unconverted += 1
            elif src=='kaspi' and typ=='order_entry':
                status=str(p.get('order_status') or '').upper()
                returned=status in {'RETURNED','ARRIVED_BACKWARD'}
                if status=='COMPLETED' or returned:
                    sale_dt=p.get('completed_date') or p.get('order_creation_date')
                    sale_day=marketplace_pipeline._day(sale_dt, 'Asia/Almaty')
                    qty=int(p.get('quantity') or 0)
                    try:
                        sale_amount=marketplace_pipeline._cents(p.get('total_price'),by_id[account_id],'KZT',db,sale_dt)
                        if start<=sale_day<=end:
                            api_gross_revenue += sale_amount
                            api_revenue += sale_amount
                            api_units += qty
                            if status=='COMPLETED':
                                key=(account_id,sale_day)
                                raw_kaspi_commission_bases[key]=raw_kaspi_commission_bases.get(key,0)+sale_amount
                        if returned:
                            return_dt=p.get('returned_date') or p.get('return_date') or p.get('completed_date') or p.get('order_creation_date')
                            return_day=marketplace_pipeline._day(return_dt, 'Asia/Almaty')
                            if start<=return_day<=end:
                                api_returns += sale_amount
                                api_return_units += qty
                                api_revenue -= sale_amount
                                api_units -= qty
                    except marketplace_pipeline.Pending:
                        api_unconverted += 1
        except (marketplace_pipeline.Pending, ValueError, TypeError, KeyError):
            continue
    if channel == "Kaspi":
        commission_estimated, commission_rate, commission_estimate_suppressed = _kaspi_commission_estimate(
            sales, expenses, raw_kaspi_commission_bases
        )
        commission += commission_estimated
    pending_return_inspection_units = sum(x.quantity for x in period_returns if x.inventory_status in {"requested", "approved", "in_transit", "received", "inspection"})
    profit = None if pending or pending_return_inspection_units else revenue-cogs-commission-logistics-return_logistics-advertising-other
    kaspi_estimated_proceeds = api_revenue - commission - logistics - return_logistics if channel == "Kaspi" else None
    return {'channel':channel,'start':str(start),'end':str(end),'revenue':revenue,'units':units,'api_gross_revenue':api_gross_revenue,'api_revenue':api_revenue,'api_units':api_units,'api_returns':api_returns,'api_return_units':api_return_units,'api_unconverted':api_unconverted,
        'pending_sales':pending,'pending_return_inspection_units':pending_return_inspection_units,'pending_reasons':{'COGS_PENDING':pending} if pending else {},'financial_complete':not pending and not api_unconverted and not pending_return_inspection_units,
        'cogs':cogs,'costs':commission+logistics+return_logistics+advertising+other,'commission':commission,'commission_estimated':commission_estimated,'commission_rate':commission_rate,'commission_estimate_suppressed':commission_estimate_suppressed,'logistics':logistics,'return_logistics':return_logistics,'kaspi_estimated_proceeds':kaspi_estimated_proceeds,'advertising':advertising,'returns':return_revenue,'return_units':return_units,
        'settlement_accrued':settlement_accrued if settlement_rows else None,'settlement_rows':settlement_rows,'settlement_unconverted':settlement_unconverted,'net_profit':profit,
        'margin':round(profit/revenue*100,2) if revenue and profit is not None else None,'sync_in_progress':sync_in_progress,'source_complete':not sync_in_progress and not api_unconverted}


@app.post("/api/wildberries/weekly-excel-preview")
async def wb_weekly_excel_preview(file: UploadFile = File(...), u=Depends(current_user)):
    """Preview official weekly WB report without modifying any financial records."""
    require(u, "analytics")
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(422, "Нужен оригинальный отчёт WB в формате .xlsx")
    from .wb_excel_reconciliation import parse_report
    try:
        return parse_report(await file.read(5 * 1024 * 1024 + 1))
    except (ValueError, StopIteration, OSError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/wildberries/reconciliation")
def wildberries_reconciliation(start: date, end: date, company_id: int | None = None,
                               limit: int = Query(default=100, ge=1, le=500),
                               offset: int = Query(default=0, ge=0),
                               u=Depends(current_user), db=Depends(get_db)):
    """Explain WB realization rows without pretending that settlement equals bank payout.

    The ledger retains native WB amounts/currency; currency conversion and
    reconciliation to a WB report must be done for the same report period.
    """
    require(u, "analytics")
    if end < start:
        raise HTTPException(422, "Дата окончания раньше даты начала")
    aq = select(Account.id).where(Account.channel == "Wildberries")
    if u.role != "Owner":
        aq = aq.where(Account.company_id.in_(u.company_ids or []))
    if company_id is not None:
        scope(u, company_id)
        aq = aq.where(Account.company_id == company_id)
    ids = list(db.scalars(aq))
    if not ids:
        return {"start": str(start), "end": str(end), "rows": [], "total": 0,
                "by_currency": {}, "unclassified": 0,
                "note": "Нет подключённых аккаунтов Wildberries"}
    records = db.execute(select(MarketplaceRecord.external_id, MarketplaceRecord.payload)
                         .where(MarketplaceRecord.account_id.in_(ids),
                                MarketplaceRecord.source == "wildberries")).all()
    rows = []
    for external_id, payload in records:
        p = payload or {}
        if str(p.get("record_type") or "").lower() != "realization":
            continue
        dt = p.get("rrDate") or p.get("rr_dt") or p.get("saleDt") or p.get("sale_dt")
        try:
            day = marketplace_pipeline._day(dt)
        except (ValueError, TypeError, KeyError):
            continue
        if not start <= day <= end:
            continue
        operation = str(p.get("sellerOperName") or p.get("supplier_oper_name") or p.get("doc_type_name") or "").strip()
        low = operation.lower()
        if "возврат" in low or "return" in low: category = "return"
        elif "штраф" in low or "penalty" in low: category = "penalty"
        elif "логист" in low or "достав" in low or "delivery" in low: category = "logistics"
        elif "удержан" in low or "deduction" in low: category = "deduction"
        elif "хранен" in low or "storage" in low: category = "storage"
        elif "продаж" in low or low == "sale": category = "sale"
        else: category = "unclassified"
        currency = str(p.get("currency") or p.get("currency_name") or "RUB").upper()
        currency = {"РУБ": "RUB", "РУБ.": "RUB", "ТЕНГЕ": "KZT"}.get(currency, currency)
        # Monetary values are NOT combined into one amount: fields may overlap.
        fields = {"retail_amount": ("retailAmount", "retail_amount"),
                  "seller_for_pay": ("ppvzForPay", "ppvz_for_pay"),
                  "sales_commission": ("ppvzSalesCommission", "ppvz_sales_commission"),
                  "delivery": ("deliveryService", "delivery_rub"),
                  "penalty": ("penalty",), "deduction": ("deduction",),
                  "acquiring": ("acquiringFee", "acquiring_fee")}
        amounts = {}
        for label, keys in fields.items():
            value = next((p[k] for k in keys if p.get(k) is not None), None)
            if value is not None:
                try: amounts[label] = str(marketplace_pipeline._number(value))
                except (TypeError, ValueError): pass
        rows.append({"external_id": external_id, "date": str(day), "operation": operation,
                     "category": category, "currency": currency, "amounts": amounts,
                     "spp": p.get("spp") or p.get("spp_percent") or p.get("sppPercent"),
                     "commission_rate": p.get("commissionPercent", p.get("commission_percent"))})
    rows.sort(key=lambda x: (x["date"], x["external_id"]))
    totals = {}
    for row in rows:
        cur = row["currency"]
        t = totals.setdefault(cur, {"records": 0, "categories": {}})
        t["records"] += 1
        t["categories"][row["category"]] = t["categories"].get(row["category"], 0) + 1
    # Financial fields are independent measures. Aggregate each one separately,
    # preserving native currency and operation category; never infer commission
    # or profit by subtracting overlapping WB amounts.
    from decimal import Decimal
    weekly = {}
    for row in rows:
        day = date.fromisoformat(row["date"])
        monday = day.fromordinal(day.toordinal() - day.weekday())
        key = (str(monday), row["currency"])
        bucket = weekly.setdefault(key, {"week_start": str(monday),
            "currency": row["currency"], "records": 0, "categories": {},
            "amounts": {}})
        bucket["records"] += 1
        cat = row["category"]
        bucket["categories"][cat] = bucket["categories"].get(cat, 0) + 1
        for field, raw in row["amounts"].items():
            # Store category-qualified amounts to prevent unrelated events from
            # being combined into a misleading payout or sales total.
            group = bucket["amounts"].setdefault(cat, {})
            group[field] = str(Decimal(group.get(field, "0")) + Decimal(raw))
    weekly_reports = sorted(weekly.values(), key=lambda v: (v["week_start"], v["currency"]))
    return {"start": str(start), "end": str(end), "total": len(rows),
            "weekly_reports": weekly_reports,
            "unclassified": sum(r["category"] == "unclassified" for r in rows),
            "by_currency": totals, "rows": rows[offset:offset + limit],
            "note": "Исходные поля WB без смешивания оборота, СПП, начислений и банковских выплат. Для окончательной сверки нужен официальный отчёт за тот же период."}


def _wb_week_args(week_start: date):
    from .wb_weekly import finance_today
    if week_start.weekday() != 0:
        raise HTTPException(422, "Неделя должна начинаться в понедельник")
    end = week_start + timedelta(days=6)
    if end >= finance_today():
        raise HTTPException(422, "Отчёт доступен только за завершённую неделю")
    return end


def _wb_week_account(db, u, account_id):
    q = select(Account).where(Account.channel == "Wildberries", Account.mode == "api", Account.active.is_(True))
    if u.role != "Owner":
        q = q.where(Account.company_id.in_(u.company_ids or []))
    if account_id is not None:
        q = q.where(Account.id == account_id)
    account = db.scalar(q.order_by(Account.id))
    if not account:
        raise HTTPException(404, "Подключение Wildberries не найдено")
    scope(u, account.company_id)
    return account


def _wb_finance_period_args(period: str, start: date, end: date):
    from .wb_weekly import _validate_report_period
    try:
        _validate_report_period(period, start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return period


@app.get("/api/wildberries/finance")
def wildberries_finance_report(period: str, start: date, end: date, account_id: int | None = None,
                               u=Depends(current_user), db=Depends(get_db)):
    """Read a daily, weekly, or month-aggregated official WB Finance report."""
    require(u, "analytics")
    period = _wb_finance_period_args(period, start, end)
    account = _wb_week_account(db, u, account_id)
    from .wb_weekly import build_report
    return build_report(db, account, start, end, period=period)


@app.get("/api/wildberries/costs")
def wildberries_cost_catalog(account_id: int, u=Depends(current_user), db=Depends(get_db)):
    require(u, "finance")
    from .wb_costs import account_for_cost, catalogue_products, current_cost_map
    account = account_for_cost(db, u, account_id)
    items, _ = catalogue_products(db, account)
    today = business_today(); costs = current_cost_map(db, account.id, today)
    for item in items:
        row = costs.get(item["external_key"])
        item["unit_cost"] = str(Decimal(row.unit_cost) / 100) if row else None
        item["effective_from"] = str(row.effective_from) if row else None
    return {"account_id": account.id, "items": items}


@app.put("/api/wildberries/costs")
def wildberries_cost_save(p: s.WBProductCostIn, u=Depends(current_user), db=Depends(get_db)):
    require(u, "finance", True)
    from .wb_costs import account_for_cost, catalogue_products, cost_external_key, money_to_tiyn
    account = account_for_cost(db, u, p.account_id)
    items, _ = catalogue_products(db, account)
    stable = cost_external_key(p.nm_id, p.seller_article, p.barcode)
    product = next((x for x in items if x["external_key"] == p.external_key or (stable and x["external_key"] == stable)), None)
    if not product:
        raise HTTPException(422, "Товар не найден в сопоставленном каталоге этого кабинета WB")
    amount = money_to_tiyn(p.unit_cost)
    row = db.scalar(select(MarketplaceProductCost).where(MarketplaceProductCost.account_id == account.id,
        MarketplaceProductCost.external_key == product["external_key"], MarketplaceProductCost.effective_from == p.effective_from))
    if row:
        row.unit_cost, row.updated_by = amount, u.id
    else:
        db.add(MarketplaceProductCost(company_id=account.company_id, account_id=account.id,
            external_key=product["external_key"], nm_id=product["nm_id"], seller_article=product["seller_article"],
            barcode=product["barcode"], product_name=product["name"], unit_cost=amount,
            currency="KZT", effective_from=p.effective_from, updated_by=u.id))
    db.commit()
    return {"saved": True, "external_key": product["external_key"], "unit_cost": str(p.unit_cost), "effective_from": str(p.effective_from)}


@app.post("/api/wildberries/costs/bulk")
def wildberries_cost_bulk(p: s.WBProductCostBulkIn, u=Depends(current_user), db=Depends(get_db)):
    require(u, "finance", True)
    from .wb_costs import account_for_cost, catalogue_products, money_to_tiyn
    account = account_for_cost(db, u, p.account_id)
    amount = money_to_tiyn(p.unit_cost)
    items, _ = catalogue_products(db, account)
    known = {x["external_key"]: x for x in items}
    unknown = [key for key in set(p.external_keys) if key not in known]
    if unknown:
        raise HTTPException(422, {"message": "Есть товары вне каталога кабинета", "external_keys": unknown[:20]})
    for key in set(p.external_keys):
        product = known[key]
        row = db.scalar(select(MarketplaceProductCost).where(MarketplaceProductCost.account_id == account.id,
            MarketplaceProductCost.external_key == key, MarketplaceProductCost.effective_from == p.effective_from))
        if row:
            row.unit_cost, row.updated_by = amount, u.id
        else:
            db.add(MarketplaceProductCost(company_id=account.company_id, account_id=account.id, external_key=key,
                nm_id=product["nm_id"], seller_article=product["seller_article"], barcode=product["barcode"],
                product_name=product["name"], unit_cost=amount, currency="KZT", effective_from=p.effective_from, updated_by=u.id))
    db.commit()
    return {"saved": len(set(p.external_keys)), "effective_from": str(p.effective_from)}


@app.get("/api/wildberries/costs/template.xlsx")
def wildberries_cost_template(account_id: int, u=Depends(current_user), db=Depends(get_db)):
    require(u, "finance")
    from .wb_costs import account_for_cost, catalogue_products, current_cost_map
    account = account_for_cost(db, u, account_id)
    from openpyxl import Workbook
    from io import BytesIO
    book = Workbook(); ws = book.active; ws.title = "Себестоимость"
    ws.append(["Артикул WB", "Название", "Себестоимость, ₸", "Ключ товара (не менять)", "Дата начала действия"])
    today = business_today(); costs = current_cost_map(db, account.id, today)
    for item in catalogue_products(db, account)[0]:
        cost = costs.get(item["external_key"])
        ws.append([item["nm_id"] or item["seller_article"], item["name"], float(Decimal(cost.unit_cost)/100) if cost else None, item["external_key"], today.isoformat()])
    ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions
    out = BytesIO(); book.save(out)
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="wb-cost-template.xlsx"'})


@app.post("/api/wildberries/costs/import")
def wildberries_cost_import(account_id: int = Form(...), file: UploadFile = File(...),
                            u=Depends(current_user), db=Depends(get_db)):
    require(u, "finance", True)
    from .wb_costs import account_for_cost, catalogue_products, money_to_tiyn
    from openpyxl import load_workbook
    account = account_for_cost(db, u, account_id)
    content = file.file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024: raise HTTPException(413, "Файл превышает 5 МБ")
    try:
        ws = load_workbook(io.BytesIO(content), read_only=True, data_only=True).active
        headers = [str(c or "").strip().lower() for c in next(ws.iter_rows(values_only=True))]
        key_col = headers.index("ключ товара (не менять)") if "ключ товара (не менять)" in headers else -1
        nm_col = headers.index("артикул wb") if "артикул wb" in headers else -1
        cost_col = headers.index("себестоимость, ₸") if "себестоимость, ₸" in headers else -1
        date_col = headers.index("дата начала действия") if "дата начала действия" in headers else -1
        if cost_col < 0 or (key_col < 0 and nm_col < 0): raise ValueError("Не найдены колонки шаблона")
        items, _ = catalogue_products(db, account)
        by_nm = {x["nm_id"]: x for x in items if x["nm_id"]}
        by_key = {x["external_key"]: x for x in items}
        rows, errors, seen = [], [], set()
        for line, values in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
            if line > 1001:
                errors.append({"row": line, "error": "лимит импорта — 1000 товаров"})
                break
            try:
                key = str(values[key_col]).strip() if key_col >= 0 and values[key_col] else ""
                nm = str(values[nm_col]).strip() if nm_col >= 0 and values[nm_col] else ""
                product = by_key.get(key) if key else by_nm.get(nm)
                if not product: raise ValueError("товар не найден по ключу/nmID")
                amount = money_to_tiyn(values[cost_col])
                raw_date = values[date_col] if date_col >= 0 else date.today()
                effective = raw_date.date() if isinstance(raw_date, datetime) else (raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date)))
                ident = (product["external_key"], effective)
                if ident in seen: raise ValueError("повтор товара и даты в файле")
                seen.add(ident); rows.append((product, amount, effective))
            except Exception as exc: errors.append({"row": line, "error": str(exc)[:180]})
        if errors: return {"saved": 0, "errors": errors[:100], "error_count": len(errors)}
        for product, amount, effective in rows:
            row = db.scalar(select(MarketplaceProductCost).where(MarketplaceProductCost.account_id == account.id,
                MarketplaceProductCost.external_key == product["external_key"], MarketplaceProductCost.effective_from == effective))
            if row: row.unit_cost, row.updated_by = amount, u.id
            else: db.add(MarketplaceProductCost(company_id=account.company_id, account_id=account.id,
                external_key=product["external_key"], nm_id=product["nm_id"], seller_article=product["seller_article"],
                barcode=product["barcode"], product_name=product["name"], unit_cost=amount,
                currency="KZT", effective_from=effective, updated_by=u.id))
        db.commit(); return {"saved": len(rows), "errors": []}
    except HTTPException: raise
    except Exception as exc: raise HTTPException(422, f"Не удалось прочитать Excel: {str(exc)[:180]}") from exc


def _sync_wb_finance_background(account_id: int, user_id: int, period: str, start: date, end: date):
    from . import wb_weekly
    with SessionLocal() as db:
        account = db.get(Account, account_id)
        user = db.get(User, user_id)
        if not account or not user or not user.active or account.channel != "Wildberries" or account.mode != "api":
            return
        try:
            credentials = load_saved_credentials(db, account.id)
            token = credentials.get("token")
            if not token:
                raise AccessRequired("Для выбранного аккаунта WB не найден сохранённый токен. Переподключите интеграцию.")
            wb_weekly.sync_period(db, account, token, period, start, end, force=True, project_user=user)
        except Exception as exc:
            db.rollback()
            meta = wb_weekly._meta(db, account.id, start, create=True, period=period)
            if meta is not None:
                state = dict(meta.payload or {})
                failed_at = now().isoformat()
                safe_error = str(exc).strip()[:400] or "Не удалось подготовить синхронизацию WB. Проверьте токен и настройки."
                state.update(status="ошибка", error=safe_error,
                             start=str(start), end=str(end), period=period,
                             attempt_at=failed_at, updated_at=failed_at)
                meta.payload = state
                meta.stage_status = "ошибка"
                db.commit()
            logger.warning("WB Finance report sync failed: trigger=manual account_id=%s period=%s error=%s",
                           account_id, period, str(exc)[:400])


@app.post("/api/wildberries/finance/sync", status_code=202)
def wildberries_finance_sync(tasks: BackgroundTasks, period: str, start: date, end: date,
                             account_id: int | None = None, u=Depends(current_user), db=Depends(get_db)):
    require(u, "analytics")
    period = _wb_finance_period_args(period, start, end)
    account = _wb_week_account(db, u, account_id)
    tasks.add_task(_sync_wb_finance_background, account.id, u.id, period, start, end)
    return {"status": "загружается", "period": period, "start": str(start), "end": str(end)}


@app.get("/api/wildberries/finance.xlsx")
def wildberries_finance_xlsx(period: str, start: date, end: date, account_id: int | None = None,
                             u=Depends(current_user), db=Depends(get_db)):
    require(u, "analytics")
    period = _wb_finance_period_args(period, start, end)
    account = _wb_week_account(db, u, account_id)
    from .wb_weekly import build_report, create_xlsx
    report = build_report(db, account, start, end, period=period)
    if report.get("status") != "готов" or not report.get("row_count"):
        raise HTTPException(409, "Финансовый отчёт ещё не получен; скачивание недоступно")
    filename = f"WB-{period}-{start}-{end}.xlsx"
    return Response(content=create_xlsx(report), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/wildberries/weekly")
def wildberries_weekly_report(week_start: date, account_id: int | None = None,
                              u=Depends(current_user), db=Depends(get_db)):
    require(u, "analytics")
    end = _wb_week_args(week_start)
    account = _wb_week_account(db, u, account_id)
    from .wb_weekly import build_report
    return build_report(db, account, week_start, end)


def _sync_wb_week_background(account_id: int, user_id: int, week_start: date, week_end: date):
    """Run a user-requested report fetch in a fresh DB session."""
    from . import wb_weekly
    with SessionLocal() as db:
        account = db.get(Account, account_id)
        user = db.get(User, user_id)
        if not account or not user or not user.active or account.channel != "Wildberries" or account.mode != "api":
            return
        try:
            credentials = load_saved_credentials(db, account.id)
            token = credentials.get("token")
            wb_weekly.sync_week(db, account, token, week_start, week_end, force=True, project_user=user)
        except Exception:
            db.rollback()
            meta = wb_weekly._meta(db, account.id, week_start, create=True)
            if meta is not None:
                state = dict(meta.payload or {})
                state.update(status="ошибка", error="Не удалось подготовить синхронизацию WB. Проверьте токен и настройки.",
                             week_start=str(week_start), week_end=str(week_end), updated_at=now().isoformat())
                meta.payload = state
                meta.stage_status = "ошибка"
                db.commit()
            logger.exception("WB weekly on-demand sync failed for account %s", account_id)


@app.post("/api/wildberries/weekly/sync", status_code=202)
def wildberries_weekly_sync(tasks: BackgroundTasks, week_start: date, account_id: int | None = None,
                            u=Depends(current_user), db=Depends(get_db)):
    """Queue a fetch for one completed week; report data remains read-only until WB returns it."""
    require(u, "analytics")
    end = _wb_week_args(week_start)
    account = _wb_week_account(db, u, account_id)
    tasks.add_task(_sync_wb_week_background, account.id, u.id, week_start, end)
    return {"status": "загружается", "week_start": str(week_start), "week_end": str(end)}


@app.get("/api/wildberries/weekly.xlsx")
def wildberries_weekly_xlsx(week_start: date, account_id: int | None = None,
                            u=Depends(current_user), db=Depends(get_db)):
    require(u, "analytics")
    end = _wb_week_args(week_start)
    account = _wb_week_account(db, u, account_id)
    from .wb_weekly import build_report, create_xlsx
    report = build_report(db, account, week_start, end)
    if report.get("status") != "готов" or not report.get("row_count"):
        raise HTTPException(409, "Недельный финансовый отчёт ещё не получен; скачивание недоступно")
    filename = f"WB-weekly-{week_start}-{end}.xlsx"
    return Response(content=create_xlsx(report), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


class MarketplaceMappingIn(BaseModel):
    product_id: int
    external_keys: list[str] = Field(min_length=1, max_length=30)


@app.post("/api/marketplace-records/{id}/mapping")
def marketplace_mapping(id: int, p: MarketplaceMappingIn, u=Depends(current_user), db=Depends(get_db)):
    require(u, "accounts", True)
    row = db.get(MarketplaceRecord, id)
    if not row: raise HTTPException(404, "Запись не найдена")
    scope(u, row.company_id)
    acc = db.scalar(select(Account).where(Account.id == row.account_id).with_for_update())
    if acc.sync_status == 'running': raise HTTPException(409, 'Синхронизация ещё выполняется')
    product = db.get(Product, p.product_id)
    if not product or not product.active: raise HTTPException(422, "Товар не найден")
    payload = row.payload or {}
    permitted = set(marketplace_pipeline.identifiers(payload))
    for item in payload.get('products') or []:
        permitted.update(marketplace_pipeline.identifiers(item))
    if not set(p.external_keys).issubset(permitted):
        raise HTTPException(422, "Идентификатор отсутствует в исходной записи")
    for key in set(p.external_keys):
        mapping = db.scalar(select(MarketplaceProductMapping).where(
            MarketplaceProductMapping.account_id == acc.id, MarketplaceProductMapping.external_key == key))
        if mapping and mapping.product_id != product.id:
            raise HTTPException(409, "Идентификатор уже связан с другим товаром")
        if not mapping:
            db.add(MarketplaceProductMapping(company_id=acc.company_id, account_id=acc.id,
                channel=acc.channel, external_key=key, product_id=product.id))
    db.flush()
    audit(db, u, 'mapping', 'accounts', acc.id, {'product_id':product.id, 'keys':p.external_keys})
    result = marketplace_pipeline.project_account(db, u, acc)
    db.commit()
    return {'ok':True, **result}


@app.post("/api/accounts/{id}/reprocess")
def reprocess_marketplace(id: int, u=Depends(current_user), db=Depends(get_db)):
    require(u, 'accounts', True)
    acc = db.scalar(select(Account).where(Account.id == id).with_for_update())
    if not acc: raise HTTPException(404, 'Интеграция не найдена')
    scope(u, acc.company_id)
    if acc.sync_status == 'running': raise HTTPException(409, 'Синхронизация ещё выполняется')
    result = marketplace_pipeline.project_account(db, u, acc)
    db.commit()
    return result


class SettlementIn(BaseModel):
    effective_date: date
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    fx_rate: int = Field(gt=0, le=10**10)


@app.put('/api/accounts/{id}/settlement')
def account_settlement(id: int, p: SettlementIn, u=Depends(current_user), db=Depends(get_db)):
    require(u, 'accounts', True)
    acc = db.scalar(select(Account).where(Account.id == id).with_for_update())
    if not acc: raise HTTPException(404, 'Интеграция не найдена')
    scope(u, acc.company_id)
    if acc.sync_status == 'running': raise HTTPException(409, 'Синхронизация ещё выполняется')
    if p.currency == 'KZT' and p.fx_rate != 10000:
        raise HTTPException(422, 'Курс KZT должен быть 10000')
    existing=db.scalar(select(AccountExchangeRate).where(AccountExchangeRate.account_id==id,
        AccountExchangeRate.currency==p.currency,AccountExchangeRate.rate_date==p.effective_date))
    if existing and existing.rate_scaled!=p.fx_rate: raise HTTPException(409,'Курс на эту дату уже зафиксирован')
    if not existing: db.add(AccountExchangeRate(account_id=id,currency=p.currency,rate_date=p.effective_date,rate_scaled=p.fx_rate,source='manual_confirmed'))
    acc.settlement_currency, acc.settlement_fx_rate = p.currency, p.fx_rate
    audit(db, u, 'settlement', 'accounts', id, p.model_dump())
    db.commit()
    return {'ok':True}


@app.post('/api/post/opening')
def post_opening(p:s.OpeningInventoryIn,u=Depends(current_user),db=Depends(get_db)):
    require(u,'inventory',True)
    obj=canonical.post_event(db,u,'opening',p);db.commit();return dump(obj)


@app.post('/api/admin/reconcile-marketplaces')
def reconcile_existing(u=Depends(current_user),db=Depends(get_db)):
    require(u,'accounts',True)
    results=marketplace_pipeline.reconcile_all_staged_marketplaces(db,u)
    audit(db,u,'reconcile','marketplace_records',details={'results':results});db.commit()
    return {'ok':True,'results':results}


@app.get("/api/data/{entity}")
def listing(
    entity: str,
    search: str = "",
    company_id: int | None = None,
    account_id: int | None = None,
    channel: str | None = None,
    start: date | None = None,
    end: date | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    u=Depends(current_user),
    db=Depends(get_db),
):
    q = access_query(db, u, entity, search, company_id, account_id)
    model = MODELS[entity][0]
    if channel and entity == "sales":
        q = q.where(
            Sale.account_id.in_(select(Account.id).where(Account.channel == channel))
        )
    count = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = []
    for obj in db.scalars(q.order_by(model.id.desc()).offset(offset).limit(limit)):
        row = dump(obj)
        if entity == "accounts":
            row["sync_status"], row["sync_error"] = sync_status_for_display(obj)
        rows.append(row)
    if entity == "niches":
        for row in rows:
            row["analysis"] = ai.niche_score(row["data"])
    if entity == "products" and rows:
        product_ids = [r["id"] for r in rows]
        from_date = start or business_today().replace(day=1)
        to_date = end or business_today()
        if to_date < from_date:
            raise HTTPException(422, "Конец периода раньше начала")
        batch_q = scope_query(select(Batch.product_id, func.coalesce(func.sum(Batch.remaining), 0)), Batch, u)
        batch_q = batch_q.where(Batch.product_id.in_(product_ids)).group_by(Batch.product_id)
        if company_id:
            batch_q = batch_q.where(Batch.company_id == company_id)
        physical = dict(db.execute(batch_q).all())
        sold_q = scope_query(select(Sale.product_id, func.coalesce(func.sum(Sale.quantity), 0)), Sale, u)
        sold_q = sold_q.where(Sale.product_id.in_(product_ids), Sale.date >= from_date, Sale.date <= to_date).group_by(Sale.product_id)
        if company_id:
            sold_q = sold_q.where(Sale.company_id == company_id)
        sold = dict(db.execute(sold_q).all())
        returned_q = select(Sale.product_id, func.coalesce(func.sum(Return.quantity), 0)).join(Return, Return.sale_id == Sale.id)
        returned_q = scope_query(returned_q, Sale, u).where(Sale.product_id.in_(product_ids), Return.date >= from_date, Return.date <= to_date).group_by(Sale.product_id)
        if company_id:
            returned_q = returned_q.where(Sale.company_id == company_id)
        returned = dict(db.execute(returned_q).all())
        defective_q = select(Sale.product_id, func.coalesce(func.sum(Return.quantity), 0)).join(Return, Return.sale_id == Sale.id)
        defective_q = scope_query(defective_q, Sale, u).where(
            Sale.product_id.in_(product_ids), Return.inventory_status == "defective"
        ).group_by(Sale.product_id)
        if company_id:
            defective_q = defective_q.where(Sale.company_id == company_id)
        defective = dict(db.execute(defective_q).all())
        accounts_q = scope_query(select(Account), Account, u)
        if company_id:
            accounts_q = accounts_q.where(Account.company_id == company_id)
        sync_times = [a.last_sync for a in db.scalars(accounts_q) if a.last_sync]
        latest_sync = max(sync_times) if sync_times else None
        for row in rows:
            specs = row.get("specifications") or {}
            market_snapshot = specs.get("marketplace_stock") or {}
            marketplace_units = sum(
                int(v.get("quantity") or 0) for v in market_snapshot.values()
                if isinstance(v, dict)
            )
            physical_units = int(physical.get(row["id"], 0) or 0)
            defective_units = int(defective.get(row["id"], 0) or 0)
            in_transit = specs.get("in_transit_quantity")
            reserved = specs.get("reserved_quantity")
            row["inventory"] = {
                "physical": physical_units,
                "available": max(0, physical_units - int(reserved)) if reserved is not None else None,
                "reserved": int(reserved) if reserved is not None else None,
                "marketplace": marketplace_units,
                "in_transit": int(in_transit) if in_transit is not None else None,
                "defective": defective_units,
                "sold": int(sold.get(row["id"], 0) or 0),
                "returned": int(returned.get(row["id"], 0) or 0),
                "last_sync": latest_sync,
                "low_stock": physical_units - int(reserved or 0) <= int(row.get("min_stock") or 0),
            }
    return {"items": rows, "total": count}


def validate_master(db, u, entity, p, existing=None):
    if hasattr(p, "company_id"):
        f.get_company(db, u, p.company_id)
    if entity == "companies" and u.role != "Owner":
        raise HTTPException(403, "Компании изменяет Owner")
    if entity == "users":
        if u.role != "Owner":
            raise HTTPException(403, "Назначение ролей доступно Owner")
        if existing and existing.id == u.id and (not p.active or p.role != "Owner"):
            raise HTTPException(422, "Нельзя отключить себя или снять свою роль Owner")
        if not existing and len(p.password) < 12:
            raise HTTPException(422, "Пароль от 12 символов")
        if p.password and len(p.password) < 12:
            raise HTTPException(422, "Пароль от 12 символов")
        for cid in p.company_ids:
            if not db.get(Company, cid):
                raise HTTPException(422, "Неизвестная компания")
    if entity == "accounts" and existing:
        linked = db.scalar(
            select(Sale.id).where(Sale.account_id == existing.id).limit(1)
        )
        if linked and (
            p.company_id != existing.company_id or p.channel != existing.channel
        ):
            raise HTTPException(
                422, "Нельзя менять компанию или канал аккаунта с продажами"
            )
    if entity == "niches":
        ai.niche_score(p.data)


def master_values(p, entity):
    values = p.model_dump()
    # Product version is an optimistic concurrency token, not an editable field.
    if entity == "products":
        values.pop("version", None)
        description = values.pop("description", "")
        barcode = values.pop("barcode", "")
        purchase_cost = values.pop("purchase_cost", 0)
        custom_fields = values.pop("custom_fields", {})
        specs = dict(values.get("specifications") or {})
        specs.update({"description": description, "barcode": barcode,
                      "purchase_cost": purchase_cost, "custom_fields": custom_fields})
        values["specifications"] = specs
    if entity == "users":
        pw = values.pop("password")
        values["email"] = values["email"].lower()
        if pw:
            values["password_hash"] = passwords.hash(pw)
    return values


@app.post("/api/products/ai-draft")
def product_ai_draft(p: dict, u=Depends(current_user)):
    """Generate an editable product draft; the caller must review and save it."""
    require(u, "catalog", True)
    return ai.product_draft(p)


@app.post("/api/data/{entity}")
def create_master(
    entity: str, payload: dict, u=Depends(current_user), db=Depends(get_db)
):
    model, cap, schema = model_info(entity)
    require(u, cap, True)
    if not schema:
        raise HTTPException(405, "Используйте проведение документа")
    p = schema.model_validate(payload)
    validate_master(db, u, entity, p)
    obj = model(**master_values(p, entity))
    db.add(obj)
    db.flush()
    audit(db, u, "create", entity, obj.id, {"after": dump(obj)})
    db.commit()
    return dump(obj)


@app.put("/api/data/{entity}/{id}")
def edit_master(
    entity: str, id: int, payload: dict, u=Depends(current_user), db=Depends(get_db)
):
    model, cap, schema = model_info(entity)
    require(u, cap, True)
    if not schema:
        raise HTTPException(405, "Проведённые финансовые записи неизменяемы")
    obj = db.get(model, id)
    if not obj:
        raise HTTPException(404, "Не найдено")
    if entity == "products":
        obj = db.scalar(select(Product).where(Product.id == id).with_for_update().execution_options(populate_existing=True))
    if hasattr(obj, "company_id"):
        scope(u, obj.company_id)
    p = schema.model_validate(payload)
    if entity == "products" and p.version is None:
        raise HTTPException(428, "Для сохранения товара нужна версия карточки. Обновите список товаров.")
    if entity == "products" and p.version != obj.version:
        raise HTTPException(409, "Товар уже изменён другим сотрудником. Обновите карточку и повторите правку.")
    validate_master(db, u, entity, p, obj)
    if entity == "customers" and p.company_id != obj.company_id:
        raise HTTPException(422, "Компания покупателя неизменяема")
    before = dump(obj)
    for k, v in master_values(p, entity).items():
        setattr(obj, k, v)
    if entity == "products":
        obj.version += 1
    audit(db, u, "update", entity, id, {"before": before, "after": dump(obj)})
    db.commit()
    return dump(obj)


@app.delete("/api/data/{entity}/{id}")
def delete_master(entity: str, id: int, u=Depends(current_user), db=Depends(get_db)):
    model, cap, schema = model_info(entity)
    require(u, cap, True)
    if not schema or entity == "users":
        raise HTTPException(
            405,
            "Удаление запрещено; отключите пользователя или используйте корректирующий документ",
        )
    if entity == "companies" and u.role != "Owner":
        raise HTTPException(403, "Только Owner")
    obj = db.get(model, id)
    if not obj:
        raise HTTPException(404, "Не найдено")
    if hasattr(obj, "company_id"):
        scope(u, obj.company_id)
    if entity == "accounts":
        secret = db.scalar(select(IntegrationSecret).where(IntegrationSecret.account_id == id))
        if secret:
            db.delete(secret)
        obj.active = False
        obj.sync_status = "never"
        obj.sync_error = ""
        audit(db, u, "archive", entity, id, {"name": obj.name, "channel": obj.channel})
        db.commit()
        return {"ok": True, "archived": True}
    before = dump(obj)
    db.delete(obj)
    audit(db, u, "delete", entity, id, {"before": before})
    db.commit()
    return {"ok": True}


OPERATIONS = {
    "purchases": (s.PurchaseIn, f.purchase, "inventory"),
    "sales": (s.SaleIn, f.sale, "sales"),
    "returns": (s.ReturnIn, f.return_sale, "sales"),
    "expenses": (s.ExpenseIn, f.expense, "finance"),
    "cash": (s.CashIn, f.payment, "finance"),
    "adjustments": (s.AdjustIn, f.adjust, "inventory"),
}


@app.post("/api/post/{kind}")
def post(kind: str, payload: dict, u=Depends(current_user), db=Depends(get_db)):
    if kind not in OPERATIONS:
        raise HTTPException(404, "Операция не найдена")
    schema, fn, cap = OPERATIONS[kind]
    require(u, cap, True)
    obj = canonical.post_event(db, u, {"purchases":"purchase", "sales":"sale", "returns":"return", "expenses":"expense", "cash":"payment", "adjustments":"stock"}[kind], schema.model_validate(payload), reject_duplicates=True)
    db.commit()
    return dump(obj)


@app.post("/api/returns/{return_id}/status")
def update_return_status(return_id: int, payload: dict, u=Depends(current_user), db=Depends(get_db)):
    require(u, "inventory", True)
    ret = db.get(Return, return_id)
    if not ret:
        raise HTTPException(404, "Возврат не найден")
    scope(u, ret.company_id)
    sale = db.get(Sale, ret.sale_id)
    if not sale:
        raise HTTPException(409, "Исходная продажа не найдена")
    f.lock_product(db, sale.product_id)
    ret = db.scalar(select(Return).where(Return.id == return_id).with_for_update())
    change = s.ReturnStatusIn.model_validate(payload)
    transitions = {
        "requested": {"approved"},
        "approved": {"in_transit"},
        "in_transit": {"received"},
        "received": {"inspection"},
        "inspection": {"restocked", "defective"},
        "defective": {"written_off"},
        "restocked": set(),
        "written_off": set(),
    }
    if change.status != ret.inventory_status:
        if change.status not in transitions.get(ret.inventory_status, set()):
            raise HTTPException(409, "Недопустимый переход статуса возврата")
        if change.status in {"defective", "written_off"} and len(change.reason.strip()) < 3:
            raise HTTPException(422, "Для брака и списания укажите причину")
        before = ret.inventory_status
        ret.inventory_status = change.status
        audit(db, u, "inventory_status", "returns", ret.id, {
            "from": before, "to": change.status, "reason": change.reason.strip(),
        })
    if change.status == "restocked":
        f.restock_return_inventory(db, u, ret)
    db.commit()
    return dump(ret)


@app.get("/api/accounting/summary")
def accounting_summary(company_id: int, start: date, end: date, u=Depends(current_user), db=Depends(get_db)):
    require(u, "finance")
    scope(u, company_id)
    if end < start:
        raise HTTPException(422, "Некорректный период")
    bank = list(db.scalars(select(BankTransaction).where(BankTransaction.company_id == company_id, BankTransaction.date >= start, BankTransaction.date <= end)))
    incoming = sum(x.amount for x in bank if x.direction == "in")
    outgoing = sum(x.amount for x in bank if x.direction == "out")
    # Receivables are authoritative only in the central finance report: it also
    # subtracts confirmed returns and therefore cannot drift from Finance/AI.
    receivable = f.report(db, u, date.min, end, company_id)["b2b_debt"]
    purchase_paid = {pid: -amt for pid, amt in db.execute(select(CashEntry.purchase_id, func.coalesce(func.sum(CashEntry.amount), 0)).where(CashEntry.purchase_id.is_not(None), CashEntry.date <= end).group_by(CashEntry.purchase_id))}
    purchases = list(db.scalars(select(Purchase).where(Purchase.company_id == company_id, Purchase.date <= end)))
    payable = sum(max(0, x.total - max(0, purchase_paid.get(x.id, 0))) for x in purchases)
    rules = [dump(x) for x in db.scalars(select(TaxRule).where(TaxRule.company_id == company_id, TaxRule.active == True, TaxRule.valid_from <= end))]
    return {"period": {"start": start, "end": end}, "bank_in": incoming, "bank_out": outgoing, "bank_net": incoming-outgoing, "receivable": receivable, "payable": payable, "tax_rules": rules, "tax_notice": "Ставки являются конфигурацией. Налоговый расчет требует проверки бухгалтером."}

@app.get("/api/report")
def get_report(
    start: date,
    end: date,
    company_id: int | None = None,
    account_id: int | None = None,
    u=Depends(current_user),
    db=Depends(get_db),
):
    require(u, "analytics")
    return f.report(db, u, start, end, company_id, account_id)


@app.get("/api/reports/executive.xlsx")
def executive_xlsx(
    start: date,
    end: date,
    company_id: int | None = None,
    account_id: int | None = None,
    u=Depends(current_user),
    db=Depends(get_db),
):
    require(u, "analytics")
    if end < start:
        raise HTTPException(422, "Конечная дата раньше начальной")
    report = f.report(db, u, start, end, company_id, account_id)
    raw = reporting_xlsx.executive_workbook(report, start, end)
    filename = f"QOR-report-{start}-{end}.xlsx"
    return Response(
        raw,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/dashboard/summary")
def dashboard_summary(
    start: date,
    end: date,
    company_id: int | None = None,
    u=Depends(current_user),
    db=Depends(get_db),
):
    """Dashboard contract from the client specification.

    Returns selected-period metrics plus immutable today/month snapshots so the
    headline KPIs never change meaning when the user changes the period filter.
    All values come from the deterministic finance engine.
    """
    require(u, "analytics")
    today = business_today()
    # The default month view asks for the same report as the monthly headline.
    # Reuse identical ranges so a large marketplace ledger is scanned only once.
    report_cache = {}

    def report_for(period_start, period_end):
        key = (period_start, period_end, company_id)
        if key not in report_cache:
            report_cache[key] = f.report(db, u, period_start, period_end, company_id)
        return report_cache[key]

    selected = report_for(start, end)
    today_report = report_for(today, today)
    month_report = report_for(today.replace(day=1), today)

    def channels(report):
        found = {str(x.get("channel", "")): x for x in report.get("channel_summary", [])}
        values = {
            name: int(found.get(name, {}).get("revenue", 0) or 0)
            for name in ("Kaspi", "Wildberries", "Ozon", "Offline", "B2B")
        }
        values["WB"] = values["Wildberries"]
        return values

    return {
        "as_of": str(today),
        "today": {
            "revenue": today_report["revenue"],
            "net_profit": today_report["net_profit"],
            "units": today_report["units"],
        },
        "month": {
            "revenue": month_report["revenue"],
            "gross_profit": month_report["gross_profit"],
            "net_profit": month_report["net_profit"],
            "margin": month_report["margin"],
        },
        "report": selected,
        "selected": {
            "revenue": selected["revenue"],
            "gross_profit": selected["gross_profit"],
            "net_profit": selected["net_profit"],
            "margin": selected["margin"],
            "units": selected["units"],
            "returns": selected["returns"],
            "advertising": selected["advertising"],
            "expenses": selected["expenses"],
            "stock_value": selected["stock_value"],
            "cash": selected["cash"],
            "b2b_debt": selected["b2b_debt"],
            "channels": channels(selected),
        },
    }


@app.get("/api/report/details")
def get_report_details(
    start: date,
    end: date,
    metric: str,
    company_id: int | None = None,
    account_id: int | None = None,
    u=Depends(current_user),
    db=Depends(get_db),
):
    require(u, "analytics")
    return f.report_details(db, u, start, end, metric, company_id, account_id)


@app.get("/api/stock")
def stock(company_id: int | None = None, u=Depends(current_user), db=Depends(get_db)):
    require(u, "inventory")
    r = f.report(db, u, business_today().replace(day=1), business_today(), company_id)
    rows = r["stock"]
    if not allowed(u, "finance") and not allowed(u, "analytics"):
        for x in rows:
            x.pop("value", None)
    return rows


@app.post("/api/inventory/count")
def inventory_count(p: s.StockCountIn, u=Depends(current_user), db=Depends(get_db)):
    """Reconcile counted physical quantity as one auditable, replay-safe movement."""
    require(u, "inventory", True)
    f.get_company(db, u, p.company_id)
    identity = f"stock-count:{p.company_id}:{p.idempotency_key}"
    body = p.model_dump(mode="json")
    old = db.scalar(select(CanonicalEvent).where(CanonicalEvent.identity == identity))
    if old:
        if old.event_type != "stock_count" or old.payload.get("request") != body:
            raise HTTPException(409, "Ключ операции уже использован для другой корректировки")
        db.commit()
        return {"ok": True, "replayed": True, "movement_id": old.target_id, **old.payload["result"]}
    product = f.lock_product(db, p.product_id)
    current = db.scalar(select(func.coalesce(func.sum(Batch.remaining), 0)).where(
        Batch.company_id == p.company_id, Batch.product_id == product.id
    )) or 0
    delta = p.counted_quantity - current
    movement_id = None
    if delta:
        if delta > 0 and (p.unit_cost is None or p.unit_cost <= 0):
            raise HTTPException(422, "При увеличении остатка укажите подтверждённую себестоимость единицы")
        adjustment = s.AdjustIn(
            company_id=p.company_id, product_id=product.id, date=business_today(),
            quantity=delta, unit_cost=p.unit_cost or 0,
            kind="adjustment", reason=p.reason,
            reference=f"count:{p.company_id}:{p.idempotency_key}",
        )
        posted = f.adjust(db, u, adjustment)
        movement_id = posted["movement_ids"][0] if posted.get("movement_ids") else None
    result = {"previous_quantity": current, "counted_quantity": p.counted_quantity, "delta": delta}
    db.add(CanonicalEvent(company_id=p.company_id, account_id=None, event_type="stock_count",
        identity=identity, payload={"request": body, "result": result}, target_id=movement_id, status="posted"))
    audit(db, u, "stock_count", "inventory", product.id, {**body, **result, "movement_id": movement_id})
    db.commit()
    return {"ok": True, "replayed": False, "movement_id": movement_id, **result}


@app.get("/api/forecast")
def forecast(
    start: date,
    end: date,
    company_id: int | None = None,
    u=Depends(current_user),
    db=Depends(get_db),
):
    require(u, "analytics")
    return ai.forecast(f.report(db, u, start, end, company_id))


@app.get("/api/alerts")
def alerts(
    start: date, end: date, company_id: int | None = None,
    u=Depends(current_user), db=Depends(get_db),
):
    require(u, "analytics")
    current = f.report(db, u, start, end, company_id)
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    previous = f.report(db, u, prev_start, prev_end, company_id)
    items = []
    for x in current["stock"]:
        dl = x.get("days_of_stock")
        if dl is not None and dl <= 7:
            items.append({"severity":"critical", "type":"stockout", "title":f"{x['name']}: запас примерно на {dl} дн.", "product_id":x.get("product_id")})
        if x.get("stale"):
            items.append({"severity":"warning", "type":"stale_stock", "title":f"{x['name']}: товар залежался на складе", "product_id":x.get("product_id")})
    if current["revenue"] and current["margin"] is not None and current["margin"] < 0:
        items.append({"severity":"critical", "type":"negative_margin", "title":"За период чистая маржа отрицательная"})
    def pct(cur, prev):
        return ((cur-prev)/abs(prev)*100) if prev else None
    ad = pct(current["advertising"], previous["advertising"]); mg = pct(current["margin"] or 0, previous["margin"] or 0)
    if ad is not None and ad >= 30:
        items.append({"severity":"warning", "type":"advertising_growth", "title":f"Расходы на рекламу выросли на {ad:.1f}%", "change_percent":round(ad,1)})
    if mg is not None and mg <= -10:
        items.append({"severity":"warning", "type":"margin_drop", "title":f"Маржа снизилась на {abs(mg):.1f}%", "change_percent":round(mg,1)})
    prev_channels={x["channel"]:x for x in previous["channel_summary"]}
    for x in current["channel_summary"]:
        old=prev_channels.get(x["channel"],{}).get("revenue",0); ch=pct(x["revenue"],old)
        if ch is not None and ch <= -20:
            items.append({"severity":"warning", "type":"channel_drop", "title":f"{x['channel']}: оборот снизился на {abs(ch):.1f}%", "change_percent":round(ch,1)})
    if current["stock_value"] >= 50_000_000 * 100:
        items.append({"severity":"info", "type":"stock_value", "title":"На складе находится товар на сумму 50 млн ₸ или более"})
    if current.get("pending_cogs_sales", 0):
        count = int(current["pending_cogs_sales"])
        items.append({"severity":"warning", "type":"missing_cost", "title":f"Для {count} продаж не задана себестоимость",
            "count":count,"action":"Заполните себестоимость или импортируйте закупки; прибыль за период пока неполная."})
    account_query=select(Account).where(Account.active.is_(True),Account.channel.in_(["Kaspi","Wildberries","Ozon"]))
    if u.role != "Owner": account_query=account_query.where(Account.company_id.in_(u.company_ids or []))
    if company_id is not None: account_query=account_query.where(Account.company_id==company_id)
    active_accounts=db.scalars(account_query).all()
    active_ids=[a.id for a in active_accounts]
    account_by_id={a.id:a for a in active_accounts}
    if active_ids:
        pending_mapping_rows=db.execute(select(MarketplaceRecord.account_id,func.count(MarketplaceRecord.id))
            .where(MarketplaceRecord.account_id.in_(active_ids),MarketplaceRecord.stage_status=="pending_mapping")
            .group_by(MarketplaceRecord.account_id)).all()
        for account_id,count in pending_mapping_rows:
            account=account_by_id[account_id]
            items.append({"severity":"warning","type":"unmapped_products",
                "title":f"{account.name}: {count} операций не сопоставлены с товарами ERP",
                "account_id":account.id,"channel":account.channel,"count":int(count),
                "action":"Сопоставьте SKU / артикул маркетплейса с товаром ERP; склад и прибыль не должны угадывать товар."})
        for account in active_accounts:
            if account.sync_status in {"failed","partial"} or account.sync_error:
                items.append({"severity":"critical" if account.sync_status=="failed" else "warning",
                    "type":"marketplace_sync","title":f"{account.name}: синхронизация {account.sync_status}",
                    "account_id":account.id,"channel":account.channel,
                    "action":(account.sync_error or "Откройте интеграцию и проверьте состояние подключения.")[:300]})
    return {"items":items, "count":len(items), "period":[str(start),str(end)], "comparison_period":[str(prev_start),str(prev_end)],
            "method":"Детерминированные правила ERP; без LLM. Рыночные сигналы добавляются только при наличии подтверждённого источника."}


@app.post("/api/calculator")
def calculator(p: dict, u=Depends(current_user)):
    require(u, "marketing")
    return ai.calculator(p)


@app.get("/api/roles")
def roles(u=Depends(current_user)):
    require(u, "users")
    return {k: sorted(v) for k, v in PERMISSIONS.items()}


@app.get("/api/ai/agents")
def ai_agents(u=Depends(current_user)):
    require(u, "ai")
    return {"items": ai.agent_catalog()}


@app.get("/api/settings")
def settings(u=Depends(current_user), db=Depends(get_db)):
    obj = db.get(Setting, 1)
    return {
        **dump(obj),
        "ai_enabled": bool(os.getenv("OPENAI_API_KEY")),
        "demo": os.getenv("DEMO_MODE", "false").strip().lower() == "true",
    }


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
            if old_payload != payload:
                row.payload = payload
                # Revalidate revisions through canonical identity checks, never
                # leave a changed source silently marked as projected.
                row.status = 'received'
            updated += 1
        else:
            db.add(MarketplaceRecord(account_id=acc.id, company_id=acc.company_id, source=result.source, external_id=external_id, payload=payload))
            inserted += 1
    return inserted, updated


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
            projection = marketplace_pipeline.project_account(db, u, acc) if total_records else {'projected':0,'pending_erp':0}
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
    scope(u,cid)
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
def ai_action_confirm(id:int,u=Depends(current_user),db=Depends(get_db)):
    require(u,"ai",True); row=db.get(AIAction,id)
    if not row: raise HTTPException(404,"Действие не найдено")
    return dump(action_engine.execute(db,u,row))

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
def ai_plan_confirm(id:int,u=Depends(current_user),db=Depends(get_db)):
    require(u,"ai",True); row=db.get(AIActionPlan,id)
    if not row: raise HTTPException(404,"План не найден")
    return dump(action_engine.execute_plan(db,u,row))

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
    if (job.status == "running" and job.started_at
            and job.started_at < now() - timedelta(minutes=15)):
        job.status = "failed"
        job.error = "AI-задание прервано сервером. Проверьте подключение AI и повторите запрос."
        db.commit()
    return dump(job)


@app.post("/api/jobs/{id}/retry")
def retry_job(id: int, tasks: BackgroundTasks, u=Depends(current_user), db=Depends(get_db)):
    job = db.get(Job, id)
    if not job or job.user_id != u.id:
        raise HTTPException(404, "Не найдено")
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
    entity: str, format: str = "csv", u=Depends(current_user), db=Depends(get_db)
):
    if format not in ("csv", "xlsx"):
        raise HTTPException(422, "Формат csv или xlsx")
    aliases = {"bank": "cash", "reports": "sales", "b2b": "sales", "stock": "movements"}
    resolved = aliases.get(entity, entity)
    q = access_query(db, u, resolved)
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
        return FileResponse(static / "index.html")
