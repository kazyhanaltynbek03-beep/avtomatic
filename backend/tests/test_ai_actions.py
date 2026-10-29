from app.db import SessionLocal
from app.models import AIAction, Expense, Audit, Product, Sale, Return, MarketplaceProductMapping, MarketplaceProductCost

def test_ai_action_requires_confirmation(client):
    p={"action_type":"post_expense","payload":{"company_id":1,"reference":"AI-E1","date":"2026-10-05","category":"ads","description":"AI proposal","amount":5000}}
    r=client.post('/api/ai/actions/propose',json=p); assert r.status_code==200,r.text
    a=r.json(); assert a['status']=='pending'; assert a['preview']['requires_confirmation'] is True
    with SessionLocal() as db: assert db.query(Expense).count()==0
    r=client.post(f"/api/ai/actions/{a['id']}/confirm"); assert r.status_code==200,r.text; assert r.json()['status']=='executed'
    with SessionLocal() as db:
        assert db.query(Expense).count()==1
        acts=[x.action for x in db.query(Audit).all()]
        assert 'ai_action_proposed' in acts and 'ai_action_executed' in acts

def test_ai_action_cancel_never_executes(client):
    p={"action_type":"post_expense","payload":{"company_id":1,"reference":"AI-E2","date":"2026-10-05","category":"ads","description":"cancel","amount":5000}}
    a=client.post('/api/ai/actions/propose',json=p).json()
    r=client.post(f"/api/ai/actions/{a['id']}/cancel"); assert r.status_code==200; assert r.json()['status']=='cancelled'
    assert client.post(f"/api/ai/actions/{a['id']}/confirm").status_code==409
    with SessionLocal() as db: assert db.query(Expense).count()==0

def test_ai_action_rejects_unapproved_kind(client):
    r=client.post('/api/ai/actions/propose',json={"action_type":"delete_everything","payload":{}})
    assert r.status_code==422

def test_ai_can_manage_product_card_with_confirmation(client):
    # Product from seed belongs to company 1. Create a card through the same approval boundary as finance writes.
    payload={"company_id":1,"product_id":1,"marketplace":"kaspi","title":"AI card","description":"Confirmed product description","image_document_ids":[101]}
    r=client.post('/api/ai/actions/propose',json={"action_type":"create_product_card","payload":payload}); assert r.status_code==200,r.text
    a=r.json(); assert a['status']=='pending'
    r=client.post(f"/api/ai/actions/{a['id']}/confirm"); assert r.status_code==200,r.text
    result=r.json()['result']; assert result['marketplace']=='kaspi' and result['version']>=1
    # Publishing is also an explicit approved action and never claims marketplace acceptance.
    r=client.post('/api/ai/actions/propose',json={"action_type":"prepare_product_card_publish","payload":{"card_id":result['id'],"review_days":7,"auto_optimize":True}}); assert r.status_code==200,r.text
    pub=r.json(); r=client.post(f"/api/ai/actions/{pub['id']}/confirm"); assert r.status_code==200,r.text
    assert r.json()['result']['status']=='ready_for_publish'

def test_ai_card_optimization_refuses_without_real_metrics(client):
    payload={"company_id":1,"product_id":1,"marketplace":"kaspi","title":"AI card 2","description":"Confirmed","image_document_ids":[101]}
    a=client.post('/api/ai/actions/propose',json={"action_type":"create_product_card","payload":payload}).json()
    card=client.post(f"/api/ai/actions/{a['id']}/confirm").json()['result']
    opt=client.post('/api/ai/actions/propose',json={"action_type":"optimize_product_card","payload":{"card_id":card['id']}}); assert opt.status_code==200
    r=client.post(f"/api/ai/actions/{opt.json()['id']}/confirm"); assert r.status_code==422

def test_ai_marketplace_cost_requires_mapping_and_confirmation(client):
    from app.db import SessionLocal
    with SessionLocal() as db:
        db.add(MarketplaceProductMapping(company_id=1,account_id=1,channel="Kaspi",external_key="kaspi:offer-1",product_id=1))
        db.commit()
    payload={"action_type":"set_marketplace_cost","agent":"finance","payload":{"account_id":1,"product_id":1,"unit_cost":"3456.70","effective_from":"2026-10-24"}}
    proposed=client.post('/api/ai/actions/propose',json=payload); assert proposed.status_code==200,proposed.text
    action=proposed.json(); assert action["status"]=="pending" and action["preview"]["requires_confirmation"] is True
    with SessionLocal() as db: assert db.query(MarketplaceProductCost).count()==0
    confirmed=client.post(f"/api/ai/actions/{action['id']}/confirm"); assert confirmed.status_code==200,confirmed.text
    assert confirmed.json()["result"]["unit_cost"]=="3456.70"
    with SessionLocal() as db:
        row=db.query(MarketplaceProductCost).one()
        assert row.unit_cost==345670 and str(row.effective_from)=="2026-10-24"

def test_ai_marketplace_cost_refuses_unmapped_product(client):
    response=client.post('/api/ai/actions/propose',json={"action_type":"set_marketplace_cost","agent":"buyer","payload":{"account_id":1,"product_id":1,"unit_cost":1000,"effective_from":"2026-10-24"}})
    assert response.status_code==422 and "сопоставлен" in response.text

def test_ai_can_link_exact_listing_only_after_confirmation(client):
    payload={"action_type":"link_marketplace_listing","agent":"buyer","payload":{"account_id":1,"product_id":1,"id_type":"sku","external_id":"seller-A-1"}}
    proposed=client.post('/api/ai/actions/propose',json=payload); assert proposed.status_code==200,proposed.text
    action=proposed.json(); assert action["status"]=="pending"
    with SessionLocal() as db: assert db.query(MarketplaceProductMapping).count()==0
    confirmed=client.post(f"/api/ai/actions/{action['id']}/confirm"); assert confirmed.status_code==200,confirmed.text
    assert confirmed.json()["result"]["external_key"]=="sku:seller-A-1"
    with SessionLocal() as db:
        row=db.query(MarketplaceProductMapping).one()
        assert (row.account_id,row.product_id,row.external_key)==(1,1,"sku:seller-A-1")

def test_ai_listing_link_refuses_cross_company_and_conflicting_ids(client):
    with SessionLocal() as db:
        product=db.get(Product,1); product.specifications={"_qor_company_ids":[1]}; db.commit()
    other=client.post('/api/ai/actions/propose',json={"action_type":"link_marketplace_listing","agent":"buyer","payload":{"account_id":2,"product_id":1,"id_type":"product","external_id":"p-2"}})
    assert other.status_code==422
    with SessionLocal() as db:
        db.add(MarketplaceProductMapping(company_id=1,account_id=1,channel="Kaspi",external_key="sku:occupied",product_id=2)); db.commit()
    conflict=client.post('/api/ai/actions/propose',json={"action_type":"link_marketplace_listing","agent":"buyer","payload":{"account_id":1,"product_id":1,"id_type":"sku","external_id":"occupied"}})
    assert conflict.status_code==409

def test_ai_can_change_alert_threshold_after_confirmation(client):
    proposed=client.post('/api/ai/actions/propose',json={"action_type":"set_product_min_stock","agent":"buyer","payload":{"product_id":1,"min_stock":12}})
    assert proposed.status_code==200,proposed.text
    with SessionLocal() as db: assert db.get(Product,1).min_stock==5
    done=client.post(f"/api/ai/actions/{proposed.json()['id']}/confirm"); assert done.status_code==200,done.text
    assert done.json()["result"]["min_stock"]==12 and done.json()["result"]["alerts_enabled"] is True

def test_ai_action_catalog_exposes_approved_inventory_controls():
    from app import ai
    assert {"link_marketplace_listing","set_product_min_stock","set_return_inventory_status"} <= set(ai.AGENT_ACTIONS["buyer"])
    assert "link_marketplace_listing" in ai.AGENT_ACTIONS["rick"]

def test_ai_specialist_cannot_claim_another_role_action(client):
    denied=client.post('/api/ai/actions/propose',json={"action_type":"post_expense","agent":"buyer","payload":{"company_id":1,"reference":"AI-NOPE","date":"2026-10-05","category":"ads","amount":5000}})
    assert denied.status_code==403

def test_ai_return_action_is_internal_and_requires_confirmation(client):
    from datetime import date
    with SessionLocal() as db:
        sale=Sale(company_id=1,account_id=1,product_id=1,reference="AI-RETURN-SALE",date=date(2026,10,10),quantity=1,revenue=10000,cogs=5000,commission=0,logistics=0,advertising=0)
        db.add(sale); db.flush()
        db.add(Return(company_id=1,sale_id=sale.id,date=date(2026,10,11),reference="AI-RETURN-1",quantity=1,revenue=10000,cogs=5000,inventory_status="requested"))
        db.commit()
    proposal=client.post('/api/ai/actions/propose',json={"action_type":"set_return_inventory_status","agent":"buyer","payload":{"return_id":1,"status":"approved"}})
    assert proposal.status_code==200,proposal.text
    with SessionLocal() as db: assert db.get(Return,1).inventory_status=="requested"
    completed=client.post(f"/api/ai/actions/{proposal.json()['id']}/confirm")
    assert completed.status_code==200,completed.text
    assert completed.json()["result"]["external_marketplace_status_changed"] is False
    with SessionLocal() as db: assert db.get(Return,1).inventory_status=="approved"
