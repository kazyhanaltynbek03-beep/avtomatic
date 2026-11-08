from app.db import SessionLocal
from app.models import MarketplaceRecord


def _add_order(db, order_id, date, status, entries):
    db.add(MarketplaceRecord(
        account_id=1, company_id=1, source="kaspi", external_id=f"order:{order_id}",
        payload={"record_type":"order","order_id":str(order_id),"code":f"K-{order_id}",
                 "creation_date":date,"status":status,"total_price":12500,
                 "state":"KASPI_DELIVERY","customer":{"name":"Private Buyer","phone":"77000000000"}},
    ))
    for index, entry in enumerate(entries):
        db.add(MarketplaceRecord(
            account_id=1, company_id=1, source="kaspi", external_id=f"entry:{order_id}:{index}",
            payload={"record_type":"order_entry","order_id":str(order_id),
                     "product_name":entry["name"],"sku":entry["sku"],
                     "quantity":entry["quantity"],"total_price":entry["amount"]},
        ))


def test_marketplace_orders_can_search_and_filter_by_period(client):
    with SessionLocal() as db:
        _add_order(db, "101", "2026-11-06T10:00:00+05:00", "COMPLETED", [
            {"name":"Товар Alpha","sku":"A-1","quantity":1,"amount":7500},
            {"name":"Товар Beta","sku":"B-2","quantity":1,"amount":5000},
        ])
        _add_order(db, "202", "2026-11-04T10:00:00+05:00", "APPROVED_BY_BANK", [
            {"name":"Старый товар","sku":"C-3","quantity":1,"amount":2500},
        ])
        db.commit()

    response = client.get("/api/marketplace-orders", params={
        "channel":"Kaspi","search":"101","start":"2026-11-06","end":"2026-11-06",
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2
    assert data["order_count"] == 1
    assert data["summary"]["delivered"] == 1
    assert {item["order_id"] for item in data["items"]} == {"101"}


def test_marketplace_order_detail_uses_saved_fields_without_buyer_pii(client):
    with SessionLocal() as db:
        _add_order(db, "303", "2026-11-06T10:00:00+05:00", "COMPLETED", [
            {"name":"Складской товар","sku":"SKU-3","quantity":2,"amount":12500},
        ])
        db.commit()

    response = client.get("/api/marketplace-order-detail", params={
        "channel":"Kaspi","account_id":1,"order_id":"303",
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["order_id"] == "303"
    assert data["status"] == "Выдан покупателю"
    assert data["items"][0]["sku"] == "SKU-3"
    assert data["amount"] == 12500
    assert data["status_history"] == []
    assert "Private Buyer" not in response.text
    assert "77000000000" not in response.text
    assert "payload" not in data
