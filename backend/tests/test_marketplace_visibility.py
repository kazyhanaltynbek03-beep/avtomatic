from app.models import MarketplaceRecord, Account
from app.db import SessionLocal


def test_marketplace_staging_visible_without_fake_sale(client):
    with SessionLocal() as db:
        acc = db.query(Account).filter(Account.channel == "Kaspi").first()
        db.add(MarketplaceRecord(account_id=acc.id, company_id=acc.company_id, source="kaspi", external_id="ORDER-ONLY-1", payload={"code":"K-1","status":"APPROVED_BY_BANK","total_price":10000}))
        db.commit()
    r = client.get("/api/marketplace-records?channel=Kaspi")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert any(x["external_id"] == "ORDER-ONLY-1" for x in body["items"])
    sales = client.get("/api/data/sales?channel=Kaspi").json()
    assert all(x.get("reference") != "ORDER-ONLY-1" for x in sales["items"])
