# Wildberries paged sync hardening — 2026-10-08

- WB sync remains split into independent sections: new_orders, order, sale, realization, stocks, products.
- Added page-wise fetch API for WB sections.
- Every successfully received page is staged and committed before the next remote request.
- Cursor is committed with the page, so timeout/rate-limit failures can resume without losing durable progress.
- ERP projection runs once per completed section instead of once per remote page.
- Section counters now include pages, records, inserted and updated rows.
- A failed section is isolated and leaves earlier committed sections/pages intact.
- Sales turnover remains separate from realization/settlement expenses and payout/Cash Flow.
- Historical test assumption about `ppvzSalesCommission` was incorrect. See `ROOT_CAUSE_REPORT.md`: the official current Finance API example gives it as a money string and exposes `commissionPercent` separately. Current revision restores the monetary value to the explicit fee mapping.
- Fixed opening inventory Excel/CSV import when supplier files omit an evidence column; the auditable import run supplies evidence text.

Verification:
- Python compileall: PASS.
- Focused marketplace/financial tests: 21 passed.
- Full backend suite from backend/: 161 passed in 31.72s (test output completed successfully; outer command timeout fired after pytest completion).
- Live WB API was not called because production credentials are not available in this environment.
