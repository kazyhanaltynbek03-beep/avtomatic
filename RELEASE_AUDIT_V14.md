# QOR AI Business ERP — V14 stability audit

## Fixed in this release

- Removed the browser's endless `/api/jobs/{id}` polling path for user-triggered AI work.
- User-triggered AI, content, designer and marketplace jobs now complete in the web request as `done` or `failed`; only server-scheduled product-card reviews use the worker queue.
- Removed the conditional React Hooks path in `AIPage`, which could crash when switching AI sections.
- Added an application Error Boundary so a component error has a recovery screen instead of a white page.
- Added ESLint with `no-undef` and React Hooks rules. Docker now runs lint before its production frontend build.
- Added dedicated production credential-key enforcement. Marketplace credentials remain account-scoped, encrypted server-side and are never returned to the browser.
- Retained idempotent credential replacement (`IntegrationSecret.account_id` is unique and credentials use an update-or-create flow); no account-scoped marketplace ENV variables are used.

## Automated checks executed

| Check | Result |
|---|---|
| `npm run lint` | PASS |
| `npm run build` | PASS |
| Python compile (`backend/app`) | PASS |
| Alembic upgrade on a clean SQLite database | PASS, revision `f95a6c3e5005` |
| Full backend pytest suite | BLOCKED before first request: installed TestClient transport hangs during startup in this environment |
| Docker build | NOT RUN: Docker daemon/CLI is not available in this environment |
| Live marketplace API | NOT RUN: requires client credentials; no success is simulated |

## Remaining release gate

Run the following in the target Docker/Render runtime before declaring a live deployment complete:

```bash
docker compose up --build
docker compose exec web pytest -q /srv/backend/tests
```

Then verify a real account for each marketplace in the UI. A real token is required; mock tests and a successful build do not verify marketplace access rights.

## Required Render environment

- `DATABASE_URL`
- `OWNER_EMAIL`
- `OWNER_PASSWORD`
- `CREDENTIAL_ENCRYPTION_KEY` (dedicated secret, required when `APP_ENV=production`)
- `COOKIE_SECURE=true`
- `APP_ENV=production`

`OPENAI_API_KEY` is optional. The deterministic ERP calculation engine remains available without it.
