# Ozon full data sync fix

- FBS v4 uses top-level postings + cursor/has_next pagination.
- FBO v3 uses offset pagination (not the FBS cursor contract).
- Finance uses /v1/finance/accrual/by-day with last_id pagination for every day in the 90-day sync window.
- Null/incomplete finance records no longer crash the whole sync.
- A valid FBO-only account can pass connection testing even when FBS access is unavailable.
- Empty API responses are distinguished from API failures; provider failures no longer masquerade as a successful zero-data sync.

Verification: Python compile PASS; connector/canonical marketplace tests 31 PASS. Frontend lint/build could not be re-run in this extracted package because node_modules is absent (eslint not installed locally); frontend source was not changed by this fix.
