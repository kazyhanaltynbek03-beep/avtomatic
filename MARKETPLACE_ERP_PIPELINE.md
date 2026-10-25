# Marketplace → ERP pipeline

This release keeps raw API data and financial posting separate.

1. Kaspi / Wildberries / Ozon connectors fetch and paginate supported source data.
2. Every external record is idempotently staged in `marketplace_records`.
3. `marketplace_pipeline` projects only confirmed, financially safe events into the deterministic ERP ledger.
4. Confirmed sales are posted through the same `finance.sale()` FIFO engine as manual/Excel/CSV sales, so Dashboard, All Sales, stock movements, reports and AI read the same ledger.
5. Unmapped SKU, missing FIFO stock/cost, returns without a matching sale, and ambiguous statuses remain `pending_erp`; they are never converted into invented profit.
6. Re-sync updates staging records and does not duplicate ERP sales because ERP references are deterministic.

Excel/CSV remains source-neutral and uses the same finance functions after preview/validation/confirmation. Marketplace report imports likewise use the same event normalization and finance functions.

Production validation still requires real credentials for each provider and sufficient token scopes. A 200 API response does not prove every optional provider scope is granted.
