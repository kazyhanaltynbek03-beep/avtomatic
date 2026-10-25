from app.db import SessionLocal
from app.models import Expense, CashEntry, AIActionPlan, Audit

def test_ai_multistep_plan_requires_one_explicit_confirmation(client):
    p={"title":"Реклама и оплата","goal":"Записать расход и оплату","thread_id":None,"steps":[
      {"action_type":"post_expense","payload":{"company_id":1,"reference":"PLAN-E1","date":"2026-10-05","category":"ads","description":"Campaign","amount":7000}},
      {"action_type":"post_cash","payload":{"company_id":1,"reference":"PLAN-C1","date":"2026-10-05","category":"ads","description":"Campaign payment","amount":-7000}}
    ]}
    r=client.post('/api/ai/plans/propose',json=p); assert r.status_code==200,r.text
    plan=r.json(); assert plan['status']=='pending' and len(plan['steps'])==2
    with SessionLocal() as db: assert db.query(Expense).count()==0 and db.query(CashEntry).count()==0
    r=client.post(f"/api/ai/plans/{plan['id']}/confirm"); assert r.status_code==200,r.text
    done=r.json(); assert done['status']=='executed' and done['progress']==2 and len(done['action_ids'])==2
    with SessionLocal() as db:
      assert db.query(Expense).count()==1 and db.query(CashEntry).count()==1
      acts=[x.action for x in db.query(Audit).all()]; assert 'ai_plan_proposed' in acts and 'ai_plan_executed' in acts

def test_ai_plan_cancel_executes_nothing(client):
    p={"title":"Не выполнять","steps":[{"action_type":"post_expense","payload":{"company_id":1,"reference":"PLAN-X","date":"2026-10-05","category":"other","description":"No","amount":1000}}]}
    plan=client.post('/api/ai/plans/propose',json=p).json()
    r=client.post(f"/api/ai/plans/{plan['id']}/cancel"); assert r.status_code==200 and r.json()['status']=='cancelled'
    assert client.post(f"/api/ai/plans/{plan['id']}/confirm").status_code==409
    with SessionLocal() as db: assert db.query(Expense).count()==0

def test_ai_plan_rejects_invalid_step_before_creation(client):
    r=client.post('/api/ai/plans/propose',json={"title":"Bad","steps":[{"action_type":"delete_everything","payload":{}}]})
    assert r.status_code==422
    with SessionLocal() as db: assert db.query(AIActionPlan).count()==0
