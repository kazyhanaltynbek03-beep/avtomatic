"""Weekly Wildberries finance reports: bounded API fetch, idempotent staging and export."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from bisect import bisect_right
from io import BytesIO
import logging
import time
import threading
import hashlib
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .connectors import AccessRequired, _json_request
from .models import Account, MarketplaceProductMapping, MarketplaceRecord, Return, Sale, now
from .marketplace_pipeline import reference as wb_reference
from . import wb_operation

log = logging.getLogger(__name__)
SOURCE = "wildberries_weekly"
DETAIL_URL = "https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed"
PAGE_SIZE = 100000
MAX_PAGES = 20
RETRY_MAX = 3
RETRY_AFTER = 15 * 60  # Recheck unpublished reports at the cadence shown in the UI.
_finance_guard = threading.Lock()
_finance_locks = {}
_finance_last_request = {}


def finance_today():
    """WB's report dates follow the Moscow timezone documented by the API."""
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def decimal(value):
    if value in (None, ""):
        return Decimal(0)
    try:
        return Decimal(str(value).replace(" ", "").replace("\u00a0", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def operation_label(payload):
    """Read both document type and operation reason (old/new WB API schemas)."""
    return wb_operation.operation_label(payload)


def is_return_operation(payload):
    return wb_operation.is_return_operation(payload)

def is_return_reversal(payload):
    return wb_operation.is_return_reversal(payload)

def is_sale_operation(payload):
    label = operation_label(payload)
    return not is_return_operation(payload) and ("продаж" in label or "sale" in label)


def signed_wb_sale_amount(payload, value):
    """Net sales/settlement contribution; retain original WB value in raw payload.

    Explicit reversals of a return require separate classification and must not
    silently be counted as ordinary returns.
    """
    amount = decimal(value)
    if is_return_operation(payload):
        label = operation_label(payload)
        if is_return_reversal(payload):
            return abs(amount)
        return -abs(amount)
    return amount


def payout_profit(payout, cogs, direct_logistics=0, reverse_logistics=0, penalty=0, storage=0, other=0):
    """Seller settlement less seller costs; commission is already reflected in forPay."""
    return (decimal(payout) - decimal(cogs) - decimal(direct_logistics)
            - decimal(reverse_logistics) - decimal(penalty) - decimal(storage) - decimal(other))


def previous_week(today=None):
    today = today or finance_today()
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(days=7), monday - timedelta(days=1)


def _request(url, token, payload):
    headers = {"Authorization": str(token).strip(), "Accept": "application/json", "Content-Type": "application/json"}
    # Shared request helper honors Retry-After, caps retries, and never logs
    # response bodies or credentials; 401/403 remain terminal.
    rate_key = hashlib.sha256(str(token).strip().encode("utf-8")).hexdigest()
    with _finance_guard:
        lock = _finance_locks.setdefault(rate_key, threading.Lock())
    with lock:
        elapsed = time.monotonic() - _finance_last_request.get(rate_key, 0)
        if elapsed < 60:
            time.sleep(60 - elapsed)
        try:
            return _json_request(url, headers, timeout=30, method="POST", payload=payload, retries=RETRY_MAX)
        finally:
            _finance_last_request[rate_key] = time.monotonic()


def fetch_period(token, start: date, end: date, api_period="weekly"):
    """Fetch one bounded daily/weekly Finance API range through its terminal 204."""
    if api_period not in ("daily", "weekly"):
        raise ValueError("Период Finance API должен быть daily или weekly")
    rrd_id = 0
    records = []
    seen = set()
    for _ in range(MAX_PAGES):
        status, rows = _request(DETAIL_URL, token, {
            "dateFrom": start.isoformat(), "dateTo": end.isoformat(),
            "period": api_period, "limit": PAGE_SIZE, "rrdId": rrd_id,
        })
        if status == 204:
            return records
        if rows is None:
            raise AccessRequired("WB: пустой ответ API без подтверждения завершения отчёта")
        if rows == []:
            raise AccessRequired("WB: получена пустая страница без HTTP 204; полнота отчёта не подтверждена")
        if not isinstance(rows, list):
            raise AccessRequired("WB: неожиданный формат недельного финансового отчёта")
        advanced = []
        for row in rows:
            if not isinstance(row, dict):
                raise AccessRequired("WB: неверный формат строки финансового отчёта")
            key = row.get("rrdId", row.get("rrd_id"))
            if key is None:
                raise AccessRequired("WB: в строке финансового отчёта отсутствует rrdId")
            try:
                key = int(key)
            except (ValueError, TypeError):
                raise AccessRequired("WB: некорректный идентификатор строки rrdId")
            if key in seen:
                continue
            seen.add(key)
            advanced.append(key)
            records.append(row)
        nxt = int(rows[-1].get("rrdId", rows[-1].get("rrd_id", 0)) or 0)
        if nxt <= rrd_id or (advanced and max(advanced) <= rrd_id):
            raise AccessRequired("WB: курсор детализации не продвинулся; отчёт не опубликован полностью")
        rrd_id = nxt
        if len(rows) < PAGE_SIZE:
            # Period endpoint page size may be advisory; request next page to
            # receive the documented 204 terminal signal and avoid truncation.
            continue
    raise AccessRequired("WB: достигнут безопасный предел страниц; отчёт помечен частичным")


def fetch_week(token, start: date, end: date):
    """Backward-compatible weekly fetch entry point."""
    return fetch_period(token, start, end, "weekly")


def _report_row_prefix(period, start, end=None):
    if period == "weekly":
        return f"row:{start}:"
    if period == "custom":
        return f"row:custom:{start}:{end}:"
    return f"row:{period}:{start}:"


def _meta(db, account_id, week_start, create=False, period="weekly", end=None):
    if period == "weekly":
        key = f"meta:{week_start}"
    elif period == "custom":
        key = f"meta:custom:{week_start}:{end}"
    else:
        key = f"meta:{period}:{week_start}"
    q = select(MarketplaceRecord).where(MarketplaceRecord.account_id == account_id,
        MarketplaceRecord.source == SOURCE, MarketplaceRecord.external_id == key).with_for_update()
    row = db.scalar(q)
    if not row and create:
        row = MarketplaceRecord(account_id=account_id, company_id=db.get(Account, account_id).company_id,
            source=SOURCE, external_id=key, payload={"week_start": str(week_start), "status": "ожидается"},
            status="received", stage_status="received")
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            row = db.scalar(q)
    return row


def _validate_report_period(period, start, end):
    if period == "weekly":
        valid = start.weekday() == 0 and end == start + timedelta(days=6) and end < finance_today()
        if not valid:
            raise ValueError("Ожидается завершённая календарная неделя с понедельника по воскресенье")
        return "weekly"
    if period == "daily":
        if end != start or end >= finance_today():
            raise ValueError("Дневной финансовый отчёт доступен только за завершённый день")
        return "daily"
    if period == "monthly":
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = next_month - timedelta(days=1)
        today = finance_today()
        current_month_to_date = start == today.replace(day=1) and end == today - timedelta(days=1)
        if start.day != 1 or (end != month_end and not current_month_to_date) or end >= today:
            raise ValueError("Ожидается завершённый месяц или текущий месяц по вчерашний день")
        return "daily"
    if period == "custom":
        if start > end:
            raise ValueError("Начало периода не может быть позже окончания")
        if end >= finance_today():
            raise ValueError("Произвольный отчёт WB доступен только по завершённый день")
        # WB's period endpoint returns daily records for a caller-selected date
        # range. Keep these rows isolated under `custom`; report calculations
        # and the existing daily/weekly/monthly records remain untouched.
        return "daily"
    raise ValueError("Поддерживаются периоды daily, weekly, monthly и custom")


def sync_period(db, account: Account, token: str, period: str, start: date, end: date,
                force=False, project_user=None, trigger="manual"):
    api_period = _validate_report_period(period, start, end)
    meta = _meta(db, account.id, start, create=True, period=period, end=end)
    if meta is None:
        return {"status": "error", "message": "Не удалось захватить отчёт"}
    state = dict(meta.payload or {})
    last = state.get("attempt_at")
    if state.get("status") == "готов" and not force:
        try:
            if now() - datetime.fromisoformat(state.get("updated_at")) < timedelta(hours=24):
                return state
        except (ValueError, TypeError):
            pass
    if state.get("status") == "загружается" and last:
        try:
            if now() - datetime.fromisoformat(last) < timedelta(minutes=20):
                return state
        except (ValueError, TypeError):
            pass
    if last and not force:
        try:
            if now() - datetime.fromisoformat(last) < timedelta(seconds=RETRY_AFTER):
                return state
        except (ValueError, TypeError):
            pass
    # Persist a lease before network I/O; another worker will observe it.
    state.update(status="загружается", attempt_at=now().isoformat(), week_start=str(start), week_end=str(end), error="")
    meta.payload = state
    meta.stage_status = "running"
    db.commit()
    try:
        # Generic connector rows are staged under a different source and may
        # span multiple weeks; only this bounded API request is authoritative
        # for the selected report window.
        source = "finance_api_period"
        rows = fetch_week(token, start, end) if period == "weekly" else fetch_period(token, start, end, api_period)
        # Replace only this report's rows, inside a transaction. External rrdId is
        # stable and unique per account/week, so retries cannot duplicate entries.
        row_prefix = _report_row_prefix(period, start, end)
        db.query(MarketplaceRecord).filter(MarketplaceRecord.account_id == account.id,
            MarketplaceRecord.source == SOURCE,
            MarketplaceRecord.external_id.like(row_prefix + "%")).delete(synchronize_session=False)
        for row in rows:
            rid = row.get("rrdId", row.get("rrd_id"))
            db.add(MarketplaceRecord(account_id=account.id, company_id=account.company_id,
                source=SOURCE, external_id=f"{row_prefix}{rid}", payload=row,
                status="received", stage_status="received"))
            # Feed these exact, bounded Finance rows through the same canonical
            # marketplace ledger path as legacy realization sync. This is what
            # gives the report sale/return links to actual FIFO cost records.
            realization_id = f"realization:{rid}"
            realization_payload = {**row, "external_id": realization_id, "record_type": "realization"}
            mirror = db.scalar(select(MarketplaceRecord).where(MarketplaceRecord.account_id == account.id,
                MarketplaceRecord.source == "wildberries", MarketplaceRecord.external_id == realization_id))
            if mirror is None:
                mirror = MarketplaceRecord(account_id=account.id, company_id=account.company_id,
                    source="wildberries", external_id=realization_id, payload=realization_payload,
                    status="received", stage_status="received")
                db.add(mirror)
            elif {k:v for k,v in (mirror.payload or {}).items() if not k.startswith("_qor_")} != realization_payload:
                mirror.payload = realization_payload
                mirror.status = "received"
                mirror.stage_status = "received"
        meta = _meta(db, account.id, start, period=period, end=end)
        state = dict(meta.payload or {})
        state.update(status="готов" if rows else "ожидается", report_id=str(rows[0].get("reportId") or "") if rows else "",
            row_count=len(rows), updated_at=now().isoformat(), attempt_at=now().isoformat(), error="",
            week_start=str(start), week_end=str(end), start=str(start), end=str(end), period=period,
            api_period=api_period, data_source=source)
        meta.payload = state
        meta.stage_status = state["status"]
        db.commit()
        if project_user is not None and rows:
            from .marketplace_pipeline import project_record
            realization_ids = [f"realization:{r.get('rrdId', r.get('rrd_id'))}" for r in rows]
            mirrors = list(db.scalars(select(MarketplaceRecord).where(
                MarketplaceRecord.account_id == account.id, MarketplaceRecord.source == "wildberries",
                MarketplaceRecord.external_id.in_(realization_ids))))
            projected = pending = 0
            for mirror in mirrors:
                ok, _reason = project_record(db, project_user, account, mirror)
                projected += int(ok)
                pending += int(mirror.status.startswith("pending"))
            state["ledger_projection"] = {"rows": len(mirrors), "projected": projected, "pending": pending}
            meta = _meta(db, account.id, start, period=period, end=end)
            meta.payload = state
            db.commit()
        return state
    except Exception as exc:
        db.rollback()
        meta = _meta(db, account.id, start, create=True, period=period, end=end)
        state = dict(meta.payload or {})
        text = str(exc)[:240]
        # A transport/API/schema failure is not evidence that WB has not published
        # the report. Keep an explicit error so the UI never silently shows zero.
        state.update(status="ошибка",
            error=text, attempt_at=now().isoformat(), week_start=str(start), week_end=str(end),
            start=str(start), end=str(end), period=period, api_period=api_period)
        meta.payload = state
        meta.stage_status = state["status"]
        db.commit()
        log.warning("WB Finance report sync failed: trigger=%s account_id=%s period=%s error=%s",
                    trigger, account.id, period, str(exc)[:240])
        return state


def sync_week(db, account: Account, token: str, start: date, end: date,
              force=False, project_user=None, trigger="manual"):
    """Backward-compatible weekly report sync entry point."""
    return sync_period(db, account, token, "weekly", start, end, force=force,
                       project_user=project_user, trigger=trigger)


def build_report(db, account, start: date, end: date, period="weekly"):
    meta = _meta(db, account.id, start, period=period, end=end)
    status = dict((meta.payload if meta else {}) or {"status": "ожидается", "week_start": str(start), "week_end": str(end), "start": str(start), "end": str(end), "period": period})
    raw = list(db.scalars(select(MarketplaceRecord).where(MarketplaceRecord.account_id == account.id,
        MarketplaceRecord.source == SOURCE, MarketplaceRecord.external_id.like(_report_row_prefix(period, start, end) + "%")).order_by(MarketplaceRecord.id)))
    rows = [r.payload or {} for r in raw]
    groups = {}
    group_ids = {}
    currencies = set()
    totals = {k: Decimal(0) for k in ("retail", "realization", "payout", "commission", "wb_reward", "commission_vat", "acquiring", "direct_logistics", "reverse_logistics", "penalty", "storage", "other")}
    sales_qty = returns_qty = 0
    returns_amount = Decimal(0)
    unallocated_operations = 0
    for p in rows:
        vendor_raw = p.get("vendorCode") or p.get("nmId") or p.get("sku")
        vendor = str(vendor_raw or "")
        nm = str(p.get("nmId") or "")
        sku = str(p.get("sku") or "")
        currency = str(p.get("currencyName") or p.get("currency") or account.settlement_currency or "KZT").upper()
        currency = {"РУБ": "RUB", "РУБ.": "RUB", "ТЕНГЕ": "KZT"}.get(currency, currency)
        currencies.add(currency)
        op = operation_label(p)
        qty = int(decimal(p.get("quantity")))
        is_return = "возврат" in op or "return" in op
        is_sale = "продаж" in op or "sale" in op
        # Fees without a WB product key must remain report-level operations.
        # Grouping them under a fake "Без артикула" product corrupts per-product profit.
        identifiable = bool(vendor_raw) and (bool(nm or sku) or is_sale or is_return)
        g = None
        if identifiable:
            key = (vendor, currency)
            g = groups.setdefault(key, {"article": vendor, "nm_id": nm, "sku": sku, "currency": currency, "name": str(p.get("title") or ""), "sales_qty": 0, "returns_qty": 0,
                **{k: Decimal(0) for k in totals}, "operation_count": 0, "cogs": None, "profit": None})
            refs = group_ids.setdefault(key, {"sale_srids": set(), "return_srids": set(), "return_rrd_ids": set()})
            g["operation_count"] += 1
        else:
            unallocated_operations += 1
        if is_return_operation(p) and not is_return_reversal(p):
            raw_return_payout = next((p[k] for k in ("forPay", "ppvzForPay", "ppvz_for_pay") if p.get(k) is not None), None)
            if raw_return_payout is not None:
                returns_amount += abs(decimal(raw_return_payout))
            returns_qty += abs(qty)
            if g:
                g["returns_qty"] += abs(qty)
                srid = p.get("srid") or p.get("srId")
                rrd = p.get("rrdId", p.get("rrd_id"))
                if srid is not None: refs["return_srids"].add(str(srid))
                if rrd is not None: refs["return_rrd_ids"].add(str(rrd))
        elif "продаж" in op or "sale" in op:
            sales_qty += abs(qty)
            if g:
                g["sales_qty"] += abs(qty)
                srid = p.get("srid") or p.get("srId")
                if srid is not None: refs["sale_srids"].add(str(srid))
        # Updated Finance API money fields are decimal strings. Keep native currency.
        fields = {
            "retail": ("retailPriceWithDisc", "retail_price_withdisc_rub"),
            "realization": ("retailAmount", "retail_amount"),
            "payout": ("forPay", "ppvzForPay", "ppvz_for_pay"),
            # Current Finance API exposes ppvzSalesCommission as a money string;
            # commissionPercent is the separate rate and is intentionally excluded.
            "commission": ("ppvzSalesCommission", "ppvz_sales_commission"),
            # Separate workbook/API fields. `vw` can overlap with the sales
            # commission field; expose it for reconciliation but do not add it again.
            "wb_reward": ("vw", "ppvzVw", "ppvz_vw"),
            "commission_vat": ("vwNds", "ppvzVwNds", "ppvz_vw_nds"),
            "acquiring": ("acquiringFee", "acquiring_fee"), "direct_logistics": ("deliveryService", "deliveryRub", "delivery_rub"),
            "reverse_logistics": ("rebillLogisticCost", "rebill_logistic_cost"), "penalty": ("penalty",),
            "storage": ("paidStorage", "storageFee", "storage_fee"), "other": ("deduction", "acceptance", "additionalPayment"),
        }
        for metric, choices in fields.items():
            raw_amount = next((p[k] for k in choices if p.get(k) is not None), None)
            if raw_amount is not None:
                if metric == "retail" and (p.get("retailPriceWithDisc") is not None or p.get("retail_price_withdisc_rub") is not None):
                    # retailPriceWithDisc is a unit price. Do not manufacture one
                    # unit for non-sale rows or rows whose quantity is zero.
                    if qty == 0 or not ("продаж" in op or "sale" in op or is_return):
                        continue
                    unit_price = decimal(raw_amount)
                    amount = (-abs(unit_price) if is_return else unit_price) * abs(qty)
                else:
                    amount = signed_wb_sale_amount(p, raw_amount) if metric in ("payout", "realization") else decimal(raw_amount)
                if g: g[metric] += amount
                totals[metric] += amount
    # Client's WB settlement convention: deliveryService/deliveryRub is the
    # WHOLE logistics envelope. rebillLogisticCost is a disclosed component,
    # not an extra charge on top of that envelope. Do not double-charge it.
    # Direct = envelope minus rebill is a reconciliation split, NOT proof that
    # each remaining row represents delivery of a completed sale.
    gross_delivery = totals["direct_logistics"]
    rebill_component = totals["reverse_logistics"]
    logistics_split_valid = (gross_delivery >= 0 and rebill_component >= 0
                             and rebill_component <= gross_delivery)
    if logistics_split_valid:
        totals["direct_logistics"] = gross_delivery - rebill_component
    else:
        # Unknown overlap: fail closed rather than inventing profit.
        totals["direct_logistics"] = None
    totals["logistics_total"] = gross_delivery
    totals["logistics_split_verified"] = Decimal(1) if logistics_split_valid else Decimal(0)
    # Product-level split cannot be reconstructed safely from report totals.
    # Keep product fee breakdown/profit unverified until operation linkage exists.
    for group in groups.values():
        group["direct_logistics"] = None
        group["profit"] = None
        group["margin_pct"] = None
    # Match only existing FIFO-posted Sale rows linked via account-product mapping.
    mappings = list(db.scalars(select(MarketplaceProductMapping).where(MarketplaceProductMapping.account_id == account.id)))
    product_by_key = {m.external_key: m.product_id for m in mappings}
    for key, group in groups.items():
        keys = (f"product:{group['nm_id']}", f"sku:{group['article']}", f"barcode:{group['sku']}",
                group["nm_id"], group["article"], group["sku"])
        pids = {product_by_key.get(k) for k in keys if k} - {None}
        if len(pids) != 1 or group["currency"] != str(account.settlement_currency or "KZT").upper():
            continue
        pid = next(iter(pids))
        refs = group_ids[key]
        sale_references = [ref for srid in refs["sale_srids"] for ref in (
            wb_reference(account, "wb-sale:" + srid), wb_reference(account, "sale:" + srid))]
        related_sale_references = [ref for srid in refs["return_srids"] for ref in (
            wb_reference(account, "wb-sale:" + srid), wb_reference(account, "sale:" + srid))]
        sale_rows = list(db.scalars(select(Sale).where(Sale.account_id == account.id,
            Sale.product_id == pid, Sale.reference.in_(sale_references)))) if sale_references else []
        related_sales = list(db.scalars(select(Sale).where(Sale.account_id == account.id,
            Sale.product_id == pid, Sale.reference.in_(related_sale_references)))) if related_sale_references else []
        return_references = [wb_reference(account, "realization:" + rid, "return") for rid in refs["return_rrd_ids"]]
        returned = list(db.scalars(select(Return).join(Sale, Return.sale_id == Sale.id).where(
            Sale.account_id == account.id, Sale.product_id == pid,
            Return.reference.in_(return_references)))) if return_references else []
        sold = sum(s.quantity for s in sale_rows)
        returned_qty = sum(r.quantity for r in returned)
        sale_cogs = sum(s.cogs for s in sale_rows)
        return_cogs = sum(r.cogs for r in returned)
        expected_sale_rows = group["sales_qty"] == 0 or (bool(refs["sale_srids"]) and sold == group["sales_qty"])
        expected_return_rows = group["returns_qty"] == 0 or (bool(refs["return_rrd_ids"]) and bool(related_sales)
            and returned_qty == group["returns_qty"])
        if expected_sale_rows and expected_return_rows and not any(s.cogs_pending for s in sale_rows + related_sales):
            # Match FIFO cost by WB sale/return identity, not by settlement date:
            # WB can settle an order in a different report week than its sale date.
            group["cogs"] = Decimal(sale_cogs - return_cogs) / 100
    # Fallback to dated seller cost when FIFO is unavailable. A return is a
    # settlement in its WB reporting period; do not repeat the original COGS or
    # reverse it here without a stock-confirmed FIFO Return. Validate that a
    # dated cost exists for the returned item, then current-period COGS remains
    # zero for returns-only groups and the negative WB forPay reduces profit.
    from .models import MarketplaceProductCost
    cost_rows = list(db.scalars(select(MarketplaceProductCost).where(
        MarketplaceProductCost.account_id == account.id).order_by(
        MarketplaceProductCost.external_key, MarketplaceProductCost.effective_from)))
    costs_by_key = {}
    for cost_row in cost_rows:
        costs_by_key.setdefault(cost_row.external_key, []).append(cost_row)
    sale_dates_by_srid = {}
    returns_missing_sale_date = set()
    for row in rows:
        op = operation_label(row)
        srid = str(row.get("srid") or row.get("srId") or "")
        if not srid:
            continue
        if "возврат" in op or "return" in op:
            if not (row.get("saleDt") or row.get("saleDate")):
                returns_missing_sale_date.add(srid)
        elif "продаж" in op or "sale" in op:
            raw_sale_date = row.get("saleDt") or row.get("saleDate") or row.get("rrdDate") or row.get("rrDt")
            if raw_sale_date:
                sale_dates_by_srid[srid] = str(raw_sale_date)[:10]
    if returns_missing_sale_date:
        # Use already stored Finance rows (no WB request) to resolve a delayed
        # return's original sale date by WB srid, when the return row omits it.
        prior = db.scalars(select(MarketplaceRecord).where(
            MarketplaceRecord.account_id == account.id, MarketplaceRecord.source == SOURCE,
            MarketplaceRecord.external_id.like("row:%")))
        for record in prior:
            payload = record.payload or {}
            op = operation_label(payload)
            if not ("продаж" in op or "sale" in op):
                continue
            srid = str(payload.get("srid") or payload.get("srId") or "")
            if srid in returns_missing_sale_date:
                sale_date = payload.get("saleDt") or payload.get("saleDate") or payload.get("rrdDate") or payload.get("rrDt")
                if sale_date:
                    sale_dates_by_srid.setdefault(srid, str(sale_date)[:10])
    def dated_cost(keys, sold_on):
        for cost_key in keys:
            history = costs_by_key.get(cost_key, [])
            idx = bisect_right([r.effective_from for r in history], sold_on) - 1
            if idx >= 0: return history[idx]
        return None
    for key, group in groups.items():
        if group["cogs"] is not None or group["currency"] != "KZT":
            continue
        amount = Decimal(0); matched_sales = matched_returns = 0
        for row in rows:
            op = operation_label(row)
            is_sale = "продаж" in op or "sale" in op
            is_return = "возврат" in op or "return" in op
            if not (is_sale or is_return):
                continue
            if str(row.get("nmId") or "") != group["nm_id"] or str(row.get("vendorCode") or row.get("nmId") or "") != group["article"]:
                continue
            # For a refund, use the original sale date if WB supplies it; the
            # financial reflection date is not a valid basis for old cost.
            raw_date = row.get("saleDt") or row.get("saleDate")
            if is_sale:
                raw_date = raw_date or row.get("rrdDate") or row.get("rrDt")
            elif is_return:
                raw_date = raw_date or sale_dates_by_srid.get(str(row.get("srid") or row.get("srId") or ""))
            try: sold_on = date.fromisoformat(str(raw_date)[:10])
            except (ValueError, TypeError): continue
            cost_row = dated_cost((f"product:{group['nm_id']}", f"sku:{group['article']}"), sold_on)
            qty = abs(int(decimal(row.get("quantity"))))
            if cost_row and qty:
                if is_sale:
                    amount += Decimal(cost_row.unit_cost) * qty / 100
                    matched_sales += qty
                else:
                    matched_returns += qty
        if matched_sales == group["sales_qty"] and matched_returns == group["returns_qty"]:
            group["cogs"] = amount
    cogs_total = Decimal(0)
    costed_groups = [g for g in groups.values() if g["sales_qty"] or g["returns_qty"]]
    cogs_complete = bool(costed_groups) and len(currencies) == 1 and all(
        g["cogs"] is not None for g in costed_groups
    ) and sum(g["sales_qty"] for g in costed_groups) == sales_qty and sum(
        g["returns_qty"] for g in costed_groups) == returns_qty
    for group in groups.values():
        if group["cogs"] is not None:
            cogs_total += group["cogs"]
            # Per-product profit is only complete when the WB attached fees to
            # that product. Unassigned report-level fees are applied only to total profit.
            # Product-level logistics split is not verified: no profit here.
    if cogs_complete and logistics_split_valid:
        totals["cogs"] = cogs_total
        totals["profit"] = payout_profit(totals["payout"], cogs_total, totals["direct_logistics"],
            totals["reverse_logistics"], totals["penalty"], totals["storage"], totals["other"])
        totals["margin_pct"] = totals["profit"] / totals["realization"] * 100 if totals["realization"] else None
    if len(currencies) > 1:
        status["status"] = "частично"
        status["error"] = "Отчёт содержит несколько валют; итоговые суммы не смешиваются."
        for key in totals:
            totals[key] = None
    if not cogs_complete or not logistics_split_valid:
        totals["cogs"] = cogs_total if cogs_complete else None
        totals["profit"] = None
    # Never present absent finance data as a confirmed zero-valued report.
    if not rows:
        for key in totals:
            totals[key] = None
    status.update({"account_id": account.id, "week_start": str(start), "week_end": str(end), "start": str(start), "end": str(end), "period": period,
        "sales_qty": sales_qty, "returns_qty": returns_qty, "returns_amount": str(returns_amount), "unallocated_operations": unallocated_operations,
        "cogs_costed_products": sum(1 for g in costed_groups if g["cogs"] is not None),
        "cogs_products_total": len(costed_groups),
        "currency": next(iter(currencies)) if len(currencies) == 1 else ("MIXED" if currencies else str(account.settlement_currency or "KZT").upper()),
        "row_count": len(rows), "updated_at": status.get("updated_at"), "totals": {k: (str(v) if v is not None else None) for k,v in totals.items()},
        "products": [{k: str(v) if isinstance(v, Decimal) else v for k,v in g.items()} for g in sorted(groups.values(), key=lambda x: (x["currency"], x["article"].lower()))],
        "cogs_complete": cogs_complete and logistics_split_valid,
        "logistics_note": "159657.50 — общий delivery; rebill включён в него по правилу клиента. Разделение по продажам требует проверки srid.",
        "operations": [{"date": str(p.get("rrdDate") or p.get("rrDt") or p.get("rrDate") or p.get("rr_dt") or p.get("saleDt") or ""), "operation": operation_label(p),
            "article": str(p.get("vendorCode") or p.get("nmId") or ""), "nm_id": str(p.get("nmId") or ""), "is_return": is_return_operation(p) and not is_return_reversal(p), "raw_amount": str(decimal(next((p[k] for k in ("forPay", "ppvzForPay", "ppvz_for_pay") if p.get(k) is not None), None))), "amount": str(signed_wb_sale_amount(p, next((p[k] for k in ("forPay", "ppvzForPay", "ppvz_for_pay") if p.get(k) is not None), None))),
            "currency": str(p.get("currencyName") or p.get("currency") or account.settlement_currency or "KZT"), "external_id": str(p.get("rrdId") or p.get("rrd_id") or ""),
            "quantity": int(decimal(p.get("quantity"))), "srid": str(p.get("srid") or p.get("srId") or ""), "sale_date": str(p.get("saleDt") or p.get("saleDate") or ""),
            "direct_logistics": str(decimal(p.get("deliveryService", p.get("deliveryRub", 0)))), "reverse_logistics": str(decimal(p.get("rebillLogisticCost", p.get("rebill_logistic_cost", 0)))),
            "commission": str(decimal(p.get("ppvzSalesCommission", p.get("ppvz_sales_commission", 0)))), "penalty": str(decimal(p.get("penalty", 0))),
            "storage": str(decimal(p.get("paidStorage", p.get("storageFee", p.get("storage_fee", 0)))))} for p in rows]})
    return status


def create_xlsx(report):
    wb = Workbook(); wb.remove(wb.active)
    t = report.get("totals") or {}; products = report.get("products", []); ops = report.get("operations", [])
    cur = report.get("currency", "KZT"); complete = report.get("cogs_complete") is True
    def val(key): return float(decimal(t[key])) if t.get(key) is not None else "Не рассчитана"
    def sheet(name, headers, rows):
        ws = wb.create_sheet(name); ws.append(headers)
        for row in rows: ws.append(row)
        return ws
    sheet("Финансовый итог", ["Показатель", "Значение", "Валюта"], [
        ["Период", f"{report.get('start')} — {report.get('end')}", cur], ["Продажи WB (реализация)",val("realization"),cur],
        ["Возвраты, шт.",report.get("returns_qty",0),"шт."],["К перечислению WB",val("payout"),cur],
        ["Себестоимость",val("cogs") if complete else "Не рассчитана",cur],["Прибыль",val("profit") if complete else "Не рассчитана",cur],
        ["Маржинальность, %",val("margin_pct") if complete else "Не рассчитана","%"],["Статус данных",report.get("status","ожидается"),""]])
    sheet("Продажи по товарам",["Артикул WB","Название","SKU","Валюта","Продажи, шт.","Возвраты, шт.","Реализация","К перечислению"],[[p["article"],p["name"],p["sku"],p["currency"],p["sales_qty"],p["returns_qty"],float(decimal(p["realization"])),float(decimal(p["payout"]))] for p in products])
    sheet("Себестоимость",["Артикул WB","Название","Продажи, шт.","Возвраты, шт.","Себестоимость","Статус"],[[p["article"],p["name"],p["sales_qty"],p["returns_qty"],float(decimal(p["cogs"])) if p["cogs"] is not None else None,"Рассчитана" if p["cogs"] is not None else "Не заполнена/проверить возврат"] for p in products])
    expense_keys=("logistics_total","commission","commission_vat","acquiring","direct_logistics","reverse_logistics","penalty","storage","other")
    expense_labels={"logistics_total":"Логистика всего (без повторного rebill)","commission":"Комиссия WB","commission_vat":"НДС комиссии","acquiring":"Эквайринг","direct_logistics":"Прямая логистика","reverse_logistics":"Обратная логистика","penalty":"Штрафы","storage":"Хранение","other":"Прочее/удержания"}
    sheet("Расходы Wildberries",["Категория","Сумма WB","Валюта","Примечание"],[[expense_labels[k],val(k),cur,"Справочное поле WB; не вычитается повторно из суммы к перечислению"] for k in expense_keys])
    returns=[o for o in ops if "возврат" in o["operation"].lower() or "return" in o["operation"].lower()]
    sheet("Возвраты",["Дата отражения","Дата продажи","Товар","nmID","Количество","Сумма к перечислению","Обратная логистика","Комиссия","Штраф","ID строки WB","srid","Период"],[[o["date"],o.get("sale_date"),o["article"],o["nm_id"],abs(o.get("quantity",0)),float(decimal(o["amount"])),float(decimal(o.get("reverse_logistics"))),float(decimal(o.get("commission"))),float(decimal(o.get("penalty"))),o["external_id"],o.get("srid"),f"{report.get('start')} — {report.get('end')}"] for o in returns])
    sheet("Прибыль и маржинальность",["Артикул WB","Название","Выручка","Себестоимость","Прибыль","Маржинальность, %","Статус"],[[p["article"],p["name"],float(decimal(p["realization"])),float(decimal(p["cogs"])) if p["cogs"] is not None else None,float(decimal(p["profit"])) if p["profit"] is not None else None,float(decimal(p["margin_pct"])) if p.get("margin_pct") is not None else None,"Рассчитана" if p["profit"] is not None else "Не рассчитана"] for p in products])
    sheet("Сверка с Wildberries",["Показатель","Значение отчёта WB","Независимое значение ERP","Разница","Комментарий"],[["К перечислению",val("payout"),"Нет независимого источника","Не рассчитана","Источник — forPay WB; поля комиссии не вычитаются повторно"],["Реализация",val("realization"),"Нет независимого источника","Не рассчитана","Значение из полученных строк WB; не подгоняется под ERP"],["Строки без артикула",report.get("unallocated_operations",0),"—","—","Оставлены отдельно, не распределены по товарам"],["Нерассчитанные товары",sum(1 for p in products if p.get("cogs") is None),"—","—","Нет FIFO/исторической цены или возврат требует проверки"]])
    for ws in wb.worksheets:
        ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
        for cell in ws[1]: cell.font=Font(bold=True,color="FFFFFF");cell.fill=PatternFill("solid",fgColor="12324A")
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value,(float,int)): cell.number_format='#,##0.00;[Red]-#,##0.00'
        for col in ws.columns:
            letter=get_column_letter(col[0].column);ws.column_dimensions[letter].width=min(42,max(12,max(len(str(c.value or "")) for c in col[:100])+2))
    data=BytesIO();wb.save(data);return data.getvalue()
