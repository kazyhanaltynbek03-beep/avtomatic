# V13 fixes
- Fixed production white screen: removed stale marketplace `job` JSX reference that caused `ReferenceError: job is not defined`.
- Marketplace integrations continue to use direct `/accounts/{id}/sync-now` calls; no marketplace job polling remains in the integrations component.
- AI/designer background jobs remain intact because they are unrelated features and have their own local job state.
- Marketplace credentials continue to come from encrypted per-account credentials, not Render marketplace token environment variables.
- Backend regression suite: 106 passed.
