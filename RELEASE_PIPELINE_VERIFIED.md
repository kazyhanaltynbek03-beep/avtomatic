# QOR ERP — проверенная сборка pipeline, 06.10.2026

## Реальные изменения

- Один canonical posting boundary для ручных документов, XLSX/CSV и нормализованных API-событий. Финансовые формулы и FIFO остались в существующем `finance.py`.
- Постоянные company/account-scoped привязки внешних SKU, barcode, nmId, offer_id к существующему ERP Product. Только точное сопоставление; конфликты блокируются.
- Атомарная обработка многопозиционного Ozon posting; `delivering` больше не считается продажей.
- WB: продажа и возврат имеют разные staging identities; остатки различаются по товару/размеру/складу. Статистика проходит lastChangeDate pagination; реализация — rrdId до пустого ответа; актуальные остатки — offset pagination. Добавлены карточки товаров с cursor pagination.
- WB financial endpoint: `/api/finance/v1/sales-reports/detailed`; stock endpoint: `/api/analytics/v1/stocks-report/wb-warehouses`.
- Kaspi: 90-дневное перекрывающее окно разбито на диапазоны <=14 дней; учитывается pageCount; пагинация entries; merchantProduct code извлекается через официальные product/merchantProduct relationships.
- Ozon finance: помесячные диапазоны и page_count. Комиссии/услуги идут в расходы, а не в оплату. Нераспознанные денежные операции остаются для классификации.
- Неполный API доступ виден как `partial` и предупреждения, а не молчаливый полный успех. WB pagination учитывает интервал запросов; 429 учитывает Retry-After.
- Canonical identity препятствует повторным продажам/расходам/возвратам и изменениям уже проведённых документов без сверки. Добавлена совместимость с прежними WB/Ozon references.
- API sync можно выполнять в фоне web-процесса с отдельным status polling; конкурентный sync одного account блокируется.
- Причины pending сохраняются и отображаются; есть фильтр, страницы, разовая привязка товара, повторная обработка без API и явно заданный курс валюты.
- XLSX: выбор листа/строки заголовков, обнаружение заголовка после преамбулы; CSV: пустые строки и преамбула. RU даты, неразрывные пробелы в деньгах; закупочные currency/fx_rate передаются в строки. Неоднозначное автоматическое предложение mapping не подставляет финансовую колонку.
- Исправлен исходный backend NameError `allowed_company_ids` при просмотре staging пользователем, не являющимся Owner.
- Добавлена недеструктивная Alembic migration `a07b8c9d1011`.

## Проверки

- CODE VERIFIED: Python compile; backend regression **141 passed**; npm ci, lint, build; один Alembic HEAD; upgrade пустой SQLite БД; upgrade существующей БД с сохранением продаж.
- MOCK/FIXTURE VERIFIED: нативные структуры Kaspi entries, WB sales/realization, Ozon delivered postings; WB cursor/offset/rrdId pagination; Kaspi 14-дневные окна, pageCount и merchant SKU; повторная обработка три раза; атомарность posting; FX; изменения источника; FIFO и возвраты; изоляция компаний; Excel/CSV.
- Golden dataset: все 6 вариантов источника дали **31 000 ₸** net profit. Gross revenue 100 000, return 10 000, net COGS 35 000, commission 12 000, logistics 4 000, advertising 5 000, other expense 3 000. API-ветки используют нативный fixture продажи; эквивалентные возврат и расходы подаются через canonical boundary. Это не доказательство получения каждого такого поля из live API.
- LIVE VERIFIED: **нет**. Реальные токены и база с 854 pending записями не предоставлены.
- Docker build/start: **не запускались**, Docker отсутствует в среде. Проверен запуск приложения/миграций вне Docker; это не эквивалент Docker-проверке.
- Браузерная проверка: результат в `VALIDATION_RESULTS.txt`.

## Ограничения — это не подтверждение полного Definition of Done

- 854 исходные pending записи не были доступны. Причины диагностируются по коду и schema fixtures; реальный набор нужен для окончательной сверки.
- WB/Ozon рублёвые суммы не превращаются молча в тенге. В источнике нужно задать валюту и подтверждённый курс (масштаб 10000). Курс фиксируется в нормализованном событии; изменение курса для уже проведённого события требует сверки.
- Неизвестный товар привязывается к существующему ERP товару. Новые ERP товары создаются штатным каталогом/импортом. Себестоимость и начальные партии вводятся закупкой/приходом; API-остатки не создают фиктивные бесплатные партии.
- Marketplace stock snapshots доступны для сверки, но не списываются/приходуются автоматически как физические движения. Для физического изменения используйте штатный приход/корректировку/stock import с подтверждённым delta и cost.
- Возврат в financial API сам по себе не доказывает физический приём товара. Если источник не подтверждает приём, требуется ручной ERP возврат/импорт; отрицательные корректировки расходов и изменённые проведённые суммы требуют сверки.
- Автоматическая загрузка отдельных Ozon product/stock/return endpoints и WB рекламного API в этой сборке не добавлена. Ozon FBO/FBS endpoints сохранены из исходного проекта; актуальность полного Ozon контракта не подтверждена: официальная документация недоступна при проверке (redirect loop).
- Kaspi commission/payout не выдумываются. Ozon accrual и WB forPay не считаются банковской выплатой. Подтверждённые выплаты/возвраты можно загрузить через существующие canonical Excel/CSV/manual операции.
- Исторические операции до последнего физического движения могут блокироваться действующей защитой FIFO. Хронологическая сортировка новых API событий реализована; автоматический пересчёт уже проведённой истории не выполняется.
- Фоновые sync работают в web-процессе и не являются durable worker queue. После аварийного завершения повторный запуск разрешается после 6-часовой lease; без нового запуска автоматического восстановления нет.
- Полную production-ready готовность всех интеграций, PostgreSQL concurrency и Render deployment без live проверки не заявляем.

## После загрузки GitHub → Render

Сохранить production DATABASE_URL и CREDENTIAL_ENCRYPTION_KEY. Docker CMD автоматически выполняет `alembic upgrade head`; не удалять БД и не использовать reset. После деплоя задать валюту/курс, загрузить настоящие партии с себестоимостью, привязать неизвестные товары и нажать «Обработать повторно». Проверить pending причины и сверить один период с кабинетом маркетплейса до использования прибыли для бизнес-решений.

## Использованные официальные источники

- https://dev.wildberries.ru/en/openapi/reports
- https://dev.wildberries.ru/docs/openapi/financial-reports-and-accounting
- https://dev.wildberries.ru/en/openapi/analytics
- https://dev.wildberries.ru/en/openapi/work-with-products
- https://guide.kaspi.kz/partner/ru/shop/api/orders/q3207
- https://guide.kaspi.kz/partner/ru/shop/api/orders/q3208
- https://guide.kaspi.kz/cdn/content/pay/product/documents/Magazin/api-po-zakazam.pdf
- https://docs.ozon.ru/api/seller/ — доступ не получен; текущий контракт требует live validation.

Предыдущие RELEASE_AUDIT файлы сохранены как история. Результаты именно этой сборки — данный файл и VALIDATION_RESULTS.txt.
