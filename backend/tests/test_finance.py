from datetime import date

import pytest
from .conftest import buy, sell, post, report, restock_return


def test_dashboard_summary_reuses_selected_finance_report(client):
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
    from app import main
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
        reference="PAY",
        date="2026-10-03",
        amount=2000,
        category="Продажа",
    )
    r = report(client)
    assert r["b2b_debt"] == 3000
    assert r["net_profit"] == 4000
    assert r["cash"] == 3000


def test_oversell_rolls_back(client):
    buy(client, qty=2)
    r = client.post(
        "/api/post/sales",
        json={
            "company_id": 1,
            "account_id": 1,
            "product_id": 1,
            "reference": "S",
            "date": "2026-10-02",
            "quantity": 3,
            "unit_price": 3000,
        },
    )
    assert r.status_code == 422
    assert report(client)["stock_value"] == 2000
    assert client.get("/api/data/sales").json()["total"] == 0


def test_duplicate_post_is_idempotently_rejected(client):
    buy(client)
    sell(client)
    r = client.post(
        "/api/post/sales",
        json={
            "company_id": 1,
            "account_id": 1,
            "product_id": 1,
            "reference": "S1",
            "date": "2026-10-02",
            "quantity": 3,
            "unit_price": 3000,
        },
    )
    assert r.status_code == 409
    assert report(client)["units"] == 3
    assert report(client)["stock_value"] == 7000


def test_expense_accrual_separate_from_payment(client):
    post(
        client,
        "expenses",
        company_id=1,
        reference="E1",
        date="2026-10-01",
        category="Аренда",
        amount=1200,
        paid=False,
    )
    r = report(client)
    assert r["net_profit"] == -1200
    assert r["cash"] == 0


def test_inventory_writeoff_recognizes_expense(client):
    buy(client)
    post(
        client,
        "adjustments",
        company_id=1,
        product_id=1,
        date="2026-10-02",
        quantity=-2,
        kind="writeoff",
        reason="Повреждение при хранении",
    )
    r = report(client)
    assert r["stock_value"] == 8000
    assert r["expenses"] == 2000
    assert r["net_profit"] == -2000


def test_historical_stock_and_cash(client):
    buy(client, paid=10000)
    sell(client, paid=9000)
    r = report(client, end="2026-10-01")
    assert r["stock_value"] == 10000
    assert r["cash"] == -10000
    assert r["revenue"] == 0


def test_late_return_hits_its_period(client):
    buy(client)
    s = sell(client)
    ret = post(
        client, "returns", sale_id=s["id"], reference="R", date="2026-11-01", quantity=1
    )
    restock_return(client, ret["id"])
    r = report(client)
    assert r["revenue"] == 9000
    assert r["cogs"] == 3000
    r = report(client, start="2026-11-01", end="2026-11-30")
    assert r["revenue"] == -3000
    assert r["cogs"] == -1000


def test_no_cross_company_ownership_consumption(client):
    from app.db import SessionLocal
    from app.models import ProductCompany
    with SessionLocal() as db:
        db.add(ProductCompany(product_id=1, company_id=2))
        db.commit()
    buy(client, company=2)
    r = client.post(
        "/api/post/sales",
        json={
            "company_id": 1,
            "account_id": 1,
            "product_id": 1,
            "reference": "S",
            "date": "2026-10-02",
            "quantity": 1,
            "unit_price": 3000,
        },
    )
    assert r.status_code == 422


def test_account_company_mismatch(client):
    buy(client)
    r = client.post(
        "/api/post/sales",
        json={
            "company_id": 1,
            "account_id": 2,
            "product_id": 1,
            "reference": "S",
            "date": "2026-10-02",
            "quantity": 1,
            "unit_price": 3000,
        },
    )
    assert r.status_code == 422


def test_return_over_quantity_and_over_refund(client):
    buy(client)
    s = sell(client, paid=0)
    for qty, refund in [(4, 0), (1, 3000)]:
        assert (
            client.post(
                "/api/post/returns",
                json={
                    "sale_id": s["id"],
                    "reference": "R",
                    "date": "2026-10-03",
                    "quantity": qty,
                    "refund": refund,
                },
            ).status_code
            == 422
        )


def test_backdating_rejected(client):
    buy(client, day="2026-10-05")
    assert (
        client.post(
            "/api/post/adjustments",
            json={
                "company_id": 1,
                "product_id": 1,
                "date": "2026-10-04",
                "quantity": 1,
                "reason": "Opening balance",
            },
        ).status_code
        == 422
    )


def test_multi_line_landed_cost_conserves_total(client):
    p = post(
        client,
        "purchases",
        company_id=1,
        reference="PO",
        supplier="S",
        date="2026-10-01",
        extra_cost=101,
        lines=[
            {"product_id": 1, "quantity": 2, "unit_cost": 100},
            {"product_id": 2, "quantity": 1, "unit_cost": 100},
        ],
    )
    assert p["total"] == 401
    assert report(client)["stock_value"] == 401


def test_negative_and_zero_cash_validation(client):
    r = client.post(
        "/api/post/cash",
        json={
            "company_id": 1,
            "reference": "C",
            "date": "2026-10-01",
            "amount": 0,
            "category": "Other",
        },
    )
    assert r.status_code == 422


def test_report_details_reconciles_profit_and_cash(client):
    buy(client, qty=5, cost=1000, paid=5000)
    sell(client, qty=2, price=3000, paid=6000, commission=200, logistics=100, advertising=50)
    for metric in ["revenue", "cogs", "gross_profit", "commission", "logistics", "advertising", "net_profit", "cash", "cash_flow", "stock_value"]:
        res = client.get("/api/report/details", params={"start":"2026-10-01", "end":"2026-10-31", "metric":metric})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["difference"] == 0, (metric, body)
        assert body["rows"]

@pytest.mark.parametrize("method,weights,expected", [
    ("quantity", (1, 3), (250, 750)),
    ("value", (1000, 6000), (142, 858)),
    ("weight", (1000, 6000), (142, 858)),
    ("volume", (1000, 12000), (76, 924)),
])
def test_full_cost_allocation_methods_conserve_every_tenge(client, method, weights, expected):
    # product 1: 1kg / 1000cm3; product 2: 2kg / 4000cm3
    versions = {p["id"]: p["version"] for p in client.get("/api/data/products?limit=10").json()["items"]}
    assert client.put("/api/data/products/1", json={
        "version":versions[1],"sku":"A","name":"Alpha","price":10000,"weight_g":1000,"volume_cm3":1000
    }).status_code == 200
    assert client.put("/api/data/products/2", json={
        "version":versions[2],"sku":"B","name":"Beta","price":0,"weight_g":2000,"volume_cm3":4000
    }).status_code == 200
    r = client.post("/api/post/purchases", json={
        "company_id":1,"reference":"FULL-"+method,"supplier":"CN","date":"2026-10-01",
        "extra_cost":1000,"cost_breakdown":{"delivery":400,"customs":300,"broker":200,"packaging":100},
        "allocation_method":method,"paid":0,
        "lines":[{"product_id":1,"quantity":1,"unit_cost":1000},{"product_id":2,"quantity":3,"unit_cost":2000}]
    })
    assert r.status_code == 200, r.text
    batches = client.get("/api/data/batches", params={"company_id":1,"limit":100}).json()["items"]
    costs = sorted((b["product_id"], b["total_cost"]) for b in batches)
    shares = (costs[0][1]-1000, costs[1][1]-6000)
    assert shares == expected
    assert sum(x[1] for x in costs) == 8000


def test_full_cost_breakdown_must_reconcile(client):
    r = client.post("/api/post/purchases", json={
        "company_id":1,"reference":"BAD-FULL","supplier":"CN","date":"2026-10-01",
        "extra_cost":1000,"cost_breakdown":{"delivery":999},"allocation_method":"quantity",
        "lines":[{"product_id":1,"quantity":1,"unit_cost":1000}]
    })
    assert r.status_code == 422


def test_defect_reduces_stock_and_recognizes_loss(client):
    buy(client)
    post(client, "adjustments", company_id=1, product_id=1, date="2026-10-02",
         quantity=-1, kind="defect", reason="Заводской брак партии")
    r = report(client)
    assert r["stock_value"] == 9000
    assert r["expenses"] == 1000
    assert r["net_profit"] == -1000


def test_inventory_count_correction_does_not_fake_operating_expense(client):
    buy(client)
    post(client, "adjustments", company_id=1, product_id=1, date="2026-10-02",
         quantity=-1, kind="adjustment", reason="Инвентаризация: расхождение")
    r = report(client)
    assert r["stock_value"] == 9000
    assert r["expenses"] == 0


def test_movement_kind_sign_validation(client):
    buy(client)
    bad = client.post("/api/post/adjustments", json={
        "company_id": 1, "product_id": 1, "date": "2026-10-02",
        "quantity": 1, "kind": "writeoff", "reason": "Неверный знак списания"
    })
    assert bad.status_code == 422
    assert report(client)["stock_value"] == 10000


def test_b2b_summary_and_channel_profitability(client):
    buy(client, qty=10, cost=1000)
    sell(client, ref="B2B-1", qty=2, price=3000, paid=1000, account=3, customer_id=1, commission=100, logistics=50, advertising=25)
    sell(client, ref="B2B-2", qty=1, price=4000, paid=0, account=3, customer_id=1)
    r = report(client)
    b = r["b2b"]
    assert b["revenue"] == 10000
    assert b["gross_profit"] == 7000
    assert b["net_profit"] == 6825
    assert b["orders"] == 2
    assert b["average_check"] == 5000
    assert b["receivables"] == 9000
    row = next(x for x in r["channel_summary"] if x["channel"] == "B2B")
    assert row["profit"] == 6825


def test_product_and_category_contribution_profit(client):
    buy(client, qty=5, cost=1000)
    sell(client, qty=2, price=3000, commission=100, logistics=50, advertising=25)
    r = report(client)
    p = r["products"][0]
    assert p["gross_profit"] == 4000
    assert p["contribution_profit"] == 3825
    cat = r["categories"][0]
    assert cat["gross_profit"] == 4000
    assert cat["contribution_profit"] == 3825


def test_cash_flow_opening_inflow_outflow_and_closing(client):
    post(client, "cash", company_id=1, reference="OPEN", date="2026-09-30", amount=5000, category="Банк")
    post(client, "cash", company_id=1, reference="IN", date="2026-10-02", amount=3000, category="B2B төлем")
    post(client, "cash", company_id=1, reference="OUT", date="2026-10-03", amount=-1200, category="Зарплата")
    r = report(client, start="2026-10-01", end="2026-10-31")
    assert r["cash_opening"] == 5000
    assert r["cash_inflow"] == 3000
    assert r["cash_outflow"] == 1200
    assert r["cash_flow"] == 1800
    assert r["cash_closing"] == 6800
    assert r["cash"] == 6800
    cats = {x["category"]: x for x in r["cash_by_category"]}
    assert cats["B2B төлем"]["inflow"] == 3000
    assert cats["Зарплата"]["outflow"] == 1200


def test_cash_flow_period_excludes_future_money(client):
    post(client, "cash", company_id=1, reference="NOW", date="2026-10-05", amount=1000, category="Банк")
    post(client, "cash", company_id=1, reference="FUTURE", date="2026-11-01", amount=9000, category="Банк")
    r = report(client, start="2026-10-01", end="2026-10-31")
    assert r["cash"] == 1000
    assert r["cash_flow"] == 1000
    assert r["cash_closing"] == 1000
