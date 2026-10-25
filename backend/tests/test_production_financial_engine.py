"""Synthetic reproduction of the reported WB incident, not production DB evidence."""
from datetime import date
import io
from sqlalchemy import select,func
from openpyxl import load_workbook
from app.db import SessionLocal
from app.models import Account,Sale,Expense,Product,Batch,Allocation,Movement,User,Return,MarketplaceRecord,MarketplaceProductMapping
from app import finance as f, marketplace_pipeline as mp, ai, importing, schemas as s, canonical
from .test_canonical_marketplace import staged
from .conftest import buy

PERIOD='start=2026-10-01&end=2026-10-31&company_id=1'

def prepare(client):
    with SessionLocal() as db:
        acc=db.get(Account,1);acc.channel='Wildberries'
        staged(db,acc,'realization:prod-shape',record_type='realization',doc_type_name='Продажа',
            nm_id=99001,sa_name='NEW-WB',subject_name='Regression product',quantity=13,
            retail_amount='733808',currency='KZT',sale_dt='2026-10-02',rr_dt='2026-10-02',srid='WB-REGRESSION')
        staged(db,acc,'realization:fee',record_type='realization',supplier_oper_name='Логистика',
            delivery_rub='100045.15',currency='KZT',rr_dt='2026-10-02')
        db.commit()
    response=client.post('/api/admin/reconcile-marketplaces');assert response.status_code==200,response.text


def test_reported_wb_incident_end_to_end_and_cost_import(client):
    prepare(client)
    for _ in range(3): assert client.post('/api/admin/reconcile-marketplaces').status_code==200
    sales=client.get('/api/data/sales?channel=Wildberries').json()['items']
    assert len(sales)==1
    sale=sales[0];assert sale['revenue']==73380800 and sale['quantity']==13 and sale['cogs_pending'] and sale['cogs'] is None
    report=client.get('/api/report?'+PERIOD).json()
    dash=client.get('/api/dashboard/summary?'+PERIOD).json()
    channel=client.get('/api/marketplace-summary?channel=Wildberries&'+PERIOD).json()
    assert report['revenue']==dash['selected']['revenue']==channel['revenue']==sum(x['revenue'] for x in sales)==73380800
    assert report['units']==13 and report['logistics']==10004515
    for key in ('cogs','gross_profit','net_profit','margin','roi'): assert report[key] is None
    assert all(x['profit'] is None for x in report['daily'])
    assert ai._agent_tool_data(report,'get_finance_summary')['revenue']==73380800
    assert ai._agent_tool_data(report,'get_finance_summary')['net_profit'] is None
    response=client.get('/api/reports/executive.xlsx?'+PERIOD);assert response.status_code==200,response.text
    wb=load_workbook(io.BytesIO(response.content));assert wb['Контроль']['E5'].value=='COGS_PENDING'
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Expense))==1
        assert db.scalar(select(func.count()).select_from(Allocation))==0
        rows=[{'SKU':'NEW-WB','Qty':'13','Cost':'20000','Date':'01.10.2026','Currency':'KZT','Ref':'OPEN-TEST','Proof':'supplier invoice'}]
        mapping=dict(sku='SKU',quantity='Qty',unit_cost='Cost',date='Date',currency='Currency',reference='Ref',evidence='Proof')
        run,normalized=importing.preview(db,db.get(User,1),'opening',rows,mapping,{'company_id':1})
        assert not run.errors,run.errors
        assert db.scalar(select(func.count()).select_from(Batch))==0 # preview is read-only
        importing.apply(db,db.get(User,1),'opening',s.OpeningInventoryIn.model_validate(normalized[0]));db.commit()
    report=client.get('/api/report?'+PERIOD).json()
    assert report['revenue']==73380800 and report['cogs']==26000000
    assert report['net_profit']==37376285 and report['profit_complete']
    assert report['cash_flow']==0
    for _ in range(2): assert client.post('/api/admin/reconcile-marketplaces').status_code==200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Sale))==1
        assert db.scalar(select(func.count()).select_from(Expense))==1
        assert db.scalar(select(func.count()).select_from(Allocation))==1
        assert db.scalar(select(func.sum(Batch.remaining)))==0
    for metric in ('revenue','cogs','gross_profit','net_profit','logistics'):
        with SessionLocal() as db:
            detail=f.report_details(db,db.get(User,1),date(2026,10,1),date(2026,10,31),metric,1)
            assert detail['difference']==0,(metric,detail)


def test_historical_sale_after_newer_stock_and_return_before_cost(client):
    buy(client,qty=1,cost=1000,day='2026-10-20')
    prepare(client)
    with SessionLocal() as db:
        sale=db.scalar(select(Sale));pid=sale.product_id;sid=sale.id
    response=client.post('/api/post/returns',json=dict(sale_id=sid,reference='HIST-RETURN',date='2026-10-21',quantity=1))
    assert response.status_code==200,response.text
    response=client.post('/api/post/opening',json=dict(company_id=1,product_id=pid,reference='HIST-COST',date='2026-10-01',quantity=13,unit_cost=2000000,evidence='Historical invoice'))
    assert response.status_code==200,response.text
    with SessionLocal() as db:
        ret=db.scalar(select(Return));assert ret.cogs==2000000
        rid=ret.id
        sale=db.get(Sale,sid);assert not sale.cogs_pending and sale.cogs==26000000
        # Cost is linked to the original batch, but unavailable until inspection.
        assert db.scalar(select(func.sum(Batch.remaining)).where(Batch.product_id==pid))==0
        assert db.scalar(select(func.count()).select_from(Movement).where(Movement.kind=='return'))==0
    for status in ("approved","in_transit","received","inspection","restocked"):
        response=client.post(f'/api/returns/{rid}/status',json={"status":status})
        assert response.status_code==200,response.text
    # Replaying the final transition is idempotent.
    response=client.post(f'/api/returns/{rid}/status',json={"status":"restocked"})
    assert response.status_code==200,response.text
    with SessionLocal() as db:
        assert db.scalar(select(func.sum(Batch.remaining)).where(Batch.product_id==pid))==1
        assert db.scalar(select(func.count()).select_from(Movement).where(Movement.kind=='return'))==1


def test_defective_return_never_enters_available_stock(client):
    buy(client,qty=1,cost=1000,day='2026-10-01')
    sale_response=client.post('/api/post/sales',json=dict(
        company_id=1,account_id=1,product_id=1,reference='DEFECT-SALE',
        date='2026-10-02',quantity=1,unit_price=2000,
    ))
    assert sale_response.status_code==200,sale_response.text
    sale_id=sale_response.json()["id"]
    ret_response=client.post('/api/post/returns',json=dict(
        sale_id=sale_id,reference='DEFECT-RETURN',date='2026-10-03',quantity=1,
    ))
    assert ret_response.status_code==200,ret_response.text
    rid=ret_response.json()["id"]
    with SessionLocal() as db:
        assert db.scalar(select(func.sum(Batch.remaining)))==0
    for status in ("approved","in_transit","received","inspection"):
        response=client.post(f'/api/returns/{rid}/status',json={"status":status})
        assert response.status_code==200,response.text
    response=client.post(f'/api/returns/{rid}/status',json={"status":"defective","reason":"Broken on arrival"})
    assert response.status_code==200,response.text
    response=client.post(f'/api/returns/{rid}/status',json={"status":"written_off","reason":"Disposed of"})
    assert response.status_code==200,response.text
    with SessionLocal() as db:
        ret=db.get(Return,rid);assert ret.inventory_status=="written_off"
        assert db.scalar(select(func.sum(Batch.remaining)))==0
        assert db.scalar(select(func.count()).select_from(Movement).where(Movement.kind=='return'))==0


def test_missing_fifo_does_not_consume_partial_batch(client):
    buy(client,qty=1,cost=123)
    with SessionLocal() as db:
        acc=db.get(Account,1);acc.channel='Wildberries'
        row=staged(db,acc,'partial',record_type='realization',supplier_oper_name='Продажа',sa_name='A',srid='PART',quantity=2,retail_price_withdisc_rub=100,currency='KZT',sale_dt='2026-10-02')
        assert mp.project_record(db,db.get(User,1),acc,row)[0]
        assert db.scalar(select(func.sum(Batch.remaining)))==1
        assert db.scalar(select(func.count()).select_from(Allocation))==0


def test_cost_excel_matches_wb_article_and_reconciles_pending_sale(client):
    prepare(client)
    with SessionLocal() as db:
        sale=db.scalar(select(Sale)); product=db.get(Product,sale.product_id)
        # Supplier uses the WB article, while the ERP SKU is an internal code.
        product.sku='INTERNAL-WB-001'; product.article='WB-ARTICLE-001'
        db.add(MarketplaceProductMapping(company_id=1,account_id=1,channel='Wildberries',
            external_key='sku:WB-ARTICLE-001',product_id=product.id))
        db.commit()
        rows=[{'Артикул WB':'WB-ARTICLE-001','Кол-во':'13','Себестоимость':'20000',
               'Дата':'01.10.2026','Валюта':'KZT','Номер':'COST-WB-001'}]
        mapping={'sku':'Артикул WB','quantity':'Кол-во','unit_cost':'Себестоимость',
                 'date':'Дата','currency':'Валюта','reference':'Номер'}
        run,normalized=importing.preview(db,db.get(User,1),'opening',rows,mapping,{'company_id':1})
        assert not run.errors,run.errors
        assert normalized[0]['product_id']==product.id
        importing.apply(db,db.get(User,1),'opening',s.OpeningInventoryIn.model_validate(normalized[0])); db.commit()
    result=client.get('/api/report?'+PERIOD).json()
    assert result['units']==13 and result['revenue']==73380800
    assert result['cogs']==26000000 and result['net_profit']==37376285
    assert result['profit_complete'] is True


def test_operation_fx_is_frozen_and_date_required(client,monkeypatch):
    monkeypatch.setattr(mp.exchange_rates,'fetch_nbk_rate',lambda *a,**k: (_ for _ in ()).throw(Exception('offline')))
    with SessionLocal() as db:
        acc=db.get(Account,1);acc.channel='Wildberries';acc.settlement_currency='RUB';acc.settlement_fx_rate=99999
        row=staged(db,acc,'fx-sale',record_type='sale',saleID='S1',srid='FX',nmId=20,vendorCode='FX',priceWithDisc=100,date='2026-10-02');rid=row.id;db.commit()
    assert client.post('/api/accounts/1/reprocess').json()['pending_reasons']['FX_REQUIRED:RUB']==1
    assert client.put('/api/accounts/1/settlement',json={'currency':'RUB','fx_rate':55000,'effective_date':'2026-10-02'}).status_code==200
    client.post('/api/accounts/1/reprocess')
    assert client.put('/api/accounts/1/settlement',json={'currency':'RUB','fx_rate':70000,'effective_date':'2026-10-03'}).status_code==200
    client.post('/api/accounts/1/reprocess')
    with SessionLocal() as db:
        sale=db.scalar(select(Sale));assert sale.revenue==55000 and sale.source_fx['fx_rate']==55000
        assert sale.source_fx['operation_date']=='2026-10-02'


def test_demo_flag_live_and_missing_profit_forecast(client,monkeypatch):
    monkeypatch.setenv('DEMO_MODE','false')
    assert client.get('/api/settings').json()['demo'] is False
    prepare(client)
    report=client.get('/api/report?'+PERIOD).json()
    report['daily']=[{'date':'2026-10-0'+str(i),'revenue':100,'profit':None} for i in range(1,4)]
    forecast=ai.forecast(report);assert forecast['net_profit'] is None and forecast['revenue']>0
