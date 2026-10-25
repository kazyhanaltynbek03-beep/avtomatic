"""Accounting invariants that must hold before a QOR release.

These tests intentionally exercise boundaries where ERP systems commonly drift:
period cut-offs, receivables, landed cost, channel attribution, refunds and cash/accrual separation.
All monetary values are integer tiyn.
"""
from .conftest import buy, sell, post, report, restock_return


def account_report(client, account_id, start="2026-10-01", end="2026-10-31"):
    r = client.get("/api/report", params={"start": start, "end": end, "account_id": account_id})
    assert r.status_code == 200, r.text
    return r.json()


def test_unpaid_purchase_changes_stock_not_cash_or_profit(client):
    buy(client, qty=5, cost=1200, paid=0)
    r = report(client)
    assert r["stock_value"] == 6000
    assert r["cash"] == 0
    assert r["net_profit"] == 0


def test_purchase_partial_payment_only_changes_cash(client):
    buy(client, qty=5, cost=1200, paid=2000)
    r = report(client)
    assert r["stock_value"] == 6000
    assert r["cash"] == -2000
    assert r["net_profit"] == 0


def test_paid_expense_hits_accrual_profit_and_cash_once(client):
    post(client, "expenses", company_id=1, reference="E-P", date="2026-10-03",
         category="Аренда", amount=2500, paid=True)
    r = report(client)
    assert r["expenses"] == 2500
    assert r["net_profit"] == -2500
    assert r["cash"] == -2500
    assert r["cash_flow"] == -2500


def test_advertising_expense_not_double_counted_as_operating(client):
    post(client, "expenses", company_id=1, account_id=1, reference="ADS", date="2026-10-03",
         category="Реклама", amount=1700, paid=False)
    r = report(client)
    assert r["advertising"] == 1700
    assert r["expenses"] == 0
    assert r["net_profit"] == -1700


def test_account_report_excludes_other_channel_sales(client):
    buy(client, qty=10, cost=1000)
    sell(client, ref="K", qty=2, price=3000, account=1)
    sell(client, ref="B", qty=1, price=5000, account=3, customer_id=1)
    kaspi = account_report(client, 1)
    b2b = account_report(client, 3)
    assert kaspi["revenue"] == 6000
    assert kaspi["cogs"] == 2000
    assert b2b["revenue"] == 5000
    assert b2b["cogs"] == 1000


def test_account_filter_does_not_fake_physical_stock_partition(client):
    buy(client, qty=4, cost=1000)
    sell(client, qty=1, price=3000, account=1)
    r = account_report(client, 1)
    assert r["stock_value"] == 3000
    assert "склад" in r["scope_note"].lower()


def test_return_without_refund_creates_refund_payable_if_sale_was_paid(client):
    buy(client, qty=3, cost=1000)
    s = sell(client, qty=3, price=3000, paid=9000)
    post(client, "returns", sale_id=s["id"], reference="R-NO-CASH", date="2026-10-03", quantity=1, refund=0)
    r = report(client)
    assert r["revenue"] == 6000
    assert r["cash"] == 9000
    assert r["refunds_payable"] == 3000


def test_return_with_immediate_refund_clears_refund_payable(client):
    buy(client, qty=3, cost=1000)
    s = sell(client, qty=3, price=3000, paid=9000)
    post(client, "returns", sale_id=s["id"], reference="R-CASH", date="2026-10-03", quantity=1, refund=3000)
    r = report(client)
    assert r["cash"] == 6000
    assert r["refunds_payable"] == 0


def test_cash_flow_period_is_not_lifetime_cash(client):
    buy(client, qty=2, cost=1000, paid=2000, day="2026-09-30")
    sell(client, qty=1, price=3000, paid=3000, day="2026-10-02")
    r = report(client, start="2026-10-01", end="2026-10-31")
    assert r["cash"] == 1000
    assert r["cash_flow"] == 3000


def test_zero_cost_inventory_can_be_sold_without_division_errors(client):
    buy(client, qty=2, cost=0)
    sell(client, qty=2, price=1500)
    r = report(client)
    assert r["cogs"] == 0
    assert r["gross_profit"] == 3000
    assert r["stock_value"] == 0


def test_full_return_reverses_revenue_cogs_units_but_not_sale_costs(client):
    buy(client, qty=2, cost=1000)
    s = sell(client, qty=2, price=3000, commission=300, logistics=100, advertising=50)
    ret = post(client, "returns", sale_id=s["id"], reference="R-FULL", date="2026-10-03", quantity=2)
    # While return inventory is pending inspection, original COGS stays recognized.
    pending = report(client)
    assert pending["revenue"] == 0
    assert pending["cogs"] == 2000
    assert pending["net_profit"] is None
    restock_return(client, ret["id"])
    r = report(client)
    assert r["revenue"] == 0
    assert r["cogs"] == 0
    assert r["units"] == 0
    # Marketplace/fulfilment costs remain incurred unless separately reversed by a source document.
    assert r["net_profit"] == -450


def test_receivable_disappears_after_full_b2b_payment(client):
    buy(client, qty=2, cost=1000)
    s = sell(client, qty=2, price=3000, paid=1000, account=3, customer_id=1, due_date="2026-10-05")
    post(client, "cash", company_id=1, sale_id=s["id"], reference="B2B-FINAL", date="2026-10-04",
         amount=5000, category="Продажа")
    r = report(client)
    assert r["b2b_debt"] == 0
    assert r["receivables"] == []
    assert r["cash"] == 6000
