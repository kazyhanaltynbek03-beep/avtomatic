# QOR AI Team

Один API-проект обслуживает шесть логически изолированных AI-ролей. API key хранится только на backend.

- Rick — главный интерфейс владельца и управленческий обзор.
- Finance — P&L, Cash Flow, расходы, дебиторка; только рассчитанные ERP-показатели.
- Analyst — SKU, каналы, динамика и закономерности.
- Buyer — остатки, партии, закуп и stock alerts; без выдуманных прогнозов.
- Marketing — Kaspi/WB/Ozon и реклама только при наличии реальных данных.
- Content — карточки/SEO/креатив; характеристики товара не придумываются.

Безопасность: AI не получает write-tools для финансовых документов. Пользовательский текст не считается системной инструкцией. При нехватке данных агент обязан сообщить об этом.

## Least-privilege ERP tools
Each AI specialist now receives only role-specific read-only tools. Finance sees finance/Cash Flow/B2B; Buyer sees inventory/products; Marketing sees channel/product metrics; Content sees confirmed product data; Analyst sees executive/channel/product analytics. Rick is the Owner orchestrator and can call all five read-only business tools. Tool outputs are server-built from deterministic ERP reports; no agent receives SQL or write access.

## Specialist execution boundaries
Each specialist can now prepare role-specific ERP changes, but no AI can commit a write by itself. Finance may prepare expenses, cash movements, counterparties and documents; Buyer may prepare purchases, stock adjustments and products; Marketing may prepare/validate/optimize marketplace card versions; Content may prepare and validate product-card drafts; Analyst remains read-only. Rick can orchestrate the complete approved action catalog. Every write is validated again by the deterministic backend, requires explicit confirmation, and is audited.

## Spreadsheet safety
CSV/XLSX are transport formats, not calculation engines. Authoritative finance stays in QOR's integer-minor-unit/Decimal backend. XLSX imports containing formulas are rejected so stale cached formula results cannot enter ERP. Exports neutralize spreadsheet-formula injection (`=`, `+`, `-`, `@`) and export authoritative values rather than business-critical formulas.
