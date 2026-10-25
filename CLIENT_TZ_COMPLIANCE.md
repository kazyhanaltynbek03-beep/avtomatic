# Client requirement compliance

| Requirement | Status | Evidence / remaining action |
|---|---|---|
| Preserve shared ERP financial pipeline | Implemented in code; runtime regression blocked | WB flows through canonical Sale/Expense events; migration adds signed marketplace corrections. Full pytest suite unavailable. |
| Client's payout-based calculation from the videos | Partially implemented | Daily, weekly and monthly report paths now use the official Finance API and expose payout, returns, delivery, penalties, storage and conditional FIFO profit. The exact client Excel/API arithmetic remains unreconciled. |
| Fetch a selected official weekly report | Implemented, live token accepted, financial parity unverified | Authenticated endpoint, bounded weekly request, `rrdId` pagination, idempotent staging, UI action and polling. The latest supplied token returned 124 rows and terminal HTTP 204 for 2026-09-28–2026-10-04. Its preliminary totals do not match the 10-row workbook; this is an unresolved reconciliation blocker, not a passing test. |
| Daily Finance report | Implemented in code; runtime not verified | Separate bounded Finance API route, period-specific storage, status polling and XLSX export. It remains distinct from daily operational sales and order streams. |
| Monthly payout report | Implemented in code; runtime not verified | Uses WB's daily Finance API for the exact calendar month (or month-to-date through yesterday) and aggregates those daily rows. The official endpoint has no monthly enum. |
| Avoid false zeroes and mixed currencies | Implemented in report logic; verify live | Empty reports return unavailable totals; mixed-currency sums are withheld. |
| Distinguish fee amount from fee rate | Implemented | `ppvzSalesCommission` is money; `commissionPercent` is the rate. Separate `vw`/`vwNds` fields are displayed. |
| Compare against client Excel | Baseline prepared; API parity failed pending investigation | 10 workbook rows and exact monetary controls are pinned in `WB_RECONCILIATION.md`. The latest valid-token API fetch returned data, but initial totals differ materially; row identity, report scope, field mapping and duplicate/overlap semantics must be reconciled before enabling a "correct" badge. |
| Calculate FIFO cost/profit only with real cost | Implemented in code; regression suite blocked | FIFO COGS now matches Finance API `srid` and return `rrdId`, rather than requiring the settlement date to equal sale date. Missing/incomplete cost keeps profit uncalculated; unassigned fees affect overall profit but are not falsely allocated to a product. |
| PostgreSQL/Render migration and deployment | Not verified | Requires production environment; health gate now expects migration head `f8c3a2b1d901`. |

## Requirements extracted from the two client videos

- Use Wildberries' seller payable (`forPay` / Excel `К перечислению Продавцу`) as the settlement base. Retail price, СПП and gross turnover are not payout or profit.
- Show sold and returned quantities and account for returns in payout and cost calculations.
- Show product cost (only when entered/mapped and supported by the ERP cost ledger), delivery/logistics, penalties, storage and resulting profit. Never label payout-minus-some-costs as profit if required costs or mappings are missing.
- Provide weekly and monthly results; the app also needs daily financial reporting separate from orders and operational sales statistics.
- Provide a useful downloadable report, with product and overall totals, without importing the seller's entire historical/catalog dataset just to fetch a selected period.

## End-to-end status

The daily/weekly/monthly Finance routes bypass generic marketplace synchronization. Ordinary WB sync now requests only current/new orders and order/sale statistics by default; stock snapshots, the full product catalog and generic realization stream are opt-in by explicitly selecting those sections. The reports must not be treated as client-ready until live API rows reconcile to the Excel control totals and UI/export agree.
