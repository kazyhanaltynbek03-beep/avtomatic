# QOR AI BUSINESS ERP — Client Requirements Matrix

This file is the release-control matrix for the client's 33-section specification. `DONE` means implemented and demonstrable in the current MASTER; `PARTIAL` means a real foundation exists but the complete client requirement is not yet closed; `BLOCKED` means an external credential/provider is required. A UI mock alone is never `DONE`.

| # | Requirement | Status | Current evidence / next gate |
|---|---|---|---|
| 1 | Unified AI Business Assistant + ERP, no CRM | PARTIAL | Core ERP + AI team exist; remove/avoid CRM semantics and close remaining modules |
| 2 | Main Dashboard + periods/channels | DONE/PARTIAL | `/api/dashboard/summary` + `/api/report`: fixed today/month KPIs, selected-period margin/units/returns/ads/expenses/stock/cash/B2B debt and explicit Kaspi/WB/Ozon/Offline/B2B turnover; period comparison remains enhancement |
| 3 | Kaspi/WB/Ozon integration | PARTIAL/BLOCKED | Connector layer/import exists; live API validation requires client credentials/docs |
| 4 | Product master | PARTIAL | Product fields expanded: article/brand/supplier/country/media/currency/fx/weight/volume/prices; file media UX pending |
| 5 | Full Cost allocation | DONE | Purchase cost breakdown + quantity/weight/volume/value allocation; FIFO batch cost; invariant tests |
| 6 | Warehouse | PARTIAL | FIFO batches/movements/historical stock + explicit receipt/writeoff/defect/adjustment semantics and tests; transfer/velocity metrics remain |
| 7 | Sales | PARTIAL | Unified sales, channel costs, returns; finish discount/status marketplace mapping |
| 8 | Offline sales | PARTIAL | Offline account/channel supported; dedicated fast-entry UX pending |
| 9 | B2B financial sales | PARTIAL | Customer/company, due date, payments/debt; no CRM funnel; finish B2B KPI screen |
| 10 | Expenses | PARTIAL | Manual expenses + categories/paid/cash; project/payment method fields pending |
| 11 | Profit | PARTIAL | Deterministic P&L by period/channel with drill-down; SKU/category slices pending |
| 12 | Cash Flow | PARTIAL | Separate immutable cash ledger; opening/inflow/outflow/net/closing reconciliation, daily/category breakdown; bank-account reconciliation pending |
| 13 | Accounting/KZ tax architecture | PARTIAL | Accounting/report/RBAC foundation; tax rules, periods, approvals require implementation |
| 14 | Bank | NOT STARTED | Need bank transaction model/import and optional provider adapters |
| 15 | Documents | PARTIAL | Document storage exists; generators/templates pending |
| 16 | AI Business Analyst | PARTIAL | Six-agent backend; every assistant answer is forced through read-only deterministic `get_business_snapshot`; broaden specialist tools/comparisons next |
| 17 | AI Market/Niche Analyst | PARTIAL | Source/date/method-aware market observations + deterministic score implemented; live full-market collectors remain dependent on provider/API access |
| 18 | Niche Score | DONE | Deterministic 7-dimension score (Demand/Competition/Margin/Advertising/Seasonality/Logistics/Risk), mandatory source/date, explicit method, no score when required observations are missing |
| 19 | AI Product Calculator | PARTIAL | Deterministic engine now calculates Full Cost, FX purchase, import costs, commission, marketplace logistics, advertising, returns, gross/net profit, margin, ROI, capital, minimum/recommended price and break-even. Turnover intentionally remains unavailable without demand/history data. |
| 20 | AI Designer | PARTIAL | AI role/UI exists; real image generation/editing pipeline pending |
| 21 | AI Content | PARTIAL | Content agent exists; product-grounded generation/approval flow pending |
| 22 | AI Forecast | PARTIAL | Screen/foundation; deterministic features + confidence/backtesting pending |
| 23 | AI Alerts | PARTIAL | Alerts surface exists; scheduled rule engine pending |
| 24 | Android+iOS app | NOT STARTED (Stage 3) | Responsive web is foundation; native/PWA decision after MVP acceptance |
| 25 | One AI Assistant | PARTIAL | Rick + 5 specialists, server-side OpenAI Responses integration and forced ERP snapshot grounding; production API runtime requires OPENAI_API_KEY |
| 26 | WhatsApp Owner AI only | NOT STARTED (Stage 3) | Explicitly not client CRM; provider integration later |
| 27 | Multiple companies + consolidated | PARTIAL | Company scoping + Owner consolidated reporting; extend all modules consistently |
| 28 | RBAC | DONE/PARTIAL | Owner/Admin/Accountant/Manager/Warehouse/Marketing implemented; continue endpoint-by-endpoint QA |
| 29 | Security + audit | PARTIAL | Sessions/RBAC/audit; expand before/after values and critical-action coverage |
| 30 | Excel/CSV import/export | PARTIAL | Import preview/mapping/idempotency foundation; XLSX/export/rollback breadth pending |
| 31 | AI never invents numbers | PARTIAL | Architecture requires backend facts; enforce all agent tools and insufficient-data contract |
| 32 | MVP | PARTIAL | Core financial engine exists; matrix above defines remaining MVP gates |
| 33 | Architecture/stack/cost/timeline/ownership | PARTIAL | README/architecture exists; client-facing estimate/ownership handover pack pending |

## Release gates

1. Clean PostgreSQL migration from zero.
2. Backend tests + financial invariant/reconciliation suite green.
3. Frontend production build green.
4. Docker Compose smoke test green.
5. Mobile/tablet/desktop critical-flow QA.
6. No known Critical/High accounting or authorization defect.
7. External integrations clearly distinguish LIVE / DEMO / BLOCKED.


## Latest MASTER pass
- B2B analytics: turnover, gross/net contribution profit, average check, receivables — implemented in deterministic report backend.
- Profitability breakdown: channel, SKU/product and category — implemented; shared unallocated operating expenses remain only in consolidated P&L to avoid false attribution.
- Added automated finance tests for B2B and contribution-profit breakdowns.


## Marketplace connector hardening
- Account-scoped Kaspi/Wildberries/Ozon connector boundary, server-side credential readiness, sync state/error/cursor, worker failure persistence and CSV/XLSX fallback are implemented.
- `GET /api/accounts/{id}/connection-status` exposes readiness without exposing secret values.
- Live provider HTTP adapters remain BLOCKED until credentials and the client account API contracts are available; no fake success is reported.


## Current MASTER — marketplace report import
- Added unified `marketplace_reports` CSV/XLSX import mapping for Kaspi/WB/Ozon account data.
- Supported normalized events: sale, return, stock adjustment; financial fields include commission, logistics, advertising, payment/refund.
- SKU is resolved against the product catalog; marketplace account/company ownership is validated.
- External IDs are converted into stable unique references and the existing import fingerprint prevents committing the same report twice.
- Preview validates rows inside rollback savepoints; confirm commits atomically through the request transaction.
- Live API sync remains BLOCKED until real marketplace credentials/API access are supplied; CSV/XLSX fallback is usable independently.

### AI Product Studio hardening — 2026-10-05
- AI Content now accepts persisted ERP product facts and/or supplier facts; unknown characteristics must be listed for clarification rather than invented.
- AI Designer requires a real uploaded source product photo and uses image-edit flow, not text-only product generation.
- Designer modes: background, enhance, marketplace main photo, infographic, banner, lifestyle, advertising creative; 1–4 variants.
- Generated assets remain drafts requiring human review and retain source_document_id traceability.


## Accounting pass — 2026-10-05
- §13 Бухгалтерия — PARTIAL: counterparties, bank operations, receivable/payable summary, configurable dated tax rules and accountant-approval field added. Final Kazakhstan tax/legal automation remains blocked pending accountant-validated rules.
- §14 Банк — PARTIAL: bank transaction ledger + reconciliation state added; live bank API remains credential/provider dependent; CSV/XLSX fallback architecture retained.
- §15 Документы — PARTIAL: structured generated-document registry supports contract/invoice/waybill/act/commercial offer/payment invoice. Final PDF templates/signing are still pending.

## AI Product Studio + marketplace validation — 2026-10-05
- Product-card version registry added for Kaspi/Wildberries/Ozon with source images, facts, validation result, metrics, parent version and review date.
- QOR Validator blocks missing title/description/image and rejects ERP characteristic mismatches; final marketplace moderation is explicitly not faked.
- Designer UI now shows generated variants, lets the owner select a version, run Kaspi-oriented preflight validation and mark a validated card ready for publication.
- Ready cards receive a configurable review date (default 7 days). Metrics can be attached after publication; optimization refuses to act without measurable performance data.
- Optimization creates a child draft/version instead of silently overwriting the current card. Live auto-publish remains BLOCKED until a marketplace write API is verified for the client account.

## Product-card continuous optimization extension
- **Implemented foundation:** 7-day scheduled review worker, KPI evidence gate, V1/V2 comparison, deterministic optimize/keep/rollback decision, one-variable-at-a-time experiment plan, next-version draft creation, Rick chat notification, QOR Validator gate, per-card optimization policy.
- **Safety:** no fabricated marketplace metrics; insufficient sample blocks decisions; no fake live publication. Auto-publish remains disabled until a verified marketplace write API is connected for the client's account.


## AI control expansion — 2026-10-05
Rick AI Action Engine now covers Product Studio actions: create marketplace card version, validate card, prepare a validated card for publication, and propose the next optimization version. All writes remain human-confirmed, permission-checked and audited. Marketplace acceptance is never faked; ready_for_publish is distinct from actual marketplace publication. Product card company scope is explicit and marketplace validation uses ERP-confirmed weight/volume fields. Backend regression suite: 94 passed.

## AI natural-language control — multi-step orchestration
- **Implemented:** Rick can propose one bounded multi-step plan (1–20 allowed ERP actions) from a single chat command.
- **Safety:** no step executes before explicit plan confirmation; all steps are prevalidated and revalidated at execution; RBAC/company scope and Audit Log apply per step.
- **Failure behavior:** execution stops on first failed step and records progress/error. Previously committed business operations are not falsely reported as rolled back.
- **UX:** plan appears inside AI chat with ordered steps and Confirm entire plan / Cancel controls.

## XLSX / document automation hardening
- Executive XLSX report: implemented (Dashboard, P&L, Cash Flow, Sales, Stock, Dynamics, Control).
- Financial totals come from the deterministic backend, not spreadsheet formulas.
- Reconciliation sheet checks Gross Profit, Net Profit and Cash Flow identities before delivery.
- Formula-injection protection remains enabled for imported/exported spreadsheet text.
