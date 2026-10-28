from datetime import timedelta
from app.db import SessionLocal
from app.models import Batch, Movement, Product, business_today


def test_product_editor_saves_fields_and_rejects_stale_version(client):
    row = client.get("/api/data/products?limit=10").json()["items"][0]
    payload = {
        "version": row["version"], "sku": row["sku"], "name": "Edited Alpha",
        "category": "Kitchen", "article": "ART-1", "brand": "QOR",
        "supplier": "Supplier", "country": "KZ", "media": ["https://example.test/p.jpg"],
        "currency": "KZT", "fx_rate": 10000, "weight_g": 0, "volume_cm3": 0,
        "min_price": 0, "recommended_price": 0, "price": 12500,
        "min_stock": 7, "active": True, "purchase_cost": 8000,
        "description": "Description", "barcode": "123456789", "custom_fields": {"season": "all"},
        "specifications": {},
    }
    saved = client.put(f"/api/data/products/{row['id']}", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == row["version"] + 1
    assert saved.json()["specifications"]["purchase_cost"] == 8000
    stale = client.put(f"/api/data/products/{row['id']}", json=payload)
    assert stale.status_code == 409
    with SessionLocal() as db:
        product = db.get(Product, row["id"])
        assert product.name == "Edited Alpha"
        assert product.price == 12500
        assert product.specifications["purchase_cost_history"] == [
            {"effective_from": str(business_today()), "unit_cost": 8000}
        ]


def test_sku_cost_change_is_dated_and_preserves_previous_value(client):
    row = client.get("/api/data/products?limit=10").json()["items"][0]
    today = business_today()
    base = {
        "sku": row["sku"], "name": row["name"], "category": row.get("category", ""),
        "article": row.get("article", ""), "brand": row.get("brand", ""),
        "supplier": row.get("supplier", ""), "country": row.get("country", ""),
        "media": row.get("media", []), "currency": "KZT", "fx_rate": 10000,
        "weight_g": 0, "volume_cm3": 0, "min_price": 0, "recommended_price": 0,
        "price": 10000, "min_stock": 5, "active": True, "description": "",
        "barcode": "", "custom_fields": {}, "specifications": {},
    }
    first = client.put(f"/api/data/products/{row['id']}", json={**base, "version": row["version"], "purchase_cost": 8000})
    assert first.status_code == 200, first.text
    first_version = first.json()["version"]
    changed = client.put(f"/api/data/products/{row['id']}", json={**base, "version": first_version, "purchase_cost": 9000})
    assert changed.status_code == 200, changed.text
    assert changed.json()["specifications"]["purchase_cost_history"] == [
        {"effective_from": str(today), "unit_cost": 8000},
        {"effective_from": str(today + timedelta(days=1)), "unit_cost": 9000},
    ]


def test_inventory_count_is_auditable_and_idempotent(client):
    opening = client.post("/api/post/opening", json={
        "company_id": 1, "product_id": 1, "reference": "EDITOR-OPEN-1",
        "date": "2026-10-20", "quantity": 10, "unit_cost": 5000,
        "evidence": "Count test opening stock",
    })
    assert opening.status_code == 200, opening.text
    payload = {
        "company_id": 1, "product_id": 1, "counted_quantity": 7,
        "reason": "Фактический пересчёт склада", "idempotency_key": "manual-count-test-0001",
    }
    first = client.post("/api/inventory/count", json=payload)
    replay = client.post("/api/inventory/count", json=payload)
    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert first.json()["delta"] == -3
    assert replay.json()["replayed"] is True
    with SessionLocal() as db:
        batches = db.query(Batch).filter_by(company_id=1, product_id=1).all()
        assert sum(b.remaining for b in batches) == 7
        moves = db.query(Movement).filter_by(reference="Фактический пересчёт склада").all()
        assert len(moves) == 1


def test_product_inventory_listing_returns_period_sales_and_return_columns(client):
    response = client.get("/api/data/products?limit=10&start=2026-10-01&end=2026-10-24")
    assert response.status_code == 200, response.text
    row = next(x for x in response.json()["items"] if x["id"] == 1)
    assert set(row["inventory"]) == {
        "total", "physical", "available", "reserved", "allocated", "marketplace", "in_transit",
        "defective", "sold", "returned", "sales_by_marketplace", "mapping_coverage",
        "reconciliation_status", "snapshot_review_required", "allocation_overdrawn", "last_sync", "low_stock",
    }
    assert row["inventory"]["available"] == row["inventory"]["physical"]
    assert row["inventory"]["reserved"] == 0
    assert row["inventory"]["total"] == sum(
        row["inventory"][key] for key in ("physical", "in_transit", "defective")
    )


def test_marketplace_stock_snapshot_is_separate_and_company_scoped(client):
    with SessionLocal() as db:
        product = db.get(Product, 1)
        product.specifications = {"marketplace_stock": {
            "Kaspi:1": {"quantity": 12}, "Kaspi:2": {"quantity": 900},
        }}
        db.commit()
    response = client.get("/api/data/products", params={"company_id":1, "limit":10})
    assert response.status_code == 200, response.text
    row = next(x for x in response.json()["items"] if x["id"] == 1)
    assert row["inventory"]["marketplace"] == 12
    assert row["inventory"]["total"] == row["inventory"]["physical"]
    assert row["inventory"]["snapshot_review_required"] is True
    assert row["inventory"]["reconciliation_status"] == "partial"


def test_shared_sku_stock_decreases_across_kaspi_and_wildberries_sales(client):
    from app.models import Account
    from .conftest import buy, sell

    with SessionLocal() as db:
        db.add(Account(id=4, company_id=1, name="WB test shop", channel="Wildberries", mode="manual"))
        db.commit()
    buy(client, ref="SHARED-100", qty=100, cost=5000, day="2026-10-26")
    sell(client, ref="KASPI-20", qty=20, price=10000, account=1, day="2026-10-27")
    sell(client, ref="WB-40", qty=40, price=10000, account=4, day="2026-10-27")

    response = client.get("/api/data/products", params={
        "limit":10, "company_id":1, "start":"2026-10-26", "end":"2026-10-27",
    })
    assert response.status_code == 200, response.text
    product = next(row for row in response.json()["items"] if row["id"] == 1)
    assert product["inventory"]["sold"] == 60
    assert product["inventory"]["physical"] == 40
    assert product["inventory"]["total"] == 40
    assert {(x["channel"], x["sold"], x["returned"]) for x in product["inventory"]["sales_by_marketplace"]} == {
        ("Kaspi", 20, 0), ("Wildberries", 40, 0),
    }
    assert product["inventory"]["mapping_coverage"]["status"] == "unmapped"
    assert product["inventory"]["reconciliation_status"] == "partial"


def test_inventory_count_requires_confirmed_cost_for_positive_adjustment(client):
    payload = {
        "company_id": 1, "product_id": 1, "counted_quantity": 2,
        "reason": "Первичная инвентаризация", "idempotency_key": "initial-count-cost-0001",
    }
    rejected = client.post("/api/inventory/count", json=payload)
    assert rejected.status_code == 422
    payload["unit_cost"] = 5000
    accepted = client.post("/api/inventory/count", json=payload)
    assert accepted.status_code == 200, accepted.text
    with SessionLocal() as db:
        batch = db.query(Batch).filter_by(company_id=1, product_id=1).one()
        assert batch.remaining == 2
        assert batch.remaining_cost == 10000


def test_marketplace_ids_map_different_platform_ids_to_one_qor_product(client):
    from app.models import Account, MarketplaceProductMapping

    with SessionLocal() as db:
        db.add(Account(id=4, company_id=1, name="WB test shop", channel="Wildberries", mode="manual"))
        db.commit()
    kaspi = client.post("/api/products/1/marketplace-mappings", json={
        "account_id": 1, "id_type": "product", "external_id": "kaspi-item-771",
    })
    wb = client.post("/api/products/1/marketplace-mappings", json={
        "account_id": 4, "id_type": "product", "external_id": "wb-nmid-992",
    })
    assert kaspi.status_code == 200, kaspi.text
    assert wb.status_code == 200, wb.text
    assert kaspi.json()["external_key"] == "product:kaspi-item-771"
    assert wb.json()["external_key"] == "product:wb-nmid-992"
    assert client.post("/api/products/1/marketplace-mappings", json={
        "account_id": 4, "id_type": "product", "external_id": "wb-nmid-992",
    }).status_code == 200
    conflict = client.post("/api/products/2/marketplace-mappings", json={
        "account_id": 4, "id_type": "product", "external_id": "wb-nmid-992",
    })
    assert conflict.status_code == 409
    with SessionLocal() as db:
        mappings = db.query(MarketplaceProductMapping).filter_by(product_id=1).all()
        assert {(m.account_id, m.external_key) for m in mappings} == {
            (1, "product:kaspi-item-771"), (4, "product:wb-nmid-992"),
        }


def test_marketplace_id_mapping_respects_account_company_scope(client):
    auth = client.post("/api/auth/login", json={
        "email":"warehouse@test.kz", "password":"Test-password-1!",
    })
    assert auth.status_code == 200, auth.text
    client.headers["X-CSRF-Token"] = auth.json()["csrf"]
    response = client.post("/api/products/1/marketplace-mappings", json={
        "account_id":2, "id_type":"product", "external_id":"other-company-item",
    })
    assert response.status_code == 403


def test_sales_breakdown_keeps_two_stores_of_same_marketplace_separate(client):
    from app.models import Account
    from .conftest import buy, sell

    with SessionLocal() as db:
        db.add_all([
            Account(id=4, company_id=1, name="WB shop", channel="Wildberries", mode="manual"),
            Account(id=5, company_id=1, name="Kaspi second shop", channel="Kaspi", mode="manual"),
        ])
        db.commit()
    buy(client, ref="MULTI-SHOP-OPEN", qty=100, cost=5000, day="2026-10-26")
    sell(client, ref="MULTI-SHOP-K1", qty=3, price=10000, account=1, day="2026-10-27")
    sell(client, ref="MULTI-SHOP-WB", qty=4, price=10000, account=4, day="2026-10-27")
    sell(client, ref="MULTI-SHOP-K2", qty=2, price=10000, account=5, day="2026-10-27")
    response = client.get("/api/data/products", params={
        "company_id":1, "start":"2026-10-26", "end":"2026-10-27",
    })
    assert response.status_code == 200, response.text
    product = next(row for row in response.json()["items"] if row["id"] == 1)
    breakdown = {x["account_name"]: (x["channel"], x["sold"]) for x in product["inventory"]["sales_by_marketplace"]}
    assert breakdown == {"Kaspi": ("Kaspi", 3), "WB shop": ("Wildberries", 4), "Kaspi second shop": ("Kaspi", 2)}


def test_mapped_kaspi_and_wb_api_sales_replay_once_and_refund_does_not_restock(client):
    from sqlalchemy import select, func
    from app import marketplace_pipeline as pipeline
    from app.models import Account, MarketplaceRecord, Sale, User
    from .conftest import buy

    with SessionLocal() as db:
        db.add(Account(id=4, company_id=1, name="WB main", channel="Wildberries", mode="manual"))
        db.commit()
    buy(client, ref="MAPPED-OPEN-100", qty=100, cost=5000, day="2026-10-26")
    kaspi_link = client.post("/api/products/1/marketplace-mappings", json={
        "account_id":1, "id_type":"product", "external_id":"K-771",
    })
    wb_link = client.post("/api/products/1/marketplace-mappings", json={
        "account_id":4, "id_type":"product", "external_id":"992",
    })
    assert kaspi_link.status_code == wb_link.status_code == 200
    with SessionLocal() as db:
        owner = db.get(User, 1)
        kaspi = db.get(Account, 1)
        wb = db.get(Account, 4)
        db.add_all([
            MarketplaceRecord(account_id=1, company_id=1, source="kaspi", external_id="K-ORDER-1",
                payload={"record_type":"order_entry", "order_status":"COMPLETED", "external_product_id":"K-771",
                         "order_id":"K-ORDER-1", "quantity":20, "total_price":"200000", "completed_date":"2026-10-27"}),
            MarketplaceRecord(account_id=4, company_id=1, source="wildberries", external_id="WB-REAL-1",
                payload={"record_type":"realization", "sellerOperName":"Продажа", "nmId":992,
                         "srid":"WB-SRID-1", "quantity":40, "currency":"KZT", "retailAmount":"400000",
                         "retailPriceWithDisc":"10000", "saleDt":"2026-10-27", "rrDate":"2026-10-27"}),
        ])
        db.flush()
        for _ in range(2):
            pipeline.project_account(db, owner, kaspi)
            pipeline.project_account(db, owner, wb)
            db.commit()
        assert db.scalar(select(func.count()).select_from(Sale)) == 2
        assert db.scalar(select(func.sum(Batch.remaining)).where(Batch.company_id == 1, Batch.product_id == 1)) == 40
        kaspi_sale = db.scalar(select(Sale).where(Sale.account_id == 1))
        kaspi_sale_id = kaspi_sale.id

    refund = client.post("/api/post/returns", json={
        "sale_id":kaspi_sale_id, "reference":"K-RETURN-NOT-RESTOCKED",
        "date":"2026-10-27", "quantity":2, "refund":0,
    })
    assert refund.status_code == 200, refund.text
    with SessionLocal() as db:
        assert db.scalar(select(func.sum(Batch.remaining)).where(Batch.company_id == 1, Batch.product_id == 1)) == 40
    inventory = client.get("/api/data/products", params={
        "company_id":1, "start":"2026-10-26", "end":"2026-10-27",
    })
    assert inventory.status_code == 200, inventory.text
    product = next(row for row in inventory.json()["items"] if row["id"] == 1)
    assert product["inventory"]["total"] == 40
    assert product["inventory"]["sold"] == 60
    assert product["inventory"]["returned"] == 2
    assert product["inventory"]["mapping_coverage"] == {
        "linked":2, "active_accounts":2, "status":"complete",
    }
    assert {(x["channel"], x["sold"]) for x in product["inventory"]["sales_by_marketplace"]} == {
        ("Kaspi",20), ("Wildberries",40),
    }
    assert product["inventory"]["reconciliation_status"] == "confirmed"
