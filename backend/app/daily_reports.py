"""Scheduled, idempotent business digest delivery."""
import logging
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from . import ai, finance
from .db import SessionLocal
from .models import Company, DailyReportDelivery, Setting, User, now
from .system_secrets import load_config
from .security import scope

logger = logging.getLogger(__name__)
PROVIDER = "whatsapp_cloud"
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def _whatsapp_config(db=None):
    saved = load_config("whatsapp_cloud", db)
    return {
        "access_token": str(saved.get("access_token") or os.getenv("QOR_WHATSAPP_ACCESS_TOKEN", "")).strip(),
        "phone_number_id": str(saved.get("phone_number_id") or os.getenv("QOR_WHATSAPP_PHONE_NUMBER_ID", "")).strip(),
        "template_name": str(saved.get("template_name") or os.getenv("QOR_WHATSAPP_TEMPLATE_NAME", "")).strip(),
        "language": str(saved.get("language") or os.getenv("QOR_WHATSAPP_TEMPLATE_LANGUAGE", "ru")).strip(),
        "graph_version": str(saved.get("graph_version") or os.getenv("QOR_WHATSAPP_GRAPH_VERSION", "v26.0")).strip(),
        "source": "site" if saved else ("server" if any(os.getenv(x, "").strip() for x in (
            "QOR_WHATSAPP_ACCESS_TOKEN", "QOR_WHATSAPP_PHONE_NUMBER_ID", "QOR_WHATSAPP_TEMPLATE_NAME")) else "missing"),
    }


def provider_status(db=None):
    config = _whatsapp_config(db)
    missing = [name for name, value in (
        ("access_token", config["access_token"]),
        ("phone_number_id", config["phone_number_id"]),
        ("template_name", config["template_name"]),
    ) if not value]
    return {"provider": PROVIDER, "configured": not missing, "missing": missing,
            "source": config["source"], "phone_number_id": config["phone_number_id"],
            "template_name": config["template_name"], "language": config["language"],
            "graph_version": config["graph_version"]}


def _money(value):
    if value is None:
        return "не рассчитано"
    amount = int(value) / 100
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " ₸"


def _change(current, previous):
    if previous in (None, 0):
        return "нет базы для сравнения"
    delta = (int(current or 0) - int(previous)) / abs(int(previous)) * 100
    return f"{delta:+.1f}%"


def _build_digest(db, user, company_id, report_date, include_ai):
    data = finance.report(db, user, report_date, report_date, company_id=company_id, active_only=True)
    previous_date = report_date - timedelta(days=1)
    previous = finance.report(db, user, previous_date, previous_date, company_id=company_id, active_only=True)
    channels = data.get("channel_summary") or []
    channel_lines = [
        f"{row.get('channel')}: {_money(row.get('revenue'))}"
        for row in channels if row.get("channel") in {"Kaspi", "Wildberries", "Ozon", "Offline", "B2B"}
    ]
    lines = [
        f"QOR · отчёт за {report_date.strftime('%d.%m.%Y')}",
        f"Выручка: {_money(data.get('revenue'))}",
        f"Чистая прибыль: {_money(data.get('net_profit')) if data.get('net_profit_complete') else 'неполная — проверьте себестоимость/источники'}",
        f"Продано единиц: {data.get('units', 0)} · возвраты: {_money(data.get('returns'))}",
        f"К предыдущему дню: выручка {_change(data.get('revenue'), previous.get('revenue'))}; единицы {_change(data.get('units'), previous.get('units'))}.",
    ]
    if data.get("net_profit_complete") and previous.get("net_profit_complete"):
        lines.append(f"Изменение чистой прибыли: {_money((data.get('net_profit') or 0) - (previous.get('net_profit') or 0))} к предыдущему дню.")
    if channel_lines:
        lines.append("По каналам: " + "; ".join(channel_lines))
    stock_alerts = data.get("stock_alerts") or []
    if stock_alerts:
        examples = ", ".join(str(item.get("name") or item.get("sku") or "товар")[:50] for item in stock_alerts[:5])
        suffix = f" и ещё {len(stock_alerts)-5}" if len(stock_alerts) > 5 else ""
        lines.append(f"Низкий остаток: {len(stock_alerts)} позиций — {examples}{suffix}")
    else:
        lines.append("Критических остатков по установленным порогам нет.")
    if data.get("pending_cogs_sales"):
        lines.append(f"Важно: по {data['pending_cogs_sales']} продажам не подтверждена себестоимость; прибыль может быть неполной.")
    incomplete = data.get("pending_source_events")
    if incomplete:
        lines.append(f"Важно: есть {incomplete} ожидающих проверки источника операций.")
    if include_ai and ai.key_status()["configured"]:
        try:
            result = ai.assistant(db, user, {
                "agent": "analyst",
                "start": str(previous_date),
                "end": str(report_date),
                "company_id": company_id,
                "question": "Сравни последний день выбранного периода с предыдущим: дай 1 главный сигнал и 1 рекомендуемую проверку. Используй только доступные данные ERP, не повторяй суммы и не предлагай изменения без подтверждения.",
            })
            insight = str(result.get("answer") or "").strip()
            if insight:
                lines.append("Вывод ИИ: " + insight[:500])
        except Exception as exc:
            logger.warning("Daily report AI note unavailable (%s)", type(exc).__name__)
            lines.append("Комментарий ИИ сегодня недоступен; цифры отчёта подготовлены ERP.")
    return "\n".join(lines)


def _send_template(recipient, message, db=None):
    if not PHONE_RE.fullmatch(recipient):
        raise ValueError("Номер получателя должен быть в международном формате +XXXXXXXX")
    config = _whatsapp_config(db)
    if not provider_status(db)["configured"]:
        raise RuntimeError("WhatsApp Business Cloud API не настроен")
    version = config["graph_version"]
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise RuntimeError("Некорректная версия WhatsApp Graph API")
    url = f"https://graph.facebook.com/{version}/{config['phone_number_id']}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient.lstrip("+"),
        "type": "template",
        "template": {
            "name": config["template_name"],
            "language": {"code": config["language"]},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": message[:1000]}]}],
        },
    }
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {config['access_token']}"},
        json=payload,
        timeout=20,
    )
    if response.is_error:
        # Keep tokens and full recipient out of application logs and delivery errors.
        raise RuntimeError(f"WhatsApp API ответил HTTP {response.status_code}")
    body = response.json()
    return str(((body.get("messages") or [{}])[0]).get("id") or "")


def test_whatsapp_connection(db=None):
    config = _whatsapp_config(db)
    if not config["access_token"] or not config["phone_number_id"]:
        raise RuntimeError("Укажите токен доступа и ID номера WhatsApp")
    if not re.fullmatch(r"v\d+\.\d+", config["graph_version"]):
        raise RuntimeError("Некорректная версия WhatsApp Graph API")
    response = httpx.get(
        f"https://graph.facebook.com/{config['graph_version']}/{config['phone_number_id']}",
        params={"fields": "display_phone_number,verified_name"},
        headers={"Authorization": f"Bearer {config['access_token']}"},
        timeout=15,
    )
    if response.is_error:
        raise RuntimeError(f"WhatsApp API ответил HTTP {response.status_code}")
    body = response.json()
    return {"ok": True, "phone": str(body.get("display_phone_number") or ""),
            "verified_name": str(body.get("verified_name") or "")}


def run_due_daily_reports(at=None):
    """Send at most one digest per company/recipient/report day; retry failures on next run."""
    with SessionLocal() as db:
        settings = db.get(Setting, 1)
        if not settings or not settings.daily_report_enabled or not settings.daily_report_consent:
            return {"sent": 0, "skipped": "disabled_or_no_consent"}
        recipient = (settings.daily_report_recipient or "").strip()
        if not recipient or not provider_status(db)["configured"]:
            return {"sent": 0, "skipped": "provider_or_recipient_not_configured"}
        try:
            zone = ZoneInfo(settings.timezone or "Asia/Almaty")
            scheduled = datetime.strptime(settings.daily_report_time or "09:00", "%H:%M").time()
        except (ValueError, KeyError):
            logger.error("Daily report schedule has an invalid time zone or time")
            return {"sent": 0, "skipped": "invalid_schedule"}
        local_now = at.astimezone(zone) if at else datetime.now(zone)
        if local_now.time().replace(second=0, microsecond=0) < scheduled:
            return {"sent": 0, "skipped": "not_due"}
        report_date = local_now.date() - timedelta(days=1)
        owner = db.scalar(select(User).where(User.active.is_(True), User.role == "Owner").order_by(User.id))
        if not owner:
            return {"sent": 0, "skipped": "owner_missing"}
        companies = db.scalars(select(Company).where(Company.active.is_(True)).order_by(Company.id)).all()
        sent = 0
        for company in companies:
            scope(owner, company.id)
            delivery = db.scalar(select(DailyReportDelivery).where(
                DailyReportDelivery.company_id == company.id,
                DailyReportDelivery.report_date == report_date,
                DailyReportDelivery.recipient == recipient,
                DailyReportDelivery.provider == PROVIDER,
            ).with_for_update())
            if delivery and delivery.status == "sent":
                continue
            if not delivery:
                delivery = DailyReportDelivery(company_id=company.id, report_date=report_date,
                                               recipient=recipient, provider=PROVIDER, status="pending")
                db.add(delivery)
                db.flush()
            last_attempt = delivery.last_attempt_at
            if last_attempt is not None:
                if last_attempt.tzinfo is None:
                    last_attempt = last_attempt.replace(tzinfo=ZoneInfo("UTC"))
                if last_attempt > now() - timedelta(hours=1):
                    continue
            if int(delivery.attempts or 0) >= 6:
                continue
            delivery.status = "sending"
            delivery.attempts = int(delivery.attempts or 0) + 1
            delivery.last_attempt_at = now()
            db.commit()
            try:
                message = _build_digest(db, owner, company.id, report_date, settings.daily_report_ai_summary)
                provider_id = _send_template(recipient, message, db)
                delivery.status = "sent"
                delivery.provider_message_id = provider_id[:180]
                delivery.error = ""
                delivery.sent_at = now()
                sent += 1
            except Exception as exc:
                delivery.status = "failed"
                delivery.error = str(exc)[:500]
                logger.warning("Daily report delivery failed for company %s (%s)", company.id, type(exc).__name__)
            db.commit()
        return {"sent": sent, "report_date": str(report_date)}


def scheduler_loop():
    import time
    while True:
        try:
            run_due_daily_reports()
        except Exception:
            logger.exception("Daily report scheduler cycle failed")
        time.sleep(60)
