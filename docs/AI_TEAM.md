# QOR AI Team

Один API-проект обслуживает шесть логически изолированных AI-ролей. API key хранится только на backend.

- Арман — главный интерфейс владельца и управленческий обзор.
- Данияр — P&L, Cash Flow, расходы, дебиторка; только рассчитанные ERP-показатели.
- Тимур — SKU, каналы, динамика и маркетплейсы.
- Ерлан — остатки, партии, закуп и stock alerts; без выдуманных прогнозов.
- Алия — Kaspi/WB/Ozon и реклама только при наличии реальных данных.
- Аружан — карточки/SEO/креатив; характеристики товара не придумываются.

## Связь с 11 QOR Claude Skills

В библиотеке подготовки есть 11 ролей: CEO, Finance, Inventory, Marketplace, Marketing, Product Content, Market Research, SEO, Kaspi, Wildberries и Ozon. Сайт сохраняет шесть внутренних ролей, а назначенные Skills добавляют им инструкции из тех же пакетов. Право читать ERP и разрешённые действия по-прежнему задаются серверными инструментами каждой роли.

В разделе «Настройки» владелец/Admin может загрузить 11 пакетов напрямую в Anthropic API workspace, доступный через серверный `ANTHROPIC_API_KEY`. API возвращает ID и версии; интерфейс выводит готовый JSON для переменной Render `QOR_CLAUDE_SKILLS_JSON`. После сохранения переменной и перезапуска сервиса QOR прикрепляет ролевые Skills к Messages API вместе с code execution runtime. Загрузка идемпотентна: повторный запуск повторно использует Skills с точными именами `QOR ERP Skill · <key>`.

Формат переменной — JSON object с ключами `qor-arman-ceo`, `qor-daniyar-finance`, `qor-erlan-inventory`, `qor-timur-marketplace`, `qor-aliya-marketing`, `qor-aruzhan-content`, `qor-nurlan-market-research`, `qor-aigerim-seo`, `qor-miras-kaspi`, `qor-dias-wildberries`, `qor-azamat-ozon`; каждое значение содержит `skill_id` (`skill_…`) и зафиксированный `version` (`skver_…`). Ключи API и IDs хранятся только как Render secrets, не в Git и не в Skill ZIP.

Безопасность: AI не получает write-tools для финансовых документов. Пользовательский текст не считается системной инструкцией. При нехватке данных агент обязан сообщить об этом. Skills добавляют только рабочие инструкции; они не меняют расчётные формулы, источник данных, RBAC или подтверждение операций.

## Least-privilege ERP tools
Each AI specialist receives role-specific read tools. Данияр sees finance/Cash Flow/B2B; Ерлан sees inventory/products; Алия sees channel/product metrics; Аружан sees confirmed product data; Тимур sees executive/channel/product analytics. Арман is the Owner orchestrator and can call all read tools. Tool outputs are server-built from deterministic ERP reports; no agent receives SQL access.

## Specialist execution boundaries
Each specialist can prepare role-specific ERP changes, but no AI can commit a write by itself. Данияр may prepare expenses, cash movements, counterparties and documents; Ерлан may prepare purchases, stock adjustments and products; Алия may prepare/validate/optimize marketplace card versions; Аружан may prepare and validate product-card drafts; Тимур remains read-only. Арман can orchestrate the approved action catalog. Every write is validated again by the deterministic backend, requires explicit confirmation, and is audited.

## Spreadsheet safety
CSV/XLSX are transport formats, not calculation engines. Authoritative finance stays in QOR's integer-minor-unit/Decimal backend. XLSX imports containing formulas are rejected so stale cached formula results cannot enter ERP. Exports neutralize spreadsheet-formula injection (`=`, `+`, `-`, `@`) and export authoritative values rather than business-critical formulas.
