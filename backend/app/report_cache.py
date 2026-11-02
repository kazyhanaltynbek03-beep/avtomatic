"""Background snapshots for common business dashboard periods.

The snapshots use the existing deterministic finance engine. They are a read-through
performance layer only; financial formulas and the ERP ledger remain authoritative.
"""
from datetime import timedelta
from sqlalchemy import select
from .models import Account, Company, DashboardReportCache, User, business_today, now
from . import finance


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
            pending_days = finance.marketplace_source_event_days(db, owner, company_id)
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
    cutoff = now() - timedelta(minutes=5)
    rows = db.scalars(select(DashboardReportCache).where(
        DashboardReportCache.scope_key.in_(keys),
        DashboardReportCache.refreshed_at >= cutoff,
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
        except Exception:
            logging.exception("Dashboard report cache refresh failed")
            refreshed = False
        if not refreshed:
            time.sleep(2 if warming else 5)
