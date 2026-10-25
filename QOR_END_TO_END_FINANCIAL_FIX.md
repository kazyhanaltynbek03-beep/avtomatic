# QOR end-to-end financial pipeline fix

This release fixes the remaining cross-screen consistency gap rather than adding another page-specific calculation.

- Stored marketplace staging is replayed automatically on application startup after deploy/restart. Existing WB records no longer require a manual reprocess click just to reach ERP.
- Every normal marketplace sync still runs the same canonical projection immediately after staging.
- Confirmed marketplace revenue can be posted without FIFO purchase history; only COGS/profit stay pending.
- Pending FIFO is reconciled idempotently later when real purchase/opening-balance batches exist.
- Dashboard exposes both canonical `Wildberries` and legacy UI alias `WB` from the same revenue bucket, fixing the zero WB turnover card.
- Money remains integer tiyn in backend and is formatted through the shared frontend money formatter.
- Profit remains unknown (`null` / dash) when COGS is missing; QOR does not manufacture a fake profit.

Verification in this environment:
- Python compileall: PASS
- Backend pytest: 147 passed
- Frontend npm install/lint/build: NOT VERIFIED here because npm install exceeded the execution timeout and eslint was not installed. Docker/Render still runs npm ci/build in its normal build stage.

Important accounting constraint: marketplace APIs do not provide the merchant's real historical purchase cost. Exact FIFO/net profit becomes available only from real purchase/opening-balance/1C/Excel cost data. Revenue, units and marketplace expenses must still appear throughout ERP before that cost arrives.
