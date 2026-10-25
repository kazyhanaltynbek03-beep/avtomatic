# Wildberries root audit — 2026-10-07

Scope: Wildberries only. Ozon/Kaspi connector logic was not modified in this pass.

Root issues fixed:
1. Product cards previously used ERP Sale rows for per-product turnover while the page-level API KPI used raw WB sales. This could make the same WB page disagree with itself. WB cards now calculate period/lifetime-in-QOR sales from raw WB `sale` records mapped to the product. ERP remains the source for COGS/profit.
2. WB sales turnover and realization/settlement were not explicit enough in the UI. The summary now exposes `settlement_accrued` separately from API sales turnover. Settlement is not booked as bank Cash Flow.
3. Prior revisions incorrectly treated `ppvzSalesCommission` as a percentage and omitted it from expense totals. The official Finance API sample shows `ppvzSalesCommission` as a money string and `commissionPercent` as the percentage. Current code now books/sums the monetary field and keeps the rate separate. This does not by itself reconcile all payout/expense semantics to a client workbook.
4. Existing catalogue/stock/product-photo pipeline is preserved. Cards already retry all API image URLs and fall back to a clean placeholder instead of broken alt text.

Verification:
- py_compile changed backend modules: PASS
- focused backend marketplace/financial tests: 21 passed
- frontend npm ci/lint/build: NOT VERIFIED in this environment because npm install exceeded execution timeout
- no live WB token/API call was performed; live provider verification is required after deploy

Business semantics:
WB sales feed -> quantity + turnover.
WB detailed realization -> settlement/fees/charges.
Actual bank payout -> Cash Flow only when a real payout/payment document exists.
FIFO absence never changes turnover; it only makes COGS/profit pending.
