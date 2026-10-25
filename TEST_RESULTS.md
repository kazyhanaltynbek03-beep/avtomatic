# Test results for this revision

- `python -m compileall -q backend/app backend/tests`: passed after the latest code edits.
- Executed both Excel parser regression functions directly (standard Python/openpyxl): passed, including a synthetic 10-row client baseline. The new weekly zero-quantity test compiles but cannot run without SQLAlchemy/pytest.
- Focused tests were invoked for `test_wb_negative_commission_and_vat_adjustments_post_as_signed_expenses` and `test_wb_weekly.py`; they could not start because `pytest` is not installed (`No module named pytest`).
- `npm run lint`: attempted; blocked because `eslint` is not installed. `npm run build` was not run after lint stopped; frontend dependencies are unavailable. `npm ci` could not retrieve packages in the network-restricted environment.
- Live WB API, production PostgreSQL migration, and Render deployment: not tested; no credentials/environment were available.
- The attached client workbook was read directly (10 rows: 5 sale, 5 logistics); exact financial control totals and a synthetic regression baseline were prepared in `WB_RECONCILIATION.md` and `tests/test_wb_excel_reconciliation.py`.
- A real official Finance API request for the workbook week was attempted using the supplied token. WB returned HTTP 401, `token signature is invalid`; no live response rows were obtained and API parity is not claimed.
- Older validation files in the project refer to previous revisions and are not evidence for these edits.
