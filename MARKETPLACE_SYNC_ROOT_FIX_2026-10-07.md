# Marketplace sync root fix — 2026-10-07

- Wildberries stock ingestion moved to the current Analytics v2 product stock report instead of the obsolete warehouse route.
- WB stock records now map by nmID into the same marketplace product identity used by catalogue/sales.
- Ozon finance parser accepts the 2026 `accrual_id` field while retaining backward compatibility with `type_id`.
- Marketplace product endpoint now accepts the selected start/end period and returns both period metrics and lifetime-in-QOR metrics.
- UI explicitly labels product sales/revenue as selected-period vs all-time-in-QOR.
- Existing source records are preserved; no destructive migration is required.

Validation: Python compileall PASS; canonical marketplace test module 23/23 PASS. Full backend suite progressed past 45% with no failure before the execution time limit.
