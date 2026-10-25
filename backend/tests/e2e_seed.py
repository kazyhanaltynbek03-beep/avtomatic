"""Synthetic browser-only WB fixture. Never invoked by production startup."""
import os
if os.environ.get('QOR_E2E_FIXTURE')!='1' or 'qor-browser' not in os.environ.get('DATABASE_URL',''):
    raise SystemExit('Browser fixture requires its isolated temporary database')
from app.db import SessionLocal
from app.models import Company,Account,MarketplaceRecord
with SessionLocal() as db:
    company=Company(name='WB Regression',bin='000000000099');db.add(company);db.flush()
    account=Account(company_id=company.id,name='WB Regression',channel='Wildberries',mode='api');db.add(account);db.flush()
    for eid,payload in [('WB-E2E-SALE',dict(record_type='realization',doc_type_name='Продажа',nm_id=999001,sa_name='WB-E2E',quantity=13,retail_amount='733808',currency='KZT',sale_dt='2026-10-02',rr_dt='2026-10-02',srid='WB-E2E-SALE')),('WB-E2E-FEE',dict(record_type='realization',supplier_oper_name='Логистика',delivery_rub='100045.15',currency='KZT',rr_dt='2026-10-02'))]:
        db.add(MarketplaceRecord(company_id=company.id,account_id=account.id,source='wildberries',external_id=eid,payload=payload))
    db.commit()
