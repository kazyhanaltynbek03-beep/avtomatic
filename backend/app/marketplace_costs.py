"""Cost overrides entered from marketplace product cards.

Dated seller costs fill only FIFO-pending marketplace sales. Existing inventory
FIFO costs remain authoritative and are never replaced by a manual estimate.
"""
from sqlalchemy import select
from .models import MarketplaceProductCost, MarketplaceProductMapping

CHANNELS = {"Kaspi", "Wildberries", "Ozon"}


def latest_cost(db, account_id, external_keys, as_of):
    keys = list(dict.fromkeys(str(k) for k in external_keys if k))
    if not keys:
        return None
    rows = db.scalars(
        select(MarketplaceProductCost)
        .where(
            MarketplaceProductCost.account_id == account_id,
            MarketplaceProductCost.external_key.in_(keys),
            MarketplaceProductCost.effective_from <= as_of,
        )
        .order_by(MarketplaceProductCost.effective_from.desc(), MarketplaceProductCost.id.desc())
    ).all()
    return rows[0] if rows else None


def resolve_cost_overrides(db, sales, returns, accounts):
    """Return effective COGS maps and unresolved sale IDs without mutating ledger rows."""
    sale_costs = {sale.id: sale.cogs for sale in sales}
    return_costs = {ret.id: ret.cogs for ret in returns}
    pending = {sale.id for sale in sales if getattr(sale, "cogs_pending", False)}
    pending_marketplace = [
        sale for sale in sales
        if sale.id in pending and accounts.get(sale.account_id)
        and accounts[sale.account_id].channel in CHANNELS
    ]
    if not pending_marketplace:
        return sale_costs, return_costs, pending

    account_ids = {sale.account_id for sale in pending_marketplace}
    product_ids = {sale.product_id for sale in pending_marketplace}
    mappings = db.scalars(
        select(MarketplaceProductMapping).where(
            MarketplaceProductMapping.account_id.in_(account_ids),
            MarketplaceProductMapping.product_id.in_(product_ids),
        )
    ).all()
    keys_by_pair = {}
    for mapping in mappings:
        keys_by_pair.setdefault((mapping.account_id, mapping.product_id), []).append(mapping.external_key)

    costs_by_pair = {}
    max_day = max(sale.date for sale in pending_marketplace)
    cost_rows = db.scalars(
        select(MarketplaceProductCost)
        .where(
            MarketplaceProductCost.account_id.in_(account_ids),
            MarketplaceProductCost.effective_from <= max_day,
        )
        .order_by(MarketplaceProductCost.effective_from, MarketplaceProductCost.id)
    ).all()
    for row in cost_rows:
        costs_by_pair.setdefault((row.account_id, row.external_key), []).append(row)

    override_by_sale = {}
    for sale in pending_marketplace:
        candidates = [
            row
            for key in keys_by_pair.get((sale.account_id, sale.product_id), [])
            for row in costs_by_pair.get((sale.account_id, key), [])
            if row.effective_from <= sale.date
        ]
        if not candidates:
            continue
        cost = max(candidates, key=lambda row: (row.effective_from, row.id))
        sale_costs[sale.id] = cost.unit_cost * sale.quantity
        pending.discard(sale.id)
        override_by_sale[sale.id] = cost.unit_cost

    sales_by_id = {sale.id: sale for sale in sales}
    for ret in returns:
        sale = sales_by_id.get(ret.sale_id)
        unit_cost = override_by_sale.get(ret.sale_id)
        if sale and unit_cost is not None and sale.cogs_pending:
            return_costs[ret.id] = unit_cost * ret.quantity
    return sale_costs, return_costs, pending
