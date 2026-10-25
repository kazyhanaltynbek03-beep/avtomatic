"""Golden financial-pipeline audit.

Every source is normalised into the same immutable finance functions.  Values are
integer tiyn; the source rows deliberately use decimal KZT to exercise parsing.
"""
from datetime import date
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException
from openpyxl import Workbook

from app import finance as f, importing, main
from app import schemas as s
from app.ai import _agent_tool_data
from app.db import Base, SessionLocal, engine
from app.models import Account, Company, Customer, Product, Return, Sale, User


START, END = date(2026, 10, 1), date(2026, 10, 31)
EXPECTED = {
    "revenue": 1_325_000,
    "cogs": 500_000,
    "gross_profit": 825_000,
    "commission": 50_000,
    "logistics": 20_000,
    "advertising": 30_000,
    "expenses": 100_000,
    "net_profit": 625_000,
    "margin": 47.17,
    "roi": 89.29,
    "cash": 925_000,
    "cash_flow": 925_000,
    "stock_value": 600_000,
    "returns": 275_000,
    "return_units": 1,
    "b2b_debt": 400_000,
}


@pytest.fixture()
def ledger():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    db.add(Company(id=1, name="Golden", bin="000000000001"))
    db.commit()
    db.add_all([
        User(id=1, email="owner@golden.kz", name="Owner", password_hash="x", role="Owner"),
        Product(id=1, sku="GOLD", name="Golden SKU", price=300_000, min_stock=0),
        Account(id=1, company_id=1, name="Kaspi", channel="Kaspi"),
        Account(id=2, company_id=1, name="Wildberries", channel="Wildberries"),
        Account(id=3, company_id=1, name="Ozon", channel="Ozon"),
        Account(id=4, company_id=1, name="Offline", channel="Offline"),
        Account(id=5, company_id=1, name="B2B", channel="B2B"),
        Customer(id=1, company_id=1, name="Golden Buyer"),
    ])
    db.commit()
    user = db.get(User, 1)
    # Source-neutral opening stock: marketplace APIs never invent supplier cost.
    f.purchase(db, user, s.PurchaseIn(company_id=1, reference="OPEN-12", supplier="Supplier",
        date=START, paid=0, lines=[s.PurchaseLine(product_id=1, quantity=12, unit_cost=100_000)]))
    db.commit()
    yield db, user
    db.close()


def _common_b2b_and_writeoff(db, user):
    f.adjust(db, user, s.AdjustIn(company_id=1, product_id=1, date=date(2026, 10, 4),
        quantity=-1, kind="writeoff", reason="Golden inventory write-off"))
    f.sale(db, user, s.SaleIn(company_id=1, account_id=5, customer_id=1, reference="B2B-1",
        date=date(2026, 10, 5), due_date=date(2026, 10, 20), product_id=1,
        quantity=2, unit_price=250_000, paid=100_000))


def _mark_return_sellable(db, user, ret):
    # Golden scenarios model an official, physically received and inspected return.
    ret.inventory_status = "restocked"
    original_today = f.business_today
    f.business_today = lambda: ret.date
    try:
        f.restock_return_inventory(db, user, ret)
    finally:
        f.business_today = original_today


def _manual(db, user):
    sale = f.sale(db, user, s.SaleIn(company_id=1, account_id=4, reference="SRC-SALE", date=date(2026, 10, 2),
        product_id=1, quantity=4, unit_price=300_000, discount=100_000,
        commission=50_000, logistics=20_000, advertising=30_000, paid=0))
    f.payment(db, user, s.CashIn(company_id=1, sale_id=sale.id, reference="SRC-PAY", date=date(2026, 10, 2), amount=1_100_000, category="Marketplace payout"))
    ret = f.return_sale(db, user, s.ReturnIn(sale_id=sale.id, reference="SRC-RETURN", date=date(2026, 10, 3), quantity=1, refund=275_000))
    _mark_return_sellable(db, user, ret)
    _common_b2b_and_writeoff(db, user)


def _import(db, user, kind, rows, mapping):
    run, _ = importing.preview(db, user, kind, rows, mapping)
    assert not run.errors, run.errors
    db.commit()
    importing.confirm(db, user, run)
    if kind in {"returns", "marketplace_reports"}:
        for ret in db.query(Return).filter(Return.inventory_status == "requested").all():
            _mark_return_sellable(db, user, ret)
    db.commit()


def _excel(db, user):
    wb = Workbook()
    ws = wb.active
    headers = ["ref", "day", "company", "account", "sku", "qty", "price", "discount", "commission", "logistics", "advertising", "paid"]
    ws.append(headers)
    ws.append(["SRC-SALE", "2026-10-02", "1", "4", "GOLD", "4", "3000", "1000", "500", "200", "300", "0"])
    raw = BytesIO(); wb.save(raw)
    parsed_headers, parsed_rows = importing.parse_file(raw.getvalue(), "golden.xlsx")
    assert parsed_headers == headers
    _import(db, user, "sales", parsed_rows,
        {"reference":"ref", "date":"day", "company_id":"company", "account_id":"account", "sku":"sku", "quantity":"qty", "unit_price":"price", "discount":"discount", "commission":"commission", "logistics":"logistics", "advertising":"advertising", "paid":"paid"})
    sale = db.scalar(__import__("sqlalchemy").select(Sale).where(Sale.reference == "SRC-SALE"))
    _import(db, user, "bank", [{"ref":"SRC-PAY", "day":"2026-10-02", "company":"1", "sale":"%s" % sale.id, "amount":"11000", "category":"Marketplace payout"}],
        {"reference":"ref", "date":"day", "company_id":"company", "sale_id":"sale", "amount":"amount", "category":"category"})
    _import(db, user, "returns", [{"sale":"%s" % sale.id, "ref":"SRC-RETURN", "day":"2026-10-03", "qty":"1", "refund":"2750"}],
        {"sale_id":"sale", "reference":"ref", "date":"day", "quantity":"qty", "refund":"refund"})
    _common_b2b_and_writeoff(db, user)


def _csv(db, user):
    """A real UTF-8 CSV goes through the same parser and normalizer as XLSX."""
    raw = (Path(__file__).parent / "fixtures" / "golden_sales.csv").read_bytes()
    headers, rows = importing.parse_file(raw, "golden.csv")
    assert headers[0] == "paid"
    _import(db, user, "sales", rows,
        {"reference":"ref", "date":"day", "company_id":"company", "account_id":"account", "sku":"sku", "quantity":"qty", "unit_price":"price", "discount":"discount", "commission":"commission", "logistics":"logistics", "advertising":"advertising", "paid":"paid"})
    sale = db.scalar(__import__("sqlalchemy").select(Sale).where(Sale.reference == "SRC-SALE"))
    _import(db, user, "bank", [{"ref":"SRC-PAY", "day":"2026-10-02", "company":"1", "sale":str(sale.id), "amount":"11000", "category":"Marketplace payout"}],
        {"reference":"ref", "date":"day", "company_id":"company", "sale_id":"sale", "amount":"amount", "category":"category"})
    _import(db, user, "returns", [{"sale":str(sale.id), "ref":"SRC-RETURN", "day":"2026-10-03", "qty":"1", "refund":"2750"}],
        {"sale_id":"sale", "reference":"ref", "date":"day", "quantity":"qty", "refund":"refund"})
    _common_b2b_and_writeoff(db, user)


def _marketplace(db, user, account_id):
    # An order must not alter P&L, stock or cash.
    rows = [
        {"event":"order", "external":"ORD-1", "day":"2026-10-02", "company":"1", "account":str(account_id)},
        {"event":"sale", "external":"SALE-1", "day":"2026-10-02", "company":"1", "account":str(account_id), "sku":"GOLD", "qty":"4", "price":"3000", "discount":"1000"},
    ]
    mapping = {"event_type":"event", "external_id":"external", "date":"day", "company_id":"company", "account_id":"account", "sku":"sku", "quantity":"qty", "unit_price":"price", "discount":"discount"}
    _import(db, user, "marketplace_reports", rows, mapping)
    channel = db.get(Account, account_id).channel
    sale_reference = f"{channel}:{account_id}:SALE-1"
    for event, external, amount in [("payment", "PAY-1", "11000"), ("commission", "COM-1", "500"), ("logistics", "LOG-1", "200"), ("advertising", "ADS-1", "300")]:
        _import(db, user, "marketplace_reports", [{"event":event, "external":external, "day":"2026-10-02", "company":"1", "account":str(account_id), "sale_ref":sale_reference, "amount":amount}],
            {"event_type":"event", "external_id":"external", "date":"day", "company_id":"company", "account_id":"account", "sale_reference":"sale_ref", "amount":"amount"})
    _import(db, user, "marketplace_reports", [{"event":"return", "external":"RET-1", "day":"2026-10-03", "company":"1", "account":str(account_id), "sku":"GOLD", "sale_ref":sale_reference, "qty":"1", "refund":"2750"}],
        {"event_type":"event", "external_id":"external", "date":"day", "company_id":"company", "account_id":"account", "sku":"sku", "sale_reference":"sale_ref", "quantity":"qty", "refund":"refund"})
    _common_b2b_and_writeoff(db, user)


@pytest.mark.parametrize("source,account_id", [("manual", 4), ("excel", 4), ("csv", 4), ("kaspi", 1), ("wildberries", 2), ("ozon", 3)])
def test_golden_financial_result_is_identical_after_normalization(ledger, source, account_id):
    db, user = ledger
    {"manual": _manual, "excel": _excel, "csv": _csv}.get(source, lambda d, u: _marketplace(d, u, account_id))(db, user)
    db.commit()
    actual = f.report(db, user, START, END, 1)
    assert {key: actual[key] for key in EXPECTED} == EXPECTED


@pytest.mark.parametrize("account_id", [1, 2, 3])
def test_marketplace_order_and_duplicate_sync_do_not_change_finance(ledger, account_id):
    db, user = ledger
    row = {"event":"order", "external":"ORD-ONLY", "day":"2026-10-02", "company":"1", "account":str(account_id)}
    mapping = {"event_type":"event", "external_id":"external", "date":"day", "company_id":"company", "account_id":"account"}
    _import(db, user, "marketplace_reports", [row], mapping)
    before = f.report(db, user, START, END, 1)
    with pytest.raises(HTTPException) as error:
        importing.preview(db, user, "marketplace_reports", [row], mapping)
    assert error.value.status_code == 409
    after = f.report(db, user, START, END, 1)
    assert {k: after[k] for k in EXPECTED} == {k: before[k] for k in EXPECTED}


def test_dashboard_sales_finance_inventory_and_ai_share_backend_truth(ledger, monkeypatch):
    db, user = ledger
    _manual(db, user)
    db.commit()
    truth = f.report(db, user, START, END, 1)
    assert main.get_report(START, END, 1, None, user, db) == truth
    dashboard = main.dashboard_summary(START, END, 1, user, db)
    for key in ("revenue", "gross_profit", "net_profit", "margin", "stock_value", "cash", "b2b_debt"):
        assert dashboard["selected"][key] == truth[key]
    accounting = main.accounting_summary(1, START, END, user, db)
    assert accounting["receivable"] == truth["b2b_debt"]
    rows = main.listing("sales", search="", company_id=1, account_id=None, channel=None, offset=0, limit=50, u=user, db=db)
    assert sum(x["revenue"] for x in rows["items"]) == 1_600_000
    monkeypatch.setattr(main, "business_today", lambda: END)
    stock_rows = main.stock(1, user, db)
    assert sum(x["value"] for x in stock_rows) == truth["stock_value"]
    ai_finance = _agent_tool_data(truth, "get_finance_summary")
    for key in ("revenue", "cogs", "gross_profit", "net_profit", "commission", "logistics", "advertising", "cash_flow", "b2b_debt"):
        assert ai_finance[key] == truth[key]
