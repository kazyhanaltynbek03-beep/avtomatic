# Integration contract (proposed)

Implementation status: **UNVERIFIED**. Audit existing QOR services and routes before adopting this proposed contract.

## Read request
`{"schema_version":"v1","tenant_id":"server-derived","store_ids":["authorized-store-id"],"period":{"from":"ISO-8601","to":"ISO-8601"},"filters":{},"limit":100,"cursor":null}`

Tenant and user identity must be derived from validated authentication, not trusted from model-supplied fields. Store IDs must be checked server-side.

## Response
`status`, `data`, `source`, `as_of`, `scope`, `warnings`, `request_id`, `schema_version`. Include field definitions and pagination status for financial/stock output.

## Tool use
Use only server-exposed read tools unless a separately authorized operation is explicitly presented. Do not send SQL, arbitrary URLs, raw tokens, or free-form write payloads.
