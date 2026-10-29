"""Read-only marketplace return discovery kept outside the financial ledger."""
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from time import sleep
from urllib.parse import quote

from sqlalchemy import select, or_, func

from . import connectors
from .db import SessionLocal
from .models import (
    Account, MarketplaceRecord, MarketplaceReturn, MarketplaceReturnAudit,
    MarketplaceReturnSyncState, MarketplaceProductMapping, Product, User,
)


PAGE_SCAN = 250
KASPI_STATUS_BATCH = 25


def _day(value):
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            from zoneinfo import ZoneInfo
            n = int(value)
            if n > 10**12:
                n //= 1000
            return datetime.fromtimestamp(n, timezone.utc).astimezone(ZoneInfo("Asia/Almaty")).date()
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError, OverflowError):
        return None


def _first(obj, *keys):
    for key in keys:
        val = obj.get(key)
        if val not in (None, ""):
            return val
    return None


def _mapped_product(db, account_id, external_key, sku=""):
    keys = [external_key] if external_key else []
    if sku:
        keys += [sku, f"sku:{sku}"]
    mapping = db.scalar(select(MarketplaceProductMapping).where(
        MarketplaceProductMapping.account_id == account_id,
        MarketplaceProductMapping.external_key.in_(keys),
    )) if keys else None
    product = db.get(Product, mapping.product_id) if mapping else None
    media = (product.media or []) if product else []
    return (product.id if product else None, product.name if product else "",
            (media[0] if media and isinstance(media[0], str) else ""))


def _upsert(db, account, external_id, *, source, order_id="", product=None,
            product_name="", sku="", quantity=None, order_date=None, issue_date=None,
            request_date=None, financial_date=None, status="detected", raw=None):
    product_id, mapped_name, image = _mapped_product(db, account.id, product, sku)
    row = db.scalar(select(MarketplaceReturn).where(
        MarketplaceReturn.account_id == account.id,
        MarketplaceReturn.source == source,
        MarketplaceReturn.external_return_id == external_id,
    ))
    today = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Almaty")).date()
    if row is None:
        row = MarketplaceReturn(
            company_id=account.company_id, account_id=account.id, marketplace=account.channel,
            source=source, external_return_id=external_id, detected_date=today,
            financial_status="unconfirmed", accounted_status="unverified",
        )
        db.add(row)
    row.external_order_id = order_id or row.external_order_id or ""
    row.product_id = product_id or row.product_id
    row.product_name = product_name or mapped_name or row.product_name or ""
    row.sku = sku or row.sku or ""
    row.image_url = image or row.image_url or ""
    row.quantity = quantity if quantity is not None else row.quantity
    row.order_date = order_date or row.order_date
    row.issue_date = issue_date or row.issue_date
    row.request_date = request_date or row.request_date
    row.financial_return_date = financial_date or row.financial_return_date
    row.return_status = status
    row.raw_data = raw or row.raw_data or {}
    row.last_synced_at = datetime.now(timezone.utc)
    return row


def discover_from_staging(db, account, after_id=0):
    """Project only documented return signals from already cached records.

    It never calls the standard marketplace sync or the finance posting pipeline.
    Kaspi status observations deliberately do not invent the refund date/amount.
    """
    found = 0
    scanned = 0
    if account.channel == "Kaspi":
        query = select(MarketplaceRecord).where(
            MarketplaceRecord.account_id == account.id,
            MarketplaceRecord.source == "kaspi",
            MarketplaceRecord.payload["record_type"].as_string().in_(["order", "order_entry"]),
            MarketplaceRecord.id > after_id,
        ).order_by(MarketplaceRecord.id).limit(PAGE_SCAN)
        rows = list(db.scalars(query))
        scanned = len(rows)
        orders = {}
        for rec in rows:
            p = rec.payload or {}
            order_id = str(_first(p, "order_id") or "")
            status = str(_first(p, "order_status", "status") or "").upper()
            if not order_id or status not in {"RETURNED", "KASPI_DELIVERY_RETURN_REQUESTED"}:
                continue
            orders.setdefault(order_id, {"status": status, "entries": []})
            if p.get("record_type") == "order_entry":
                orders[order_id]["entries"].append(p)
        by_id = {str((r.payload or {}).get("order_id") or ""): r.payload or {}
                 for r in rows if (r.payload or {}).get("record_type") == "order"}
        for order_id, group in orders.items():
            order = by_id.get(order_id, {})
            entries = group["entries"]
            if not entries:
                entries = [{}]
            for index, entry in enumerate(entries):
                entry_id = str(_first(entry, "entry_id", "external_id") or index)
                status = "requested" if group["status"] == "KASPI_DELIVERY_RETURN_REQUESTED" else "returned"
                _upsert(db, account, f"kaspi-order:{order_id}:entry:{entry_id}",
                    source="kaspi_orders_api", order_id=str(_first(order, "code") or order_id),
                    product=_first(entry, "external_product_id"),
                    product_name=str(_first(entry, "product_name") or ""),
                    sku=str(_first(entry, "sku") or ""), quantity=_first(entry, "quantity"),
                    order_date=_day(_first(order, "creation_date", "creationDate", "order_creation_date") or _first(entry, "order_creation_date")),
                    issue_date=_day(_first(order, "completion_date", "completionDate") or _first(entry, "completed_date")),
                    status=status, raw={"order_status":group["status"], "order":order, "entry":entry})
                found += 1
    elif account.channel == "Wildberries":
        rows = list(db.scalars(select(MarketplaceRecord).where(
            MarketplaceRecord.account_id == account.id,
            MarketplaceRecord.source == "wildberries",
            MarketplaceRecord.payload["record_type"].as_string() == "realization",
            MarketplaceRecord.id > after_id,
        ).order_by(MarketplaceRecord.id).limit(PAGE_SCAN)))
        scanned = len(rows)
        for rec in rows:
            p = rec.payload or {}
            operation = " ".join(str(p.get(k) or "") for k in (
                "docTypeName", "doc_type_name", "supplierOperName", "supplier_oper_name",
                "sellerOperName", "seller_oper_name")).lower()
            if "возврат" not in operation and "return" not in operation:
                continue
            rrd = str(_first(p, "rrdId", "rrd_id") or rec.external_id)
            sku = str(_first(p, "sa_name", "vendorCode", "vendor_code", "supplierArticle") or "")
            nm = _first(p, "nmId", "nm_id")
            _upsert(db, account, f"wb-realization:{rrd}", source="wildberries_finance_report",
                order_id=str(_first(p, "srid", "srID", "orderId", "order_id") or ""),
                product=f"product:{nm}" if nm else None,
                product_name=str(_first(p, "productName", "subject") or ""), sku=sku,
                quantity=abs(int(_first(p, "quantity") or 0)) or None,
                order_date=_day(_first(p, "orderDt", "order_dt")),
                financial_date=_day(_first(p, "rrdDate", "rrd_date", "operation_date")),
                status="financial_operation_reported",
                raw={"rrdId":rrd, "operation":operation, "srid":_first(p,"srid","srID"),
                     "report_date":_first(p,"rrdDate","rrd_date"), "amount_unconfirmed":True})
            found += 1
    db.flush()
    return {"scanned": scanned, "found": found}


def match_inventory_return(db, row, account):
    """Return the unique, already-posted ERP return for an observation, if provable.

    This is a read-only bridge. Unmatched or ambiguous observations never affect
    stock; stock changes still go through the existing /api/returns status flow.
    """
    from .models import Sale, Return
    from .marketplace_pipeline import reference

    refs = set()
    raw = row.raw_data or {}
    if row.marketplace == "Wildberries":
        srid = raw.get("srid") or raw.get("srID")
        if srid:
            refs.add(reference(account, "wb-sale:" + str(srid)))
    elif row.marketplace == "Kaspi":
        order = raw.get("order") or {}
        entry = raw.get("entry") or {}
        order_keys = {
            str(value) for value in (
                order.get("id"), order.get("order_id"), entry.get("order_id"),
                entry.get("orderId"),
            ) if value not in (None, "")
        }
        if order_keys:
            records = db.scalars(select(MarketplaceRecord).where(
                MarketplaceRecord.account_id == account.id,
                MarketplaceRecord.source == "kaspi",
                MarketplaceRecord.payload["record_type"].as_string() == "order_entry",
                MarketplaceRecord.payload["order_id"].as_string().in_(list(order_keys)),
            )).all()
            refs.update(reference(account, record.external_id) for record in records)
        for value in (entry.get("entry_id"), entry.get("external_id")):
            if value not in (None, ""):
                refs.add(reference(account, str(value)))
    if not refs or row.product_id is None:
        return None

    sales = db.scalars(select(Sale).where(
        Sale.company_id == row.company_id,
        Sale.account_id == account.id,
        Sale.product_id == row.product_id,
        Sale.reference.in_(list(refs)),
    )).all()
    if len(sales) != 1:
        return None
    returns = db.scalars(select(Return).where(Return.sale_id == sales[0].id)).all()
    if row.quantity is not None:
        returns = [item for item in returns if item.quantity == row.quantity]
    if len(returns) != 1:
        return None
    ret = returns[0]
    return {
        "id": ret.id,
        "status": ret.inventory_status,
        "quantity": ret.quantity,
    }


def serialize_return(row, account, product=None):
    return {
        "id": row.id, "external_return_id": row.external_return_id, "product_id": row.product_id,
        "marketplace": row.marketplace, "account_id": row.account_id,
        "store": account.name if account else "Магазин", "order_id": row.external_order_id,
        "product_name": row.product_name or (product.name if product else "Товар не сопоставлен"),
        "sku": row.sku or (product.sku if product else ""),
        "image_url": row.image_url or ((product.media or [""])[0] if product and product.media else ""),
        "quantity": row.quantity, "order_date": row.order_date, "issue_date": row.issue_date,
        "request_date": row.request_date, "financial_return_date": row.financial_return_date,
        "detected_date": row.detected_date, "amount": row.amount,
        "currency": row.currency, "status": row.return_status,
        "financial_status": row.financial_status, "accounted_status": row.accounted_status,
        "reason": row.reason, "guarantee_case": row.guarantee_case,
        "defect": row.defect, "examination": row.examination,
        "seller_decision": row.seller_decision, "marketplace_decision": row.marketplace_decision,
        "item_condition": row.item_condition, "source": row.source,
        "financial_source": "financial_statement_import" if (row.raw_data or {}).get("financial_statement") else row.source,
        "last_synced_at": row.last_synced_at,
    }


def run_discovery(account_id):
    """Background, resumable scan of cached source records; no order/report sync."""
    with SessionLocal() as db:
        state = db.scalar(select(MarketplaceReturnSyncState).where(
            MarketplaceReturnSyncState.account_id == account_id))
        account = db.get(Account, account_id)
        if not account or account.channel not in {"Kaspi", "Wildberries"}:
            return
        if state is None:
            state = MarketplaceReturnSyncState(account_id=account_id, status="running")
            db.add(state)
        now = datetime.now(timezone.utc)
        started_at = state.started_at
        if started_at is not None and started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        if state.status == "running" and started_at and started_at > now - timedelta(minutes=20):
            return
        state.status = "running"
        state.error = ""
        state.started_at = now
        db.commit()
        try:
            if account.channel == "Kaspi":
                credentials = connectors.load_saved_credentials(db, account_id)
                token = str(credentials.get("token") or "").strip()
                if not token:
                    raise connectors.AccessRequired("Для проверки старых заказов Kaspi нужен действующий API-токен")
                api = connectors.KaspiConnector(account, credentials)
                headers = api._headers()
                after_id = int(state.cursor or 0)
                order_rows = list(db.scalars(select(MarketplaceRecord).where(
                    MarketplaceRecord.account_id == account_id,
                    MarketplaceRecord.source == "kaspi",
                    MarketplaceRecord.payload["record_type"].as_string() == "order",
                    MarketplaceRecord.id > after_id,
                ).order_by(MarketplaceRecord.id).limit(KASPI_STATUS_BATCH)))
                if not order_rows:
                    state.status = "done"
                    state.cursor = "0"
                    state.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    return
                order_ids = [str((row.payload or {}).get("order_id") or "") for row in order_rows]
                entry_rows = db.scalars(select(MarketplaceRecord).where(
                    MarketplaceRecord.account_id == account_id,
                    MarketplaceRecord.source == "kaspi",
                    MarketplaceRecord.payload["record_type"].as_string() == "order_entry",
                    MarketplaceRecord.payload["order_id"].as_string().in_(order_ids),
                )).all()
                entries_by_order = {}
                for entry in entry_rows:
                    entries_by_order.setdefault(str((entry.payload or {}).get("order_id") or ""), []).append(entry.payload or {})
                for index, cached in enumerate(order_rows):
                    cached_payload = cached.payload or {}
                    order_id = str(cached_payload.get("order_id") or "")
                    if not order_id:
                        state.cursor = str(cached.id)
                        state.scanned += 1
                        db.commit()
                        continue
                    if index:
                        sleep(1.0)
                    _, response = connectors._json_request(
                        f"{api.base_url}/{quote(order_id, safe='')}", headers, timeout=12, retries=1,
                    )
                    resource = response.get("data") or {}
                    attrs = resource.get("attributes") or {}
                    status = str(attrs.get("status") or "").upper()
                    if status in {"RETURNED", "KASPI_DELIVERY_RETURN_REQUESTED"}:
                        entries = entries_by_order.get(order_id) or [{}]
                        for line_no, line in enumerate(entries):
                            entry_id = str(line.get("entry_id") or line.get("external_id") or line_no)
                            _upsert(db, account, f"kaspi-order:{order_id}:entry:{entry_id}",
                                source="kaspi_orders_api", order_id=str(attrs.get("code") or cached_payload.get("code") or order_id),
                                product=line.get("external_product_id"), product_name=str(line.get("product_name") or ""),
                                sku=str(line.get("sku") or ""), quantity=line.get("quantity"),
                                order_date=_day(_first(attrs, "creationDate") or cached_payload.get("creation_date")),
                                issue_date=_day(_first(attrs, "completionDate") or cached_payload.get("completion_date")),
                                status="requested" if status == "KASPI_DELIVERY_RETURN_REQUESTED" else "returned",
                                raw={"order_status":status, "order_id":order_id, "order_code":attrs.get("code"),
                                     "returned_to_warehouse":attrs.get("returnedToWarehouse")})
                            state.found += 1
                    state.cursor = str(cached.id)
                    state.scanned += 1
                    db.commit()
                has_more = db.scalar(select(MarketplaceRecord.id).where(
                    MarketplaceRecord.account_id == account_id,
                    MarketplaceRecord.source == "kaspi",
                    MarketplaceRecord.payload["record_type"].as_string() == "order",
                    MarketplaceRecord.id > int(state.cursor or 0),
                ).limit(1)) is not None
                state.status = "partial" if has_more else "done"
                if not has_more:
                    state.cursor = "0"
                    state.completed_at = datetime.now(timezone.utc)
                db.commit()
                return
            while True:
                result = discover_from_staging(db, account, int(state.cursor or 0))
                rows = list(db.scalars(select(MarketplaceRecord.id).where(
                    MarketplaceRecord.account_id == account_id,
                    MarketplaceRecord.source == ("kaspi" if account.channel == "Kaspi" else "wildberries"),
                    MarketplaceRecord.payload["record_type"].as_string().in_(["order", "order_entry"])
                    if account.channel == "Kaspi" else MarketplaceRecord.payload["record_type"].as_string() == "realization",
                    MarketplaceRecord.id > int(state.cursor or 0),
                ).order_by(MarketplaceRecord.id).limit(PAGE_SCAN)))
                if not rows:
                    state.status = "done"
                    state.completed_at = datetime.now(timezone.utc)
                    state.cursor = ""
                    db.commit()
                    break
                state.cursor = str(rows[-1])
                state.scanned += result["scanned"]
                state.found += result["found"]
                db.commit()
                if len(rows) < PAGE_SCAN:
                    state.status = "done"
                    state.completed_at = datetime.now(timezone.utc)
                    state.cursor = ""
                    db.commit()
                    break
        except Exception as exc:
            db.rollback()
            state = db.scalar(select(MarketplaceReturnSyncState).where(
                MarketplaceReturnSyncState.account_id == account_id))
            if state:
                state.status = "partial" if state.cursor else "failed"
                state.error = str(getattr(exc, "detail", "") or str(exc))[:300] or f"Не удалось обработать данные ({type(exc).__name__}). Повторите проверку."
                db.commit()
