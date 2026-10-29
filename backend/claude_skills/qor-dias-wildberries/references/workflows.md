# Workflows

## Standard request
- Capture question and output format.
- Confirm scope and time window; default to no write actions.
- Fetch evidence through exposed approved tools.
- Follow role algorithm.
- Deliver a concise answer plus source/as-of/scope/warnings.

## Exception workflow
If records conflict, retain both values, identify field definitions and timestamps, then create an exception for authorized review. Do not overwrite or silently choose a preferred source.

## Multi-store workflow
Use explicit store IDs; return per-store rows before any consolidated result. Confirm currency, timezone, seller legal entity and fulfillment model are compatible before aggregation.

## Escalation
Stop on cross-tenant scope, secret exposure, uncertain customer identity, unsupported write, or material accounting discrepancy. Preserve request IDs and sanitized evidence.
