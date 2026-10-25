from app.db import SessionLocal
from app.models import Batch, Movement, Product


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
        "total", "physical", "available", "reserved", "marketplace", "in_transit",
        "defective", "sold", "returned", "last_sync", "low_stock",
    }
    assert row["inventory"]["available"] == row["inventory"]["physical"]
    assert row["inventory"]["reserved"] == 0
    assert row["inventory"]["total"] == sum(
        row["inventory"][key] for key in ("physical", "marketplace", "in_transit", "defective")
    )


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
