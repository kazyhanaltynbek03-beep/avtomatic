# QOR V12 integration cleanup
- Marketplace credentials come only from encrypted per-account IntegrationSecret records.
- Removed legacy credential_ref from API input and frontend forms.
- Removed marketplace polling job state from the Accounts/Integrations page.
- /api/accounts/{id}/sync-now executes synchronously in the web process.
- Legacy /api/jobs kind=sync is executed immediately for API accounts for backward compatibility, preventing stuck queued jobs.
- Removed legacy marketplace token ENV examples.
- Kaspi/Wildberries/Ozon connector required fields are canonical token / client_id+api_key.
- Backend regression suite: 106 passed.
