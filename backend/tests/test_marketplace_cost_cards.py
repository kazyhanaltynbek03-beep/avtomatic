from datetime import date

from app.db import SessionLocal
from app.models import MarketplaceProductMapping, Sale


def test_marketplace_card_cost_recalculates_kaspi_reports(client):
    with SessionLocal() as db:
        db.add(MarketplaceProductMapping(
            company_id=1, account_id=1, channel="Kaspi",
            external_key="sku:A", product_id=1,
        ))
        db.add(Sale(
            company_id=1, account_id=1, product_id=1,
            reference="KASPI-COST-TEST", date=date(2026, 10, 5),
            quantity=2, revenue=50000, cogs=0, cogs_pending=True,
            commission=0, logistics=0, advertising=0,
        ))
        db.commit()

    saved = client.put("/api/marketplace-products/cost", json={
        "account_id": 1, "product_id": 1, "unit_cost": "100.00",
        "effective_from": "2026-10-01",
    })
    assert saved.status_code == 200, saved.text

    report = client.get("/api/report", params={
        "start": "2026-10-01", "end": "2026-10-31",
    }).json()
    assert report["cogs"] == 20000
    assert report["gross_profit"] == 30000
    assert report["net_profit"] == 30000
    assert report["profit_complete"] is True

    summary = client.get("/api/marketplace-summary", params={
        "channel": "Kaspi", "start": "2026-10-01", "end": "2026-10-31",
    }).json()
    assert summary["cogs"] == 20000
    assert summary["pending_sales"] == 0
    assert summary["net_profit"] == 30000

    products = client.get("/api/marketplace-products", params={
        "channel": "Kaspi", "account_id": 1,
        "start": "2026-10-01", "end": "2026-10-31",
    }).json()
    card = next(item for item in products["items"] if item["id"] == 1)
    assert card["unit_cost"] == 10000
    assert card["cogs"] == 20000
    assert card["profit"] == 30000
