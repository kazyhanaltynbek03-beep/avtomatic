# WB return sign patch — 2026-10-12

## Implemented
- Recognizes returns from both document and operation reason, camelCase and snake_case, case-insensitively.
- Normalizes WB `forPay` and `retailAmount` to negative for ordinary returns regardless of raw sign; original payload remains untouched.
- Normalizes return signs for legacy ERP settlement calculation and weekly report Excel operation rows.
- Recognizes explicit return reversals separately (review WB nomenclature before using in production).
- Existing report UI displays return quantities and net signed totals.

## Validation
- `python -m pytest tests/test_wb_weekly.py tests/test_wb_return_sign_fix.py`: 14 passed.
- Full suite stopped on pre-existing/integration test `tests/test_canonical_marketplace.py::test_normalized_api_sale_three_replays_metrics[Wildberries]`: expected revenue 10000000, got 0. Not proven related to this patch.
- React build, Docker and real WB API/PostgreSQL reconciliation NOT verified.
- Exact 1.13 KZT residual and logistics mismatch not verified.

## Caution
- Fees/commission and corrections are not globally sign-flipped: those fields have different semantics.
- Do not deploy to live seller without staging and a WB Excel reconciliation.
