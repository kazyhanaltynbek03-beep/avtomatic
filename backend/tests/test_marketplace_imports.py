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
