"""Secure inbound WhatsApp Cloud API webhook for the QOR read-only assistant."""
import hashlib
import hmac
import logging
import re

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, func

from .db import get_db
from .models import AIMessage, AIThread, Job, Setting, User
from .system_secrets import load_config

logger = logging.getLogger(__name__)
router = APIRouter()


def _config(db):
    return load_config("whatsapp_cloud", db)


def _recipient_allowed(db, sender):
    setting = db.get(Setting, 1)
    if not setting:
        return False
    config = _config(db)
    client_number = "".join(c for c in str(config.get("client_chat_number") or "") if c.isdigit())
    owner_number = "".join(c for c in str(config.get("owner_chat_number") or "") if c.isdigit())
    legacy_number = "".join(c for c in str(getattr(setting, "daily_report_recipient", "")) if c.isdigit())
    allowed = [number for number in (client_number, owner_number) if number]
    if not allowed:
        allowed = [legacy_number] if legacy_number else []
    elif not client_number and legacy_number:
        allowed.append(legacy_number)
    sender_number = "".join(c for c in str(sender) if c.isdigit())
    return bool(sender_number and sender_number in allowed)


def _enqueue_inbound_text(db, sender, text, message_id, provider):
    owner = db.scalar(select(User).where(
        User.active.is_(True), func.lower(User.role).in_(("owner", "admin"))
    ).order_by(User.id).limit(1))
    if not owner:
        logger.error("WhatsApp assistant has no active owner account")
        return None
    digits = "".join(char for char in str(sender) if char.isdigit())
    title = "WhatsApp " + (digits[-6:] or "chat")
    thread = db.scalar(select(AIThread).where(
        AIThread.user_id == owner.id, AIThread.title == title, AIThread.archived.is_(False)
    ).order_by(AIThread.id.desc()).limit(1))
    if not thread:
        thread = AIThread(user_id=owner.id, agent="rick", title=title, archived=False)
        db.add(thread)
        db.flush()
    recent = db.scalars(
        select(AIMessage).where(AIMessage.thread_id == thread.id)
        .order_by(AIMessage.id.desc()).limit(40)
    ).all()
    if any((row.meta or {}).get("whatsapp_message_id") == message_id for row in recent):
        return None
    history = [{"role": row.role, "content": row.content}
               for row in reversed(recent) if row.role in ("user", "assistant")][-10:]
    db.add(AIMessage(thread_id=thread.id, role="user", content=text, attachments=[],
                     meta={"channel": "whatsapp", "whatsapp_message_id": message_id}))
    buyer_request = re.search(
        r"(закуп|закупить|закупка|покупать|что купить|что закуп|что продавать|хорошо прода|лучше прода|бестсел|лидер продаж|топ продаж|перспектив.*товар|ниша|сатып ал|тауар.*сат|сұраныс|қай тауар|жақсы сат|сатылымы жақсы|what to buy|best.?selling|procure|niche)",
        text.casefold(),
    )
    job = Job(company_id=None, user_id=owner.id, kind="assistant", status="queued",
              payload={"question": text, "agent": "buyer" if buyer_request else "rick",
                       "history": history, "read_only": True, "include_tool_data": True,
                       "thread_id": thread.id, "whatsapp_sender": sender,
                       "whatsapp_provider": provider})
    db.add(job)
    db.commit()
    return job.id


@router.get("/api/webhooks/whatsapp")
async def verify_whatsapp_webhook(request: Request, db=Depends(get_db)):
    config = _config(db)
    expected = str(config.get("webhook_verify_token") or "")
    if (request.query_params.get("hub.mode") != "subscribe"
            or not expected
            or not hmac.compare_digest(request.query_params.get("hub.verify_token", ""), expected)):
        raise HTTPException(403, "Webhook verification failed")
    return PlainTextResponse(request.query_params.get("hub.challenge", ""))


@router.post("/api/webhooks/whatsapp")
async def receive_whatsapp_webhook(request: Request, background: BackgroundTasks, db=Depends(get_db)):
    config = _config(db)
    if (config.get("provider", "whatsapp_cloud") not in {"whatsapp_cloud", "meta"}
            or not config.get("inbound_enabled")):
        return {"ok": True}
    app_secret = str(config.get("app_secret") or "")
    if not app_secret:
        raise HTTPException(503, "WhatsApp webhook is not configured")
    raw = await request.body()
    supplied = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid webhook payload")
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            if str(metadata.get("phone_number_id", "")) != str(config.get("phone_number_id", "")):
                continue
            for message in value.get("messages", []):
                if message.get("type") != "text":
                    continue
                sender = str(message.get("from") or "")
                text = str((message.get("text") or {}).get("body") or "").strip()[:3000]
                message_id = str(message.get("id") or "")
                if not sender or not message_id or not text or not _recipient_allowed(db, sender):
                    continue
                job_id = _enqueue_inbound_text(db, sender, text, message_id, "whatsapp_cloud")
                if job_id:
                    from .worker import run_one
                    background.add_task(run_one, job_id)
                logger.info("Queued WhatsApp assistant job %s", job_id)
    return {"ok": True}


@router.post("/api/webhooks/greenapi")
async def receive_green_api_webhook(request: Request, background: BackgroundTasks, db=Depends(get_db)):
    config = _config(db)
    if config.get("provider") != "green_api" or not config.get("inbound_enabled"):
        return {"ok": True}
    webhook_token = str(config.get("green_webhook_token") or "").strip()
    if not webhook_token:
        raise HTTPException(503, "Green-API webhook is not configured")
    supplied = request.headers.get("Authorization", "")
    if not hmac.compare_digest(supplied, "Bearer " + webhook_token):
        raise HTTPException(401, "Invalid Green-API webhook authorization")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid Green-API webhook payload")
    if payload.get("typeWebhook") != "incomingMessageReceived":
        return {"ok": True}
    instance_id = str((payload.get("instanceData") or {}).get("idInstance") or "")
    if instance_id != str(config.get("green_api_instance_id") or ""):
        logger.warning("Ignoring Green-API webhook for an unconfigured instance")
        return {"ok": True}
    sender_data = payload.get("senderData") or {}
    chat_id = str(sender_data.get("chatId") or "")
    message_data = payload.get("messageData") or {}
    message_type = str(message_data.get("typeMessage") or "")
    if message_type == "textMessage":
        message_text = str((message_data.get("textMessageData") or {}).get("textMessage") or "").strip()[:3000]
    elif message_type == "extendedTextMessage":
        message_text = str((message_data.get("extendedTextMessageData") or {}).get("text") or "").strip()[:3000]
    else:
        return {"ok": True}
    message_id = str(payload.get("idMessage") or "")
    if (not re.fullmatch(r"\d{8,15}@c\.us", chat_id) or not message_id
            or not message_text or not _recipient_allowed(db, chat_id)):
        return {"ok": True}
    job_id = _enqueue_inbound_text(db, chat_id, message_text, message_id, "green_api")
    if job_id:
        from .worker import run_one
        background.add_task(run_one, job_id)
        logger.info("Queued WhatsApp assistant job %s", job_id)
    return {"ok": True}


def send_whatsapp_text(db, recipient, message, provider=None):
    """Send a user-initiated reply inside WhatsApp's service window."""
    config = _config(db)
    provider = provider or config.get("provider", "whatsapp_cloud")
    if provider == "green_api":
        from .green_api import send_text
        return send_text(db, recipient, message)
    token = str(config.get("access_token") or "").strip()
    phone_id = str(config.get("phone_number_id") or "").strip()
    version = str(config.get("graph_version") or "v26.0").strip()
    if not token or not phone_id:
        raise RuntimeError("WhatsApp Cloud API credentials are missing")
    response = httpx.post(
        f"https://graph.facebook.com/{version}/{phone_id}/messages",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"messaging_product": "whatsapp", "recipient_type": "individual",
              "to": str(recipient), "type": "text",
              "text": {"preview_url": False, "body": str(message)[:4096]}},
        timeout=20,
    )
    if response.is_error:
        logger.warning("WhatsApp reply failed with status %s", response.status_code)
        raise RuntimeError("WhatsApp could not deliver the reply")
    return response.json()



def _excel_safe(value):
    import json
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, str):
        value = value[:32000]
        if value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
    return value


def make_report_workbook(tool_results, answer, period, question):
    """Stream a transparent workbook from exact ERP tool outputs without holding cells in memory."""
    import json
    import re
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook(write_only=True)
    summary = wb.create_sheet("Сводка")
    title = WriteOnlyCell(summary, value="Отчёт QOR")
    title.font = Font(size=16, bold=True, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor="172033")
    summary.append([title])
    was_limited = any(bool((item.get("result") or {}).get("report_truncated")) for item in (tool_results or []) if isinstance(item, dict))
    summary_rows = [
        ("Запрос", _excel_safe(str(question)[:1000])),
        ("Период", " — ".join(period or []) if isinstance(period, list) else str(period or "")),
        ("Ответ Claude", _excel_safe(str(answer)[:4000])),
        ("Данные", "Листы содержат результаты ERP-инструментов, использованных Claude. Значения сохранены в исходных единицах источника."),
        ("Объём выгрузки", "Достигнут предел выгрузки: сузьте период или магазин." if was_limited else "Все строки выбранной выгрузки помещены в файл."),
    ]
    for label, value in summary_rows:
        summary.append([label, value])
    summary.column_dimensions["A"].width = 24
    summary.column_dimensions["B"].width = 100

    used_titles = {"Сводка"}
    table_count = 0
    rows_remaining = 4000

    def make_title(raw):
        clean = re.sub(r"[\[\]:*?/\\]", "_", str(raw or "Данные"))
        base = (clean[:31] or "Данные").strip("'")
        title = base
        suffix = 2
        while title in used_titles:
            ending = f"_{suffix}"
            title = base[:31-len(ending)] + ending
            suffix += 1
        used_titles.add(title)
        return title

    def styled_header(ws, headers):
        cells = []
        for header in headers:
            cell = WriteOnlyCell(ws, value=str(header)[:120])
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="2563EB")
            cells.append(cell)
        ws.append(cells)

    def add_table(title, rows):
        nonlocal table_count, rows_remaining
        if not isinstance(rows, list) or not rows or rows_remaining <= 0:
            return
        def flatten(item):
            flattened = {}
            for key, value in item.items():
                if isinstance(value, dict):
                    for nested_key, nested_value in value.items():
                        flattened[f"{key}.{nested_key}"] = nested_value
                else:
                    flattened[key] = value
            return flattened
        objects = [flatten(item) for item in rows if isinstance(item, dict)]
        ws = wb.create_sheet(make_title(title))
        ws.freeze_panes = "A2"
        if objects:
            all_headers = list(dict.fromkeys(key for item in objects for key in item.keys()))
            headers = all_headers[:39]
            overflow_headers = all_headers[39:]
            display_headers = headers + (["Дополнительные поля (JSON)"] if overflow_headers else [])
            styled_header(ws, display_headers)
            count = min(len(objects), rows_remaining)
            for item in objects[:count]:
                values = [_excel_safe(item.get(key)) for key in headers]
                if overflow_headers:
                    values.append(_excel_safe({key: item.get(key) for key in overflow_headers if key in item}))
                ws.append(values)
            rows_remaining -= count
            for index in range(len(display_headers)):
                ws.column_dimensions[get_column_letter(index + 1)].width = 28
            ws.auto_filter.ref = f"A1:{get_column_letter(len(display_headers))}{count + 1}"
        else:
            styled_header(ws, ["Значение"])
            count = min(len(rows), rows_remaining)
            for item in rows[:count]:
                ws.append([_excel_safe(item)])
            rows_remaining -= count
            ws.column_dimensions["A"].width = 36
        table_count += 1

    def collect(value, path, depth=0):
        if depth > 5:
            return
        if isinstance(value, list):
            if value and all(isinstance(item, dict) for item in value):
                add_table(path, value)
            elif value and all(not isinstance(item, (dict, list)) for item in value):
                add_table(path, value)
            else:
                for index, item in enumerate(value):
                    collect(item, f"{path}_{index + 1}", depth + 1)
        elif isinstance(value, dict):
            for key, nested in value.items():
                if isinstance(nested, (dict, list)):
                    collect(nested, f"{path}_{key}", depth + 1)

    for index, item in enumerate(tool_results or []):
        tool = str(item.get("tool") or f"Источник {index + 1}")
        source_data = item.get("result")
        before = table_count
        if isinstance(source_data, (dict, list)):
            collect(source_data, tool)
        if table_count == before and source_data is not None and rows_remaining > 0:
            rows = [[str(key), _excel_safe(value)] for key, value in list(source_data.items())[:min(500, rows_remaining)]] if isinstance(source_data, dict) else [[_excel_safe(value)] for value in source_data[:min(500, rows_remaining)]]
            ws = wb.create_sheet(make_title(tool))
            ws.freeze_panes = "A2"
            styled_header(ws, ["Поле", "Значение"] if rows and len(rows[0]) == 2 else ["Значение"])
            for row in rows:
                ws.append(row)
            rows_remaining -= len(rows)
            table_count += 1

    if table_count == 0:
        ws = wb.create_sheet("Данные")
        styled_header(ws, ["Результаты инструментов"])
        ws.append([_excel_safe(json.dumps(tool_results or [], ensure_ascii=False, default=str)[:30000])])
    output = BytesIO()
    wb.save(output)
    return output.getvalue()

def send_whatsapp_document(db, recipient, content, filename="qor-report.xlsx"):
    import httpx
    config = _config(db)
    token = str(config.get("access_token") or "").strip()
    phone_id = str(config.get("phone_number_id") or "").strip()
    version = str(config.get("graph_version") or "v26.0").strip()
    if not token or not phone_id:
        raise RuntimeError("WhatsApp Cloud API credentials are missing")
    headers = {"Authorization": f"Bearer {token}"}
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    media = httpx.post(
        f"https://graph.facebook.com/{version}/{phone_id}/media",
        headers=headers,
        data={"messaging_product": "whatsapp", "type": mime},
        files={"file": (filename, content, mime)},
        timeout=30,
    )
    if media.is_error:
        logger.warning("WhatsApp report upload failed with status %s", media.status_code)
        raise RuntimeError("WhatsApp could not upload the report")
    media_id = str(media.json().get("id") or "")
    if not media_id:
        raise RuntimeError("WhatsApp did not return a report media ID")
    response = httpx.post(
        f"https://graph.facebook.com/{version}/{phone_id}/messages",
        headers={**headers, "Content-Type": "application/json"},
        json={"messaging_product": "whatsapp", "recipient_type": "individual",
              "to": str(recipient), "type": "document",
              "document": {"id": media_id, "filename": filename}},
        timeout=20,
    )
    if response.is_error:
        logger.warning("WhatsApp report delivery failed with status %s", response.status_code)
        raise RuntimeError("WhatsApp could not deliver the report")
    return response.json()
