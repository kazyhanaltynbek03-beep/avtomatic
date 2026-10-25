# Ozon root fix — 2026-10-07

Focused fix only; WB logic intentionally left unchanged.

Root causes fixed:
1. Ozon `/v3/product/list` rows were not persisted as products until the optional `/v3/product/info/list` enrichment succeeded. One enrichment/API failure could therefore produce `0 товаров` despite a valid catalogue response. Base catalogue rows are now staged immediately; rich info remains enrichment.
2. Finance `/v1/finance/accrual/by-day` uses `type_id` for accrual classification. The connector incorrectly preferred `accrual_id` as a type and record identity. That could misclassify finance rows and collapse unrelated accruals onto the same staging identity. Classification now uses `type_id`; missing explicit row IDs use a deterministic content hash.
3. Unclassified finance diagnostics now include `accrued_category` when type_id is absent.

Verification:
- py_compile changed backend modules: PASS
- focused marketplace/connector/financial tests: 21 passed

Live Ozon credentials were not available in the test environment, so live Seller API validation must be done after deployment with the existing integration. Do not delete the existing account/data before testing.
