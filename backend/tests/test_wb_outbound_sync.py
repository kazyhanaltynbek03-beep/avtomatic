from datetime import date

from app.db import SessionLocal
from app.models import Account, Batch, MarketplaceProductMapping, Product


def test_wb_sync_blocks_allocations_above_physical_stock(client):
    with SessionLocal() as db:
        db.add(Account(id=4, company_id=1, name="WB FBS", channel="Wildberries", mode="api",
                       integration_settings={"wb_warehouse_id": "555"}))
        product = db.get(Product, 1)
        product.specifications = {"marketplace_stock_allocations": {"4": {"sizes": {"987654": 6}}}}
        db.add(Batch(company_id=1, product_id=1, date=date(2026, 10, 1), quantity=5, remaining=5, total_cost=25000, remaining_cost=25000))
        db.add_all([
            MarketplaceProductMapping(company_id=1, account_id=4, channel="Wildberries", external_key="product:123456", product_id=1),
            MarketplaceProductMapping(company_id=1, account_id=4, channel="Wildberries", external_key="size:987654", product_id=1),
        ])
        db.commit()

    response = client.post("/api/accounts/4/wb/products/1/sync", json={"confirm": True})
    assert response.status_code == 409
    assert "распределено" in response.text.lower()


def test_account_dump_does_not_expose_outbound_secrets(client):
    with SessionLocal() as db:
        account = db.get(Account, 1)
        account.integration_settings = {"kaspi_feed_token_hash": "private-hash", "kaspi_store_id": "STORE"}
        db.commit()
    response = client.get("/api/data/accounts?limit=20")
    assert response.status_code == 200
    account = next(row for row in response.json()["items"] if row["id"] == 1)
    assert "integration_settings" not in account
