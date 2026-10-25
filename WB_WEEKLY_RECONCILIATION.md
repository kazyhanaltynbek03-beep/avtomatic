# Wildberries weekly reconciliation — implementation status

- The existing diagnostic API now returns weekly totals, grouped by Monday start date, original currency, and operation category.
- Separate fields are never summed together; this avoids treating settlement as profit or actual bank payout.
- The WB finance screen now switches between daily, weekly and monthly views. Monthly data uses the daily Finance API and aggregates the selected month; each view has its own status, storage key and Excel download.
- The Finance API rows are also projected under stable realization IDs into the existing canonical ledger, so matched items can use FIFO purchase costs. Standalone costs remain report-level.
- Standard marketplace sync requests current orders and order/sale statistics only; stock snapshots, full product catalog and generic realization stream are opt-in. The bounded Finance report request remains independent of those streams.
- No historical records, Alembic migrations, or credentials were changed.
- Remaining: investigate the latest live API/Excel mismatch (124 API rows versus 10 Excel rows, with materially different payout), implement row-identity Excel matching, run the backend regression suite and frontend lint/build in a dependency-complete environment, and verify the deployed Render app. The latest change does NOT claim Excel parity or client acceptance.
