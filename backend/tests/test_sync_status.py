from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.main import SYNC_RUNNING_TIMEOUT_SECONDS, sync_status_for_display


def test_recent_sync_heartbeat_remains_running():
    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    account = SimpleNamespace(sync_status="running", sync_error="", last_sync=now)

    assert sync_status_for_display(account, now) == ("running", "")


def test_old_sync_heartbeat_is_reported_as_timeout_without_mutating_account():
    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    old = now - timedelta(seconds=SYNC_RUNNING_TIMEOUT_SECONDS + 1)
    account = SimpleNamespace(sync_status="running", sync_error="", last_sync=old)

    status, error = sync_status_for_display(account, now)

    assert status == "failed"
    assert error.startswith("SYNC_TIMEOUT:")
    assert account.sync_status == "running"
    assert account.sync_error == ""


def test_missing_heartbeat_is_reported_as_timeout():
    account = SimpleNamespace(sync_status="running", sync_error="", last_sync=None)

    status, error = sync_status_for_display(account)

    assert status == "failed"
    assert "повторно" in error


def test_terminal_status_and_error_are_preserved():
    account = SimpleNamespace(
        sync_status="partial", sync_error="catalog unavailable", last_sync=None
    )

    assert sync_status_for_display(account) == ("partial", "catalog unavailable")


def test_kaspi_bounded_report_status_is_not_hidden_by_archive_pause(monkeypatch):
    from app.main import kaspi_period_status_for_display

    now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    monkeypatch.setenv("KASPI_PAUSE_ACCOUNT_IDS", "77")
    account = SimpleNamespace(
        id=77, channel="Kaspi", sync_status="running", sync_error="KASPI_PERIOD_SYNC:lease",
        last_sync=now, integration_settings={"kaspi_period_job": {
            "start": "2026-10-01", "end": "2026-10-31", "mode": "issued", "status": "running",
        }},
    )

    assert kaspi_period_status_for_display(
        account, date(2026, 10, 1), date(2026, 10, 31), at=now,
    ) == ("running", "", now)


def test_kaspi_completed_period_uses_its_own_coverage_timestamp(monkeypatch):
    from app.kaspi_integrity import period_key
    from app.main import kaspi_period_status_for_display

    now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    synced = datetime(2026, 11, 3, 11, tzinfo=timezone.utc)
    start, end = date(2026, 10, 1), date(2026, 10, 31)
    monkeypatch.setenv("KASPI_PAUSE_ACCOUNT_IDS", "77")
    account = SimpleNamespace(
        id=77, channel="Kaspi", sync_status="partial", sync_error="KASPI_PERIOD_PAUSED",
        last_sync=now, integration_settings={"kaspi_period_sync": {
            period_key("issued", start, end): synced.isoformat(),
        }},
    )

    assert kaspi_period_status_for_display(account, start, end, at=now) == ("done", "", synced)


def test_marketplace_summary_does_not_keep_timed_out_sync_spinner(client):
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    from app.db import SessionLocal
    from app.main import SYNC_RUNNING_TIMEOUT_SECONDS
    from app.models import Account

    with SessionLocal() as db:
        account = db.get(Account, 1)
        account.channel = "Wildberries"
        account.sync_status = "running"
        account.last_sync = datetime.now(timezone.utc) - timedelta(
            seconds=SYNC_RUNNING_TIMEOUT_SECONDS + 1
        )
        db.commit()

    today = datetime.now(ZoneInfo("Asia/Almaty")).date().isoformat()
    response = client.get(
        f"/api/marketplace-summary?channel=Wildberries&start={today}&end={today}"
    )

    assert response.status_code == 200, response.text
    assert response.json()["sync_status"] == "failed"
    assert response.json()["sync_in_progress"] is False
    assert response.json()["sync_errors"][0].startswith("SYNC_TIMEOUT:")


def test_kaspi_period_sync_is_idempotent_while_account_sync_runs(client):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from app.db import SessionLocal
    from app.models import Account

    with SessionLocal() as db:
        account = db.get(Account, 1)
        account.sync_status = "running"
        account.last_sync = datetime.now(timezone.utc)
        db.commit()

    today = datetime.now(ZoneInfo("Asia/Almaty")).date().isoformat()
    response = client.post(
        f"/api/accounts/1/sync-kaspi-period?start={today}&end={today}&report_mode=issued"
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"
    assert response.json()["already_running"] is True
