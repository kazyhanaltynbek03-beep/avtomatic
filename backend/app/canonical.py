"""One validated posting boundary for API, spreadsheets and manual ERP commands.

Money is already normalized to KZT tiyn at this boundary. The existing financial
and FIFO engines remain the only implementations of accounting calculations.
"""
from sqlalchemy import select
from fastapi import HTTPException
from . import finance as f
from .models import CanonicalEvent, Sale, Return, Expense, CashEntry, Purchase

HANDLERS = {'sale': (f.sale, Sale), 'return': (f.return_sale, Return),
            'expense': (f.expense, Expense), 'payment': (f.payment, CashEntry),
            'purchase': (f.purchase, Purchase), 'stock': (f.adjust, None), 'opening':(f.opening_inventory,None)}


def post_event(db, user, kind, payload, identity=None, reject_duplicates=False, confirmed_marketplace=False):
    fn, model = HANDLERS[kind]
    company = getattr(payload, 'company_id', None)
    if kind == 'return':
        sale = db.get(Sale, payload.sale_id)
        if not sale:
            raise HTTPException(422, 'Продажа не найдена')
        company = sale.company_id
    f.get_company(db, user, company)  # authorization and serialization before dedup
    body = payload.model_dump(mode='json')
    ref = getattr(payload, 'reference', None)
    identity = identity or (f'{kind}:{company}:{ref}' if ref else None)
    if not identity:
        return fn(db, user, payload)  # manual adjustments lack a source event ID
    old = db.scalar(select(CanonicalEvent).where(CanonicalEvent.identity == identity))
    if old:
        compare_body=dict(body)
        if kind in {"sale","expense"} and not old.payload.get("source_fx"):
            compare_body["source_fx"]={}
        if reject_duplicates:
            raise HTTPException(409, "Документ уже проведён")
        if old.company_id != company or old.event_type != kind or ({"source_fx":{},**old.payload} if kind in {"sale","expense"} else old.payload) != compare_body:
            raise HTTPException(409, 'EVENT_REVISION_REQUIRES_RECONCILIATION')
        return db.get(model, old.target_id) if model else old
    # Existing production documents predating the canonical-event table.
    target = db.scalar(select(model).where(model.reference == ref)) if model and ref else None
    if target:
        if reject_duplicates:
            raise HTTPException(409, "Документ уже проведён")
        if target.company_id != company:
            raise HTTPException(409, 'REFERENCE_BELONGS_TO_OTHER_COMPANY')
        # Never accept a changed source as an idempotent replay of a legacy entry.
        expected = {'sale': ('quantity', 'product_id', 'account_id', 'date'),
                    'return': ('quantity', 'sale_id', 'date'),
                    'expense': ('amount', 'account_id', 'date'),
                    'payment': ('amount', 'sale_id', 'date'),
                    'purchase': ('date',)}[kind]
        if any(getattr(target, k) != getattr(payload, k) for k in expected):
            raise HTTPException(409, 'LEGACY_EVENT_REVISION_REQUIRES_RECONCILIATION')
        if kind == 'sale' and target.revenue != payload.quantity * payload.unit_price - payload.discount:
            raise HTTPException(409, 'LEGACY_AMOUNT_REQUIRES_RECONCILIATION')
    else:
        target = fn(db,user,payload,confirmed_marketplace=confirmed_marketplace) if kind=="sale" else fn(db,user,payload)
        db.flush()
    event = CanonicalEvent(company_id=company, account_id=getattr(payload, 'account_id', None),
        event_type=kind, identity=identity, payload=body,
        target_id=getattr(target, 'id', None), status='posted')
    db.add(event)
    db.flush()
    return target
