from datetime import date
from types import SimpleNamespace

from app import report_cache


def test_pending_source_days_are_reused_briefly_and_scoped(monkeypatch):
    report_cache._PENDING_SOURCE_DAYS_CACHE.clear()
    report_cache._PENDING_SOURCE_DAYS_LOCKS.clear()
    clock = [100.0]
    calls = []

    def source_days(db, user, company_id=None, account_ids=None, active_only=True):
        calls.append((user.id, company_id, active_only))
        return [date(2026, 11, 1) if active_only else date(2026, 11, 2)]

    monkeypatch.setattr(report_cache, "monotonic", lambda: clock[0])
    monkeypatch.setattr(report_cache.finance, "marketplace_source_event_days", source_days)
    user = SimpleNamespace(id=42)

    assert report_cache.get_pending_source_days(object(), user, company_id=7) == (date(2026, 11, 1),)
    assert report_cache.get_pending_source_days(object(), user, company_id=7) == (date(2026, 11, 1),)
    assert report_cache.get_pending_source_days(object(), user, company_id=7, active_only=False) == (date(2026, 11, 2),)
    assert len(calls) == 2

    clock[0] += report_cache._PENDING_SOURCE_DAYS_TTL_SECONDS + 1
    assert report_cache.get_pending_source_days(object(), user, company_id=7) == (date(2026, 11, 1),)
    assert len(calls) == 3
