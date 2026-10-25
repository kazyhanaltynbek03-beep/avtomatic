# WB sale -> ERP status fix

- Confirmed WB realization sales are now surfaced as real API revenue/units even when ERP posting is blocked by missing FIFO cost/stock.
- ERP revenue remains canonical: only canonical.post_event -> finance.sale can post it.
- Profit/COGS are deliberately shown as unavailable while confirmed sales are pending ERP, preventing false negative/positive profit.
- Product/order/stock records are not treated as revenue or expense.
- Existing nmId/vendorCode/SKU/barcode mapping and NBK historical FX are reused.
- Mapping action is hidden for already mapped/projected records.
- Full backend regression: 146 passed. Python compile: PASS.
- Frontend build: NOT VERIFIED in this environment (node_modules unavailable). Render/Docker build must run npm ci/lint/build before release.

Important: if WB sales remain pending because QOR has no purchase batches/cost, this is not a mapping bug. FIFO cannot be invented. Add/import real opening stock/purchases with cost, then reprocess the WB account; canonical sales will post and profit will become available.
