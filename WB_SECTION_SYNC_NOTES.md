# Wildberries independent sync (2026-10-08)
- WB API fetch now supports selective streams: new_orders, order, sale, realization, stocks, products.
- Each stream is staged, projected and committed separately; failures roll back only the failing stream.
- Status includes per-stream results and errors; other marketplace connectors unchanged.
- This is a structural isolation fix, not a verified financial reconciliation against a real WB seller account.
- Follow-up production work: durable queued jobs and checkpointed page commits (currently section-level commits), independent scheduler, endpoint rate-limit tuning, actual WB statement-to-QOR reconciliation.
