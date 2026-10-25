# WB financial reconciliation — release guard

Current Excel preview is read-only. Do not infer weekly settlement from operational sales.

This revision prevents the frontend from displaying numeric Excel↔API differences unless the WB report period is independently verified. Previously the UI compared all fetched weekly buckets to an arbitrary uploaded XLSX, which could produce misleading differences even for different reporting periods.

Implementation update:
- Daily, weekly, and monthly Finance report workflows are implemented. Monthly uses daily API rows; current month stops at yesterday.
- Selected report rows now feed the canonical marketplace pipeline and match FIFO costs through `srid`/`rrdId`.
- Standard WB sync defaults to current orders and order/sale statistics; stock snapshots, catalog and generic realization streams are opt-in.
- The report calculation uses `forPay` as seller payable, deducts FIFO COGS and standalone fees, and keeps fee fields as independent controls to avoid double subtraction.

Remaining production blockers:
1. Reconcile the live Finance API result (124 rows) to the client's 10-row workbook using exact account, report scope and immutable row/order identifiers. Do not call parity until this passes.
2. Handle changed already-posted WB rows through explicit reconciliation; canonical events reject silent revisions.
3. Run the backend regression suite and frontend lint/build in a dependency-complete environment.
4. Verify the deployed Render database/account and a client-authorized daily, weekly and monthly report flow.

No DB migration or historical ERP posting is changed.
