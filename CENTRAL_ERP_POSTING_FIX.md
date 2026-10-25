# Central ERP posting fix

Confirmed marketplace revenue is now posted even when historical FIFO batches are missing.
- Sale/revenue/units become visible across ERP immediately.
- `cogs_pending` marks only the missing cost leg.
- Profit/margin/ROI return null while any sale in the selected period lacks FIFO cost.
- Reprocess later reconciles pending COGS from historical batches without duplicating revenue.
- Marketplace revenue remains idempotent through canonical events.
- Existing strict FIFO behavior remains for normal/manual sales.

Verification: backend pytest 146 passed; Python compileall passed.
Alembic head: b19d2e3f4001.
