from datetime import datetime
from zoneinfo import ZoneInfo

from app.db import SessionLocal
from app.models import DailyReportDelivery, Setting
from app import daily_reports


def test_daily_report_settings_requires_recipient_consent_and_provider(client, monkeypatch):
    for key in ("QOR_WHATSAPP_ACCESS_TOKEN", "QOR_WHATSAPP_PHONE_NUMBER_ID", "QOR_WHATSAPP_TEMPLATE_NAME"):
        monkeypatch.delenv(key, raising=False)

    missing_consent = client.put("/api/automation/daily-report", json={
        "enabled": True, "time": "09:00", "recipient": "+77001234567", "consent": False,
    })
    assert missing_consent.status_code == 422

    no_provider = client.put("/api/automation/daily-report", json={
        "enabled": True, "time": "09:00", "recipient": "+77001234567", "consent": True,
    })
    assert no_provider.status_code == 409

    disabled = client.put("/api/automation/daily-report", json={
        "enabled": False, "time": "09:00", "recipient": "+77001234567", "consent": True,
    })
    assert disabled.status_code == 200


def test_daily_digest_is_deduplicated_per_company_and_report_date(client, monkeypatch):
    monkeypatch.setenv("QOR_WHATSAPP_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("QOR_WHATSAPP_PHONE_NUMBER_ID", "test-number-id")
    monkeypatch.setenv("QOR_WHATSAPP_TEMPLATE_NAME", "qor_daily_business_report")
    with SessionLocal() as db:
        config = db.get(Setting, 1)
        config.daily_report_enabled = True
        config.daily_report_consent = True
        config.daily_report_recipient = "+77001234567"
        config.daily_report_time = "09:00"
        db.commit()

    sent = []
    monkeypatch.setattr(daily_reports, "_send_template", lambda recipient, message: sent.append((recipient, message)) or "wamid.test")
    scheduled_time = datetime(2026, 10, 31, 9, 5, tzinfo=ZoneInfo("Asia/Almaty"))
    first = daily_reports.run_due_daily_reports(at=scheduled_time)
    second = daily_reports.run_due_daily_reports(at=scheduled_time)

    assert first == {"sent": 2, "report_date": "2026-10-30"}
    assert second["sent"] == 0
    assert len(sent) == 2
    assert all("Выручка:" in message and "Чистая прибыль:" in message for _, message in sent)
    with SessionLocal() as db:
        deliveries = db.query(DailyReportDelivery).filter_by(report_date="2026-10-30", status="sent").all()
        assert len(deliveries) == 2
