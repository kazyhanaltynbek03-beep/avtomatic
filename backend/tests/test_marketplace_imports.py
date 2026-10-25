from app import importing


def test_marketplace_report_fields_cover_financial_events():
    fields = importing.FIELDS["marketplace_reports"]
    for key in ("event_type", "external_id", "account_id", "sku", "quantity", "unit_price", "commission", "logistics", "advertising", "sale_reference", "refund", "stock_delta"):
        assert key in fields


def test_marketplace_event_type_aliases():
    assert importing.marketplace_event("sale") == "sale"
    assert importing.marketplace_event("продажа") == "sale"
    assert importing.marketplace_event("возврат") == "return"
    assert importing.marketplace_event("остаток") == "stock"



def test_product_catalog_template_includes_card_fields():
    fields = importing.FIELDS["products"]
    for key in ("sku", "name", "article", "brand", "supplier", "country", "media", "currency", "fx_rate", "min_price", "recommended_price", "price", "specifications"):
        assert key in fields


def test_product_catalog_normalizes_excel_media_money_and_fx():
    product = importing.normalize("products", {
        "sku": "SKU-1", "name": "Товар", "article": "ART-1",
        "price": "1250,50", "min_price": "1000", "recommended_price": "1500", "fx_rate": "1,25",
        "media": "https://example.test/a.jpg; https://example.test/b.jpg",
        "specifications": '{"color":"black"}',
    }, {key: key for key in ("sku", "name", "article", "price", "min_price", "recommended_price", "fx_rate", "media", "specifications")})
    assert product.price == 125050
    assert product.min_price == 100000
    assert product.recommended_price == 150000
    assert product.fx_rate == 12500
    assert product.media == ["https://example.test/a.jpg", "https://example.test/b.jpg"]
    assert product.specifications == {"color": "black"}
