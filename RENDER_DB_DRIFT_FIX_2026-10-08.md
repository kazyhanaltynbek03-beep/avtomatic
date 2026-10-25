# Render production DB drift fix — 2026-10-08

The Render database was stamped at `f97c8e5f7007` but already contained schema objects from later migrations. Alembic therefore failed on duplicate columns such as `accounts.settlement_currency`.

Fix: migrations after the compatibility revision are now defensive/idempotent. They inspect the actual schema and add/create/alter only missing or incompatible objects. No reset, drop, or destructive production stamping is required.

Verified locally:
- clean DB -> Alembic head: PASS
- DB already at head, stamped back to f97c8e5f7007 -> upgrade head: PASS
- final head: d31f4a6b7001
- compileall: PASS
- focused migration/marketplace/WB tests: 13 passed
