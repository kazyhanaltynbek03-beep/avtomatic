# WB Excel comparison release notes

Read-only XLSX upload is now available in the Wildberries reconciliation panel.
The screen compares independent monetary columns from uploaded WB Excel with the saved WB API weekly aggregates in their original currency.
**These comparisons are diagnostic only**: API weekly aggregates and XLSX periods have not been verified to cover identical report boundaries, and record-by-record matching is not implemented.
No financial postings, database migrations or old ledger data were changed.

Verification: backend compileall passed; focused XLSX parser test passed (1 test). Frontend npm ci timed out; lint/build unverified. Live WB/Render testing not performed.

Outstanding for production financial parity: official WB report period metadata, stable operation IDs, row-level matching, discrepancy reasons, FIFO costing and net profit validation, and frontend build.
