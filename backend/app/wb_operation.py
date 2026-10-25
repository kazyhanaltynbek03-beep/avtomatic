"""Shared Wildberries operation classification; financial and inventory actions remain separate."""

FIELDS = ("docTypeName", "doc_type_name", "supplierOperName", "supplier_oper_name", "sellerOperName", "seller_oper_name")

def operation_label(payload):
    return " ".join(str(payload.get(k) or "") for k in FIELDS).casefold().strip()

def is_return_operation(payload):
    label = operation_label(payload)
    return "возврат" in label or "return" in label

def is_return_reversal(payload):
    label = operation_label(payload)
    return is_return_operation(payload) and any(marker in label for marker in (
        "сторно возврат", "сторно по возврат", "отмена возврат",
        "reversal of return", "return reversal", "cancel return"))
