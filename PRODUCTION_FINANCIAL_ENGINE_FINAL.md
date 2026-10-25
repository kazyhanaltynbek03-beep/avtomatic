# QOR AI Business ERP — Production financial engine

## Root cause fixed

The Wildberries realization pipeline attempted FIFO before it could post a sale. When no historical batch existed, a confirmed sale stayed out of `sales`, while independently parsed marketplace expenses were posted. This made revenue and unit counts appear as zero and made expense-only loss look final.

The API health endpoint also still expected an old Alembic revision after the latest database changes, which could return HTTP 503 on an otherwise migrated database.

## Behaviour after migration

- Confirmed Kaspi, Wildberries and Ozon sales create one idempotent ERP sale even if FIFO is unavailable.
- The sale keeps confirmed quantity and revenue; `cogs_pending=true` keeps COGS, gross profit, net profit, margin and ROI unknown.
- Existing and new source events use the same canonical posting and finance reporting service.
- WB product identity is resolved by saved mapping, exact seller SKU or barcode; a uniquely identified marketplace item may create a catalogue identity and mapping without inventing stock or cost.
- Historical stock/cost can be entered through `Opening Inventory / Historical Cost` import or `POST /api/post/opening`; it creates a real FIFO batch and reconciles pending sales without duplicating revenue. Excel matching accepts the internal SKU, the Wildberries seller article, or a saved WB product mapping; ambiguous matches are rejected rather than assigned to a wrong product.
- Reconciliation is explicit in the marketplace inbox: `Восстановить учёт из сохранённых API-записей`. It is idempotent and does not call the marketplace API.
- Past RUB operations persist original amount, currency, operation date, historical FX rate and source. A missing rate is `FX_REQUIRED`; a later rate cannot rewrite an existing operation.
- Ozon FBS/FBO posting synchronization follows the provider cursor (`cursor`/`has_next`) and rejects a non-advancing cursor. This prevents skipped or duplicated sales when more than one page is returned.
- Ozon connector uses FBO v3 and accrual-by-day endpoints. Accruals are staged for classification; they do not become invented payouts, revenue or expenses.
- Money is rendered in KZT with two decimal places. `DEMO_MODE=false` does not show the demo badge.

## Migration

Alembic head: `c20e3f405002`.

The migration adds immutable source FX metadata for sales/expenses, pipeline progress/reason fields for marketplace records and per-account dated exchange rates. It is additive and preserves historical accounting documents.

## Validation

- Python compile: PASS.
- Backend regression suite: 152 passed, 1 existing AnyIO deprecation warning.
- Empty SQLite migration and `/api/health` compatibility check: PASS after `c20e3f405002`.
- Frontend lint and production build: PASS.
- Financial regression covers: WB sale without pre-created product/FIFO, logistics, no fake profit, dashboard/report/channel/AI reconciliation, idempotent reprocess, opening-cost FIFO reconciliation, returns before cost, FX date lock and XLSX controls.
- Docker engine was unavailable in this workspace, so Docker image build was not run.
- Browser acceptance test is included in `frontend/e2e/production-runner.cjs`. The isolated execution environment blocked Node from spawning the local Python fixture process, so a full Chromium pass could not be honestly marked PASS here. The test itself uses no live marketplace credentials and checks login, demo badge, staged WB sale, core pages, FIFO reconciliation, XLSX and logout.

## Deploy and verify once

1. Deploy the ZIP with the existing production PostgreSQL database; startup runs `alembic upgrade head`.
2. Open Wildberries and press `Восстановить учёт из сохранённых API-записей` once.
3. Check `pending_fifo` / `COGS_PENDING` entries. Import opening inventory or historical purchases only from confirmed cost documents. For a supplier Excel use the WB article/SKU, quantity, unit cost, date on or before the sale, currency and a unique document number.
4. Verify the resulting revenue against the WB realization report. Live API permissions and real payloads still require this final post-deploy verification; no production credentials or production database were present in the archive.
