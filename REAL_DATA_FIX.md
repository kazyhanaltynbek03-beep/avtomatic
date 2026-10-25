# Real marketplace data fix

- Marketplace product catalogue entries are now auto-created/mapped only when the API supplies a real seller SKU and product name/card metadata.
- No cost price or FIFO lot is fabricated. Missing accounting cost remains a reconciliation requirement.
- Marketplace inbox exposes product_name, seller SKU, quantity, source amount/currency, marketplace status, ERP status and projection reason.
- Existing canonical ERP posting remains the single financial/inventory engine.
- Kaspi order/entry/product extraction retained; WB cards/sales/realizations/stocks retained; Ozon postings/finance retained.
- Backend regression: 141/141 passed from backend working directory.
- Frontend lint/build could not be rerun in this environment because npm dependency installation timed out; source change is limited to an existing table column list.
