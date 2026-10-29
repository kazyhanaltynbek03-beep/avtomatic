# Error handling

- 401/403: stop; do not retry with another credential or broaden access.
- 404: distinguish absent record from inaccessible scope; do not infer.
- 409: preserve current state and ask for a fresh read / human resolution.
- 429: honor documented Retry-After and service quota; cap retries.
- 5xx/network timeout: bounded exponential backoff with jitter only for idempotent reads; preserve request ID.
- Partial page/report: label incomplete and do not claim totals.
- Schema drift: quarantine unknown fields and request contract review.
- Duplicate delivery: deduplicate by source event ID plus account; do not create a second business event.
- Never log secrets or unredacted personal data.
