# QOR Business — AI Assistant + ERP

Рабочий проект: React frontend, FastAPI backend, PostgreSQL, SQLAlchemy/Alembic, фоновые задания, FIFO-учёт, роли, импорт/экспорт и Claude API layer. Готов к локальному запуску и развёртыванию для приёмки. Перед реальной эксплуатацией обязательна проверка на целевом PostgreSQL/сервере и настройка HTTPS.

## Быстрый запуск: Docker

Требуются Docker Engine и Docker Compose v2.

```bash
cp .env.example .env
# Задайте POSTGRES_PASSWORD и OWNER_PASSWORD в .env.
docker compose up --build -d
# Пустая рабочая база + Owner:
docker compose run --rm web python -m app.seed
```

Открыть **http://localhost:8000**. Логин из OWNER_EMAIL, пароль из OWNER_PASSWORD. API-документация: **http://localhost:8000/api/docs**.

Для демонстрационной базы вместо обычного seed на **пустой базе**:

```bash
docker compose run --rm -e OWNER_EMAIL=owner@qor.local -e 'OWNER_PASSWORD=Qor-Demo-2026!' web python -m app.seed --demo
```

В `.env` выставьте `DEMO_MODE=true`, затем `docker compose up -d`. Demo создаёт 2 компании, 10 каналов/аккаунтов, 7 SKU, закупочные партии, продажи за 38 дней, расходы, платежи, B2B-клиентов и пользователей склада. Все бизнес-операции в demo синтетические.

**Тестовый Owner:** `owner@qor.local` / `Qor-Demo-2026!`.
Тест склада: `warehouse1@qor.local` / `Qor-Demo-2026!` — доступ только к первой компании, без финансовой аналитики.

Seed не изменяет существующую установку. Не загружайте demo в базу с реальными данными. Перед публичным запуском поменяйте пароль, отключите DEMO_MODE, включите COOKIE_SECURE=true и HTTPS.

## Локальный запуск без Docker

Python 3.12+, Node.js 22+.

```bash
cd frontend
npm ci
npm run build
cd ../backend
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.lock
alembic upgrade head
python -m app.seed --demo
# Linux/macOS:
export COOKIE_SECURE=false
export DEMO_MODE=true
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

В другом терминале с тем же окружением и рабочей папкой `backend`:

```bash
python -m app.worker
```

Для PowerShell переменные задаются `$env:COOKIE_SECURE="false"` и `$env:DEMO_MODE="true"`. Локально по умолчанию используется SQLite; это удобный режим проверки одного пользователя. Production — PostgreSQL через `DATABASE_URL=postgresql+psycopg://user:password@host:5432/db`. Не запускайте несколько workers/web процессов на SQLite.

Для разработки интерфейса: `cd frontend && npm run dev`; Vite проксирует `/api` на backend:8000. Для backend и worker используйте одно значение DATABASE_URL и одну папку UPLOAD_DIR.

## Что работает

- Компании, аккаунты Kaspi/WB/Ozon/Offline/B2B, товары, клиенты, пользователи: формы и связанные справочники; CRUD там, где удаление не разрушает учёт.
- Закупки из нескольких строк; партии; распределение доставки/прочих затрат; единый физический склад с юридической принадлежностью остатков; FIFO; складской журнал; ввод и списание остатков.
- Продажи, частичные возвраты в исходные партии, оплаты и задолженность B2B, документы-счета HTML, расходы и деньги отдельно от прибыли.
- Dashboard с периодами, KPI, динамикой и каналами; P&L, стоимость склада, дебиторка, медленные товары, прогноз по фактическим продажам, предупреждения.
- CSV/XLSX для товаров, продаж, изменений остатков, закупок, расходов, B2B, marketplace reports, банка: шаблон, mapping, preview, проверка, ошибки CSV, атомарное подтверждение, защита от дублей и формул в экспорте.
- AI Assistant через Claude Messages API с ограниченными backend tools; карточки по характеристикам/фото. AI Designer image editing is a separate optional OpenAI Images API integration. Калькулятор и прогноз не используют LLM.
- Market Analyst: сохранение источников/дат/наблюдений, объяснимая оценка 0–100, «Недостаточно данных» при отсутствии показателей.
- Файлы и документы с контролем доступа; Owner/Admin/Accountant/Manager/Warehouse/Marketing; Argon2, защищённые сессии, CSRF, audit log.
- Адаптивный интерфейс desktop/tablet/mobile, поиск по справочникам, таблицы с пагинацией.

## Внешние credentials

Для локального учёта внешние credentials не нужны.

| Для чего | Что получить |
|---|---|
| AI Assistant / карточки / дизайнер | ANTHROPIC_API_KEY с активным Anthropic API access и billing; Claude subscription не заменяет API access |
| Kaspi live integration | Токен продавца и доступ к нужным API своего магазина |
| Wildberries live integration | Токен с правами на нужные seller/statistics/finance API |
| Ozon live integration | Client-Id + Api-Key с нужными правами |

**Важное ограничение:** Kaspi live API в этой версии поддерживает синхронизацию заказов, чтение деталей и состава, изменение документированных статусов, справочники каталога и импорт карточек. Цены и остатки Kaspi обновляются через XML-прайс-лист, а не через REST seller API; динамический QOR feed ещё не подключён. Документированные методы финансовых взаиморасчётов Kaspi seller API отсутствуют — используйте CSV/XLSX-выгрузки. См. [KASPI_API_SETUP.md](KASPI_API_SETUP.md). WB/Ozon функции доступны согласно разделам интеграций; CSV/XLSX остаётся fallback. Demo adapter не создаёт фальшивых продаж.

Claude Messages API code is implemented. Live calls require ANTHROPIC_API_KEY. The optional AI Designer still needs OPENAI_IMAGE_API_KEY. AI-тексты и изображения — черновики для проверки владельцем; исходные финансовые числа выводятся отдельно.

## Проверки

```bash
cd backend
pytest -q
alembic check
cd ../frontend
npm run build
```

Проверенные сценарии и границы проверки: [docs/QA.md](docs/QA.md).
Архитектура, формулы, модель БД и эксплуатационные ограничения: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Сопоставление требований: [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md).
Схема PostgreSQL: [docs/schema.postgresql.sql](docs/schema.postgresql.sql).

## Структура проекта

```text
backend/
  app/
    main.py         REST API, сессии, CRUD, загрузки, импорт/экспорт
    models.py       модели, связи, ограничения и индексы
    schemas.py      валидация входящих документов
    finance.py      FIFO и детерминированные финансовые расчёты
    security.py     RBAC, company scope, CSRF, audit
    importing.py    CSV/XLSX, mapping, preview, подтверждение
    connectors.py   контракты маркетплейсов, CSV/demo adapters
    ai.py           controlled tool, Claude Messages API, optional OpenAI Images API, calculator/forecast
    worker.py       очередь заданий
    seed.py         bootstrap Owner и demo
  migrations/      Alembic migrations
  tests/           регрессионные проверки
frontend/src/      React UI, формы, графики, адаптивные стили
frontend/dist/     готовая production-сборка
Dockerfile
compose.yaml
.env.example
docs/
```

## Границы этой версии

Один независимый бизнес/workspace на установку. Только KZT, без валютной переоценки. Управленческая бухгалтерия, без автоматического НДС, ЭСФ и регламентированной отчётности. Нет автоматической сверки банковских платежей, межфирменных складских переводов, резервирования и серийного учёта. Проведённые финансовые документы неизменяемы: товарный возврат/списание — отдельные операции. Процедура сторно ошибочных расходов/денежных записей и массовое перепроведение задним числом требуют дальнейшей реализации.

Новый live connector, регламентированная бухгалтерия и налоговые правила нельзя считать выполненными только по наличию соответствующего пункта меню. Здесь эти границы указаны явно.

## AI-команда

Business Assistant усилен до команды из 6 специализированных AI-сотрудников: **Рик (AI-руководитель), Финансист, Аналитик, Закупщик, Маркетолог и Контент**. Владелец по умолчанию общается с Риком, но может открыть любого специалиста напрямую. Все шесть используют один серверный `ANTHROPIC_API_KEY`; разделение выполняется ролями, системными инструкциями и контролируемыми backend tools. Критические финансовые показатели по-прежнему рассчитывает ERP, а не LLM. AI имеет read-only доступ к разрешённому snapshot и не проводит финансовые документы.

## Accounting release gate

`backend/tests/test_accounting_invariants.py` contains additional accounting invariants for period cut-offs, cash vs accrual accounting, channel attribution, receivables, refunds payable, landed inventory and zero-cost stock. A release must not be marked production-ready unless the complete backend test suite passes against the target PostgreSQL version and the frontend production build/browser smoke tests pass on mobile, tablet and desktop.


### Marketplace report fallback
For Kaspi/Wildberries/Ozon exports use import kind `marketplace_reports`. Map `event_type`, `external_id`, `date`, `company_id`, `account_id`, `sku` and the event-specific fields. Supported event types are sale/return/stock (Russian aliases are accepted). Preview performs validation without posting financial records; confirmation posts the whole validated import in one transaction. Re-uploading an already committed identical report is rejected by fingerprint.

## AI Product Studio
Content generation is grounded in verified ERP/supplier facts. Designer transformations require an uploaded real product image, support multiple marketplace creative modes and store generated images as review-required Documents. Configure server-side `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` for text generation. Optional AI Designer image editing uses `OPENAI_IMAGE_API_KEY` and `OPENAI_IMAGE_MODEL`; never expose keys in the browser.

### Accounting / Bank / Documents foundation
QOR now includes company-scoped counterparties, bank transactions with reconciliation state, versionable tax-rule records with mandatory accountant approval flag, generated business-document records, and an accounting summary endpoint for bank flow, receivables and payables. Tax rules are configuration only: AI is not allowed to make a final tax/legal decision. Bank API remains optional; CSV/XLSX is the fallback path.

## QA status (2026-10-05)

Offline runtime QA in the available environment now completes the backend SQLite test suite: **84 passed**. During this pass regressions were fixed in Product Calculator compatibility, Niche Score, inventory adjustment test plumbing, AI tool-boundary tests, and password hashing gained an Argon2 fallback for constrained test environments while production keeps `pwdlib` as the declared dependency.

Still not certified in this environment: PostgreSQL/Alembic clean-database run (Docker/psycopg unavailable here) and frontend production build (`vite`/node_modules unavailable and package download has no network). These remain release gates before staging/production.

### AI Product Studio — 7-day optimization cycle
Product cards can now be scheduled for a deterministic review after publication readiness. The worker queues due reviews, requires a minimum evidence sample, compares conversion with the parent version when available, and writes the result into Rick's AI Workspace chat. Low-performing cards create the next optimization draft one layer at a time (main image → visuals/infographic → title/content); materially worse child versions produce a rollback recommendation. Every generated draft must pass QOR Marketplace Validator before it can be considered ready for publication. QOR never reports a live Kaspi/WB/Ozon update unless a verified marketplace write adapter actually performed it. Default policy: review in 7 days, auto-optimize enabled, auto-publish disabled, rollback enabled.

## AI Action Engine
Rick can now prepare controlled ERP write actions from natural-language requests. AI never writes directly to finance or inventory: it creates a pending action with a normalized preview. The user must explicitly Confirm or Cancel in AI Workspace. Confirmation re-validates RBAC/company scope and calls the same deterministic ERP services used by normal forms; proposal/execution/cancellation are written to Audit Log. Initial controlled actions cover purchases, sales, returns, expenses, cash movements, warehouse adjustments, products, counterparties and generated documents. User/role changes, credentials, settings and destructive deletes are intentionally excluded from AI actions.


## AI control expansion — 2026-10-05
Rick AI Action Engine now covers Product Studio actions: create marketplace card version, validate card, prepare a validated card for publication, and propose the next optimization version. All writes remain human-confirmed, permission-checked and audited. Marketplace acceptance is never faked; ready_for_publish is distinct from actual marketplace publication. Product card company scope is explicit and marketplace validation uses ERP-confirmed weight/volume fields. Backend regression suite: 94 passed.

### AI multi-step plans (2026-10-05)
Rick can now prepare a bounded plan of up to 20 validated ERP write actions from one natural-language request. A plan is preview-only until the user explicitly confirms it. On confirmation, every step is revalidated against RBAC/company scope, executed through the same domain services as manual ERP operations, and audited. Execution stops on the first error and reports partial progress; no hidden continuation occurs. Single writes continue to use the existing AI Action approval flow.

QA: backend regression suite **97 passed** after adding multi-step plans. Frontend source was updated with plan preview/confirm/cancel cards; production Vite build remains an environment gate where node_modules are unavailable.

### AI specialist execution + Excel integrity
The six AI roles are now job-scoped executors, not interchangeable chat personas. Specialists can prepare only actions in their professional scope; every write remains Preview → explicit approval → deterministic backend validation → Audit Log. Business-critical calculations never depend on LLM arithmetic or Excel formulas. XLSX imports with formulas are rejected; CSV/XLSX exports neutralize formula injection and contain backend-calculated values.

### Executive XLSX report
QOR can generate a server-side executive workbook from the same deterministic finance engine used by the UI: `GET /api/reports/executive.xlsx?start=YYYY-MM-DD&end=YYYY-MM-DD`. The workbook contains Dashboard, P&L, Cash Flow, channel sales, stock, daily dynamics and a Control sheet with reconciliation identities. Excel is a reporting surface; authoritative financial calculations remain on the backend.

### Premium responsive UI pass (2026-10-05)
- Unified professional interaction layer for desktop/tablet/mobile: restrained Lucide outline iconography, stronger hierarchy, consistent controls/cards/tables and financial tabular numerals.
- Mobile navigation upgraded to a wider app-style drawer with explicit close control, backdrop blur, larger touch targets and safe-area padding; bottom dock retained for primary actions.
- Tables remain desktop tables on wide screens and become labeled information cards on phones so reports stay readable without horizontal guessing.
- Motion uses short functional transitions, press feedback and respects `prefers-reduced-motion`; keyboard focus states are explicit.
