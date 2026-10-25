# QOR V15 release audit

- Marketplace sync has one production path: `/api/accounts/{id}/sync-now`; legacy `kind=sync` jobs return HTTP 410.
- Per-account credentials are encrypted in `integration_secrets`; repeated PUT replaces the secret without duplicate rows.
- Marketplace payloads are persisted idempotently in `marketplace_records` using `(account_id, source, external_id)`.
- Raw orders are intentionally not booked as financial sales until ERP has sufficient product/cost/payment semantics; this prevents false profit.
- Kaspi pagination uses up to 100 records/page and follows pages; Ozon FBS/FBO pagination follows offsets.
- Kaspi write operations follow current documented order status endpoint; status operations requiring `code` validate it.
- Excel/CSV import retains preview -> mapping -> validation -> confirm workflow. Marketplace report import is exposed in UI.
- Python compile passes; Alembic has one head `d15e0a1b2c3d`.
- Backend test suite: 108 passed.
- Docker blocks deployment on `npm run lint` and `npm run build`. Local npm dependency installation in this execution environment timed out, so Render/Docker remains the authoritative frontend build check.
