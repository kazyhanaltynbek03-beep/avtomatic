# WB reconciliation status

The diagnostic route `GET /api/wildberries/reconciliation?start=YYYY-MM-DD&end=YYYY-MM-DD` exposes realization operation categories and raw independent measures, including seller payout, realized goods, commission amount/rate, logistics, penalty, deduction, acquiring, and currency. It does not treat seller payout as a bank transfer.

The weekly report uses a separate exact-period fetch and staging namespace. It does not reuse generic realization staging because that stream is rolling and is not guaranteed to be scoped to the selected week. The weekly export labels `ppvzSalesCommission`, `vw`, and `vwNds` separately; `vw` is informational and is not added again to deductions.

The supplied client workbook was inspected: 10 rows (5 sales, 5 logistics); observed dates 2026-10-01–2026-10-03. Totals and negative commission/VAT corrections are documented in `ROOT_CAUSE_REPORT.md`. This is a workbook arithmetic comparison, not a live API parity check. No live credentials or same-period API response were available.
