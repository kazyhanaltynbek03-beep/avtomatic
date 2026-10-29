# Algorithms

## Task algorithm
1. Restate objective, decision deadline and required granularity.
2. Identify required source, account(s), period and timezone.
3. Check permissions and freshness; retrieve only required fields.
4. Apply the role-specific method below.
5. Validate totals/identifiers and identify gaps.
6. Return findings, evidence, uncertainty and an actionable next step.

## Specialist method
Use ERP-approved totals as authoritative. Reconciliation compares distinct source records by account and event date/type; do not sum order value and payout as equivalent revenue. Keep gross sales, discounts, fees, logistics, refunds, adjustments, taxes and payout components separate.

## Confidence
- High: current authoritative ERP/API record, complete scope, definitions known.
- Medium: evidence is authoritative but delayed, incomplete, or one key assumption remains.
- Low: external estimate, inferred mapping, stale snapshot or undocumented metric.

Never convert a low-confidence signal into an official KPI.
