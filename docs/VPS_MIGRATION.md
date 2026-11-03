# VPS cutover checklist

Use this checklist when the VPS is ready. Keep the current Render service available until the VPS has passed a login, database, integration, and background-worker check.

## Services

The existing `compose.yaml` runs PostgreSQL, a one-time Alembic migration, the web app, the marketplace worker, and report-cache warmup/worker. Start them with the Compose file so the migration completes before the web and workers start. Before the VPS web service becomes healthy, the warmup prepares dashboard cards and full finance snapshots for Owner, Admin, and Accountant users, for each permitted company scope, and for the standard periods plus a rolling 370-day period. Snapshots include sales, returns, balances, and stock/cost detail. The API serves prepared reports immediately; the always-on report-cache worker refreshes them in the background. A custom date range is saved after its first calculation. Keep both workers running; do not run a second copy of either during cutover. The first VPS startup can take longer while the initial reports are prepared, so keep Render available and do not switch the domain until the VPS health check and report comparison pass.

After starting the stack, verify the first-pass warmup before moving traffic:

```sh
docker compose ps web report-cache-warmup report-cache-worker
docker compose logs report-cache-warmup
```

The warmup container must exit successfully, the web container must be healthy, and the report-cache worker must remain running. The worker logs each full snapshot it prepares, including the 370-day date range.

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
6. Verify sign-in, companies, marketplace connections, Claude API test, WhatsApp connection test, and the marketplace account sync status. The 370-day report uses data already present in the restored database; Kaspi and Wildberries API history limits and saved sync cursors remain the source of any backfill. Confirm the required history is present before switching traffic.
7. Check a dashboard period and an Excel export against the current service.
8. Switch the domain only after these checks pass. Keep Render available for rollback until the VPS is stable.

## API history note

Kaspi history scans a 370-day window. Wildberries financial realization reports are backfilled for 370 days; operational orders and sales are limited by WB's API retention to 90 days. Keep the financial reports and operational order/status history clearly distinguished in the UI.
