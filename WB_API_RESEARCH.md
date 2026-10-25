# Wildberries API research

Checked official Financial Reports and Accounting API documentation: <https://dev.wildberries.ru/docs/openapi/financial-reports-and-accounting> (retrieved 2026-10-09).

- The current documented period detail method is `POST https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed`.
- The request supports `period=weekly|daily`, `dateFrom`, `dateTo`, `limit`, and `rrdId`; pagination starts at `rrdId=0`, then continues using the last row's `rrdId` until HTTP 204.
- The method is documented for data from 2024-01-29 and has a limit of one request per minute per seller account. A financial token scope is required.
- HTTP 204 is the documented no-more-data response. 401 indicates an unauthorized request; 429 indicates rate limiting. The application must distinguish an empty completed result from transport/schema failures.
- Money fields in the current API are decimal strings according to WB release notes. Preserve them as decimals and preserve currency/signs.
- The official response example distinguishes the monetary `ppvzSalesCommission` (`"23.74"`) from the percentage `commissionPercent` (`24`). The older ERP assumption that the former was a percent was incorrect and has been corrected.
- An API `forPay` amount is the seller amount for the report rows; it must not be described as a bank transfer. Daily operational orders/sales are not a substitute for the weekly realization report.

The project requests the current method with weekly period, bounded dates, and `rrdId`. Real API validation is pending; this file does not claim an account's token or actual payload was tested.

Sources:

- Official endpoint documentation: <https://dev.wildberries.ru/docs/openapi/financial-reports-and-accounting>
- Official release notes: <https://dev.wildberries.ru/release-notes>
- Official API forum note about weekly report publication timing: <https://dev.wildberries.ru/forum/1397>
