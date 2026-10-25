from decimal import Decimal
from app.wb_weekly import is_return_operation, signed_wb_sale_amount

def test_return_case_and_both_field_names():
    for value in ("Возврат", "возврат", "ВОЗВРАТ", "Возврат товара", "RETURN"):
        for field in ("docTypeName", "doc_type_name", "supplierOperName", "supplier_oper_name", "sellerOperName"):
            row = {field: value}
            assert is_return_operation(row)
            assert signed_wb_sale_amount(row, "11753.06") == Decimal("-11753.06")
            assert signed_wb_sale_amount(row, "-11753.06") == Decimal("-11753.06")

def test_sale_and_reversal():
    assert signed_wb_sale_amount({"docTypeName": "Продажа"}, "11000") == Decimal("11000")
    assert signed_wb_sale_amount({"docTypeName": "Сторно возврата"}, "-11000") == Decimal("11000")
