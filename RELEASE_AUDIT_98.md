# QOR AI Business ERP — Production Audit 98

Date: 2026-10-06

## Scope and architecture

* `frontend/src/main.jsx` is now bootstrap-only. Shared transport, formatting,
  permissions, feedback/error boundary and loading hook live in `services/`,
  `utils/`, `components/` and `hooks/`; application composition lives in `app/`.
* Client API errors have one safe conversion path. Unstructured objects no longer
  surface as `[object Object]`.
* Marketplace flow is exactly `credentials → test connection → sync → staging`.
  Test and sync are separate UI/API actions; marketplace sync never uses jobs or
  polling. `/api/jobs` remains only for synchronous AI work.
* Financial reporting, dashboard, stock, accounting summary and AI read the
  deterministic finance service. No frontend financial formula was added.

## Real bugs fixed

1. The entry module contained all infrastructure and pages (2704 lines), making
   runtime faults and circular responsibility likely. It is now a 10-line bootstrap
   with reusable infrastructure modules.
2. API validation responses exposed raw Pydantic text; these now return a safe,
   user-readable `VALIDATION_ERROR` contract.
3. Health checks did not verify migration compatibility. `/api/health` now verifies
   database connectivity and current Alembic revision without exposing internals.
4. The financial golden suite lacked CSV parity and an existing-DB migration proof.
   Both are now automated.
5. Provider HTTP response bodies could be reflected to users. Connector errors are
   now secret-safe, with bounded retry/backoff for 429 and 5xx responses.
6. Credential verification and sync were one UI action. They are separate actions
   against the same connector; credentials update in-place and never return tokens.
7. The production bundle was one 738 kB JS chunk. Vendor chunks now keep the app
   chunk at 311 kB and chart code at 406 kB.

## Automated results actually executed

| Gate | Result |
|---|---|
| Python compile | PASS — `python -m compileall -q app` |
| Deterministic backend regression | PASS — 45 passed in 3.04s |
| Focused finance/integration regression | PASS — 32 passed in 2.91s |
| Golden financial regression | PASS — 10 passed in 0.78s |
| Clean migration and health | PASS — `upgrade head`, health reports `database: ok`, `migration: compatible` |
| Existing DB upgrade | PASS — automated test preserves old sale and gives discount `0` |
| Alembic heads | PASS — `e16f1a2b3c4d (head)` |
| `pip check` | PASS — no broken requirements |
| `npm ci` | PASS — 306 packages installed from lockfile |
| `npm run lint` | PASS — zero warnings/errors, `no-undef` is an error |
| `npm run build` | PASS — Vite production build |
| Playwright E2E | NOT PASSED — test suite and Chromium are installed, but this sandbox cannot start Playwright's web-server subprocess; run with `QOR_E2E_PASSWORD` in normal CI; no false PASS claimed |
| Docker build | NOT RUN — Docker CLI is absent in this environment |
| Full pytest suite | NOT PASSED — the suite's FastAPI `TestClient` transport hangs in this sandbox. Total collected tests in this archive: 112; 45 transport-independent tests ran successfully. |

## Financial golden dataset

All money is integer tiyn; amounts in this table are KZT for readability. Opening
stock is 12 units at 1,000 KZT. The data includes a 4-unit sale at 3,000 KZT,
1,000 KZT discount, 1-unit return/refund, 500 KZT commission, 200 KZT logistics,
300 KZT advertising, a 2-unit B2B sale (1,000 KZT unpaid), and a 1-unit write-off.
`ORDER` is separately normalized and never creates revenue, cash or stock movement.

| Metric | Expected | Manual | XLSX | CSV | Kaspi | Wildberries | Ozon |
|---|---:|---:|---:|---:|---:|---:|---:|
| Revenue | 13,250 | 13,250 PASS | 13,250 PASS | 13,250 PASS | 13,250 PASS | 13,250 PASS | 13,250 PASS |
| FIFO COGS | 5,000 | 5,000 PASS | 5,000 PASS | 5,000 PASS | 5,000 PASS | 5,000 PASS | 5,000 PASS |
| Gross Profit | 8,250 | 8,250 PASS | 8,250 PASS | 8,250 PASS | 8,250 PASS | 8,250 PASS | 8,250 PASS |
| Commission | 500 | 500 PASS | 500 PASS | 500 PASS | 500 PASS | 500 PASS | 500 PASS |
| Logistics | 200 | 200 PASS | 200 PASS | 200 PASS | 200 PASS | 200 PASS | 200 PASS |
| Advertising | 300 | 300 PASS | 300 PASS | 300 PASS | 300 PASS | 300 PASS | 300 PASS |
| Operating expenses | 1,000 | 1,000 PASS | 1,000 PASS | 1,000 PASS | 1,000 PASS | 1,000 PASS | 1,000 PASS |
| Net Profit | 6,250 | 6,250 PASS | 6,250 PASS | 6,250 PASS | 6,250 PASS | 6,250 PASS | 6,250 PASS |
| Margin | 47.17% | 47.17 PASS | 47.17 PASS | 47.17 PASS | 47.17 PASS | 47.17 PASS | 47.17 PASS |
| ROI | 89.29% | 89.29 PASS | 89.29 PASS | 89.29 PASS | 89.29 PASS | 89.29 PASS | 89.29 PASS |
| Cash / Cash Flow | 9,250 | 9,250 PASS | 9,250 PASS | 9,250 PASS | 9,250 PASS | 9,250 PASS | 9,250 PASS |
| Returns | 2,750 | 2,750 PASS | 2,750 PASS | 2,750 PASS | 2,750 PASS | 2,750 PASS | 2,750 PASS |
| Write-off / inventory valuation | 6,000 inventory | 6,000 PASS | 6,000 PASS | 6,000 PASS | 6,000 PASS | 6,000 PASS | 6,000 PASS |
| B2B receivables | 4,000 | 4,000 PASS | 4,000 PASS | 4,000 PASS | 4,000 PASS | 4,000 PASS | 4,000 PASS |

The same suite additionally proves duplicate marketplace ORDER import returns 409
and leaves financial values unchanged for Kaspi, Wildberries and Ozon.

## Marketplace status

| Provider | Code / mock verification | Live verification |
|---|---|---|
| Kaspi | Credentials lifecycle, status validation, normalization, idempotency, safe retry path PASS | LIVE VALIDATION REQUIRED — no customer token used |
| Wildberries | Credentials lifecycle, normalization, idempotency, safe retry path PASS | LIVE VALIDATION REQUIRED — no customer token used |
| Ozon | Client ID/API key lifecycle, FBS/FBO normalization, idempotency, safe retry path PASS | LIVE VALIDATION REQUIRED — no customer token used |

## AI module status

| Module | Purpose | Data source / tools | Endpoint path | Code status |
|---|---|---|---|---|
| Business Assistant | Owner questions | Aggregated deterministic report tools | `/api/jobs` kind `assistant` | CODE VERIFIED |
| Financial Analyst | Explain finance | Finance summary, expenses, cash flow, receivables | `/api/jobs` kind `assistant` | CODE VERIFIED |
| Marketplace Analyst | Channel comparison | Synced/staged marketplace + report data | `/api/jobs` kind `assistant` | CODE VERIFIED |
| Inventory / Procurement | Stock recommendations | Inventory/status aggregates | `/api/jobs` kind `assistant` | CODE VERIFIED |
| Sales Analyst | Sales trends | Sales aggregates | `/api/jobs` kind `assistant` | CODE VERIFIED |
| Marketing Analyst | Marketing analysis | Existing advertising and revenue facts only | `/api/jobs` kind `assistant` | CODE VERIFIED |
| Forecast | Bounded forecast | Historical deterministic report data | `/api/forecast` | CODE VERIFIED |
| Market / Niche | Internal observation analysis | Entered observations, no invented external data | `/api/data/niches` | CODE VERIFIED |
| Designer | Text/design workflow | Product/document context; no fake image output | `/api/jobs` kind `designer` | CODE VERIFIED |
| Accounting Assistant | Explain/classify, no autonomous writes | Finance aggregates and proposals | `/api/jobs` / action confirmation | CODE VERIFIED |

OpenAI-backed responses require `OPENAI_API_KEY`; absent/timeout/provider errors
remain contained in AI UI. No live OpenAI request was performed in this audit.

## Required Render environment

```text
DATABASE_URL
APP_ENV=production
OWNER_EMAIL
OWNER_PASSWORD
CREDENTIAL_ENCRYPTION_KEY
COOKIE_SECURE=true
DEMO_MODE=false
OPENAI_API_KEY                 # optional for the core ERP; required for live AI
OPENAI_MODEL=gpt-4.1-mini      # optional override
OPENAI_IMAGE_MODEL=gpt-image-1 # optional; only if image generation is enabled
```

No `WB_MAIN_TOKEN`, `KASPI_MAIN_TOKEN` or `OZON_MAIN_TOKEN` belongs in Render.
Marketplace credentials are encrypted per account in QOR.

## Deployment and five-minute smoke test

1. Create Render PostgreSQL and set the environment values above.
2. Deploy the repository with the included Dockerfile. It runs frontend `npm ci`,
   lint/build, `alembic upgrade head`, seed and Uvicorn on Render `PORT`.
3. Open `/api/health`; expect `status: ok`, `database: ok`, `migration: compatible`.
4. Log in, open Dashboard, Sales, Finance, Inventory and Integrations.
5. Create or select an integration, save site credentials, use **Проверить
   подключение**, then **Синхронизировать**; repeat sync and verify no duplicate
   staged records. Import the supplied CSV/XLSX shape through Preview → Confirm.

## Delivery limitations and quality assessment

There is no `.git` metadata in the supplied archive, so no Git commit was created.
Suggested commit summary: `refactor(frontend): isolate bootstrap and shared services;
fix(security): safe API/provider errors and health migration check;
test(finance): add CSV golden, credential lifecycle, and migration upgrade coverage`.

| Area | Assessment | Reason |
|---|---:|---|
| Financial engine | 9.9/10 | Deterministic golden parity across six sources, FIFO and idempotency proven |
| Backend | 9.4/10 | Strong focused regression; full TestClient suite not executable in this sandbox |
| Frontend | 9.4/10 | Clean lint/build and safer modules; full browser run blocked here |
| Database | 9.7/10 | One head, clean and existing-DB migration proofs |
| Marketplace code | 9.5/10 | Safe bounded connector flow; real credentials still required |
| Excel/CSV | 9.7/10 | XLSX/CSV parsing and golden parity verified |
| AI architecture | 9.3/10 | Tool/data boundaries verified; no live provider request |
| Security | 9.5/10 | Encrypted credentials, safe errors, RBAC paths; external pentest not run |
| UX | 9.2/10 | Existing design preserved; browser/mobile visual run not completed |
| E2E | 7.0/10 | Playwright coverage added but not runnable in this sandbox |
| Render/GitHub | 9.0/10 | Dockerfile/config reviewed; Docker daemon and Render deploy not available |

The evidence supports a high-quality code release, but **not an overall verified
9.8/10 release** until browser E2E, Docker build, Render deployment and live
Marketplace/OpenAI checks are run in a normal CI/deployment environment.
