# WB architecture fix — 2026-10-08

- Single Wildberries fetch implementation: `fetch()` is now a compatibility wrapper over `fetch_section_pages()`.
- Product content cursor (`updatedAt`, `nmID`) is persisted and resumes after restart.
- Per-section durable status is stored under `_sections` in `Account.sync_cursor`.
- WB sync no longer accumulates page payloads in RAM; only counters are retained.
- Marketplace staging commits every successful page before the next remote request.
- Full ERP projection runs once after all WB streams instead of once per section.
- Failed pages retain the last committed cursor and are retried on the next run.
- `sync_cursor` changed to Text on PostgreSQL; SQLite migration is a safe no-op because SQLite does not enforce VARCHAR length.
- Existing-database migration test updated to the new Alembic head.

Verification:
- Python compileall: PASS.
- Alembic: one head `d31f4a6b7001`.
- Focused connector/marketplace/financial/migration tests: 24 passed.
- Full pytest displayed all test progress with no assertion output but exceeded the execution timeout during completion; therefore full-suite PASS is not claimed.
- Live WB API was not exercised because production credentials are not present in this environment.
