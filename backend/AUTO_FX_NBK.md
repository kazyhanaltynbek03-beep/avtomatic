# Automatic FX — National Bank of Kazakhstan

Marketplace foreign-currency postings use the official NBK exchange rate for the event date.

- Primary source: National Bank of Kazakhstan historical rates web service.
- Cache: `exchange_rates`, unique by currency + rate date.
- Historical stability: a cached historical rate is reused; today's rate never rewrites yesterday's posting.
- KZT uses identity 1.0000.
- If NBK is temporarily unavailable, the integration's manual settlement FX rate is used only when its currency matches.
- If neither official nor manual rate is available, posting stays pending with `FX_REQUIRED:<currency>` instead of inventing a conversion.

Rates are stored scaled by 10,000 (e.g. 5.37 KZT/RUB -> 53700).
