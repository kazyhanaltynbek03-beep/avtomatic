# QOR production financial engine fix

Root cause fixed in this release:

Older QOR releases could mark a Wildberries `realization` staging row as `projected` after only its marketplace expense leg had been written. Newer `project_account()` trusted that historical status and skipped the row forever, so the expense existed while the authoritative `Sale` did not. This exactly permits the production state `WB expenses > 0`, `Sales = 0`, `WB turnover = 0`.

The reconciliation loop now treats `projected` as an audit hint, not proof of financial completeness. For every confirmed WB realization sale it verifies that the expected ERP Sale reference actually exists. If it is missing, the row is safely re-opened and passed through the idempotent canonical posting pipeline. Existing sales remain untouched. Canonical identity/reference protection prevents duplicate revenue on repeated deploy/reprocess.

Missing FIFO continues to set `cogs_pending=true`; it never blocks confirmed marketplace revenue. Profit remains incomplete until real cost batches are available.

Verification in this workspace:
- backend pytest: 148 passed
- Python compileall: PASS
- Alembic: b19d2e3f4001 (single head)
- Added regression test for legacy `projected` WB realization with missing Sale, including idempotent second reconciliation.
- Frontend npm ci/lint/build: NOT VERIFIED here because npm install exceeded the execution transport timeout. No frontend source was changed by this fix.
