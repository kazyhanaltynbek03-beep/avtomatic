from app.db import SessionLocal
from app.models import Job


def _green_config():
    return {
        "provider": "green_api",
        "inbound_enabled": True,
        "green_api_instance_id": "7103513543",
        "green_webhook_token": "webhook-test-secret-012345",
        "client_chat_number": "+77082903190",
        "owner_chat_number": "+77786712780",
    }


def _payload(sender="77786712780@c.us", message_type="textMessage"):
    data = {"typeMessage": message_type}
    if message_type == "textMessage":
        data["textMessageData"] = {"textMessage": "Покажи продажи за неделю"}
    else:
        data["extendedTextMessageData"] = {"text": "Покажи продажи за неделю"}
    return {
        "typeWebhook": "incomingMessageReceived",
        "instanceData": {"idInstance": 7103513543},
        "idMessage": "green-api-message-1",
        "senderData": {"chatId": sender},
        "messageData": data,
    }


def test_green_api_webhook_queues_direct_allowlisted_text(client, monkeypatch):
    import app.whatsapp_inbound as inbound
    import app.worker as worker

    monkeypatch.setattr(inbound, "load_config", lambda provider, db: _green_config())
    ran = []
    monkeypatch.setattr(worker, "run_one", lambda job_id: ran.append(job_id))

    response = client.post(
        "/api/webhooks/greenapi",
        headers={"Authorization": "Bearer webhook-test-secret-012345"},
        json=_payload(),
    )

    assert response.status_code == 200
    assert ran
    with SessionLocal() as db:
        job = db.get(Job, ran[0])
        assert job.status == "queued"
        assert job.payload["question"] == "Покажи продажи за неделю"
        assert job.payload["whatsapp_sender"] == "77786712780@c.us"
        assert job.payload["whatsapp_provider"] == "green_api"


def test_green_api_webhook_acknowledges_but_logs_disallowed_sender(client, monkeypatch, caplog):
    import logging
    import app.whatsapp_inbound as inbound

    caplog.set_level(logging.INFO, logger="app.whatsapp_inbound")
    monkeypatch.setattr(inbound, "load_config", lambda provider, db: _green_config())
    response = client.post(
        "/api/webhooks/greenapi",
        headers={"Authorization": "Bearer webhook-test-secret-012345"},
        json=_payload(sender="77000000000@c.us"),
    )

    assert response.status_code == 200
    assert "reason=recipient_not_allowed" in caplog.text
    assert "…0000" in caplog.text
    assert "Покажи продажи" not in caplog.text
    with SessionLocal() as db:
        assert db.query(Job).count() == 0


def test_green_api_webhook_accepts_extended_text(client, monkeypatch):
    import app.whatsapp_inbound as inbound
    import app.worker as worker

    monkeypatch.setattr(inbound, "load_config", lambda provider, db: _green_config())
    ran = []
    monkeypatch.setattr(worker, "run_one", lambda job_id: ran.append(job_id))
    response = client.post(
        "/api/webhooks/greenapi",
        headers={"Authorization": "Bearer webhook-test-secret-012345"},
        json=_payload(message_type="extendedTextMessage"),
    )

    assert response.status_code == 200
    assert ran


def test_whatsapp_delivery_failure_is_not_marked_done(client, monkeypatch):
    import app.ai as ai
    import app.whatsapp_inbound as inbound
    from app.worker import run_one

    with SessionLocal() as db:
        job = Job(company_id=None, user_id=1, kind="assistant", status="queued",
                  payload={"question": "Покажи продажи", "whatsapp_sender": "77786712780@c.us",
                           "whatsapp_provider": "green_api", "thread_id": 0})
        db.add(job)
        db.commit()
        job_id = job.id

    monkeypatch.setattr(ai, "assistant", lambda db, user, payload: {"answer": "Отчёт готов"})

    def fail_send(*args, **kwargs):
        raise RuntimeError("Green-API не отправил сообщение (HTTP 401)")

    monkeypatch.setattr(inbound, "send_whatsapp_text", fail_send)
    assert run_one(job_id)

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed"
        assert job.result["whatsapp_delivery_status"] == "failed"
        assert job.result["answer"] == "Отчёт готов"
        assert "HTTP 401" in job.error
