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
from .security import scope

logger = logging.getLogger(__name__)
PROVIDER = "whatsapp_cloud"
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def provider_status():
    missing = [key for key in (
        "QOR_WHATSAPP_ACCESS_TOKEN",
        "QOR_WHATSAPP_PHONE_NUMBER_ID",
        "QOR_WHATSAPP_TEMPLATE_NAME",
    ) if not os.getenv(key, "").strip()]
    return {"provider": PROVIDER, "configured": not missing, "missing": missing}


def _money(value):
    if value is None:
        return "не рассчитано"
    amount = int(value) / 100
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " ₸"


def _build_digest(db, user, company_id, report_date, include_ai):
    data = finance.report(db, user, report_date, report_date, company_id=company_id, active_only=True)
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
    ]
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
    if include_ai and os.getenv("ANTHROPIC_API_KEY"):
        try:
            result = ai.assistant(db, user, {
                "agent": "analyst",
                "start": str(report_date),
                "end": str(report_date),
                "company_id": company_id,
                "question": "Подготовь короткий управленческий комментарий к ежедневному отчёту: 1 главный сигнал и 1 рекомендуемая проверка. Используй только доступные данные ERP, не повторяй суммы и не предлагай изменения без подтверждения.",
            })
            insight = str(result.get("answer") or "").strip()
            if insight:
                lines.append("Вывод ИИ: " + insight[:500])
        except Exception as exc:
            logger.warning("Daily report AI note unavailable (%s)", type(exc).__name__)
            lines.append("Комментарий ИИ сегодня недоступен; цифры отчёта подготовлены ERP.")
    return "\n".join(lines)


def _send_template(recipient, message):
    if not PHONE_RE.fullmatch(recipient):
        raise ValueError("Номер получателя должен быть в международном формате +XXXXXXXX")
    config = provider_status()
    if not config["configured"]:
        raise RuntimeError("WhatsApp Business Cloud API не настроен")
    version = os.getenv("QOR_WHATSAPP_GRAPH_VERSION", "v26.0").strip()
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise RuntimeError("Некорректная версия WhatsApp Graph API")
    url = f"https://graph.facebook.com/{version}/{os.environ['QOR_WHATSAPP_PHONE_NUMBER_ID']}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient.lstrip("+"),
        "type": "template",
        "template": {
            "name": os.environ["QOR_WHATSAPP_TEMPLATE_NAME"],
            "language": {"code": os.getenv("QOR_WHATSAPP_TEMPLATE_LANGUAGE", "ru")},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": message[:1000]}]}],
        },
    }
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {os.environ['QOR_WHATSAPP_ACCESS_TOKEN']}"},
        json=payload,
        timeout=20,
    )
    if response.is_error:
        # Keep tokens and full recipient out of application logs and delivery errors.
        raise RuntimeError(f"WhatsApp API ответил HTTP {response.status_code}")
    body = response.json()
    return str(((body.get("messages") or [{}])[0]).get("id") or "")


def run_due_daily_reports(at=None):
    """Send at most one digest per company/recipient/report day; retry failures on next run."""
    with SessionLocal() as db:
        settings = db.get(Setting, 1)
        if not settings or not settings.daily_report_enabled or not settings.daily_report_consent:
            return {"sent": 0, "skipped": "disabled_or_no_consent"}
        recipient = (settings.daily_report_recipient or "").strip()
        if not recipient or not provider_status()["configured"]:
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
                provider_id = _send_template(recipient, message)
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
