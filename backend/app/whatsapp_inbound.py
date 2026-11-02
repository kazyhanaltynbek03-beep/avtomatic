"""Secure inbound WhatsApp Cloud API webhook for the QOR read-only assistant."""
import hashlib
import hmac
import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

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
    saved = "".join(c for c in str(getattr(setting, "daily_report_recipient", "")) if c.isdigit())
    return bool(saved and saved == "".join(c for c in str(sender) if c.isdigit()))


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
    if not config.get("inbound_enabled"):
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
                owner = db.scalar(select(User).where(User.active.is_(True), User.role.in_(("owner", "admin"))).order_by(User.id).limit(1))
                if not owner:
                    logger.error("WhatsApp assistant has no active owner account")
                    continue
                title = "WhatsApp " + sender[-6:]
                thread = db.scalar(select(AIThread).where(AIThread.user_id == owner.id, AIThread.title == title, AIThread.archived.is_(False)).order_by(AIThread.id.desc()).limit(1))
                if not thread:
                    thread = AIThread(user_id=owner.id, agent="rick", title=title, archived=False)
                    db.add(thread)
                    db.flush()
                recent = db.scalars(select(AIMessage).where(AIMessage.thread_id == thread.id).order_by(AIMessage.id.desc()).limit(40)).all()
                if any((row.meta or {}).get("whatsapp_message_id") == message_id for row in recent):
                    continue
                history = [{"role": row.role, "content": row.content} for row in reversed(recent) if row.role in ("user", "assistant")][-10:]
                db.add(AIMessage(thread_id=thread.id, role="user", content=text, attachments=[], meta={"channel": "whatsapp", "whatsapp_message_id": message_id}))
                job = Job(company_id=None, user_id=owner.id, kind="assistant", status="queued",
                          payload={"question": text, "agent": "rick", "history": history,
                                   "read_only": True, "thread_id": thread.id, "whatsapp_sender": sender})
                db.add(job)
                db.commit()
                from .worker import run_one
                background.add_task(run_one, job.id)
    return {"ok": True}


def send_whatsapp_text(db, recipient, message):
    """Send a user-initiated reply inside WhatsApp's service window."""
    config = _config(db)
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
