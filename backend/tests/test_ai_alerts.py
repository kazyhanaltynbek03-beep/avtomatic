from app.db import SessionLocal
from app.models import Account, MarketplaceRecord


def test_erp_alerts_report_unmapped_marketplace_records_and_failed_sync(client):
    with SessionLocal() as db:
        account=db.get(Account,1)
        account.sync_status="partial"
        account.sync_error="Тест: API временно недоступен"
        db.add(MarketplaceRecord(account_id=1,company_id=1,source="kaspi",external_id="unmapped-1",
            payload={"product_name":"Тестовый товар","sku":"K-1"},status="pending_mapping",
            stage_status="pending_mapping",reason_code="SKU_NOT_MAPPED"))
        db.commit()
    response=client.get("/api/alerts?start=2026-10-01&end=2026-10-24")
    assert response.status_code==200,response.text
    items=response.json()["items"]
    mapping=next(x for x in items if x["type"]=="unmapped_products")
    sync=next(x for x in items if x["type"]=="marketplace_sync")
    assert mapping["account_id"]==1 and mapping["count"]==1
    assert "Тест" in sync["action"]
