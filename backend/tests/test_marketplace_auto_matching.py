from app.db import SessionLocal
from app.models import Account, MarketplaceProductMapping, MarketplaceRecord, Product, ProductCompany


def _catalog_row(db, account, source, external_id, payload):
    db.add(MarketplaceRecord(account_id=account.id, company_id=account.company_id,
                             source=source, external_id=external_id, payload=payload))


def test_auto_matching_links_exact_article_across_multiple_shops_idempotently(client):
    with SessionLocal() as db:
        db.add(Product(id=10, sku="chair-01", article="chair-01", name="Игровой стул",
                       specifications={"_qor_company_ids": [1]}))
        db.add(ProductCompany(product_id=10, company_id=1))
        kaspi_two = Account(id=4, company_id=1, name="Kaspi 2", channel="Kaspi", active=True)
        wb = Account(id=5, company_id=1, name="WB 1", channel="Wildberries", active=True)
        db.add_all([kaspi_two, wb])
        _catalog_row(db, db.get(Account, 1), "kaspi", "entry:k1", {
            "record_type": "order_entry", "sku": "chair-01", "external_product_id": "k-100"})
        _catalog_row(db, kaspi_two, "kaspi", "entry:k2", {
            "record_type": "order_entry", "sku": "CHAIR-01", "external_product_id": "k-200"})
        _catalog_row(db, wb, "wildberries", "product:500:600", {
            "record_type": "product", "vendorCode": "Chair-01", "nmId": 500,
            "chrtId": 600, "barcodes": ["460000000001"]})
        db.commit()

    first = client.post("/api/products/marketplace-matching/auto", json={"company_id": 1})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["links_created"] == 8
    assert body["products_linked"] == 3
    assert body["review_count"] == 0

    second = client.post("/api/products/marketplace-matching/auto", json={"company_id": 1})
    assert second.status_code == 200, second.text
    assert second.json()["links_created"] == 0
    assert second.json()["already_linked"] == 8
    assert second.json()["products_linked"] == 3

    with SessionLocal() as db:
        mappings = db.query(MarketplaceProductMapping).filter(
            MarketplaceProductMapping.product_id == 10).all()
        assert {m.account_id for m in mappings} == {1, 4, 5}


def test_auto_matching_leaves_ambiguous_and_name_only_matches_unlinked(client):
    with SessionLocal() as db:
        second = Product(id=3, sku="CHAIR-ALT", article="CHAIR-02", name="Игровой стул",
                         specifications={"_qor_company_ids": [1]})
        duplicate = Product(id=4, sku="CHAIR-ALT-2", article="CHAIR-02", name="Другой стул",
                            specifications={"_qor_company_ids": [1]})
        db.add_all([second, duplicate])
        db.add_all([ProductCompany(product_id=3, company_id=1), ProductCompany(product_id=4, company_id=1)])
        wb = Account(id=5, company_id=1, name="WB 1", channel="Wildberries", active=True)
        db.add(wb)
        _catalog_row(db, wb, "wildberries", "product:700:701", {
            "record_type": "product", "vendorCode": "CHAIR-02", "nmId": 700, "chrtId": 701,
            "name": "Игровой стул"})
        _catalog_row(db, wb, "wildberries", "product:800:801", {
            "record_type": "product", "vendorCode": "CHAIR-02", "nmId": 800, "chrtId": 801,
            "name": "Игровой стул"})
        _catalog_row(db, wb, "wildberries", "product:900:901", {
            "record_type": "product", "vendorCode": "DIFFERENT-SKU", "nmId": 900, "chrtId": 901,
            "name": "Alpha"})
        db.commit()

    response = client.post("/api/products/marketplace-matching/auto", json={"company_id": 1})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review_count"] >= 1
    assert any("Неоднозначное" in item["reason"] for item in body["review"])
    with SessionLocal() as db:
        assert db.query(MarketplaceProductMapping).filter(
            MarketplaceProductMapping.account_id == 5).count() == 0


def test_auto_matching_respects_company_scope_and_does_not_write_financial_rows(client):
    with SessionLocal() as db:
        db.get(Product, 1).specifications = {"_qor_company_ids": [1]}
        other = db.get(Account, 2)
        _catalog_row(db, other, "kaspi", "entry:other", {
            "record_type": "order_entry", "sku": "A", "external_product_id": "other-k"})
        db.commit()

    before_sales = client.get("/api/data/sales?company_id=1").json()["total"]
    response = client.post("/api/products/marketplace-matching/auto", json={"company_id": 1})
    assert response.status_code == 200, response.text
    after_sales = client.get("/api/data/sales?company_id=1").json()["total"]
    assert before_sales == after_sales
    assert all(row["account_id"] != 2 for row in response.json()["per_account"])


def test_auto_matching_does_not_link_another_companys_product(client):
    with SessionLocal() as db:
        foreign_product = Product(id=3, sku="FOREIGN-A", article="A", name="Alpha",
                                  specifications={"_qor_company_ids": [2]})
        db.add(foreign_product)
        _catalog_row(db, db.get(Account, 1), "kaspi", "entry:foreign-match", {
            "record_type": "order_entry", "sku": "A", "external_product_id": "k-a"})
        db.commit()

    response = client.post("/api/products/marketplace-matching/auto", json={"company_id": 1})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.query(MarketplaceProductMapping).filter(
            MarketplaceProductMapping.account_id == 1,
            MarketplaceProductMapping.product_id == 3).count() == 0


def test_auto_matching_flags_conflicting_brand_and_characteristics(client):
    with SessionLocal() as db:
        product = db.get(Product, 1)
        product.brand = "QOR Brand"
        product.specifications = {"_qor_company_ids": [1],
                                  "attributes": [{"name": "Color", "value": "black"}]}
        _catalog_row(db, db.get(Account, 1), "kaspi", "entry:attribute-conflict", {
            "record_type": "order_entry", "sku": "A", "external_product_id": "k-a",
            "brand": "Different Brand", "characteristics": [{"name": "Color", "value": "red"}]})
        db.commit()

    response = client.post("/api/products/marketplace-matching/auto", json={"company_id": 1})
    assert response.status_code == 200, response.text
    body = response.json()
    assert any("противоречат" in row["reason"] for row in body["review"])
    with SessionLocal() as db:
        assert db.query(MarketplaceProductMapping).filter(
            MarketplaceProductMapping.account_id == 1,
            MarketplaceProductMapping.product_id == 1).count() == 0
