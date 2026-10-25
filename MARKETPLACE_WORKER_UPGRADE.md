# Marketplace worker upgrade

This build consolidates marketplace data into product-centric ERP views without storing image binaries in PostgreSQL.

Implemented in this build:
- Unicode-safe product metadata (RU/KZ/EN/ZH and other UTF-8 text).
- Product metadata enrichment from marketplace catalogue/posting payloads.
- Remote marketplace image URLs stored in Product.media; images remain on provider CDN.
- Product-centric API `/api/marketplace-products` with image/name/SKU/brand/category/price and ERP sales/revenue/cost metrics.
- Ozon accrual classification for explicit commission/logistics/storage/advertising/penalty/acquiring operations; unknown operation types remain unclassified instead of being guessed.
- Existing WB catalogue, stock, sale and realization feeds continue through the same mapping/ERP pipeline.
- Existing Ozon FBS/FBO/finance pagination and null-safe handling retained.
- Destructive/write marketplace actions are NOT guessed or enabled generically. They must use provider-supported official endpoints and explicit permissions/confirmation.

Important API boundary:
- Seller APIs differ by provider and credential scope. QOR must expose a capability only when the connected account/API actually grants it.
- Advertising may require a separate provider API/credential scope; lack of access must be surfaced as unavailable, never as zero spend.
