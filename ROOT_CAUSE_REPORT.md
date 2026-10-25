# WB weekly report: traced chain and confirmed causes

## Data path

`POST /api/wildberries/weekly/sync` → background task → `wb_weekly.sync_week()` → bounded Finance API request with `period=weekly`, date range and `rrdId` paging → atomic `wildberries_weekly` staging → `build_report()` → UI KPIs/table or XLSX export.

The generic account sync follows a different path: `WildberriesConnector.fetch_section_pages('realization')` → `_stage_marketplace_records()` → source `wildberries` → `marketplace_pipeline.project_record()` → canonical Sale/Expense events. It can cover a rolling period, so its staged rows are not substituted for a selected-week report.

## Confirmed defects and changes

| Root cause | Effect | Change |
|---|---|---|
| Weekly page only read staged data; no selected-period fetch action or active polling | A week stayed empty until a scheduler pass/manual reload | Added authenticated background sync endpoint, button, and polling/status refresh |
| Generic sync and weekly view use separate staging sources | A successful generic sync could not populate the weekly view | Weekly view now requests the exact selected period through its own official endpoint; generic rows are not misrepresented as a complete selected-week report |
| Current `ppvzSalesCommission` money field was treated as a percentage; `commissionPercent` is the rate | Commission was omitted/mislabelled | Map amount and rate separately in weekly report, reconciliation preview, and canonical expense projection |
| ERP sale revenue preferred `retailPriceWithDisc` over `retailAmount` | Sale revenue could differ from realized goods amount in the client workbook | Current Finance API `retailAmount` is preferred; legacy fallback is used only when missing |
| Weekly profit subtracted COGS but not separate logistics/penalty/storage/deduction rows | Profit could be overstated | Profit subtracts standalone payout expenses and leaves COGS/profit unavailable until FIFO costs are complete |
| Negative commission/VAT adjustments were rejected by the Expense schema/database check | A sale row with a negative fee could fail canonical projection | Added signed values only for unpaid marketplace fee/adjustment categories, with migration and regression test |
| Weekly `retailPriceWithDisc` multiplied by `max(1, quantity)` | Zero-quantity rows could create a fabricated retail amount | Count only sale/return rows with non-zero quantity; preserve return sign; added a regression case |
| `/api/health` accepted only the prior migration revision | New migrated databases would be marked degraded | Updated expected head revision |

## Client workbook comparison

Compared the supplied workbook's 10 rows (5 sales and 5 logistics rows). Its observed sale dates span 2026-10-01 to 2026-10-03. Totals: realized goods 250,485.45; commission 3,790.72; commission VAT 606.51; acquiring 11,468.25; payable seller 234,619.97; separate logistics 32,697.17. Penalty, storage, deductions and adjustments are zero in these rows. Two sales rows contain commission corrections of -301.67 and VAT corrections of -48.27.

The workbook’s payable amount reconciles arithmetically as realized goods less commission, commission VAT and acquiring. Logistics is separately reported; payable less logistics equals 201,922.80 before COGS. The workbook has no explicit currency column. There is no live API payload for the same report, so API-to-workbook row parity is not claimed.

## Remaining verification

The supplied token was sent to the official Finance API and rejected with HTTP 401 (`token signature is invalid`); no API rows were received. The exact client workbook and video control values are captured in `WB_RECONCILIATION.md`, but API-to-Excel parity is not proven. The general WB sync still starts its order/sale/realization history at 90 days and paginates the product catalog; this is separate from the bounded weekly report fetch and remains a scope/performance item against the client's request to avoid broad initial ingestion.

Production PostgreSQL migration, UI build, and Render behavior require the client's environment. Dependency-based tests could not run here; see `TEST_RESULTS.md`.
