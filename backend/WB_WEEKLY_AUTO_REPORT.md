# WB weekly financial report

QOR checks the last completed Monday–Sunday reporting period in a bounded server-side loop. It calls the current Finance API period endpoint, `POST /api/finance/v1/sales-reports/detailed`, with `period=weekly`, the exact week boundaries and `rrdId` pagination. It does not call order, stock or product APIs for this job. An empty response remains `Ожидается отчёт`; 401/403 is shown as an access error, and transient failures are retried by the shared bounded request helper, including `Retry-After` for 429.

The report rows are stored under a separate `wildberries_weekly` source in the existing idempotent marketplace staging table. No ledger entry, sale or expense is created from a report row. A per-week metadata row provides the running lease, report ID, period, status, last update and error without changing PostgreSQL schema or Alembic history.

Amounts are parsed and summed as `Decimal` in native currency. `retailPriceWithDisc` is shown as turnover, `retailAmount` as realization, and `forPay` as amount due to the seller. Commission, acquiring, delivery, storage, penalty and other fields stay visible as their own WB values and are not subtracted a second time from `forPay`. Profit is `forPay − confirmed FIFO COGS`; QOR only supplies COGS when existing posted sale and return quantities match the report and use the same account currency. Otherwise it shows `Не рассчитана`.

The download is generated from the same report builder used by the website and has three sheets: `Недельный отчёт`, `Финансовые операции`, `Сводка`. Re-fetches replace only the same account/week rows keyed by `rrdId`.

## Live validation required

The official API documentation requires a Finance category token. The seller's country, token permissions and availability of period details must be confirmed with the actual account. This archive does not contain the customer's live token or a matching-period source Excel file, so no live API or client-Excel reconciliation was performed.
