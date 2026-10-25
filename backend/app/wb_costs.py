"""Seller-scoped Wildberries product cost history and catalogue helpers."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import select

from .models import Account, MarketplaceProductCost, MarketplaceProductMapping, Product

TIYN = Decimal("100")


def cost_external_key(nm_id="", seller_article="", barcode=""):
    """Prefer stable WB nmID; use seller SKU/barcode only when it is absent."""
    if nm_id not in (None, ""):
        return "product:" + str(nm_id).strip()
    if seller_article not in (None, ""):
        return "sku:" + str(seller_article).strip()
    if barcode not in (None, ""):
        return "barcode:" + str(barcode).strip()
    return ""


def money_to_tiyn(value):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Укажите себестоимость числом, максимум 2 знака после запятой")
    if amount <= 0 or amount > Decimal("1000000000000"):
        raise ValueError("Себестоимость должна быть больше нуля и не превышать 1 000 000 000 000 ₸")
    return int(amount * TIYN)


def latest_cost(db, account_id: int, external_key: str, as_of: date):
    return db.scalar(select(MarketplaceProductCost).where(
        MarketplaceProductCost.account_id == account_id,
        MarketplaceProductCost.external_key == external_key,
        MarketplaceProductCost.effective_from <= as_of,
    ).order_by(MarketplaceProductCost.effective_from.desc(), MarketplaceProductCost.id.desc()).limit(1))


def cost_at(db, account_id: int, keys, as_of: date):
    """Return the newest matching cost. Keys must already be ordered by stability."""
    for key in keys:
        if key:
            row = latest_cost(db, account_id, key, as_of)
            if row:
                return row
    return None


def account_for_cost(db, user, account_id):
    account = db.get(Account, account_id)
    if not account or account.channel != "Wildberries":
        raise HTTPException(404, "Кабинет Wildberries не найден")
    from .security import scope
    scope(user, account.company_id)
    return account


def catalogue_products(db, account: Account):
    """Use already-mapped ERP products; do not duplicate WB's product catalogue."""
    mappings = list(db.scalars(select(MarketplaceProductMapping).where(
        MarketplaceProductMapping.account_id == account.id,
        MarketplaceProductMapping.company_id == account.company_id,
    ).order_by(MarketplaceProductMapping.id)))
    by_product = {}
    by_key = {}
    for mapping in mappings:
        by_product.setdefault(mapping.product_id, []).append(mapping.external_key)
        by_key[mapping.external_key] = mapping.product_id
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(by_product)))} if by_product else {}
    out = []
    for product_id, keys in by_product.items():
        product = products.get(product_id)
        if not product:
            continue
        nm_keys = [k for k in keys if k.startswith("product:")]
        sku_keys = [k for k in keys if k.startswith("sku:")]
        barcode_keys = [k for k in keys if k.startswith("barcode:")]
        stable = (nm_keys or sku_keys or barcode_keys or keys)[0]
        nm_id = stable.split(":", 1)[1] if stable.startswith("product:") else ""
        seller_article = stable.split(":", 1)[1] if stable.startswith("sku:") else product.article or product.sku
        barcode = barcode_keys[0].split(":", 1)[1] if barcode_keys else ""
        out.append({
            "external_key": stable, "nm_id": nm_id, "seller_article": seller_article,
            "barcode": barcode, "product_id": product.id, "name": product.name,
            "image_url": (product.media or [None])[0], "currency": "KZT",
        })
    return out, by_key


def current_cost_map(db, account_id: int, as_of: date):
    rows = db.scalars(select(MarketplaceProductCost).where(
        MarketplaceProductCost.account_id == account_id,
        MarketplaceProductCost.effective_from <= as_of,
    ).order_by(MarketplaceProductCost.effective_from, MarketplaceProductCost.id)).all()
    result = {}
    for row in rows:
        result[row.external_key] = row
    return result

