# WB financial reconciliation fix

- Strictly classifies Wildberries realization operations before ERP posting.
- Unknown/non-financial realization rows no longer become expenses.
- Product/stock/order rows remain non-financial staging records.
- Sale rows create revenue only as canonical sales; commission/acquiring/logistics are categorized expenses.
- Return rows remain guarded by sale/warehouse confirmation.
- On the next WB sync/reprocess, old auto-generated WB expenses that no longer match the strict classifier are removed. Manual expenses are untouched.
- Existing canonical ERP idempotency and FIFO engine remain the source of truth.
- Backend regression: 143 passed; focused WB regression: 19 passed; Python compileall passed.
- Frontend was not changed; npm dependencies were not present in this workspace, so lint/build were not rerun here.
