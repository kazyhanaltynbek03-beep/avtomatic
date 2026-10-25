# Marketplace root-cause fix — 2026-10-07

## Root causes found
1. Ozon connector fetched postings and finance accruals but did not fetch the independent product catalogue, product details, attributes, prices or stock endpoints. Therefore `marketplace-products` legitimately had zero catalogue mappings even while raw finance rows existed.
2. The new `/v1/finance/accrual/by-day` response is nested/type-id driven. The old projection expected flat `amount/operation_type` semantics, so rows were left unclassified.
3. Marketplace summary labelled ERP revenue as “API sales”. This made API sales appear as zero whenever ERP projection was waiting for FX/mapping/FIFO.
4. Ozon product metadata in unconfirmed postings was ignored because product resolution happened only for confirmed financial events.
5. UI described all incomplete states as missing FIFO, masking FX/mapping/projection problems.

## Changes
- Ozon catalogue: `/v3/product/list` + `/v3/product/info/list`.
- Ozon characteristics: `/v4/product/info/attributes`.
- Ozon stocks: `/v4/product/info/stocks`.
- Ozon prices: `/v5/product/info/prices`.
- Existing FBS/FBO posting and finance accrual pagination retained.
- Accrual type dictionary loaded from `/v1/finance/accrual/types`; nested item/non-item/delivery/commission charges are parsed without treating seller revenue as an expense.
- Raw confirmed marketplace sales/units are calculated separately from ERP-posted revenue.
- Product metadata is mapped even before a posting becomes a financial sale.
- Stock snapshot is attached to canonical product metadata without manufacturing FIFO cost.
- Product cards show photo/name/SKU/price/current marketplace stock/sold units/revenue/costs.

## Important boundary
Ozon advertising is a separate Performance API with separate OAuth2 client_id/client_secret. Seller Client-Id + Api-Key cannot lawfully provide the complete advertising campaign dataset. QOR must request/store those Performance credentials separately before full ad-campaign ingestion can be live-tested.

## Verification
- Python compileall: PASS.
- Focused marketplace/financial tests: 21 PASS.
- Full backend suite was started and passed all tests reached before the 45-second execution limit; it did not finish, so this file does not claim a full-suite pass.
- Frontend dependency installation exceeded the execution window; lint/build were therefore not verified in this run.
