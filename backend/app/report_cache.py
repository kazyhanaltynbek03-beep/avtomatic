"""Background snapshots for common business dashboard periods.

The snapshots use the existing deterministic finance engine. They are a read-through
performance layer only; financial formulas and the ERP ledger remain authoritative.
"""
from datetime import timedelta
import threading
import os
from time import monotonic
from sqlalchemy import select
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


def standard_ranges(today=None):
    today = today or business_today()
    yesterday = today - timedelta(days=1)
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
        (today, today), (yesterday, yesterday), (monday, today),
        (previous_week_start, previous_week_end), (current_month, today),
        (previous_month_start, previous_month_end), (quarter_start, today),
        (six_month_start, today), (year_start, today),
        (previous_year_start, previous_year_end),
    ]
    unique = {}
    for start, end in windows:
        unique[(start, end)] = (start, end)
    return list(unique.values())


def _scope_key(user, company_id):
    if company_id is not None:
        return f"company:{int(company_id)}"
    if user.role == "Owner":
        return "all"
    # Multi-company non-owners retain the normal authorization-filtered calculation.
    return None


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


def _full_scope_key(user, company_id=None, active_only=False):
    # Full snapshots are currently warmed for the owner, whose scope covers the
    # entire workspace. Other roles keep their own authorization-filtered reads.
    if user.role != "Owner":
        return None
    scope = f"company:{int(company_id)}" if company_id is not None else "all"
    return f"full:{scope}:{'active' if active_only else 'all'}"


def get_full_report(db, user, start, end, company_id=None, account_id=None, active_only=False):
    """Return a precomputed full report, including its saved historical detail."""
    if account_id is not None:
        return None
    key = _full_scope_key(user, company_id, active_only)
    if key is None:
        return None
    row = db.scalar(select(DashboardReportCache).where(
        DashboardReportCache.scope_key == key,
        DashboardReportCache.start_date == start,
        DashboardReportCache.end_date == end,
    ))
    if row is None or row.refreshed_at is None:
        return None
    current = now()
    refreshed_at = row.refreshed_at
    if refreshed_at.tzinfo is None and current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    elif refreshed_at.tzinfo is not None and current.tzinfo is None:
        refreshed_at = refreshed_at.replace(tzinfo=None)
    max_age = timedelta(minutes=60) if end >= business_today() - timedelta(days=1) else timedelta(hours=12)
    return row.payload if refreshed_at >= current - max_age else None


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
    db.commit()
    return True


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
    """Refresh one missing/stale standard range per worker turn."""
    owner = db.scalar(select(User).where(
        User.active.is_(True), User.role == "Owner"
    ).order_by(User.id).limit(1))
    if owner is None:
        return False

    today = business_today()
    ranges = standard_ranges(today)
    company_ids = list(db.scalars(select(Company.id).where(Company.active.is_(True)).order_by(Company.id)))
    scopes = [("all", None)] + [(f"company:{company_id}", company_id) for company_id in company_ids]
    current = now()
    refresh_interval = timedelta(minutes=5)

    for key, company_id in scopes:
        for start, end in ranges:
            row = db.scalar(select(DashboardReportCache).where(
                DashboardReportCache.scope_key == key,
                DashboardReportCache.start_date == start,
                DashboardReportCache.end_date == end,
            ))
            if row and row.refreshed_at and row.refreshed_at > current - refresh_interval:
                continue
            pending_days = get_pending_source_days(db, owner, company_id)
            payload = finance.report_headline(db, owner, start, end, company_id, pending_days)
            if row is None:
                row = DashboardReportCache(
                    scope_key=key, start_date=start, end_date=end,
                    payload=payload, refreshed_at=current,
                )
                db.add(row)
            else:
                row.payload = payload
                row.refreshed_at = current
            db.commit()
            return True
    return False


def refresh_full_one(db):
    """Prepare one complete finance report outside the request path."""
    from fastapi.encoders import jsonable_encoder

    owner = db.scalar(select(User).where(
        User.active.is_(True), User.role == "Owner"
    ).order_by(User.id).limit(1))
    if owner is None:
        return False

    today = business_today()
    ranges = standard_ranges(today)
    company_ids = list(db.scalars(
        select(Company.id).where(Company.active.is_(True)).order_by(Company.id)
    ))
    scopes = [("all", None)] + [
        (f"company:{company_id}", company_id) for company_id in company_ids
    ]
    current = now()
    # Refresh recent operational periods frequently; older snapshots are still
    # rebuilt regularly so late marketplace backfills are reflected.
    for scope_key, company_id in scopes:
        for start, end in ranges:
            for active_only in (True, False):
                key = f"full:{scope_key}:{'active' if active_only else 'all'}"
                row = db.scalar(select(DashboardReportCache).where(
                    DashboardReportCache.scope_key == key,
                    DashboardReportCache.start_date == start,
                    DashboardReportCache.end_date == end,
                ))
                cutoff_age = timedelta(minutes=10) if end >= today - timedelta(days=1) else timedelta(hours=2)
                if row and row.refreshed_at:
                    refreshed_at = row.refreshed_at
                    compare_now = current
                    if refreshed_at.tzinfo is None and compare_now.tzinfo is not None:
                        compare_now = compare_now.replace(tzinfo=None)
                    elif refreshed_at.tzinfo is not None and compare_now.tzinfo is None:
                        refreshed_at = refreshed_at.replace(tzinfo=None)
                    if refreshed_at > compare_now - cutoff_age:
                        continue
                payload = jsonable_encoder(finance.report(
                    db, owner, start, end, company_id, active_only=active_only
                ))
                store_full_report(
                    db, owner, start, end, payload, company_id, active_only=active_only
                )
                return True
    return False


def cache_ready(db):
    owner = db.scalar(select(User).where(
        User.active.is_(True), User.role == "Owner"
    ).order_by(User.id).limit(1))
    if owner is None:
        return True
    today = business_today()
    ranges = standard_ranges(today)
    company_ids = list(db.scalars(select(Company.id).where(Company.active.is_(True)).order_by(Company.id)))
    keys = ["all"] + [f"company:{company_id}" for company_id in company_ids]
    rows = db.scalars(select(DashboardReportCache).where(
        DashboardReportCache.scope_key.in_(keys),
    )).all()
    ready = {(row.scope_key, row.start_date, row.end_date) for row in rows}
    return all((key, start, end) in ready for key in keys for start, end in ranges)


if __name__ == "__main__":
    import logging
    import time
    from .db import SessionLocal

    logging.basicConfig(level=logging.INFO)
    warming = "--warm" in __import__("sys").argv[1:]
    while True:
        try:
            with SessionLocal() as db:
                if warming and cache_ready(db):
                    break
                refreshed = refresh_one(db)
                if os.getenv("QOR_FULL_REPORT_CACHE", "0").strip().lower() in {"1", "true", "yes"}:
                    refreshed = refresh_full_one(db) or refreshed
        except Exception:
            logging.exception("Dashboard report cache refresh failed")
            refreshed = False
        if not refreshed:
            time.sleep(2 if warming else 5)
