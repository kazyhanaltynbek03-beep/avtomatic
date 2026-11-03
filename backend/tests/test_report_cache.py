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


def test_standard_ranges_include_rolling_370_day_window():
    today = date(2026, 11, 3)
    start = date(2025, 10, 30)
    assert (start, today) in report_cache.standard_ranges(today)
    assert (today - start).days + 1 == 370


def test_full_report_cache_is_scoped_and_persisted():
    user = SimpleNamespace(id=42, role="Owner")
    payload = {"revenue": 123, "daily": []}

    class DB:
        row = None
        committed = False

        def scalar(self, _query):
            return self.row

        def add(self, row):
            self.row = row

        def commit(self):
            self.committed = True

    db = DB()
    start, end = date(2026, 11, 1), date(2026, 11, 3)
    assert report_cache.store_full_report(db, user, start, end, payload)
    assert db.committed
    assert db.row.scope_key == "full:active:all"
    assert report_cache.get_full_report(db, user, start, end) == payload
    assert report_cache.get_full_report(
        db, SimpleNamespace(id=7, role="Accountant"), start, end,
    ) is None


def test_active_overview_report_serves_prewarmed_snapshot(client, monkeypatch):
    from app import main
    from app.db import SessionLocal
    from app.models import User

    payload = {"revenue": 9876, "daily": [], "stock_alerts": []}
    monkeypatch.setenv("QOR_FULL_REPORT_CACHE", "1")
    with SessionLocal() as db:
        owner = db.get(User, 1)
        report_cache.store_full_report(
            db, owner, date(2026, 11, 1), date(2026, 11, 3), payload,
            company_id=1, active_only=True,
        )

    def unexpected_report(*_args, **_kwargs):
        raise AssertionError("prewarmed report should bypass the full calculation")

    monkeypatch.setattr(main.f, "report", unexpected_report)
    response = client.get("/api/report", params={
        "start": "2026-11-01", "end": "2026-11-03",
        "company_id": 1, "active_only": "true",
    })
    assert response.status_code == 200, response.text
    assert response.json() == payload
