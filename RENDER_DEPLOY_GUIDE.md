# Safe Render deployment guide

1. Keep the existing production PostgreSQL service and `DATABASE_URL`. Do not reset, recreate, or delete the database.
2. Preserve `CREDENTIAL_ENCRYPTION_KEY`; changing it can make stored marketplace credentials unreadable. Keep it private and stable.
3. Deploy the project using its existing Docker/start configuration. Let the existing Alembic upgrade run; apply the new Alembic migration `f8c3a2b1d901` through the normal startup migration path; do not edit or delete migration history.
4. Confirm health/readiness reports migration head `f8c3a2b1d901` and inspect application logs. Confirm the web service starts and the WB scheduler starts once per web process. The scheduler is an in-process daemon, not a durable queue; use a single-worker deployment or a future distributed lease/worker design to avoid redundant periodic work.
5. In the ERP, select one closed Monday–Sunday week and click “Загрузить из WB”. Check status, last update, row count, and visible error. Do not repeatedly trigger while a sync is in progress; the existing report lease suppresses duplicate active work.
6. Reconcile one real report to the same-period seller XLSX before relying on totals or profit. Keep real credentials only in the deployment's secret manager, never in chat or source control.

Deployment was not performed or live-verified in this task.
