from datetime import date

import pytest
from .conftest import buy, sell, post, report, restock_return


def test_dashboard_summary_reuses_selected_finance_report(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "business_today", lambda: date(2026, 10, 31))
    buy(client, qty=10, cost=1000)
    sell(client, qty=1, price=2000, day="2026-10-02")
    summary = client.get(
        "/api/dashboard/summary",
        params={"start": "2026-10-01", "end": "2026-10-31"},
    )
    assert summary.status_code == 200, summary.text
    report_response = report(client)
    assert summary.json()["report"]["revenue"] == report_response["revenue"]
    assert summary.json()["report"]["net_profit"] == report_response["net_profit"]
    today = str(main.business_today())
    month_report = report(client, "2026-10-01", today)
    today_report = report(client, today, today)
    assert summary.json()["month"]["revenue"] == month_report["revenue"]
    assert summary.json()["month"]["gross_profit"] == month_report["gross_profit"]
    assert summary.json()["month"]["net_profit"] == month_report["net_profit"]
    assert summary.json()["today"]["revenue"] == today_report["revenue"]
    assert summary.json()["today"]["units"] == today_report["units"]


def test_disconnected_store_remains_in_historical_reports(client):
    from app.db import SessionLocal
    from app.models import Account

    buy(client, qty=5, cost=1000)
    sell(client, ref="ACTIVE-STORE", qty=1, price=2000, account=1)
    with SessionLocal() as db:
        db.add(Account(id=4, company_id=1, name="Old WB", channel="Wildberries"))
        db.commit()
    sell(client, ref="DISCONNECTED-STORE", qty=1, price=3000, account=4)

    before = report(client)
    assert before["revenue"] == 5000
    response = client.delete("/api/accounts/4/credentials")
    assert response.status_code == 200, response.text
    after = report(client)
    assert after["revenue"] == 5000
    assert next(row for row in after["channels"] if row["name"] == "Old WB")["revenue"] == 3000
    dashboard = client.get(
        "/api/dashboard/summary",
        params={"start": "2026-10-01", "end": "2026-10-31"},
    ).json()["report"]
    assert dashboard["revenue"] == 2000
    assert all(row["name"] != "Old WB" for row in dashboard["channels"])
    sales = client.get("/api/data/sales").json()["items"]
    assert [row["reference"] for row in sales] == ["ACTIVE-STORE"]
    with SessionLocal() as db:
        archived = db.get(Account, 4)
        assert archived.active is False
        assert db.query(Account).filter(Account.id == 4).count() == 1


def test_pending_source_scan_projects_only_confirmed_event_dates(client):
    from datetime import datetime, timezone
    from app import finance
    from app.db import SessionLocal
    from app.models import Account, MarketplaceRecord, User

    epoch_ms = int(datetime(2026, 10, 3, tzinfo=timezone.utc).timestamp() * 1000)
    with SessionLocal() as db:
        account = db.get(Account, 1)
        user = db.get(User, 1)
        db.add_all([
            MarketplaceRecord(account_id=1, company_id=account.company_id, source="kaspi",
                external_id="confirmed-order", payload={"record_type":"order_entry", "order_status":"COMPLETED", "completed_date":"2026-10-02"},
                status="received", stage_status="pending_mapping"),
            MarketplaceRecord(account_id=1, company_id=account.company_id, source="wb",
                external_id="confirmed-sale", payload={"record_type":"sale", "saleDt":epoch_ms},
                status="received", stage_status="pending_mapping"),
            MarketplaceRecord(account_id=1, company_id=account.company_id, source="kaspi",
                external_id="unconfirmed-order", payload={"record_type":"order_entry", "order_status":"NEW", "created_at":"2026-10-04"},
                status="received", stage_status="pending_mapping"),
        ])
        db.commit()

        assert finance.marketplace_source_event_days(db, user) == [date(2026, 10, 2), date(2026, 10, 3)]


def test_dashboard_summary_does_not_recompute_default_month(client, monkeypatch):
    from app import main

    today = date(2026, 10, 24)
    monkeypatch.setattr(main, "business_today", lambda: today)
    original_headline = main.f.report_headline
    periods = []

    def counted_headline(db, user, start, end, company_id=None, pending_source_days=None, include_balances=True):
        periods.append((start, end, company_id))
        return original_headline(db, user, start, end, company_id, pending_source_days, include_balances)

    monkeypatch.setattr(main.f, "report_headline", counted_headline)
    response = client.get(
        "/api/dashboard/summary",
        params={"start": "2026-10-01", "end": "2026-10-24"},
    )

    assert response.status_code == 200, response.text
    assert periods == [
        (date(2026, 10, 1), today, None),
        (today, today, None),
    ]


def test_stock_is_asset_not_expense(client):
    buy(client, qty=10, cost=1000, extra=1000, paid=11000)
    r = report(client)
    assert r["stock_value"] == 11000
    assert r["net_profit"] == 0
    assert r["cash_flow"] == -11000


def test_fifo_two_costs(client):
    buy(client, qty=2, cost=1000)
    buy(client, ref="P2", qty=3, cost=2000, day="2026-10-02")
    s = sell(
        client,
        qty=4,
        price=4000,
        day="2026-10-03",
        commission=400,
        logistics=100,
        advertising=200,
    )
    r = report(client)
    assert s["cogs"] == 6000
    assert r["stock_value"] == 2000
    assert r["gross_profit"] == 10000
    assert r["net_profit"] == 9300


def test_partial_return_restores_original_fifo_cost(client):
    buy(client, qty=2, cost=1000)
    buy(client, ref="P2", qty=3, cost=2000, day="2026-10-02")
    s = sell(client, qty=4, price=4000, paid=16000, day="2026-10-03")
    r1 = post(
        client,
        "returns",
        sale_id=s["id"],
        reference="R1",
        date="2026-10-04",
        quantity=3,
        refund=12000,
    )
    restock_return(client, r1["id"])
    r = report(client)
    assert r["revenue"] == 4000
    assert r["cogs"] == 2000
    assert r["stock_value"] == 6000
    assert r["cash"] == 4000
    r2 = post(
        client,
        "returns",
        sale_id=s["id"],
        reference="R2",
        date="2026-10-04",
        quantity=1,
        refund=4000,
    )
    restock_return(client, r2["id"])
    r = report(client)
    assert r["revenue"] == 0
    assert r["cogs"] == 0
    assert r["stock_value"] == 8000
    assert r["cash"] == 0


def test_rounding_conserves_minor_units(client):
    buy(client, qty=3, cost=100, extra=1)
    for i in range(3):
        sell(client, ref="S" + str(i), qty=1, price=200)
    r = report(client)
    assert r["cogs"] == 301
    assert r["stock_value"] == 0


def test_b2b_debt_cash_and_profit_separate(client):
    buy(client)
    s = sell(
        client,
        qty=2,
        price=3000,
        paid=1000,
        account=3,
        customer_id=1,
        due_date="2026-10-10",
    )
    r = report(client)
    assert r["b2b_debt"] == 5000
    assert r["net_profit"] == 4000
    assert r["cash"] == 1000
    post(
        client,
        "cash",
        company_id=1,
        sale_id=s["id"],
