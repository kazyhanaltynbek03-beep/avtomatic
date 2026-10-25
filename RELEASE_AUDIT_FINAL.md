# QOR AI Business ERP — Final production audit

## Changes made

1. Fixed three tests that imported the same application through `backend.app` while the
   test/runtime entry point is `app`. This caused test collection to fail before any
   assertions ran.
2. Updated the Ozon FBS postings list endpoint from retired `/v3/posting/fbs/list`
   to `/v4/posting/fbs/list`. Ozon retired the v3 endpoint in June 2026.
3. Corrected the backend dependency lock. The previous lock paired FastAPI 0.142.2
   with Starlette 1.7.0, outside FastAPI's supported Starlette range. The release
   uses the compatible FastAPI 0.115.6 / Starlette 0.41.3 / AnyIO 4.7.0 set.
4. Added the missing transitive `sniffio` lock entry.
5. Made dashboard notification timers single-instance and cleaned them up when App
   unmounts, preventing stale timer state updates.

## Production paths confirmed by source audit

- Marketplace credentials are encrypted per `account_id` in `integration_secrets`;
  values are not returned by the API or used from marketplace Render ENV variables.
- Credential save updates the existing secret instead of inserting another row, which
  removes the unique-key 409 path on repeated saves.
- Marketplace sync is synchronous at `/api/accounts/{id}/sync-now`; `/api/jobs`
  rejects marketplace sync with HTTP 410. Jobs remain only for AI/content/designer
  work and server-scheduled product-card review.
- Marketplace records are staged idempotently using the unique tuple
  `(account_id, source, external_id)` and are not booked automatically as financial
  sales from raw order payloads.
- The frontend has an App error boundary and ESLint `no-undef` is an error.
- Empty SQLite migration path has one Alembic head and upgrades successfully.

## Verification results

### Passed locally

```text
Python compile: PASS
Alembic heads: d15e0a1b2c3d (head)
Empty SQLite upgrade: PASS
Frontend lint: PASS (0 warnings)
Frontend production build: PASS
Focused backend tests: 20 passed in 0.04s
```

The focused test run includes connectors, product calculator, forecasts, AI agent
tool/data-scope rules, marketplace import normalization, and spreadsheet safety.

### Environment limitation recorded honestly

This execution sandbox blocks the worker-thread handoff used by synchronous
FastAPI routes. Its TestClient hangs even for a minimal independent FastAPI app,
so the remaining request-level tests cannot be truthfully marked passed here.
This is a sandbox/runtime limitation, not a failed assertion. Run the full command
after deploy or in a normal Docker/Python environment:

```bash
cd backend
PYTHONPATH=. pytest -q
```

## Still requires real external verification

- A distinct valid Wildberries API token with the required scopes.
- A valid Kaspi merchant token and merchant account permissions.
- Ozon Client-Id/API-Key with FBS/FBO permissions.
- `OPENAI_API_KEY` for provider-backed AI responses and image generation.
- PostgreSQL migration on a copy of the existing production database.
- Render deployment against its managed PostgreSQL instance.

## Required Render environment

```text
DATABASE_URL
APP_ENV=production
OWNER_EMAIL
OWNER_PASSWORD
CREDENTIAL_ENCRYPTION_KEY
COOKIE_SECURE=true
DEMO_MODE=false
OPENAI_API_KEY                 # optional for the core ERP
OPENAI_MODEL                   # optional, defaults in .env.example
OPENAI_IMAGE_MODEL             # optional, defaults in .env.example
UPLOAD_DIR=/srv/uploads
FRONTEND_DIST=/srv/frontend
```

Do not add `WB_MAIN_TOKEN`, `KASPI_MAIN_TOKEN`, or `OZON_MAIN_TOKEN` to Render.
Each company enters its credentials in QOR under Management → Integrations.

## Five-minute deployment smoke test

1. Deploy from GitHub and sign in with the owner account.
2. Create a company and a marketplace integration.
3. Save credentials, open Connection status, then run Sync.
4. Run Sync again and confirm the staging record count does not increase for the
   same external records.
5. Upload a small CSV/XLSX, preview/match columns, confirm import, and inspect the
   dashboard/report.
6. Open AI Business Assistant with `OPENAI_API_KEY`; verify it states that data is
   insufficient when no ERP data exists, rather than inventing values.

## AI capability matrix

| AI module | Purpose | Data source / tools | Endpoint | Status |
| --- | --- | --- | --- | --- |
| Business Assistant | Owner questions and summary | Aggregated ERP read tools | `/api/jobs` (`assistant`) | Code path + focused tests passed; provider key required |
| Financial Analyst | Explains financial metrics | Financial summary / period comparison | `/api/jobs` (`assistant`) | Code path + focused tests passed; provider key required |
| Marketplace Analyst | Marketplace performance | Marketplace summary | `/api/jobs` (`assistant`) | Code path + focused tests passed; live token required |
| Inventory / Procurement | Stock and buying proposals | Inventory status | `/api/jobs` (`assistant`) | Code path + focused tests passed |
| Sales Analyst | Sales trends and products | Sales / product profitability | `/api/jobs` (`assistant`) | Code path + focused tests passed |
| Marketing Analyst | Advertising efficiency | Expense and revenue aggregates | `/api/jobs` (`assistant`) | Code path + focused tests passed |
| Forecast | Forecast with caveat/confidence | Historical aggregates | `/api/jobs` (`assistant`) | Code path + focused tests passed |
| Market / Niche | External-data-aware research | Restricted context | `/api/jobs` (`assistant`) | Code path + focused tests passed; external source required |
| Designer | Text/image creative task | Product-safe content tools | `/api/jobs` (`designer`) | Code path + focused tests passed; image key required |
| Accounting Assistant | Classification/explanation proposals | Accounting aggregates | `/api/jobs` (`assistant`) | Code path + focused tests passed |

AI write operations remain proposal → user confirmation → backend execution; they
are not automatically applied by the LLM.
