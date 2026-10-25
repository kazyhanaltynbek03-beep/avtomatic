from datetime import datetime, timedelta, timezone
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
