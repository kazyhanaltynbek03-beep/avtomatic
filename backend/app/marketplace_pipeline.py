"""Normalize staging into validated canonical events and the existing ERP engine."""
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
from sqlalchemy import select
from .models import Account, MarketplaceRecord, MarketplaceProductMapping, Product, Sale, Expense, CanonicalEvent
from . import schemas as s, canonical, exchange_rates, finance as f
from . import wb_operation

CONFIRMED_KASPI = {'COMPLETED'}
RETURNED_KASPI = {'RETURNED', 'ARRIVED_BACKWARD'}
CONFIRMED_OZON = {'delivered', 'completed'}
# Do not treat a cancelled Ozon posting as a restocked return: cancellation can
# happen before delivery. Only an explicit returned posting can restore FIFO.
RETURNED_OZON = {'returned'}


class Pending(ValueError):
    pass


def _day(value, timezone_name=None):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        tz = ZoneInfo(timezone_name) if timezone_name else None
        if isinstance(value, (int, float)):
            instant = datetime.fromtimestamp(
                value / 1000 if value > 10_000_000_000 else value, timezone.utc
            )
            return instant.astimezone(tz).date() if tz else instant.date()
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if tz and parsed.tzinfo:
            parsed = parsed.astimezone(tz)
        return parsed.date()
    except (ValueError, TypeError, OverflowError, KeyError):
        raise Pending('DATE_MISSING_OR_INVALID')


def _day_for_account(value, acc):
    return _day(value, "Asia/Almaty" if str(getattr(acc, "channel", "")).lower() == "kaspi" else None)


def _number(value):
    try:
        result = Decimal(str(value).replace('\u00a0', '').replace('\u202f', '').replace(' ', '').replace(',', '.'))
        if not result.is_finite():
            raise ValueError()
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise Pending('AMOUNT_MISSING_OR_INVALID')


def _cents(value, acc=None, currency=None, db=None, on_date=None):
    rate = 10000
    if acc and currency and currency.upper() != 'KZT':
        if db is not None and on_date is not None:
            try:
                rate, _source = exchange_rates.rate_scaled(db, currency, _day_for_account(on_date, acc), acc)
            except exchange_rates.FxUnavailable as exc:
                raise Pending(str(exc))
        elif currency.upper() == acc.settlement_currency and acc.settlement_fx_rate > 0:
            rate = acc.settlement_fx_rate
        else:
            raise Pending('FX_REQUIRED:' + currency.upper())
    return int((_number(value) * 100 * Decimal(rate) / 10000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def identifiers(p):
    fields = {'supplierArticle': 'sku', 'vendorCode': 'sku', 'sa_name': 'sku', 'offer_id': 'sku',
              'merchant_code': 'sku', 'external_sku': 'sku', 'sku': 'sku', 'barcode': 'barcode',
              'nmId': 'product', 'nmID': 'product', 'nm_id': 'product', 'product_id': 'product',
              'external_product_id': 'product', 'chrtId': 'size'}
    return list(dict.fromkeys([f'{kind}:{str(p[key]).strip()}' for key, kind in fields.items()
                             if p.get(key) is not None and str(p[key]).strip()] + ['barcode:'+str(x) for x in p.get('barcodes') or []]))


def _seller_sku(payload):
    for key in ("supplierArticle", "vendorCode", "sa_name", "offer_id", "merchant_code", "external_sku"):
        value = payload.get(key)
        if value is not None and str(value).strip(): return str(value).strip()[:100]
    value = payload.get("sku")
    if value is not None and str(value).strip() and not str(value).strip().isdigit(): return str(value).strip()[:100]
    return ""


def _product_name(payload, sku):
    for key in ("product_name", "name", "title", "subjectName", "subject_name", "imt_name"):
        value = payload.get(key)
        if value is not None and str(value).strip(): return str(value).strip()[:200]
    return sku


def _media_urls(payload):
    urls=[]
    def add(value):
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            urls.append(value)
        elif isinstance(value, dict):
            for candidate in ("big", "square", "c516x688", "c246x328", "url", "src", "imageUrl", "image_url"):
                add(value.get(candidate))
        elif isinstance(value, list):
            for item in value:
                add(item)
    sources = [payload]
    sources.extend(
        value for key in ("merchant_product_attributes", "product_attributes")
        if isinstance((value := payload.get(key)), dict)
    )
    for source in sources:
        for key in ("primary_image", "image", "image_url", "imageUrl", "picture", "thumbnail"):
            add(source.get(key))
        for key in ("images", "photos", "media"):
            values = source.get(key) or []
            if isinstance(values, dict): values = list(values.values())
            if not isinstance(values, list): continue
            for item in values:
                add(item)
    return list(dict.fromkeys(urls))[:12]

def _update_product_metadata(product, payload, acc):
    name=_product_name(payload, product.sku)
    if name and (not product.name or product.name==product.sku or product.name.startswith(acc.channel+':')): product.name=name
    for key in ("brand","brand_name","manufacturer"):
        if payload.get(key): product.brand=str(payload[key])[:120]; break
    category=payload.get("subjectName") or payload.get("subject_name") or payload.get("category")
    if isinstance(category,dict): category=category.get("title") or category.get("name") or category.get("code")
    if category: product.category=str(category)[:100]
    media=_media_urls(payload)
    if media: product.media=list(dict.fromkeys((product.media or [])+media))[:20]
    price=payload.get("price") or payload.get("current_price") or payload.get("retailPrice")
    if isinstance(price,dict): price=price.get("price") or price.get("marketing_price") or price.get("old_price")
    try:
        if price is not None and Decimal(str(price))>=0: product.price=int((Decimal(str(price))*100).quantize(Decimal("1")))
    except Exception: pass
    specs=dict(product.specifications or {})
    specs.update({"source":acc.channel,"account_id":acc.id,"external_keys":identifiers(payload),"auto_created":specs.get("auto_created",True)})
    attrs=payload.get("attributes") or payload.get("characteristics") or payload.get("dimensions")
    if attrs: specs["marketplace_attributes"]=attrs
    product.specifications=specs
    return product

def ensure_marketplace_product(db,acc,payload):
    sku=_seller_sku(payload)
    keys=identifiers(payload)
    stable=next((k for k in keys if k.startswith('product:')),None)
    if not sku and not stable: return None
    if not sku: sku=(acc.channel+':'+str(acc.id)+':'+stable)[:100]
    product=Product(sku=sku,name=_product_name(payload,sku),article=_seller_sku(payload),
        category=payload.get('subject_name') or 'Marketplace',active=True,min_stock=0,
        specifications={'source':acc.channel,'account_id':acc.id,'external_keys':keys,'auto_created':True})
    _update_product_metadata(product,payload,acc)
    db.add(product);db.flush();return product


def resolve_product(db, acc, payload):
    keys=identifiers(payload)
    mappings=db.scalars(select(MarketplaceProductMapping).where(
        MarketplaceProductMapping.account_id==acc.id,MarketplaceProductMapping.company_id==acc.company_id,
        MarketplaceProductMapping.external_key.in_(keys))).all() if keys else []
    mapped={m.product_id for m in mappings}
    skus=[str(payload[k]).strip() for k in ('supplierArticle','vendorCode','sa_name','offer_id','merchant_code','external_sku') if payload.get(k)]
    if not skus and payload.get('sku') and not str(payload['sku']).isdigit(): skus=[str(payload['sku'])]
    candidates=db.scalars(select(Product).where((Product.sku.in_(skus))|(Product.article.in_(skus)))).all() if skus else []
    matched=mapped or {p.id for p in candidates}
    if len(matched)>1: raise Pending('MAPPING_AMBIGUOUS:'+','.join(keys))
    if not matched:
        barcodes={k.split(':',1)[1] for k in keys if k.startswith('barcode:')}
        if barcodes:
            for product in db.scalars(select(Product)):
                specs=product.specifications or {}
                known=set(map(str,specs.get('barcodes') or [])) | {str(specs.get('barcode') or '')}
                if known & barcodes: matched.add(product.id)
        if len(matched)>1: raise Pending('MAPPING_AMBIGUOUS:'+','.join(keys))
    product=db.get(Product,next(iter(matched))) if matched else ensure_marketplace_product(db,acc,payload)
    if not product: raise Pending('SKU_NOT_MAPPED:'+','.join(keys))
    if not product.active: raise Pending('MAPPED_PRODUCT_INACTIVE')
    _update_product_metadata(product,payload,acc)
    known={m.external_key for m in mappings}
    for key in keys:
        if key not in known: db.add(MarketplaceProductMapping(company_id=acc.company_id,account_id=acc.id,
            channel=acc.channel,external_key=key,product_id=product.id))
    db.flush();return product


def amount_snapshot(db,acc,value,currency,dt,model,ref):
    currency=str(currency).upper();day=_day_for_account(dt, acc);original=_number(value)
    existing=db.scalar(select(model).where(model.reference==ref,model.company_id==acc.company_id))
    prior=existing.source_fx if existing else None
    if prior:
        if _number(prior['original_amount'])!=original or prior['original_currency']!=currency or prior['operation_date']!=str(day):
            raise Pending('EVENT_REVISION_REQUIRES_RECONCILIATION')
        return prior['amount_kzt'],prior
    try: rate,source=exchange_rates.rate_scaled(db,currency,day,acc)
    except exchange_rates.FxUnavailable as exc: raise Pending(str(exc))
    total=int((original*100*Decimal(rate)/10000).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    return total,dict(original_amount=str(original),original_currency=currency,operation_date=str(day),
        fx_rate=rate,fx_source=source,amount_kzt=total,external_id=ref)


def reference(acc, external, kind='sale'):
    ref = f'{acc.channel}:{acc.id}:{external}' if kind == 'sale' else f'{acc.channel}:{kind}:{acc.id}:{external}'
    return ref if len(ref) <= 120 else ref[:45] + ':' + hashlib.sha256(ref.encode()).hexdigest()


def _sale_event(db, acc, payload, quantity, amount, dt, external, currency, legacy_refs=None):
    product = resolve_product(db, acc, payload)
    qty = int(quantity or 0)
    if qty <= 0 or _number(amount) <= 0:
        raise Pending('SALE_FIELDS_INCOMPLETE')
    # Represent a line total exactly, including totals indivisible by quantity.
    ref = reference(acc, external)
    legacy_refs = list(legacy_refs or [])
    if acc.channel == 'Wildberries':
        legacy_refs.extend(reference(acc, 'sale:' + str(x)) for x in (payload.get('srid'), payload.get('saleID')) if x)
    legacy = db.scalars(select(Sale).where(Sale.account_id == acc.id, Sale.company_id == acc.company_id,
                                         Sale.reference.in_(legacy_refs))).all() if legacy_refs else []
    if len(legacy) > 1: raise Pending('LEGACY_DUPLICATES_REQUIRE_RECONCILIATION')
    if legacy: ref = legacy[0].reference
    total,fx=amount_snapshot(db,acc,amount,currency,dt,Sale,ref)
    unit=(total+qty-1)//qty
    return 'sale', s.SaleIn(company_id=acc.company_id, account_id=acc.id, product_id=product.id,
        reference=ref, date=_day_for_account(dt, acc), quantity=qty, unit_price=unit,
        discount=unit * qty - total, paid=0,source_fx=fx)


def _return_event(db, acc, payload, quantity, dt, external, original, restocked):
    product = resolve_product(db, acc, payload)
    sale = db.scalar(select(Sale).where(Sale.reference == reference(acc, original),
        Sale.company_id == acc.company_id, Sale.account_id == acc.id, Sale.product_id == product.id))
    if not sale:
        raise Pending('RETURN_REQUIRES_SALE_MATCH:' + str(original))
    if not restocked and not sale.cogs_pending:
        raise Pending('RETURN_STOCK_CONFIRMATION_REQUIRED')
    return 'return', s.ReturnIn(sale_id=sale.id, reference=reference(acc, external, 'return'),
                               date=_day_for_account(dt, acc), quantity=int(quantity), refund=0)


def _expense_event(db, acc, external, category, value, dt, currency):
    ref=reference(acc,external+':'+category,'expense')
    if not _number(value): return None
    amount,fx=amount_snapshot(db,acc,value,currency,dt,Expense,ref)
    if not amount:
        return None
    return 'expense', s.ExpenseIn(company_id=acc.company_id, account_id=acc.id,
        reference=ref,date=_day_for_account(dt, acc),category=category,amount=amount,paid=False,source_fx=fx)


def _ozon_commission_events(db, acc, posting, dt):
    """Book only explicit Ozon commission amounts from posting financial data.

    Seller payout is deliberately not cash: it is an accrual, and a cash entry
    is created only from a real settlement document. Unknown service fields stay
    in staging rather than being guessed as logistics or advertising.
    """
    events=[]
    financial=posting.get('financial_data') or {}
    for index,line in enumerate(financial.get('products') or []):
        commission=line.get('commission_amount')
        currency=line.get('commissions_currency_code') or line.get('currency_code')
        nested=line.get('commission') or {}
        if commission is None:
            commission=nested.get('amount')
            currency=currency or nested.get('currency')
        if commission is None or _number(commission) <= 0:
            continue
        product_key=line.get('product_id') or index
        event=_expense_event(db,acc,f"{posting.get('posting_number') or posting.get('order_number') or 'posting'}:{product_key}",
            'Marketplace commission',commission,dt,currency or posting.get('currency_code') or 'RUB')
        if event: events.append(event)
    return events


def normalize_record(db, acc, row):
    p = row.payload or {}
    source = row.source.lower()
    typ = str(p.get('record_type') or '').lower()
    events = []
    # Product metadata is independent from financial confirmation. A pending/new
    # posting must still enrich the catalogue instead of being discarded.
    if source == 'ozon' and typ == 'posting':
        for item in p.get('products') or []:
            if isinstance(item, dict):
                resolve_product(db, acc, item)
    if source == 'wildberries' and typ == 'sale':
        sid = str(p.get('saleID') or p.get('saleId') or '')
        original = 'wb-sale:' + str(p.get('srid') or sid)
        if sid.upper().startswith('R') or p.get('isStorno'):
            # Sales statistics don't confirm physical receipt at the warehouse.
            events.append(_return_event(db, acc, p, p.get('quantity') or 1,
                p.get('date'), row.external_id, 'wb-sale:' + str(p.get('srid') or ''),
                p.get('returned_to_warehouse') is True))
        else:
            # Do not substitute list price for an asynchronously missing sale price.
            amount = p.get('priceWithDisc')
            if amount is None:
                amount = p.get('finishedPrice')
            events.append(_sale_event(db, acc, p, 1, amount, p.get('date'), original,
                                      p.get('currency') or 'RUB'))
    elif source == 'wildberries' and typ == 'realization':
        currency = p.get('currency') or p.get('currencyName') or p.get('currency_name') or 'RUB'
        currency = {'руб': 'RUB', 'руб.': 'RUB', 'тенге': 'KZT'}.get(str(currency).lower(), currency)
        dt = p.get('saleDt') or p.get('sale_dt') or p.get('rrDt') or p.get('rrDate') or p.get('rr_dt')
        operation = wb_operation.operation_label(p)
        op = operation
        srid = p.get('srid') or p.get('srId'); qty = int(p.get('quantity') or 0)
        is_return = wb_operation.is_return_operation(p) and not wb_operation.is_return_reversal(p)
        is_sale = not wb_operation.is_return_operation(p) and ('продаж' in op or 'sale' in op)
        is_logistics = any(x in op for x in ('логист', 'достав', 'перевоз'))
        is_storage = 'хранен' in op or 'storage' in op
        is_acceptance = any(x in op for x in ('приемк', 'приёмк', 'acceptance'))
        is_penalty = any(x in op for x in ('штраф', 'penalty'))
        is_deduction = any(x in op for x in ('удержан', 'deduction'))
        if is_sale and qty > 0:
            if not srid: raise Pending('SALE_IDENTITY_MISSING')
            realized_amount = p.get('retailAmount', p.get('retail_amount'))
            if realized_amount is not None:
                total = _number(realized_amount)
            else:
                # Legacy statistics payloads lack retailAmount. Preserve this
                # compatibility only when the current Finance API value is absent.
                price = p.get('retailPriceWithDisc', p.get('retail_price_withdisc_rub'))
                if price is None:
                    raise Pending('WB_REALIZED_AMOUNT_MISSING')
                total = _number(price) * qty
            events.append(_sale_event(db,acc,p,qty,total,dt,'wb-sale:'+str(srid),currency))
            # Detailed realization is the settlement/fee report, not the source
            # of turnover. WB documents ppvzSalesCommission as a money string;
            # commissionPercent is the separate rate. Keep this actual fee.
            for label, camel, snake in (('Marketplace acquiring','acquiringFee','acquiring_fee'),
                                        ('Marketplace commission','ppvzSalesCommission','ppvz_sales_commission'),
                                        ('Marketplace commission VAT','vwNds','ppvz_vw_nds'),
                                        ('Marketplace logistics','deliveryService','delivery_rub')):
                amount = p.get(camel, p.get('deliveryRub', p.get(snake, 0))) if label == 'Marketplace logistics' else p.get(camel, p.get(snake, 0))
                event = _expense_event(db, acc, row.external_id, label, amount, p.get('rrDt') or p.get('rrDate') or p.get('rr_dt') or dt, currency)
                if event: events.append(event)
            # Do not infer any additional fee from retail minus seller payout:
            # that difference can include discounts, SPP and other adjustments.
        elif is_return and qty > 0:
            events.append(_return_event(db, acc, p, qty, dt, row.external_id, 'wb-sale:' + str(srid or ''), p.get('returned_to_warehouse') is True))
        elif is_logistics:
            event = _expense_event(db, acc,row.external_id,'Marketplace logistics',p.get('deliveryService',p.get('deliveryRub',p.get('delivery_rub',0))),p.get('rrDt') or p.get('rrDate') or p.get('rr_dt') or dt,currency)
            if event: events.append(event)
        elif is_storage:
            event = _expense_event(db, acc,row.external_id,'Marketplace storage',p.get('paidStorage',p.get('storageFee',p.get('storage_fee',0))),p.get('rrDt') or p.get('rrDate') or p.get('rr_dt') or dt,currency)
            if event: events.append(event)
        elif is_acceptance:
            event = _expense_event(db, acc,row.external_id,'Marketplace acceptance',p.get('paidAcceptance',p.get('acceptance',0)),p.get('rrDt') or p.get('rrDate') or p.get('rr_dt') or dt,currency)
            if event: events.append(event)
        elif is_penalty:
            event = _expense_event(db, acc,row.external_id,'Marketplace penalties',p.get('penalty',0),p.get('rrDt') or p.get('rrDate') or p.get('rr_dt') or dt,currency)
            if event: events.append(event)
        elif is_deduction:
            event = _expense_event(db, acc,row.external_id,'Marketplace deductions',p.get('deduction',0),p.get('rrDt') or p.get('rrDate') or p.get('rr_dt') or dt,currency)
            if event: events.append(event)
        else:
            return [], 'received', 'WB_OPERATION_NOT_FINANCIAL_OR_UNCLASSIFIED:' + (operation or 'EMPTY')
    elif source == 'kaspi' and typ == 'delivery_charge':
        status = str(p.get('order_status') or '').upper()
        if status in CONFIRMED_KASPI:
            charge = _expense_event(db, acc, row.external_id, 'Marketplace logistics',
                p.get('amount'), p.get('completed_date') or p.get('order_creation_date'),
                p.get('currency') or 'KZT')
            if charge: events.append(charge)
        else:
            return [], 'received', 'DELIVERY_COST_REQUIRES_COMPLETED_ORDER'
    elif source == 'kaspi' and typ == 'return_delivery_charge':
        status = str(p.get('order_status') or '').upper()
        if status in RETURNED_KASPI:
            charge = _expense_event(db, acc, row.external_id, 'Marketplace return logistics',
                p.get('amount'), p.get('returned_date') or p.get('return_date') or p.get('completed_date') or p.get('order_creation_date'),
                p.get('currency') or 'KZT')
            if charge: events.append(charge)
        else:
            return [], 'received', 'RETURN_LOGISTICS_REQUIRES_CONFIRMED_RETURN'
    elif source == 'kaspi' and typ == 'order_entry':
        status=str(p.get('order_status') or '').upper()
        if status in CONFIRMED_KASPI:
            events.append(_sale_event(db, acc, p, p.get('quantity'), p.get('total_price'),
                p.get('completed_date') or p.get('order_creation_date'), row.external_id, 'KZT'))
        elif status in RETURNED_KASPI:
            # A return is booked only after Kaspi confirms it came back, never
            # at a mere cancellation/request stage.
            events.append(_return_event(db, acc, p, p.get('quantity'),
                p.get('returned_date') or p.get('completed_date') or p.get('order_creation_date'),
                'return:' + row.external_id, row.external_id, True))
        else:
            return [], 'received', 'NOT_FINANCIAL_OR_NOT_CONFIRMED'
    elif source == 'ozon' and typ == 'posting' and str(p.get('status') or '').lower() in CONFIRMED_OZON:
        products = p.get('products') or []
        if not products:
            raise Pending('POSTING_PRODUCTS_MISSING')
        seen = set()
        for index, x in enumerate(products):
            key = str(x.get('sku') or x.get('offer_id') or '')
            if not key or key in seen:
                raise Pending('POSTING_PRODUCT_IDENTITY_AMBIGUOUS')
            seen.add(key)
            qty = int(x.get('quantity') or 0)
            events.append(_sale_event(db, acc, x, qty, _number(x.get('price')) * qty,
                p.get('delivered_at') or p.get('shipment_date') or p.get('in_process_at') or p.get('created_at'),
                row.external_id + ':' + key, x.get('currency_code') or p.get('currency_code') or 'RUB',
                [reference(acc, f"{row.external_id}:{index}:{x.get('offer_id') or x.get('sku') or ''}")]))
        events.extend(_ozon_commission_events(db, acc, p,
            p.get('delivered_at') or p.get('shipment_date') or p.get('in_process_at') or p.get('created_at')))
    elif source == 'ozon' and typ == 'posting' and str(p.get('status') or '').lower() in RETURNED_OZON:
        products=p.get('products') or []
        if not products: raise Pending('POSTING_PRODUCTS_MISSING')
        for x in products:
            key=str(x.get('sku') or x.get('offer_id') or '')
            if not key: raise Pending('POSTING_PRODUCT_IDENTITY_AMBIGUOUS')
            events.append(_return_event(db,acc,x,x.get('quantity'),
                p.get('cancelled_at') or p.get('delivered_at') or p.get('shipment_date') or p.get('created_at'),
                'return:'+row.external_id+':'+key,row.external_id+':'+key,True))
    elif source == 'ozon' and typ == 'finance_accrual':
        # New Ozon accrual API is nested and type_id-driven. total_amount is NOT
        # blindly booked as an expense: POSTING can contain seller revenue.
        dt=p.get('date') or p.get('accrual_date') or p.get('operation_date')
        type_names=p.get('_accrual_type_names') or {}
        def money(obj):
            return obj if isinstance(obj,dict) else {}
        def category_for(type_id):
            name=str(type_names.get(str(type_id)) or '').lower()
            # Stable IDs are used only where Ozon's accrual semantics are known;
            # names remain the forward-compatible path for newly introduced IDs.
            try: tid=int(type_id)
            except (TypeError,ValueError): tid=-1
            if tid in {32,29,98} or any(w in name for w in ('logistic','delivery','lastmile','достав','логист')): return 'Marketplace logistics'
            if tid in {1} or any(w in name for w in ('acquiring','эквайр')): return 'Marketplace acquiring'
            if tid in {41,54} or any(w in name for w in ('payperclick','advert','promotion','marketing','реклам','продвиж')): return 'Реклама'
            if any(w in name for w in ('storage','хранен')): return 'Marketplace storage'
            if any(w in name for w in ('commission','комисс')): return 'Marketplace commission'
            if any(w in name for w in ('penalty','штраф')): return 'Marketplace penalties'
            return None
        charges=[]
        non=p.get('non_item_fee') or {}
        if isinstance(non,dict) and non.get('type_id') is not None:
            charges.append((non.get('type_id'), money(non.get('accrued')), 'non'))
        for group in ((p.get('item_fees') or {}).get('fees') or []):
            if not isinstance(group,dict): continue
            sku=group.get('sku')
            for fee in group.get('fees') or []:
                if isinstance(fee,dict): charges.append((fee.get('type_id'),money(fee.get('accrued')),f'item:{sku}'))
        posting=p.get('posting') or {}
        if isinstance(posting,dict):
            for prod in posting.get('products') or []:
                if not isinstance(prod,dict): continue
                sku=prod.get('sku')
                # Product-level commission is explicit and safe to book.
                comm=prod.get('commission') or {}
                sale_comm=money(comm.get('sale_commission'))
                if sale_comm.get('amount') is not None:
                    charges.append(('commission',sale_comm,f'commission:{sku}'))
                delivery=prod.get('delivery') or {}
                total_delivery=money(delivery.get('total_accrued'))
                service_ids=[x.get('type_id') for x in delivery.get('services') or [] if isinstance(x,dict)]
                if total_delivery.get('amount') is not None:
                    charges.append((service_ids[0] if service_ids else 'delivery',total_delivery,f'delivery:{sku}'))
        for idx,(type_id,amount_obj,suffix) in enumerate(charges):
            value=amount_obj.get('amount'); currency=amount_obj.get('currency') or p.get('currency') or 'RUB'
            if value is None or _number(value)==0: continue
            category='Marketplace commission' if type_id=='commission' else ('Marketplace logistics' if type_id=='delivery' else category_for(type_id))
            if not category: continue
            event=_expense_event(db,acc,row.external_id+':'+str(suffix)+':'+str(idx),category,abs(_number(value)),dt,currency)
            if event: events.append(event)
        if not events:
            return [], 'received', 'OZON_ACCRUAL_INFORMATIONAL_OR_UNCLASSIFIED:' + str(p.get('type_id') or p.get('accrued_category') or '')
    elif source == 'ozon' and typ == 'finance_transaction':
        # Accrual is a settlement receivable, never a bank payout.
        dt = p.get('operation_date')
        currency = p.get('currency_code') or 'RUB'
        commission = p.get('sale_commission') or 0
        if _number(commission) > 0:
            raise Pending('COMMISSION_REVERSAL_REQUIRES_RECONCILIATION')
        event = _expense_event(db, acc, row.external_id, 'Marketplace commission', -_number(commission), dt, currency)
        if event:
            events.append(event)
        for i, service in enumerate(p.get('services') or []):
            price = _number(service.get('price'))
            name = str(service.get('name') or '')
            category = 'Marketplace logistics' if any(word in name for word in ('Delivery','Return','Logistic','Dropoff','Pickup','Fulfillment','Storage')) else 'Marketplace other expenses'
            if any(word in name for word in ('Advertising','Marketing','Promotion')): category = 'Реклама'
            event = _expense_event(db, acc, row.external_id + ':' + str(i), category, -price, dt, currency)
            if event:
                events.append(event)
        if not events and _number(p.get('amount') or 0):
            raise Pending('FINANCIAL_OPERATION_REQUIRES_CLASSIFICATION:' + str(p.get('operation_type') or ''))
    elif typ in {'stock', 'product'}:
        product=resolve_product(db, acc, p)
        if typ == 'stock':
            qty=0
            stocks=p.get('stocks')
            if isinstance(stocks,dict):
                for part in stocks.values():
                    if isinstance(part,dict): qty += int(part.get('present') or 0)
            elif isinstance(stocks,list):
                for part in stocks:
                    if isinstance(part,dict): qty += int(part.get('present') or part.get('quantity') or part.get('amount') or 0)
            else:
                qty=int(p.get('quantity') or p.get('stock') or p.get('amount') or 0)
            specs=dict(product.specifications or {})
            snapshots=dict(specs.get('marketplace_stock') or {})
            snapshots[f'{acc.channel}:{acc.id}']={'quantity':qty,'updated_at':datetime.now(timezone.utc).isoformat()}
            specs['marketplace_stock']=snapshots; product.specifications=specs
        # A stock snapshot has neither a movement delta nor supplier cost. Keep
        # it available for inventory reconciliation; never manufacture FIFO lots.
        return [], 'received_stock' if typ == 'stock' else 'mapped_product', 'STOCK_SNAPSHOT_RECONCILE' if typ == 'stock' else 'PRODUCT_MAPPED'
    else:
        return [], 'received', 'NOT_FINANCIAL_OR_NOT_CONFIRMED'
    return events, 'projected' if events else 'received', 'projected' if events else 'NO_FINANCIAL_EVENT'


def project_record(db, user, acc, row):
    try:
        # A multi-line posting is atomic. Mapping and every ledger write roll back
        # together; a retry can never leave a partially deducted shipment.
        with db.begin_nested():
            payload = row.payload or {}
            if (acc.channel == "Kaspi" and str(payload.get("record_type") or "").lower() == "order_entry"
                    and str(payload.get("order_status") or "").upper() in RETURNED_KASPI):
                sale_ref = reference(acc, row.external_id)
                prior_sale = db.scalar(select(Sale.id).where(
                    Sale.reference == sale_ref,
                    Sale.account_id == acc.id,
                    Sale.company_id == acc.company_id,
                ))
                if prior_sale is None:
                    sale_kind, sale_payload = _sale_event(
                        db, acc, payload, payload.get("quantity"), payload.get("total_price"),
                        payload.get("completed_date") or payload.get("order_creation_date"),
                        row.external_id, "KZT",
                    )
                    canonical.post_event(db, user, sale_kind, sale_payload, confirmed_marketplace=True)
            events, status, reason = normalize_record(db, acc, row)
            for kind, payload in events:
                canonical.post_event(db,user,kind,payload,confirmed_marketplace=True)
            db.flush()
        ok = status == 'projected'
        pending_cost=any(kind=='sale' and db.scalar(select(Sale.cogs_pending).where(Sale.reference==payload.reference)) for kind,payload in events)
        if pending_cost: reason='COGS_PENDING'
        elif ok: reason='SALE_POSTED' if any(k=='sale' for k,_ in events) else 'EVENT_POSTED'
    except Exception as exc:
        reason = str(getattr(exc, 'detail', exc))[:400] or exc.__class__.__name__
        status = 'pending_mapping' if reason.startswith(('SKU_NOT_MAPPED', 'MAPPING_', 'MAPPED_PRODUCT')) else 'pending_erp'
        ok = False
    row.status = status
    row.stage_status=('pending_fifo' if reason=='COGS_PENDING' else 'posted') if ok else ('pending_fx' if reason.startswith('FX_REQUIRED') else ('pending_mapping' if status=='pending_mapping' else ('failed' if status.startswith('pending') else 'ignored_non_financial')))
    row.reason_code=reason.split(':',1)[0]
    row.payload = {**(row.payload or {}), '_qor_projection_reason': reason}
    return ok, reason


def _wb_allowed_expense_categories(payload):
    op = str(payload.get('sellerOperName') or payload.get('supplier_oper_name') or '').strip().lower()
    if op in {'продажа', 'sale'}:
        return {'Marketplace commission', 'Marketplace commission VAT', 'Marketplace acquiring', 'Marketplace logistics'}
    if any(x in op for x in ('логист', 'достав', 'перевоз')): return {'Marketplace logistics'}
    if 'хранен' in op or 'storage' in op: return {'Marketplace storage'}
    if any(x in op for x in ('приемк', 'приёмк', 'acceptance')): return {'Marketplace acceptance'}
    if any(x in op for x in ('штраф', 'penalty')): return {'Marketplace penalties'}
    if any(x in op for x in ('удержан', 'deduction')): return {'Marketplace deductions'}
    return set()


def reconcile_wb_generated_expenses(db,acc,rows):
    # Historical expenses are immutable. A changed classifier is not evidence
    # that a posted expense was false. Retain it for explicit accountant review.
    return 0


def project_account(db, user, acc, external_ids=None, date_from=None, date_to=None):
    query = select(MarketplaceRecord).where(MarketplaceRecord.account_id == acc.id,
        MarketplaceRecord.company_id == acc.company_id)
    if external_ids is not None:
        external_ids = list(dict.fromkeys(str(x) for x in external_ids if x))
        if not external_ids:
            rows = []
        else:
            rows = db.scalars(query.where(MarketplaceRecord.external_id.in_(external_ids))).all()
    else:
        rows = db.scalars(query).all()
    if date_from is not None or date_to is not None:
        filtered = []
        for row in rows:
            payload = row.payload or {}
            value = (payload.get('order_creation_date') or payload.get('completed_date')
                     or payload.get('saleDt') or payload.get('sale_dt') or payload.get('date')
                     or payload.get('created_at') or payload.get('operation_date'))
            try:
                day = _day_for_account(value, acc)
            except Pending:
                continue
            if date_from is not None and day < date_from: continue
            if date_to is not None and day > date_to: continue
            filtered.append(row)
        rows = filtered
    def sort_key(row):
        p = row.payload or {}
        if p.get('record_type') == 'product': return date.min, 0, row.id
        try:
            day = _day_for_account(p.get('saleDt') or p.get('sale_dt') or p.get('date') or p.get('order_creation_date') or p.get('delivered_at') or p.get('shipment_date') or p.get('created_at') or p.get('operation_date'), acc)
        except Pending:
            day = date.max
        # Prefer authoritative realization over preliminary sales for the same ID.
        return day, 0 if p.get('record_type') == 'realization' else 1, row.id
    rows.sort(key=sort_key)
    reconciled_expenses = reconcile_wb_generated_expenses(db, acc, rows) if acc.channel == 'Wildberries' else 0
    realized = {str(r.payload.get('srid')) for r in rows if r.payload.get('record_type') == 'realization'
                and (r.payload.get('sellerOperName') or r.payload.get('supplier_oper_name')) == 'Продажа'}
    projected = pending = 0
    reasons = {}
    # A sale may have been confirmed before historical purchase/FIFO data arrived.
    # Reprocessing closes only the missing COGS leg; it never duplicates revenue.
    pending_sales = db.scalars(select(Sale).where(
        Sale.company_id == acc.company_id, Sale.account_id == acc.id, Sale.cogs_pending.is_(True)
    ).order_by(Sale.date, Sale.id)).all()
    cogs_reconciled = 0
    for sale_obj in pending_sales:
        cogs_reconciled += int(f.settle_pending_sale_cogs(db, user, sale_obj))
    for row in rows:
        if row.source == 'wildberries' and row.payload.get('record_type') == 'sale' and str(row.payload.get('srid')) in realized and not str(row.payload.get('saleID') or '').startswith('R') and db.scalar(select(Sale.id).where(Sale.company_id==acc.company_id,Sale.account_id==acc.id,Sale.reference==reference(acc,'wb-sale:'+str(row.payload.get('srid'))))):
            row.status = 'received'
            row.stage_status='ignored_non_financial';row.reason_code='DUPLICATE_EVENT'
            row.payload = {**row.payload, '_qor_projection_reason': 'COVERED_BY_REALIZATION'}
            continue
        was_projected=row.status=="projected"
        ok, reason = project_record(db,user,acc,row)
        projected += int(ok and not was_projected)
        if row.status.startswith('pending') or row.stage_status=='pending_fifo':
            pending += 1
            reasons[reason] = reasons.get(reason, 0) + 1
    return {'projected': projected, 'pending_erp': pending, 'pending_reasons': reasons,
            'reconciled_false_expenses': reconciled_expenses, 'reconciled_pending_cogs': cogs_reconciled, 'total_records': len(rows),
            'total_projected': sum(r.status == 'projected' for r in rows)}


def reconcile_all_staged_marketplaces(db, user):
    """Idempotently project all stored marketplace staging records into ERP. No external calls."""
    results = []
    from .security import scope_query
    accounts = db.scalars(scope_query(select(Account),Account,user)).all()
    for acc in accounts:
        if acc.channel not in {"Wildberries", "Kaspi", "Ozon"}:
            continue
        result = project_account(db, user, acc)
        results.append({"account_id": acc.id, "channel": acc.channel, **result})
    return results
