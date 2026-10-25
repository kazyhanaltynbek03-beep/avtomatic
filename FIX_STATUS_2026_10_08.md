# QOR verification — 2026-10-08

Changes:
- Historical conclusion corrected in 2026-10-09 audit: `ppvzSalesCommission` is a monetary amount in the current official Finance API sample; `commissionPercent` is the rate. The earlier exclusion understated recorded commission and overstated profit. Current code and tests use the money field; live account reconciliation remains required.
- Weekly Finance API failures now produce explicit `ошибка` status, rather than silently reporting `ожидается` as though WB had not published a report.

Validation:
- Backend pytest: 165 passed, 2 warnings.
- Python compileall: passed.
- No real WB API token used; reconciliation against client XLSX not verified.
- PostgreSQL migrations not changed.
- Production deployment not verified. Do not claim financial parity until live reconciliation.
