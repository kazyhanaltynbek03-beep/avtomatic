# Full ERP pipeline fix

- WB realization can create/link a real catalogue product from seller SKU + WB product identity.
- Confirmed marketplace sale posts revenue/units even if historical FIFO batches are absent.
- Missing FIFO marks only COGS/profit incomplete; it does not suppress revenue.
- Later reprocess reconciles pending COGS without duplicating revenue.
- Marketplace summary preserves unknown profit as null instead of coercing it to 0.
- Product/category/channel profit stays unknown while COGS is pending.
- Channel table now formats costs/profit/logistics/etc as tiyn -> KZT instead of displaying raw tiyn as tenge.
- Existing sync path already runs projection automatically after each marketplace sync.
- Existing staged records require one reprocess after deployment; future syncs project automatically.

Verification:
- Python compileall: PASS
- Backend pytest: 147 passed
- Frontend lint/build: not executed locally because node_modules are not installed in this environment; Docker/Render npm ci gate remains authoritative.
