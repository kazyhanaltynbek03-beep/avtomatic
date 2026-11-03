# VPS cutover checklist

Use this checklist when the VPS is ready. Keep the current Render service available until the VPS has passed a login, database, integration, and background-worker check.

## Services

The existing `compose.yaml` runs PostgreSQL, a one-time Alembic migration, the web app, the marketplace worker, and report-cache warmup/worker. Start them with the Compose file so the migration completes before the web and workers start. Before the VPS web service becomes healthy, the warmup prepares complete finance snapshots for the standard periods (day, week, month, quarter and year) and for each company, including return totals, return balances and stock/cost detail. The API then reads saved snapshots instead of recalculating a full report on each visit. The report-cache worker keeps the snapshots refreshed and prepares custom ranges after their first calculation. Keep both workers running; do not run a second copy of either during cutover. The first VPS startup can take longer while the initial reports are prepared, so keep Render available and do not switch the domain until the VPS health check and report comparison pass.

## Values to preserve

- Use the same `CREDENTIAL_ENCRYPTION_KEY` value as the current environment. Site-entered Claude and WhatsApp credentials, plus marketplace tokens, are encrypted with this key. If it changes, the database will not be able to decrypt those values.
- Copy the production `.env` values securely. Do not put tokens in GitHub, screenshots, or the browser console.
- Keep the existing database and uploaded files. The Compose volumes are named `pgdata` and `uploads`.

## Cutover order

1. Configure a supported Linux VPS, Docker Engine, Docker Compose, firewall, domain DNS, and HTTPS reverse proxy.
2. Take a PostgreSQL backup and copy the uploads volume from the active deployment.
3. Copy the repository's deployed `main` commit and production environment values to the VPS.
4. Restore the PostgreSQL backup and uploads before starting the new workers.
5. Start the Compose stack and confirm Alembic migrations and health checks complete.
6. Verify sign-in, companies, marketplace connections, Claude API test, WhatsApp connection test, and that the marketplace worker resumes its saved cursors.
7. Check a dashboard period and an Excel export against the current service.
8. Switch the domain only after these checks pass. Keep Render available for rollback until the VPS is stable.

## API history note

Kaspi history scans a 370-day window. Wildberries financial realization reports are backfilled for 370 days; operational orders and sales are limited by WB's API retention to 90 days. Keep the financial reports and operational order/status history clearly distinguished in the UI.
