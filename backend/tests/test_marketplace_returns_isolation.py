from datetime import date
import json

from app.db import SessionLocal
from app import finance
from app.models import Account, MarketplaceRecord, MarketplaceReturn, User
from app.security import passwords
from app.marketplace_returns import discover_from_staging
from .conftest import report


def test_kaspi_late_return_observation_is_idempotent_and_does_not_post_finance(client):
    with SessionLocal() as db:
        account = db.get(Account, 1)
        db.add_all([
            MarketplaceRecord(account_id=1, company_id=1, source="kaspi", external_id="order:OLD-8M",
                payload={"record_type":"order", "order_id":"OLD-8M", "code":"K-88001",
                         "status":"RETURNED", "creation_date":1770670800000, "completion_date":1770757200000}),
            MarketplaceRecord(account_id=1, company_id=1, source="kaspi", external_id="entry:OLD-8M:E1",
                payload={"record_type":"order_entry", "order_id":"OLD-8M", "entry_id":"E1",
                         "order_status":"RETURNED", "quantity":1, "sku":"A", "product_name":"Alpha"}),
        ])
        db.commit()
        before = finance.report(db, db.get(User, 1), date(2026, 2, 1), date(2026, 10, 31), 1)
        first = discover_from_staging(db, account)
        db.commit()
        second = discover_from_staging(db, account)
        db.commit()
        after = finance.report(db, db.get(User, 1), date(2026, 2, 1), date(2026, 10, 31), 1)
        assert first["found"] == second["found"] == 1
        assert db.query(MarketplaceReturn).count() == 1
        observed = db.query(MarketplaceReturn).one()
        assert observed.order_date == date(2026, 2, 10)
        assert observed.financial_return_date is None
        assert observed.amount is None
        assert observed.financial_status == "unconfirmed"
        assert before == after


def test_wb_report_return_is_stored_without_guessing_refund_amount(client):
    with SessionLocal() as db:
        account = Account(id=20, company_id=1, name="WB second store", channel="Wildberries", mode="api")
        db.add(account)
        db.flush()
        db.add(MarketplaceRecord(account_id=20, company_id=1, source="wildberries", external_id="realization:9001",
            payload={"record_type":"realization", "rrdId":9001, "docTypeName":"Возврат",
                     "srid":"wb-return-1", "vendorCode":"A", "quantity":1, "rrdDate":"2026-10-27",
                     "orderDt":"2026-02-10", "forPay":-50000}))
        db.commit()
        result = discover_from_staging(db, account)
        db.commit()
        row = db.query(MarketplaceReturn).filter_by(account_id=20).one()
        assert result["found"] == 1
        assert row.external_order_id == "wb-return-1"
        assert row.order_date == date(2026, 2, 10)
        assert row.financial_return_date == date(2026, 10, 27)
        assert row.amount is None
        assert row.financial_status == "unconfirmed"


def test_marketplace_returns_endpoint_keeps_unknowns_visible_and_unconfirmed(client):
    with SessionLocal() as db:
        db.add(MarketplaceReturn(company_id=1, account_id=1, marketplace="Kaspi", source="kaspi_orders_api",
            external_return_id="kaspi:unknown-date", external_order_id="K-1", product_name="Alpha", sku="A",
            quantity=1, order_date=date(2026, 2, 10), detected_date=date(2026, 10, 27),
            amount=None, financial_status="unconfirmed", return_status="returned"))
        db.commit()
    response = client.get("/api/marketplace-returns", params={"marketplace":"Kaspi", "start":"2026-10-27", "end":"2026-10-27"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 1
    assert data["summary"]["unknown_count"] == 1
    assert data["summary"]["confirmed_amount"] == 0
    assert data["items"][0]["financial_return_date"] is None
    assert data["items"][0]["amount"] is None


def test_returns_data_is_scoped_to_user_company(client):
    with SessionLocal() as db:
        db.add(User(id=4, email="accountant@test.kz", name="Accountant",
                    password_hash=passwords.hash("Test-password-1!"), role="Accountant", company_ids=[1]))
        db.add(MarketplaceReturn(company_id=2, account_id=2, marketplace="Kaspi", source="kaspi_orders_api",
            external_return_id="other-company-return", external_order_id="OTHER-1", detected_date=date(2026, 10, 27)))
        db.commit()
    auth = client.post("/api/auth/login", json={"email":"accountant@test.kz", "password":"Test-password-1!"}).json()
    client.headers["X-CSRF-Token"] = auth["csrf"]
    own_rows = client.get("/api/marketplace-returns")
    forbidden = client.get("/api/marketplace-returns", params={"company_id":2})
    assert own_rows.status_code == 200
    assert all(item["account_id"] != 2 for item in own_rows.json()["items"])
    assert forbidden.status_code == 403


def test_statement_import_is_idempotent_and_stays_out_of_financial_report(client):
    from .conftest import report as report_snapshot

    before = report_snapshot(client)
    csv_data = (
        "Return ID,Order ID,Operation date,Refund,SKU,Quantity,Currency\n"
        "rrd-2026-10-27,K-88001,27.10.2026,50000.00,A,1,KZT\n"
    )
    mapping = {
        "external_return_id":"Return ID", "external_order_id":"Order ID",
        "financial_return_date":"Operation date", "amount":"Refund",
        "sku":"SKU", "quantity":"Quantity", "currency":"Currency",
    }
    for _ in range(2):
        response = client.post("/api/marketplace-returns/financial-statement/import",
            data={"account_id":"1", "mapping":json.dumps(mapping)},
            files={"file":("statement.csv", csv_data, "text/csv")})
        assert response.status_code == 200, response.text
    with SessionLocal() as db:
        rows = db.query(MarketplaceReturn).all()
        assert len(rows) == 1
        assert rows[0].amount == 5_000_000
        assert rows[0].financial_return_date == date(2026, 10, 27)
        assert rows[0].financial_status == "confirmed"
        assert rows[0].accounted_status == "unverified"
    assert report_snapshot(client) == before


def test_unmatched_marketplace_return_never_changes_stock_or_finance(client):
    from app.models import Movement, Return

    with SessionLocal() as db:
        observed = MarketplaceReturn(
            company_id=1, account_id=1, marketplace="Kaspi",
            source="kaspi_orders_api", external_return_id="safe-unmatched-1",
            external_order_id="ORDER-NOT-MAPPED", product_name="Не сопоставлен",
            quantity=1, detected_date=date(2026, 10, 29), raw_data={},
        )
        db.add(observed)
        db.commit()
        observation_id = observed.id
        before_movements = db.query(Movement).count()
        before_returns = db.query(Return).count()

    before_report = report(client)
    response = client.post(f"/api/marketplace-returns/{observation_id}/inventory-match")
    assert response.status_code == 200, response.text
    assert response.json()["matched"] is False
    assert "Остаток не изменён" in response.json()["message"]
    assert report(client) == before_report

    with SessionLocal() as db:
        assert db.query(Movement).count() == before_movements
        assert db.query(Return).count() == before_returns
