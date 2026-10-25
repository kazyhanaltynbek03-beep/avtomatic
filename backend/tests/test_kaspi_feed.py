import xml.etree.ElementTree as ET
from datetime import date

from app.db import SessionLocal
from app.models import Batch, MarketplaceProductMapping, Product


def test_kaspi_feed_exports_only_mapped_items_and_allocated_stock(client):
    saved = client.put("/api/accounts/1/marketplace-settings", json={
        "kaspi_store_id": "STORE-1", "kaspi_merchant_id": "MERCHANT-1",
        "kaspi_full_catalog_confirmed": True, "auto_sync": False,
    })
    assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        product = db.get(Product, 1)
        product.price = 12500
        product.brand = "QOR"
        product.specifications = {"marketplace_stock_allocations": {"1": {"quantity": 4}}}
        db.add(Batch(company_id=1, product_id=1, date=date(2026, 10, 1), quantity=10, remaining=10, total_cost=50000, remaining_cost=50000))
        db.add(MarketplaceProductMapping(company_id=1, account_id=1, channel="Kaspi", external_key="sku:A", product_id=1))
        db.commit()

    created = client.post("/api/accounts/1/kaspi/feed-url")
    assert created.status_code == 200, created.text
    feed = client.get(created.json()["feed_url"])
    assert feed.status_code == 200, feed.text
    root = ET.fromstring(feed.content)
    offer = root.find(".//{*}offer")
    assert offer is not None and offer.attrib["sku"] == "A"
    assert offer.find("{*}price").text == "125"
    availability = offer.find(".//{*}availability")
    assert availability.attrib["storeId"] == "STORE-1"
    assert availability.attrib["stockCount"] == "4"
    assert availability.attrib["available"] == "yes"
    assert client.get(created.json()["feed_url"] + "x").status_code == 404


def test_kaspi_feed_requires_complete_catalog_confirmation(client):
    client.put("/api/accounts/1/marketplace-settings", json={
        "kaspi_store_id": "STORE-1", "kaspi_merchant_id": "MERCHANT-1",
        "kaspi_full_catalog_confirmed": False,
    })
    response = client.post("/api/accounts/1/kaspi/feed-url")
    assert response.status_code == 409
