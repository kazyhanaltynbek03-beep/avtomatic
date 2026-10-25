from app.db import SessionLocal
from app.models import AIAction, Expense, Audit, MarketplaceProductMapping, MarketplaceProductCost

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
