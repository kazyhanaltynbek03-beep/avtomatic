# Financial and operational safety

QOR ERP remains authoritative for approved totals, cost basis, inventory and accounting logic. Never modify production calculations, filters, sync algorithms, historical facts, commission logic, logistics, cost of goods or financial aggregates.

For reconciliation preserve independent measures: order date, handover/delivery date, return date, source financial-operation date and payout date. Match by stable marketplace event/operation IDs where available. Avoid counting both an order reversal and its refund as two separate returns. Compare only equivalent currencies, scopes, periods, statuses and metric definitions.

An observed mismatch creates an exception with source values and likely causes; it does not trigger an automatic correction. Any write requires a preview and server authorization.
