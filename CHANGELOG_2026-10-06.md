# Critical ERP correction pass — 2026-10-06

## Fixed

- Dashboard now reports the `Wildberries` channel correctly instead of looking up a non-existent `WB` channel.
- Stock rows now include daily velocity, days of stock, turnover days and FIFO unit cost; stockout alerts can use real days-of-stock data.
- Purchase lines support KZT/CNY/USD (or another 3-letter currency) with an explicit FX rate. The posted FIFO batch stores the converted KZT cost.
- Audit Log records before/after values for create, update and delete operations on editable master data.
- Expenses now store project and payment method, including CSV/XLSX import fields.

## Regression protection

`backend/tests/test_critical_regressions.py` covers Wildberries Dashboard turnover, FX stock cost plus days of stock, and Audit before/after values.

## Remaining external gates

Kaspi/Wildberries/Ozon live adapters, production PostgreSQL test, and a clean frontend build need the target server credentials/dependencies. They are not claimed as complete by this release.

## V4 Kaspi full order operations
- Removed the artificial Kaspi read-only restriction.
- Added server-side POST order status operations using official Kaspi order API.
- Added UI actions for ACCEPTED_BY_MERCHANT, ASSEMBLE, ARRIVED, CANCELLED and COMPLETED.
- Added cancellation reason/comment, numberOfSpace and buyer security-code support.
- Added explicit confirmation before marketplace writes and audit logging.

## V5 — Wildberries + Ozon live API
- Wildberries API: live FBS new-orders adapter (`marketplace-api.wildberries.ru/api/v3/orders/new`).
- Ozon Seller API: live FBS + FBO posting synchronization for the last 14 days.
- Integration modal now includes `Проверить и синхронизировать` after credentials are saved.
- Marketplace secrets remain encrypted server-side and are never returned to the browser.
- Removed the previous WB/Ozon placeholder exceptions.

## V7 clean integrations UI
- Removed legacy Marketplace Accounts wording from the client UI.
- Removed credential_ref / ENV variable field from the integration creation form.
- Added visible `Интеграции` menu entry.
- New marketplace integrations default to API mode.
- Integration form is limited to Kaspi, Wildberries and Ozon; secrets are entered only in the secure API modal.
- Connection status, last sync and sync errors remain visible in the integrations table.

## V8 stability audit
- Fixed audit-log JSON serialization for datetime/date values. Creating or editing marketplace accounts could previously fail with `Object of type datetime is not JSON serializable` during `db.commit()`.
- Normalized model dumps with FastAPI `jsonable_encoder` before audit/API serialization.
- Re-ran the complete backend test suite: 106 passed.
- Confirmed the frontend no longer contains the legacy ENV credential field or `Marketplace Accounts` label; the navigation label is `Интеграции` and account creation defaults to API mode.

## V9 — Direct API setup + smarter spreadsheet import
- API credentials are entered directly while creating Kaspi/Wildberries/Ozon integrations.
- Credentials are encrypted server-side and a live sync job starts immediately after creation.
- Excel/CSV import now auto-maps common RU/KZ/EN column names.
- Sales imports can resolve products by SKU/article instead of requiring internal product IDs.
- Selected company and Offline/B2B account are auto-filled for sales imports when available.
- Preview/transaction safeguards remain mandatory before financial data is committed.
- Backend regression suite: 106 passed.

## V10 — immediate marketplace sync
- Fixed production queue bug: Render web service did not start `app.worker`, so marketplace jobs could remain `queued` forever.
- Added synchronous authenticated endpoint `POST /api/accounts/{id}/sync-now` for Kaspi, Wildberries and Ozon.
- Integration UI now calls the marketplace API immediately for test/sync instead of enqueueing a worker job.
- Account status is persisted as `running` -> `done` / `failed`; API errors are shown immediately and last check time is saved.
- Creating an API integration now performs its first live sync immediately.
