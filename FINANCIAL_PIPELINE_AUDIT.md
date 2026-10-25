# Financial Calculation & Data Pipeline Audit

## Result

**PASS:** Manual input, a real parsed XLSX row, and normalised Kaspi,
Wildberries and Ozon financial-event rows reach the same deterministic finance
engine and produce the same golden financial result.  All stored amounts are
integer tiyn; decimal KZT is converted by `Decimal` during import.

## Central production path

```text
Manual form ─┐
XLSX / CSV ─┼─> validation + normalisation ─> finance.py immutable posting
Kaspi ──────┤                                  ├─> FIFO batches / movements
Wildberries ┤                                  ├─> Sales / Returns / Expenses / Cash
Ozon ───────┘                                  └─> finance.report() source of truth
```

`ORDER` is deliberately not a P&L, stock or cash event. Only confirmed
`SALE`, `PAYMENT`, `RETURN`, `COMMISSION`, `LOGISTICS`, `ADVERTISING` and stock
events can change the ledger. Missing marketplace financial data is never
guessed.

## Golden dataset (1–31 October 2026)

| Event | Amount / quantity | Accounting treatment |
| --- | ---: | --- |
| Opening purchase | 12 × 1,000 ₸ | FIFO stock: 12,000 ₸ |
| Confirmed sale | 4 × 3,000 ₸ − 1,000 ₸ discount | Revenue 11,000 ₸; FIFO COGS 4,000 ₸ |
| Marketplace payment | 11,000 ₸ | Cash only |
| Commission / logistics / advertising | 500 / 200 / 300 ₸ | Separate cost events |
| Return | 1 unit, 2,750 ₸ refund | Revenue −2,750 ₸; FIFO COGS −1,000 ₸; cash −2,750 ₸ |
| Inventory write-off | 1 unit | Stock −1,000 ₸; operating expense 1,000 ₸ |
| B2B sale | 2 × 2,500 ₸; paid 1,000 ₸ | Revenue 5,000 ₸; COGS 2,000 ₸; receivable 4,000 ₸ |

## Expected versus actual (all sources)

| Metric | Expected | Manual | XLSX | Kaspi | Wildberries | Ozon |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Revenue | 13,250 ₸ | PASS | PASS | PASS | PASS | PASS |
| FIFO COGS | 5,000 ₸ | PASS | PASS | PASS | PASS | PASS |
| Gross profit | 8,250 ₸ | PASS | PASS | PASS | PASS | PASS |
| Commission | 500 ₸ | PASS | PASS | PASS | PASS | PASS |
| Logistics | 200 ₸ | PASS | PASS | PASS | PASS | PASS |
| Advertising | 300 ₸ | PASS | PASS | PASS | PASS | PASS |
| Write-off expense | 1,000 ₸ | PASS | PASS | PASS | PASS | PASS |
| Net profit | 6,250 ₸ | PASS | PASS | PASS | PASS | PASS |
| Margin | 47.17% | PASS | PASS | PASS | PASS | PASS |
| ROI | 89.29% | PASS | PASS | PASS | PASS | PASS |
| Cash / Cash Flow | 9,250 ₸ | PASS | PASS | PASS | PASS | PASS |
| Inventory valuation | 6,000 ₸ | PASS | PASS | PASS | PASS | PASS |
| Returns | 2,750 ₸ / 1 unit | PASS | PASS | PASS | PASS | PASS |
| B2B receivable | 4,000 ₸ | PASS | PASS | PASS | PASS | PASS |

## Automated verification

```text
pytest -q tests/test_financial_pipeline_golden.py
9 passed

python -m compileall -q app tests
PASS

alembic upgrade head (empty SQLite database)
PASS — e16f1a2b3c4d (head)
```

The test suite covers the five source paths, XLSX parsing, discounts, FIFO,
returns, payment, marketplace cost-event separation, write-off, B2B debt,
duplicate import prevention, and parity of Report, Dashboard, Sales listing,
Inventory, Accounting summary and AI finance tool output.

## Fixes made during this audit

1. Added a separately stored `discount` field. Revenue is now the explicit net
   revenue after discount; no frontend/AI calculation is authoritative.
2. Added Excel import support for returns.
3. Split marketplace event handling: order is non-financial; payment, commission,
   logistics and advertising are separate normalised events.
4. Classified separate marketplace commission/logistics events in the central
   report, so their metrics match direct/manual transactions.
5. Routed Accounting Summary B2B receivable through `finance.report()`; it now
   also accounts for returns and cannot diverge from Dashboard/Finance/AI.
6. Added and tested the sale-discount migration. It is compatible with SQLite
   and PostgreSQL because it avoids SQLite-incompatible `ALTER COLUMN DROP DEFAULT`.

## Honest external scope

This proves QOR's internal normalisation and finance results with automated
fixtures. It does **not** claim a live Kaspi, Wildberries or Ozon token test.
Live sync must provide the documented event types and identifiers; raw API order
payloads remain staged and cannot alter finance until a confirmed financial
report/event is imported.
