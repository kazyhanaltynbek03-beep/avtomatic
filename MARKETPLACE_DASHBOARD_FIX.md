# Marketplace dashboard fix

- Added `/api/marketplace-summary` backed by the same deterministic `finance.report()` engine used by Dashboard and reports.
- Channel aggregation now exposes commission, logistics, advertising, returns and return units without duplicating formulas in React.
- Wildberries/Kaspi/Ozon pages show business KPIs for the selected global period before raw API records.
- Raw marketplace records remain a technical reconciliation section and do not become P&L merely by being received.
- Existing NBK historical FX conversion remains unchanged.

Validation in this environment:
- Python compile: PASS
- Backend pytest: 146/146 PASS
- Frontend lint/build: NOT VERIFIED in this environment because npm dependency installation timed out and eslint binary was not installed. Docker/CI still runs the project's normal frontend quality gates.
