# QOR source audit — 2026-10-08

Changes (focused, non-destructive):
- Weekly finance: reject malformed/null API payloads rather than silently marking empty results.
- Validate WB row objects and `rrdId` values before saving.
- Distinguish missing finance data from numeric zero in API totals.
- Refuse `.xlsx` export when a weekly report is not ready.
- Weekly scheduler checks the last four completed weeks to recover missed reports, rather than just the latest week.
- Reduce unpublished-report retry wait from 6 hours to 1 hour. No schema or migration changes.

Checks:
- `python -m compileall -q backend`: PASS.
- `pytest backend/tests/test_wb_weekly.py -q`: 2 PASS.
- Full backend tests: 161 PASS, 3 FAIL. Failures in canonical marketplace WB commission accounting (2) and Alembic migration upgrade (1). These are not fixed in this conservative patch; DO NOT deploy to production without investigating and validating.
- Frontend build not executed (node_modules unavailable). No live WB API credentials were used.

Known outstanding risks: worker is a daemon thread in the web process, no persistent page cursor, financial field mapping requires reconciliation against official WB reports, and the 3 failing backend tests require resolution. Existing DB/migrations must be preserved.
