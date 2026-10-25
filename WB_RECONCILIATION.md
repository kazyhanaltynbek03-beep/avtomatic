# WB reconciliation — client baseline and live check status

## Period and source

- Client workbook: detailed report ID visible in filename `865293807`; the workbook itself has no explicit currency column.
- Report week to request: **2026-09-28 through 2026-10-04** (Monday–Sunday). The five sales rows have sale dates 2026-10-01 to 2026-10-03; five logistics rows are separate operations.
- The attached WB videos show the same finance-report context and visible control values: seller payable **234,619.97** and logistics **32,697.17**.

## Client workbook control totals

| Measure | Workbook | QOR field mapping | Status |
|---|---:|---|---|
| Rows | 10 (5 sales, 5 logistics) | Unique `rrdId` count | Does not match live API yet |
| Retail price | 306,487.26 | `retailPriceWithDisc` × quantity / Excel `Цена розничная с учетом согласованной скидки` | Workbook baseline captured |
| WB realized goods | 250,485.45 | `retailAmount` / Excel `Вайлдберриз реализовал Товар (Пр)` | Workbook baseline captured |
| Commission before agent services | 3,790.72 | `ppvzSalesCommission` / Excel column with same meaning | Workbook baseline captured; includes two negative adjustments |
| WB reward without VAT | 3,790.715517… | `vw` / Excel `Вознаграждение Вайлдберриз (ВВ), без НДС` | Informational/overlapping; do not subtract a second time |
| Commission VAT | 606.51 | `vwNds` / Excel VAT column | Workbook baseline captured; includes two negative adjustments |
| Acquiring | 11,468.25 | `acquiringFee` / Excel payment-service compensation | Workbook baseline captured |
| Seller payable | 234,619.97 | `forPay` or documented equivalent / Excel seller-payable column | Workbook baseline captured |
| Direct logistics | 32,697.17 | logistics operation / `deliveryService` or `deliveryRub` | Separate from sale rows and payable |
| Returns, penalties, storage, deductions | 0 in these rows | Return / `penalty` / `paidStorage` / `deduction` | Workbook baseline captured |

Workbook arithmetic check: 250,485.45 − 3,790.72 − 606.51 − 11,468.25 = 234,619.97. Seller payable less separate logistics is 201,922.80 before FIFO COGS. Do not label that amount as profit.

## Live API result (latest token)

A read-only request to the official period-detail endpoint succeeded for 2026-09-28–2026-10-04. Pagination ended with HTTP 204 after two requests; 124 unique rows were returned in KZT. The API date range matches the requested week, but the initial aggregate field comparison does **not** match the workbook (10 rows). For example, workbook seller payable is 234,619.97 while the initial API aggregation reported 961,515.37. This is a failed reconciliation and not evidence that the client report currently works.

Do not patch values with a balancing offset or assume that same week dates prove same report scope. The next comparison must inspect safe, non-secret row attributes and compare each API `rrdId` to Excel operations/available immutable IDs, identify why the API result includes 124 rows while the workbook has 10, verify whether the workbook is a partial report, and validate field names/signs against official API definitions. Then compare operation-category subtotals and payout/logistics independently. The earlier 401 note is obsolete; the latest token was accepted.

## Updated implementation for the client workflow

- Finance report routes now support a completed day, completed week, full month, and current month through yesterday. Monthly periods call the official API with `period=daily` because WB does not offer a monthly enum.
- The bounded Finance rows are stored separately by report period and also passed into the canonical marketplace pipeline under stable `realization:<rrdId>` IDs. This allows existing product mappings and FIFO batches to calculate real COGS without importing all product cards.
- FIFO matching uses WB sale `srid` and return row `rrdId`, not settlement date. Returns reverse the matching item's cost; standalone WB fees remain report-level and are not falsely attached to a product.
- Overall report profit is calculated as seller payable minus matched net FIFO COGS and separately reported delivery, reverse logistics, penalties, storage and other deductions. Commission/VAT/acquiring are visible as separate control fields and are not subtracted twice from `forPay`.
- Standard account sync defaults to current orders and order/sale statistics. Stock snapshots, the full product catalog and generic historical realization stream are opt-in; the selected Finance report route does not invoke them.

## Ready comparison procedure

For a live QOR verification after report scope and field mapping are resolved:

1. Query `POST /api/finance/v1/sales-reports/detailed` with `period=weekly`, `dateFrom=2026-09-28`, `dateTo=2026-10-04`, `limit=100000`, `rrdId=0`.
2. Continue with the last row's `rrdId` at the documented per-account rate until HTTP 204. Do not publish a page set as final before the terminal response.
3. Compare unique row IDs, report/account scope, operation types, native currency, and each independent amount above. Keep `ppvzSalesCommission`, `vw`, and VAT separate; never sum overlapping fields.
4. Run the QOR selected-week fetch and compare backend JSON, UI totals, and downloaded XLSX against the same baseline. Check exact row count, update time, source, report ID, and pagination count.
5. In an authorized QOR session, use `POST /api/wildberries/finance/sync?period=weekly&start=2026-09-28&end=2026-10-04&account_id=<id>`; it reads the token saved for that account. Poll `GET /api/wildberries/finance` for that period until terminal status, then download `GET /api/wildberries/finance.xlsx` with the same parameters. The Finance route does not invoke the generic order/catalog sync.
6. Mark the comparison passed only if account, week, report scope, currency, operation identities and source report version match. Investigate every non-zero difference; do not apply a balancing adjustment.

## Scope distinction

The selected-week screen uses its bounded Finance API request and a separate weekly staging source. The general WB sync still has a rolling 90-day initial window for order/sale/realization streams and a full paginated product-catalog stream. Those generic streams are not needed to fetch one weekly financial report and must not be used as evidence that the selected weekly report is complete. Daily operational sales and current new orders are separate data products from the daily Finance API report. The API exposes daily and weekly periods; a month view should aggregate daily finance rows for the exact month, not call a nonexistent monthly API period.
