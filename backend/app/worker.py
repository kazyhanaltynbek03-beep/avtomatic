import time, logging, re
from datetime import timedelta
from sqlalchemy import select
from fastapi import HTTPException
from .db import SessionLocal
from .models import Job, User, ProductCardVersion, AIThread, AIMessage, now
from .security import scope
from . import ai, daily_reports
from .product_studio import assess_performance, next_experiment

logging.basicConfig(level=logging.INFO)


def schedule_due_card_reviews():
    """Queue each due marketplace-card review once. Safe to call every worker loop."""
    with SessionLocal() as db:
        due = db.scalars(select(ProductCardVersion).where(
            ProductCardVersion.review_after.is_not(None),
            ProductCardVersion.review_after <= now(),
            ProductCardVersion.review_state == "scheduled",
        ).limit(50).with_for_update(skip_locked=True)).all()
        for card in due:
            owner = db.scalar(select(User).where(User.active == True, User.role.in_(["Owner","Admin"])).order_by(User.id))
            if not owner: continue
            if card.company_id not in (owner.company_ids or []) and owner.role != "Owner": continue
            db.add(Job(company_id=card.company_id,user_id=owner.id,kind="card_review",payload={"card_id":card.id}))
            card.review_state = "queued"
        db.commit()
        return len(due)


def _card_review(db, job, user):
    card = db.get(ProductCardVersion, int(job.payload["card_id"]))
    if not card: raise ValueError("Карточка не найдена")
    baseline = db.get(ProductCardVersion, card.parent_version_id) if card.parent_version_id else None
    assessment = assess_performance(card.metrics or {}, baseline.metrics if baseline else None)
    card.last_reviewed_at = now(); card.review_state = "reviewed"
    policy = card.optimization_policy or {}
    experiment = next_experiment(card.version) if assessment.get("should_optimize") else None
    new_card = None
    if assessment.get("decision") == "rollback" and baseline:
        # Rollback is prepared, never falsely reported as marketplace publication.
        card.status = "rollback_recommended"
    elif assessment.get("decision") == "optimize" and policy.get("auto_optimize", True):
        latest = db.scalar(select(ProductCardVersion.version).where(ProductCardVersion.product_id==card.product_id, ProductCardVersion.marketplace==card.marketplace).order_by(ProductCardVersion.version.desc()).limit(1)) or card.version
        new_card = ProductCardVersion(company_id=card.company_id,product_id=card.product_id,marketplace=card.marketplace,version=latest+1,title=card.title,description=card.description,characteristics=card.characteristics,image_document_ids=card.image_document_ids,status="optimization_draft",parent_version_id=card.id,optimization_policy=policy,review_state="idle",validation={"passed":False,"errors":[],"warnings":[assessment["reason"]],"requires_ai_regeneration":True,"experiment":experiment})
        db.add(new_card); db.flush()
    thread = db.scalar(select(AIThread).where(AIThread.user_id==user.id, AIThread.company_id==card.company_id, AIThread.agent=="rick", AIThread.archived==False).order_by(AIThread.id.desc()))
    if not thread:
        thread=AIThread(user_id=user.id,company_id=card.company_id,agent="rick",title="Оптимизация карточек"); db.add(thread); db.flush()
    version_ref = f"V{new_card.version}" if new_card else f"V{card.version}"
    message = f"Проверил карточку {card.marketplace.upper()} V{card.version}. {assessment['reason']}."
    if new_card: message += f" Подготовлен черновик {version_ref}: {experiment['label']}. Перед публикацией он должен пройти QOR Validator."
    elif assessment.get("decision") == "rollback": message += f" Рекомендую вернуть предыдущую версию V{baseline.version}; автоматическая публикация не имитируется без live write API."
    else: message += " Текущую версию оставляем без изменений."
    db.add(AIMessage(thread_id=thread.id,role="assistant",content=message,attachments=[],meta={"type":"card_review","card_id":card.id,"new_card_id":new_card.id if new_card else None,"assessment":assessment,"experiment":experiment}))
    return {"card_id":card.id,"new_card_id":new_card.id if new_card else None,"assessment":assessment,"experiment":experiment}


def run_one(job_id=None):
    with SessionLocal() as db:
        # Lease recovery after crashes. Failed provider calls are retried explicitly,
        # to avoid duplicate billable image generations.
        stale = db.scalars(
            select(Job).where(
                Job.status == "running", Job.started_at < now() - timedelta(minutes=15)
            )
        ).all()
        for j in stale:
            j.status = "failed"
            j.error = "Задача прервана сервером. Перед повтором проверьте лимит провайдера."
        db.commit()
        query = select(Job).where(Job.status == "queued")
        if job_id is not None:
            query = query.where(Job.id == int(job_id))
        job = db.scalar(query.order_by(Job.id).with_for_update(skip_locked=True))
        if not job:
            return False
        job.status = "running"
        job.started_at = now()
        job.attempts += 1
        db.commit()
        jid = job.id
        try:
            user = db.get(User, job.user_id)
            if not user or not user.active:
                raise ValueError("Пользователь отключён")
            if job.company_id:
                scope(user, job.company_id)
            if job.kind == "card_review":
                result = _card_review(db, job, user)
            else:
                result = {
                    "assistant": ai.assistant,
                    "content": ai.content,
                    "designer": ai.designer,
                }[job.kind](db, user, job.payload)
            report_data = result.pop("report_data", None) if isinstance(result, dict) else None
            if job.kind == "assistant" and job.payload.get("whatsapp_sender"):
                answer = str(result.get("answer") or "Не удалось сформировать ответ по данным ERP.")[:4000]
                thread_id = int(job.payload.get("thread_id") or 0)
                if thread_id:
                    db.add(AIMessage(thread_id=thread_id, role="assistant", content=answer, attachments=[], meta={"channel": "whatsapp"}))
                db.flush()
                from .whatsapp_inbound import send_whatsapp_text, send_whatsapp_document, make_report_workbook
                delivery_state = "sent"
                delivery_failure = None
                reply_sent = False
                try:
                    provider = job.payload.get("whatsapp_provider")
                    send_whatsapp_text(db, job.payload["whatsapp_sender"], answer, provider=provider)
                    reply_sent = True
                    question = str(job.payload.get("question") or "")
                    wants_excel = re.search(r"(?:\bexcel\b|\bxlsx\b|эксел|эксель|таблиц)", question, re.I)
                    if report_data and wants_excel and provider != "green_api":
                        workbook = make_report_workbook(report_data, answer, result.get("period"), question)
                        send_whatsapp_document(db, job.payload["whatsapp_sender"], workbook, "qor-report.xlsx")
                except Exception as exc:
                    delivery_state = "partial" if reply_sent else "failed"
                    logging.warning("WhatsApp assistant delivery %s for job %s (%s): %s",
                                    delivery_state, jid, type(exc).__name__, str(exc)[:240])
                    delivery_failure = exc
                if isinstance(result, dict):
                    result["whatsapp_delivery_status"] = delivery_state
                job.result = __import__("fastapi").encoders.jsonable_encoder(result)
                if delivery_failure:
                    job.status = "failed"
                    job.error = f"WhatsApp delivery {delivery_state}: {str(delivery_failure)}"[:500]
                else:
                    job.status = "done"
            else:
                job.result = __import__("fastapi").encoders.jsonable_encoder(result)
                job.status = "done"
            db.commit()
        except Exception as e:
            db.rollback()
            job = db.get(Job, jid)
            job.status = "failed"
            job.error = str(e.detail if isinstance(e, HTTPException) else e)[:500]
            db.commit()
            logging.warning("Job %s failed: %s", jid, type(e).__name__)
        return True


if __name__ == "__main__":
    last_whatsapp_alert_check = 0.0
    while True:
        schedule_due_card_reviews()
        if time.monotonic() - last_whatsapp_alert_check >= 60:
            try:
                daily_reports.run_due_whatsapp_alerts()
            except Exception:
                logging.exception("WhatsApp alert monitor cycle failed")
            last_whatsapp_alert_check = time.monotonic()
        if not run_one():
            time.sleep(2)
