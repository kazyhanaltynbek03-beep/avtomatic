"""Conservative, additive matching of QOR SKUs to staged marketplace cards.

Matching is deliberately limited to an exact seller article/SKU. Names, photos,
and fuzzy attribute similarity are not strong enough to merge inventory safely.
"""
from collections import defaultdict
import unicodedata

from sqlalchemy import select

from .models import Account, Batch, MarketplaceProductMapping, MarketplaceRecord, Product, ProductCompany, Sale
from . import marketplace_pipeline


def _sku_key(value):
    value = unicodedata.normalize("NFKC", str(value or "")).strip()
    return value.casefold() if value else ""


def _attribute_pairs(value, result):
    ignored = {"name", "title", "category", "description", "sku", "barcode", "article",
               "supplierarticle", "vendorcode", "nmid", "chrtid", "productid", "id"}
    if isinstance(value, dict):
        label = value.get("name") or value.get("title")
        item_value = value.get("value", value.get("values", value.get("valueName")))
        if label is not None and item_value is not None:
            key = "".join(ch for ch in _sku_key(label) if ch.isalnum())
            normalized = _sku_key(item_value)
            if key and key not in ignored and normalized:
                result.setdefault(key, set()).add(normalized)
            return
        for name, item in value.items():
            key = "".join(ch for ch in _sku_key(name) if ch.isalnum())
            if key in ignored or name in {"id", "code"}:
                continue
            if isinstance(item, (str, int, float, bool)):
                normalized = _sku_key(item)
                if normalized:
                    result.setdefault(key, set()).add(normalized)
            elif isinstance(item, (dict, list)):
                _attribute_pairs(item, result)
    elif isinstance(value, list):
        for item in value:
            _attribute_pairs(item, result)


def _marketplace_attributes(payload):
    result = {}
    for key in ("attributes", "characteristics", "dimensions", "product_attributes", "merchant_product_attributes"):
        _attribute_pairs(payload.get(key), result)
    for parent in (payload.get("product_attributes"), payload.get("merchant_product_attributes")):
        if isinstance(parent, dict):
            for key in ("attributes", "characteristics", "dimensions"):
                _attribute_pairs(parent.get(key), result)
            for brand_key in ("brand", "brand_name", "manufacturer"):
                if parent.get(brand_key):
                    result.setdefault("brand", set()).add(_sku_key(parent[brand_key]))
    for brand_key in ("brand", "brand_name", "manufacturer"):
        if payload.get(brand_key):
            result.setdefault("brand", set()).add(_sku_key(payload[brand_key]))
    return result


def _qor_attributes(product):
    result = {}
    if product.brand:
        result.setdefault("brand", set()).add(_sku_key(product.brand))
    specifications = product.specifications or {}
    for key in ("attributes", "characteristics", "dimensions", "marketplace_attributes", "custom_fields"):
        _attribute_pairs(specifications.get(key), result)
    return result


def _attributes_conflict(product_attributes, marketplace_attributes):
    for key in product_attributes.keys() & marketplace_attributes.keys():
        if product_attributes[key] and marketplace_attributes[key] and not product_attributes[key] & marketplace_attributes[key]:
            return True
    return False


def _seller_sku(channel, payload):
    if channel == "Kaspi":
        return str(payload.get("sku") or "").strip()
    return marketplace_pipeline._seller_sku(payload)


def _marketplace_identity(channel, payload):
    if channel == "Wildberries":
        value = payload.get("nmId") or payload.get("nmID") or payload.get("nm_id")
        return f"wb:{value}" if value not in (None, "") else None
    value = payload.get("external_product_id") or payload.get("product_id")
    return f"kaspi:{value}" if value not in (None, "") else f"kaspi-sku:{_sku_key(_seller_sku(channel, payload))}"


def match_staged_catalog(db, accounts, products):
    """Add unambiguous account-scoped mappings; never edit sales or inventory."""
    account_ids = [a.id for a in accounts]
    product_ids = [p.id for p in products]
    if not account_ids or not product_ids:
        return {"links_created": 0, "already_linked": 0, "products_linked": 0,
                "products_scanned": 0, "review": [], "review_count": 0,
                "per_account": [], "catalog_accounts": 0, "_new_wb_pairs": []}

    company_ids_by_product = defaultdict(set)
    for product_id, company_id in db.execute(select(
        ProductCompany.product_id, ProductCompany.company_id
    ).where(ProductCompany.product_id.in_(product_ids))):
        company_ids_by_product[int(product_id)].add(int(company_id))
    for product in products:
        for company_id in (product.specifications or {}).get("_qor_company_ids", []):
            try:
                company_ids_by_product[product.id].add(int(company_id))
            except (TypeError, ValueError):
                continue
    product_ids = list(company_ids_by_product) or product_ids
    for product_id, company_id in db.execute(select(Batch.product_id, Batch.company_id).where(Batch.product_id.in_(product_ids))):
        company_ids_by_product[product_id].add(company_id)
    for product_id, company_id in db.execute(select(Sale.product_id, Sale.company_id).where(Sale.product_id.in_(product_ids))):
        company_ids_by_product[product_id].add(company_id)
    for product_id, company_id in db.execute(select(MarketplaceProductMapping.product_id, MarketplaceProductMapping.company_id).where(
        MarketplaceProductMapping.product_id.in_(product_ids))):
        company_ids_by_product[product_id].add(company_id)

    codes_to_products = defaultdict(lambda: defaultdict(set))
    for product in products:
        for company_id in company_ids_by_product.get(product.id, set()):
            for code in {_sku_key(product.sku), _sku_key(product.article)} - {""}:
                codes_to_products[company_id][code].add(product.id)

    account_by_id = {a.id: a for a in accounts}
    records = db.scalars(
        select(MarketplaceRecord).where(
            MarketplaceRecord.account_id.in_(account_ids),
            MarketplaceRecord.source.in_(["kaspi", "wildberries"]),
            MarketplaceRecord.payload["record_type"].as_string().in_(["product", "order_entry"]),
        ).order_by(MarketplaceRecord.id)
    ).yield_per(1000)
    # Keep only compact key sets per seller item. Kaspi order lines repeat a
    # product many times, so retaining ORM rows here would grow with order count.
    catalogue = defaultdict(lambda: defaultdict(set))
    catalogue_attributes = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for row in records:
        account = account_by_id.get(row.account_id)
        if account is None:
            continue
        payload = row.payload or {}
        seller_sku = _seller_sku(account.channel, payload)
        key = _sku_key(seller_sku)
        if key:
            identifiers = set(marketplace_pipeline.identifiers(payload))
            if identifiers:
                identity = _marketplace_identity(account.channel, payload)
                catalogue[(account.id, key)][identity].update(identifiers)
                for attribute, values in _marketplace_attributes(payload).items():
                    catalogue_attributes[(account.id, key)][identity][attribute].update(values)

    existing_rows = db.scalars(select(MarketplaceProductMapping).where(
        MarketplaceProductMapping.account_id.in_(account_ids),
    )).all()
    mapped_by_key = {(m.account_id, m.external_key): m.product_id for m in existing_rows}
    created = already = 0
    new_wb_pairs = set()
    review = []
    per_account = {a.id: {"account_id": a.id, "channel": a.channel, "account_name": a.name,
                          "matched_products": 0, "links_created": 0, "review": 0, "catalog_items": 0,
                          "products_scanned": sum(1 for p in products if a.company_id in company_ids_by_product.get(p.id, set()))}
                   for a in accounts}
    for (account_id, _sku), groups in catalogue.items():
        per_account[account_id]["catalog_items"] += 1

    for product in products:
        qcodes = list(dict.fromkeys(x for x in (_sku_key(product.sku), _sku_key(product.article)) if x))
        for account in accounts:
            if account.company_id not in company_ids_by_product.get(product.id, set()):
                continue
            matched_groups = defaultdict(set)
            duplicate_qor_code = False
            for code in qcodes:
                candidates = codes_to_products[account.company_id].get(code, set())
                if catalogue.get((account.id, code)) and len(candidates) > 1:
                    duplicate_qor_code = True
                for identity, keys in catalogue.get((account.id, code), {}).items():
                    matched_groups[identity].update(keys)
            if duplicate_qor_code or len(matched_groups) > 1:
                per_account[account.id]["review"] += 1
                review.append({"product_id": product.id, "sku": product.sku, "account_id": account.id,
                               "account_name": account.name, "reason": "Неоднозначное совпадение артикула",
                               "marketplace_keys": sorted({key for keys in matched_groups.values() for key in keys})})
                continue
            if not matched_groups:
                continue
            product_attributes = _qor_attributes(product)
            merged_marketplace_attributes = defaultdict(set)
            for code in qcodes:
                for identity in matched_groups:
                    for attribute, values in catalogue_attributes.get((account.id, code), {}).get(identity, {}).items():
                        merged_marketplace_attributes[attribute].update(values)
            if _attributes_conflict(product_attributes, merged_marketplace_attributes):
                per_account[account.id]["review"] += 1
                review.append({"product_id": product.id, "sku": product.sku, "account_id": account.id,
                               "account_name": account.name,
                               "reason": "Артикул совпал, но бренд или характеристики противоречат карточке QOR",
                               "marketplace_keys": sorted({key for keys in matched_groups.values() for key in keys})})
                continue
            keys = set(next(iter(matched_groups.values())))
            # Do not create a link without a stable marketplace identifier.
            if not keys:
                continue
            conflicts = [key for key in keys if mapped_by_key.get((account.id, key)) not in (None, product.id)]
            if conflicts:
                per_account[account.id]["review"] += 1
                review.append({"product_id": product.id, "sku": product.sku, "account_id": account.id,
                               "account_name": account.name, "reason": "Карточка уже связана с другим товаром QOR",
                               "marketplace_keys": sorted(set(conflicts))})
                continue
            added_for_product = False
            linked_for_product = False
            for key in sorted(keys):
                prior = mapped_by_key.get((account.id, key))
                if prior == product.id:
                    already += 1
                    linked_for_product = True
                    continue
                mapping = MarketplaceProductMapping(company_id=account.company_id, account_id=account.id,
                    channel=account.channel, external_key=key, product_id=product.id)
                db.add(mapping)
                mapped_by_key[(account.id, key)] = product.id
                created += 1
                added_for_product = True
                linked_for_product = True
                per_account[account.id]["links_created"] += 1
            if linked_for_product:
                per_account[account.id]["matched_products"] += 1
            if added_for_product and account.channel == "Wildberries":
                new_wb_pairs.add((account.id, product.id))

    db.flush()
    return {"links_created": created, "already_linked": already, "review": review[:200],
            "products_linked": sum(row["matched_products"] for row in per_account.values()),
            "products_scanned": len({p.id for a in accounts for p in products
                                      if a.company_id in company_ids_by_product.get(p.id, set())}),
            "review_count": len(review), "per_account": list(per_account.values()),
            "catalog_accounts": sum(1 for a in accounts if per_account[a.id]["catalog_items"] > 0),
            "_new_wb_pairs": sorted(new_wb_pairs)}
