"""Background snapshots for common business dashboard periods.

The snapshots use the existing deterministic finance engine. They are a read-through
performance layer only; financial formulas and the ERP ledger remain authoritative.
"""
from datetime import timedelta
import threading
import os
import logging
from time import monotonic
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from .models import Account, Company, DashboardReportCache, User, business_today, now
from . import finance


_PENDING_SOURCE_DAYS_TTL_SECONDS = 30
_PENDING_SOURCE_DAYS_CACHE = {}
_PENDING_SOURCE_DAYS_LOCKS = {}
_PENDING_SOURCE_DAYS_GUARD = threading.Lock()


def _month_start(day):
    return day.replace(day=1)


def _shift_month(day, offset):
    month = day.month - 1 + offset
    year = day.year + month // 12
    month = month % 12 + 1
    return day.replace(year=year, month=month, day=1)


def _full_cache_enabled():
    return os.getenv("QOR_FULL_REPORT_CACHE", "0").strip().lower() in {"1", "true", "yes"}


def standard_ranges(today=None):
    today = today or business_today()
    yesterday = today - timedelta(days=1)
    day_before_yesterday = today - timedelta(days=2)
    monday = today - timedelta(days=today.weekday())
    previous_week_start = monday - timedelta(days=7)
    previous_week_end = monday - timedelta(days=1)
    current_month = _month_start(today)
    previous_month_start = _shift_month(current_month, -1)
    previous_month_end = current_month - timedelta(days=1)
    quarter_start = today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1)
    year_start = today.replace(month=1, day=1)
    previous_year_start = year_start.replace(year=year_start.year - 1)
    previous_year_end = year_start - timedelta(days=1)
    six_month_start = _shift_month(current_month, -5)
    windows = [
        (today, today), (yesterday, yesterday), (day_before_yesterday, day_before_yesterday),
        (monday, today), (previous_week_start, previous_week_end), (current_month, today),
        (previous_month_start, previous_month_end), (quarter_start, today),
        (six_month_start, today), (year_start, today),
        (previous_year_start, previous_year_end),
    ]
    # Keep only the named reporting windows used by the UI. A rolling 370-day
    # full-report snapshot is intentionally omitted; year and half-year reports
    # are still prepared from the already-synced ledger below.
    unique = {}
    for start, end in windows:
        unique[(start, end)] = (start, end)
    return list(unique.values())


def _scope_key(user, company_id):
    if company_id is not None:
        if _full_cache_enabled() and user.role != "Owner":
            return f"user:{int(user.id)}:company:{int(company_id)}"
        return f"company:{int(company_id)}"
    if user.role == "Owner":
        return "all"
    return f"user:{int(user.id)}:all" if _full_cache_enabled() else None



def _analytics_users(db):
    from .security import allowed
    users = db.scalars(select(User).where(
        User.active.is_(True)
    ).order_by(User.id)).all()
    allowed_users = [user for user in users if allowed(user, "analytics")]
    if not _full_cache_enabled():
        return [user for user in allowed_users if user.role == "Owner"][:1]
    return allowed_users


def _scopes_for(user, active_company_ids):
    if user.role == "Owner":
        return [("all", None)] + [
            (f"company:{company_id}", company_id) for company_id in active_company_ids
        ]
    if not _full_cache_enabled():
        return []
    allowed_ids = set()
    for value in (user.company_ids or []):
        try:
            allowed_ids.add(int(value))
        except (TypeError, ValueError):
            continue
    return [(f"user:{int(user.id)}:all", None)] + [
        (f"user:{int(user.id)}:company:{company_id}", company_id)
        for company_id in active_company_ids if company_id in allowed_ids
    ]

def invalidate_marketplace_reports(db, channel, start, end, company_id=None):
    """Mark affected snapshots stale while keeping them readable during refresh.

    A sync can change rows already represented by a prepared report. Preserve the
    last snapshot for immediate reads, then make the background worker rebuild only
    scopes and periods that overlap the changed event window.
    """
    if not channel or end < start:
        return 0
    users = _analytics_users(db)
    company_ids = list(db.scalars(select(Company.id).where(
        Company.active.is_(True)
    ).order_by(Company.id)))
    scope_keys = set()
    for user in users:
        for dashboard_scope, scoped_company in _scopes_for(user, company_ids):
            if company_id is not None and scoped_company not in (None, company_id):
                continue
            scope_keys.add(dashboard_scope)
            scope_keys.add(_marketplace_scope_key(user, channel, scoped_company))
            if _full_cache_enabled():
                scope_keys.add(_full_scope_key(user, scoped_company, True))
                scope_keys.add(_full_scope_key(user, scoped_company, False))
    if not scope_keys:
        return 0
    result = db.execute(update(DashboardReportCache).where(
        DashboardReportCache.scope_key.in_(scope_keys),
        DashboardReportCache.start_date <= end,
        DashboardReportCache.end_date >= start,
    ).values(refreshed_at=now() - timedelta(days=1)))
    db.commit()
    return int(result.rowcount or 0)


def get(db, user, start, end, company_id=None):
    key = _scope_key(user, company_id)
    if key is None:
        return None
    row = db.scalar(select(DashboardReportCache).where(
        DashboardReportCache.scope_key == key,
        DashboardReportCache.start_date == start,
        DashboardReportCache.end_date == end,
    ))
    return row.payload if row else None


def _store_cache_row(db, key, start, end, payload, refreshed_at=None):
    """Insert or update a snapshot, recovering if another worker inserts it first."""
    refreshed_at = refreshed_at or now()
    row = db.scalar(select(DashboardReportCache).where(
        DashboardReportCache.scope_key == key,
        DashboardReportCache.start_date == start,
        DashboardReportCache.end_date == end,
    ))
    if row is None:
        db.add(DashboardReportCache(
            scope_key=key, start_date=start, end_date=end,
            payload=payload, refreshed_at=refreshed_at,
        ))
    else:
        row.payload = payload
        row.refreshed_at = refreshed_at
    try:
        db.commit()
    except IntegrityError:
        # Warmup and the always-on worker may calculate the same cold period.
        db.rollback()
        row = db.scalar(select(DashboardReportCache).where(
            DashboardReportCache.scope_key == key,
            DashboardReportCache.start_date == start,
            DashboardReportCache.end_date == end,
        ))
        if row is None:
            raise
        row.payload = payload
        row.refreshed_at = refreshed_at
        db.commit()
    return True


def _marketplace_scope_key(user, channel, company_id=None):
    if company_id is not None:
        scope = f"company:{int(company_id)}"
    elif user.role == "Owner":
        scope = "all"
    else:
        scope = f"user:{int(user.id)}:all"
    return f"marketplace:{channel}:{scope}"


def get_marketplace_summary(db, user, channel, start, end, company_id=None):
    key = _marketplace_scope_key(user, channel, company_id)
    row = db.scalar(select(DashboardReportCache).where(
        DashboardReportCache.scope_key == key,
        DashboardReportCache.start_date == start,
        DashboardReportCache.end_date == end,
    ))
    return row.payload if row else None


def store_marketplace_summary(db, user, channel, start, end, payload, company_id=None):
    key = _marketplace_scope_key(user, channel, company_id)
    data = dict(payload)
    data["report_cached_at"] = now().isoformat()
    row = db.scalar(select(DashboardReportCache).where(
        DashboardReportCache.scope_key == key,
        DashboardReportCache.start_date == start,
        DashboardReportCache.end_date == end,
    ))
    if row is None:
        row = DashboardReportCache(
            scope_key=key, start_date=start, end_date=end,
            payload=data, refreshed_at=now(),
        )
        db.add(row)
    else:
        row.payload = data
        row.refreshed_at = now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.scalar(select(DashboardReportCache).where(
            DashboardReportCache.scope_key == key,
            DashboardReportCache.start_date == start,
            DashboardReportCache.end_date == end,
        ))
        if row is None:
            raise
        row.payload = data
        row.refreshed_at = now()
        db.commit()
    return True


def _full_scope_key(user, company_id=None, active_only=False):
    scope = f"company:{int(company_id)}" if company_id is not None else "all"
    if user.role == "Owner":
        return f"full:{scope}:{'active' if active_only else 'all'}"
    return f"full:user:{int(user.id)}:{scope}:{'active' if active_only else 'all'}"

def get_full_report(db, user, start, end, company_id=None, account_id=None, active_only=False):
    """Return a prepared report immediately; the worker refreshes it in the background."""
    if account_id is not None:
        return None
    key = _full_scope_key(user, company_id, active_only)
    row = db.scalar(select(DashboardReportCache).where(
        DashboardReportCache.scope_key == key,
        DashboardReportCache.start_date == start,
        DashboardReportCache.end_date == end,
    ))
    return row.payload if row else None

def store_full_report(db, user, start, end, payload, company_id=None,
                      account_id=None, active_only=False):
    if account_id is not None:
        return False
    key = _full_scope_key(user, company_id, active_only)
    if key is None:
        return False
    row = db.scalar(select(DashboardReportCache).where(
        DashboardReportCache.scope_key == key,
        DashboardReportCache.start_date == start,
        DashboardReportCache.end_date == end,
    ))
    if row is None:
        row = DashboardReportCache(
            scope_key=key, start_date=start, end_date=end,
            payload=payload, refreshed_at=now(),
        )
        db.add(row)
    else:
        row.payload = payload
        row.refreshed_at = now()
    try:
        db.commit()
    except IntegrityError:
        # A web request and the warmup worker can finish the same cold snapshot
        # together. Reload the unique row and update it instead of failing the job.
        db.rollback()
        row = db.scalar(select(DashboardReportCache).where(
            DashboardReportCache.scope_key == key,
            DashboardReportCache.start_date == start,
            DashboardReportCache.end_date == end,
        ))
        if row is None:
            raise
        row.payload = payload
        row.refreshed_at = now()
        db.commit()
    return True


def _ai_scope_key(user, company_id=None, account_id=None):
    if account_id is not None:
        return f"ai:account:{int(account_id)}"
    if company_id is not None:
        return f"ai:company:{int(company_id)}"
    return "ai:all" if user.role == "Owner" else None


def get_ai_snapshot(db, user, start, end, company_id=None, account_id=None):
    """Read a recent AI snapshot, including historical accounts excluded by dashboard KPIs."""
    key = _ai_scope_key(user, company_id, account_id)
    if key is None:
        return None
    row = db.scalar(select(DashboardReportCache).where(
        DashboardReportCache.scope_key == key,
        DashboardReportCache.start_date == start,
        DashboardReportCache.end_date == end,
    ))
    if row is None:
        return None
    refreshed_at = row.refreshed_at
    current = now()
    if refreshed_at.tzinfo is None:
        current = current.replace(tzinfo=None)
    if refreshed_at < current - timedelta(minutes=5):
        return None
    return row.payload


def store_ai_snapshot(db, user, start, end, payload, company_id=None, account_id=None):
    """Persist a bounded-period AI snapshot so follow-up questions reuse the result."""
    key = _ai_scope_key(user, company_id, account_id)
    if key is None:
        return False
    return _store_cache_row(db, key, start, end, payload)


def get_pending_source_days(db, user, company_id=None, active_only=True):
    """Reuse the expensive source-event scan across nearby report calculations.

    The finance rows themselves are still queried for every period. Only the
    completeness signal is memoized, for a short window while the background
    worker warms the standard ranges.
    """
    key = (int(user.id), int(company_id) if company_id is not None else None, bool(active_only))
    with _PENDING_SOURCE_DAYS_GUARD:
        lock = _PENDING_SOURCE_DAYS_LOCKS.setdefault(key, threading.Lock())
    with lock:
        cached = _PENDING_SOURCE_DAYS_CACHE.get(key)
        current = monotonic()
        if cached and current - cached[0] < _PENDING_SOURCE_DAYS_TTL_SECONDS:
            return cached[1]
        days = tuple(finance.marketplace_source_event_days(
            db, user, company_id, active_only=active_only,
        ))
        _PENDING_SOURCE_DAYS_CACHE[key] = (monotonic(), days)
        if len(_PENDING_SOURCE_DAYS_CACHE) > 128:
            oldest = sorted(_PENDING_SOURCE_DAYS_CACHE.items(), key=lambda item: item[1][0])[:32]
            for old_key, _value in oldest:
                _PENDING_SOURCE_DAYS_CACHE.pop(old_key, None)
        return days


def refresh_one(db):
    """Refresh one missing/stale dashboard period for every analytics user."""
    users = _analytics_users(db)
    if not users:
        return False
    today = business_today()
    ranges = standard_ranges(today)
    company_ids = list(db.scalars(select(Company.id).where(
        Company.active.is_(True)
    ).order_by(Company.id)))
    current = now()
    for user in users:
        for key, company_id in _scopes_for(user, company_ids):
            for start, end in ranges:
                row = db.scalar(select(DashboardReportCache).where(
                    DashboardReportCache.scope_key == key,
                    DashboardReportCache.start_date == start,
                    DashboardReportCache.end_date == end,
                ))
                span_days = (end - start).days
                if span_days <= 1 and end >= today - timedelta(days=1):
                    refresh_age = timedelta(minutes=5)
                elif span_days <= 7 and end >= today - timedelta(days=7):
                    refresh_age = timedelta(minutes=15)
                else:
                    refresh_age = timedelta(hours=12)
                if row and row.refreshed_at and row.refreshed_at > current - refresh_age:
                    continue
                pending_days = get_pending_source_days(db, user, company_id)
                payload = finance.report_headline(db, user, start, end, company_id, pending_days)
                _store_cache_row(db, key, start, end, payload, current)
                return True
    return False

def refresh_marketplace_one(db):
    """Prepare one raw-marketplace summary for a standard period and scope."""
    from .main import _calculate_marketplace_summary

    users = _analytics_users(db)
    if not users:
        return False
    today = business_today()
    ranges = standard_ranges(today)
    company_ids = list(db.scalars(select(Company.id).where(
        Company.active.is_(True)
    ).order_by(Company.id)))
    current = now()
    for user in users:
        for _scope, company_id in _scopes_for(user, company_ids):
            for channel in ("Kaspi", "Wildberries", "Ozon"):
                key = _marketplace_scope_key(user, channel, company_id)
                for start, end in ranges:
                    row = db.scalar(select(DashboardReportCache).where(
                        DashboardReportCache.scope_key == key,
                        DashboardReportCache.start_date == start,
                        DashboardReportCache.end_date == end,
                    ))
                    span_days = (end - start).days
                    if span_days <= 1 and end >= today - timedelta(days=1):
                        refresh_age = timedelta(minutes=5)
                    elif span_days <= 7 and end >= today - timedelta(days=7):
                        refresh_age = timedelta(minutes=15)
                    else:
                        refresh_age = timedelta(hours=6)
                    if row and row.refreshed_at and row.refreshed_at > current - refresh_age:
                        continue
                    payload = _calculate_marketplace_summary(
                        channel, start, end, company_id, None, user, db
                    )
                    cached_payload = {**payload, "report_cached_at": current.isoformat()}
                    _store_cache_row(db, key, start, end, cached_payload, current)
                    logging.getLogger(__name__).info(
                        "Prepared marketplace summary %s for %s..%s", key, start, end
                    )
                    return True
    return False


def refresh_full_one(db):
    """Prepare one full finance report per turn for every analytics user."""
    from fastapi.encoders import jsonable_encoder

    users = _analytics_users(db)
    if not users:
        return False
    today = business_today()
    ranges = standard_ranges(today)
    company_ids = list(db.scalars(select(Company.id).where(
        Company.active.is_(True)
    ).order_by(Company.id)))
    current = now()
    for user in users:
        for scope_key, company_id in _scopes_for(user, company_ids):
            for start, end in ranges:
                for active_only in (True, False):
                    key = _full_scope_key(user, company_id, active_only)
                    row = db.scalar(select(DashboardReportCache).where(
                        DashboardReportCache.scope_key == key,
                        DashboardReportCache.start_date == start,
                        DashboardReportCache.end_date == end,
                    ))
                    span_days = (end - start).days
                    if span_days <= 1 and end >= today - timedelta(days=1):
                        refresh_age = timedelta(minutes=5)
                    elif span_days <= 7 and end >= today - timedelta(days=7):
                        refresh_age = timedelta(minutes=15)
                    else:
                        refresh_age = timedelta(hours=12)
                    if row and row.refreshed_at and row.refreshed_at > current - refresh_age:
                        continue
                    payload = jsonable_encoder(finance.report(
                        db, user, start, end, company_id, active_only=active_only
                    ))
                    store_full_report(
                        db, user, start, end, payload, company_id, active_only=active_only
                    )
                    logging.getLogger(__name__).info(
                        "Prepared full report cache %s for %s..%s", key, start, end
                    )
                    return True
    return False

def cache_ready(db):
    """Wait until every UI report period is snapshotted before web starts."""
    users = _analytics_users(db)
    if not users:
        return True
    today = business_today()
    ranges = standard_ranges(today)
    company_ids = list(db.scalars(select(Company.id).where(
        Company.active.is_(True)
    ).order_by(Company.id)))
    expected = []
    full_expected = []
    marketplace_expected = []
    for user in users:
        scopes = _scopes_for(user, company_ids)
        for scope_key, company_id in scopes:
            expected.append(scope_key)
            for variant in (True, False):
                full_expected.append(_full_scope_key(user, company_id, variant))
            for channel in ("Kaspi", "Wildberries", "Ozon"):
                marketplace_expected.append(_marketplace_scope_key(user, channel, company_id))
    expected = list(dict.fromkeys(expected))
    rows = db.scalars(select(DashboardReportCache).where(
        DashboardReportCache.scope_key.in_(expected),
    )).all()
    ready = {(row.scope_key, row.start_date, row.end_date) for row in rows}
    if not all((key, start, end) in ready for key in expected for start, end in ranges):
        return False

    if _full_cache_enabled():
        full_expected = list(dict.fromkeys(full_expected))
        full_rows = db.scalars(select(DashboardReportCache).where(
            DashboardReportCache.scope_key.in_(full_expected),
        )).all()
        full_ready = {(row.scope_key, row.start_date, row.end_date) for row in full_rows}
        if not all((key, start, end) in full_ready for key in full_expected for start, end in ranges):
            return False

    # Gate web startup on every period exposed by the report controls. This
    # prevents a cold synchronous calculation when a customer selects month,
    # half-year, or year immediately after the VPS starts.
    marketplace_expected = list(dict.fromkeys(marketplace_expected))
    marketplace_rows = db.scalars(select(DashboardReportCache).where(
        DashboardReportCache.scope_key.in_(marketplace_expected),
    )).all()
    marketplace_ready = {
        (row.scope_key, row.start_date, row.end_date) for row in marketplace_rows
    }
    return all(
        (key, start, end) in marketplace_ready
        for key in marketplace_expected for start, end in ranges
    )


if __name__ == "__main__":
    import logging
    import time
    from .db import SessionLocal

    logging.basicConfig(level=logging.INFO)
    warming = "--warm" in __import__("sys").argv[1:]
    cycle = 0
    while True:
        try:
            full_cache_enabled = _full_cache_enabled()
            phase_count = 3 if full_cache_enabled else 2
            phase = cycle % phase_count
            cycle += 1
            with SessionLocal() as db:
                if warming and cache_ready(db):
                    break
                if phase == 0:
                    refreshed = refresh_one(db)
                elif phase == 1 and full_cache_enabled:
                    refreshed = refresh_full_one(db)
                else:
                    refreshed = refresh_marketplace_one(db)
        except Exception:
            logging.exception("Dashboard report cache refresh failed")
            refreshed = False
        if not refreshed:
            time.sleep(2 if warming else 5)
