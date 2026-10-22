# Architecture, financial semantics and data contracts

Current normative handbook. Historical evidence and section-by-section provenance are in the [migration map](archive/2026-10-18/MIGRATION_MAP.md); it is not required reading for ordinary work. Current delivery/installation/task state is owned by [CURRENT_STATUS](CURRENT_STATUS.md).

[1. Architecture, storage, API and security](#c1) | [2. Money, formulas, NULL and coverage](#c2) | [3. Original → Preview → journal → financial DRAFT → GET → Close](#c3) | [4. Identity, provenance, receipts and currentness](#c4) | [5. Money, trades, settlement, fees and NKD](#c5) | [6. H0/H1/H2, membership, valuation and coverage](#c6) | [7. Returns, hypothetical results and monetary attribution](#c7) | [8. Tax, IIS, actual income, goals, risk and scenarios](#c8) | [9. Providers, freshness, reconciliation and source units](#c9) | [10. Export formats, schema versions and compatibility](#c10)

<a id="c1"></a>

Startup readiness includes the supported versioned Alembic schema path and a real DB endpoint; HTTP health/root alone cannot prove DB readiness. Never substitute `Base.metadata.create_all()` for released migrations. Repeat startup on a current schema is idempotent. SQLite restore uses application-level maintenance/serialization: prevent new DB work during the critical replacement, finish or predictably reject active work, validate and retain pre-restore backup; engine.dispose alone does not prove all checked-out connections are gone. The accepted SQLite policy retains the bounded busy timeout and does not enable WAL merely as generic cleanup; a change requires reproducible need and Windows backup/restore/sidecar checks.

## 1. Architecture, storage, API and security

The backend owns financial meaning and persisted authority. Use coherent committed read snapshots; writers reserve SQLite before final dependency validation and commit all accepted effects atomically. Native editor state is bound to positive month identity and an explicit section allowlist. No public HTTP flag can convert a strict financial writer into a partial one.

The following clauses define architecture and integrity. Historical issue identifiers are provenance, not new task assignments. Current release/runtime/UAT facts live only in S.

<a id="c1-0001-architecture-19"></a>
### Local architecture

<a id="c1-0001-architecture-19-решение"></a>
#### Решение


<a id="c1-0001-architecture-19-репозиторий-и-границы"></a>
#### Репозиторий и границы

Используется monorepo с основными каталогами:

- `backend/` — Python-приложение, доменная логика, persistence и HTTP API;
- `frontend/` — React-приложение;
- `docs/` — спецификация, backlog и ADR;
- `scripts/` — команды разработки, миграции данных и локальной эксплуатации;
- `data/` — только локальные базы, импорты, экспорты и backup; содержимое не хранится в Git.

Backend разделяется на независимую доменную часть и внешние адаптеры. Финансовые формулы и бизнес-инварианты не зависят от FastAPI, SQLAlchemy или React. API вызывает доменные сервисы, а frontend получает уже рассчитанные показатели.


<a id="c1-0001-architecture-19-backend"></a>
#### Backend

Выбран стек:

- Python;
- FastAPI для HTTP API;
- Pydantic для входных и выходных контрактов;
- SQLAlchemy 2 для persistence;
- Alembic для версионируемых миграций;
- SQLite для локального MVP.

SQLite соответствует однопользовательской локальной нагрузке, не требует отдельного сервера и поддерживает транзакции и backup API. Foreign keys включаются явно.


<a id="c1-0001-architecture-19-frontend"></a>
#### Frontend

Выбран стек:

- React;
- TypeScript;
- Vite;
- React Router;
- TanStack Query;
- Recharts;
- Tailwind CSS и простые компонентные примитивы.

Frontend отвечает за ввод, отображение и пользовательские состояния, но не дублирует финансовые формулы backend.


<a id="c1-0001-architecture-19-почему-excel-не-является-базой"></a>
#### Почему Excel не является базой

Excel остаётся источником разовой исторической миграции и визуальным референсом. Он не используется как рабочее хранилище, потому что:

- текущая книга содержит несогласованные диапазоны и ошибки формул;
- связи, ограничения и миграции схемы трудно контролировать;
- параллельное хранение исходных и расчётных значений непрозрачно;
- невозможно надёжно обеспечить транзакционное клонирование месяца и воспроизводимые расчёты.

После миграции источником истины становится SQLite; Excel не синхронизируется с приложением.


<a id="c1-0001-architecture-19-single-user-и-отсутствие-авторизации"></a>
#### Single-user и отсутствие авторизации

MVP предназначен для одного владельца и по умолчанию слушает только `127.0.0.1`. Регистрация, пароли, роли и удалённый доступ не добавляются заранее. Это уменьшает поверхность атаки и не создаёт инфраструктуру, которая не нужна локальному сценарию.

<a id="c1-0004-localhost-request-security-12"></a>
### Loopback Host and Origin policy

<a id="c1-0004-localhost-request-security-12-decision"></a>
#### Decision


<a id="c1-0004-localhost-request-security-12-host"></a>
#### Host

Every HTTP request must have a local Host authority whose hostname is exactly one of:

- `127.0.0.1`;
- `localhost`.

A valid optional TCP port is allowed. The middleware deliberately does not hardcode port `8000` because the backend port is configurable and the Vite proxy preserves its `127.0.0.1:5173` Host header. Non-local, malformed, userinfo-style, wildcard, or invalid-port Host values are rejected with D08-shaped HTTP `400 bad_request`.

The in-process Starlette `TestClient` synthetic pair (`Host: testserver` with peer `testclient`) is accepted only for the test harness. A real Uvicorn peer address cannot satisfy that condition.


<a id="c1-0004-localhost-request-security-12-unsafe-browser-requests"></a>
#### Unsafe browser requests

`GET`, `HEAD`, and `OPTIONS` are read/safe methods for this guard. Other methods are treated as state-changing.

For a state-changing request:

- if an `Origin` header is present, it must be plain `http` and its exact local authority (hostname + optional port) must equal the request Host authority;
- `Origin: null`, HTTPS/foreign origins, different local ports/authorities, malformed origins, paths/query/fragment/userinfo, and remote origins are rejected with D08-shaped HTTP `403 forbidden`;
- if `Origin` is absent but `Sec-Fetch-Site: cross-site` is present, the request is rejected as defense in depth;
- if both browser-origin signals are absent, the request is allowed. This preserves deliberate local CLI/API usage such as PowerShell `Invoke-RestMethod`, curl, seed/admin scripts, and test clients.

This is not authentication. A process already running with local machine access remains inside the trusted-machine boundary of the application.


<a id="c1-0004-localhost-request-security-12-development-flow"></a>
#### Development flow

No wildcard CORS policy is added. The canonical Vite frontend uses relative `/api` URLs and the existing proxy. With `changeOrigin: false`, a browser request from `http://127.0.0.1:5173` reaches the backend with matching local Host/Origin authority and is accepted.

Direct arbitrary cross-origin development calls are not part of the contract; use the Vite proxy.


<a id="c1-0004-localhost-request-security-12-consequences"></a>
#### Consequences

- Foreign Host values cannot read local API responses through a DNS-rebinding Host.
- Cross-origin browser writes from unrelated websites are rejected server-side.
- Normal production UI, Vite dev proxy, health/read endpoints, and origin-less local PowerShell/API calls remain usable.
- The application remains loopback-only and does not gain auth, HTTPS, cloud, telemetry, public hosting, or wildcard CORS.

<a id="c1-montheditorintegration-1"></a>
### Native month editor integration

The editor route is `/v2/data/months/:monthId`. `monthId` must be a positive safe integer; the page calls `getMonth(id)` and never selects another month after a 404. Accepted section IDs are `general` (the default), `income`, `assets`, `positions`, `payouts`, `budget`, `liabilities`, and `note`. Unknown or duplicate section values show an error without mounting a write section. The six accepted leaves are wired through the same exact-month context; component identity uses the month ID, not its snapshot date.

Leaf components receive `MonthEditorContext` from `UiV2MonthEditorPage.tsx`: the exact `month`, `readOnly` derived from its current status, a confirmed `refresh()`, `setDirty(section, value)`, and `returnToClose` when the validated `from`/`monthId`/`step` query names this same month. A leaf must clear its dirty flag on unmount, key its requests and local state to `month.id`, and ignore responses after that identity changes. It must use its own canonical API and read back its write; no shared save transaction exists. `readOnly` prohibits mutations until the user explicitly confirms reopen. Reopen only changes lifecycle through `reopenMonth` and then rereads `getMonth`; it does not close the month again or reset evidence in the frontend.

Internal editor links preserve the query and hash, including the validated return-to-close context. Navigation with a dirty leaf asks before discarding, including browser Back. Browser reload/close uses the platform's unsaved-changes prompt. Retired `/v1` and legacy month paths redirect to their native `/v2` workspaces; there is no separate editor route.

<a id="c1-data_integrity_hardening_closeout_2026-09-27-28"></a>
### Atomicity and coherent read invariants

<a id="c1-data_integrity_hardening_closeout_2026-09-27-28-what-changed"></a>
#### What changed


<a id="c1-data_integrity_hardening_closeout_2026-09-27-28-1-writes-are-atomic-against-the-state-they-validated"></a>
#### 1. Writes are atomic against the state they validated

The wave removed several “validate, then race, then commit stale state” classes:

- optimistic financial writes use database-level compare-and-swap semantics (#484);
- a reporting month cannot become CLOSED between edit validation and commit (#485);
- statement correction and append-only revision history stay coherent under competing corrections/retractions (#488);
- linked-debt balance evidence cannot be removed by two competing writers that both observed the old state (#489);
- transfer-link leg ownership/reconciliation evidence is serialized before relink/delete decisions (#490);
- salary canonical-cardinality races cannot create a second canonical salary row (#491);
- month clone reads one coherent source state and publishes the target atomically (#492).

**Effect:** concurrent owner/API actions fail with a conflict instead of silently producing hybrid or stale financial state.


<a id="c1-data_integrity_hardening_closeout_2026-09-27-28-2-composite-financial-reads-are-coherent"></a>
#### 2. Composite financial reads are coherent

#496 introduced one SQLite snapshot boundary for composite financial reads, while keeping provider/network I/O outside the read transaction and revalidating afterward.

**Effect:** one API/report response no longer mixes “before” and “after” rows from concurrent commits.


<a id="c1-data_integrity_hardening_closeout_2026-09-27-28-3-historical-payoutprovenance-data-survives-corrections-safely"></a>
#### 3. Historical payout/provenance data survives corrections safely

#486 added a supported DRAFT correction lifecycle for positions/months that already have provider payout history:

- the active financial snapshot can be removed/recreated;
- provider payout identity and append-only revisions remain auditable;
- historical reconciliation remains preserved without permanently occupying the active manual-flow slot;
- foreign-key integrity and rollback semantics remain fail-closed.

#487 keeps payout counting conservative when a previously resolved provider/manual match becomes newly ambiguous.

**Effect:** owner corrections no longer require destroying audit history, and ambiguous payout data cannot silently double-count or disappear.


<a id="c1-data_integrity_hardening_closeout_2026-09-27-28-4-performance-exactness-cannot-be-resurrected-from-stale-evidence"></a>
#### 4. Performance exactness cannot be resurrected from stale evidence

- reporting-month deletion invalidates affected cash-boundary completeness (#493);
- PRE/POST valuation capture is bound to the material event version it observed (#494);
- explicit valuation boundary groups fail closed when member dates/membership no longer match the persisted group (#495).

**Effect:** XIRR/TWRR cannot become “exact” again merely because stale evidence still exists after an underlying financial event changed.


<a id="c1-data_integrity_hardening_closeout_2026-09-27-28-5-cashaccount-identity-remains-explicit-through-aiexport"></a>
#### 5. Cash/account identity remains explicit through AI/export

#497 preserves real cash-account identity through AI bundle/review assembly; unassigned cash stays a synthetic/unassigned identity rather than being guessed onto a real account.

**Effect:** AI/export consumers cannot accidentally treat an unassigned cash row as evidence for a specific account.


<a id="c1-data_integrity_hardening_closeout_2026-09-27-28-6-exact-known-subtotal-is-now-distinct-from-complete-portfolio-coverage"></a>
#### 6. “Exact known subtotal” is now distinct from “complete portfolio coverage”

#498 froze the financial-completeness contract:

- a mathematically exact subtotal over persisted rows may remain `available / exact`;
- if an active capital-included account has no snapshot, portfolio-source coverage is `partial` with `active_account_snapshot_missing`;
- the missing account stays missing; its value is never zero-filled;
- with no usable portfolio/included-debt evidence, the capital metric is `unavailable` with `portfolio_snapshot_missing`.

Implementation was completed end-to-end:

- #536 — AI Analysis Bundle/history/capital-domain metadata;
- #537 — portfolio/financial review, capital goals and allocation/concentration support;
- #538 — canonical read-model coverage plus compact owner-facing markers on Home, Capital, Reports/history and month surfaces;
- #539 — close-readiness no longer lets unassigned cash satisfy a real cash account.

The canonical coverage helper is shared with the AI bundle so owner-facing and AI/export surfaces cannot diverge on what counts as capital evidence.

**Effect:** Hermes can show “known subtotal: exact, coverage: partial” truthfully instead of choosing between a false zero and a falsely complete total.

<a id="c2"></a>
## 2. Money, formulas, NULL and coverage

All financial arithmetic uses `Decimal`, integer minor-unit money and `ROUND_HALF_UP`; no binary float. Explicit zero, absent observation, `NULL`, `UNKNOWN`, unavailable number and partial coverage are distinct. Exact known subtotal means exact arithmetic over declared inputs, not complete financial history. Snapshot presence, syntax safety, source authority, freshness and period coverage are independent axes.

Liquid capital excludes property and subtracts included credit-card debt; reference net worth adds property less mortgage under its own support rules. Principal redemption and cashback are not passive income. The detailed inclusion, capital history and cash rules below own these formulas.

<a id="c2-master_spec-295"></a>
### Conceptual persisted entities

<a id="c2-master_spec-295-9-модель-данных"></a>
#### 9. Модель данных

Ниже приведена логическая модель. Названия таблиц могут быть уточнены, но смысл сущностей менять нельзя без обновления спецификации.


<a id="c2-master_spec-295-91-app_settings"></a>
#### 9.1. `app_settings`

Глобальные настройки:

- базовая валюта;
- локаль;
- часовой пояс;
- текущая цель пассивного дохода;
- нижняя граница полной истории пассивного дохода `passive_income_history_start_month`, допускается `null` и логически представляется как `YYYY-MM`;
- налоговые правила;
- настройки экспорта;
- путь резервных копий.

`passive_income_history_start_month=null` означает прежнее поведение: вся доступная история CLOSED месяцев допускается в исторические passive-income метрики. Граница включительна и подробно определена в ADR 0008.


<a id="c2-master_spec-295-92-reporting_months"></a>
#### 9.2. `reporting_months`

Поля:

- `id`;
- `year`;
- `month`;
- `period_start`;
- `period_end`;
- `snapshot_date`;
- `status`: `draft` / `closed`;
- `source`: `manual` / `excel_migration` / `alfa_pdf`;
- `created_at`;
- `updated_at`.

Ограничение: один отчётный месяц на комбинацию `year + month`.


<a id="c2-master_spec-295-93-accounts"></a>
#### 9.3. `accounts`

Поля:

- `id`;
- `name`;
- `account_type`: `brokerage`, `iis`, `deposit`, `savings`, `cash`, `other`;
- `external_code` — локальный идентификатор брокера;
- `status`: `active`, `frozen`, `closed`, `hidden`;
- `include_in_capital`;
- `include_in_returns`;
- `notes`.


<a id="c2-master_spec-295-94-iis_profiles"></a>
#### 9.4. `iis_profiles`

Поля:

- `account_id`;
- `iis_type`;
- `opened_at`;
- `eligible_close_at`;
- `notes`.

Юридическую допустимость закрытия приложение не определяет. Оно показывает введённую пользователем контрольную дату.


<a id="c2-master_spec-295-95-iis_contributions"></a>
#### 9.5. `iis_contributions`

Поля:

- `id`;
- `account_id`;
- `tax_year`;
- `amount`;
- `is_target_reached`;
- `notes`.


<a id="c2-master_spec-295-96-tax_benefits"></a>
#### 9.6. `tax_benefits`

Поля:

- `id`;
- `account_id`;
- `tax_year`;
- `benefit_type`;
- `status`: `planned`, `submitted`, `received`, `rejected`;
- `amount`;
- `received_at`;
- `notes`.


<a id="c2-master_spec-295-97-instruments"></a>
#### 9.7. `instruments`

Поля:

- `id`;
- `name`;
- `instrument_type`: `stock`, `bond`, `fund`, `currency`, `gold`, `other`;
- `isin`;
- `ticker`;
- `moex_secid`;
- `currency`;
- `nominal_value` для облигаций;
- `is_active`;
- `manual_price_allowed`;
- `notes`.

ISIN является предпочтительным внешним идентификатором, но не обязан быть заполнен в MVP.


<a id="c2-master_spec-295-98-position_snapshots"></a>
#### 9.8. `position_snapshots`

Поля:

- `id`;
- `reporting_month_id`;
- `account_id`;
- `instrument_id`;
- `quantity`;
- `average_cost_per_unit`;
- `market_price_per_unit`;
- `accrued_interest` при необходимости;
- `market_value`;
- `cost_basis`;
- `unrealized_result`;
- `price_date`;
- `price_source`: `manual`, `moex`, `alfa_pdf`;
- `manual_adjustment`;
- `notes`.

Все расчётные поля должны либо пересчитываться сервером, либо быть явно помечены как импортированные. Нельзя бездумно доверять значениям, присланным frontend.

Удаление позиции из DRAFT-месяца исключает её из активного снимка. Если на неё
ссылается применённая выплата провайдера или её append-only revision, строка
позиции сохраняется как историческая идентичность: `reporting_month_id = NULL`,
`archived_from_period = YYYY-MM`. Применённая выплата с этой позицией как
текущим источником также выходит из активного календаря, сохраняя provider
identity, исходную позицию и все revisions. Новую исправленную позицию для того
же месяца/счёта/инструмента можно создать отдельно. Историческая reconciliation
с ручным потоком остаётся доступной для аудита и освобождает только активную
уникальную привязку этого потока: исправленная выплата может связаться с ним,
а историческая связь не удаляется и не редактируется. Удаление ручного потока,
который служит исторической reconciliation, запрещено. При удалении DRAFT-месяца
сохраняются связанные выплаты, revisions и reconciliation с ручным потоком;
их исторические строки отвязываются от удаляемого месяца. FK остаются
ограничивающими, а удаление CLOSED-месяца по-прежнему требует reopen.


<a id="c2-master_spec-295-99-deposit_snapshots"></a>
#### 9.9. `deposit_snapshots`

Поля:

- `id`;
- `reporting_month_id`;
- `account_id`;
- `name`;
- `deposit_type`: `deposit`, `savings`;
- `balance`;
- `annual_rate`;
- `expected_monthly_interest`;
- `actual_interest_received`;
- `notes`.

Даты открытия и окончания в MVP необязательны.


<a id="c2-master_spec-295-910-cash_balances"></a>
#### 9.10. `cash_balances`

Поля:

- `id`;
- `reporting_month_id`;
- `name`;
- `amount`;
- `currency`;
- `include_in_capital`;
- `notes`.

Допускается одна агрегированная строка «Денежные средства».


<a id="c2-master_spec-295-911-income_entries"></a>
#### 9.11. `income_entries`

Поля:

- `id`;
- `reporting_month_id`;
- `income_type`: `salary`, `bonus`, `side_income`, `cashback`, `other`;
- `name`;
- `gross_amount`;
- `tax_amount`;
- `net_amount`;
- `received_at`;
- `is_recurring`;
- `include_in_cash_flow`;
- `include_in_passive_income`;
- `notes`.

Для зарплаты и премии должны храниться gross и фактический net. Расчётный net показывается отдельно.


<a id="c2-master_spec-295-912-investment_cash_flows"></a>
#### 9.12. `investment_cash_flows`

Поля:

- `id`;
- `reporting_month_id`;
- `account_id`;
- `instrument_id`, допускается `null`;
- `flow_type`: `interest`, `coupon`, `dividend`, `redemption`, `deposit`, `withdrawal`, `commission`, `tax`, `realized_profit`, `realized_loss`, `other`;
- `event_date`;
- `gross_amount`;
- `tax_amount`;
- `commission_amount`;
- `net_amount`;
- `currency`;
- `source`;
- `notes`.

Погашение облигации хранится как `redemption` и не входит в пассивный доход.


<a id="c2-master_spec-295-913-expected_cash_flows"></a>
#### 9.13. `expected_cash_flows`

Поля:

- `id`;
- `account_id`;
- `instrument_id`;
- `flow_type`: `coupon`, `dividend`, `interest`, `redemption`, `other`;
- `expected_date`;
- `gross_amount`;
- `expected_tax_amount`;
- `expected_net_amount`;
- `currency`;
- `source`;
- `source_as_of_date`;
- `is_confirmed`;
- `notes`.

В прогноз пассивного дохода погашение номинала не включается.


<a id="c2-master_spec-295-914-expense_entries"></a>
#### 9.14. `expense_entries`

Поля:

- `id`;
- `reporting_month_id`;
- `category`;
- `amount`;
- `expense_type`: `mandatory`, `comfortable`, `other`;
- `is_recurring`;
- `notes`.

В MVP основной расчёт использует только `mandatory`.


<a id="c2-master_spec-295-915-saving_allocations"></a>
#### 9.15. `saving_allocations`

Поля:

- `id`;
- `reporting_month_id`;
- `destination`;
- `amount`;
- `notes`.

Это план/факт откладывания и не является расходом для расчёта покрытия обязательных расходов.


<a id="c2-master_spec-295-916-planned_budget_lines"></a>
#### 9.16. `planned_budget_lines`

Owner-entered план расходов на выбранный reporting month. Отдельная таблица, чтобы
фактические `expense_entries` никогда не читались как бюджет и наоборот.

Поля:

- `id`;
- `reporting_month_id`;
- `category` (та же форма, что `expense_entries.category`);
- `planned_amount_kopecks`;
- `expense_type`: `mandatory`, `comfortable`, `other`;
- `notes`.

Правила:

- пустой план — валидное состояние и не блокирует закрытие месяца;
- `planned_amount_kopecks = 0` — явный ноль владельца, а не «не заполнено»;
- сопоставление план/факт идёт по точной паре `(category, expense_type)`: одинаковые
  строки суммируются с обеих сторон, односторонние ключи показываются отдельной
  строкой с отсутствующей стороной (`null`) и никогда не «склеиваются» по другому ключу;
- отсутствие стороны и явный ноль — разные вещи: `null` означает «не введено»,
  `planned_amount_kopecks = 0` — явный ноль владельца; UI показывает отсутствие как `—`,
  а не как `0 ₽`;
- план не является расходом и не участвует в расчёте покрытия обязательных расходов;
- #336 не вводит новых формул: план/факт — представление, а не расчёт.


<a id="c2-master_spec-295-917-debts"></a>
#### 9.17. `debts`

Поля:

- `id`;
- `reporting_month_id`;
- `debt_type`: `credit_card`, `other`;
- `name`;
- `current_balance`;
- `include_in_liquid_capital`;
- `annual_rate_basis_points`, допускается `null`;
- `next_due_date`, допускается `null`;
- `contract_end_date`, допускается `null`;
- `notes`.

Правила:

- `null` означает «неизвестно», `0` — реальную ставку 0%. Ставка никогда не выводится
  из суммы платежа, остатка или notes;
- `next_due_date` (ближайший обязательный платёж на `snapshot_date`) и
  `contract_end_date` (окончание договора) — разные смыслы и не смешиваются;
- при копировании месяца ставка и `contract_end_date` переносятся как стабильные
  условия, а `next_due_date` очищается: это событие, подтверждаемое в новом месяце.


<a id="c2-master_spec-295-918-property_snapshots"></a>
#### 9.18. `property_snapshots`

Поля:

- `id`;
- `reporting_month_id`;
- `name`;
- `estimated_value`;
- `mortgage_balance`;
- `monthly_payment`;
- `mortgage_annual_rate_basis_points`, допускается `null`;
- `notes`.

`null` означает «неизвестно», `0` — реальную ставку 0%; ставка не выводится из платежа,
остатка или notes. Ставка month-local и переносится при копировании месяца.

Недвижимость не входит в ликвидный капитал.


<a id="c2-master_spec-295-919-goals"></a>
#### 9.19. `goals`

Поля:

- `id`;
- `name`;
- `goal_type`: `passive_income`, `capital`, `expense_coverage`, `mortgage_coverage`, `other`;
- `target_value`;
- `target_date`, допускается `null`;
- `is_active`;
- `calculation_mode`;
- `notes`.

Основная цель MVP: 100 000 ₽ чистого пассивного дохода в месяц.


<a id="c2-master_spec-295-920-monthly_comments"></a>
#### 9.20. `monthly_comments`

Поля:

- `id`;
- `reporting_month_id`;
- `position`;
- `text`.

Нужно поддерживать несколько заметок, а не только одно большое поле.


<a id="c2-master_spec-295-921-import_sessions"></a>
#### 9.21. `import_sessions`

Заготовка для будущих импортов:

- `id`;
- `source_type`;
- `file_name`;
- `file_hash`;
- `status`;
- `started_at`;
- `finished_at`;
- `summary_json`;
- `error_text`.

This legacy conceptual import-session shape does not limit the later accepted source/provider import receipts described in C3–C5; those versioned contracts own actual persistence.

---

<a id="c2-master_spec-668"></a>
### Capital, income and cash formulas

<a id="c2-master_spec-668-101-ликвидный-капитал"></a>
#### 10.1. Ликвидный капитал

```text
liquid_assets =
    cash_balances
  + deposit_balances
  + securities_market_value
  + other_liquid_assets

liquid_capital_net = liquid_assets - credit_card_debt - other_included_debts
```

Недвижимость и остаток ипотеки не входят в `liquid_capital_net`.

Формула — известный итог по сохранённым включённым строкам. Счёт без снимка остаётся в каталоге; в сумму не входит его отсутствующее значение, и нулём оно не подставляется. Строка `CashBalance` с `account_id = NULL` — непривязанный кэш и не закрывает снимок ни одного реального счёта. Слова `available`, `exact`, `partial` и `complete` для этого итога, полнота источников портфеля и отдельная полнота cash-history/performance заданы в [`docs/financial-completeness-contract.md`](#c2-financial-completeness-contract-8).


<a id="c2-master_spec-668-102-чистая-стоимость-недвижимости"></a>
#### 10.2. Чистая стоимость недвижимости

```text
property_equity = estimated_property_value - mortgage_balance
```


<a id="c2-master_spec-668-103-покрытие-ипотеки-ликвидными-активами"></a>
#### 10.3. Покрытие ипотеки ликвидными активами

```text
mortgage_coverage_pct = liquid_capital_net / mortgage_balance * 100
mortgage_coverage_gap = liquid_capital_net - mortgage_balance
```

Если ипотека равна нулю, процент не делится на ноль; UI показывает «ипотека закрыта».


<a id="c2-master_spec-668-104-фактический-чистый-пассивный-доход-месяца"></a>
#### 10.4. Фактический чистый пассивный доход месяца

```text
actual_net_passive_income =
    deposit_interest_net
  + bond_coupons_net
  + dividends_net
  + other_capital_income_net
```

Комиссии и налоги должны учитываться только один раз. Если `net_amount` уже рассчитан в событии, повторно вычитать налог нельзя.

Кэшбэк не включается.


<a id="c2-master_spec-668-105-средний-фактический-пассивный-доход"></a>
#### 10.5. Средний фактический пассивный доход

Среднее строится по **eligible CLOSED reporting months**, а не по календарному году и не по всем календарным слотам подряд.

Глобальная настройка:

```text
passive_income_history_start_month: YYYY-MM | null
```

задаёт включительную нижнюю границу полной истории пассивного дохода. `null` означает прежнее поведение — использовать всю доступную историю CLOSED месяцев.

Месяц участвует в историческом среднем, только если он CLOSED и находится на/после границы. Сумма не определяет eligibility: настоящий CLOSED месяц с нулевым или отрицательным пассивным доходом участвует. DRAFT/reopened month не участвует до повторного закрытия. Отсутствующий календарный месяц не превращается в нулевой месяц и не увеличивает знаменатель.

До накопления 12 eligible CLOSED месяцев:

```text
actual_passive_income_avg =
    sum(actual_net_passive_income for eligible available months)
    / count(eligible available months)
```

После накопления 12 используются последние 12 **eligible CLOSED reporting-month records** по `(year, month)`. Это rolling window, а не calendar-year average.

UI показывает фактически использованный count и настроенную границу, например:

```text
Среднее за 5 закрытых месяцев из 12 · учёт с мая 2026
```

Если eligible CLOSED месяцев нет, UI сообщает отсутствие закрытой истории в выбранном периоде, а не выдаёт это за измеренный нулевой месяц.

Единый backend eligibility source применяется также к current/progress passive-income Goal и к actual-dividend history component прогноза. Подробный normative contract, migration/default и примеры определены в ADR 0008.


<a id="c2-master_spec-668-106-прогнозный-чистый-пассивный-доход"></a>
#### 10.6. Прогнозный чистый пассивный доход

```text
forecast_12m_net_passive_income =
    expected_deposit_interest_next_12m
  + expected_coupon_net_next_12m
  + expected_dividend_component
  + other_expected_capital_income
```

Для MVP:

- ожидаемые купоны берутся из ручного календаря ожидаемых выплат;
- проценты по депозитам могут рассчитываться из текущего остатка и ставки;
- дивидендная часть строится из фактического среднего net dividends по той же eligible CLOSED history и той же lower boundary, что определены §10.5 / ADR 0008; после 12 eligible месяцев используется rolling last-12;
- граница исторического passive income не фильтрует forward-looking `expected_cash_flows` купонов, процентов и прочего ожидаемого дохода;
- погашения облигаций исключаются;
- налоги учитываются, если известны, иначе сумма маркируется как приблизительная.

```text
forecast_monthly_net_passive_income = forecast_12m_net_passive_income / 12
```


<a id="c2-master_spec-668-107-прогресс-к-цели"></a>
#### 10.7. Прогресс к цели

Для passive-income Goal текущее значение и прогресс используют фактическое rolling average из §10.5 (R02-27), а C04 forecast остаётся отдельной прогнозной метрикой:

```text
passive_income_goal_progress_pct =
    actual_passive_income_avg / passive_income_goal_target * 100
```

Точная цель берётся из canonical Goals source of truth, а не hardcode UI. Прогнозный passive income показывается рядом отдельно и не подменяет фактический current value цели.


<a id="c2-master_spec-668-108-покрытие-обязательных-расходов"></a>
#### 10.8. Покрытие обязательных расходов

```text
mandatory_expense_coverage_pct =
    forecast_monthly_net_passive_income / mandatory_expenses * 100
```

Если обязательные расходы равны нулю, UI не показывает бесконечность.

Дополнительно:

```text
passive_income_minus_mandatory_expenses =
    forecast_monthly_net_passive_income - mandatory_expenses
```


<a id="c2-master_spec-668-109-остаток-денежного-потока-месяца"></a>
#### 10.9. Остаток денежного потока месяца

```text
monthly_cash_balance =
    actual_net_salary
  + actual_net_bonus
  + side_income_net
  + cashback
  + other_income
  + actual_net_passive_income
  - mandatory_expenses
  - other_recorded_expenses
  - saving_allocations
```

Кэшбэк участвует в денежном потоке, но не в пассивном доходе.

Для `income_entries` месячный денежный поток учитывает только строки с
`include_in_cash_flow=true`. `OTHER` с `include_in_passive_income=false`
попадает в отдельный `other_income`; пассивный `OTHER` учитывается через
`actual_net_passive_income` только если он также включён в cash flow.
Пассивный `OTHER` с `include_in_cash_flow=false` остаётся в аналитике
фактического пассивного дохода, но исключается из остатка денежного потока.


<a id="c2-master_spec-668-1010-депозиты"></a>
#### 10.10. Депозиты

Упрощённый ожидаемый среднемесячный доход:

```text
expected_monthly_interest = balance * annual_rate / 12
```

Фактически полученные проценты хранятся отдельно и не должны заменяться прогнозом.


<a id="c2-master_spec-668-1011-позиция-ценной-бумаги"></a>
#### 10.11. Позиция ценной бумаги

```text
market_value = quantity * market_price_per_unit + accrued_interest_if_applicable
cost_basis = quantity * average_cost_per_unit
unrealized_result = market_value - cost_basis
```

Для облигаций нужно чётко договориться о единицах цены. Внутри доменной модели хранить денежную цену за штуку. Процентную котировку преобразовывать на границе импорта/интерфейса.


<a id="c2-master_spec-668-1012-инвестиционный-результат-mvp"></a>
#### 10.12. Инвестиционный результат MVP

В ручном MVP показываются раздельно:

- фактический денежный доход;
- изменение рыночной стоимости;
- нереализованный результат текущих позиций;
- комиссии;
- налоги;
- пополнения и выводы.

Нельзя называть простое изменение стоимости портфеля «доходностью», если не учтены внешние потоки.

<a id="c2-financial-completeness-contract-8"></a>
### Known subtotal and distinct coverage axes

This document defines how a mathematically exact sum of persisted rows relates to coverage words. It does not change `MASTER_SPEC` §10.1 arithmetic, ADR 0007 composition classes, close guards, or performance formulas.


<a id="c2-financial-completeness-contract-8-1-three-axes"></a>
#### 1. Three axes

These words are separate. A single field must not collapse them.

| Axis | Words | Meaning |
|---|---|---|
| Known subtotal | the canonical formula over persisted included rows that exist | Integer-kopeck sum. A required account with no snapshot stays in the catalog. Its snapshot value is absent from this sum and is never stored or displayed as `0.00`. |
| Availability | `available`, `unavailable` | `available` means the numeric claim is present. `unavailable` means the value is withheld (`null`), including when no capital evidence exists. |
| Precision | `exact`, `approximate`, `unknown` | `exact` means the number is the exact minor-unit result of its declared formula over its declared inputs. |
| Coverage | `complete`, `partial`, `unavailable` | Whether the named source set for that claim is fully represented. |

`exact` is precision. `partial` and `complete` are coverage. An available exact known subtotal can sit beside partial coverage.

`unavailable` on a metric withholds the number. `unavailable` on coverage means the named source set cannot be judged or the claim has no usable evidence. Read the field, not the word alone.


<a id="c2-financial-completeness-contract-8-2-portfolio-source-coverage"></a>
#### 2. Portfolio-source coverage

This claim answers one question: for this reporting month, does every account required for liquid capital have a persisted snapshot?

**Required set (read time, current catalog).** An account is required when `status = active` and `include_in_capital = true`. Hermes has no effective-dated capital-inclusion history. ADR 0007 does not snapshot global account flags. Until a separate architecture adds that history, this current catalog is the required set. Closed-month immutability protects persisted month rows. It does not freeze this coverage label.

**Represented.** The month represents that account when it has at least one of:

- a position snapshot for the account;
- a deposit snapshot for the account;
- a cash-balance row whose `account_id` is that account.

`CashBalance.account_id = NULL` is synthetic/unassigned cash, the same identity as integrated #497. It does not satisfy the snapshot requirement of any real account, including an account with `account_type = cash`. When `include_in_capital` is true, that row's amount can still sit in the known subtotal as unassigned cash. It is not a catalog account.

An explicit zero amount is a real snapshot. Frozen, closed, hidden, and `include_in_capital = false` accounts are outside this required set.

**Outcomes.**

- `complete` — every required account is represented.
- `partial`, reason `active_account_snapshot_missing` — at least one required account is missing a snapshot, and the month still has some persisted capital or included-debt evidence. The known subtotal stays `available` and `exact`.
- Capital metric `unavailable`, reason `portfolio_snapshot_missing` — the month has no persisted portfolio or included-debt snapshot rows. The total is withheld. It is not published as `0.00`.

`stale_valuation` stays a freshness fact. A stale price keeps the persisted position and does not by itself make portfolio-source coverage partial. `future_dated_valuation` stays the stronger existing rule: the affected capital value is withheld for that period. `draft_value` / `draft_month_incomplete` stay additional draft defects. A closed month does not carry them.


<a id="c2-financial-completeness-contract-8-3-reproduced-two-account-case"></a>
#### 3. Reproduced two-account case

Closed reporting month:

- active capital-included account A has a snapshot worth `100.00` RUB;
- active capital-included account B has no position, deposit, or cash snapshot;
- the `100.00` RUB figure is the sum of the included rows that exist.

Canonical reading on every surface:

| Claim | Result |
|---|---|
| Known subtotal `liquid_capital_net` | `100.00` RUB |
| Availability of that subtotal | `available` |
| Precision of that subtotal | `exact` |
| Portfolio-source coverage | `partial` |
| Reason | `active_account_snapshot_missing` |
| Account B | stays in the account catalog and in missing-account metadata. Its snapshot value is absent from the subtotal and is never `0.00` |
| Complete liquid capital / complete portfolio value | not established |

Included debt or extra persisted rows stay inside the known subtotal. They do not cure account B.

A consumer may show `100.00` as the known subtotal. The same payload or screen must carry `partial` / `active_account_snapshot_missing`. A consumer that cannot carry that marker must not present `100.00` as the period's complete capital.

Close stays allowed. The existing close-readiness warning is about the missing account. It is not an instruction to null the period subtotal, and it is not a hard close blocker.


<a id="c2-financial-completeness-contract-8-4-what-historycoverage--complete-attests"></a>
#### 4. What `history.coverage = complete` attests

`reporting_history[].coverage` is the point-level coverage aggregate already used for that history point: portfolio-source coverage, draft, gap versus the previous stored reporting month, future-dated included valuation, property-quality codes on that point, and passive-history-before-start.

`complete` means none of those defect classes fired for that point. Portfolio-source incompleteness is one of those classes. In the two-account case the point is `partial` with `active_account_snapshot_missing`.

That field does not attest:

- cash-boundary / cash-history completeness;
- performance computability;
- price freshness;
- salary-tax history (`salary_tax_context.history_coverage` is a separate claim);
- a gap-free calendar across the whole archive (`coverage.missing_calendar_periods` / `reporting_history_gap`).

`coverage.domains.portfolio` is the selected period's portfolio-source coverage. `coverage.domains.capital` is partial when any reporting-history point has `active_account_snapshot_missing`. `coverage.domains.history` on the financial review follows the same point coverage through historical dynamics.

`total_net_worth` remains unavailable (`no_authoritative_aggregate` / `total_net_worth_unavailable`). That partial is a different claim. It can appear together with `active_account_snapshot_missing`. One reason does not stand in for the other.


<a id="c2-financial-completeness-contract-8-5-source--coverage-matrix"></a>
#### 5. Source / coverage matrix

The two-account case, same closed period.

| Surface | `100.00` means | Coverage that travels with it | Canonical behavior |
|---|---|---|---|
| Home and month detail via closed-report comparison | known subtotal | `partial` / `active_account_snapshot_missing` | implemented in #538 |
| v2 Capital: net, composition, allocation shares | known subtotal; shares are shares of that subtotal | marker on the net; allocation support partial | implemented in #537/#538 |
| v2 Reports / history archive | known subtotal of each closed point | per-point marker | implemented in #538 |
| Closed-to-closed delta | exact difference of the two known subtotals | partial when either endpoint is partial | implemented in #538 |
| Month close readiness and deterministic insight | warning for the missing account | warning remains non-blocking | implemented in #539; unassigned cash does not satisfy a real account |
| AI bundle `reporting_history[]` KPI | known subtotal, `available` / `exact` | point coverage + metric reason | implemented in #536 using canonical portfolio-source coverage |
| AI bundle `coverage.domains.capital` | — | `partial` with the same reason | implemented in #536 |
| AI bundle `current_portfolio.coverage` and `coverage.domains.portfolio` | — | `partial` / `active_account_snapshot_missing` | aligned with the same identity contract |
| Portfolio-review and financial-review capital section | known subtotal | snapshot reason in addition to the separate net-worth reason | implemented in #537 |
| Financial-review `coverage.domains.history` | — | `partial` once the history point is partial | implemented in #537 |
| Capital goal current value / progress | known subtotal | same snapshot reason; arithmetic unchanged | implemented in #537 |
| Allocation / concentration denominator | shares of the known subtotal | support `partial` with the same reason | implemented in #537; shares are not recomputed |
| Performance availability, XIRR, TWRR, valuation point | not this subtotal | independent fail-closed prerequisites | unchanged and separate |
| Cash-boundary coverage | unrelated owner attestation of cash crossings | independent `complete` / `unknown` | unchanged and separate |

Comparison, goals, and allocation keep their existing arithmetic. The completed follow-ups changed coverage/support metadata and owner-facing explanation, not the underlying capital formula.


<a id="c2-financial-completeness-contract-8-6-current-catalog-and-historical-membership"></a>
#### 6. Current catalog and historical membership

| Question | Rule |
|---|---|
| Which accounts are required for this portfolio-source claim? | Current `active` + `include_in_capital`. Read time. |
| Which rows enter the known subtotal? | The rows `liquid_capital_for_month` already includes. Current `include_in_capital` still filters deposits and securities. This contract does not change that sum. |
| Which accounts are in a historical performance scope? | `account_performance_scope_memberships` only. Current `include_in_returns` must not rewrite that history. |
| Account in capital, outside performance membership | Affects portfolio-source coverage and the known subtotal. It does not become a performance member. |
| Account in historical performance membership, outside capital | Can block performance. It is not a required capital snapshot. |

Changing `status` or `include_in_capital` can change the coverage label of an already closed month without rewriting snapshot amounts. That is the accepted interim. Effective-dated capital membership is out of scope.


<a id="c2-financial-completeness-contract-8-7-performance-prerequisites-stay-separate"></a>
#### 7. Performance prerequisites stay separate

Performance quality `exact` means the accepted performance prerequisite set is satisfied. Capital precision `exact` means the known-subtotal arithmetic is exact. Those two uses of `exact` must not be copied onto each other.

For a valuation point, each account selected by historical performance membership still needs positions, deposits, and performance cash, or the point stays non-exact with `not_computable_scope_coverage_incomplete`. A single position snapshot of `100.00` RUB does not satisfy that set. Portfolio-source coverage is the only claim for which one position, deposit, or account-linked cash snapshot represents that real account.

Cash-boundary coverage (`docs/r08-01c-performance-availability.md`) is an owner attestation that cash crossings are known. It stores no amount. Snapshot presence does not prove it. Its absence does not change the capital known subtotal and does not create `active_account_snapshot_missing`.


<a id="c2-financial-completeness-contract-8-8-completed-follow-up-implementation"></a>
#### 8. Completed follow-up implementation

All four accepted implementation slices are complete on canonical `main`. They did not change formulas, close blockers, performance component rules or cash-boundary rules.


<a id="c2-financial-completeness-contract-8-f1--ai-analysis-bundle-metadata--completed-in-536"></a>
#### F1 — AI analysis bundle metadata — completed in #536

`backend/src/hermes_finance/services/ai_analysis_bundle.py` and `backend/tests/test_ai_analysis_bundle_export.py`.

For each reporting-history point, when portfolio-source coverage is partial:

- `reporting_history[].coverage` is `partial` and includes `active_account_snapshot_missing`;
- `liquid_assets_total`, `included_debts`, and `liquid_capital_net` stay the known subtotal: `available`, `exact`, value present;
- those three metrics include `active_account_snapshot_missing` in `reason_codes`;
- `coverage.domains.capital` is `partial` with that reason when any point has it.

Keep `portfolio_snapshot_missing` for a month with no capital evidence, value `null`. Keep the selected-portfolio block as it is: the missing account stays in the account catalog and in `missing_snapshot_account_refs`. `test_cash_snapshot_detection_is_account_specific` is the closest fixture; extend it to the history point and the KPI reason list. Reason codes are already free-form strings in the bundle schema. Emitting a new status/reason combination changes instance meaning, so the follow-up records a bundle `schema_version` minor bump under `docs/AI_ANALYSIS_BUNDLE.md`.


<a id="c2-financial-completeness-contract-8-f2--review-goals-and-allocation-metadata--completed-in-537"></a>
#### F2 — Review, goals, and allocation metadata — completed in #537

`portfolio_review_package.py`, `ai_financial_review.py`, and their tests.

- Capital-section reasons include `active_account_snapshot_missing` when the selected point has it, and still include the existing net-worth reason.
- The capital metric stays `available` / `exact`.
- Historical-dynamics coverage follows the history point, so the review history domain becomes `partial`.
- A capital goal's current value and progress keep the known subtotal and carry the same reason.
- Allocation / concentration support becomes `partial` with the same reason when its denominator is that partial subtotal. Shares are not recomputed.


<a id="c2-financial-completeness-contract-8-f3--owner-facing-marker--completed-in-538"></a>
#### F3 — Owner-facing marker — completed in #538

Add portfolio-source coverage, computed with the section 2 rule, onto the read models that already emit the known subtotal: month dashboard liquid capital, closed-report comparison (including the delta), and capital composition. Render that marker beside the figure on Home, month detail, Capital and Reports/history. Do not reimplement the required-account rule in React. Do not hide or restate `100.00`. The missing account stays visible in the account list.


<a id="c2-financial-completeness-contract-8-f4--close-readiness-cash-identity--completed-in-539"></a>
#### F4 — Close-readiness cash identity — completed in #539

`backend/src/hermes_finance/services/close_readiness.py`, and the deterministic insight that repeats its warning.

A `CashBalance` row with `account_id = NULL` must not count as the snapshot of any real account. The AI bundle missing-snapshot check already requires a matching `account_id` (#497). Leave the known-subtotal formula unchanged. This docs change does not edit that detector.


<a id="c2-financial-completeness-contract-8-9-non-goals"></a>
#### 9. Non-goals

- No formula, migration, or UI change in the #498 contract change.
- No new account-membership history.
- No change to close hard guards.
- No weakening of performance fail-closed behavior.
- No use of cash-boundary coverage as a proxy for missing snapshots.
- No freshness or property-identity redesign.
- No second capital total that zero-fills account B.
- No removal of a missing account from the catalog or from missing-account metadata.
- No use of unassigned cash as the snapshot of a real account.

<a id="c2-0003-income-cash-flow-inclusion-18"></a>
### Income inclusion and exact monthly cash balance

<a id="c2-0003-income-cash-flow-inclusion-18-decision"></a>
#### Decision


<a id="c2-0003-income-cash-flow-inclusion-18-1-meaning-of-include_in_cash_flow"></a>
#### 1. Meaning of `include_in_cash_flow`

`include_in_cash_flow` is the normative inclusion switch for whether **that `IncomeEntry.net_amount` contributes to `monthly_cash_balance`**.

- `true` — the entry contributes to monthly cash balance according to the matrix below;
- `false` — the entry does not contribute to monthly cash balance.

The flag affects only the monthly cash-balance calculation. It does **not** remove the row from storage and does not change unrelated analytics such as salary-tax history, normalized bonus, or actual passive-income classification.


<a id="c2-0003-income-cash-flow-inclusion-18-2-other-non-passive-income-gets-an-explicit-cash-balance-bucket"></a>
#### 2. `OTHER` non-passive income gets an explicit cash-balance bucket

`IncomeType.OTHER` with:

- `include_in_passive_income=false`;
- `include_in_cash_flow=true`

is ordinary non-passive cash income and contributes to a new explicit `other_income` cash-balance bucket.

It must not be relabeled as `side_income` and must not be placed in the passive-income bucket.

The cash-balance domain/API breakdown therefore gains `other_income` as a `MoneyValue`/`RubleAmount` field.


<a id="c2-0003-income-cash-flow-inclusion-18-3-other-passive-income-is-counted-exactly-once"></a>
#### 3. `OTHER` passive income is counted exactly once

For `IncomeType.OTHER` with `include_in_passive_income=true`, the entry remains part of the actual passive-income metric defined by R02-04.

For monthly cash balance:

- if `include_in_cash_flow=true`, its amount contributes **only through the cash-balance `passive_income` subtotal**;
- if `include_in_cash_flow=false`, it remains visible in actual passive-income analytics but is excluded from monthly cash balance.

It must never also be added to `other_income`.

Consequently, `CashBalanceBreakdown.passive_income` means the passive-income amount that is eligible for monthly cash flow. It may be lower than the dashboard's full `passive_income_actual` when an `OTHER` passive income row explicitly has `include_in_cash_flow=false`.

Passive sources that are not `IncomeEntry` rows (for example deposit snapshots and valid investment cash flows) have no `include_in_cash_flow` flag and keep their existing cash-balance behavior.


<a id="c2-0003-income-cash-flow-inclusion-18-4-typeflag-matrix"></a>
#### 4. Type/flag matrix

| Income type | `include_in_cash_flow` | `include_in_passive_income` | Passive-income metric | Monthly cash balance |
|---|---:|---:|---|---|
| `salary` | `true` | `false` | no | `salary_net` |
| `salary` | `false` | `false` | no | excluded |
| `bonus` | `true` | `false` | no | `bonus_net` |
| `bonus` | `false` | `false` | no | excluded |
| `side_income` | `true` | `false` | no | `side_income_net` |
| `side_income` | `false` | `false` | no | excluded |
| `cashback` | `true` | `false` | no | `cashback` |
| `cashback` | `false` | `false` | no | excluded |
| `other` | `true` | `false` | no | `other_income` |
| `other` | `false` | `false` | no | excluded |
| `other` | `true` | `true` | yes, `other_capital_income` | `passive_income`, exactly once |
| `other` | `false` | `true` | yes, `other_capital_income` | excluded |

For `salary`, `bonus`, `side_income` and `cashback`, `include_in_passive_income=true` remains invalid under R02-04 and is not a valid matrix state.


<a id="c2-0003-income-cash-flow-inclusion-18-5-normative-monthly-cash-balance-formula"></a>
#### 5. Normative monthly cash-balance formula

After R02-19:

```text
monthly_cash_balance =
    included_salary_net
  + included_bonus_net
  + included_side_income_net
  + included_cashback
  + included_other_income_net
  + included_passive_income
  - mandatory_expenses
  - other_recorded_expenses
  - saving_allocations
```

Where `included_*` for `IncomeEntry` sources means `include_in_cash_flow=true`, and `included_passive_income` excludes only passive `IncomeEntry.OTHER` rows whose `include_in_cash_flow=false` while preserving all other canonical passive-income sources.


<a id="c2-0003-income-cash-flow-inclusion-18-6-write-contract"></a>
#### 6. Write contract

No new write-time incompatibility is introduced between the two flags beyond R02-04.

In particular, `OTHER + include_in_passive_income=true + include_in_cash_flow=false` is valid: the row is passive income for analytics but intentionally excluded from monthly cash balance.

Existing create defaults remain unchanged:

- `include_in_cash_flow=true`;
- `include_in_passive_income=false`.


<a id="c2-0003-income-cash-flow-inclusion-18-7-backward-compatibility-and-closed-months"></a>
#### 7. Backward compatibility and closed months

R02-19 must not add a migration that rewrites existing income rows or guesses new flag values.

Existing persisted booleans are taken at face value:

- rows with `include_in_cash_flow=true` keep participating according to their type;
- rows with `include_in_cash_flow=false` begin to be correctly excluded from cash balance;
- existing `OTHER + passive=false + cash_flow=true` rows begin to contribute through `other_income`.

The current month editor writes `include_in_cash_flow=true` for its salary/bonus/side-income/cashback rows, so ordinary rows created through the existing UI are expected to keep the same cash-balance inclusion behavior.

Closed-month rows remain immutable. Because cash balance is a derived read-time calculation rather than a persisted monthly total, historical cash-balance output may change for closed months that already contain one of the affected flag combinations. This is an intentional formula correction, not a data rewrite.

To make that change observable, R02-19 must advance the externally reported monthly-summary/dashboard `calculation_version` from `v1` to `v2` (or the next canonical version if it has already advanced before implementation).


<a id="c2-0003-income-cash-flow-inclusion-18-8-implementation-constraints-for-r02-19"></a>
#### 8. Implementation constraints for R02-19

R02-19 should:

- filter `salary`/`bonus`/`side_income`/`cashback` cash-balance sums by `include_in_cash_flow=true`;
- add the `other_income` field to cash-balance input, breakdown and API DTO;
- sum `OTHER + passive=false + cash_flow=true` into `other_income`;
- include `OTHER + passive=true + cash_flow=true` through `passive_income` only;
- exclude `OTHER + passive=true + cash_flow=false` from the cash-balance passive subtotal without removing it from actual passive-income metrics;
- preserve the R02-04 source-of-truth and deposit-interest invariants;
- update `MASTER_SPEC.md` §10.9 and relevant cash-balance contract/docstrings to the accepted formula before R02-19 is marked DONE;
- advance the public monthly-summary/dashboard calculation version;
- use integer kopecks/`RubleAmount` only; no binary float;
- avoid DB migration unless an implementation-only schema need is independently proven (none is required by this contract).

Exposing `include_in_cash_flow` as a new user-facing control in the month editor is **not required by R02-19**. That is a separate UI choice; R02-19 is responsible for making the already persisted/API-visible flag semantically correct.

<a id="c2-0007-capital-composition-history-20"></a>
### Closed capital history and asset-stack denominator

<a id="c2-0007-capital-composition-history-20-decision"></a>
#### Decision


<a id="c2-0007-capital-composition-history-20-1-history-contains-closed-reporting-months-only"></a>
#### 1. History contains CLOSED reporting months only

Capital-composition history contains only `ReportingMonth.status == closed` months.

Draft months are excluded even if they currently contain positions or balances. Reopening a previously closed month removes it from this historical result until it is closed again, matching the existing meaning of closed-month history elsewhere in the application.

Returned points are ordered strictly by `(year ASC, month ASC)`.


<a id="c2-0007-capital-composition-history-20-2-missing-calendar-months-are-unknown-not-zero"></a>
#### 2. Missing calendar months are unknown, not zero

The API returns one point per existing CLOSED reporting month and does not create synthetic reporting months.

If May and July are CLOSED while June is absent or draft, the result contains May and July only. June is **unknown history**, not a month of zero assets.

The frontend may insert a presentation-only gap marker with `null` chart coordinates so the visual series breaks at June. It must not insert zero-valued financial data, interpolate between May and July, or backfill June from either neighboring month.


<a id="c2-0007-capital-composition-history-20-3-asset-class-taxonomy-is-exactly-the-existing-allocation-taxonomy"></a>
#### 3. Asset-class taxonomy is exactly the existing allocation taxonomy

The historical contract reuses these five classes in this canonical order:

1. `cash`
2. `deposits`
3. `stocks`
4. `bonds`
5. `gold_other`

No second classifier is introduced.

For every returned CLOSED month all five classes are emitted exactly once. A class with no rows in that known month is an explicit known zero for that class.

`gold_other` keeps the existing meaning: all position instrument types other than `stock` and `bond`, plus `other_liquid_assets`. R03-11 does not split gold, funds, currency or other instruments into new historical classes.


<a id="c2-0007-capital-composition-history-20-4-per-month-values-reuse-the-existing-accepted-valuation-semantics"></a>
#### 4. Per-month values reuse the existing accepted valuation semantics

Each historical point is calculated from that reporting month's own persisted snapshot data using the same source of truth as current `asset_allocation` and `liquid_capital_for_month`:

- cash: included cash balances for that reporting month;
- deposits: included deposit snapshot balances for that reporting month;
- stocks: included position snapshot market value where instrument type is `stock`;
- bonds: included position snapshot market value where instrument type is `bond`;
- gold/other: included position snapshot market value for all other instrument types plus `other_liquid_assets`.

All money remains RUB `MoneyValue` with decimal-string major units at the API boundary and integer kopecks / `RubleAmount` inside backend calculation paths.

Historical aggregation must not use a later month's prices, balances, positions or allocation to fill an earlier month.

R03-11 does not introduce new snapshotting of global account flags or reinterpret existing historical behavior; it reuses the currently accepted services and their semantics.


<a id="c2-0007-capital-composition-history-20-5-asset-stack-and-net-capital-are-deliberately-separate-values"></a>
#### 5. Asset stack and net capital are deliberately separate values

For each month the response exposes:

```text
liquid_assets_total = cash + deposits + stocks + bonds + gold_other
liquid_capital_net = liquid_assets_total - included_debts
```

`liquid_assets_total` is the stacked-area total and the denominator for the `%` composition view.

`liquid_capital_net` is the accepted net-capital metric from `liquid_capital_for_month`; it is shown as a separate total/net line or value.

The stack is therefore **not required to equal** `liquid_capital_net`. The difference is `included_debts`. Real estate and mortgage remain outside this contract exactly as in `MASTER_SPEC §10.1`.

The response also exposes `included_debts` so the UI can reconcile the difference without inventing a subtraction client-side:

```text
liquid_assets_total - included_debts = liquid_capital_net
```

R03-11 does not change which debts are included in liquid capital.


<a id="c2-0007-capital-composition-history-20-6-percentage-view-uses-the-asset-stack-never-net-capital"></a>
#### 6. Percentage view uses the asset stack, never net capital

The `%` view represents the composition of liquid **assets**, not net capital after debts.

For a class:

```text
share_pct = class_amount / liquid_assets_total * 100
```

The backend does not need to return precomputed percentages in v1. The frontend may derive display percentages from exact money strings/kopecks using the existing exact-money helper path; binary floating-point arithmetic must not be used for financial sums or the authoritative denominator.

If `liquid_assets_total == 0`, percentage values are unavailable (`null`/`—` in presentation) rather than divided by zero.

Chart libraries may receive converted numeric coordinates only after exact financial amounts/totals have already been established, following the existing Recharts boundary convention.


<a id="c2-0007-capital-composition-history-20-7-api-shape"></a>
#### 7. API shape

Use a separate analytics endpoint because this is a cross-month dataset and does not conceptually depend on a selected dashboard month:

```text
GET /api/analytics/capital-composition
```

Canonical response shape:

```json
{
  "asset_classes": ["cash", "deposits", "stocks", "bonds", "gold_other"],
  "points": [
    {
      "reporting_month_id": 42,
      "year": 2026,
      "month": 7,
      "snapshot_date": "2026-07-31",
      "allocation": [
        {"asset_class": "cash", "amount": {"amount": "100000.00", "currency": "RUB"}},
        {"asset_class": "deposits", "amount": {"amount": "400000.00", "currency": "RUB"}},
        {"asset_class": "stocks", "amount": {"amount": "300000.00", "currency": "RUB"}},
        {"asset_class": "bonds", "amount": {"amount": "700000.00", "currency": "RUB"}},
        {"asset_class": "gold_other", "amount": {"amount": "200000.00", "currency": "RUB"}}
      ],
      "liquid_assets_total": {"amount": "1700000.00", "currency": "RUB"},
      "included_debts": {"amount": "100000.00", "currency": "RUB"},
      "liquid_capital_net": {"amount": "1600000.00", "currency": "RUB"}
    }
  ]
}
```

No selected `month_id` parameter is required in v1. The dataset is the complete closed-month history available in the local database.


<a id="c2-0007-capital-composition-history-20-8-one-source-of-truth-for-current-and-historical-allocation"></a>
#### 8. One source of truth for current and historical allocation

R03-12 must not duplicate the current `_asset_allocation` formula in a second router/service.

Implementation should extract or promote one reusable backend allocation function/service that accepts `(session, reporting_month_id, liquid_capital_result)` and returns the existing five-class allocation. Both:

- selected-month Dashboard `asset_allocation`; and
- `/api/analytics/capital-composition`

must call that same source.

The analytics router only maps the service DTO to API models; no financial aggregation belongs in the router.


<a id="c2-0007-capital-composition-history-20-9-known-zero-vs-unknown-history"></a>
#### 9. Known zero vs unknown history

These cases are normative:

- CLOSED month exists, no stock positions in that month → `stocks = 0` and the point still contains the `stocks` class;
- CLOSED month exists but has no capital or included-debt evidence → the capital metric is unavailable/null with `portfolio_snapshot_missing`; never assert complete aggregate zero from empty rows. In an otherwise evidenced point an absent class can remain known zero. This is the later financial-completeness amendment; percentage view remains unavailable for a genuinely zero asset stack;
- calendar month has no CLOSED `reporting_month` → no point exists for that month; frontend displays a gap, never five zeros;
- future month data must never be copied backward to fill any missing historical point.


<a id="c2-0007-capital-composition-history-20-synthetic-examples"></a>
#### Synthetic examples


<a id="c2-0007-capital-composition-history-20-example-a--all-classes-present"></a>
#### Example A — all classes present

```text
cash         100 000 ₽
deposits     400 000 ₽
stocks       300 000 ₽
bonds        700 000 ₽
gold_other   200 000 ₽
----------------------
assets     1 700 000 ₽
debts        100 000 ₽
net        1 600 000 ₽
```

The stacked chart reaches `1 700 000 ₽`; the net-capital line/value is `1 600 000 ₽`.


<a id="c2-0007-capital-composition-history-20-example-b--known-zero-class"></a>
#### Example B — known zero class

```text
cash         120 000 ₽
deposits     450 000 ₽
stocks             0 ₽
bonds        800 000 ₽
gold_other   230 000 ₽
----------------------
assets     1 600 000 ₽
debts         50 000 ₽
net        1 550 000 ₽
```

`stocks` is returned explicitly as zero because the CLOSED month is known; the other four classes still sum to the stack total.


<a id="c2-0007-capital-composition-history-20-example-c--calendar-gap"></a>
#### Example C — calendar gap

May and July are CLOSED, June is draft or absent:

```text
points = [May, July]
```

The API does not synthesize June. A chart adapter may place a null June gap only to stop visual interpolation.

<a id="c3"></a>

PDF payout acceptance is statement-specific, selected-row and atomic for missing/CLOSED months. Preserve duplicate/idempotency guards and explicit create_separate/link_existing choice for manual candidates. Generic investment-flow deletion cannot silently erase statement provenance; retract uses the accepted auditable statement-specific lifecycle. No account/instrument/month is auto-created and no raw PDF/extracted text/path/beneficiary payload is persisted or logged.

V1 durable intake is not an implemented versioned reparse engine. Preserve exact Owner-retained original bytes and authority filename. Before future parser/enrichment/economic promotion, prove exact reattachment, a new append-only parser/generation revision with lineage/cross-generation dedup and reviewed currentness, or an explicitly accepted fresh disjoint rebuild with validated original/source/review crosswalk. Fail closed on parser drift; never rewrite old manifests, drop triggers, delete bound months or copy database rows to bypass guards. Upgrade acceptance includes synthetic parser A→B recognition, changed denomination, REPO pending, missing original, duplicate S1, overlapping reports, replay/ABA and numeric-reader samples. S records current implementation/acceptance limits.

## 3. Original → Preview → journal → financial DRAFT → GET → Close

An intact original, S1 source acceptance, journal capture, financial DRAFT, independent readback and Close are different stages. Preview is zero-write. Preserve frozen bytes/hash/parser/authority filename, every source occurrence ordinal and the complete observed set. Journal-only Save adds zero economic effects and does not persist raw XML. Financial Apply revalidates dependencies inside its one reserved transaction. ACK followed by failed GET is GET-only recovery; uncertain ACK is not proof of success or failure.

Close classification is precise: required month/snapshot geometry and date rules, existing financial conflicts and applicable unresolved source/intake/receipt guards are blocking. An ordinary active-account snapshot absence is a nonblocking warning with a partial known subtotal. Stale valuation is freshness, not missing source coverage. Cash-boundary/in-kind/performance prerequisites remain separate; Close does not attest them. Bound intake obligations survive defer/unbind/rebind and forbid delete→recreate erasure. Unknown section economics never becomes a zero movement.

<a id="c3-mybroker_s1-1"></a>
### Frozen original and S1 source normalization

Authority: [#708 accepted contract](https://github.com/LTstripes/hermes-finance/issues/708#issuecomment-5999540552),
the accepted [#713 endpoint disposition](https://github.com/LTstripes/hermes-finance/issues/713#issuecomment-6020928890)
and the [#716 implementation plan](https://github.com/LTstripes/hermes-finance/issues/716#issuecomment-6021176561)
with its Owner-local [gate confirmation](https://github.com/LTstripes/hermes-finance/issues/716#issuecomment-6021302431).
Parser constants and hand-built synthetic fixtures record the sanitized Integrator
manifests; they do not claim public format stability. No Owner XML or report value
is used in implementation or tests.

Upload is available under **Data → Files**, independently of a reporting month.
The multipart API is `/api/mybroker-import/preview` and `/apply`; `/{import_id}`
provides committed readback and `/lineage` provides the reduced source history.

Preview returns the hash, strict filename interval, parser/provider identity,
section inventory, normalized rows, explicit mapping bindings, conflicts and
unresolved evidence. Filename account and row `acc_code` are distinct identities:
both require explicit `alfa_mybroker` registry mappings, with no suffix/name/Alfa
PRO heuristic. Instrument mappings use the manifest's ISIN identity. No current
instrument class becomes event-C1.

Apply confirms the complete document set. Its confirmation digest binds every
normalized row and both native trade IDs, range, mapping revisions and current
reconciliation facts. Apply reparses the upload and reserves the SQLite writer
before rechecking the entire set. A stale or conflicting set writes nothing.
The UI retires confirmation on any Apply attempt and shows success only after
an independent GET agrees with the reviewed document and mapping bindings.

`mybroker_imports` is an append-only source ledger. It stores hashes, confirmed
dates, normalized facts, mapping IDs and acceptance provenance, never XML,
filenames, security names, arbitrary comments or paths. Migration 0048 adds only
this empty table; downgrade refuses to discard populated lineage. No economic
facts or historical months are created, overwritten or backfilled.

Economic identity is provider + source `acc_code` + both native trade IDs;
document/section/ordinal identifies an occurrence. Identical settled material
adds occurrences without another trade. Pending advances to settled only with
unchanged economic core and a later source endpoint, independent of upload order.
Equal endpoints with different lifecycle states conflict even when range starts
differ. Pending absence is checked against every account-scoped confirmed report
covering the trade timestamp, in both chronology and upload directions.
The immutable economic core must always agree. Present settlement/depo dates,
settlement time, commission and accrued-interest evidence must agree within each
state; absence may be enriched and pending plans never replace settled evidence.
Occurrence cash visibility alone is not material disagreement, but contradictory
present settlement/commission legs still conflict. Projection enrichment does
not rewrite persisted occurrences. Material changes, settled-to-pending, pending
disappearance in an overlapping confirmed report, and ambiguous primary-only
money linkage require reconciliation. A new trade also cannot make a previously
accepted money linkage ambiguous. Incomplete IDs retain observations without
authoritative trade identity.
Money rows linked to incomplete IDs retain their visible blocker and attach to
no identity-less trade.


<a id="c3-mybroker_s1-1-read-only-section-metadata-789792"></a>
#### Read-only section metadata (#789/#792)

Source Preview adds a separate `metadata_evidence` envelope identified by
`mybroker-section-metadata-v1` and bound to SHA256 of the exact uploaded bytes.
It is not part of normalized S1 JSON, confirmation material or saved receipts.
GET returns the immutable accepted S1 receipt; it cannot reconstruct metadata
without original bytes. Existing accepted Money grammar selection is unchanged.

Only these exact MyBroker-namespace trees report `READY_SAFE_STRUCTURE`:

- `Trades3/Report[@Name='4_Transfers']/Tablix1`: no wrapper/table attributes,
  no table children; raw report inventory remains 1.
- `Trades4/Report[@Name='5_UFSR']/Tablix1[@Textbox4='Подключен']/Details_Collection/Details`:
  exactly one childless Details, with only `sys_start_time` (ASCII
  `DD.MM.YYYY HH:MM`, valid calendar/time) and `sys_end_time='-'`;
  raw report inventory remains 3. The collection/wrapper have no attributes.

Every fixed node occurs once, Report has only its exact Name, and all text/tails
are whitespace-only. Extra attributes/nodes, comments, processing instructions,
foreign namespaces, alternate states/end tokens or malformed times block the
classification. Invalid S1 family/cardinality/bounds still reject the upload.
The previously supported childless Report is a separate family and is not
classified as either new safe pattern.

Both classifications derive zero movements. Connection times are validated but
not returned, constrained to the reporting month or used as transaction dates;
period scope and coverage remain unknown. The envelope retains S1 source warnings
and does not disposition any source/account/Close blockers. Money daily controls,
unknown economics, REPO and unexpected UFSR/Transfers remain unresolved. Any
consumer authority to relax a specific section blocker needs a separate decision
and review; this classifier grants none.


<a id="c3-mybroker_s1-1-native-money-linkage-compatibility-788"></a>
#### Native Money linkage compatibility (#788)

The exact full strings `Расчеты по сделке <numeric-primary-id>` and
`Комиссия по сделке <numeric-primary-id>` are accepted from the `oper_type`
attribute of the Money `oper_type` node. The accepted `comment` attribute
variant remains supported. IDs contain 1–128 ASCII digits. Neither field is
trimmed, searched for substrings, translated or used to invent a secondary ID.
When both fields match, they must agree on role and ID; otherwise the complete
document refuses parsing with `money_linkage_conflict`, including legacy rereads.
Matching both fields still yields one observation per original amount leaf.
Other Money operations keep their existing classification and blockers.

New documents with native linkage record the bounded optional
`money_linkage_version=mybroker-money-linkage-v1` extension under the unchanged
`mybroker-s1-v2` identity. Comment-only documents retain their frozen normalized
shape. The extension participates in confirmation material; row ordinals,
source account, posted date, currency, exact signed amount and both trade-native
IDs retain their original authority. Native cash requires a unique settled
trade; pending-only linkage stays unlinked with `money_link_not_settled`.
Existing account/ID ambiguity, direction, date/currency and commission-basis
checks still apply. Link recognition is not financial fee/NKD acceptance.

For exact bytes already accepted as S1 v2, source Preview/replay, broker-month
planning and original-bound Money reads select the grammar recorded in that
immutable receipt. An absent extension means the old comment-only grammar.
Thus old oper_type-only rows remain unsupported; saved JSON, fingerprints,
confirmation digests and receipts are never upgraded or rewritten. Unknown
extension versions refuse parsing with `money_linkage_version_unsupported`.
Fresh reports can provide new native evidence through normal overlap guards;
they never erase an older unsupported occurrence or grant complete coverage.
There is no migration, reimport or financial write in this parser repair.

This bounded fix does not waive unparsed Money/control nodes, Transfers/UFSR,
separate stock-fee proof or any remaining #787 Gate 0 blocker. Original Owner-local
read-only recheck and any subsequently authorized scratch work remain separate.

The [#736 compatibility repair](https://github.com/LTstripes/hermes-finance/issues/736)
also accepts the sanitized completed REPO observation shape at
`Trades/Report/Tablix2/Details_Collection/Details`: exactly one `trade_no`
matching `B[0-9]+`, a distinct single `repo_no` matching `B[0-9]+`, and
`comment` exactly `репо ч.1` or `репо ч.2`. IDs remain bounded to 128 characters.
The partner and marker validate syntax only; no pairing or financial semantics
are derived. The original one-part `ids` remains an observation with
`identity=null`, `repo_observed=true`, `trade_ids_incomplete` and
`repo_semantics_unsupported`. Reciprocal rows and duplicate occurrences never
manufacture a second native ID or an S2 execution.

For the #736 REPO compatibility repair, parser identity and normalized shape
remain `mybroker-s1-v2`; previously accepted numeric-ID documents normalize
identically. The later optional nominal extension is described below. Malformed
B IDs, ambiguous partners, absent/inconsistent markers and pending B rows refuse parsing.
B-linked money comments remain unsupported and unlinked. Because S1 does not
retain arbitrary money comments, H2 owner-cash claims cannot override an
identity-less REPO observation in the account's scoped source set. H0/H1,
source-cash coverage and XIRR continue to refuse unresolved affected evidence.

Source settlement/commission legs remain source evidence. No buy/sell principal
is relabeled as payout or realized profit; missing tax stays unknown, accrued
interest stays evidence, and unknown commission embedding never yields an
available all-in cash event. Pending is never actual cash. Transfers/UFSR,
generic money moves and unknown rows remain visible unresolved evidence.

Confirmed per-account source ranges are returned separately from financial
completeness; the latter stays `unknown`, including quiet/empty reports.
Import cannot revise accepted endpoint quantities or silently contradict a
complete no-crossing assertion. Subsequent no-crossing reads/writes also check
accepted source evidence against the historical account universe, preventing a
later assertion from ignoring unresolved event-C1. Existing source-free Phase 1
material signatures and solver behavior are unchanged. Reconciliation/C5 and
Reopen remain prerequisites where already required; S1 cannot perform them.
An unresolved pending trade survives the filename range until an explicit
settled occurrence resolves it. Actual settlement/depo dates crossing later
cutoffs are checked too; a new import surfaces impact on already accepted later
intervals before writing. Planned dates never clear an unsettled cutoff.
Both source guards use the membership-derived account universe at the interval
endpoints and the explicit source-account bindings; an unrelated, excluded or
historically uncovered account contributes no MyBroker blocker. Existing missing
membership guards remain independent. Within an included account S1 still has
no event-C1 proof, so it cannot safely restrict a source event to stock/bond/gold
from today's catalogue or a position's class. All potentially affected classes
remain guarded there; this does not assign or backfill a trade class.


<a id="c3-mybroker_s1-1-endpoint-evidence-parser-mybroker-s1-v2"></a>
#### Endpoint evidence (parser `mybroker-s1-v2`)

`mybroker-s1-v2` adds the accepted #716 Positions evidence without financial
writes. Security rows carry beginning/ending actual quantity, beginning value and
ending value beside the unchanged ending actual/forward quantity keys. Values
keep the source-native basis labels (beginning `previous_day_eod`, ending
`covered_to_eod`) as document `endpoint_basis`; that #716 endpoint extension
derives no price and introduces no bond nominal/NKD/clean-dirty semantics.

The later optional nominal extension retains `face_value`, `nominal` and
`nominal_value` attributes as `face_value` on trade/position rows (including
`2`-suffixed pending attributes), without changing trade core/identity or S1
financial authority. It keeps `mybroker-s1-v2` compatible by reproducing each
saved row's nominal-key presence when validating an exact reattached original.
Previously absent keys remain absent. New parsing distinguishes all-empty nominal
attributes (`face_value=""`) from invalid/conflicting values (`face_value=NULL`).
An older saved NULL stays frozen unknown even when an exact reattachment now parses
as empty; it never becomes assumed-face evidence. All other recorded nominal
values and parser facts must still agree. Saved JSON, manifests and fingerprints are never
rewritten, and reattachment cannot promote opaque nominal attributes into frozen
facts. New intakes may retain these facts. Provisional NKD inference uses only
trade-row nominal or the disclosed absent/empty-face assumption under the
[instrument-return contract](#c7-source_instrument_returns-1); position nominal
never supplies trade face.

The RUB currency row is recognized only by the accepted conjunction
`active_type=Валюта`, `active_name=RUB`, empty `ISIN1`, and is normalized
separately as `rub_money` beginning/ending money amounts. Its absence is never
zero RUB. Multiple matching rows are a blocking conflict (`rub_money_ambiguous`);
unclassified Positions rows stay visible blockers and are not stored.

Evidence gaps are document-level `endpoint_blockers`
(`endpoint_beginning_quantity_unavailable`, `endpoint_value_unavailable`,
`rub_money_unavailable`, `rub_money_incomplete`, `position_row_unclassified`).
They remain visible in Preview and committed readback but do not refuse a source
import; conflicts still refuse the whole Apply. Same-date accepted quantity
conflicts are unchanged, and this slice does not compare source values with
accepted snapshots.

A document already accepted under `mybroker-s1-v1` with the same bytes is an
explicit `accepted_parser_version_conflict`, never a silent re-interpretation or
rewrite; endpoint evidence for those bytes needs a distinct report. Coverage stays
`unknown`, and quotes, C1, historical backfill and #715 trade-ledger semantics
remain outside this slice.

Historical reconstruction (#709), trade-to-manual-fact reconciliation, historical
valuation/class evidence, bond returns, transfer semantics and payout-kind
interpretation remain outside S1. Full backend/frontend CI, independent review
and applicable Owner UAT remain separate from focused synthetic checks.

<a id="c3-broker_months-1"></a>
### Atomic source to financial DRAFT

The [durable source-intake journal](#c3-source_intake-8) (#889 first slice) saves
recognized observations, opaque inventories, Owner RUB assumptions and grouped
decisions without relaxing this financial writer. Bound pending intake participates
in scoped readiness/Close/returns even before a financial receipt exists. A
verified journal-only finance link can satisfy supported obligations after the
existing strict Apply/GET; it neither posts money nor removes incomplete-source
blockers. Reload requires exact-original reattachment for review mutations.

Issue #773 adds original XML → zero-write whole-account Preview → reviewed atomic
DRAFT Apply → independent GET → existing global Close. The receipt joins existing
immutable S1, stage-only identities, canonical S2 trades and native finance rows;
it does not introduce another trade, cash or payout ledger.

The strict financial slice requires exact-compatible RUB stock/bond identity,
one explicitly bound active broker/IIS account and the exact existing DRAFT month
with its final-day snapshot. Identity may reuse the compatible catalogue or use
the separately reviewed bounded official bond FACEUNIT creation proof in C4.
Without accepted denomination evidence new identity retains `instrument_currency_unproven`;
Owner-default RUB does not clear it. Unsupported instruments cannot be skipped to make the account complete.
Position quantity and native total, beginning and ending values, separate RUB cash
and the full Money inventory remain distinct. Source cash is not incremented again
by settlement or payouts. Missing tax, cost and bond NKD stay null.
Affirmative zero holdings remain in source inventory without fabricated position
rows. Missing security inventory is unproven, not observed zero; fractional stock
quantities are explicit Preview conflicts. Balanced endpoints cannot clear an
unresolved canonical settlement principal, commission or cash ownership.

Accepted S1 trade settlement/commission patterns and canonical native trade keys
retain their authority. The #782 extension under accepted #781 adds only explicitly
reviewed actual net coupons and account funding to an existing source-owned DRAFT.
Coupons use InvestmentCashFlow; funding uses H2 v2 HistoricalOwnerFlow. Neither
creates ExternalFlow nor adds source cash again. Accepted #783 additionally handles
an individually proved settled RUB **bond BUY** with negative posted paid NKD and
a separately charged nonzero native-linked fee through the existing
ExecutedTradeRevision. No duplicate endpoint cash or inferred EOD NKD/cost arises.
Accepted #790 adds a separate, typed **settled RUB stock BUY** proof
(`stock_buy_separate_fee_v1`) using exact native settlement S and separately
charged fee F, individually reviewed fee-excluded `summ_trade=T`, `bank_tax=B`,
and the existing ExecutedTradeRevision. It adds no paid NKD leg, extra cash,
payout or ledger. A source evidence reference is required; an entered reference
or matching equation alone is not independent brokerage fee-basis proof.
Unknown dividends, opaque Money and unsupported source sections remain
visible scoped exceptions. An incomplete DRAFT is allowed; unresolved
evidence blocks its covered account at Close.

The [incomplete DRAFT identity separation](#c4-mybroker_identity-7-incomplete-draft-structural-separation)
allows only server-validated Positions/Money structural side branches to remain
bookkeeping exceptions rather than identity conflicts. Preview and reserved
Apply use the same versioned original-bound classification. It never deletes
`unparsed_source_rows` from S1 or GET/Close, accepts a hidden identity row, creates
tax/NKD/fee economics or changes exact/indicative return readiness. A successful
partial Apply is not financial completeness or permission to Close.

The Money Preview requires original bytes for the complete accepted overlapping
source union. Original observations guide specific instrument/payment/boundary
review; they do not mint payment identity from date, amount or narrative. The server
assigns coupon identity and retains permanent occurrence-to-target ownership,
including old H2/S2 owners and revoked evidence. Indistinguishable repetitions and
missing events in a covering report block acceptance. A typed PDF can explicitly
link the same ICF; it cannot invent missing gross, tax or commission components.

Money Apply reserves the writer, revalidates all dependencies and stages ICF, H2,
ownership links and proof in one transaction, followed by independent GET. Versioned
Money proof and monotonic retirement/dependency tokens use the existing append-only
BrokerMonthApply journal; legacy receipt JSON and S1 are unchanged. A → B → A cannot
revive stale review. Retired proof requires reviewed reaffirmation of the same core
targets. Replay returns current disputed/readiness state without adding money.
Journal revision order is assigned under the writer reservation, independently of
wall-clock timestamps. A compatible staged coupon addition preserves unchanged
earlier payouts. Legacy PDF technical tax zero is displayed as unknown when its
accepted provenance marks tax unavailable; stored legacy facts are not rewritten.
Claim-free coupon reuse is limited to the already proven complete occurrence set.
A distinguishable second coupon cannot be linked to that payout even with matching
amount/date and supplied claims. Money funding requires H2 v2; legacy v1 authority
needs explicit version-bound reaffirmation, retaining its original receipts.
Independent GET retains batch targets and also returns all current targets for the
source-owned account/month, so the desktop panel preserves earlier acceptances.
Compatible additive typed PDF LINK_EXISTING keeps the original Money authority:
the ICF facts and existing PDF support must remain identical, and each added
attachment must contain one matching initial link revision for that exact target.
Later PDF revisions, retractions or contradictions retain monotonic retirement.
Lifecycle retirement follows the affected target and reporting period (including
old scope when a row moves), so cash/payout/PDF changes in another month of the
same account do not retire independent accepted Money.

Preview confirmation binds original bytes, selected account/month, identity/source
revisions, financial dependencies and supplied optional-document hashes. Apply
reserves the writer, revalidates and stages all changes in one transaction. Any
failure rolls back identity/source/trade/position/cash/receipt writes. Same-intent
request replay returns the original receipt with zero new economic rows, including
after Close; it cannot mutate CLOSED. Overlaps reuse canonical trade identity.
Manual or conflicting facts require explicit reconciliation rather than overwrite.

GET reads the accepted immutable S1 source and current authority/projection under
one snapshot. Readiness and reserved server Close share the same source checks:
all positions and cash must still match, mappings/source authority must remain
valid, intersecting evidence must have no material unresolved conflicts. Receipt-derived hard
guards apply to accounts explicitly covered by source-owned receipts. Independent
bound-intake guards also apply before any financial receipt, under the C3 journal contract;
unrelated account/manual behavior remains outside those scoped obligations.
Supplied optional evidence remains attached to its receipt. Source/control and
authority failures are recomputed rather than frozen: successful compatible
canonical enrichment clears its temporary projection blocker. Preview and GET
also retain every applicable receipt's unresolved evidence at account level.
Unrelated active accounts retain `active_account_snapshot_missing` warnings;
ordinary months keep existing behavior. Account readiness does not attest whole
portfolio coverage: `coverage_state=unknown`, exact XIRR/TWRR remain unavailable.

Optional documents are absent by default. Supplied documents without an accepted
typed reader are hashed and disclosed as `optional_evidence_unsupported`, blocking
Close rather than producing guessed corroboration. Dedicated optional adapters
remain deferred. The desktop route currently accepts the original XML only.

Migration 0057 adds an empty append-only ownership receipt table with source/month/
account foreign keys. It neither backfills financial data nor reparses legacy S1.
Downgrade refuses populated source-owned receipts to prevent lost ownership.
Migration 0058 adds only permanent Money occurrence links with ICF/H2 target and
receipt foreign keys; it performs no financial backfill and refuses downgrade when
links are populated. The desktop extension accepts the required original XML set.

Synthetic backend regressions cover exact values/missingness, replay, both overlap
orders, distinct native IDs, stale review, full rollback, conflicts and reserved
Close concurrency. Desktop tests verify explicit review, failed/mismatched GET,
CLOSED reading and real API Preview → Apply → GET → global Close at desktop widths,
including the incomplete Money path. Synthetic evidence is not Owner acceptance.

<a id="c3-broker_months-217"></a>
### Original-bound section disposition

<a id="c3-broker_months-217-original-bound-section-disposition-799--800"></a>
#### Original-bound section disposition (#799 / #800)

The accepted [#799 Integrator amendments](https://github.com/LTstripes/hermes-finance/issues/799#issuecomment-6120415679)
add the separately versioned `mybroker-section-disposition-v1` variant in the
existing append-only BrokerMonthApply journal. It accepts metadata only, for one
existing source-owned DRAFT receipt and exact import/account/month. No schema,
source, mapping, financial row or frozen S1/receipt JSON is changed.

Use the existing multipart `/api/broker-months/preview` and `/apply` with one exact
original XML. Intent names `contract_version`, `base_request_id`, `import_id`,
`account_id`, `reporting_month_id` and `sections`, each containing `section`
(`4_Transfers` or `5_UFSR`) and `expected_predecessor` (null for first acceptance).
Apply also requires `request_id` and the server's `confirmation_digest`.
Supporting files, client source hashes and safety assertions are not accepted.

Both stages reread the original with the recorded S1/native-Money grammar,
compare parser facts allowing established service enrichment, validate filename,
range, account aliases and mapping identities, and independently rerun the strict
#792 classifier. The receipt binds the original SHA, filename digest, source and
base-receipt digests, exact section locator/shape, inventory 1/3, zero derived
movements and unknown period scope. Connection dates are never retained as events.
Apply rereads dependencies and heads under the existing reserved writer; failure
rolls back the whole acceptance. Preview writes nothing.

GET `/{request_id}` shows each metadata section as `effective`, `superseded` or
`blocked` without originals. Source-month GET also includes `section_dispositions`;
the month list retains its source-month rows. The shared source resolver removes
only that source's proved named section code before blocker union in Preview,
GET and reserved Close. Unsafe or unproved overlapping sources retain their own
blockers. Frozen exceptions have no understood exclusive section provenance in
the legacy contract, so their contribution remains blocked; no backfill occurs.
All other Money, footer/Positions, REPO, unparsed rows, fee and NKD guards remain.

One chain per import/account/month/section follows explicit predecessor links,
independent of timestamps. Forks, missing predecessors and malformed/unknown
journal variants fail closed. The existing monotonic source/mapping journal and
dependency receipts retain ABA invalidation, including snapshot geometry edits.
An invalid head grants nothing; it never revives an older proof. Explicit fresh
acceptance referencing that head can restore newly validated authority; stale
history does not permanently poison account readiness. Exact replay is read-only
and returns current state, even on CLOSED. Fresh acceptance on CLOSED is refused;
normal Close status changes do not invalidate structural proof.

This code authority does not accept real September Gate 0, Positions/footer
grammar (#798), daily Money definitions (#793), actual stock fee basis or actual
Money ownership. Owner/private Apply/Close, Test/Stable/CLOSED mutations and exact
return authority remain outside this synthetic implementation.

<a id="c3-broker_month_native_s2a-1"></a>
### Source-native money and nullable basis

Scope: [#772](https://github.com/LTstripes/hermes-finance/issues/772), under
[#768 accepted amendments](https://github.com/LTstripes/hermes-finance/issues/768#issuecomment-6106797516).
This is the persistence/consumer subcandidate. It does not assemble or import a
broker month, change existing receipts, or supply indicative/exact returns.


<a id="c3-broker_month_native_s2a-1-persisted-contract"></a>
#### Persisted contract

`PositionSnapshot.price_source=broker_statement_native`, `native_contract_version=1`
stores exact RUB `market_value_kopecks` independently of quantity. The internal
transaction-scoped helper leaves unproved per-unit price, average acquisition
cost, cost basis and unrealized result null. Accrued interest is independently
nullable; `bond_nkd_basis=unknown|included|excluded|not_applicable` describes the
native total's basis and never supplies a missing NKD amount. Stock requires
`not_applicable`; bond requires one of the other three values. Source asset kind
must match the instrument and is frozen in `historical_instrument_type`.

`InvestmentCashFlow.amount_basis=broker_statement_net_v1` stores actual posted
net RUB for stock/bond payouts. Gross, tax and commission are null. Redemption
remains principal repayment, outside passive income/result sums. No calendar
forecast becomes an actual payment. Legacy `gross_components` arithmetic and
manual position formulas remain unchanged.

Both modes reference an existing immutable `MyBrokerImport` plus a canonical
SHA256 fact key. The source date must be in that source interval; a position
must use the month snapshot date and a payout must lie in the actual month.
Source money is bounded nonnegative integer kopecks; source quantity is exact,
positive, at most six decimals, whole for stocks and within Numeric(18,6).
SQLite quantities that cannot round-trip exactly are refused; the caller must
roll back the entire staging transaction on any validation or flush error.
The account/fact-key unique constraint prevents a second cash projection,
including two concurrent attempts or the same fact seen in overlapping sources.

The helpers flush without committing. They are representation primitives, **not
source authority or Preview/Apply**: S2b must verify the original-bound facts,
effective mappings/dispositions/corrections, canonical cross-document identity,
economic ownership against existing events, stale dependencies and the global
month state inside one writer transaction. Referencing an import and key alone
does not prove those facts. No public manual create/update payload exposes these
modes. Manual, quote and legacy broker Apply cannot revise/delete native rows;
a later reviewed source revision lifecycle is required.

Migration 0056 preserves every existing column/value/reference. Added legacy
basis defaults are `gross_components` and `unknown`, with no guessed bond basis.
Guarded nullable CHECKs keep legacy fields mandatory. Downgrade preserves legacy
data and refuses any native row rather than discarding facts or filling nulls.
Only synthetic databases are used for migration verification in this slice.
The older 0045 downgrade explicitly removes its reflected historical-kind CHECK
before dropping the column, so the 0056 batch rebuild preserves full downgrade
compatibility as well as the source-fact refusal.


<a id="c3-broker_month_native_s2a-1-consumer-inventory"></a>
#### Consumer inventory

| Consumer | Source-mode behavior |
| --- | --- |
| Position/payout GET DTOs, desktop types | Exact total/net and nullable components plus explicit mode/provenance |
| Dashboard account/class results | One missing cost/P&L makes its whole aggregate unavailable, including mixed manual/native rows |
| IIS result and summary | Known coupon/dividend cash stays visible; unknown unrealized result makes both total results null |
| JSON export 1.3 / Markdown report | Nullable raw and report components; no fabricated tax or P&L zero |
| AI bundle / financial review | Missing acquisition cost/P&L/NKD unavailable; statement provenance retained |
| Broker reconciliation / statement preparation | Nullable local evidence preserved; old component-based linking/apply checks unchanged |
| Quote preview/apply, position/payout manual CRUD | Native facts cannot be overwritten; quote preview excludes native totals |
| Month clone | Native EOD positions are not carried to a different source date; actual payouts were never cloned |
| Monthly Close | Existing global workflow and other-account/nonbroker blockers remain; no new source-only readiness exemption |
| Exact valuation / class eligibility / XIRR normal and historical fallback | Native totals do not establish exact economic basis or promote solver quality |

No new source completeness assertion or source Close orchestration is supplied.
Bookkeeping capital includes proven totals; amount-known is not cost-basis-known
or proof of complete source/account coverage. S2b still owns the audited source
readiness path. #771 integration must use its transaction-scoped identity helpers
without changing S1 accepted evidence or committing a separate import.

<a id="c3-060-39"></a>
### Bounded realised-payout PDF import

<a id="c3-060-39-alfa-depository-income-statement-import"></a>
#### Alfa depository income statement import

- только принятое семейство стандартизированного Alfa income-payment PDF;
- владелец явно выбирает локальный PDF;
- только text layer, без OCR;
- Inspect → transient mapping → Prepare → explicit selected Apply;
- тот же PDF идемпотентен и duplicate-protected;
- manual candidates требуют явного `create_separate` или `link_existing`;
- CLOSED/missing-month операции падают атомарно;
- raw PDF, полный extracted text, original path/filename, beneficiary private data и private provider payload не persist/log;
- account / instrument / month автоматически не создаются.

<a id="c3-source_intake-8"></a>
### Durable non-economic intake journal

and financial DRAFT remain blocked; catalogue/EOD audits are not repeated here.


<a id="c3-source_intake-8-saved-evidence-and-progress"></a>
#### Saved evidence and progress

Migration `0059_source_intake` adds three empty tables:
`source_intake_originals`, `source_intake_observations`, and
`source_intake_revisions`. They retain original hash/length/filename digest,
period/native accounts, all recognized occurrences, a bounded whole-tree
structural inventory, and append-only review/policy/link history. Structural
inventory stores tag/attribute names, value/text fingerprints, child counts and
bounded native account/ISIN/trade/REPO partner references. Unknown attributes,
including numeric zero, receive no economic authority. A partner reference is not
a second execution ID. Frozen S1 and accepted financial receipts are unchanged.

Raw XML, filenames/absolute paths and browser File objects are not cached.
Money-row operation/narrative text is the bounded exception described in
[monthly source estimates](#c7-source_monthly_returns-1); other arbitrary source
narratives remain fingerprint-only. Originals remain with the Owner. Reload retains the
queue and decisions; mutation/reparse requires reselecting the exact original.
The server rechecks bytes, filename authority, manifest, versions and current
dependencies. Parser/generation drift refuses rather than silently reinterpreting
stored observations. Browser storage and implicit outbound lookups are absent.

The first intentional save records the already Owner-authorized RUB preference.
`owner_default_rub` and explicit account/instrument overrides are revision-backed
proposals. They do not attest denomination, settlement/quote units, NKD, tax or
completeness, and do not create Instrument or mapping rows. Existing catalogue,
official nominal evidence, Owner selection, default, unknown and conflict remain
distinct. Explicit official FX evidence is retained with provenance; expiry or
cache loss leaves a stale exception and never converts it into assumed RUB.
The public lookup remains opt-in/session-local; journal reads never fetch data.


<a id="c3-source_intake-8-api-and-transaction-boundaries"></a>
#### API and transaction boundaries

All routes are under `/api/broker-months/intakes`:

| Route | Effect |
| --- | --- |
| `POST /` | Multipart original + typed save intent/request ID; save complete observations and optional explicitly reviewed account/month attachment. No financial effects. |
| `GET /`, `GET /{id}` | Independent coherent read of current proposals, full saved observations, history, binding and blockers. List supports month filtering and optional unbound observations. |
| `POST /{id}/review-preview` | Original + grouped decisions/expected head; zero writes/network; returns digest and zero financial effects. |
| `POST /{id}/decisions` | Original + exact reviewed digest/request ID; append decisions/policy/overrides only. |
| `POST /{id}/finance-link` | Same reviewed command protocol, referencing an existing strict SOURCE receipt; append a link only. |

The read-only [source-intake-bound instrument result](#c7-source_intake_result-1)
slice computes one visibly hypothetical per-instrument RUB/percent result from a
saved original and reuses the accepted #858/#862 readers; it writes nothing and
grants no financial authority.

Save/decision/link commands reserve SQLite's writer before revalidation and commit
one transaction. Stale heads, changed original/dependencies, unsupported flags or
forked journal refuse. Same request/intent is read-only replay; another intent with
that request ID conflicts. Native occurrences are not duplicated on repeated
upload. Policy/decision/dependency revisions detect A→B→A. Restore admission epoch
and process incarnation invalidate outstanding review confirmations even when
restored values and sequence numbers match. Committed journal evidence survives
the supported SQLite online-backup/restore path.

An ACK followed by failed GET recovers by GET, without another POST. A financial
commit followed by missing link recovers by financial GET then idempotent link,
without another financial POST. Link acceptance checks exact original/generation,
account/period, accepted S1, strict receipt and its own live projection/source
authority under the writer reservation. It does not require aggregate Close
readiness, which includes the unsatisfied intake and would create a circular gate.
Incomplete strict receipts keep their financial/source blockers. Links become
ineffective on affected authority/decision/ABA changes; history remains intact.
Current journal identity conflicts, evidence gaps and explicit deferrals remain
pending even when an earlier strict SOURCE receipt is otherwise clean. Link preview,
reserved confirmation and every GET revalidate all current journal choices against
the exact accepted S1 mappings and receipt instrument binding. An incompatible choice
or deferral requires explicit journal resolution before fresh linking; an old link
cannot waive it. Acknowledged replay never restores the effectiveness of an old link.
A saved proof-only creation choice can reconcile read-only to the card created by
its own strict receipt only when the exact frozen receipt proof is still current
and its ISIN/type/currency, accepted instrument and S1 mapping all match. The saved
choice remains unchanged; expiry, replacement proof or an incompatible target stays
pending. No RUB assumption supplies this proof.


<a id="c3-source_intake-8-binding-consumers-and-protected-lifecycle"></a>
#### Binding, consumers and protected lifecycle

Unbound viewing creates no obligation for unrelated months. Binding requires an
exact native account/period and editable final-day DRAFT, with explicit alias
selection and existing conflict/revocation guards. Once bound, defer/unbind/rebind
cannot remove the obligation. Generic month DELETE and snapshot geometry changes
are explicitly refused under the writer reservation before bulk child deletion;
DELETE→recreate cannot erase journal history. CLOSED mutation remains prohibited.

One scoped resolver supplies account readiness, reserved server Close, statement
returns, actual source cash coverage, exact-performance and historical-XIRR
consumers. New unresolved evidence applies even when the account already has an
accepted financial receipt or numeric return. Unrelated account/month/manual
behavior is unchanged. The ordinary known-subtotal formula and historical
account-presence coverage are preserved. A separate
`source_account_financial_coverage` accompanies summary/Capital coverage; AI and
Markdown exports retain the corresponding partial defects. Presence is not
complete financial coverage, and unknown values are never zero.

All three tables are append-only at SQLite level. Dependency tokens contain only
table/row identity and old/new account, month and event-date scope, and are recorded
once an intake exists. Financial row edits, moves and delete/recreate cannot revive
a previous link after A→B→A; fresh explicit linking is required. Unrelated financial
scopes do not retire the link. Ordinary installations
without an intake acquire no journal history from unrelated catalogue edits.
Downgrade refuses any populated intake journal. Upgrade/downgrade does no financial
backfill and is not automatically deployed to Owner/Test/Stable by this code task.


<a id="c3-source_intake-8-explicit-remaining-boundary"></a>
#### Explicit remaining boundary

No assumed global card, financial `broker_source_partial_v1`, filtered S1, arbitrary
12-of-13 positions/cash, REPO economics, accepted-finance correction/retirement,
FX engine, new Skip or Close waiver is implemented. Those remain the separately
gated continuation in #889. Synthetic/Windows desktop evidence is not June/July
Owner financial GO or UAT and does not authorize protected runtime operations.

<a id="c3-mybroker_batch_preflight-1"></a>
### Bounded original-set preflight

`POST /api/mybroker-preflight/preview` accepts multipart `files` (one to eight
original XML files) and an optional JSON `intent`. This is a pre-import inventory;
it neither executes BrokerMonth Preview nor creates a ReportingMonth, source,
receipt, mapping or financial row. There is no batch Apply endpoint.

Intent permits `account_bindings` with the existing identity-preview shape and
optional `requested_from` / `requested_to` dates supplied together. Omitted dates
select the uploaded filename-declared range. Bounds are 8 MiB per original,
32 MiB per batch, 30,000 parsed rows and 120 calendar months.
Multipart data is parsed directly from the request stream into bounded memory.
File count, each original and aggregate bytes are checked before extending a
buffer; originals are never spooled to temporary files. Headers and intent are
bounded separately. Batch account bindings are validated against all observed
aliases, then each document receives only its applicable bindings.

The service uses the existing S1 original grammar selector and native reducer,
strict identity planner, and H0 endpoint definitions inside a query-only committed
snapshot. The existing #804 original/inventory-bound incomplete-DRAFT classifier
may clear only proved nonidentity structure for the advisory DRAFT candidate
marker. Standalone identity stays strict; S1 warnings and all financial, H0 and
seam blockers remain visible. Previously persisted originals retain their recorded
Money grammar and must match their immutable binder. H0 remains the inventory of persisted accepted
sources; this preflight does not replace it. A new original's range is declared
by its filename under the S1 contract, not independently attested by this Preview.

The response separates:

- `documents`: original identity/range/parser, source-native position and separate
  RUB cash observations on each endpoint side, mappings/type/denomination evidence,
  unsupported section inventory, and distinct source/calendar/financial/DRAFT/
  Close statuses. Normalized Money, NKD and fee observations remain intact with
  unknown financial authority. An independently observed whole month may be a
  candidate for the existing separate reviewed incomplete DRAFT Preview.
- `calendar`: whole-month original availability and explicit references to source
  endpoint sides. Missing interior EOD is unknown. A partial or wide report proves
  only its own endpoints and dated events; it cannot lend intervening EOD or
  historical market valuations. A following first-day opening can reference the
  previous day's EOD without establishing a whole-month original.
- `seams`: adjacent ending versus opening quantities, source values and RUB cash,
  compared only for the same native source account. Differences use exact Decimal
  arithmetic; one kopeck is a conflict. Missing/ambiguous rows stay unknown. These
  comparisons also stay unknown for sub-kopeck cash or security values, even if
  the Decimal values are equal or their difference is an integral number of
  kopecks. No rounding or monetary minor-unit assertion is made in that case.
  The precision blocker prevents DRAFT candidacy for the affected seam.
  These comparisons do not attest complete settled inventory or financial coverage.
- `native_trade_inventory`: existing reducer projections plus occurrence lineage,
  exact duplicate/enrichment/pending-to-settled, changed core/material, missing
  overlap and multiplicity diagnostics. Repeated identical file uploads are
  counted as uploads, not new trade occurrences. Anonymous Money is never
  economically deduplicated. No second ledger is persisted.
- `report_availability`: explicit missing adjacent and 2025 originals. A known
  range is an observation, not proof of historical financial completeness.
  Adjacent originals are observed only for two consecutive full calendar-month
  originals with the same filename account and valid immutable binders. A
  contiguous seam between partial/wide reports cannot establish this availability.

`coverage_state` and `financial_completeness` remain `unknown`;
`financial_apply_available` is false and `close_performance` is blocked. Preflight
grants no source-account/portfolio crossing, H2, Close, XIRR or TWRR authority.
The Owner-original pilot is a separate later read-only UAT. Automated evidence
uses fabricated originals only; originals and private response values belong
outside Git, logs and public issue/PR evidence.

<a id="c4"></a>
## 4. Identity, provenance, receipts and currentness

Economic native trade identity differs from a document/section/ordinal occurrence. Date, amount, title and ISIN alone are insufficient deduplication keys; a REPO partner is not a second execution ID. Mapping revisions, immutable receipt versions and correction/reaffirmation/retirement have distinct ownership. Preserve obligations after defer/unbind and version-specific read/replay compatibility.

Quote, settlement, payout, denomination and native EOD currencies are separate. Owner default, explicit override, existing catalogue and official proof are separate provenance. Only the bounded official bond FACEUNIT resolver accepts `SUR → RUB` while retaining raw SUR; it is not a universal currency resolver. Currentness is contract-specific: historical material hashes can coincide at ABA, whereas durable intake adds monotonic revisions/restore epoch/process-incarnation guards. Do not claim one universal hash prevents all ABA.

<a id="c4-mybroker_identity-7"></a>
### Original-bound identity and RUB proof

`POST /api/mybroker-import/identity-preview` accepts the unchanged original XML
and strict source-range filename, plus optional multipart `intent` JSON:

```json
{"account_bindings": [{"identity": "1234567-000", "hermes_id": 1}]}
```

The example is synthetic. Filename account and every row account remain separate
aliases. An existing effective mapping supplies its accepted binding; a new alias
requires an explicit account binding in the reviewed intent. Accounts are never
created or inferred from names, external codes or suffixes. All aliases in one
original must resolve to the same brokerage/IIS account. Duplicate request aliases
and duplicate resolved position aliases block the entire batch.

The `mybroker-identity-v1` envelope reparses authoritative bytes using the bounded
`mybroker-s1-v2` family and adds metadata separately. Existing S1 normalized rows,
source acceptance, receipts, Skip and correction lifecycle remain unchanged.
There are no invented root dates. The Preview binds the original hash, filename
range/account, parser identities, observed row accounts/ISINs/type/names/custody,
trade currency observations, proposals and current dependency revision. Its
confirmation digest is deterministic. Preview uses the committed read-only
snapshot and writes nothing.

Only row-level Positions `active_type=Акции|Облигации`, `active_name`, `ISIN1`,
`acc_code` and `place` provide security metadata. Completed Trades supplies
`isin_reg`, `p_name`, `acc_code`, `curr_calc` and `Textbox14`. Contradictory
`curr_calc`/`Textbox14` observations refuse the entire batch with
`trade_currency_observation_conflict`, without deriving security denomination.
Trade type must link
to Positions by exact account and ISIN. Trade-only type remains unproven; names,
group placement and current catalogue type cannot manufacture source authority.
In the standalone identity contract, unknown/unparsed rows, invalid ISINs, unsupported asset types, REPO, account/type/
mapping alias conflicts and incompatible revoked bindings refuse the whole batch.
Opaque UFSR/transfer source warnings remain visible; identity eligibility does not
attest their financial semantics or source completeness.


<a id="c4-mybroker_identity-7-incomplete-draft-structural-separation"></a>
#### Incomplete DRAFT structural separation

The source-month writer alone selects internal `incomplete_draft=True` for both
Preview and writer-reserved identity staging. The standalone identity Preview and
ordinary staging remain strict; no HTTP intent flag can waive source warnings.
`mybroker-incomplete-draft-identity-v1` rechecks the original tree and can defer
only structurally bounded Positions/Money side branches. The original byte hash,
classifications and contract version participate in the identity confirmation
digest. Originals without these exceptions retain their existing identity shape.

The bounded grammar includes the exact populated NDFL `Tablix3` three-attribute
leaf (unsigned D2), Money beginning/ending scalar wrappers, daily scalar displays,
the `Textbox116` summary, operation-group summary and three exact empty trees.
Money numeric displays use bounded signed decimals (48 characters) with exact
minor-unit representation; sub-kopecks are rejected without rounding. Daily
displays are explicitly empty before each group's last rn and populated together
only on that last rn; missing, empty and numeric zero remain distinct.
Currency labels are literal RUB. Tablix7 accepts only four complete ordered
label sequences under [#828](https://github.com/LTstripes/hermes-finance/issues/828)
and [#872](https://github.com/LTstripes/hermes-finance/issues/872):
[`Внесено по распоряжению Клиента`, `Купоны`, `Списано по тарифам Банка`],
[`Внесено по распоряжению Клиента`, `Дивиденды`, `Купоны`, `Списано по тарифам Банка`],
[`Дивиденды`, `Купоны`, `Списано по тарифам Банка`],
or [`Купоны`, `Списано по тарифам Банка`]. Each group retains exactly
one childless p_code6/volume6 leaf under p_code6_Collection. This is not an optional
group grammar; totals do not classify dividend/coupon/fee events or Owner flows.
Keys, expanded namespaces, paths,
ordered children and singleton branches are checked, with no text/tail payload,
comments, processing instructions or nested namespace declarations. The complete
Money table order and net/operation child order match the accepted
[#804 manifest as amended](https://github.com/LTstripes/hermes-finance/issues/804#issuecomment-6129597801).
After projecting these branches out of a temporary tree, every remaining node
must lie on an actually consumed S1 Positions/Trades/Money path. Retained-node
attributes are restricted by exact path to consumed row keys or enumerated
caption keys; grouping wrappers accept no attributes. Fixed path cardinalities,
consumed S1 row counts, original hash and source inventory remain binding. Root
attributes match the exact family including Textbox6; sections remain ordered.
Only one observed row-account/RUB context is eligible; aliases still require
separate explicit mappings. Source cash/quantity mismatches remain conflicts.
Unknown roots,
extra/moved rows, hidden account/ISIN/native-ID attributes inside an exception,
malformed/foreign/duplicate shapes and all existing semantic conflicts still
refuse the batch. Optional branches are not inferred when absent.

This is identity eligibility for an explicitly incomplete DRAFT, not safe-layout
or financial acceptance. Values are never interpreted, summed or substituted.
The envelope reports `financial_authority=none` and unresolved tax/Money
classifications. S1 parser, normalized JSON, fingerprints, source warnings and
legacy receipts stay unchanged; `unparsed_source_rows` remains a source exception
and a server GET/Close blocker. Unknown tax/bond NKD, fee basis, native cash and
settlement ownership retain their existing controls. Real scratch, Apply and
independent GET/UAT require their separate Owner gates.


<a id="c4-mybroker_identity-7-currency-limitation-in-the-confirmed-original"></a>
#### Currency limitation in the confirmed original

The confirmed stock/bond Positions shape has **no security denomination field**.
`curr_calc=RUB`, `Textbox14=RUB`, the RUB cash row and source valuation totals do
not establish `Instrument.currency`. Preview therefore proposes new stock/bond
metadata with `currency=null` and the typed `instrument_currency_unproven` gap.
Without compatible catalogue or accepted official proof the whole strict batch has `can_stage=false`; compatible rows are not partially persisted.
No database/application RUB default is used as evidence. Nominal, ticker and quote
are not derived from source totals or trade prices.

A compatible existing global Instrument is reused, including inactive instruments,
with its existing currency and metadata preserved. The Preview labels that currency
`existing_catalogue`; source currency remains separately `unproven`. One instrument
mapping is global across accounts. Exact replay/overlap reuse the same identity and
effective mapping. Instrument/account/source changes, including A→B→A changes in
the existing monotonic correction journal, retire the old Preview.

New-card staging requires a separately accepted authoritative currency source or
compatible model sub-slice. The accepted official bond-proof path below supplies a bounded reference resolver. It does not add nullable Instrument denomination or an arbitrary currency override.
The manifest's currency gap is an explicit creation blocker, not an automatic Skip.


<a id="c4-mybroker_identity-7-internal-transaction-contract-inside-the-source-month-writer"></a>
#### Internal transaction contract inside the source-month writer

`services.mybroker_identity.stage_identity` is a Python helper, with **no HTTP
Apply route and no commit**. Call it before staging month facts, using original
bytes/filename, the reviewed account intent and confirmation digest. It reserves
SQLite's single writer with the existing no-op source-ledger UPDATE, expires ORM
state and recomputes the entire plan under that same writer reservation. A stale
digest or any conflict/evidence gap refuses before identity writes.

All identity/mapping staging uses one savepoint and the existing mapping lifecycle
helper with `commit=False`. A flush error rolls back all staged identity rows;
success retains the outer writer transaction and returns the exact mapping IDs.
The source→month orchestrator owns its single final commit, and must roll
back the outer transaction on any later failure. The helper does not accept source
lineage, create a month, write positions/cash/income/trades, Close or reconcile Skip.
Callers must not expose it as a permanent standalone metadata Apply.

Synthetic regressions cover confirmed field placement, typed new-stock/bond gaps,
inactive catalogue reuse with a currency differing from settlement, two accounts
sharing one global instrument, replay/overlap, aliases, revoked mappings, legacy
Skip, original/range/catalogue/mapping/source staleness, savepoint failure and
independent-session visibility/outer rollback. Real new-instrument Owner UAT and
source-month financial acceptance remain later gates.


<a id="c4-mybroker_identity-7-source-first-session-inbox-886"></a>
#### Source-first session inbox (#886)

The existing original-first BrokerMonthReview retains one unedited File in the
existing in-memory original session. All parsed Positions, Trades and Money stay
inspectable, including when the whole identity batch blocks DRAFT. Identity
proposals expose `intake_status=matched|pending_review`, raw source names/native
kind/ISIN, observation scopes, local catalogue candidates and typed reasons.
`matched` means a compatible proposal, never an accepted financial posting.
Source-month intake reuses exact compatible existing inactive cards automatically,
with alias/revocation/type guards and RUB scope preserved. Explicit manual selection
still refuses inactive cards. Unsupported financial evidence remains separate from
identity review.

One unchecked session opt-in enables deduplicated batches of at most 32 public
ISINs against MOEX ISS. The request DTO rejects all extra properties. The fixed
HTTPS adapter sends only exact ISIN/validated public SECID plus pagination controls;
no XML, filename, source hash, account, holdings, amount, path or credentials leave
the app. Redirects and ambient proxy/auth settings are disabled. Search pages must
be exhausted within bounds, with exact ISIN/SECID/type/currentness checks against
security specifications. Settlement `CURRENCYID` is never denomination authority.
The bounded new-card path accepts bonds only when official `FACEUNIT` proves a
supported denomination, including the exact official nominal-code alias `SUR` →
`RUB`, with raw `SUR` retained in the proof description. No other alias or settlement
currency fallback is accepted; stock/fund/absent/conflicting/stale metadata stays UNKNOWN.
Official metadata is not a quote, financial observation or broker holding proof.

Public interpretations, official URLs, description/search records and retrieval
time live in a bounded process-local cache for one hour. The latest lookup for an
ISIN retires all older proof IDs, including public-candidate A→B→A. An explicit refresh clears
session selections/public results and obtains a new full-original Preview before
new decisions. Backend restart evicts proofs and safely makes outstanding proposals
stale. Preview and Apply never fetch network metadata. Owner selection references
only a server-held proof ID, or an exact compatible current catalogue ID; it cannot
assert currency, assign legacy NULL-ISIN by name, or waive existing alias/revocation
conflicts. The single exceptions queue supports explicit deferral with no Skip.

After grouped decisions, the UI reparses the retained original with a fresh
source/dependency digest. The existing writer rechecks the entire identity batch
under its single writer reservation. New card/mapping IDs feed that same atomic
source-DRAFT transaction; official provenance is retained in its receipt. No
metadata-only commit or partial financial posting is added. Independent GET and
acknowledged-commit GET-only recovery remain the existing session flow; committed
same-key replay does not require the transient public cache. Unknown Money still
blocks Close/returns under the existing contracts.

Scope: one original per existing review session; the existing <=8-document batch
preflight stays advisory and unchanged. Navigation retains the original under the
supported session lifecycle. The unsaved File session does not survive reload/restart. The durable intake journal retains saved observations and decisions; mutation still asks to select the exact original again. No raw XML persistence,
localStorage/IndexedDB, separate financial ledger, Owner data operation or runtime
activation is introduced. Synthetic network fixtures are used for verification.

<a id="c4-mybroker_instrument_dispositions-17"></a>
### Append-only Skip, correction and obligation lifecycle

<a id="c4-mybroker_instrument_dispositions-17-1-source-preservation-decision"></a>
#### 1. Source preservation decision

The upload is reparsed in full. No XML filtering, synthetic report generation,
ISIN replacement, normalized-row deletion, or suppression of unsupported
observations is permitted. The original whole-file SHA-256, parser identity,
normalized document, source occurrence ordinals, native trade identities,
monetary observations and provenance remain unchanged by a skip.

Keep accepted S1 retention: persist only the whole-file hash, parser identity,
full normalized source facts/ordinals and disposition provenance. Never add
raw XML storage, an archive, source names/paths/private comments or XML backups.
The original bytes remain intact for Preview and authoritative Apply reparse;
source preservation means evidence fidelity, not bytes stored in the database.
Previously accepted S1 v2 records remain unchanged.


<a id="c4-mybroker_instrument_dispositions-17-2-smallest-identity-and-acceptance-scope"></a>
#### 2. Smallest identity and acceptance scope

- The durable disposition key is provider + immutable source import/document hash
  + exact source ISIN. It covers every occurrence of that ISIN in that document,
  including all explicitly bound source accounts. Preview discloses those accounts,
  every affected position/trade reference and linked Money evidence.
- The Owner chooses `map` or `skip` for each exact ISIN. `map` uses the existing
  compatible effective registry binding. `skip` creates neither an Instrument nor
  a BrokerIdentityMapping and supplies no Hermes instrument ID or historical class.
- Accounts always require their existing explicit mappings. Undecided instruments,
  contradictory/ambiguous mappings and source integrity/reconciliation conflicts
  still block source Apply. Skip cannot override any source-level conflict.
- A skip is never inferred from catalogue absence, current holdings, zero values,
  instrument names, tickers, account suffixes or another report. Each new document
  requires explicit review, including an overlapping report of the same ISIN.
- An already accepted S1 document with no disposition extension keeps exactly its
  accepted v2 semantics. Adding a skip retrospectively is refused. Original
  `mappings_json`, `normalized_json`, parser constants and hashes are not rewritten.


<a id="c4-mybroker_instrument_dispositions-17-3-append-only-lifecycle-and-atomicity"></a>
#### 3. Append-only lifecycle and atomicity

An additive, empty migration supplies a disposition revision ledger and Apply
receipts, separate from `mybroker_imports`. A revision freezes the key, reviewed
source-set fingerprint, exact account bindings, affected occurrence fingerprints,
contract version, typed Owner confirmation, expected predecessor revision,
confirmation digest and acceptance time. Append-only SQL guards and populated
downgrade refusal protect the ledger. Supported whole-file backup/recovery must
preserve it without special private artifacts.

Initial source acceptance and all initial skips commit together under the existing
SQLite writer reservation. Preview and Apply bind the entire unfiltered source,
mapped bindings, explicit decisions, relevant registry/lifecycle/financial state
and revision set. Stale, changed, contradictory or partially invalid decisions
roll back the entire Apply. No financial writes occur.

Same bytes, range, account bindings and accepted decision set replay as a source
no-op. A request receipt preserves the original committed revision identity;
independent GET also reports current disposition state. A reused request key with
different intent/digest conflicts. A changed skip choice on source reimport is
not a correction API and is refused.

Explicit revision-bound `revoke` withdraws the reviewed skip, retaining its
permanent affected occurrences as unresolved excluded evidence. It does not map
the ISIN, permit S2 promotion, remove blockers or restore completeness.
`reaffirm` can restore the same exclusion after review of fresh dependencies; it
cannot rewrite the source, accepted mappings or financial facts. Dependency loss
retires authority and must not silently revive after an A→B→A change.

Ordinary reimport/revoke/reaffirm cannot perform Skip↔Map correction, retrospective plain-S1 skips or source-economic replacement. The accepted bounded Skip-to-Map correction extension below is the sole reviewed exception; its complete overlapping support, target/account and independent S2 guards remain mandatory. Other corrections fail closed as reconciliation required, with C5 and CLOSED/Reopen protections.


<a id="c4-mybroker_instrument_dispositions-17-4-projection-and-evidence-rules"></a>
#### 4. Projection and evidence rules

All readers use one authoritative disposition resolver. Missing/invalid extension
state on a document accepted with skips fails closed. Resolver output separates
the immutable accepted disposition from current effective state and includes
permanent occurrence references and revision dependencies.

Skipped, retired and revoked occurrences cannot create canonical executions,
cash flows, snapshots, prices, valuations, cost basis or return-class assignments.
Their source trades remain in the evidence union for identity conflicts, pending
lifecycle, cash linkage and cutoff exposure. A mapped occurrence of the same
economic identity in another report must not silently promote an excluded trade;
mixed disposition/support requires reconciliation. No duplicate economic event
or cash leg can arise from repetition or overlap.

Source Apply success is separate from financial eligibility. An affected account
cannot become complete by totaling only mapped rows. Attestations cannot override
excluded inventory, linked money or possible cash/in-kind crossings. Historical
class remains unknown; all potentially affected classes in the historically
included account remain guarded.

| Reader/gate | Required treatment |
| --- | --- |
| S1 Preview, GET, lineage | Full unchanged document, mapped/skipped/unsupported counts, exact ISIN choices and revision state; coverage remains unknown. |
| S2 canonical trade acceptance | Disclose excluded occurrences; refuse promotion and mixed mapped/skipped support; keep economic identity and money ambiguity checks. |
| H0 inventory | Structural exclusion impact and revision fingerprints; preserve endpoint/event observations and no private values in reduced output. |
| H1 endpoint accept/reaffirm/GET | Excluded positions do not become endpoint components; potentially affected excluded inventory/trades remain blockers. No smaller complete account total. |
| H2-A1 / H2-B1 | Preserve money and full counterparty evidence; exclusion cannot supply outside-boundary, transfer or non-owner-flow semantics. |
| H2-A2 cash coverage | Excluded trade cash cannot automatically become accepted non-owner trade cash; possible crossing/opaque source evidence blocks completeness. |
| Class no-crossing / cash / in-kind coverage | Relevant exclusions block new claims and invalidate relevant existing reads; source Apply preserves pre-existing reconciliation guards. |
| H3 account/portfolio XIRR, class XIRR/TWRR, monthly materialization | Consult current exclusion impact in every availability path, including legacy fallback. Relevant exclusion gives explicit partial/NOT_COMPUTABLE; no solver input from skipped rows. |

Every affected acceptance fingerprint and lifecycle dependency must include the
disposition revision set. Both sanctioned ORM writers and supported SQL change
tracking must prevent disappearance, A→B→A restoration or an old receipt from
reviving authority. Reads may invalidate authority without changing CLOSED facts;
protected dependency correction still requires the existing explicit Reopen.


<a id="c4-mybroker_instrument_dispositions-17-5-frozen-scope-only-irrelevance-proof"></a>
#### 5. Frozen scope-only irrelevance proof

The only positive irrelevant case in v1 is disjoint historical account scope:
using effective immutable source account bindings and exact dated membership/
universe evidence, no affected mapped source account belongs to the requested
account/class/portfolio scope. Current account flags do not supply dated proof.
Portfolio/cross-account queries also require their independent tracked-transfer,
in-kind and roster gates. Unrelated independently evidenced scopes stay unchanged.

For a scope containing an affected account, there is no positive same-account
date-window irrelevance claim. Skipped settled position/value/unknown carry-forward
can affect any cutoff. Report non-overlap, earliest observation, later quiet
reports, absent/zero rows, equal actual/forward, old completed trades, catalogue
state and Owner skip do not establish lifetime, disposal or complete absence.
Relevant historical source-dependent endpoint, cash/in-kind/class completeness,
XIRR/TWRR and legacy/fallback eligibility remain partial/UNKNOWN/NOT_COMPUTABLE
with a specific excluded-source-impact reason. No guessed exposure expiry.

Full trades/Money/unsupported observations continue participating in identity,
link ambiguity, pending lifecycle and settlement/custody checks. Skip-linked
settled Money stays unresolved in H2-A2 even with valid native identity or mapped
support in another report. Preserve source Apply reconciliation refusal for
pre-existing COMPLETE claims; never silently downgrade or overwrite CLOSED facts.
A future independently accepted proof contract may relax same-account windows;
it is not a prerequisite for reviewed source Apply.


<a id="c4-mybroker_instrument_dispositions-17-6-ui-and-synthetic-acceptance"></a>
#### 6. UI and synthetic acceptance

Preview uses **Сопоставить** / **Пропустить (не учитывать)** and explains:
**Источник сохранён; для затронутой исторической доходности требуется полное подтверждение**.
Changing any choice retires confirmation; Apply requires a new reviewed Preview.
Success requires independent GET equality for the full normalized document,
accepted bindings, disposition revisions and counts. Accounts remain explicit.

Synthetic acceptance must cover:

- Mixed mapped/skipped/undecided instruments, independent filename/row account
  identities, REPO and unsupported observations; undecided/account/conflict
  refusal, mapped survival and no skipped catalogue or financial events.
- Byte/hash/parser/normalized-occurrence preservation through Preview→Apply→GET;
  existing fully mapped v2 and accepted legacy records behave unchanged.
- Exact same-hash replay, changed range/choice, stale remapping/revision, duplicate
  request keys, rollback/concurrent Apply and correction refusal.
- Overlapping repeated identities with consistent and mixed decisions; excluded
  Money remains identifiable and cannot establish complete coverage.
- Relevant H0/H1/H2/H3, legacy/class XIRR/TWRR and monthly eligibility refusal,
  plus a positively proven disjoint historical account scope; unresolved future pending,
  custody/settlement/commission and opaque transfer exposure remain guarded.
- Revoke/reaffirm, dependency retirement and SQL A→B→A protection; CLOSED/Reopen
  behavior; empty migration, append-only guards, populated downgrade refusal and
  supported backup/recovery.
- Russian choice interaction, stale confirmation and independent readback mismatch.

All fixtures are fabricated. No Owner data or runtime access, Stable/Test changes,
release or merge is authorized. Implementation requires the accepted contract,
synthetic evidence, full relevant exact-candidate CI, independent financial/data
candidate review and Integrator acceptance. Owner-local UAT is a separate gate.


<a id="c4-mybroker_instrument_dispositions-17-7-accepted-bounded-skip-to-map-correction-extension"></a>
#### 7. Accepted bounded Skip-to-Map correction extension

[#752 amended contract](https://github.com/LTstripes/hermes-finance/issues/752#issuecomment-6090540978)
and its [READY recheck](https://github.com/LTstripes/hermes-finance/issues/752#issuecomment-6090672906)
define the separate correction route deferred above. This does not change original
source acceptance, reimport or revoke/reaffirm semantics.

The API is `POST /api/mybroker-import/corrections/preview`, then
`POST /api/mybroker-import/corrections/apply`, followed independently by
`GET /api/mybroker-import/corrections/{request_id}`. Submit the complete declared
`decisions` array and strict `owner_reviewed: true`. Each decision binds `import_id`,
`document_sha256`, `isin`, `original_revision_id`, `expected_revision`,
`expected_correction_revision` (zero initially), exact effective `mapping_id` and
`hermes_id`, and the positively reviewed `reviewed_instrument_type`. Apply adds a
request ID and the fresh Preview's `confirmation_digest`.

Catalogue/account/registry preparation is separate. Existing mapping-trigger
retirement must finish before constructing these pins. Only an intact original
accepted Skip with a current, traceable retired predecessor is eligible. Revoked,
accepted, invalid or missing/unhistoried predecessors refuse. Exact target ISIN,
observed mapping ISIN, instrument type and observed trade currency must agree;
funds receive no equity fallback. A batch has no fixed size. Every declared
decision must pass, and all account/ISIN exclusion support across overlapping
imports must be included. The API never drops a failed fund or silently selects
an 18/17 tranche: a smaller scope needs its own accepted scope/overlap review.

Migration 0055 creates only empty, append-only correction receipts, revisions and
a monotonic change journal. Original Skip/source sets, revisions, receipts and
JSON remain untouched. Writer reservation, complete dependency reread and digest
comparison precede all inserts. Any mismatch or insert failure rolls back the
whole batch. Populated receipt downgrade refuses. Source/registry/catalogue
changes conservatively retire correction authority for the entire reviewed source
union; SQL A-to-B-to-A cannot restore it. Returning to the old target needs fresh
Preview and a new correction revision. Existing SQL guards remain installed.

GET separates the immutable committed receipt/revision IDs from current effective
corrections and unresolved exclusions. Exact request/digest replay returns these
same committed IDs with fresh current state; it never reaccepts retired authority.
A changed request payload/digest conflicts. An identical newly reviewed batch is
a correction-revision no-op only while every current effect is valid.

S1 reads retain original mappings and Skip history while exposing effective
mappings separately. S2, H0/H1/H2 and Performance use the same effective resolver.
S2 separately accepts canonical trade support and deduplicates economic identities
and Money across files. Within-file duplicate Money refuses correction; ambiguous
primary linkage and reducer conflicts remain blockers. Corrected Money stays
bound to its exact originally accepted account mapping, revalidated against the
effective registry and trade account even for Money-only support documents. It stays
unresolved in H2 until current independent S2 acceptance exists. H1/H2 and S2
fingerprints retain correction generation IDs, so fresh correction cannot revive
an older financial acceptance. Correction removes only resolved exclusion impact;
endpoint, membership, C1, fee, funding, REPO, pending, XIRR and TWRR gates remain.
Affected CLOSED facts refuse until explicit Reopen; Apply never changes facts,
months, deposits, catalogue or mappings. Owner-local preparation/UAT and numeric
return acceptance remain separate from synthetic code verification.

<a id="c4-position_class_identity-25"></a>
### Frozen historical class identity

<a id="c4-position_class_identity-25-minimal-design"></a>
#### Minimal design

One nullable `PositionSnapshot.historical_instrument_type` uses the existing
`InstrumentType` vocabulary. NULL means unknown/unavailable; `other` is
unclassified and is represented as NULL. This is snapshot identity evidence,
not class valuation, crossing coverage or return eligibility.

Creation captures the initial draft identity. Clone carries the source identity
as the existing month-copy workflow's starting point; copying unknown cannot
make it exact. Catalogue edits, quote/quantity updates, Close and Reopen never
refresh it. A correction explicitly supplies a type through position PATCH;
explicit NULL withdraws evidence. A CLOSED row must first be reopened, corrected
and reclosed. Legacy rows can only gain evidence by an explicit correction;
reopening/reclosing alone does not repair history.

Class-only correction/withdrawal preserves the stored financial totals, including
legacy totals that do not round-trip through rounded per-unit prices. Supplying
financial inputs continues to use the existing position recalculation rules.

Migration 0045 adds the nullable checked column without any data UPDATE/default.
Downgrade succeeds while all evidence is NULL and fails closed if evidence would
be lost. Old-schema backups require the existing forward recovery route or are
rejected by same-schema restore.

Readers of C1 must use this persisted field and never fall back to the current
catalogue. Historical Performance account scope remains the existing
`AccountPerformanceScopeMembership`; current account flags are not evidence.
Existing portfolio/account valuations, returns and presentation groupings are
unchanged. No class-return API or C2/C3 read model is introduced.

<a id="c4-membership_aware_valuation_identity_contract-10"></a>
### Membership-aware v2 identity and frozen legacy compatibility

<a id="c4-membership_aware_valuation_identity_contract-10-decision"></a>
#### Decision

Bind observed PRE/POST valuation evidence to **boundary-date historical membership material**
as well as the existing flow/group material. Use a v2 material hash. Do not grandfather
legacy v1 signatures. No database schema change is required for this policy.

Define the observation target identity:

```text
K = (
  reporting_month_id,
  scope,
  account_id,
  target_kind,
  target_id,
  boundary_date,
)

S2 = SHA256(canonical_json([
  "observed-valuation-material-v2",
  scope,
  account_id,
  boundary_date,
  existing_v1_flow_or_group_material,
  membership_material,
]))
```

Retain all existing #494 flow/group material, including explicit boundary-group membership.
Standalone-flow signatures now receive explicit observation scope/account context. PRE and POST
for one target intentionally share S2; relation and observed amount are not target material.


<a id="c4-membership_aware_valuation_identity_contract-10-boundary-date-membership-material"></a>
#### Boundary-date membership material

For **account scope**, include only the selected account and every historical membership row
covering the boundary date, represented deterministically as:

```text
(id, account_id, effective_from, effective_to, include_in_returns)
```

For **portfolio scope**, include every account ID in the canonical account catalogue and every
covering membership row for each account, including explicitly excluded accounts. Do not reduce
the identity to accounts that own the target flow/group.

Dates are inclusive; use ISO dates, literal null for open-ended ends and deterministic
account/row ordering. Account names, notes, visibility/status and current `include_in_returns`
are not historical membership evidence.

An authoritative binding requires exactly one covering membership row per relevant account.
Missing/overlapping history is non-authoritative. Explicit exclusion remains known history.

Conservatively, changing a covering row ID, either endpoint or the inclusion flag changes S2,
even when the resulting inclusion boolean on that date is unchanged. Editing an interval that
covers neither the old nor new boundary date does not invalidate that observation.

Whole-return-interval membership coverage and transition rules remain separate. This contract
does not invent intraday membership ordering or synthetic flows.


<a id="c4-membership_aware_valuation_identity_contract-10-capture-reservation-and-read-time-validation"></a>
#### Capture, reservation and read-time validation

Capture start obtains K and S2 in one coherent read associated with the actual observed values.
It must not fetch a fresh signature at submit time and attach it to older observations.

At publication:

1. acquire the SQLite writer reservation before authoritative rereads;
2. expire stale ORM state;
3. reread and validate membership, flow/group target identity and CLOSED state;
4. recompute current S2 and compare with the capture-start signature;
5. reject missing/invalid/mismatching identity with no automatic retry or re-signing;
6. hold the reservation through persistence and commit/rollback.

Concurrent outcomes are deterministic:

- membership correction commits first -> older capture fails S2 validation;
- capture commits first -> membership correction retires the persisted observation atomically;
- close wins first -> capture/membership write fails the CLOSED guard.

At read time, recompute S2 in the same coherent snapshot as the observed evidence.
Unbound/stale/mismatching signatures, invalid targets, duplicate PRE/POST sides or inconsistent
identities make the boundary unavailable. PRE and POST must match the same current K and S2.
Retain the existing currency, coverage, quality, provenance and ordering checks. Do not repair
or choose a convenient pair at read time.

The canonical authority path remains
`performance_availability._observed_boundary_for_target()`.


<a id="c4-membership_aware_valuation_identity_contract-10-legacy-v1-compatibility"></a>
#### Legacy v1 compatibility

Choose **fail-closed recapture**, not grandfathering.

Existing v1 hashes and null signatures cannot prove capture-time membership. Keep stored rows
without blanket migration/rewrite, but do not accept them as authoritative v2 observations.
Do not automatically rehash them, assume history was unchanged or manufacture provenance.
Normal authorized invalidation or fresh source-backed recapture may retire them.

Compatibility cost: exact TWRR that depends on v1 observations becomes unavailable until valid
PRE/POST evidence is supplied. CLOSED rows are not silently changed or reopened. This rule must
not independently disable XIRR.

A logical signature-version change is required, but a new schema/version column is not.
The existing nullable 64-character signature column can store the SHA-256 digest; v2 domain
separation plus strict recomputation is enough to reject legacy signatures safely.


<a id="c4-membership_aware_valuation_identity_contract-10-608-invalidation-and-validation-map"></a>
#### #608 invalidation and validation map

For account `a`, let `U` be the exact union of the complete old and new intervals of all
changed/replaced/withdrawn membership rows. It is not the UI selection and not an enclosing
gap-filled interval. Existing open-ended rows remain read-only/blocking in the first writer.


<a id="c4-membership_aware_valuation_identity_contract-10-observed-valuation-identity"></a>
#### Observed valuation identity

`material_signature_for_boundary()` and `stage_create_observed_valuation_point()` must use
v2 membership-aware identity, including targets that have no observation rows yet.


<a id="c4-membership_aware_valuation_identity_contract-10-observedvaluationpoint"></a>
#### ObservedValuationPoint

Atomically retire all PRE/POST rows affected by the changed membership:

- account-scope observations for account `a` whose boundary date lies in U;
- every portfolio-scoped boundary whose boundary date lies in U, regardless of target-flow
  ownership, including standalone flows of other accounts and groups with no member flow from a.

Preserve account-scoped observations for unrelated accounts.


<a id="c4-membership_aware_valuation_identity_contract-10-cashboundarycoverage--inkindboundarycoverage"></a>
#### CashBoundaryCoverage / InKindBoundaryCoverage

For account `a`, any overlapping COMPLETE attestation becomes UNKNOWN as a whole row.
Preserve row identity, dates and provenance fields. Do not split, delete or automatically
re-attest it. Do not invalidate unrelated accounts merely because they share a portfolio.


<a id="c4-membership_aware_valuation_identity_contract-10-read-time-availability-and-immutable-facts"></a>
#### Read-time availability and immutable facts

`_observed_boundary_for_target()` / `_twrr_boundary_reasons()` independently reject stale or
unbound evidence even if eager invalidation missed a row.

Canonical valuation/membership/flow/transfer/cash/in-kind readers recompute from canonical
history. Do not rewrite external flows or their separately asserted scope flags, transfer
evidence, boundary-group definitions, in-kind movement facts or monthly snapshot values.


<a id="c4-membership_aware_valuation_identity_contract-10-608-form-identity--read-back"></a>
#### #608 form identity / read-back

The #608 stale-state identity must cover the complete account membership history and affected
evidence/targets, including ObservedValuationPoint, ExternalFlowBoundaryGroup and
ExternalFlowBoundaryGroupMember. The existing preparation token is insufficient unchanged.

After commit, read back the exact resulting membership set and affected identities, then
coherently reread readiness and final XIRR/TWRR for the original request. A read error or
identity mismatch is not success.


<a id="c4-membership_aware_valuation_identity_contract-10-closed-and-atomicity"></a>
#### CLOSED and atomicity

Before membership mutation, reject if U intersects:

- any CLOSED reporting period;
- any CLOSED snapshot date within U;
- the CLOSED parent reporting month of any affected observed valuation evidence.

Resolve both stored observation identities and canonical targets. An unresolvable dependency
fails closed; it is not skipped.

Stale comparison, overlap/CLOSED checks, membership replacement, evidence invalidation and
resulting read identity are one transaction with no nested commits.


<a id="c4-membership_aware_valuation_identity_contract-10-required-reference-outcomes"></a>
#### Required reference outcomes

| Vector | Required outcome |
|---|---|
| Capture -> relevant include/exclude change -> publish | Reject old capture. |
| Capture -> covering interval endpoint moves -> publish | Reject old capture, even when inclusion at the boundary remains the same. |
| Capture -> covering row withdrawn -> publish | Reject; missing history remains unknown. |
| Account observation -> unrelated account membership changes | Preserve binding. |
| Portfolio observation -> another account enters/leaves at boundary | Reject old capture and retire affected portfolio PRE/POST. |
| Existing signed observation -> accepted membership correction | Retire both sides atomically; read-time validation rejects stale survivors. |
| Fresh observation after correction | Accept when corrected membership and all existing evidence requirements pass; no promise of computable returns. |
| Contractually metadata-only account/flow changes | Preserve binding where existing contracts already say material identity is unchanged. |
| Legacy v1 observation | Non-authoritative under v2; no automatic upgrade. |


<a id="c4-membership_aware_valuation_identity_contract-10-deliberate-boundary"></a>
#### Deliberate boundary

This is **current-material identity**, not a monotonic revision/audit generation.

If material state changes A -> B -> A and is exactly restored, the resulting S2 may again equal
the original hash. Rejecting solely because an intervening edit occurred would require a
separately accepted generation/version mechanism. #608 must not silently introduce one, and
must keep its separate stale-form/restore/duplicate-protection identity.

<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19"></a>
### Reusable broker mappings and explicitly approved baseline

<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-non-negotiable-invariants"></a>
#### Non-negotiable invariants

These remain authoritative and are not weakened:

- local single-user product; loopback-only; no cloud/auth/telemetry/trading/background refresh;
- exact money: `Decimal` / integer minor units, `ROUND_HALF_UP`, no binary `float` in financial logic;
- a CLOSED reporting month is immutable until explicit reopen;
- Hermes identity stays canonical; provider IDs are projections (ADR 0013 §6);
- frontend is not the financial source of truth;
- no raw Alfa payloads, credentials, runtime paths, or private diagnostic artifacts in Git, logs, API, or persistence;
- existing historical imports (manual, Excel, T-Invest quotes/payouts, Alfa depository PDF statements) remain historical truth and are not re-imported or rewritten by a current-state baseline.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-current-accepted-surface-baseline-of-this-contract"></a>
#### Current accepted surface (baseline of this contract)

This ADR is written against current `r07` `67fa84653be23c05852f2e05bd0c4bcd39c879f9`.

| Surface | What it already does | What it must not be mistaken for |
|---|---|---|
| `BrokerSnapshotProvider` / Alfa PRO adapter (ADR 0013, R06-03) | Owner-triggered read-only current snapshot | Historical ledger, cash-flow import, trading |
| R06-04 matching / preview | Explicit account mapping; explicit instrument mapping; exact unique ISIN; fail-closed conflicts | Persistent mapping store |
| R07-08A normalized reconciliation | Read-only row states; comparison-only provider valuation fields; `eligible_for_apply=false` | Apply path |
| R06-05 `broker_snapshot_apply` | Selective quantity apply into one editable month; dependent average cost / market price / NKD are owner-local decisions; closed-month refusal; fingerprint stale-preview protection; identical quantity + `keep_existing` dependents is `unchanged` | Persistent mappings; cash apply; provider price/UchPrice/NKD/P&L as Hermes values |
| `instrument_market_mappings` | Market-data quote identity (T-Invest `instrument_uid` / historical MOEX board identity) | Broker account/position identity |
| Alfa depository PDF import | Per-import transient statement mapping | Broker snapshot mapping |
| R07-07 `alfa_pro_positions` freshness family | Always `unknown` because Alfa observation timestamps are **not** persisted after quantity apply | A freshness clock invented from `updated_at` or apply time |

R06-05 already implements the quantity write the owner needs. The missing contract is: **when** a current snapshot may become the trusted current-state boundary, **which** Alfa fields may persist, and **how** owner-confirmed mappings are reused without silent remap.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-decision"></a>
#### Decision


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-1-introduce-a-persistent-broker-identity-mapping-registry"></a>
#### 1. Introduce a persistent broker-identity mapping registry

Add a local, owner-controlled **broker identity mapping registry**, separate from market-data mappings and from statement-import mappings.

The registry stores provider-scoped **account** and **instrument** identity links that the owner has explicitly confirmed. Subsequent broker snapshot preview/reconciliation **pre-populates** those links into the existing `OwnerMappingInput` shape and labels them as reused. The existing matcher remains the resolver. This ADR does not invent a second matching engine.

Logical record (storage shape is an implementation decision; these fields are normative):

```text
BrokerIdentityMapping
    mapping_id
    provider                  # e.g. alfa_pro; later t_invest broker snapshot
    subject_kind              # account | instrument
    provider_identity         # opaque provider key; see §3
    hermes_target_id          # accounts.id or instruments.id
    status                    # effective | revoked | superseded
    observed_isin             # instruments only; optional evidence at confirmation
    confirmed_at
    source_as_of              # snapshot observation time used at confirmation
    captured_at
    predecessor_mapping_id    # set on remap
    successor_mapping_id      # set when this row is superseded
    revoked_at / revoke_reason
```

Append-only lifecycle: confirm, revoke, and remap insert or status-transition history. They must not rewrite the original confirmation tuple `(provider, subject_kind, provider_identity, hermes_target_id, confirmed_at)`. Historical `PositionSnapshot` rows are never rewritten because a mapping later changes.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-2-registry-is-not-the-other-mapping-tables"></a>
#### 2. Registry is not the other mapping tables

| Store | Bounded context | Canonical key | This ADR |
|---|---|---|---|
| `instrument_market_mappings` | Market quotes (ADR 0009 / 0010) | provider + `provider_instrument_id` (+ venue) | Unchanged. T-Invest quote `instrument_uid` stays here. |
| Statement import mappings | Alfa depository PDF inspect/prepare/apply | Per-import ISIN/account mapping | Unchanged. Transient per import. |
| **Broker identity mapping registry** | Broker current holdings identity | `(provider, subject_kind, provider_identity)` | **New.** First implemented provider: `alfa_pro`. |

Copying or inferring broker mappings from market mappings, statement mappings, account names, `external_code`, tickers, section codes, or `IIAType` is forbidden. No automatic backfill from legacy data.

The registry is provider-neutral so a future T-Invest **broker** snapshot adapter (ADR 0010) can store `t_invest` account/instrument holdings identity without sharing the quote-mapping table. This ADR does not implement T-Invest broker import.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-3-provider-identity-keys"></a>
#### 3. Provider identity keys

Hermes local `account_id` / `instrument_id` remain canonical.

For `provider = alfa_pro` the registry keys are the keys the accepted matcher already uses:

| Kind | Provider identity | Alfa field | Not a registry key |
|---|---|---|---|
| `account` | `provider_account_id` | `ClientAccountEntity.IdAccount` | `IdSubAccount`, `IdRazdel`, `RCode`, names, `IIAType` |
| `instrument` | `provider_instrument_id` | `ClientPositionEntity.IdObject` / `AssetInfoEntity.IdObject` | ticker, name, section, subaccount |

Subaccount/section IDs remain snapshot observations. They are not mapping keys in this contract. Mapping at section granularity, or aggregating duplicate provider rows that resolve to the same Hermes `(account, instrument)`, remains the existing fail-closed rule (“no aggregation rule”). This ADR does not add that rule.

ISIN is **not** the registry key. Exact unique ISIN matching remains a deterministic **resolution path** under the existing matcher (see §5).

Provider identity is opaque text as already accepted. A changed provider id is a new identity, never a silent remap of the old one (ADR 0013 §6).


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-4-effective--revoked--remapped--uniqueness"></a>
#### 4. Effective / revoked / remapped / uniqueness

Statuses:

| Status | Resolver behaviour | Owner effect |
|---|---|---|
| `effective` | Loaded into `OwnerMappingInput` for the next preview | Shown as reused; owner may keep, revoke, or remap |
| `revoked` | Ignored | Owner must map again if the provider identity reappears |
| `superseded` | Ignored; successor is the effective row | Previous confirmation remains auditable |

**Remap** is revoke-by-supersession plus a new `effective` row in one explicit owner action. It is not an in-place overwrite of `hermes_target_id`.

While `effective`, uniqueness is fail-closed as follows, per provider:

1. **Forward (accounts and instruments):** at most one `effective` Hermes target for `(provider, subject_kind, provider_identity)`. A second distinct target for the same provider identity requires explicit remap.
2. **Reverse (instruments):** at most one `effective` `provider_instrument_id` for `(provider, hermes_instrument_id)`. A second provider instrument id for the same Hermes instrument requires explicit remap.
3. **Reverse (accounts):** multiple provider accounts may point at one Hermes account only when the owner confirms each pair explicitly. That is not aggregation: if those accounts then contribute duplicate resolved positions for the same Hermes instrument, the existing position-level conflict still wins.

Identical repeated confirmation of an already effective pair is idempotent (no new successor). Confirming a **different** Hermes target for an effective provider identity without an explicit remap/revoke is a **conflict** and must not write. The same applies to a second `effective` provider instrument id for one Hermes instrument.

Request-body mappings (today’s `OwnerMappingInput`) remain valid for one preview/apply:

- equal to an effective registry pair → reused, not a conflict;
- new provider identity with no effective row → candidate `new` mapping, persisted only after explicit confirmation (§6);
- disagrees with an effective registry pair and the request does not carry an explicit revoke/remap → `conflict`, fail-closed.

One Hermes instrument may appear under many mapped **accounts**; instrument uniqueness is per provider instrument id, not per account. Duplicate provider **position** rows that collapse to one Hermes `(account_id, instrument_id)` stay a position-level conflict (existing R06-04 rule). That conflict is not resolved by this registry.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-5-resolution-order-preview"></a>
#### 5. Resolution order (preview)

Each owner-triggered snapshot preview keeps the accepted gates: incomplete / stale / non-eligible / compatibility `unknown|unsupported` snapshots are fail-closed and not apply candidates (ADR 0013, ADR 0015, R07-08A).

Then:

1. Load `effective` registry rows for the snapshot’s `provider`.
2. Compose them with any explicit request mappings under §4.
3. Run the **existing** matcher:
   - accounts: explicit mapping only;
   - instruments: explicit mapping, else exact unique normalized ISIN (`strip` + `upper`; empty ISIN is absent);
   - ticker / name / `IIAType` / section code / numeric similarity never create identity;
   - explicit mapping that contradicts present ISIN evidence on both sides is `conflict` (existing B5).
4. Classify each identity row for owner display (presentation on top of matcher status, not a second matcher):

| Classification | Meaning |
|---|---|
| `reused` | Resolved from an `effective` registry row |
| `deterministic_isin` | Instrument resolved only by exact unique ISIN; no effective registry row yet |
| `new` | Unmatched; owner must map or skip |
| `ambiguous` | Existing matcher `ambiguous` (multiple Hermes ISINs) |
| `conflict` | Existing matcher `conflict`, uniqueness violation, or request/registry disagreement |
| `provider_identity_absent` | An `effective` registry row whose provider identity is not in this snapshot (orphaned; not auto-revoked) |

Owner-readable labels (title, type, short id) remain a presentation concern. They must not become registry keys. UUIDs/internal ids stay secondary.

Unique ISIN matching **may** resolve an instrument without a registry row. It must **not** silently insert a registry row. Persistence happens only under §6.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-6-when-the-registry-may-be-written"></a>
#### 6. When the registry may be written

Registry writes are explicit owner confirmations. Allowed writes:

- confirm a `new` account mapping;
- confirm an instrument mapping that the matcher already resolved (`explicit` or `deterministic_isin`) or that the owner picked from a non-ambiguous candidate set;
- revoke an `effective` mapping;
- remap as defined in §4.

Forbidden writes:

- silent persist because unique ISIN matched;
- silent persist because preview ran;
- silent persist because quantity apply ran **without** those identities being in the confirmed set;
- backfill from closed months, statement imports, market mappings, or guessed names.

A successful **baseline apply** (§7) of a selected position row **must** include, in the same transaction, confirmation of the account and instrument identities used for that row (already `effective`, or newly confirmed in this action). Quantity must not land without a durable identity explanation.

Revoke/remap never mutates already applied `PositionSnapshot` quantity, cost, or quotes.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-7-owner-approved-current-state-baseline"></a>
#### 7. Owner-approved current-state baseline

A **baseline** is an explicit owner action that uses one complete, compatibility-confirmed Alfa (or later broker) current snapshot to establish trusted **current position quantity** in **one editable reporting month**, after identity confirmation.

Normative flow (issue #201 UX, now contract):

1. Owner fetches a current read-only snapshot (existing adapter; no background refresh).
2. Preview shows reused / deterministic / new / ambiguous / conflict identities.
3. Owner confirms only unresolved/new mappings; may revoke or remap reused ones.
4. Preview shows current quantity differences for resolved identities (existing R06-04 / R07-08A states).
5. Owner explicitly applies **selected** quantity rows to the editable month through the accepted R06-05 apply path (fingerprint, selective, transactional).
6. Re-running the same baseline against unchanged identities and quantities is idempotent: selected rows come back `unchanged` and no financial fields move.

Baseline parameters:

| Field | Rule |
|---|---|
| `provider` | Snapshot provider; first implementation `alfa_pro` |
| `reporting_month_id` | Must exist and be editable (`draft`). CLOSED → refuse, existing `CLOSED_MONTH` semantics. |
| `baseline_date` | Owner-declared current-state date. **Must equal** that month’s `snapshot_date`. Planned owner use is `2026-08-31` on the August 2026 month whose `snapshot_date` is that day. A mismatch is fail-closed. |
| `source_as_of` / `captured_at` | Provenance of the snapshot actually confirmed. Local observation time may differ from `baseline_date`; do not substitute one for the other (R07-07 four clocks). |

What a baseline **may** establish, after explicit owner confirmation:

- registry account mappings;
- registry instrument mappings (deterministic or owner-picked);
- `PositionSnapshot.quantity` for selected resolved rows with provider quantity `> 0`, via R06-05 `update` / `create`;
- baseline provenance (§8).

What a baseline **must not** silently establish or overwrite:

- any other reporting month, including earlier closed months and other drafts;
- deposits, withdrawals, transfers, statement payouts, T-Invest payouts, or performance history (`external_flows`, valuation points, XIRR/TWRR inputs);
- Hermes `average_cost_per_unit` from Alfa `UchPrice` / accounting price;
- Hermes `market_price_per_unit`, `price_date`, `price_source` from Alfa `Price`;
- Hermes `accrued_interest` from Alfa `NKD` / `PSTNKD`;
- Hermes unrealized result from Alfa `NPLtoMarketCurPrice` / `DailyPL`;
- Hermes cash balances from Alfa `ClientBalanceEntity.Money` (still non-comparable at this `r07` schema);
- new Hermes accounts or instruments invented from the snapshot;
- credentials, raw frames, or private diagnostics.

R06-05 dependent-field rules stay: `create` requires explicit **local** average cost and market price/date/source; `update` requires explicit `keep_existing` or explicit **local** replace. Provider valuation fields are never a legal replace source.

Zero or missing provider quantity cannot be applied (existing R06-05). A missing provider row must not delete a Hermes position. Hermes-only rows are visible in preview; clearing them is outside this baseline contract.

`ClientPositionEntity.IsMoney = true` is a cash-like observation. Those rows are **not** quantity-baseline eligible and must not create or update `PositionSnapshot` instrument rows. They stay with the cash/comparison family.

Provider-only rows whose identity is unresolved stay `unresolved` / `new`. They are never silently created.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-8-baseline-provenance-minimum-persist"></a>
#### 8. Baseline provenance (minimum persist)

When a baseline apply commits, persist a month-scoped **baseline provenance** record (name is an implementation decision) containing only:

- `provider`;
- `reporting_month_id`;
- `baseline_date`;
- `source_as_of`;
- `captured_at`;
- owner `confirmed_at`;
- sanitized `compatibility_fingerprint` / apply fingerprint already used by R06-05 / ADR 0015;
- per selected row: `position_snapshot_id`, action `created|updated|unchanged`, applied `quantity`.

Do not persist provider prices, NKD, P&L, cash amounts, tickers, names, or raw snapshots in this record.

This **narrowly supersedes** ADR 0013 §11 for the enumerated minimum in §10 only. Issue #201 is the owner’s explicit persistence confirmation for those fields. The legal/terms gate remains closed for raw payloads, undocumented extras, and any broader Alfa-derived ledger.

R07-07 currently states that Alfa PRO observations are transient and the `alfa_pro_positions` family is always `unknown` (`alfa_pro_observation_not_persisted`). After the implementation slice that writes §8, that family must be updated to read this provenance: `source_as_of` is the observation clock; `confirmed_at` is import/apply time and is **not** freshness. Until that slice lands, R07-07 stays as written.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-9-existing-historical-data-and-coexistence"></a>
#### 9. Existing historical data and coexistence

A current Alfa baseline **coexists** with earlier imported history as a new trusted **current-state** boundary:

- closed months keep their snapshots;
- statement/T-Invest/manual history is not re-derived from Alfa current state;
- the selected draft month becomes the owner-approved current holdings quantity for that `snapshot_date`;
- later months are not auto-cloned or backfilled by this contract (existing month clone/reopen rules unchanged);
- performance/history contracts that already treat closed snapshots as truth continue to do so.

No migration rewrites owner data. No backfill of the registry.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-10-alfa-fields-persist-vs-comparison-only-vs-ignored"></a>
#### 10. Alfa fields: persist vs comparison-only vs ignored

Authoritative raw-field meanings remain R06-03 / `FIELD_MAPPINGS`. A field name is still not evidence. This table is the **persistence/apply** gate on top of that mapping.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-101-may-persist-minimum"></a>
#### 10.1 May persist (minimum)

| Alfa entity.field | Snapshot field | Persist as | Condition |
|---|---|---|---|
| `ClientAccountEntity.IdAccount` | `provider_account_id` | registry account identity | Explicit owner confirm / baseline confirm |
| `ClientPositionEntity.IdObject` / `AssetInfoEntity.IdObject` | `provider_instrument_id` | registry instrument identity | Explicit owner confirm / baseline confirm |
| `AssetInfoEntity.ISIN` | `isin` | optional `observed_isin` evidence on the instrument mapping; also deterministic match input | Never the registry key; never overwrites a conflicting Hermes `Instrument.isin` |
| `ClientPositionEntity.TorgPos` | `quantity` | `PositionSnapshot.quantity` | Explicit selected R06-05 apply; quantity `> 0`; identity resolved and confirmed; not `IsMoney` |
| (Hermes clocks) | `source_as_of`, `captured_at` | baseline provenance | Written only with a committed baseline apply |
| (sanitized ADR 0015) | compatibility fingerprint | baseline provenance | Value-independent structural fingerprint only |


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-102-comparison-only--preview-may-show-never-write-as-hermes-financial-truth"></a>
#### 10.2 Comparison-only — preview may show; never write as Hermes financial truth

Listed names match `COMPARISON_ONLY_PROVIDER_FIELDS` plus cash and classification observations.

| Alfa entity.field | Snapshot field | Why comparison-only |
|---|---|---|
| `ClientPositionEntity.Price` | `broker_unit_price` | No accepted unit/currency/scale conversion into Hermes `market_price_per_unit` |
| `ClientPositionEntity.UchPrice` | `accounting_price` | Must not become `average_cost_per_unit` merely because it exists |
| `ClientPositionEntity.NKD` | `accrued_interest_nkd` | Non-comparable vs Hermes kopecks; not auto NKD apply |
| `ClientPositionEntity.NPLtoMarketCurPrice` | `unrealized_result` | Hermes unrealized is derived from local valuation; not broker НПУ |
| `ClientBalanceEntity.Money` | cash `amount` | Hermes cash is month-scoped and (on this `r07`) not account-linked; existing cash rows stay `non_comparable` |
| `ClientPositionEntity.IsMoney` | `is_money` | Classification only; money rows are not instrument quantity baseline |
| synthesized `market_value` | `market_value` | R06-03 forbids `TorgPos * Price` stand-in; no official position market-value field |
| `SubAccountRazdelEntity.RCode` / `IdRazdel` / `IdSubAccount` / `IdRazdelGroup` | section/subaccount observations | Display/correlation only; not registry keys |
| `AssetInfoEntity.Ticker` / `Name` | `ticker` / `display_name` | Discovery/display hints; never identity; not stored as mapping keys |

R07-08A `comparison_only_fields` remains the API list for valuation observations. Implementation must not promote those fields into write instructions.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-103-unresolved--ignored--do-not-map-persist-or-infer"></a>
#### 10.3 Unresolved / ignored — do not map, persist, or infer

| Alfa field | Reason |
|---|---|
| `ClientAccountEntity` extras / live `IIAType` | Undocumented; IIS stays owner-controlled (ADR 0013 §7) |
| `ClientPositionEntity.PSTNKD` | Insufficient to distinguish from `NKD` |
| `ClientPositionEntity.DailyPL` | Daily P/L is not unrealized-result |
| `ClientBalanceEntity.PortfolioCost` | Portfolio-level; not position market value |
| `ClientOperationEntity` and type codes `3` / `14` | Not in the production snapshot; not a ledger (ADR 0013 §9) |
| `#Order.*`, limits, archive, order book, trade tape | Trading/out of adapter |
| Raw router frames, credentials, exception text | Privacy / ADR 0013 §10–11, ADR 0015 |


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-11-synthetic-acceptance-examples"></a>
#### 11. Synthetic acceptance examples

All identities below are synthetic (`SYN-*`). No owner/runtime values.

Shared fixture unless a row overrides it:

- provider `alfa_pro`;
- Hermes account `H-ACC-1`, instrument `H-INS-1` with ISIN `SYN000000001`;
- draft month `2026-08` with `snapshot_date = 2026-08-31`;
- complete compatible snapshot, `eligible_for_apply = true`.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-e1--first-time-mapping"></a>
#### E1 — First-time mapping

**Given** empty registry; snapshot account `SYN-ACCOUNT-001`, instrument `SYN-INSTRUMENT-001` with unique ISIN `SYN000000001`, `TorgPos = 10`; Hermes has `H-ACC-1` / `H-INS-1` and no August position.

**When** owner maps `SYN-ACCOUNT-001 → H-ACC-1`, accepts the unique-ISIN instrument resolution, and applies create with explicit local average cost and market price.

**Then** registry gains two `effective` rows; August `PositionSnapshot.quantity = 10`; baseline provenance written; comparison-only `Price`/`UchPrice`/`NKD` are not copied.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-e2--reused-mapping-next-run"></a>
#### E2 — Reused mapping next run

**Given** E1 registry rows still `effective`; next snapshot same identities, `TorgPos = 12`; August still draft with quantity `10`.

**When** owner opens preview with no request mappings.

**Then** account and instrument classify `reused`; owner is not asked to re-enter them; quantity preview is `differs` / `12 vs 10`; apply update with `keep_existing` dependents writes quantity `12` only.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-e3--new-instrument"></a>
#### E3 — New instrument

**Given** E1 registry; snapshot adds `SYN-INSTRUMENT-002` with ISIN `SYN000000002` and no Hermes instrument with that ISIN.

**When** preview runs.

**Then** `SYN-INSTRUMENT-001` stays `reused`; `SYN-INSTRUMENT-002` is `new` / unmatched; no row is auto-created; quantity apply of the new id is refused until the owner maps it to an existing Hermes instrument (or creates that instrument **outside** this flow, then maps). This flow does not invent instruments.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-e4--changed-provider-account-identity"></a>
#### E4 — Changed provider account identity

**Given** effective `SYN-ACCOUNT-001 → H-ACC-1`; new snapshot has only `SYN-ACCOUNT-002` (old id absent).

**When** preview runs.

**Then** `SYN-ACCOUNT-001` is `provider_identity_absent` (not auto-revoked, not silently rebound); `SYN-ACCOUNT-002` is `new`; positions under `002` stay unresolved until explicit remap `001` superseded and `002 → H-ACC-1` confirmed. No quantity apply through the orphaned mapping.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-e5--conflicting-isin"></a>
#### E5 — Conflicting ISIN

**Given** effective `SYN-INSTRUMENT-001 → H-INS-1` and Hermes ISIN `SYN000000001`; snapshot `SYN-INSTRUMENT-001` now carries ISIN `SYN000000099`.

**When** preview runs.

**Then** instrument status is `conflict` (“explicit mapping contradicts provider ISIN evidence”); classification `conflict`; row is not applyable; registry remains `effective` until owner remaps or fixes local ISIN by the ordinary instrument editor. No silent retarget.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-e6--revoked-then-remapped"></a>
#### E6 — Revoked then remapped

**Given** E1 effective instrument mapping.

**When** owner revokes `SYN-INSTRUMENT-001`, then remaps it to `H-INS-2` (existing Hermes instrument, ISIN compatible or absent).

**Then** original row becomes `superseded` (or `revoked` then a new confirm — remap must leave history); new `effective` row points at `H-INS-2`; previously applied August quantity on `(H-ACC-1, H-INS-1)` is **unchanged**; later preview uses `H-INS-2`.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-e7--identical-baseline-rerun"></a>
#### E7 — Identical baseline rerun

**Given** E1 after apply (quantity already `10`, dependents kept); same snapshot, same mappings, same `baseline_date`.

**When** owner applies the same selected row with the same fingerprint-valid keep-existing decisions.

**Then** result item action is `unchanged`; `PositionSnapshot` financial fields and `updated_at` semantics follow existing R06-05 no-op (no rewrite); provenance may record the rerun as unchanged evidence but must not invent a second quantity history. Mapping confirm is idempotent.


<a id="c4-0016-owner-approved-alfa-baseline-and-broker-mappings-19-e8--closed-month-refusal"></a>
#### E8 — Closed-month refusal

**Given** August month `closed`; registry may already be populated.

**When** owner requests baseline apply (or R06-05 apply) for that month.

**Then** refusal with existing closed-month semantics; no quantity write; no registry write as a side-effect of the refused apply. Reopen remains the only path to edit that month. Preview may still be read-only.

Additional synthetic guards the implementation slices must keep (already accepted elsewhere, restated so they are not dropped):

- request maps one provider account to two Hermes accounts → `conflict`;
- two provider position rows resolve to the same Hermes pair → position `conflict`, no aggregation;
- stale/incomplete/compatibility-unknown snapshot → no actionable rows, `eligible_for_apply` false;
- `UchPrice` present and owner omitted local average cost on **create** → validation error, not a silent copy.

<a id="c5"></a>
## 5. Money, trades, settlement, fees and NKD

Recognition Money, accepted coupon net, Owner funding and execution cash legs are distinct. Preserve the one economic owner of each occurrence/leg. Cash already present in an endpoint cannot be credited twice. Principal redemption is capital, not passive income. Source algebra validates an independently established basis; it never chooses a convention. Bond BUY needs the supported S/N/F proof; stock BUY uses the separately proved S/F basis and cannot fill paid NKD with a synthetic zero.

<a id="c5-mybroker_money_candidates-1"></a>
### Money occurrences and acceptance boundaries

Authority: [#778 accepted contract](https://github.com/LTstripes/hermes-finance/issues/778#issuecomment-6109639388)
and the bounded implementation assignment [#780](https://github.com/LTstripes/hermes-finance/issues/780).

`services.mybroker_money_candidates.read_money_candidates(session, import_id=...,
document=original_bytes, filename=original_filename, account_id=...)` is a
standalone backend diagnostic read. It returns the typed
`mybroker-money-candidates-v1` inventory for an accepted S1 import. There is no
HTTP route, persistence model, acceptance endpoint or financial writer.

The read uses a committed coherent snapshot. It reparses the original through
the unchanged S1 family/namespace/schema/filename/cardinality/bounds rules and
requires equality of every parser fact, ordered Money leaf and section inventory
against the immutable import. Established service enrichment is preserved;
occurrence fingerprints use the full saved S1 rows, exactly like existing cash
coverage readers. Changed bytes, parser, declared range, account facts, amounts
or ordinals refuse interpretation with a bounded error code.

The bounded [S1 native-linkage extension](#c3-mybroker_s1-1-native-money-linkage-compatibility-788)
selects original reparsing from the accepted receipt's optional
`money_linkage_version`. Absence preserves the legacy comment-only interpretation,
including previously unsupported oper_type-only leaves. Newly accepted native
settlement/commission observations retain S1 precedence. No old fingerprints,
S1 JSON or financial receipts are reclassified; unknown versions and contradictory
native/comment roles or IDs refuse interpretation.

Every signed amount leaf remains an observation, including unsupported rows and
the existing settlement/commission roles. Those roles retain precedence and
their saved linkage; they are never second candidate cash rows. Explicit,
currently valid `alfa_mybroker` bindings must resolve both filename and row
account to the selected brokerage/IIS account. Invalid bindings, posted dates
outside the confirmed range, non-RUB amounts, zero, fractional kopecks, signed
64-bit overflow and wrong direction leave the observation unsupported with
typed reasons. There is no rounding or currency/date substitution.

The three observed shapes are exact-operation, full-narrative coupon and
incoming-account-cash candidates, and exact negative `НКД по сделке`. Narrative
recognition is bounded to 4096 characters. Per the
[Integrator source-shape finding](https://github.com/LTstripes/hermes-finance/pull/784#issuecomment-6110094535),
the coupon suffix is exactly `д.ф.DD.MM.YY`. Calendar validity uses a fixed
Gregorian 2000–2099 validation anchor, with no `%y` pivot and no narrative-date
value returned or used as financial evidence. Four-digit, partial and invalid
calendar forms remain unsupported. This shape check never replaces the actual
posted `settlement_date`. Placeholder issuer/bank/token
values never become instrument, owner, trade or economic identities. Unknown
and dividend shapes remain unsupported. All candidate authority is `unproven`;
instrument/event links stay null, incoming cash has unknown owner crossing and
portfolio externality, and paid NKD has unknown execution linkage and embedding
basis. No current accrued valuation is inferred.

`summary_proof_unavailable` is mandatory: the accepted manifest does not prove
the complete source-rooted account/currency/amount summary selector or row join.
No `oper_group` label or matched total is manufactured. All current S1
blockers/conflicts and missing mappings remain in the inventory exceptions,
including opaque, pending, REPO and unparsed-source evidence.

The inventory exposes all relevant overlapping accepted reports and their
Money occurrence references, even after binding withdrawal. Same-report
multiplicity stays visible. Different matching multiplicities in overlapping
reports have an explicit `overlapping_source_multiplicity_mismatch` diagnostic;
the reader does not pair or collapse their rows. Equal date/amount/currency only identifies possible
competing evidence; it never establishes economic equivalence. Missing matches
in a report covering the posting date remain explicit. No report union is
summed or deduplicated. `source_subtotals` counts admissible candidate leaves
only within the selected original, preserving repeated leaves. It is diagnostic
source arithmetic and must not be added to endpoint cash or interpreted as
canonical payments.

DTO source hashes, account aliases and occurrence fingerprints are Owner-local
provenance. Do not log/publish them. Raw narratives, bank/issuer names and tokens
are consumed in memory and are absent from DTOs and errors. Public tests and
evidence use fabricated originals only.

S1 JSON/receipts, financial ledgers, source cash, UNKNOWN coverage and Close
guards are unchanged. The standalone inventory reports
`financial_apply_available=false`; recognition cannot complete source-account
bookkeeping. The separate financial contract/writer and later Owner UAT remain
outside this adapter.

<a id="c5-mybroker_s2_a-12"></a>
### Executed trades, settlement, commission and paid NKD

<a id="c5-mybroker_s2_a-12-persistence-and-source-linkage"></a>
#### Persistence and source linkage

Migration `0049_executed_trade_truth` adds four empty tables without backfill:

- `executed_trades`: stable Hermes ID, unique provider/source account/ordered
  native-ID pair, frozen economic core and exact accepted mapping IDs/targets;
- `executed_trade_occurrences`: unique S1 import/section/ordinal references and
  source fingerprints, separate from economic execution identity;
- `executed_trade_revisions`: append-only accepted lifecycle/evidence snapshots,
  revision/material fingerprint, reviewed confirmation digest and acceptance time;
- `executed_trade_applies`: idempotency receipts for entire selected sets.

Core quantity/price and source amounts are lossless canonical decimal strings.
RUB money additionally uses integer minor units with `ROUND_HALF_UP`; a minor-unit
value for an unsupported currency stays null, with the original source amount
and currency retained. No quantity × price, FX, bond/NKD or cash projection is
performed. A populated ledger/receipt refuses destructive downgrade.

The alias requires both native IDs. Overlapping documents add provenance, never
another execution or cash leg. Distinct native pairs with identical economics
stay distinct. Exact settlement/commission material has one canonical leg with
all supporting S1 money-row references. Multiple differing legs and ambiguous
primary-only linkage remain conflicts; split/refund cases are not aggregated.
Identical repeated money rows within a single document retain observed
multiplicity and all row references; they never prove a single settlement or
single economic cost. Cross-document repetition remains occurrence lineage.
Money-row ownership is recomputed from source account and primary native ID
across the full accepted union before using any stored linkage, including null
links. An incomplete-ID observation competing with a full identity is ambiguous.


<a id="c5-mybroker_s2_a-12-lifecycle-and-evidence"></a>
#### Lifecycle and evidence

`pending` stores prospective observation and planned dates, without actual dates
or actual cash legs. Monotonic pending → settled enrichment preserves the economic
core and earlier revision. `settled` can still lack actual cash/depo dates, usable
money evidence, fee basis or historical event-C1. These are separate readiness
dimensions; source settlement-money rows remain authority, while trade amount
only checks consistency. Nothing becomes financially ready in S2-A.

Fee basis supports `zero / separate / embedded / unknown` in persistence. S2-A
can establish only an explicitly observed zero with no commission leg, or
`unknown`. Nonzero linked fee rows remain attributable source evidence, without
accepting separation/embedding or another economic cost. S2-B owns those explicit
reconciliations. Event-C1 remains nullable and is never filled from the current
catalogue, an account name or a neighbouring snapshot. Source lifecycle is
distinct from active/superseded/retracted acceptance; S2-A writes only active
source acceptance and cannot correct/retract a previous acceptance.


<a id="c5-mybroker_s2_a-12-api-and-authoritative-acceptance"></a>
#### API and authoritative acceptance

Use identities returned by `/api/mybroker-import/lineage`:

1. `POST /api/executed-trades/preview` with `{"identities": ["<source digest>"]}`.
   Candidates disclose `create / enrich / noop`, frozen bindings, source
   occurrences, actual/planned dates, cash evidence and conflicts/readiness.
2. `POST /api/executed-trades/apply` with the same selected identities,
   `confirmation_digest` and a caller-generated `request_id`. No normalized
   browser rows, arbitrary fee/C1 facts or target corrections are accepted.
3. Independently `GET /api/executed-trades/{trade_id}` (or the collection) and
   compare the committed aggregate, revision, evidence and conflicts.

Preview binds the full accepted source union/document hashes/ranges/parsers,
mapping lifecycle, canonical revisions/occurrences, month states, historical
memberships, legacy reconciliation facts and dependent coverage. Apply reserves
SQLite's writer before authoritative reread; changed state refuses the entire
set. Any selected conflict or write failure rolls back all aggregate, occurrence,
revision and receipt writes. Identical fresh material is a revision no-op.

An exact request replay returns current committed readback without writing; a
reused key with different selected identities/confirmation is an idempotency
conflict. A replay does not reaccept or repair newer source/mapping changes.
Every read reports current conflicts separately from the frozen accepted core
and exposes prior revisions. New S1 evidence requires another reviewed enrichment;
changed core/bindings or withdrawn/disputed support cannot overwrite acceptance.


<a id="c5-mybroker_s2_a-12-dependencies-and-boundaries"></a>
#### Dependencies and boundaries

Accepted COMPLETE no-crossing contradictions block acceptance; source/class
guards remain in place. Canonical accepted or disputed executions independently
block affected historical account intervals for all potentially affected classes
while event-C1 is unresolved. Pending persists through later cutoffs; actual
cash/depo/fee dates remain distinct. Missing/changed source support cannot restore
no-crossing by disappearance. Class material signatures additionally bind
canonical revisions when relevant. Dependency guards remain anchored to the
latest accepted canonical revision; newer S1 evidence can strengthen blocking
but cannot relax it until S2 Apply explicitly accepts the enrichment.
Read blocking does not mutate CLOSED months, coverage claims or endpoint facts,
and source-only append-only promotion does not authorize financial correction
through CLOSED history.

Coverage remains `unknown`. No ReportingMonth, PositionSnapshot, CashBalance,
InvestmentCashFlow, ExternalFlow, payout, transfer or UFSR fact is created or
changed. No return consumer, historical reconstruction, realized P&L or bond
arithmetic is enabled. S2-B reconciliation/correction/retraction, #709 backfill,
financial/data candidate review and Integrator acceptance remain separate.


<a id="c5-mybroker_s2_a-12-reviewed-paid-buy-cash-extension"></a>
#### Reviewed paid-buy cash extension

[#781 accepted contract](https://github.com/LTstripes/hermes-finance/issues/781#issuecomment-6109886284)
and #783 extend an existing source-owned DRAFT through the `broker_money_v1`
batch. A `trade` decision selects one original negative paid-NKD Money occurrence,
the existing canonical `trade_id` and its exact `expected_trade_revision`.
`TradeCashClaims` binds a specific review to the server's context digest and
separately confirms the settled RUB bond BUY link, the complete occurrence set,
separately posted NKD, separately charged nonzero native-ID commission and an
independently proved native-total basis. The desktop form discloses the ordered
native IDs, posted S/N/F, native T/summ_nkd/bank_tax and actual cash/custody dates.

`includes_paid_nkd` checks `-(S+N)=T`; `excludes_paid_nkd` checks `-S=T`, using
signed debits. Neither equality discovers the basis. Native NKD and fee must
agree exactly in kopecks with the separate negative Money legs. The actual
cash debit remains `S+N+F` once. Fractional kopecks, missing/multiple cash legs,
unsupported pending/REPO/FX, ambiguous primary linkage, changed mappings and
target reassignment refuse the entire batch.

Apply appends the existing `ExecutedTradeRevision` with `fee_basis=separate`,
three cash legs and the accepted reconciliation. Money occurrence ownership
uses existing `ExecutedTradeOccurrence` entries, the same cross-writer mutex
as coupon/H2 ownership, and the existing immutable month receipt journal.
No migration, second cash ledger, payout/owner event for NKD, endpoint cash
increment or inferred EOD NKD/cost basis is introduced. Accepted S1 JSON and
earlier revisions stay immutable.

Candidate rebuild, canonical GET, source-account readiness and reserved Close
revalidate the same receipt and reconciliation. A source union/target/catalogue
change or reopening retires authority monotonically; restoring old values or
replaying an old request cannot reaffirm it. New explicit review is required.
One supported trade does not clear opaque Money, unparsed UFSR/REPO/transfer
sections or other source gaps. C1, portfolio scope and exact returns remain
unavailable. Synthetic Close evidence does not establish real-account Close.


<a id="c5-mybroker_s2_a-12-stock-buy-separate-commission--typed-code-integrated-real-source-basis-blocked"></a>
#### Stock BUY separate commission — typed code integrated; real-source basis BLOCKED

[Independent #790 financial/source contract](https://github.com/LTstripes/hermes-finance/issues/790#issuecomment-6113136761)
received [Integrator conditional ACCEPT](https://github.com/LTstripes/hermes-finance/issues/790#issuecomment-6113269181).
The 2026-10-11 contract was design GO only. On 2026-10-12, exact
[#790 PR #796](https://github.com/LTstripes/hermes-finance/pull/796)
implemented the bounded typed source-owned proof and desktop review; **no real
Owner stock fee has been independently source-accepted**. Its exact merged
commit is `fee94e4fd4c77db3e50500a6fc3b6d103af2b498`; refer to
[post-main CI 38212066232](https://github.com/LTstripes/hermes-finance/actions/runs/38212066232)
for completed SUCCESS (attempt 1, all applicable jobs).
The existing #783 path is exclusively a settled RUB **bond BUY** with
separate negative settlement, paid NKD and fee legs, and an explicitly reviewed
native total NKD inclusion basis. It cannot be reused for a stock commission
by supplying a synthetic zero NKD event.

The implemented two-leg stock variant must prove an existing settled RUB
**stock BUY** by provider + account + **ordered two native IDs**, one exact
negative settlement `S` and separately charged negative commission `F`
bound to the unique native primary. It requires an **independently established**
native fee-excluded `summ_trade=T`, matching source `bank_tax=B` and verified
`-S=T` / `-F=B` at exact kopecks. Merely matching these equations, matching
monthly cash or checking a generic confirmation is **not** proof of the
accounting convention. For the current real source that independent fee-basis
referent is still unaccepted: it may require one specific Owner-local evidence
reference; without it the execution's `commission_basis_unresolved` must remain.

The implementation follows accepted [#788](https://github.com/LTstripes/hermes-finance/issues/788)
and reuses the existing Money batch,
`ExecutedTradeRevision`, `ExecutedTradeOccurrence` and immutable receipts.
The stock proof is strictly discriminated from the bond three-leg proof.
The dedicated `stock_buy_separate_fee_v1` claims and Money commission seed
are validated separately from legacy three-leg bond proofs. Literal pre-change
coupon/H2/bond/zero-fee JSON fingerprints and receipts stay compatible;
stock fees deduplicate by provider/source account/ordered native execution IDs
and role, not by matching narrative/date/amount. A specific basis-reference
identifier is stored in the review context, but **cannot by itself establish
the broker's fee-exclusion convention**. An independent Owner-local source proof
is mandatory before real September acceptance.

There must be **two** cash roles and **no** paid-NKD role, extra CashBalance,
InvestmentCashFlow, H2, ExternalFlow, cost-basis or EOD accrual.
NULL accrued remains NULL, observed source zero stays observed zero.
Unknown fee inclusion, embedded/multiple fee, SELL, FX, REPO, pending,
native-primary ambiguity and contradictory receipt evidence remain BLOCKED.
Preview, Apply, canonical trade GET, broker-month GET and reserved Close must
consume the **same** proof, scoped per affected trade and source account.
[#787](https://github.com/LTstripes/hermes-finance/issues/787)
real-original Gate 0 remains BLOCKED until all its independently validated
source compatibility gates pass.

See the [11 October dated closeout](DEVELOPMENT.md#d5) for
source-specific sequencing without duplicating private Owner financial data.

<a id="c5-instrument_cash_income-1"></a>
### Known instrument net cash income

Accepted boundary: [#858](https://github.com/LTstripes/hermes-finance/issues/858)
and [#855 acceptance](https://github.com/LTstripes/hermes-finance/issues/855#issuecomment-6231173234).

`GET /api/instruments/{instrument_id}/cash-income?account_id=…&t0=YYYY-MM-DD&t1=YYYY-MM-DD`
reads one exact brokerage/IIS account, one historically supported RUB stock/bond,
and posted dates `(t0,t1]`. Invalid dates return 422, missing references 404.
The desktop entry is an on-demand block on Capital → Performance. It lists the
catalogue including inactive instruments; current holdings do not filter payouts.

The canonical service owns composition; ICF owns economic identity. Each ICF ID
appears once. Equal dates and amounts are not a deduplication key. Money source
occurrences and typed PDF links qualify the ICF rather than adding cash events.
Source-net coupons require effective `source_cash_coupons.authority`; an active
linked PDF cannot revive a retired Money proof. Legacy typed payouts require
active, scope-compatible latest `AppliedStatementEventRevision` readback.
Manual rows retain `manual_booked` even when independently corroborated.

Historical denomination/type needs frozen native SOURCE-receipt identity with
matching original source digest, current accepted bindings and dispositions,
or Money's explicit effective exact-RUB-bond acceptance. Today's instrument
catalogue and RUB payment currency alone cannot supply historical denomination.
Prior valid identity supports exited holdings; source revocation/remapping loses
that authority. Unsupported rows remain visible with reasons and are excluded.
Unlinked PDFs and XML dividend summaries are not semantic event sources.

Amounts are exact two-decimal RUB strings backed by integer kopecks. `booked_net`
is the observed ICF fact; `included_in_known_net` identifies rows admitted to the
provable coupon/dividend subtotals. Missing qualifying observations yield NULL,
not zero. An evidenced zero row can yield `0.00`. Net is never reduced by tax or
fees a second time. PDF `tax_available=false` yields tax NULL despite legacy
technical storage zero. Non-RUB rows have all RUB amount fields NULL.

`coverage` and `completeness` are always `unknown`: there is no whole-interval
proof in this slice. No observed rows does not mean no actual income. Redemption
principal, paid NKD, funding, prices and forecasts are excluded. No total-return
RUB/%, valuation inference or AI export is produced.

One existing `coherent_read_operation` pins the query-only committed SQLite
snapshot for facts, proofs, absence sets, mappings and retained revision journals.
No DML, provider, acceptance, Apply, Close or reopen is performed. The deterministic
dependency fingerprint binds retained journals, including retirement/correction/
disposition history, so supported source A→B→A cannot restore an old token.

The existing canonical ledger has a bounded limitation: generic gross-component
ICFs have no standalone revision journal. Only source-owned same-month scopes
have the existing monotonic Money dependency journal. Without such a journal or
effective Money ownership, a manual/custom row or typed payout remains an honest
unavailable proof: the booked fact is visible, the subtotal excludes it, and the
full-response `dependency_fingerprint` is NULL. The API never invents a reusable
ABA token from unchanged legacy values. This adds no writer or persistence schema.
The UI clears results on selector/context changes and each explicit read has a
new request generation; it hides values during refresh/errors and rejects a
different response scope. NULL fingerprint is explained in provenance details.

Focused verification lives in `test_instrument_cash_income_service.py`,
`InstrumentCashIncome.test.tsx`, and the disposable real-backend desktop journey:
`npm run build` then
`npm run test:e2e -- --project=instrument-income`.
All test source documents, accounts and screenshots are synthetic. This evidence
does not replace separately authorized Owner UAT.

<a id="c5-instrument_trades-1"></a>
### Instrument executions and effective cash legs

Bounded read-only [#862](https://github.com/LTstripes/hermes-finance/issues/862)
slice, based on canonical main `8faa8fb9940dc03a13b674ec6e5100389d103d99` after
[#860 exact post-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/39020641994)
completed successfully.

`GET /api/instruments/{instrument_id}/known-trades?account_id=…&t0=YYYY-MM-DD&t1=YYYY-MM-DD`
reads one brokerage/IIS account, one historical instrument and explicit `(t0,t1]`.
It uses one query-only committed snapshot for source union, canonical executions,
revisions, mappings, receipts, Money ownership and currentness. Invalid interval
is 422, missing references 404, other HTTP methods 405. There is no writer/schema,
provider request, Apply/Close, cash-flow creation or new ledger.

Canonical `ExecutedTrade.source_identity` owns event identity. The existing
`executed_trades._context` / `_read` revalidate the accepted revision against native
sources/dispositions/corrections. Ordered native IDs remain separate. Overlapping
originals and repeated occurrences corroborate one canonical trade; distinct ID
pairs remain separate even with equal dates and amounts. Only exact account and
instrument rows enter the response. Inactive/exited instruments remain selectable.

`observed_native_execution` is distinct from `effective_cash_leg_authority`.
The former exposes signed Decimal quantity, BUY/SELL from native quantity sign,
native IDs, revision, lifecycle, separately observed execution/settlement/depository
dates, source occurrences and conflict reasons. It confers no cash authority.
Conflicted observations remain labelled unavailable currentness. Missing date/side
has NULL and a reason; a pending planned date is explicitly separate from actual.
Selection uses the union of execution, actual/planned settlement and source cash
dates, retaining boundary crossings and not treating a date outside `(t0,t1]` as
part of that date's interval. Frozen and current candidate settlement dates both
retain an unresolved crossing for review.

Accepted cash uses only existing `broker_trade_money.effective_proof` and its
Money ownership/retirement/currentness guards plus the current canonical revision.
Stock BUY supports settlement and nonzero separately reviewed commission; bond
BUY supports settlement, paid NKD and commission from the existing three-leg
independently reviewed basis. Each role has signed exact RUB and kopeck strings,
effective date/interval placement, basis, Money receipt and source occurrence
identifiers. Unsupported/ineffective/missing proof gives NULL values and explicit
reasons; no raw Money date/amount matching, SELL proceeds, inferred zero NKD/fee/tax,
cost allocation or accepted cash total is introduced. No financial amount is
summed across roles or combined with payouts/EOD values.

Historical RUB identity reuses accepted native SOURCE identity and exact mappings,
including prior observations of an exited holding. A SOURCE receipt from a later
reporting interval cannot establish an earlier execution's identity. A genuinely
effective, exact native/source-bound Money stock/bond BUY proof can supply its
existing narrow exact-RUB type link, including a prior-month execution with later
cash settlement; without that proof the identity remains NULL.

`known_count` is the canonical count within this bounded response, never full
history. A 250-event cap returns `capacity_exceeded`, no list and NULL count,
without silent truncation. Source gaps, unsupported/unparsed sections and
unaccepted native executions remain explicit markers. Empty inventory does not
prove absence of trades. `trade_history_completeness` and `financial_coverage`
are always `unknown`; endpoint quantities, flat EOD values and payout observations
do not change that.

`dependency_digest` describes only the current snapshot: exact scope, scoped
retained sources, account receipts, executions/revisions/occurrences, Money owners,
correction/disposition history and retained absence reasons. It contains no source
text in API/UI/logs and is **not** a reusable currentness token. Existing journals
do not completely protect the S2-only inventory/absence set against every ABA;
therefore `dependency_fingerprint=NULL` and token `currentness=unavailable` always.
Individual current source/proof checks still occur on each GET. No synthetic token
substitutes for the missing journal and no new journal writer is added.

The on-demand Capital → Performance instrument selector reads this independent
section beside #858 payouts / #860 EOD. They may have separate response snapshots;
no joined rate or result is computed. New request generations, exact outer/event
scope validation, selector invalidation and hidden results during errors/refresh
prevent a late account/instrument/date response appearing as current selection.

Focused evidence belongs to `test_instrument_trades_service.py`,
`InstrumentTrades.test.tsx` and the existing payout/EOD regressions. Disposable
source-backed desktop journey, production dist at 1440 and 1280 with 125% zoom:

```text
npm run build
npm run test:e2e -- --project=instrument-trades
```

The fixtures/DB/screenshots are synthetic. They do not replace Owner-real UAT.
Full instrument P&L/RUB/%/XIRR/TWRR, #814 settlement/NKD evidence, #774 S3,
#839 WHAT-IF, #856 export, Owner DB and Stable remain outside this slice.

<a id="c6"></a>
## 6. H0/H1/H2, membership, valuation and coverage

H0 inventory is not financial authority. H1 opening/closing endpoints cannot replace dated H2 boundary crossings or affirmative complete cash history. Preserve every frozen H2-A1 v1–v3 and H2-A2 v1–v4 evidence/signature/read/replay contract, target compatibility and independent reaffirmation. A2 v3 is coupon-only; only v4 can consume narrowly proved non-Owner paid NKD from role=trade. No reparse, ABA, Reopen, Money reaffirmation or replay silently restores retired coverage.

Accepted finite membership preparation and authoritative PRE/POST capture are delivered capabilities. Their existence does not make every class, instrument, period or source ready. Historical C1 cannot come from today's instrument class. The full component, no-crossing, endpoint and PERF-H1 contracts follow.

<a id="c6-historical_reconstruction_h0-1"></a>
### H0 inventory and seam discovery

Authority: [#720](https://github.com/LTstripes/hermes-finance/issues/720), the
[#709 plan](https://github.com/LTstripes/hermes-finance/issues/709#issuecomment-6025043634)
and its [Integrator acceptance](https://github.com/LTstripes/hermes-finance/issues/709#issuecomment-6025126898).
Consumes accepted [S1](#c3-mybroker_s1-1) and [S2-A](#c5-mybroker_s2_a-12) identities and readers.

`POST /api/historical-reconstruction/preview` takes only a selection:

```json
{
  "account_ids": [1, 2],
  "requested_from": "2030-01-01",
  "requested_to": "2030-03-31"
}
```

Dates and accounts above are synthetic. Select every account relevant to the
intended scope, including non-MyBroker accounts. This API reports the explicit
selection; it does not infer a portfolio universe from current inclusion flags.
Missing source or historical membership for a selected account remains visible.
Selections allow up to 100 distinct existing Hermes accounts and 36,600 days.

The response exposes structural evidence only:

- Confirmed source report ranges, their inclusive gaps/overlaps inside the
  request, and dated observed event ranges. Confirmed quiet ranges do not prove
  economic completeness. Earliest source event and earliest active accepted
  canonical execution are separate, across all accepted history for the selected
  account. `earliest_accepted_canonical_execution` includes active accepted pending
  and settled identities; lifecycle and current conflicts remain separately visible.
- Beginning and ending observations are evaluated independently. Beginning uses
  the actual previous-day EOD, including leap-day; ending uses report-end EOD.
  Both boundaries of an intersecting report remain visible even outside the
  request. The monthly matrix joins only exact dates, never interior or nearest
  month-ends. Source component observations remain distinct from complete
  endpoint acceptance. An observed RUB zero is a cash observation only.
- Side-specific missing quantities/values/cash, common source integrity and
  mapping blockers, opaque Transfers/UFSR/unknown sections, repo/incomplete IDs,
  negative states and pending/forward/cash/custody exposure. Opening settled
  inventory is unproven even when ending actual and forward quantities agree.
  Actual S1/S2-A cash-leg dates, including later commissions and money-only
  source enrichment, independently constrain the cutoff. Current source candidates
  may strengthen blocking but cannot clear frozen canonical cash/pending exposure
  until explicit S2-A enrichment. Planned dates never clear a pending cut.
- Historical membership intervals, gaps/overlaps and cutoff inclusion, without
  using today's account inclusion or instrument class as historical evidence.
- Existing month-owned fact categories for the account, month status and exact
  snapshot date, including CLOSED and DRAFT facts. No March boundary is hard-coded.
  Overlap is reported for review; source values are not compared or reconciled.
- Informational S2-A `create/enrich/noop` candidate operations and blockers,
  using the existing source digest; identity-less observations remain unpromotable.
  These operations are not executed by H0. H0 has no Apply route.

`preview_digest` identifies the selection and committed source/mapping/canonical,
membership, month, target and dependent evidence state. Every call rereads one
query-only SQLite snapshot, including when a Session is reused. This digest is
an inventory review identity, not an Apply confirmation or an acceptance token.

Event-history observation, exact source endpoint acceptance, monthly
materialization, account/portfolio XIRR, class no-crossing/crossing XIRR and exact
TWRR availability are separate fields. H0 does not call solvers or reinterpret
existing Hermes return availability. Complete source endpoints/materialization
require the separate H1 contract; return consumers remain unevaluated here.
Opaque section event dates cannot be recovered from S1's retained structural flags.
Quiet/empty reports, missing securities or missing cash never establish zero
capital, inception or complete financial coverage.

No migration, persistence, financial mutation, coverage promotion, provider
request, backfill, price/class/cost/P&L inference or month close/reopen occurs.
The output excludes native source identifiers, holdings, amounts, filenames,
raw XML and arbitrary source text. Hermes IDs, source identity digests, dates
and structural flags support Owner-local review. Do not publish Owner-local
reports or responses as agent/GitHub artifacts; synthetic tests supply evidence.
Independent candidate review, Integrator acceptance and applicable Owner UAT
remain separate from CI and from this read-only Preview.

<a id="c6-historical_endpoints_h1_a-1"></a>
### Exact source H1 endpoints

Authority: [#723](https://github.com/LTstripes/hermes-finance/issues/723),
[accepted contract](https://github.com/LTstripes/hermes-finance/issues/721#issuecomment-6025311447)
and [frozen amendments](https://github.com/LTstripes/hermes-finance/issues/721#issuecomment-6025408148).
S1 and S2 retain their existing [source](#c3-mybroker_s1-1) and
[execution](#c5-mybroker_s2_a-12) meanings.

One accepted `mybroker-s1-v2` document supports one mapped account at its exact
`covered_to` EOD: RUB stocks and one separate complete RUB cash row. Each source
row is referenced by import, section, ordinal and fingerprint. Quantities and
source total values retain their canonical decimal strings. RUB money must be
exactly representable in signed 64-bit integer kopecks; fractional kopecks and
overflow block acceptance. No price, cost, P&L, NKD or FX is derived.

Migration `0050_historical_endpoints` adds two empty tables without backfill:
`historical_endpoint_revisions` and `historical_endpoint_applies`. Revisions and
receipts are append-only, with SQL triggers protecting migrated databases;
populated downgrade refuses loss. Supported whole-file backup/recovery preserves
both. The endpoint key is account + exact date + EOD + RUB; provider and source
side are provenance, never additional economic identities.


<a id="c6-historical_endpoints_h1_a-1-api"></a>
#### API

1. `POST /api/historical-endpoints/preview` with operation `accept`, account ID,
   exact valuation date, accepted source import ID and `source_side=ending`.
   With missing claims it returns observations, sorted blockers and the backend
   source-set fingerprint for the explicit review.
2. Supply typed `owner_attestation` claims bound to account, date, ending side,
   complete source-set fingerprint and every position-row fingerprint.
   Required assertions are `inventory_complete`, `other_components_absent`,
   `rub_cash_complete_and_reconciled`, and `rub_stock_basis_confirmed`.
   The reference is a bounded label using letters, digits, underscore or hyphen;
   it is not a filename, path or free-form narrative. Defaults remain unconfirmed.
3. Apply the same intent with the reviewed `confirmation_digest` and a unique
   `request_id` to `POST /api/historical-endpoints/apply`. Existing targets require
   the exact `expected_revision`. No browser financial amounts or C1 fields are
   accepted. Apply obtains the writer reservation before rereading authoritative
   context and holds it until commit/rollback.
4. Independently `GET /api/historical-endpoints/{endpoint_key}`. Apply also returns
   readback from a new coherent DB session, plus the committed receipt revision.
   GET rederives the components from immutable S1 and compares the frozen envelope;
   only effective accepted evidence exposes `total_value_kopecks`.

Fresh identical requests write receipts without additional endpoint revisions.
Exact receipt replay returns the original committed revision identity plus current
readback, including later retirement/invalidation. Key reuse with different intent
or confirmation conflicts. Restoring authority requires reviewed `reaffirm`;
different economic quantity/value/cash remains reconciliation-required. Explicit
`revoke` targets the existing revision with `owner_withdrawal` or
`evidence_disputed`, without new source/claims.


<a id="c6-historical_endpoints_h1_a-1-evidence-and-lifecycle"></a>
#### Evidence and lifecycle

Claims cannot override duplicates, missing/ambiguous cash, opaque source sections,
pending/forward exposure, canonical disputed settlement or incompatible recorded
components. Historical membership must be unambiguous; explicit exclusion stays
excluded. Stock admissibility is endpoint-only Owner evidence. It establishes no
C1 or class/return coverage; `endpoint_c1` remains null. Generic interval fee/cash
limitations remain separate from endpoint blockers.
Trade conflicts block only identities observed at/before the EOD cutoff; every
occurrence is checked so a disputed timestamp cannot hide earlier exposure.
Strictly later trade conflicts and generic Money remain return limitations.
Later source-linked settlement/commission cash for a pre-cutoff execution still
blocks, including cash legs supplied by a separate accepted report.

Overlap compares exact snapshot dates, full instrument/quantity/value composition,
owned RUB cash and additional components, including DRAFT/CLOSED material and
archived provenance. Matching totals cannot conceal offsetting differences.
Identical overlap corroborates and never adds another amount. Unknown archive/date
or ownership relationships fail closed.
An archive's reporting label and quote date do not prove its original snapshot
date. Potentially relevant unresolved archival dates block acceptance. Earlier
source actual/forward disagreements remain unresolved across later cutoffs; a
later clean report alone cannot settle position-level exposure.

`retire` is dependency lifecycle loss of authority; `revoke` is a reviewed Owner
action. Frozen mapping/instrument identity, membership, canonical execution revision and month-owned
overlap changes append retirement transactionally with sanctioned writers.
Component-set additions/removals also retire the frozen account/month dependency;
removing a newly added conflicting component cannot silently revive acceptance.
Reopen/date-change/delete uses exact frozen month dependencies; an independent
endpoint inside a month's calendar dates is not retired merely by those dates.
Ordinary Close changes no acceptance. Dependency correction requires applicable
CLOSED periods to be reopened; contradictory newly accepted evidence can immediately
invalidate reads without rewriting CLOSED history. Restoring amounts or reclosing
does not reactivate retired authority.

No ReportingMonth, PositionSnapshot, CashBalance, DepositSnapshot, flow, coverage
or return-consumer writes are produced by H1 Apply. Beginning Apply, mixed assets,
multiple account/report assembly, conflicting replacement and historical monthly
materialization remain separate slices. Independent financial/data review,
exact-candidate CI and applicable Owner-local UAT remain separate gates.

<a id="c6-historical_portfolio_flows_h2_b1-1"></a>
### H2 whole-portfolio owner boundary

Implementation reference for [#731](https://github.com/LTstripes/hermes-finance/issues/731),
under the [accepted #729 contract](https://github.com/LTstripes/hermes-finance/issues/729#issuecomment-6039216401).
This backend bridge binds one existing H2-A1 flow per Apply. It creates no cash
facts, source occurrence owners, ReportingMonths or performance consumer inputs.


<a id="c6-historical_portfolio_flows_h2_b1-1-review-and-apply"></a>
#### Review and apply

- `POST /api/historical-portfolio-flows/preview` accepts a `PortfolioFlowIntent`.
- `POST /api/historical-portfolio-flows/apply` adds `request_id` and `confirmation_digest`.
- `GET /api/historical-portfolio-flows/{flow_id}` independently returns current authority.

An intent specifies `flow_id`, `expected_flow_revision` and
`expected_portfolio_revision` (zero means no portfolio acceptance). Operations
are `accept`, `reaffirm` and `revoke`. No financial amount, source replacement,
membership write or transfer reconciliation is accepted in a request.

Preview without claims discloses the immutable core and server-discovered
catalogue, dated memberships, source/mapping material, source-flow revisions and
permanent occurrence ownership, relevant legacy legs with full counterparts,
reconciliation and coverage inventory. It remains blocked. Nothing is inferred
from current account flags, absence of a counterpart, dates or amounts.

Review all catalogue candidates, including hidden/closed accounts and other
providers. Supply `roster` with the exact date, catalogue ID set and one typed
entry per candidate. `tracked` entries form the dated tracked universe; each
requires exactly one inclusive effective membership row. Other dispositions
(`not_yet_opened`, `no_longer_tracked`, `not_investment_account`) need explicit
historical confirmation and a bounded opaque reference. A relevant accepted
source or affirmative inclusion contradicts an asserted irrelevant disposition.
All roster and outside-counterparty booleans default to unconfirmed.

Preview the chosen roster entries to obtain `review_context_digest`, then bind
both attestations to that digest. Roster completeness confirms no relevant
unregistered/omitted historical tracked account. `outside` additionally binds
the exact flow and accepted revision ID, source-set fingerprint, core and owned
occurrences through the review digest. It confirms identifiable original
movement/counterparty, outside the entire tracked universe, non-transfer routing
and the exact actual Owner boundary amount with no inseparable fee/tax/gross-net
component. Only opaque reference labels are accepted, without native counterparty
IDs, statements, paths or replacement financial values.

Run Preview with the complete attestations and use its confirmation digest for
Apply. Apply reserves the SQLite writer before rereading all evidence and
checking both expected revisions and the digest. Acceptance and its receipt
commit atomically. A fresh identical intent adds a receipt but no revision or
economic event. Reusing a request ID for a different intent/digest conflicts.
Receipt replay returns the original committed revision identity and a fresh
current readback, including retirement/revocation.


<a id="c6-historical_portfolio_flows_h2_b1-1-authority-and-loss-of-evidence"></a>
#### Authority and loss of evidence

GET separates `account_scope` / `account_effective_state` from `portfolio_scope`
and portfolio acceptance/effectiveness. A portfolio amount is supplied only for
an effective EXTERNAL contribution/withdrawal using the unchanged exact H2-A1
core. Explicit unique historical exclusion reports `not_in_scope`; missing or
ambiguous membership stays `unknown`. `cash_coverage` always remains `unknown`.

Generic dated unsupported Money requires its existing effective row-specific
H2-A1 semantics. Potentially relevant opaque Transfers/UFSR and unresolved
source/mapping identities block promotion. Legacy link status cannot supply an
H2 source bridge: one-legged/unresolved relationships and relevant resolved
transfers remain blocked, with full explicitly linked legs and reconciliation
disclosed even outside the event date/report range. Demonstrably unrelated
source ranges and completed transfer spans are excluded from current evidence.
No pairing, netting, transfer residual, fee allocation or transit valuation is
performed.

Portfolio revisions and receipts are append-only. ORM dependency hooks retire
acceptances transactionally across the whole disclosed catalogue, including
another account's membership and H2-A1 retirement/revoke. GET reconstructs
current support without writes. Migration `0053_historical_portfolio_flows` also
installs an append-only structural SQL change journal (table/row keys and date
intervals only). Digest-bound relevant journal IDs prevent SQL bypass A→B→A
from reviving an old acceptance. No-op writer reservations add no change events.
Existing account authority is preserved unless its own H2-A1 lifecycle retires it.

Reviewed `reaffirm` can restore the same core with fresh dependencies/claims;
portfolio `revoke` works even with broken positive support. Revoke never removes
valid account evidence. Independent acceptance needs no ReportingMonth and
calendar overlap with CLOSED does not prohibit it. Existing protected dependency
corrections retain their explicit Reopen guards; close/reclose never restores
portfolio authority.


<a id="c6-historical_portfolio_flows_h2_b1-1-synthetic-evidence"></a>
#### Synthetic evidence

`backend/tests/test_statement_import_historical_portfolio_flows.py` covers
positive/negative exact cash, full/subset/disposed rosters, missing/overlapping
memberships, inclusion/exclusion and unsupported account types, every affirmative
claim, row/revision binding, other-account opaque/unsupported sources, explicit
legacy counterparts/transit/differences, dependency retirement and SQL bypass,
stale/concurrent Apply, rollback, replay/noop/revoke/reaffirm, strict HTTP requests,
empty-schema migration and append-only/loss guards, backup/restore, independent
CLOSED overlap and unchanged coverage. Fixtures contain fabricated data only.

Source-aware CashBoundaryCoverage is an independent compatible gate. Its projection
and revisions do not confer or retire portfolio authority; H2-B1 cash_coverage
remains UNKNOWN. Source-free COMPLETE coverage remains a blocking dependency.


<a id="c6-h2-base"></a>
### H2-A1: accepted account-boundary Owner cash events

H2-A1 separates immutable source occurrence, stable economic `flow_id`, revision/effectiveness and request receipt. It stores one attested historical account-boundary cash event, not a ReportingMonth, ExternalFlow, CashBalance, position or payout. Accepted event does not establish complete history: coverage remains unknown until separately accepted H2-A2. Native operation text/sign alone never classifies Owner cash.

An admissible seed is one accepted frozen S1 v2 Money occurrence: `import_id > 0`, `section=money`, `ordinal >= 0`, kind unsupported and no settlement/commission linkage, on one explicitly mapped brokerage account. Filename and row-account aliases must both bind that exact account; freeze mapping IDs/targets/lifecycle. The immutable source supplies its cash-group posted date within confirmed range, exact RUB, finite nonzero signed Decimal and exactly integral kopecks within signed int64. No client replacement, rounding, float, FX, date inferred from upload/last_update/report end or pending settlement. Positive source credit means contribution, negative debit withdrawal; store positive magnitude while preserving source sign and reject contradictory direction.

`OwnerCashClaims` has ten affirmative claims, all default false:

| Exact claim | Required meaning |
|---|---|
| `original_row_identifiable` | Owner can identify the exact original row privately. |
| `posted_cash_date_confirmed` | Source cash-group date is the actual posted cash date. |
| `signed_cash_convention_confirmed` | Source sign/direction convention is independently confirmed. |
| `owner_capital_crossing` | This is Owner capital crossing the selected account boundary. |
| `not_income_tax_promotion_or_internal_cash` | It is not coupon/dividend/redemption income, tax, promotion/bonus or other internal cash. |
| `not_settlement_or_commission` | It is not an execution settlement or commission leg. |
| `cash_not_in_kind` | It is cash, not a noncash movement. |
| `not_tracked_account_transfer` | No known/suspected tracked-account transfer is being disguised as capital. |
| `counterparty_outside_account_boundary` | The counterparty is outside this account boundary. |
| `complete_occurrence_set_is_one_event` | The entire disclosed corroborating occurrence set is one economic event. |

Claims bind the exact facts, occurrences, mappings, dated scope and review context. The envelope uses `provenance_kind=owner_attested_source_row`, a bounded non-narrative reference, `source_set_fingerprint`, `review_context_digest` and direction `contribution|withdrawal`. Missing claims permit inspection, not acceptance. Claims never override linked/incomplete/ambiguous trades, pending-only evidence, opaque Transfers/UFSR or source integrity/conflict blockers. An unidentifiable row stays unsupported.

The server discovers the complete relevant source union, full ranges and conflict/legacy/coverage context; caller-selected supportive rows cannot narrow it. Account/date/signed amount/currency is a comparison signature, never a unique economic key. Hash, timestamp, ordinal and upload order are not cross-report IDs. One occurrence permanently belongs to one economic owner, including after revoke. Same occurrence retry adds no money. Across reports exact core equality is necessary but insufficient: bounded corroboration permits at most one matching candidate per report plus explicit entire-set same-event attestation. Indistinguishable repeated rows within one report, distinct equal movements, competing ownership and ambiguous equivalence block; never choose first, collapse or sum them. New relevant reports require fresh source-set review; disputed/disappearing evidence is reconciliation, not cancellation or a compensating opposite flow.

Operations are `accept`, same-core `corroborate`, `reaffirm`, and `revoke`; dependency loss appends retirement. Changed date/amount/direction/account core replacement is outside the bounded correction contract even under a fresh ID. Revoke names exact target/revision and bounded `attestation_withdrawn|evidence_disputed`, requires neither positive claims nor a valid source selection, and remains possible when support is broken. Immutable occurrence ownership remains. New support, mapping/membership loss or source dispute removes effective authority transactionally; coherent GET independently fails closed without repair. ABA, old replay and reclose cannot revive it: explicit reviewed same-core reaffirmation is required.

Account truth comes first. Authoritative `account_scope` never becomes portfolio externality merely because the event is external to one brokerage account. `portfolio_scope` stays unknown unless frozen reviewed evidence binds the dated complete tracked-investment universe/membership and proves the counterparty lies outside it, without transfer ambiguity. Current include flags or amount/date matching cannot supply this. Resolved transfers between historically included accounts remain portfolio-internal; unresolved identity, difference/fee/transit and in-kind/currency cases retain their own gates. H2-B1 separately owns whole-portfolio proof.

An independent source event needs no ReportingMonth and is not prohibited merely by calendar overlap with a CLOSED month. It does not change CLOSED financial facts, membership or coverage. Actual protected dependency corrections require the applicable explicit Reopen; fail-closed dependency retirement may remove authority without rewriting CLOSED facts. No automatic reopen/reclose or legacy monthly materialization.

The implemented routes are `POST /api/historical-owner-flows/preview`, `POST /api/historical-owner-flows/apply`, and `GET /api/historical-owner-flows/{flow_id}`. Preview is read-only and returns complete source/legacy/dependency evidence, observations, blockers, fingerprints and confirmation digest. Existing-target operations name `flow_id + expected_revision`. Apply uses the same reviewed intent/digest and unique request ID, reserves SQLite before authoritative reread of all dependencies/ownership/revisions/CLOSED state, and commits revision/ownership/receipt atomically; failure rolls them all back. No client economic replacements/month fields are accepted. Same key/different intent conflicts. Exact replay preserves the original committed revision plus current readback, including later retirement/revoke; fresh identical effective intent creates no extra event/amount/revision. Apply returns post-commit readback; independent GET must confirm before success.

Frozen `h2-a1-owner-rub-v1` remains the default original evidence contract. Explicit `h2-a1-owner-rub-v2` supplies the reviewed directed dependency compatibility needed by A2; v3 adds the later section-aware support described below. Preserve literal old evidence/signatures/receipts and use reviewed same-core cross-version reaffirmation, never grandfathering or silently rehashing. Source-aware coverage alone cannot retire/revive its own compatible underlying event. Legacy COMPLETE/flow/transfer conflicts remain independently binding.

### H2-A2: source-aware account cash-boundary coverage

H2-A2 reuses one existing `CashBoundaryCoverage` ID and unique `(account_id, covered_from, covered_to)` plus append-only source-bound revisions/receipts. It stores no amount and owns no source occurrence. For EOD `a < b`, consume exactly `a < event_date <= b`, persisting inclusive day coverage `[a+1 day,b]`; a one-day interval is valid. Opening-day cash is already in opening EOD, closing-day cash is included. Membership context also covers both EOD boundaries `[a,b]`.

`SourceCashClaims` has four affirmative claims, all default false: `all_report_channels_disclosed`, `full_interval_no_omitted_crossing`, `every_owner_crossing_enumerated`, `source_and_legacy_conflicts_resolved`. They bind a bounded reference and `review_context_digest`: every relevant alias/report channel is disclosed; the exact day interval has no known omitted crossing; every crossing is enumerated by effective accepted events; and source/legacy conflicts are resolved within the supported slice. An empty effective event set additionally requires explicit `zero_owner_cash_crossings=true` against an empty unresolved-candidate set. Quiet reports, no blocking rows, endpoint agreement and an interval checkbox alone never prove zero or completeness; claims cannot waive machine gaps/blockers.

The server-discovered deterministic versioned envelope binds all of the following, including relevant absence sets:

- Every accepted relevant report, including quiet/overlapping sources, original/current mapped aliases, provider/parser/hash/normalized fingerprints and mapping lifecycle. Disclose full confirmed ranges, clipped contributions, exact disjoint range union and each gap; a min/max hull cannot fill missing days. Wider support needed for an in-window flow remains bound in full. Remap/withdrawal cannot hide formerly relevant support.
- Every account/window flow, including ineffective/revoked/retired history: flow ID, current revision/acceptance/effectiveness/material signature, immutable core and every permanently owned import/Money/ordinal/fingerprint. Count effective economic flow once; corroboration adds provenance only. A revoked unresolved crossing still prevents COMPLETE.
- Every relevant Money occurrence, not merely Owner rows. Each must have effective reviewed H2-A1 ownership or the supported exact unambiguous non-Owner linkage/disposition for that frozen version. Preserve multiplicity, trade identity/lifecycle and all incomplete/pending/missing-link blockers. V1's clean slice does not classify unsupported payout/tax/promo by text/sign. Later v3/v4 exceptions below are narrow versioned additions.
- Opaque/unparsed/unknown/Transfers/UFSR inventories and justified account/date exposure, transfer legs/links/reconciliation/transit, in-kind and currency facts. Opaque evidence lacking finer scope potentially affects its full report range. No blanket Owner dismissal, guessed net-zero, FX or rounding; endpoint blockers remain independent unless inventory/scope is uninterpretable.
- Exact account identity/type and effective-dated membership rows/IDs/ranges/flags across both endpoints and day interval. First positive source-aware slice requires continuous unambiguous inclusion. Gaps/overlaps/exclusion stay nonauthoritative for that positive claim; today's flags cannot repair history. Relevant counterparty/alias evidence exposes transfers without imposing unrelated whole-portfolio membership as an account gate.
- All relevant legacy ExternalFlow/deposit/withdrawal/direct-payout representations, linked transfer legs outside the window, legacy/competing COMPLETE and overlapping UNKNOWN assertions. Equality is only a clue. The bounded clean slice refuses unresolved legacy crossing/COMPLETE competition; do not ignore overlapping UNKNOWN coverage, synthesize a bridge or duplicate an exact existing key.

Source-aware `owner_attested_source_cash_history` is distinct from legacy/source-free `owner_attestation`. A provenance label/notes/digest alone cannot forge COMPLETE or authorize an assessor that reads only another ledger. Accepted source cash coverage is separate from in-kind/valuation/inception/portfolio authority and numerical returns.

Dependency direction is source facts/semantic ownership → effective A1 flow revision → A2 coverage revision. A2 must not use its own COMPLETE projection to establish A1 effectiveness, accept/reaffirm/revive A1 during coverage Apply, or blanket-exempt all legacy coverage from A1 invalidation. Old incompatible A1 envelopes remain frozen; explicit reviewed same-core compatible reaffirmation precedes coverage. A2 v1 is `h2-a2-source-cash-rub-v1`; its v2–v4 frozen section/coupon/paid-NKD amendments follow below.

Identity is immutable. Operations are accept, reviewed same-identity reaffirm, revoke and automatic dependency retirement. An account/date-window change requires withdrawing the old assertion and separately accepting the new exact key with both affected intervals checked; no changed-key PATCH, split or audit deletion. New relevant sources, changed flow/owner/support/mapping/membership/legacy/transfer/in-kind/currency/competing coverage retire the affected assertion to UNKNOWN in the same transaction; unrelated scopes do not. ABA, replay, reclose or independent Money/A1 reaffirmation cannot restore A2; separate fresh reviewed A2 reaffirmation is required.

Positive edits and explicit revoke intersecting CLOSED reporting periods require explicit Reopen. Dependency-loss retirement may project UNKNOWN even in CLOSED, without rewriting its facts; GET rechecks currentness without repair writes. Revocation needs exact target/revision/reason and current conflict binding, not valid positive support. No ReportingMonth creation or automatic reopen/reclose.

Implemented routes: `POST /api/cash-boundary-coverages/preview`, `POST /api/cash-boundary-coverages/apply`, `GET /api/cash-boundary-coverages/{coverage_id}`. Intent names account and exact `opening_date < closing_date`; existing target requires `coverage_id + expected_revision` together, reaffirm requires that target, revoke only target/revision/bounded reason. Preview returns full union/gaps/occurrence dispositions/membership/legacy/blockers and review/confirmation digests. Apply uses the exact reviewed intent/digests/request ID, reserves the writer before full authoritative reread and atomically commits projection/revision/receipt. Stale/conflicting/failed work rolls back all three. Legacy create/PATCH cannot forge source provenance or promote bound evidence. Same-key different intent/digest conflicts; exact receipt replay reports original committed revision plus current effectiveness/UNKNOWN, and fresh identical effective intent adds no revision. Independently GET after Apply; a failed GET is GET-only recovery.

Provenance: accepted [H2-A1 #725](https://github.com/LTstripes/hermes-finance/issues/725#issuecomment-6032376369), mandatory [account-first amendment](https://github.com/LTstripes/hermes-finance/issues/725#issuecomment-6033577843), accepted [H2-A2 #728](https://github.com/LTstripes/hermes-finance/issues/728#issuecomment-6039160610) and [acceptance](https://github.com/LTstripes/hermes-finance/issues/728#issuecomment-6041619786). Their historical pre-implementation statuses are not current restrictions; the literal accepted evidence versions and their boundaries remain authoritative.

<a id="c6-broker_statement_return-23"></a>
### Frozen H2-A1/A2 evidence versions and retirement

#815 diagnostic CODE GO [6166582304](https://github.com/LTstripes/hermes-finance/issues/815#issuecomment-6166582304)
adds immutable `section_authority` entries for the selected and intersecting
account sources, separately for Transfers and UFSR. Each entry binds import,
account and reporting month; reports `effective|missing|blocked`, current head
request ID and proof material signature when a head exists. A safe `pattern` is
disclosed only after the existing #800 chain and current dependency resolver
validate the exact proof. Raw inventory and safe original XML alone leave the
grant missing; stale, malformed or conflicting authority remains blocked without
falling back to an older receipt. Superseded history does not override a valid
fresh head. Head IDs, proof material, blocked/conflicting histories and relevant
source changes participate in the S3 fingerprint even while reasons and rate
remain unchanged. GET, original Preview and JSON attachment export share this DTO.

These are three separate evidence layers: original-safe XML structure, accepted
source-scoped metadata grant, and independently accepted economic-period coverage.
Section entries always retain `period_scope=unknown`. They do not assess material
exposure, dated crossings or continuous historical performance membership.
`cash_coverage_state` remains owned by the H2-A2 reader. The #816
[accepted compatibility contract](https://github.com/LTstripes/hermes-finance/issues/816#issuecomment-6168054932)
introduces `h2-a2-source-cash-rub-v2`: each intersecting source records raw and
effective syntax blockers, absent/current section heads, full scoped receipt
chains and current base/grammar/mapping/dependency bindings before blocker union.
Only current exact-month #800 authority removes its own named Transfers/UFSR
exception. It adds no coverage dates; H2-A1 v1/v2 retain their frozen raw-S1 blockers.
An independently complete quiet interval still needs continuous membership,
resolved Money/exposure, all four reviewed claims and explicit zero crossings.
Section-aware v2 accepts and explicitly reviewed same-identity reaffirmations bind v2 context;
v1 reads/replays retain their original evidence and never inherit section grants.
Relevant source/section/base/dependency changes append retirement and UNKNOWN in
the same transaction, including CLOSED and receipts from later lifecycle hooks.
ABA and replay cannot revive retirement. Coherent GET rechecks without writes;
positive edits/reaffirm/revoke still require explicit Reopen when CLOSED.
`material_account_exposure_unassessed`, overlapping-source and all other retained
null reasons remain in force. Cash compatibility alone grants no numerical return.

The [#819 accepted implementation contract](https://github.com/LTstripes/hermes-finance/issues/819#issuecomment-6170897968)
introduces separate `h2-a1-owner-rub-v3` account crossing evidence. Each source in
the full discovered account/date cohort binds canonical #800 provenance before
blocker union: raw/effective codes, absent/present heads, exact original/month
geometry, full relevant journal and current source/base/mapping/dependency support.
Only its own current Transfers/UFSR authority removes those named codes. Another
unsafe or ambiguous source still blocks; section authority supplies neither an
economic zero nor Owner externality. Exact signed RUB cash, complete occurrence
claims and permanent H2/Money ownership remain required. No month or financial
cash is created by Preview/GET or metadata acceptance.

V1/v2 serialized identities, builders, evidence, signatures and replay retain
their original contracts. Cross-version acceptance requires reviewed same-core
`reaffirm` with expected revision and freshly bound claims. Accepted v3 support
is compared after every sanctioned flush, including receipts from late listeners;
dependency loss appends retirement in the same transaction, then retires dependent
A2 evidence. CLOSED calendar overlap and ordinary Close alone do not retire A1;
dependency-loss retirement does not reopen or change CLOSED financial facts.
ABA, section reacceptance and old request replay cannot restore A1/A2 authority.
Retired v3 needs explicit reviewed A1 reaffirmation, followed by separate A2 review.
Source-aware/noncomplete A2 coverage is excluded from intrinsic v3 dependencies,
preserving the directed S1/section → A1 → A2 relationship and legacy COMPLETE conflicts.

Existing BrokerMoney account_funding creation/reuse/proof and only the A2 v2
account reader accept exact independently effective A1 v2/v3, binding the actual
version/revision/signature. Money's default remains v2; A2 v1 and shared assessor
ledger/portfolio dispatch are unchanged. Money reserves an authority-free typed
envelope during its atomic staging, then seals the final receipt; transient staging
must not look like a malformed #800 journal. Reuse, corroboration and replay add no
second economic amount, CashBalance, ExternalFlow or InvestmentCashFlow. No new
coupon/NKD/trade exemption, portfolio authority or numerical return follows.

The [#820 coupon contract and CODE GO](https://github.com/LTstripes/hermes-finance/issues/820#issuecomment-6172319178)
adds `h2-a2-source-cash-rub-v3`. This remains the frozen coupon-only version.
V1/v2 retain their literal evidence, signatures, readback and replay;
v3 continues to accept independently effective A1 v2/v3 revisions.
Only a current target-specific BrokerMoney proof can classify a permanently
owned exact Money occurrence as `accepted_non_owner_coupon`. V3 binds the full
target occurrence/owner cohort, relevant Money journal, canonical existing ICF,
account/month/instrument/source facts and optional typed PDF event/revision
support. No PDF is invented for net-native payouts; unavailable tax stays null.
The same exhaustive authority partitions only those existing effective coupon
ICF IDs out of legacy overlap. Every other ICF, ExternalFlow, unresolved Money,
NKD, membership, source gap and retained exposure blocker remains effective.
Coupon cash creates no second payout, cash row or Owner/investor external flow.

Receipt, ownership, target and typed PDF changes retire accepted v3 in the
dependency transaction, including CLOSED and late listeners. Presence and
absence participate in review binding. Restoring facts, replaying an old request
or independently reaffirming Money does not revive H2-A2; fresh reviewed coverage
reaffirmation is required. Reads only assess current authority and never repair it.

Under [#849](https://github.com/LTstripes/hermes-finance/issues/849), an otherwise
validated exact source/account/interval with no coverage row also reads the
existing H2-A2 inventory under the current accepted contract, in that
same coherent snapshot. Its stable blockers join `reason_codes`; the full relevant
dependency material and contract version participate in the opaque fingerprint.
Raw diagnostic rows/identifiers are not added to the response or logs. Source,
binding or currentness failures prevent this diagnostic lookup; no guessed scope
is used. GET, original Preview, desktop reasons and JSON export retain parity.
Even a valid inventory with no blockers is not accepted coverage: the generic
`account_crossing_coverage_unproved` and null rate remain. Existing coverage-row
branches retain their established versioned readers and availability. Accepted
paid-NKD has no disposition in v1-v3; the diagnostic itself grants no authority.

The [#870 accepted v4 contract](https://github.com/LTstripes/hermes-finance/issues/870#issuecomment-6237129361)
adds `h2-a2-source-cash-rub-v4` for new accepts and explicit reviewed reaffirmations.
V1/v2/v3 retain their literal evidence, readbacks and receipt replay, including v3
coupon currentness and unresolved paid NKD. V4 preserves A1 v2/v3 compatibility.

`source_cash_trade_money` is a query-only adapter from permanent trade ownership
and the latest target-specific Money receipt to the frozen trade revision and
full current canonical source union. Only a unique exact original Money
occurrence in the reviewed `nkd_leg` may become `accepted_non_owner_paid_nkd`.
The complete three-leg owner/receipt cohort, ordered native ID pair, current
active settled RUB bond BUY revision, account/mapping/month/settlement/custody
support and all independent claims must agree. Exact signed kopecks validate
an already proved includes/excludes basis; arithmetic never selects that basis.
Overlapping originals, duplicate roles/rows, missing owners, stale/retracted
proofs and unknown operations remain unresolved. There is no cross-original
paid-NKD deduplication or new authority from date/amount/ISIN matching.

V4 freezes relevant target/history, journal, source, owner and absence sets in
`paid_nkd_authority`. Trade revision/occurrence and Money dependencies participate
in the full post-flush comparison, including receipts appended by later listeners.
Dependency loss appends retirement in the same transaction even in CLOSED;
rollback restores both dependency and retirement. Close alone changes no proof.
ABA, replay, reopening and independent Money reaffirmation cannot revive A2:
fresh claims, expected revision and separate A2 reaffirmation are required.
GET/Preview/export only read currentness and never repair persisted authority.

Synthetic acceptance uses the original reviewed Money fixture: S -10,000.00,
N -125.50, F -10.00, debit 10,135.50 RUB; opening cash 10,000.00, coupons
+3,000.00 and Owner funding +50,000.00 yield EOD 52,864.50 and zero residual.
Six occurrences partition into two coupons, one Owner funding, two trade cash
legs and one paid-NKD non-Owner occurrence. Economic row counts remain
CashBalance/ICF/HistoricalOwnerFlow/ExternalFlow/ExecutedTrade = 1/2/1/0/1.
The adapter adds zero economic rows or amounts. It grants neither automatic
A2 COMPLETE nor S3 numeric; all independent coverage, membership, endpoint and
exposure gates still apply. Paid NKD is not a coupon, Owner contribution or
bond EOD accrued NKD. Real September source authority (0/5 independently proved
links under #814), actual S3/Close and exact-return/export authority remain BLOCKED.

Routes (all read-only, including POST preview):

- `GET /api/broker-statement-returns/sources?account_id=...` lists accepted source
  receipts for selection. Listing is discovery, not rate authority.
- `GET /api/broker-statement-returns?account_id=...&request_id=...` rebuilds evidence
  in one coherent committed read snapshot.
- `POST /api/broker-statement-returns/preview` accepts original XML plus
  `account_id`/`request_id` form fields. The existing accepted source is required;
  parser facts must match its unchanged original, allowing only established S1
  service enrichment. No client-supplied amount, rate or evidence override.
- `GET /api/broker-statement-returns/export` returns the same DTO as JSON.
  Optional `expected_fingerprint` on GET/export requires the viewed evidence;
  changed evidence returns a fresh unavailable DTO with `statement_preview_stale`.

Desktop route `/v2/capital/statement-return` is linked from the performance page.
Account/source query identities and response identities must agree. Switching
account clears the selected source; pending/failed refresh hides the old result
and export. The export link pins the displayed fingerprint. It cannot export an
old percentage after the source or coverage changes.

<a id="c6-r08-01b-valuation-coverage-8"></a>
### Valuation component matrix

<a id="c6-r08-01b-valuation-coverage-8-authoritative-interpretation"></a>
#### Authoritative interpretation

The accepted #145 v2 contract is normative, including its explicit
`not_computable_*` outcomes. Accepted #179 semantics are preserved:
`ExternalFlow.scope_membership=unknown` is not evidence, and the present
`Account.include_in_returns` flag must not reclassify a historical flow or
historical valuation-point scope.

The valuation service derives a point from one persisted reporting-month
snapshot. It never fills a missing component from another month, a month
label, a provider observation, or a capital delta. A point can expose a
persisted total only when its selected account components are authoritative.


<a id="c6-r08-01b-valuation-coverage-8-discoverysupport-matrix"></a>
#### Discovery/support matrix

| Component | Persisted source and existing meaning | Portfolio scope | Account scope | Support outcome |
| --- | --- | --- | --- | --- |
| Valuation boundary | `reporting_months.snapshot_date` is a non-null `Date`; `status` is `draft` or `closed`. | The date is authoritative only for a closed month and is never reduced to `YYYY-MM`. | Same. | Missing date is handled defensively as unavailable; draft data is not a trusted valuation point. |
| Position value | `position_snapshots.market_value_kopecks`, backend-recomputed per month/account/instrument. | Authoritative for selected `include_in_returns` accounts when rows are present and values are valid. | Authoritative for the explicit in-scope account when rows are present and values are valid. | Missing account component is `unknown`; invalid persisted value is unavailable. The stored value is the existing RUB valuation; no FX is invented from `Instrument.currency`. |
| Deposit value | `deposit_snapshots.balance_kopecks`, account-linked and base-currency-denominated by the existing schema. | Authoritative for selected accounts when rows are present and valid. | Authoritative for the explicit account when rows are present and valid. | Missing account component is `unknown`; values are treated as base currency under #145 v2. |
| Performance cash | `cash_balances.amount_kopecks` and explicit `currency`; baseline has no account identity. | A legacy `NULL account_id` row cannot be assigned to the portfolio without guessing. | A legacy `NULL account_id` row cannot be assigned to an account. | Existing unlinked rows are `not_computable_scope_cash_unclassified`. The additive nullable account linkage introduced by R08-01B is authoritative only when populated; non-RUB rows are unavailable without an accepted conversion. |
| Scope membership evidence | `account_performance_scope_memberships` is effective-dated point-scope evidence; `external_flows.scope_membership` and transfer identity/status come from accepted #179/R08-01A. | Every account must have one unambiguous membership row at the valuation date. | Same for the explicit account. | Missing/overlapping membership is `not_computable_scope_membership_history_missing`; current `include_in_returns` is never used for historical selection. Flow membership remains separate coverage and is never converted to zero. |
| Quote/provenance/freshness | `PositionSnapshot.price_date`/`price_source`, optional immutable `PositionQuoteProvenance`, and read-only R07 freshness service. | Provenance is attached to position components. | Same. | No refresh/network call. Existing persisted valuation remains the source; freshness/quality is metadata, not a replacement value. |
| Excluded sources | `expected_cash_flows`/provider payout rows are forecast/calendar data; legacy `investment_cash_flows` are not boundary proof. Debts and property are outside gross performance valuation. | Never added to the valuation total. | Never added to the valuation total. | Excluded by contract; no double counting of internal interest, coupons, dividends, redemptions, fees, or taxes. |


<a id="c6-r08-01b-valuation-coverage-8-deliberate-implementation-boundary"></a>
#### Deliberate implementation boundary

The baseline has no trusted top-level portfolio valuation row, no account
identity for cash, and no effective-dated scope history. Therefore the
smallest additive solution is a nullable `cash_balances.account_id` link plus
explicit effective-dated account scope membership evidence. Existing cash and
membership history remain unclassified: no row is backfilled or inferred from
`name`, `include_in_capital`, or present-state account flags. The performance
service fails closed when either evidence set is incomplete.

Valuation points are derived read-only DTOs. They report exact RUB totals only
for authoritative selected components, with component coverage, provenance,
quality, and stable reason codes. Availability of an interval and return
metric remains the explicit R08-01C/#146/#147 boundary.

<a id="c6-historical_membership_api-1"></a>
### Finite historical membership API

Implements the accepted lifecycle and #610 valuation identity contracts. This is
not a source of new financial semantics or a durable audit trail.

`GET /api/performance/membership` takes `account_id`, `start_date`, `end_date`
and `scope` (`account` or `portfolio`). The account identifies the history being
edited; dates/scope preserve the original returns request. The response contains
the entire account history, a state identity, a transient form token and canonical
readiness with final XIRR/TWRR from the same committed snapshot.

`POST` takes the same context, `form_token`, `replaced_ids`, `replacements`
(`effective_from`, finite `effective_to`, explicit `include_in_returns`) and
`attested: true`. Empty replacements withdraw the named rows. Unselected rows are
preserved. The UI displays the complete before/after set and old/new interval
union before re-attestation. Open-ended existing rows cannot be selected.

After acquiring the SQLite writer reservation, the API consumes the form and
compares the complete membership/evidence/target state. Replacement, CLOSED
checks and invalidation share that transaction. The mutation returns affected
intervals, retired observation IDs, revoked coverage IDs, boundary target
identities and the resulting identity. After commit, an independent coherent read
must match that identity and read readiness/XIRR/TWRR; otherwise the response is
not a confirmed success. The browser rereads and compares the resulting row set
and identity, invalidating other query consumers. It never retries POST.

The state hash covers the preparation evidence catalogue plus observations,
boundary groups and group members, including targets without captured sides.
This conservative conflict detector is separate from the boundary-date v2
financial material hash. It does not broaden the invalidation map.

Form tokens are process-local, single-use, expire after 30 minutes, and are bounded
to 1024 outstanding entries. A submission retires other outstanding membership
forms; stale/failed/ambiguous submissions require rereading and re-attestation.
Restart loses forms. The existing database-maintenance restore guard changes a
transient form epoch after draining active operations, on success or failure, so
restoring identical contents cannot revive a form. These values are not persisted
financial generations and do not alter the accepted S2 A-to-B-to-A policy.

No migrations, provenance schema, provider calls, inferred historical intervals,
flow-scope rewrites, PRE/POST capture UI or automatic reopen/reclose are added.

<a id="c6-historical_membership_lifecycle_proposal-18"></a>
### Accepted finite membership writer lifecycle

<a id="c6-historical_membership_lifecycle_proposal-18-accepted-bounded-writer-contract"></a>
#### Accepted bounded writer contract

1. **Explicit evidence and interval.** Owner chooses an existing account, inclusive
   calendar dates `[effective_from, effective_to]` and explicitly attests included
   or excluded. Exclusion is known history, not an unknown gap. The first editor
   accepts finite intervals only; existing open-ended rows remain visible and
   block conflicting edits until an explicitly reviewed correction is possible.
   Current include_in_returns is neither a default attestation nor a write target.
2. **Gaps and overlaps.** Gaps remain unknown; no inferred extension, interpolation,
   merge or fill. Reject every overlapping interval for the same account, even
   when flags agree. Inclusive adjacent intervals must start the day after the
   preceding end. A correction must name all replaced rows and show the complete
   resulting interval set; hidden splitting/truncation is forbidden. Existing
   ambiguous overlaps stay fail-closed until explicitly corrected as one set.
3. **Corrections and withdrawal.** Replace/withdraw explicit row identities with
   optimistic comparison against the entire account history read at form opening.
   Changing either boundary or flag affects the union of old and new intervals;
   withdrawal leaves unknown history. Owner reviews that union and the before/after
   set, and re-attests. Metadata is not yet present in this model: any provenance
   persistence requirement needs a separate accepted schema decision. Do not
   invent an audit table or claim a durable audit trail from the existing columns.
4. **Invalidation.** Never rewrite external flows or their scope flags. In the same
   transaction, invalidate dependent cash/in-kind attestations and observed
   valuation evidence whose scope depended on the changed historical set. The
   implementation proposal must enumerate exact canonical consumers and affected
   account/portfolio boundary/group identities before acceptance; conservative
   invalidation must itself be approved, not implemented ad hoc. Re-attesting
   membership alone cannot attest cash/in-kind history or restore PRE/POST.
   Existing solver rules for in-interval membership transitions remain unchanged.
5. **CLOSED guard.** Reserve the writer before reading history/status/dependencies.
   Reject if the affected union intersects a CLOSED reporting period or a CLOSED
   snapshot/observed boundary relying on it, including an old interval removed by
   correction. For open-ended existing history, the affected future extent is not
   silently bounded by the UI selection. Reopen is a separate Owner operation;
   never reopen/reclose in the writer. Explain all reports requiring reopen, then
   explicit reclose and recalculation.
6. **Atomicity and races.** A single transaction covers stale-state comparison,
   overlap checks, CLOSED checks, replacement and invalidation. Any failure rolls
   back all changes. Concurrent close, correction, deletion, restore or competing
   history edits cannot yield a partial set or stale successful attestation.
   No transaction may commit through a nested service mid-operation. Duplicate
   submits must not create duplicate intervals. Unknown network outcome requires
   authoritative read-back before another write; never automatic POST retry.
7. **Read-back.** Return/read the resulting exact row set and affected identities,
   compare with the submitted correction, then reread canonical readiness and both
   final metrics for the original account/scope/interval. Read error or mismatching
   identity is not success. Saving history does not imply computable returns.

<a id="c6-pui04_implementation-8"></a>
### Preparation DTO, currentness and independent readback

<a id="c6-pui04_implementation-8-delivered-boundary"></a>
#### Delivered boundary

Preparation is embedded in the accepted Capital Performance detail. This avoids
another global route/spine change. Existing `start/end/scope/account_id/view` stay
unchanged; `prepare_account` and `prepare_reason` retain the selected repair context
through deep link/back/refresh. Account scope cannot silently prepare another account.

The Owner sees canonical external-flow classifications, exact amounts/source,
transfer links and independent cash/in-kind records. Empty lists require explicit
zero-activity attestation; incomplete history can be saved as unknown. Existing
coverage is reaffirmed only for its exact displayed interval; overlapping/different
intervals cannot be silently merged or overwritten. Cash account binding is an
explicit action. Creating a transfer link does not infer its legs; each leg is
attached explicitly and canonical reconciliation rules may reject conflicts.

Flow corrections reuse canonical invalidation. Current include flags, legacy
flows/imports, capital delta and payouts are never historical evidence. Finite membership inputs and observed PRE/POST capture use the accepted separate contracts in C6; preparation does not fabricate either. Saving and recomputing never calls a provider
or automatically opens/closes a report.


<a id="c6-pui04_implementation-8-technical-dto-and-optimistic-guard"></a>
#### Technical DTO and optimistic guard

`GET /api/performance/preparation?account_id=&start_date=&end_date=` returns one
coherent committed snapshot: context, canonical flow/coverage/movement/cash response
DTOs, transfer links, relevant reporting-period statuses and `evidence_token`.
Both interval endpoints are shown for source inspection; solver interval semantics
remain backend-owned. Snapshot-date matches include boundary reports even when their
reporting period is outside the requested dates.

The preparation client sends `X-Performance-Evidence` on existing canonical POST/PATCH
routes. Before any service reads/mutations, its request session reserves SQLite's
writer and compares a SHA-256 token of the complete preparation source tables:
accounts, historical membership, reporting months, cash balances, external flows,
transfer links/reconciliation evidence and cash/in-kind coverage/movements. Partner
legs and old intervals are included. Any mismatch returns 409 without mutation.
The lock remains through canonical commit/rollback, including CLOSED guards. This
is conservative conflict detection: even an unrelated preparation-source edit may
require rereading. It is neither a persisted revision nor financial evidence.
Existing clients without the optional header retain their contracts.

The token is captured with the displayed ledger and is never refreshed just before
POST to disguise an old attestation. Double-clicks have a synchronous client latch;
concurrent duplicate creates using the same token admit one changed state only.
No write retries occur automatically. On ambiguous outcomes the form locks until
explicit reread and inspection. On successful response, invalidate dependent queries,
read back the saved record and reread canonical readiness (including both final
XIRR/TWRR). Read failure or identity mismatch is not success. Unavailable metrics
remain unavailable, including while reports await explicit reclose.

<a id="c6-r08-03a-valuation-boundaries-8"></a>
### Observed valuation boundary persistence

<a id="c6-r08-03a-valuation-boundaries-8-persisted-evidence"></a>
#### Persisted evidence

`external_flow_boundary_groups` identifies an explicit same-date group at a
`portfolio` or `account` scope. Its members are persisted in
`external_flow_boundary_group_members`. The capture service sorts member IDs
and permits one explicit group per selected scope, reporting month and event
date; it never groups flows from a date implicitly.

`observed_valuation_points` stores one owner/provider-captured observation with:

- an exact non-negative minor-unit value and explicit `performance_currency`;
- `complete`/`unavailable`/`unknown` coverage and `exact`/`unavailable`/`unknown`
  quality;
- required provenance kind and optional provenance reference;
- an explicit `pre_external_flow` or `post_external_flow` relation;
- exactly one target: `external_flow_id` or `boundary_group_id`.
- a material signature of that flow, or of the group and every current member.

The signature uses the flow ID, reporting month, account, event date, exact
minor-unit amount, direction, kind, currency, scope membership and transfer
link. Group signatures also bind the group ID, month, scope, account, boundary
date and sorted member identities/signatures. Source, notes and timestamps are
metadata and do not change the signature. Every capture passes the signature
read when it began; persistence compares it with current state
under a SQLite writer reservation. Both PRE and POST must bind the same current
signature. Preexisting observations with no signature are unavailable until
freshly captured; migration does not infer their original event state. Once the
capture-start signature matches the current target under the writer reservation,
recapture retires older unbound or stale points for that same scope and boundary
before saving new evidence. A partial fresh pair remains unavailable.

The capture services accept only draft reporting months. Existing monthly
snapshots, legacy investment cash flows, historical scope membership and
current account flags are not backfilled or reinterpreted. Portfolio-internal
transfers cannot create a boundary group.

Boundary groups and observed points are scope-specific. Availability considers
only groups matching the requested scope and account; one external flow may
therefore have separate valid account- and portfolio-scope groups and evidence.

Group membership is immutable after creation. Both valuation capture and
performance availability revalidate every current member against the group's
reporting month, scope/account and boundary date. A group is unusable if a
member changes date or leaves the selected scope; it cannot accept new observed
points or make TWRR exact. To correct a stale date or membership, delete the
group in its editable reporting month, then explicitly create a replacement
with the chosen date and member IDs and capture fresh PRE/POST observations.
Deleting a group also deletes its members and observed points. The service does
not infer a replacement date or membership. Direct boundaries for flows that
are not members of a group keep their existing lifecycle.


<a id="c6-r08-03a-valuation-boundaries-8-read-only-availability"></a>
#### Read-only availability

`GET /api/performance/availability` exposes `external_flow_boundaries`. Each
entry contains the deterministic flow ID tuple, event date, availability,
both observed sides when present, exact values/provenance, and stable reason
codes. A side is usable only when its relation/date, coverage, quality and
performance currency are valid. For either explicit relation, `observed_date`
must equal the flow or group `boundary_date`; an earlier PRE or later POST is
not exact boundary evidence. Missing sides fail closed with
`not_computable_valuation_boundary_missing`; ambiguous or unproven same-day
ordering fails closed with
`not_computable_valuation_boundary_order_unknown`.

The response remains evidence-only: it contains no return factor, percentage,
TWRR/XIRR value, interpolation, provider refresh or inferred valuation. The
future #147 calculator may consume this contract without redefining flow,
transfer, currency or historical-scope semantics.

<a id="c6-pui05_valuation_capture-9"></a>
### Delivered authoritative PRE/POST capture

<a id="c6-pui05_valuation_capture-9-delivered-boundary"></a>
#### Delivered boundary

`GET /api/performance/valuation-captures?start_date=&end_date=&scope=&account_id=`
returns one committed snapshot with:

- the canonical explicit targets that need observed evidence, resolved from
  `performance_availability_for_interval` (never a second target detector);
- target identity: boundary group ID or flow IDs, scope/account, event date,
  reporting month and its status, performance currency;
- `pre_state`/`post_state` per relation (`captured`, `missing`, `stale` or
  `ambiguous`) plus every persisted side with exact amount/currency, coverage,
  quality, provenance kind and the material binding state;
- the current `material_signature` and, only for a truly capturable target, a
  single-use capture token;
- canonical readiness with both final metrics from the same snapshot.

`POST /api/performance/valuation-captures` takes the target identity, the
capture-start `expected_material_signature`, the single-use `form_token` and
one actually observed side (relation, exact amount, provenance
kind/reference, notes, explicit attestation). The server resolves the
reporting month, observed date, target performance currency and authoritative
coverage/quality from the target itself, so a client cannot submit a
mismatched month, boundary date, currency or non-authoritative value.


<a id="c6-pui05_valuation_capture-9-authoritative-only-capture"></a>
#### Authoritative-only capture

The supported adapter persists only evidence that could ever make the pair
authoritative:

- `coverage=complete` and `quality=exact` (the API accepts nothing else);
- `performance_currency` exactly equal to the target performance currency.

This is intentional: the canonical valuation-boundary service has no
observation update/delete correction path, so an incomplete, inexact or
foreign-currency side would permanently consume the target without ever
making TWRR usable. Owners see only source-backed complete/exact input; the
write form has no unknown/unavailable choices and shows the currency fixed
and read-only. When no confirmed historical source exists, the form says so
and performs no write — the readiness limitation stays displayed.

Persisted legacy/non-authoritative sides remain visible in their stored form
and continue to fail closed. The adapter offers no edit, delete or repair
path for them.


<a id="c6-pui05_valuation_capture-9-fail-closed-rules"></a>
#### Fail-closed rules

- The writer reservation is acquired before the authoritative reread; the
  stored signature must equal the capture-start signature or the write is
  rejected (`409`) without mutation.
- Flow correction/delete, group date or member change, and membership change
  therefore change the signature and reject a stale form. The accepted #610
  A→B→A policy is unchanged.
- One side per target and material state: an existing bound side, duplicate
  same-relation rows or an already ambiguous target are rejected. The adapter
  never picks a convenient pair and never retires corrupt rows implicitly.
- Non-authoritative input (incomplete coverage, inexact quality) is rejected
  at the DTO boundary (`422`) and again in the adapter service; a currency
  different from the target performance currency is rejected (`409`). No row
  is created by any rejected submission, so a later valid source-backed
  capture remains possible.
- CLOSED months fail closed (`409`); the read marks the target
  `requires_reopen`. There is no automatic reopen, reclose or retry.
- The capture token is process-local, single-use, expires after 30 minutes and
  is retired by a restore epoch. A rejected or ambiguous submission can only be
  followed by an explicit reread, never a blind replay.
- Amount, currency, coverage, quality, provenance and attestation are validated
  before persistence; only the canonical service stores the observation.


<a id="c6-pui05_valuation_capture-9-read-back"></a>
#### Read-back

After commit the response is produced from an independent coherent reread: the
saved side must appear bound to the same current signature in the capture
projection, and the canonical readiness (diagnostics plus final XIRR/TWRR) is
read in the same snapshot. A commit acknowledgement alone is never presented as
a confirmed capture. Remaining blockers are not hidden; saving evidence does
not guarantee TWRR, and XIRR stays independently available when its
prerequisites are met.

The readiness diagnostic keeps exact capability semantics: the observation
adapter reports `available` only when a concrete target can accept fresh
evidence now, `requires_reopen` when only the explicit month reopen blocks it,
and `not_implemented`/`unsupported` when identity, grouping or duplicate sides
make input impossible.


<a id="c6-pui05_valuation_capture-9-deliberate-limitations"></a>
#### Deliberate limitations

- Observation deletion or in-place correction is not supported by the accepted
  contracts. A wrong observed value can only be replaced through a material
  target change (which retires stale sides) followed by fresh capture.
- Persisted non-authoritative legacy sides are displayed and fail closed; the
  adapter deliberately does not repair, replace or delete them.
- Explicit boundary-group creation/deletion remains a separate lifecycle and
  is not part of this adapter; same-day grouping is never inferred.
- Free-form provenance references are stored but never echoed by the read
  projection.

<a id="c6-class_no_crossing_endpoints-7"></a>
### Full-class no-crossing claims and exact endpoints

<a id="c6-class_no_crossing_endpoints-7-evidence-and-write-lifecycle"></a>
#### Evidence and write lifecycle

Migration 0046 creates `class_no_crossing_coverages` without defaults/backfill.
Each assertion stores one class, inclusive covered dates, state
(`complete`, `unknown`, `revoked`), `owner_attestation` provenance, an optional
reference label, revision and material signature. There is no statement-verified
source in this slice and no free-form notes. References must be privacy-safe
labels, never private payloads or credentials.

Migration 0047 adds `opening_inventory_complete` and `closing_inventory_complete`.
Each is an explicit Owner claim that **every holding of the requested class in
every historically included account** is represented at that exact endpoint,
including accounts with no holdings of that class. Both default to false;
upgrade preserves existing C2 records without manufacturing inventory claims.
The same Owner action may affirm no-crossing and both inventory claims. No
position footprint, other-class row, importer success or empty query sets them.

`POST /api/class-evidence/coverages` creates an explicit assertion.
`PUT /api/class-evidence/coverages/{id}` supplies its complete replacement,
including `unknown`/`revoked`, with required `If-Match` integer revision.
`GET /api/class-evidence/coverages` returns the evidence inventory.
Writes reserve SQLite's writer through commit/rollback, check both original
and proposed intervals against CLOSED periods/snapshot dates, reject overlapping
assertions of the same class and reject stale revisions. Reopen all intersecting
closed months before correcting/revoking/reaffirming evidence.

COMPLETE requires an explicit class-wide assertion against the current
persisted facts. Purchases/sales, distributions, principal, reclassification,
attributable fees/taxes, external in-kind and all other class entry/exit events
are covered by the assertion. Net-zero crossings remain crossings.
InvestmentCashFlow is a contradiction source, never complete trade history.
Known class-attributed cash facts reject the assertion; unattributed income/cost
facts block class completeness. Unattributed settlement deposits/withdrawals do
not alone assert security purchases or sales. Known events on either covered
date are checked; unknown ordering at the opening date is not inferred.

COMPLETE is bound to persisted membership, exact reporting identities, class
positions/quantities/values and relevant known flows/movements. Both inventory
claims are included in this binding, scoped to the same class, exact dates and
entire historical account universe; neither is a claim about only clean rows.
Current account flags, current instrument type, quotes and metadata are not
historical proof and cannot rewrite the binding. Reads compare this signature
to current committed material every time; there is no result cache.
Reopen retires intersecting COMPLETE assertions to UNKNOWN and increments their
revision, even if data is later restored unchanged. Explicit C1 correction
retires affected class assertions even if subsequently undone. A signature
mismatch is exposed as effective `invalidated` with the stored provenance/state
still visible; explicit reaffirmation replaces the binding in DRAFT.
Close never attests or repairs evidence. Whole-file backup/restore carries the
table; an old-schema recovery upgrade creates no assertions.
Downgrade refuses to discard either persisted affirmative inventory claim,
including claims on revoked/unknown records.


<a id="c6-class_no_crossing_endpoints-7-exact-endpoint-read"></a>
#### Exact endpoint read

`GET /api/class-evidence/endpoints?asset_class=stock&start_date=...&end_date=...`
returns requested/actual dates, historical included account IDs, currency,
coverage state/provenance, status and sorted reason codes. Exact opening/closing
integer kopeck values appear only for `eligible`; otherwise both are NULL.

The whole historical portfolio universe uses existing
`AccountPerformanceScopeMembership` coverage, with gap/overlap/change checks
for catalogue accounts including historical exclusions. Current flags never
fill a gap. Endpoints must match exactly one reporting snapshot per requested
date. All observed interval snapshots must be CLOSED. Only persisted
`historical_instrument_type` class identity and `market_value_kopecks` are used;
NULL never falls back to today's catalogue. Stored bond value already carries
its existing accrued-interest basis; no recomputation/addition occurs here.
The accepted PositionSnapshot write path normalizes monetary inputs through
`RubleAmount`, and its existing API returns `market_value_kopecks` in RUB.
That persisted RUB total is the endpoint valuation basis. Current mutable
`Instrument.currency` is neither historical currency proof nor signature
material: a catalogue currency edit cannot change historical eligibility.
No foreign amount is converted or valued here; the non-RUB base-currency gate
remains unsupported. This does not introduce FX or a foreign valuation path.

Unknown historical identities block completeness. Appearance/disappearance,
quantity changes, reclassification and relevant archived history fail closed.
Both explicit inventory claims must be true on the single matching, complete,
material-bound Owner assertion. A position footprint proves only presence of
that row. For example, account B's bond rows cannot prove B's stock inventory
complete, even when account A has stable stock rows. Absent endpoint claims
keep both values unavailable until explicit attestation; cash/deposit rows
cannot repair the missing evidence. An Owner claim cannot override known NULL
identity, quantity changes or other contradictions.
All observed intermediate snapshots are checked as well as endpoints.
No trades/corporate actions are invented from deltas. The only accepted
quantity redistribution uses explicit existing `internal_transfer` markers
with instrument, positive quantity and Owner provenance, between continuously
included accounts, exactly reconciling per-account/per-instrument quantities
across adjacent snapshots. Unmatched/unknown markers block eligibility.
An exactly reconciled same-class internal movement is not itself a class crossing.

Exactly one evidence interval must match the request. This first slice does not
assemble unions, narrow larger assertions or produce empty-class zero values.
Clean rows never substitute for a whole requested class. Foreign components,
funds, FX/currency, deposits/savings and `gold_other` remain unsupported.


<a id="c6-class_no_crossing_endpoints-7-deterministic-reasons"></a>
#### Deterministic reasons

| Code | Meaning |
| --- | --- |
| `unsupported_class` | Outside stock/bond/gold capability. |
| `unsupported_currency` | Non-RUB base-currency setting; persisted endpoint valuation is RUB. |
| `membership_incomplete_or_changed` | Missing/overlapping/gapped/changing historical scope. |
| `historical_universe_empty` | No continuously included historical account universe. |
| `exact_endpoint_missing_or_ambiguous` | Requested snapshot date does not identify exactly one month. |
| `reporting_month_not_closed` | An observed interval month is DRAFT. |
| `historical_class_unknown` | A relevant historical position has NULL identity. |
| `historical_class_reclassified` | Observed instrument identities cross the requested class. |
| `archived_position_incomplete` | Relevant archived history cannot prove complete active endpoints. |
| `class_endpoint_empty` | No requested-class component at an exact endpoint. |
| `opening_class_inventory_not_complete` | No explicit whole-class, whole-universe opening inventory claim. |
| `closing_class_inventory_not_complete` | No explicit whole-class, whole-universe closing inventory claim. |
| `position_set_changed` / `position_quantity_changed` | Quantities are not stable or exactly explained by accepted internal markers. |
| `known_cash_crossing` / `cash_flow_class_unknown` | Known class cash contradiction or unresolved class attribution. |
| `external_in_kind_crossing` / `in_kind_class_unknown` | Known external movement or missing historical movement identity. |
| `internal_transfer_ambiguous` | Internal evidence cannot reconcile the requested historical scope/quantities. |
| `no_crossing_coverage_missing_or_ambiguous` | No single exactly matching assertion. |
| `no_crossing_coverage_not_complete` | Stored assertion is unknown/revoked. |
| `no_crossing_material_changed` | Current authoritative material differs from the assertion's binding. |

No providers/background reads, return solvers, PRE/POST, execution ledger,
corporate-action engine, tax lots or portfolio/account-return changes are added.

<a id="c6-instrument_eod_observations-1"></a>
### Instrument EOD endpoint comparability

Accepted scope: [#860](https://github.com/LTstripes/hermes-finance/issues/860),
following [#855 acceptance](https://github.com/LTstripes/hermes-finance/issues/855#issuecomment-6231173234).
Implementation started after #858 post-main CI succeeded on `9586f2ba5571cd40c8bcfc2fedd98d676d65c5ad`.

`GET /api/instruments/{instrument_id}/eod-observations?account_id=…&t0=YYYY-MM-DD&t1=YYYY-MM-DD`
reads one exact brokerage/IIS account and two exact persisted `PositionSnapshot`
observations, with `t0 < t1`. Invalid dates return 422; absent references return
404. The existing on-demand Capital → Performance panel reads this composite
endpoint once. Both boundaries and [known net payouts](#c5-instrument_cash_income-1)
share one committed, query-only snapshot. Payout dates remain `(t0,t1]`.

Each available boundary exposes Decimal quantity, exact RUB market value,
historical RUB stock/bond identity, native NKD basis, price date, position/import/
row identifiers, accepted receipt IDs, revision generation, currentness and
dependency fingerprint. Amounts remain integer-kopek-backed decimal strings.
Per-unit quote absence does not erase an independently accepted native total.
No nearest-date, live quote or catalogue-only identity fallback is allowed.

Authority reuses native SOURCE receipts, original source integrity, accepted
historical mappings/dispositions, canonical overlap conflicts and native
account/month projection readback. A changed, ambiguous, archived, unsupported
or unproven boundary returns NULL numeric values and explicit reason codes.
Missing positions never imply zero ownership or value. The native writer's
suppressed zero row also cannot establish zero closing value without separate
accepted evidence of no outstanding entitlement. Inactive/exited instruments
remain selectable and their known payouts remain independent of endpoint gaps.

Pair comparability concerns the observed value basis only. Unknown bond NKD
basis leaves comparability NULL; mismatched basis/identity makes it false.
Only comparable observations may expose `observed_position_value_difference`.
Changing quantity does not establish price profit, sale proceeds, cost or a
realized/unrealized split. The UI labels any difference as observed position
values, never adds payouts to it, and prominently states that full instrument
return RUB/% is unavailable. Interval activity and payout completeness remain
unknown. No new accounting engine, writer, schema, provider call or export exists.

The EOD token binds relevant source material, retained mappings/history,
account/instrument/periods, positions, account receipts and current native
account/month projection digests. Unrelated accounts' original source text is
not hashed into it. The existing global correction generation conservatively
invalidates it on source/registry/catalogue SQL changes, including ABA. Native
position/month/cash changes through supported ORM writers use the retained
monotonic dependency receipts. Arbitrary SQL projection ABA bypassing those
writers is outside that existing journal guarantee; this slice adds no triggers.
Changed current projection readback is still detected. No reliable native
boundary journal means that boundary's token is NULL.

`valuation_dependency_fingerprint` describes the EOD dependency set. The full
`dependency_fingerprint` additionally binds #858's payout token and is NULL
whenever either boundary journal or the payout token is unavailable. #858 manual,
retired, UNKNOWN, NULL and tax semantics are unchanged. The UI hides both sections
during refresh/error or selector/context changes and rejects a different outer,
boundary or payout scope. Every explicit read gets a new request generation.

Focused evidence: `test_instrument_eod_observations_service.py`, unchanged #858
regressions and `InstrumentCashIncome.test.tsx`. The disposable real-backend
production-dist desktop journey is:

```text
npm run build
npm run test:e2e -- --project=instrument-eod
```

It covers bond 1000/950/coupon 120, stock 1000/900/dividend 120, exact-date gaps,
provenance, selector invalidation, keyboard submission, 1440px desktop and
1280px at 125% zoom. Its accounts, documents and screenshots are synthetic;
it performs no Owner/Stable operations and does not replace Owner UAT.

<a id="c6-performance_v1_reconciliation_2026-09-06-62"></a>
### PERF-H1 A–F and all sixteen normative vectors

<a id="c6-performance_v1_reconciliation_2026-09-06-62-accepted-perf-h1-hardening-contract"></a>
#### Accepted PERF-H1 hardening contract

PERF-H1 A–F define the accepted implemented completeness guards below. Known membership transitions cannot substitute for constant-scope evidence, and the absence of known bad cash rows cannot establish affirmative cash-boundary coverage.

The contract does not redesign R08. Its policy remains:

**false unavailable > false exact**.


<a id="c6-performance_v1_reconciliation_2026-09-06-62-h1-a--asynchronous-owned-account-transfer-transit"></a>
#### H1-A — asynchronous owned-account transfer transit

A linked A -> B transfer between two historically proven in-scope accounts
remains `INTERNAL_TRANSFER` for whole-portfolio scope even when its legs settle
on different dates. Different settlement dates never turn it into an owner
contribution/withdrawal.

If `source_leg.event_date < destination_leg.event_date`, the interval from the
source departure through destination arrival is transfer transit. Money in
transit is economically still part of the owner portfolio, but current Hermes
valuation components do not represent a synthetic in-transit asset.

Hermes must not synthesize cash-in-transit, move leg dates, temporarily classify
the transfer as external, or silently treat omitted transit value as return.

A required whole-portfolio valuation is unsafe when its effective/observation
date falls on or between those date-only endpoints and there is no explicit
trusted provenance proving that the valuation includes the transferred capital.
Same-day ordering continues to use the existing fail-closed boundary-order
semantics unless explicit provenance proves order.

Metric-specific effect:

- XIRR checks only the required opening and closing valuations;
- exact TWRR checks opening, closing and every observed pre/post valuation
  boundary actually consumed by an external-flow subperiod split;
- an unrelated intermediate TWRR boundary inside transit does not by itself
  make XIRR unavailable;
- account-scope legs remain withdrawal/contribution on their actual dates and
  are not blocked merely because the aggregate portfolio transfer has transit.

New stable reason:

`not_computable_transfer_in_transit_unvalued`

Structural linkage alone is not proof that whole-portfolio value reconciles.
For same-currency v1 performance, transfer legs must either have equal boundary
amounts or the difference must be explained by authoritative canonical evidence
from this closed set:

- broker fee / commission charged inside scope;
- tax charged inside scope;
- accepted FX conversion/spread evidence under an existing currency contract.

Reconciliation evidence must identify the specific transfer it explains; one
fee/tax item cannot be reused to reconcile multiple overlapping transfers. FX
reconciliation never bypasses the existing performance-currency completeness
gate.

No other unexplained reconciliation category is allowed without a future
accepted contract. An unexplained difference remains fail-closed with:

`not_computable_transfer_reconciliation_incomplete`

Partially linked/one-legged transfers continue using the existing unresolved
transfer reason. Overlapping transit intervals are evaluated independently;
intersection with any unvalued transit interval blocks the affected required
whole-portfolio valuation. Detection must not be limited to transfer legs whose
own event dates fall inside the requested interval: a transit interval may span
a required valuation even when both leg dates lie outside that request window.


<a id="c6-performance_v1_reconciliation_2026-09-06-62-h1-b--in-kind-securities-crossing-a-performance-boundary"></a>
#### H1-B — in-kind securities crossing a performance boundary

Hermes must never synthesize cash for a security or other non-cash asset merely
to satisfy XIRR/TWRR inputs.

Absence of `ExternalFlow` or legacy cash deposit/withdrawal rows is not proof
that no in-kind movement occurred. Exact performance therefore requires
explicit in-kind boundary coverage for accounts capable of holding transferable
investment instruments.

For current v1, that population is deterministic and restricted to accounts
that are historically relevant to the selected performance scope:

- canonical account type `brokerage`;
- canonical account type `iis`;
- any account that has persisted `position_snapshots` in or before the requested
  interval, even if its generic account type is broader.

Cash-only/other accounts with no persisted investment positions do not acquire
an in-kind coverage requirement merely because they exist.

Minimum coverage states:

- `COMPLETE` — the required account/interval is explicitly covered and every
  in-kind boundary movement is known, including the valid case where there
  were none;
- `UNKNOWN` — Hermes cannot establish whether such movement occurred.

`COMPLETE` means the history is known; it does not mean the movement set is
empty. A known but unvalued movement continues to block exact performance.
Coverage must retain account/interval identity and provenance. It may be
established only by explicit owner attestation or a future accepted authoritative
statement/import contract. Existing history is never automatically migrated to
`COMPLETE`. Corrections that change closed historical evidence must preserve the
existing explicit reopen semantics rather than silently mutating closed history.

Unknown coverage:

`not_computable_in_kind_boundary_coverage_unknown`

A known in-kind movement without an accepted event-date non-cash valuation
contract:

`not_computable_in_kind_movement_unvalued`

An in-kind movement between two historically in-scope accounts is conceptually
internal at portfolio scope, but until Hermes has accepted non-cash
transfer/valuation evidence sufficient to preserve valuation continuity, exact
portfolio performance across that known movement remains unavailable rather
than assuming continuity. Full non-cash flow support is deferred.


<a id="c6-performance_v1_reconciliation_2026-09-06-62-h1-c--taxfee-treatment-and-performance-basis"></a>
#### H1-C — tax/fee treatment and performance basis

R08 performance is explicitly frozen as after-tax / after-internal-cost
performance. Taxes and commissions charged inside the selected investment
scope reduce performance and do not become owner capital withdrawals merely
because investment cash decreases.

Example: brokerage cash falls by 100,000 RUB while an owner withdrawal is
processed; 87,000 RUB reaches the owner and 13,000 RUB is withheld/remitted as
tax from inside the investment scope.

Canonical semantics:

- external withdrawal boundary amount = 87,000 RUB;
- internal tax cost = 13,000 RUB;
- no synthetic 100,000 RUB external withdrawal.

The separation is deterministic only when accepted source evidence establishes
the actual outside-scope amount and the tax/fee component. Evidence may be one
authoritative source contract with explicit gross/tax/net meaning or multiple
canonical events that deterministically reconcile to the same primary owner
transaction. Hermes must not infer boundary meaning from legacy field names.
If the actual boundary amount cannot be proven:

`not_computable_external_flows_incomplete`

A standalone tax charged from in-scope investment cash without a related owner
withdrawal remains an internal cost. It creates no `ExternalFlow` and does not
make external-flow coverage incomplete merely because no withdrawal exists.


<a id="c6-performance_v1_reconciliation_2026-09-06-62-h1-d--direct-realised-coupondividend-payout-outside-brokerage-cash"></a>
#### H1-D — direct realised coupon/dividend payout outside brokerage cash

If a realised coupon/dividend is paid directly from issuer/broker/source to the
owner outside the investment scope without first entering in-scope brokerage
cash:

- the coupon/dividend remains economic/passive-income explanation evidence;
- the separately proven actual payment crossing the investment boundary is
  represented using existing external-withdrawal semantics;
- the economic income event is not injected separately into XIRR/TWRR;
- no new external-flow kind is introduced.

The flow belongs to the canonical investment account that generated the
entitlement, established by accepted source/account/holding provenance, never by
guessing from a later snapshot. If the same instrument is held in multiple
accounts, each independently evidenced account payout is separate.

`event_date` is the actual payout/settlement date and reporting-month association
follows the month containing that event date. A matching debit from
`CashBalance` is not required when the cash never entered in-scope brokerage
cash.

Withholding outside scope is distinct from H1-C. Example: gross dividend
10,000 RUB, 1,300 withheld before payment, 8,700 paid directly to owner.

- external boundary amount = 8,700 RUB;
- 1,300 is not a separate internal brokerage-cash tax event;
- gross 10,000 may remain passive-income/explanation evidence;
- return math consumes the 8,700 external boundary flow and valuations without
  adding the gross dividend again.

Expected/provider calendar events are not proof of realised payment. Accepted
actual-cash evidence is required; otherwise the affected interval remains
`not_computable_external_flows_incomplete`.

A proven direct payout is sufficient boundary-flow evidence for the payment,
but it never substitutes for the observed pre/post valuation boundaries required
by exact TWRR. Internal tax/commission is not added a second time on top of a
valuation that already reflects that cost.


<a id="c6-performance_v1_reconciliation_2026-09-06-62-h1-e--stable-whole-portfolio-scope-membership"></a>
#### H1-E — stable whole-portfolio scope membership

Gap-free effective-dated membership history is necessary but not sufficient for
exact whole-portfolio return. A known account transition from out-of-scope to in-scope (or the reverse) can select different endpoint portfolio compositions. Without an accepted scope-transition value it must not be reported as investment return.

Until a future accepted scope-transition valuation contract exists, exact
whole-portfolio XIRR/TWRR is available only when every historically relevant
account has one constant `include_in_returns` state for every date in the closed
requested interval `[start_date, end_date]`.

A transition strictly before `start_date` or strictly after `end_date` is
irrelevant. A transition whose effective date lies inside the requested closed
interval makes exact whole-portfolio performance unavailable. No synthetic
contribution/withdrawal is created from the entering/leaving account value.

New stable reason:

`not_computable_scope_membership_changed`

Explicit flow-level membership evidence must also agree with the effective-dated
history at that flow's `event_date`:

- `stable_in_scope` requires effective membership `true` on that date;
- `stable_out_of_scope` requires effective membership `false` on that date;
- `unknown` retains the existing non-authoritative fail-closed behavior.

A contradiction is scope-coverage failure and must not be silently resolved in
favour of either record. The existing `not_computable_scope_coverage_incomplete`
reason may represent this inconsistency; response metadata should identify the
affected account/flow evidence.

This restriction applies to whole-portfolio performance. Existing explicit
account-scope fail-closed membership rules remain authoritative.


<a id="c6-performance_v1_reconciliation_2026-09-06-62-h1-f--explicit-cash-boundary-history-coverage"></a>
#### H1-F — explicit cash-boundary history coverage

The absence of known bad `ExternalFlow` or legacy deposit/withdrawal rows is not
proof that all owner cash crossings were captured. A missing contribution or
withdrawal can otherwise appear as investment return even when valuations are
perfectly observed.

Exact XIRR/TWRR therefore requires affirmative cash-boundary history coverage
for every account historically included in the selected performance scope over
the requested interval. In-kind coverage and cash-boundary coverage are
independent proofs; satisfying one never satisfies the other.

Minimum coverage states:

- `COMPLETE` — authoritative/owner-confirmed evidence establishes that all
  owner cash boundary crossings for the covered account/interval are known and
  represented under the accepted `ExternalFlow` contract, including the valid
  case of zero crossings;
- `UNKNOWN` — completeness cannot be established.

Coverage may be established by explicit owner attestation or a future accepted
authoritative statement/import contract. Existing historical intervals are not
automatically migrated to `COMPLETE` merely because no blocking rows exist or a
reporting month is closed.

`COMPLETE` is a completeness assertion, not a replacement for the flows
it covers: any known contribution/withdrawal still requires its canonical
`ExternalFlow` evidence and all ordinary amount/date/currency/transfer rules.
A direct payout covered by H1-D is part of cash-boundary history and must be
represented explicitly; expected/provider calendar evidence remains
insufficient.

When cash-boundary coverage is `UNKNOWN`, exact performance remains
`NOT_COMPUTABLE` using the existing stable reason:

`not_computable_external_flows_incomplete`

Coverage persistence must retain account/interval identity and provenance.
Corrections to evidence belonging to closed historical months must preserve
explicit reopen semantics; closing a month alone never attests cash-boundary
completeness.


<a id="c6-performance_v1_reconciliation_2026-09-06-62-new-stable-reason-codes-from-h1"></a>
#### New stable reason codes from H1

- `not_computable_transfer_in_transit_unvalued`
- `not_computable_transfer_reconciliation_incomplete`
- `not_computable_in_kind_boundary_coverage_unknown`
- `not_computable_in_kind_movement_unvalued`
- `not_computable_scope_membership_changed`

Cash-boundary coverage intentionally reuses
`not_computable_external_flows_incomplete`. Existing R08 reasons remain
authoritative where applicable.


<a id="c6-performance_v1_reconciliation_2026-09-06-62-normative-regression-vectors"></a>
#### Normative regression vectors

1. Async transfer 10 -> 15 Feb, requested closing valuation 12 Feb: portfolio
   XIRR and TWRR are `NOT_COMPUTABLE` due unvalued transit.
2. Same async transfer wholly inside a 1 -> 28 Feb interval, with no required
   TWRR valuation inside transit: portfolio XIRR/TWRR may remain available if
   all other prerequisites are complete.
3. External owner flow on 12 Feb during the 10 -> 15 Feb transit: XIRR is not
   blocked solely by the unsafe TWRR boundary; exact TWRR is blocked.
4. A transit interval spanning a required valuation is detected even when both
   transfer-leg dates themselves lie outside the requested metric interval.
5. Transfer 100,000 -> 99,900 with no accepted reconciliation: unavailable.
   With authoritative 100 RUB internal fee evidence linked to that transfer:
   may reconcile.
6. Brokerage/IIS interval with unknown in-kind coverage: exact performance is
   unavailable.
7. Known external transfer of shares without accepted event-date non-cash
   valuation: exact performance is unavailable.
8. Withdrawal processing debits 100,000 from scope, pays owner 87,000 and
   withholds 13,000 inside scope: external withdrawal 87,000 + internal tax
   cost 13,000.
9. Standalone in-scope tax with no owner withdrawal: no external flow.
10. Retained dividend: no external flow.
11. Dividend enters brokerage cash then owner withdraws it: separate internal
    income event + external withdrawal; no double counting.
12. Direct gross dividend 10,000 with 1,300 withheld outside scope and 8,700
    paid directly to owner: external withdrawal 8,700; no internal 1,300 tax
    event. Exact TWRR still requires its ordinary observed boundary evidence.
13. Portfolio A remains worth 100 while portfolio account B remains worth 50
    but B changes `include_in_returns=false -> true` inside the interval:
    whole-portfolio exact XIRR/TWRR are unavailable rather than reporting a
    synthetic +50% return.
14. `ExternalFlow.scope_membership=stable_in_scope` on a date where effective
    membership is false: scope coverage is inconsistent and exact performance
    is unavailable.
15. Opening valuation 100, closing valuation 200, no recorded flow rows and no
    affirmative cash-boundary coverage: exact performance is unavailable rather
    than inferring +100% return.
16. The same interval with explicit COMPLETE cash-boundary coverage and zero
    actual owner crossings may proceed if every other prerequisite is complete.

<a id="c7"></a>
## 7. Returns, hypothetical results and monetary attribution

XIRR is annualized, TWRR is period return with observed required PRE/POST boundaries, and S3 is indicative nonannualized MWR with Decimal-string `rate_fraction`. Unit conversions and metric-specific reason codes are part of the contract. Lack of source authority and numerical solver failure remain different states.

The supported class subset requires C1–C5/no-crossing evidence; it is not generic trading-class performance. Account WHAT-IF retains hard UNKNOWN reasons and finite assumptions. Instrument WHAT-IF stays stock-only/fixed-holding. PERF04 is `ΔV − external flow`, a monetary bridge; it is neither return nor automatically P&L. Component rows must reconcile in minor units without duplicating transfer, payout, tax or fee effects.

<a id="c7-r08-01c-performance-availability-12"></a>
### Independent prerequisites and stable reason codes

<a id="c7-r08-01c-performance-availability-12-read-only-api"></a>
#### Read-only API

```text
GET /api/performance/availability
    ?start_date=YYYY-MM-DD
    &end_date=YYYY-MM-DD
    &scope=portfolio|account
    [&account_id=<id>]
```

`start_date` and `end_date` are exact persisted valuation dates and
`start_date` must be before `end_date`. `account_id` is required for
`scope=account` and is forbidden for `scope=portfolio`.

The top-level `availability` is conservative: it is `available` only when
both downstream prerequisite assessments are available. Consumers should use
`xirr` and `twrr` separately because XIRR can be available when exact TWRR is
not.

The response contains:

- `opening_valuation` and `closing_valuation` with the selected reporting
  month, exact valuation date, total, component coverage and source
  provenance;
- `scope_membership` with effective-dated account evidence for the whole
  interval;
- `cash_boundary_coverage` with affirmative per-account cash-history evidence,
  state and provenance;
- `external_flows` with sanitized exact flow metadata, classification,
  transfer status, legacy unclassified row IDs and coverage reasons;
- `external_flow_boundaries` with deterministic pre/post observed valuation
  evidence for each selected-scope external flow or explicit same-date flow
  group;
- `xirr` and `twrr` prerequisite availability, each with stable reason codes.

No return value, return percentage, inferred valuation or converted foreign
currency amount is returned.


<a id="c7-r08-01c-performance-availability-12-evidence-rules"></a>
#### Evidence rules


<a id="c7-r08-01c-performance-availability-12-opening-and-closing-valuations"></a>
#### Opening and closing valuations

Each boundary must resolve to exactly one persisted `reporting_months` row
whose `snapshot_date` equals the requested date. A missing or ambiguous match
is unavailable; a later or neighboring month is never substituted. The
selected month must be closed. The R08-01B valuation service must also report
all selected position, deposit and performance-cash components as authoritative
in the base currency. Missing components stay unknown and are not emitted as
zero.

Existing position and deposit snapshot amounts are base-currency values under
their persisted schema. A cash row without an explicit account identity is
unclassified for performance scope. Non-base-currency cash or flow requires an
accepted dated conversion, which is not available in this v1 slice.


<a id="c7-r08-01c-performance-availability-12-historical-scope-membership"></a>
#### Historical scope membership

The service uses only `account_performance_scope_memberships` for historical
scope selection. Every account relevant to a portfolio request, or the
explicit account request, must have gap-free non-overlapping effective-dated
membership evidence over the requested interval. The present account flag is
never used to rewrite history.


<a id="c7-r08-01c-performance-availability-12-cash-boundary-history-coverage"></a>
#### Cash-boundary history coverage

Exact performance additionally requires affirmative cash-boundary coverage for
every account historically included in the selected scope over the interval.
Coverage is `complete` only when the owner has explicitly attested that all
owner cash crossings are known, including the valid zero-crossing case. The
current accepted provenance is `owner_attestation`; the persisted provenance
fields leave room for a future authoritative source without treating a
provider/import value as authoritative today.

Missing, partial, overlapping, ambiguous or `unknown` coverage remains
`unknown` and contributes the existing
`not_computable_external_flows_incomplete` reason to both XIRR and TWRR. No
flow rows, closed months, current account state, successful valuation,
in-kind evidence or heuristics can infer completeness. Complete coverage is
not a flow ledger and does not replace canonical `ExternalFlow` validation for
any known contribution, withdrawal or direct payout. Coverage writes affecting
closed reporting months require the existing explicit reopen lifecycle.


<a id="c7-r08-01c-performance-availability-12-external-flow-completeness"></a>
#### External-flow completeness

Explicit R08-01A flows are selected by their exact `event_date` over the
interval and classified at the requested scope. A linked two-leg transfer is
internal for portfolio scope and crosses the boundary for each affected
account scope. A one-sided or otherwise unresolved link blocks the affected
scope. An unknown persisted flow membership is non-authoritative.

Legacy `investment_cash_flows.deposit` and `withdrawal` rows remain legacy
evidence. A legacy withdrawal can stop being an unclassified blocker only when
one canonical in-scope `ExternalFlow` already proves the same account/date/
currency boundary and the withdrawal row's own explicit
gross/tax/commission/net arithmetic deterministically reconciles to that
boundary. A standalone tax/commission row is never attached to a withdrawal
by account/date/currency: the current persisted evidence has no
transaction-specific identity for that association, so the reconciliation
remains ambiguous and blocks. The legacy row is never reclassified and no
gross/net field is guessed as the boundary amount. A legacy deposit, an
ambiguous match, or malformed arithmetic still blocks with
`not_computable_external_flows_incomplete`.

Internal tax and commission rows are cost evidence only. They do not create an
`ExternalFlow`. A standalone cost remains internal cost but cannot reconcile a
withdrawal without transaction-specific identity. Embedded cost fields in one
withdrawal row may corroborate its canonical boundary; the existing canonical
boundary remains the only XIRR/TWRR input. A realised coupon/dividend outside
brokerage cash likewise requires an explicit same-account/date/currency
external withdrawal whose boundary equals the validated actual receipt. Its
income row is corroboration and is not injected into return math; missing or
ambiguous holding provenance remains fail-closed.

Expected cash flows and provider payout calendar rows do not become realised
performance flows. Without one valid actual income event for the same
account/holding/kind/settlement date, the affected interval remains
`not_computable_external_flows_incomplete`.


<a id="c7-r08-01c-performance-availability-12-xirr-and-twrr-prerequisites"></a>
#### XIRR and TWRR prerequisites

XIRR prerequisites require trusted opening and closing valuations, complete
historical membership, complete dated external-flow evidence, no unresolved
transfer identity and complete conversion into the performance currency.
Interior date-only ordering is not an XIRR blocker. A start/end-date external
flow requires known inclusion in the consumed valuation; otherwise XIRR is NULL
with `not_computable_valuation_boundary_order_unknown`. A current, exact, complete,
same-scope/currency/date PRE or POST observation must match the consumed endpoint
value unambiguously. One side suffices. Opening POST and closing PRE flows are
excluded from the investor schedule; opening PRE and closing POST flows are
included once. Interior dates do not require TWRR PRE/POST observations.

Exact TWRR additionally requires an explicit observed valuation boundary around
every external flow. R08-03A persists an observed point with an exact
performance-currency value, complete coverage, provenance and quality, and
relates it explicitly to one flow or same-date flow group as
`pre_external_flow` or `post_external_flow`. Each side's `observed_date` must
equal the flow or group boundary date. The read-only response exposes both
sides under `external_flow_boundaries`; a boundary is available only when both
sides are present, exact, complete and in the requested performance currency.

An interior flow without an observed boundary is
`not_computable_valuation_boundary_missing`; an otherwise available same-day
observation without an explicit relation, or multiple ungrouped same-day
flows, is `not_computable_valuation_boundary_order_unknown`. No interpolation,
timestamp-only ordering assumption or start/end-of-day convention is exact.


<a id="c7-r08-01c-performance-availability-12-stable-reason-codes"></a>
#### Stable reason codes

The contract preserves the accepted codes:

```text
not_computable_opening_valuation_missing
not_computable_closing_valuation_missing
not_computable_external_flows_incomplete
not_computable_scope_coverage_incomplete
not_computable_scope_cash_unclassified
not_computable_scope_membership_history_missing
not_computable_currency_conversion_incomplete
not_computable_transfer_identity_unresolved
not_computable_valuation_boundary_missing
not_computable_valuation_boundary_order_unknown
```

Existing valuation-point diagnostics such as
`not_computable_reporting_month_not_closed`,
`not_computable_snapshot_date_missing` and
`not_computable_unsupported_position_valuation` may accompany these codes.

<a id="c7-r08-02-portfolio-xirr-8"></a>
### Annualized whole-portfolio/account XIRR

<a id="c7-r08-02-portfolio-xirr-8-read-only-api"></a>
#### Read-only API

```text
GET /api/performance/xirr
    ?start_date=YYYY-MM-DD
    &end_date=YYYY-MM-DD
    [&scope=portfolio|account]
    [&account_id=<id>]
```

`start_date` and `end_date` are the exact persisted valuation dates used by
R08-01C, and the start must precede the end.

`scope` is `portfolio` (the default) or `account`.  Portfolio scope rejects an
`account_id`; account scope requires an explicit `account_id`, and any other
combination is a validation error.  Account scope was added for #146 and is
called as:

```text
GET /api/performance/xirr
    ?start_date=YYYY-MM-DD
    &end_date=YYYY-MM-DD
    &scope=account
    &account_id=<id>
```

The response contains:

- `value`: an exact decimal string in annualized percentage points, or `null`;
- `value_unit: "percentage_points"` and `annualized: true`, so the UI does
  not need to infer or calculate the presentation unit;
- `scope` and the `account_id` it describes (`null` at portfolio scope);
- `period` with the requested boundary dates;
- `availability`, `quality`, and stable `reason_codes`.


<a id="c7-r08-02-portfolio-xirr-8-cash-flow-convention"></a>
#### Cash-flow convention

The backend builds one investor-perspective series from authoritative R08-01C
evidence:

- opening valuation is negative;
- external contribution is negative;
- external withdrawal is positive;
- an in-scope portfolio transfer is omitted;
- closing valuation is positive.

Account scope reuses the same translation and solver.  Opening and closing
valuations are the requested account's own boundary points, and each flow is
classified for that account: a contribution to the account is negative and a
withdrawal from it is positive.  A fully linked transfer between two in-scope
accounts remains `INTERNAL_TRANSFER` at portfolio scope, but is a withdrawal
for the source account and a contribution for the destination account.  A flow
belonging to any other account is `NOT_IN_SCOPE` and never enters the series.

All amounts remain integer RUB kopecks until the Decimal solver.  No capital
delta, legacy deposit/withdrawal row, expected event, provider payout, or
unresolved transfer is injected or reclassified.


<a id="c7-r08-02-portfolio-xirr-8-account-scope-146"></a>
#### Account scope (#146)

Account scope extends the accepted R08-02 pipeline instead of adding a second
one.  It consumes `performance_availability_for_interval(scope=account,
account_id=...)`, the accepted external-flow classification and the same XIRR
solver.  When an input is missing or ambiguous the result stays
`NOT_COMPUTABLE` with the existing fail-closed reason codes: no flow,
valuation, membership or in-kind fact is inferred, approximated or backfilled.
Portfolio scope semantics and reason codes are unchanged.


<a id="c7-r08-02-portfolio-xirr-8-fail-closed-calculation"></a>
#### Fail-closed calculation


<a id="c7-r08-02-portfolio-xirr-8-historical-source-bridge-734"></a>
#### Historical source bridge (#734)

When month-owned XIRR prerequisites are available, the existing path takes
precedence unchanged. Otherwise the same route and `xirr_for_interval` can consume
effective H1/H2 evidence. Both boundaries must be accepted exact account/date EOD
RUB endpoints; a source boundary is never mixed with a month-owned boundary.
Portfolio totals sum both endpoints for every historically included account,
using the existing gap-free dated membership and membership-transition gates.
Current account inclusion flags cannot supply that universe.

Each required account needs effective H2-A2 COMPLETE coverage for the exact
`[start_date + 1 day, end_date]` window, bound to the compatible H2-A1 ledger.
The shared COMPLETE assessor accepts a gap-free, nonoverlapping union of adjacent
effective source-aware rows; it does not require one row for the whole window.
Gaps, UNKNOWN/retired rows, overlaps and source-free assertions remain refusals.
The existing in-kind and currency gates remain affirmative. Each effective H2-A1
event with `start_date < event_date <= end_date` enters once with the same investor
sign convention. Portfolio events additionally require effective H2-B1 EXTERNAL
authority; explicit NOT_IN_SCOPE adds no amount. Unknown authority or suspected
tracked-account transfers block. Existing portfolio transit safety also applies
at the requested boundaries. No pairing or netting is introduced.

The complete read uses one committed snapshot. Every read revalidates the frozen
endpoint, flow, coverage and portfolio authority through their existing lifecycle
readers. Retired, revoked or invalidated evidence remains unavailable after old
amounts are restored. Evidence refusal precedes solver execution; an eligible
series uses the unchanged solver and retains its numerical reason codes.

No intermediate month-end, ReportingMonth creation, ledger/schema change or
financial write is required. The month-owned availability API, class returns and
TWRR keep their existing evidence requirements; H3 does not promote them.
The existing readiness projection presents final H3 XIRR independently of legacy
monthly availability/TWRR. Ineffective historical endpoints, ineffective account
flows and unknown portfolio-flow authority have specific source-required
diagnostics, with no supported in-page repair action implied.


<a id="c7-r08-02-portfolio-xirr-8-numerical-limitations"></a>
#### Numerical limitations

The solver uses the date-only XIRR equation with a 365-day year and a
deterministic bracketed Decimal search in an isolated local context. The log-rate
bracket expands when the initial scan misses a certified unique root; numerical
search exhaustion or an unrepresentable rate reports convergence failure, not
proof of no root. Before accepting a visible bracket,
it applies an exact sign-variation certificate: with
`z = (1 + rate) ** (1 / 365)`, the equation is a polynomial in positive `z`.
Histories with more than one coefficient sign change cannot prove a unique
positive root and remain unavailable.  A value is returned only when this
certificate permits at most one root and that root converges.  Otherwise the
response is unavailable with one of:

```text
not_computable_xirr_no_valid_root
not_computable_xirr_convergence_failed
not_computable_xirr_root_ambiguity
```

Interior same-day ordering remains TWRR-specific; endpoint-flow inclusion follows
the [XIRR prerequisites](#c7-r08-01c-performance-availability-12-xirr-and-twrr-prerequisites).

<a id="c7-r08-03-twrr-contract-recon-32"></a>
### Exact period TWRR mathematics

<a id="c7-r08-03-twrr-contract-recon-32-exact-twrr-availability-rule"></a>
#### Exact TWRR availability rule

For either `portfolio` or an explicit `account`, exact TWRR may be calculated only if all of the following hold:

1. The requested opening and closing dates resolve to exactly one closed, trusted valuation point each.
2. Every required selected-scope component is authoritative in the performance currency, including historical scope membership and performance cash classification.
3. External-flow coverage is complete: explicit boundary amounts are valid, relevant flow membership is authoritative, transfers are resolved when applicable, and conversion is complete.
4. There are no selected-scope external contribution/withdrawal boundaries requiring an unobserved or unordered split. At portfolio scope, a fully linked transfer between two in-scope accounts is internal and does not violate this condition.

With no selected-scope external boundary flow, the calculator uses the single exact factor:

```text
TWRR = closing_value / opening_value - 1
```

The factor can be `0` for a flat period or negative for a loss period. Those outcomes are not `not_computable` by themselves. The delivered read-only TWRR API exposes the period percentage only when the metric-specific evidence and numerical guards pass.

When external flows are supported by the prerequisite, the calculator must order explicit flow groups and use an observed valuation immediately before and immediately after each group. Contributions use positive boundary amount from the portfolio perspective; withdrawals use the same non-negative amount with withdrawal direction. The chained subperiod factors must use those observed boundaries and must not interpolate, assume start/end-of-day order, or turn a capital delta into return.

The following independent reference vector fixes the accepted segmentation:

| Boundary | Observed value (RUB) | Signed boundary flow (RUB) | Factor |
| --- | ---: | ---: | ---: |
| Opening | 1,000.00 | — | — |
| Before contribution 1 | 1,100.00 | — | `1,100 / 1,000 = 1.10` |
| After contribution 1 | 1,200.00 | `+100.00` | `1,200 / (1,100 + 100) = 1.00` |
| Before withdrawal 2 | 1,320.00 | — | `1,320 / 1,200 = 1.10` |
| After withdrawal 2 | 1,270.00 | `-50.00` | `1,270 / (1,320 - 50) = 1.00` |
| Closing | 1,333.50 | — | `1,333.50 / 1,270 = 1.05` |

The chained factor is `1.10 × 1.00 × 1.10 × 1.00 × 1.05 = 1.2705`, so the reference TWRR is `27.05%`. Accepted observed PRE/POST capture can record the required flow-adjacent observations and relations; exact availability still depends on those observations being present and current.


<a id="c7-r08-03-twrr-contract-recon-32-fail-closed-rules"></a>
#### Fail-closed rules

The following are `not_computable` for TWRR. Existing R08-01C reasons propagate to TWRR unless explicitly noted:

| Situation | TWRR reason | XIRR distinction |
| --- | --- | --- |
| Opening or closing point missing | `not_computable_opening_valuation_missing` or `not_computable_closing_valuation_missing` | Blocks both metrics. |
| Selected month is draft, has no snapshot date, or contains an invalid persisted valuation | `not_computable_reporting_month_not_closed`, `not_computable_snapshot_date_missing`, or `not_computable_unsupported_position_valuation` | Blocks both metrics. |
| Missing/unknown selected component, unclassified cash, or incomplete historical membership | `not_computable_scope_coverage_incomplete`, `not_computable_scope_cash_unclassified`, or `not_computable_scope_membership_history_missing` | Blocks both metrics; current account flags cannot repair history. |
| Relevant legacy deposit/withdrawal row | `not_computable_external_flows_incomplete` | Blocks both metrics; no legacy amount is guessed. |
| Unresolved or incomplete transfer identity | `not_computable_transfer_identity_unresolved` | Blocks both metrics for the affected scope. |
| Foreign flow/component without an accepted dated conversion | `not_computable_currency_conversion_incomplete` | Blocks both metrics. |
| Interior external flow has no trusted observed valuation on its date | `not_computable_valuation_boundary_missing` | XIRR may remain available when its own evidence is complete. |
| A date-only valuation exists on the flow date but no explicit pre/post-flow relation proves order | `not_computable_valuation_boundary_order_unknown` | Interior XIRR may remain available; start/end flow inclusion must be known. |
| More than one external flow | Every flow/group must satisfy the boundary rule; one missing or unordered boundary blocks the whole TWRR interval. | XIRR still needs only complete dated flow evidence. |
| Fully linked in-scope transfer at portfolio scope | No TWRR boundary reason from that transfer. | It is internal at portfolio scope, but external at each affected account scope. |
| Flat or negative return with otherwise valid evidence | No availability failure solely for a zero or negative return. | The numerical implementation preserves the value rather than downgrade it. |

`not_computable` means unavailable, never zero and never a silently downgraded approximate result.

<a id="c7-broker_statement_return-7"></a>
### Indicative statement MWR: inputs, units and solver

<a id="c7-broker_statement_return-7-frozen-interface"></a>
#### Frozen interface

`BrokerStatementReturn` uses `method=broker_statement_mwr_period_v1`, `scope=account`,
actual `account_id`, `t0`/`t1` EOD dates, `currency=RUB`, `annualized=false`,
`status=quality=indicative|unavailable`, and `rate_fraction` as a Decimal string or
null. Fraction `0.0201` means **2.01% over the actual period**. Money in the JSON
DTO is a signed integer kopeck **string**, preserving values beyond JavaScript's
safe integer range. Unknown money stays null.

Both endpoints disclose each native position's ISIN, instrument identity,
actual quantity, native value and source ordinal, the position sum, **separate**
RUB cash and total. Source provenance includes original hash, parser identity,
source signature, source-month request and confirmation digest. The response
discloses effective crossing IDs, dates, signs, revisions and material signatures,
cash coverage state/revision, membership, exposure, NKD basis and reason codes.
The material fingerprint binds current source, receipt, dependencies and evidence.

<a id="c7-broker_statement_return-182"></a>
### Statement return endpoints, independent coverage and period conversion

<a id="c7-broker_statement_return-182-inputs-and-availability"></a>
#### Inputs and availability

The valuation adapter reads the unchanged original-bound S1 document linked to
the existing BrokerMonthApply source receipt. `t0=covered_from-1 day` follows the
accepted `previous_day_eod` legend; `t1=covered_to` follows `covered_to_eod`.
Both source endpoints are used together; no monthly/historical valuation fallback.
Source hash/parser/range, account aliases, instrument types/currency, source-owned
projection, current dependencies, endpoint completeness, cash/quantity controls
and competing overlapping reports are rechecked. Untrusted changed source values
are not exposed as accepted facts.

Crossings come only from effective existing HistoricalOwnerFlow revisions, with
independently accepted, currently effective source CashBoundaryCoverage for the
exact `(t0,t1]` interval. The coverage reader rechecks its whole source inventory,
enumerated flow IDs, membership and revision binding. An empty ExternalFlow table,
an incomplete DRAFT or `include_in_returns=false` proves no zero-crossing schedule.
Positive crossings enter this **account**; portfolio externality is not inferred.
No new H2 acceptance or source classification is performed here.

H2-A2 still rejects unrelated legacy cash, transfers, unproved payouts and
unresolved Money inventories. This adapter preserves those
unavailable results; it does not invent a compatible broader coverage contract.
It also blocks competing sources and unassessed REPO/pending/Transfers/UFSR
exposure, including diagnostic-only wrapper evidence. Structural disposition
does not establish absence of financial impact.

Known source valuation facts remain visible when only flow/coverage/exposure
proof is missing. All availability reasons remain machine-readable. Bond NKD
UNKNOWN can permit **indicative** when every other gate passes, with the exact
warning **"По оценке брокера; учёт НКД в стоимости облигаций не подтверждён"**.
There is no invented zero NKD, tax, cost or error interval.


<a id="c7-broker_statement_return-182-mathematics-and-isolation"></a>
#### Mathematics and isolation

Investor vector: `-V0@t0`, `-Ei@(t0,t1]`, `+V1@t1`. Coupon, dividends, posted
fees, settlement and summaries already reflected in cash are not extra investor
flows. Only the existing Decimal/ACT365 `calculate_xirr` numerical kernel is
reused. Convert its internal annualized root to
`R=(1+r)^((t1-t0).days/365)-1` at Decimal precision 60. Ambiguity, no-root and
convergence failures remain null with reasons. Solver quality never grants exact
financial authority to this DTO.

Synthetic tests cover midpoint 2.01%, contribution/withdrawal 0%, internal net
coupon/fee 2.8%, negative return, independently compounded residual below 0.01
RUB and absolute fraction error at most 1e-8, root guards, missing coverage,
source/membership/date/projection changes, overlap, percent units, stale account
responses, preview/export parity and no database writes. Existing exact
XIRR/TWRR/class readers and guards are unchanged. Real September percentage and
Owner financial/UAT acceptance require their separately authorized evidence.

<a id="c7-broker_statement_what_if-11"></a>
### Bounded hypothetical account-period return

<a id="c7-broker_statement_what_if-11-scope-and-provenance"></a>
#### Scope and provenance

One accepted unchanged XML, one RUB brokerage account, its exact native `(t0,t1]`.
The new service composes unchanged S3, Money-candidate, H2-A2 inventory (current
contract), permanent ownership and metadata readers inside one committed read
snapshot. It does not call Preview/Apply, accept or reaffirm evidence, repair
receipts, persist scenarios, request providers, or calculate actual S3 with altered
evidence. Existing S3/H2/Close/exact XIRR/TWRR contracts remain unchanged.

`StatementWhatIfContext` separates verified observed endpoints/capital delta,
untouched `actual_result`, full diagnostic inventory, fixed effective H2 schedule,
zero or one optional native incoming-bank candidate, exact required assumptions,
hard blockers and context fingerprint. Bad provenance does not relabel cached
endpoints as observations. All effective H2 crossings are mandatory and counted
once. Compatible H2/Money ownership of the same target is one event; incompatible,
conflicting or ineffective ownership cannot become an optional candidate.
Coupon and trade dispositions come from the existing H2 inventory.
H2-A2 v4 `accepted_non_owner_paid_nkd` is compatible only with one exact permanent
trade owner and its matching `trade_target_id`; missing ownership is a hard
inventory mismatch. It retains the separate `money_basis` choice and pattern
blockers, without adding an economic row or investor crossing. Legacy v3 unresolved
paid NKD and all other authority/currentness gates retain their existing behavior.

There is no generic outgoing classifier, manual amount/date/endpoint entry, IIS
extension, arbitrary interval, portfolio aggregation, saved scenario or batch mode.
More than one eligible optional incoming candidate or 128 fixed crossings is a
capacity blocker; inventories and schedules are never truncated.


<a id="c7-broker_statement_what_if-11-finite-assumptions"></a>
#### Finite assumptions

The server derives each requirement and its complete reference membership:

1. Model the native account continuously with both native EOD totals, without
   valuation/cost adjustments or a historical portfolio-inclusion assertion.
2. Use all fixed crossings and explicitly include/exclude the optional candidate.
   Excluding a candidate does not delete observed cash. Posting date is the native
   modeled date. `schedule_mode=explicit_empty` is required for an empty selected
   schedule and differs from missing/null; a nonempty schedule requires `dated`.
3. When actual crossing completeness is absent, assume no additional boundary
   crossings in this selected account beyond the displayed schedule.
4. Enumerated recognized unresolved coupon/NKD or S1-linked settlement/commission
   occurrences contribute no extra investor flow or endpoint adjustment in this
   native-total model. Unknown tax/NKD/fee authority is never zeroed or counted again.
5. Each named Transfers/UFSR channel separately has no additional modeled effect
   outside native totals/schedule. Only existing parsed safe patterns or a genuinely
   empty observed tree qualify. A zero row count with opaque attributes/text/comments
   does not qualify. Accepted section authority and economic period coverage remain
   separate; `period_scope=unknown` stays unknown.

No choice is selected automatically. Missing valid choices produce
`needs_assumptions` with both numeric fields null. Duplicate, extra, wrong-reference,
wrong-choice or contradictory schedule selections block. The literal
`SCOPED_REASONS` map is conditional on the complete inspected inventory; every
unknown/new reason defaults to a hard blocker. Source membership, integrity,
mapping/currentness, legacy/transfer overlap, unsupported Money, unmodeled nonempty
REPO/pending/in-kind/custody/opaque exposure and authority conflicts cannot be
bypassed by assumptions. Mathematical failure also returns null for both fields.


<a id="c7-broker_statement_what_if-11-units-and-mathematics"></a>
#### Units and mathematics

Independent strict frozen WHAT-IF types do not inherit actual S3 DTOs.
Result: `kind=broker_statement_what_if_result_v1`,
`method=broker_statement_what_if_mwr_period_v1`, `scope=account`,
`authority=hypothetical`, `currency=RUB`, `annualized=false`,
`status=hypothetical|needs_assumptions|blocked`. There is no scenario `quality`
or actual `rate_fraction` override. Monetary operands and results are canonical
integer-kopeck strings; unknown is null. Diagnostic native monetary lexemes are
converted exactly into named kopeck fields, never rounded; the raw dependency
fingerprint also binds the unmodified reader material. Nonmonetary source fields
(such as native price/quantity) retain their original source units.

The unchanged Decimal XIRR kernel consumes investor flows
`-V0@t0, -Ei@ti, +V1@t1`, `t0 < ti <= t1`; positive `Ei` enters the account.
At precision 60 its internal ACT/365 root is converted to the actual-period
fraction `R=(1+r)^((t1-t0).days/365)-1`. Only that finite fixed-point Decimal
fraction is returned. No root, conservative ambiguity, nonconvergence and
nonfinite guards remain effective. No annualized number or confidence interval
is published.

`scenario_result_kopecks = V1 - V0 - sum(Ei)`, labelled
**«Условный результат после учёта выбранных внешних движений»**.
It is not actual P&L, realized/unrealized profit, taxable income or `V0 * R`.
Display uses retained string/BigInt helpers with HALF_UP and negative-zero handling.

Synthetic 30-day reference: 10,000 RUB + 1,000 RUB on day 15 → 11,211 RUB.
Independent equation: `10,000 × 1.0201 + 1,000 × 1.01 = 11,211`.
Including that candidate gives 211 RUB / 2.01%; excluding it gives 1,211 RUB /
12.11%. These are different scenarios, not bounds on actual performance.


<a id="c7-broker_statement_what_if-11-http-and-desktop-lifecycle"></a>
#### HTTP and desktop lifecycle

All routes are POST multipart under `/api/broker-statement-what-if`:

| Route | Required fields beyond unchanged `file`, `account_id`, accepted `request_id`, `expected_actual_fingerprint` |
| --- | --- |
| `/context` | None |
| `/evaluate` | JSON `assumptions`, `expected_context_fingerprint` |
| `/export` | Same plus `expected_result_fingerprint` |

All responses, including handled validation errors, use `Cache-Control: no-store`.
Query parameters, unexpected/duplicate form fields, endpoint overrides and invalid
strict assumptions are 422. Missing source identity is 404. Context/actual/result
staleness is a typed 409 without a number or attachment. Export re-reads and
recomputes the same full result DTO; it is never a rate-only or persisted token.
Body/XML/financial values are not included in error logs or exception diagnostics.

Context binds source/parser/scope/version, actual fingerprint, complete Money and
H2 dependency inventory including absences, permanent ownership, metadata and
relevant coupon/Money/section/flow material. Assumptions are separately canonicalized
and hashed; result binds both plus full provenance and schedule.

The panel lives below the existing S3 result on `/v2/capital/statement-return`.
Actual availability/reasons stay visible with the scenario. Native facts, accepted
H2, optional candidate, per-channel choices, selected assumptions and actual
limitations remain distinct. Full member references and diagnostic inventory expand.
Original bytes and selections exist only in page memory. Changing original,
account/source, assumptions, refreshing, errors or response mismatch hides the
old result and disables export. Generation/abort guards reject late responses,
including A→B→A source changes. Download requires fresh bound server validation.

<a id="c7-source_monthly_returns-1"></a>
### Monthly native-source estimates

The read-only `source_monthly_returns` service and
`GET /api/source-returns/monthly?source_account=...` assemble one native source
account from verified saved source-intake journals. Each calendar month retains
its own opening and closing native EOD position-plus-separate-RUB-cash totals.
A different previous closing total is disclosed as `seam_mismatch`; neither
operand is replaced. Missing endpoints remain NULL with `missing_endpoint`,
and an invalid month does not suppress independent valid months. Long reports
supply only their actual outer EOD boundaries, never intermediate month ends.
Reports starting or ending inside a month remain in the calendar and dated-flow
schedule with `partial_month_source`. Their partial endpoints cannot stand in
for calendar-month boundaries; without another source those boundaries remain
NULL. Interior full months retain dated flows and missing EOD independently.

The separate approximate monthly Modified Dietz/period kernel is
`calculate_monthly_return_chain`. Period growth and XIRR use the outer endpoints
and one dated schedule; the approximate chained return uses each month’s own
monthly estimate. A missing monthly endpoint withholds the chain while independently
known outer-period growth/XIRR may remain available when statements continuously
cover the dated flow interval. Period flow coverage uses the union of statement date
ranges within the actual outer statement dates, independently of valuation availability.
Partial calendar-edge months remain incomplete without nulling known period flow totals;
a gap inside the reported interval makes affected contributions,
withdrawals, growth and XIRR NULL with `flow_coverage_gap` and `unknown_flow`.
Independent covered segments remain available. Any Modified Dietz factor `1+r<0`
withholds the geometric chain with `negative_dietz_factor`, preserving the monthly
estimate and known growth; a factor exactly zero remains allowed. Rates are Decimal fraction
strings and money is integer kopecks in this endpoint. Results are
`authority=provisional`, `financial_authority=none`, `approximate=true` and grant
no financial Apply, Close, source completeness or exact TWRR authority. Without
two boundaries, flow totals remain NULL with `insufficient_boundaries`; no
source-backed interval is established.

Owner decision (2026-10-20, #912): capture provisional Money classification at
upload. Migration `0060_source_money_classifications` adds the empty
`source_intake_money_classifications` table, linked to the original intake and
immutable observation, unique by intake/stable source reference and observation.
It stores source date, signed integer kopecks, currency, native operation/narrative,
classification, origin/status and created/updated timestamps. Captured operation
and narrative text are capped at 256 and 4096 characters respectively; overlong
text retains a prefix plus its full-text digest so different long rows remain
distinct during overlap deduplication. Classification uses the original text.
Fractional-kopeck or
overflow amounts remain NULL and produce gaps. There is no legacy inference or
backfill. Downgrade drops this table, including populated provisional choices,
while preserving the pre-existing journal and financial tables; upgrade can be
reapplied. Released migration bytes remain unchanged.

Save captures every Money occurrence in the same reserved transaction as its
observations. Deterministic rules reuse the existing original-bound money candidate
patterns: client/bank deposits and withdrawals are external, coupons/dividends are
income, commissions/tariffs are fees, НДФЛ is tax, settlements/НКД по сделке are
trade settlement. Explicit withdrawal/deposit/transfer semantics take precedence
over generic coupon/dividend words. Refined НКД по сделке names remain settlement;
unrecognized НКД variants are unknown rather than coupon income. Everything else
is unknown, never a guessed flow. Defaults have
`origin=default_rule,status=assumed`. Re-upload never duplicates occurrences or
replaces an existing classification. Exact original re-save with a new request ID
can capture missing legacy rows; acknowledged same-request replay stays read-only.
A changed Money extraction count refuses with
`source_intake_parser_revision_changed` before capturing any classifications.

`GET /api/broker-months/intakes/{id}` includes `money_classifications` with stable
references and bounded text. The intake listing omits this field.
`PUT /api/source-intakes/{id}/money-classifications/{ref}` accepts only
`{classification}` from `external_deposit, external_withdrawal, coupon, dividend,
fee, tax, trade_settlement, internal_transfer, unknown`. It reserves the writer,
validates intake/reference and any bound draft month, and persists
`origin=user_choice,status=confirmed`; repeated identical PUT is idempotent.
Invalid external-flow currency/amount/direction refuses. Bound CLOSED months
require Reopen. These choices change only provisional interpretation, never
financial receipts, recognized observations or Close authority.

Monthly GET reads saved classifications without reattaching originals. External
deposits/withdrawals enter the schedule with their persisted status;
`coupons_kopecks` and `dividends_kopecks` report the classified RUB income subtotal
per month, without adding it again as investor flow. The monthly
`income_assumptions_used` flag is true when any included coupon/dividend uses
an assumed default; return-schedule `assumptions_used` remains separate.
Non-RUB Money rows are excluded from RUB income and flows and make the month’s
flows unknown. Affected month, period and containing segment contributions,
withdrawals, growth and rates remain NULL with `currency_unsupported` and
`unknown_flow`; independent RUB-only months remain available. Unknown RUB money
stays in
`unrecognized_money` gaps and withholds flow-dependent metrics with `unknown_flow`.
Missing classifications on pre-migration intakes produce
`classification_missing_legacy_intake`; reads never backfill or interpret missing
rows as zero. An unreadable or native-scope-ambiguous original marks every
month it covers as having unknown flows: affected month, period and segment
contributions/withdrawals, growth and rates remain NULL with `unknown_flow`.
Financial parser blockers (`unparsed_source_rows`, `unknown_section`, unsupported
Transfers/UFSR and unclassified position rows) likewise mark the document’s covered
months and containing totals as unknown, retaining each explicit blocker code.
Non-financial statuses do not block returns; neighbouring complete documents stay
independently usable.
Currency checks in these source-return readers and shared Money validation normalize
case and surrounding whitespace; legacy `RUR` is the same ruble currency as `RUB`,
including persisted classification comparisons and overlap signatures. Native saved
source facts/fingerprints are not rewritten. Independent complete months remain
available. Income totals are NULL when statement date coverage for the month is
incomplete, retaining `flow_coverage_gap`; a covered quiet month may report zero.
With complete date coverage, classified income subtotals remain partial when
interpretation gaps exist. Python callers may
still verify exact originals through the provisional context reader and supply
source-bound transient choices for default external rows; a persisted user choice
always takes precedence. Overlap deduplication preserves references and same-report
multiplicity, prefers confirmed choices, and discloses conflicting choices.
Missing monthly boundaries split `segments` into contiguous available month groups
with each group's own endpoints, flows and partial chained return/XIRR/growth.
When a continuous long report supplies only the outer endpoints and no complete
monthly group exists, it retains one `partial_segment` with the outer-period
totals; its monthly chain remains unavailable.

<a id="c7-source_instrument_returns-1"></a>
### Monthly native-source instrument estimates

The separate read-only service `source_instrument_returns` and
`GET /api/source-returns/instruments?source_account=...` group verified saved
intakes by native account and ISIN. This is a provisional source interpretation,
with `authority=provisional` and `financial_authority=none`, including for unbound
intakes. It needs no original reattachment, metadata creation, financial Apply,
receipt, migration or Close change. It does not replace the accepted instrument
payout, execution or EOD readers.

Each monthly row retains the statement's own opening/closing quantity and native
EOD valuation. A missing quantity or value stays NULL independently; an absent
position is never affirmative zero. A long report supplies only its actual outer
boundaries. Overlapping copies must agree on each endpoint. Native settled trades
are counted in their settlement month, once per ordered two-part native identity.
One-part or absent identity is `trade_identity_unresolved`: withhold the affected
buys/sells/total, including across overlapping reports; never deduplicate by intake ID.
Let T be native `summ_trade`, N the native NKD and F commission. With an
`includes_paid_nkd` basis, buys cost = T + F and sells proceeds = T - F;
with `excludes_paid_nkd`, buys cost = T + N + F and sells proceeds = T + N - F.
These are the C5 native-total basis meanings. For buys, a current accepted cash proof
matching the native identity, IDs and exact trade components takes precedence,
revalidated through the existing proof reader and cash checks. A malformed proof
envelope (including missing/invalid `claims`, `source_identity`, `native_ids`,
`signed_minor` or `nkd_leg` fields) is invalid and contributes no basis: use unique
inference or withhold with `trade_nkd_basis_unknown`. These cash checks validate
buys only; sells rely on per-row inference or remain withheld.
For MyBroker bond buys and sells,
the provisional reader also infers a basis per row from parsed `Price` (percent
of face), signed `qty` and face value D in settlement-currency units per security:
let P = Price / 100 * D * |qty|. Use the explicit positive trade-row face when
present. When the trade-row face is absent or empty, provisionally assume D = 1000
and apply the same exact-one-reading test below. The optional row attributes
`face_value`, `nominal` and `nominal_value` (also their `2`-suffixed variants
on pending rows) are normalized as `face_value` on parsed trade/position rows.
Only a trade-row value supplies a dated nominal for inference. Position-row
nominal has no proven validity interval and may describe a post-amortization face;
it is not applied to trades, even for the same account/ISIN and statement.
Conflicting trade aliases and explicit invalid/nonpositive values leave inference
unknown and never fall back to 1000; position evidence cannot fill that gap.
Contradictory nominal evidence across settled overlapping trade copies is
`overlapping_trade_conflict` and withholds affected costs. There is no derivation
of face from T or substitution of current instrument database metadata for
historical source evidence. Explicit 500, 100 and other faces remain supported.
An absent-face amortized trade whose amounts do not uniquely fit assumed 1000
stays unknown; the reader does not search for another face.
With Decimal arithmetic and the unchanged per-row 0.01 tolerance,
|T - P - N| <= 0.01 implies
`includes_paid_nkd`; |T - P| <= 0.01 with N != 0 implies `excludes_paid_nkd`.
Both or neither matching leaves inference unknown. Optional nominal keys are omitted
when no supported attribute exists, preserving normalized payloads for those legacy
rows. Previously saved intakes are read as frozen facts: exact-original reattachment
reproduces their saved nominal-key presence under the C3 compatibility rule; opaque
attribute fingerprints are not promoted to nominal evidence. An unknown inference
preserves a valid reviewed proof; a decidable inference conflicting with that proof makes the basis
unknown and adds `trade_nkd_basis_conflict`, including when inference used assumed
1000. Only an accepted basis supplied by assumed-face inference adds
`face_value_assumed` to that instrument-month; a reviewed basis retains precedence
and does not acquire the assumption flag. Without a valid proof or a unique
inference, `trade_nkd_basis_unknown` withholds affected buys/sells/price effect/
total/rate; bond EOD approximation does not waive this. This arithmetic inference
is limited to the provisional reader and creates no accepted proof or attestation.
Missing commission or bond NKD is unknown; omitted stock NKD is inapplicable zero.
Pending or missing settlement produces `trade_missing_settlement`,
including both the execution and planned settlement months for pending trades.
Contradictory trade observations, REPO or non-RUB trades withhold affected costs.
Trade and income currency checks treat trimmed, case-insensitive `RUR` as `RUB`.

Monthly `price_effect_kopecks` = V1 - V0 - buys_cost_kopecks + sells_proceeds_kopecks;
`income_kopecks` is classified coupons + dividends; `total_kopecks` is price effect +
income. `capital_base_kopecks` = V0 + buys_cost_kopecks. `return_percent` is the
Decimal percentage string 100 * total / capital base, NULL for nonpositive base
or unavailable operands. Money is integer kopecks; quantities are Decimal strings.
These are simple monthly estimates, not XIRR or TWRR. Bonds use reported values
without resolving clean/dirty or accrued-interest basis: `approximate=true` and
`bond_valuation_basis_unknown` disclose this without blocking numbers. Stocks have
`approximate=false` when no gaps or assumed income exist. Assumed income makes both
the month and all-time row approximate, while confirmed income alone does not.
`face_value_assumed` is also a disclosure: it makes the month and all-time row
approximate without by itself making all-time coverage partial. In general, any
monthly flag except `income_confirmed` sets `approximate=true`.
This grants no financial authority.

Persisted coupon/dividend classifications supply signed income amounts and their
assumed/confirmed status. Whole ISIN or explicit saved registration aliases take
precedence over whole saved names; a missing or ambiguous match stays in the income
list with `isin=NULL` and an `unattributed_income` gap/reference. Registration aliases
are usable only if actually present in saved identity evidence; the reader does
not reconstruct metadata discarded by the existing parser or infer a registration
crosswalk. Overlap handling reuses the monthly Money validation/deduplication rules,
keeps same-report multiplicity and prefers confirmed choices.

The service's per-instrument monthly `income_complete` is true exactly when at least
one usable intake covers the entire calendar month and that instrument/month has
neither an income gap nor a source-structure gap. Income gaps are
`unattributed_income`, `currency_unsupported`,
`classification_missing_legacy_intake`, `invalid_money_row`,
`invalid_external_flow`, `unrecognized_money` and `overlap_flow_choice_conflict`;
the source-gap codes are listed below. Otherwise it is false, including a missing
month or unreadable overlapping source even when another intake is readable.
An account-level gap with no ISIN applies to every instrument in that month;
an instrument-specific gap applies only to that instrument. This is completeness
of the provisional saved-source income interpretation, not proof of all historical
payouts, accepted financial coverage or readiness for Close.

Assumed coupon/dividend classifications may satisfy completeness. They set
`income_assumptions_used=true` and `income_assumed`/`approximate=true` only on
instruments/months with an attributed assumed payout; confirmed income alone does
not. Thus `income_complete=true` does not mean confirmed income or an exact return.
Missing endpoints, trade NKD/nominal/currency/REPO gaps, seam mismatches and bond
valuation approximation do not by themselves make income incomplete, although
they can withhold price effect, total or rate.

Every income field (`coupons_kopecks`, `dividends_kopecks`,
`assumed_income_kopecks`, `confirmed_income_kopecks`, `income_kopecks`) is nullable.
With complete coverage, no matching observations means affirmative zero. With
incomplete coverage, retain a signed observed subtotal if at least one matching
observation exists (including an observed zero or cancelling sum); otherwise NULL.
A numeric income subtotal therefore does not imply completeness. Incomplete income
always withholds monthly `total_kopecks` and `return_percent`, while known price
components remain available unless independently blocked.

For each instrument, all-time `income_complete` is the logical AND of all its
emitted monthly values over the account's saved-source span, including missing and
partial months. All-time `income_assumptions_used` is their logical OR. Each all-time
income field sums every non-NULL monthly component independently and is NULL only
if no month supplies a value. A complete empty month can therefore supply zero
even when another month's income is NULL and all-time completeness is false.
All-time `total_kopecks` still sums only available monthly totals; it can be numeric
with `income_complete=false`. Conversely complete income can coexist with a partial
all-time return because of trade/valuation gaps.

The instrument API exposes the same flags as JSON booleans at
`instruments[].months[].income_complete` and
`instruments[].all_time.income_complete`, and preserves income NULL versus integer
zero/subtotal exactly. Neither the response root nor individual `income[]` events
has an aggregate `income_complete` field. An unknown account/no saved instrument
identities returns an empty instrument list, not an invented complete zero result.

Unknown source structure, scope ambiguity
or an unreadable overlapping intake withholds affected costs/income completeness.
The explicit structure-gap codes `source_reader_unavailable`,
`native_source_scope_ambiguous`, `unparsed_source_rows`, `unknown_section`,
`4_Transfers_unsupported`, `5_UFSR_unsupported` and `position_row_unclassified`
are month-local source gaps: preserve their flags, withhold costs and total,
and set `income_complete=false`. Money `currency_unsupported` affects income
completeness and totals, preserving known price components. Trade
`trade_currency_unsupported` and `repo_trade_unsupported` withhold affected costs
and price effects without making covered income incomplete. Instrument-specific
missing endpoint components remain local to that instrument/operand.
Independent instruments and months remain available where evidence permits.

`seam_mismatch` discloses differing consecutive native opening/closing values or
quantities, and within-month quantity movements unexplained by the observed trades;
it never replaces native operands. All-time monetary fields sum available component
values, and `total_kopecks` sums only months with an available total. Thus all-time
total need not equal its independently available price-effect plus income subtotals.
`available_months` lists numeric monthly totals; `missing_months` lists months with
no usable whole-month source coverage; `partial_months` lists covered months whose
total is withheld. These lists, `partial`, `income_complete` and flags disclose
incomplete sums; a covered income gap does not invent a `missing_month` flag.
Missing coverage is `missing_month` and stays NULL in monthly rows, never zero.
All-time capital base and percentage remain NULL: this scope defines monetary sums,
not a holding-period or chained instrument rate. GET is no-store and performs no
classification backfill, receipt or economic writes.

<a id="c7-broker_statement_provisional-12"></a>
### Source-intake provisional account estimate

Read-only artifact for the bounded [2026-10-18 Owner decision](https://github.com/LTstripes/hermes-finance/issues/839#issuecomment-6253883555):
one deliberately provisional RUB period estimate from a saved durable source-intake
journal and its exact unchanged original, without a financial `SOURCE` receipt,
`Apply`, accepted H2 evidence, Close or a stored scenario. It is `authority=provisional`
and `financial_authority=none`; it never replaces actual S3, exact XIRR/TWRR or Close.

<a id="c7-broker_statement_provisional-12-scope"></a>
#### Scope and provenance

The route verifies the journal's exact original SHA-256, byte length, filename digest
and manifest, then reproduces the recorded MyBroker grammar (native linkage or the
frozen legacy grammar) from the uploaded bytes. A parser or original mismatch refuses
rather than reinterpreting saved observations. Two scopes exist:

- **`scope=account`** — the previously accepted bound path: the journal has one bound
  Hermes account, all source aliases resolve to it under the existing effective
  mapping/currentness rules, and `account_id` is that Hermes account.
- **`scope=native_source`** — the journal is intentionally unbound (`account_id` and
  `reporting_month_id` are `null`, as in the accepted #769 source-only history) and no
  accepted financial binding exists. The scope identity comes from the statement rows:
  exactly one distinct native `acc_code` across every recognized position, RUB cash row,
  Money row and every completed/pending/REPO trade (`trade.core.source_account` in the
  frozen S1 shape) is required; the filename account is only a source label and is
  never treated as a signed identity. Multiple row aliases, an unproven alias, an
  ambiguous scope or invalid endpoints produce a typed blocked context with the safely
  observed per-row facts; they never mix accounts or relabel the filename. The response
  carries `account_id=null`, `native_source_account`, `financial_authority=none` and a
  visible provenance limitation. No Account, Instrument, ReportingMonth, mapping,
  H2/Money acceptance or S1 receipt is created or changed by the estimate.

<a id="c7-broker_statement_provisional-12-observed"></a>
#### Observed layer and endpoint eligibility

The observed operands are the broker-reported native EOD values of every recognized
security plus the single separate RUB currency row: `V0 = sum(position.beginning_value)
+ rub_money.beginning_amount`, `V1 = sum(position.ending_value)
+ rub_money.ending_amount`, `t0 = covered_from - 1 day`, `t1 = covered_to`.
`V1 - V0` is shown as the broker-reported value change, never as return, P&L or taxable
income. Values must convert exactly to integer kopecks and be non-negative; exactly one
RUB row with both amounts is required; unclassified Positions rows, endpoint conflicts,
quantity/value conflicts and every other unproven endpoint diagnostic withhold the
totals and the return. A missing beginning quantity is disclosed as a limitation but
does not invalidate a present beginning value. Cash is counted exactly once; the
per-security values and the separate RUB row are never double-counted.

<a id="c7-broker_statement_provisional-12-assumptions"></a>
#### Finite assumptions

No choice is selected automatically; missing valid choices produce
`needs_assumptions` with both numeric fields null. The server derives the complete
requirement set and exact source-reference membership:

1. **Native basis** — model this same account continuously with both native EOD totals,
   without valuation/cost adjustments or a portfolio-membership assertion.
2. **Recognized incoming candidates** — each bounded `account_cash_in_candidate`
   (`из АО …`) is explicitly included as an external inflow at its native posting date
   or excluded from the external schedule; excluding does not delete the observed row.
   There is no generic withdrawal classifier, so unrecognized/negative Money rows stay
   unknown and are named in the limitations.
3. **Schedule** — explicit `dated` or `explicit_empty`; omitted/null is not empty.
4. **Remaining crossings** — within the scenario this selected native account has no
   other boundary crossings beyond the displayed schedule. This is a hypothetical
   statement, not completeness proof.
5. **Trades/Money/pending** — recognized settlements, commissions, coupons, accrued
   interest and pending trades add no extra investor flow or endpoint adjustment in
   this native-total model; their amounts are never zeroed and coupons/NKD are not
   added twice. Recognized coupon/NKD observations are displayed separately.
6. **REPO** — when REPO is observed in recognized trades or structural native
   references, `native_totals_include_REPO_as_reported` is required and the result is
   strongly conditional: REPO amount, custody basis and economic effect stay unknown.
7. **Unparsed/opaque rows** — when material unparsed rows/sections are reported, the
   scenario explicitly assumes they are already reflected in the broker-reported native
   totals and add no separate modeled effect; their meaning stays unknown.

Unknown future diagnostics and invalid assumption membership block. Candidate capacity
is bounded (16) without truncation; extra candidates are retained and blocked.

<a id="c7-broker_statement_provisional-12-mathematics"></a>
#### Units and mathematics

The unchanged Decimal XIRR kernel and S3 period conversion are reused at precision 60.
For a selected external inflow `Ei > 0` the investor vector is `-V0@t0, -Ei@ti, +V1@t1`
with `t0 < ti <= t1`; the returned fraction is `(1+r)^((t1-t0).days/365)-1`,
`annualized=false`, and the scenario amount is `V1 - V0 - sum(Ei)`. No-root, ambiguity,
convergence and non-finite guards stay fail-closed. Synthetic 30-day reference:
`10,000 + 1,000 on day 15 -> 11,211 RUB`; including the candidate gives 211 RUB /
2.01%, excluding it gives 1,211 RUB / 12.11% — labelled scenarios, not bounds. When
exactly one candidate exists, the opposite interpretation is returned as a clearly
labelled alternative; with zero or multiple candidates no automatic alternative is
invented.

<a id="c7-broker_statement_provisional-12-http"></a>
#### HTTP and desktop

All routes are POST multipart under `/api/broker-statement-provisional` with the
unchanged `file`, `intake_id` and `expected_manifest_digest`:

| Route | Required fields beyond the common ones |
| --- | --- |
| `/context` | None |
| `/evaluate` | JSON `assumptions`, `expected_context_fingerprint` |
| `/export` | Same plus `expected_result_fingerprint` |

Unexpected/duplicate fields and query parameters are 422; missing intake is 404;
original/manifest/context/result staleness is a typed 409 without a number. Responses
are no-store and never log XML or financial values; export re-reads and recomputes the
same full DTO. The panel lives in the durable source-intake journal, uses the
page-memory original, shows observed RUB components and source lexemes, candidates,
payouts, every required choice, the nonannualized period %, the scenario RUB and all
limitations, and hides the old result on any edit. Unbinding or choosing a different
account/original invalidates it; A→B→A and late-response races are rejected.

A zero-metadata desktop entry at `/v2/data/source-intake` lists existing journals
without requiring a ReportingMonth or Account and reattaches the exact original from
page memory. It only reads the journal and calls the provisional routes; it creates no
financial metadata and cannot save, rebind or apply an intake. The existing bound month
journal keeps its panel. The synthetic real-backend acceptance journey covers this
empty-metadata path and asserts zero metadata tables, unchanged journal history and the
same 211 RUB / 2.01% reference.

<a id="c7-broker_statement_provisional-12-boundary"></a>
#### Boundary and verification

This slice does not change strict S3, `can_apply`, Close, financial tables or the
journal writer, and does not assign unknown postings as Owner funding. Synthetic
backend tests cover the reference equation, loss/funding/withdrawal signs,
explicit-empty vs missing schedule, unbound single-native scope with zero
metadata/finance DML, ambiguous second alias, missing endpoint side, REPO/unparsed/
pending assumptions, quantity/value conflict, alias remap, capacity, stale original/
manifest/context and zero writes; desktop tests cover no-default choices, observed vs
scenario separation, source-native scope without an account binding, edit
invalidation, late responses and full JSON export. Real numeric availability is not
promised; the provisional figure is never promoted to actual performance.

<a id="c7-instrument_what_if-1"></a>
### Supported stock-only fixed-holding WHAT-IF

Read-only slice for [#865](https://github.com/LTstripes/hermes-finance/issues/865),
under the [accepted stock-only amendment](https://github.com/LTstripes/hermes-finance/issues/865#issuecomment-6233624253).
This contract does not authorize actual instrument performance.

`GET /api/instruments/{id}/conditional-return` recomputes one brokerage/IIS account,
one historical RUB stock and exact EOD `(t0,t1]`. The three Boolean query choices
`no_unobserved_movements`, `no_unobserved_payouts`, `no_other_costs_or_taxes`
default to false. `request_nonce` binds a response to the caller's evaluation;
it is not evidence of source completeness. Responses use `Cache-Control: no-store`.

One outer `coherent_read_operation` owns the query-only committed snapshot.
`instrument_eod_observations` supplies #860 boundaries and nested #858 net
payouts; `known_instrument_trades` supplies #862 executions. Readers and
financial writers retain their existing authority. No new financial row,
schema, ledger, source parser, provider call or export is introduced.

DTO sections separate `observed`, `accepted_known`, `chosen_assumptions`,
`hard_blockers` and `hypothetical_result`. Only all three selected assumptions
and no hard blocker permit integer-kopeck `V1 - V0 + P`. P is the sum of the
canonical supported dividend ICF events once, preserving unknown tax breakdown
and already netted fees/taxes. The unannualized fraction and percentage-point
strings use Decimal precision 100 and no display rounding. A repeating fraction
is represented to that declared arithmetic precision, never through binary float.
For 1000→900 and net dividends 150, results are `50.00` RUB, fraction `0.05`,
percent `5`. Negative and exact-kopeck results follow the same formula.

Hard guards retain missing/stale EOD, changed identity/positive quantity,
incompatible currency, unproven/booked/conflicting payouts, native/accepted
executions and crossing/pending events, REPO/opaque transfers, principal,
persisted in-kind movements, source binding/integrity/disposition conflicts,
unparsed sections, source-calendar gaps and ambiguous overlapping originals.
The source inventory is inspected even when the accepted trade list is empty.
Current S1 preparation and the existing derived cash/quantity controls are
recomputed for each scoped original, including S1-only originals whose ending
economics agree but whose opening cash or inventory contradicts the source.
Account-scoped Money rows inside the period conservatively block with
`money_economic_effect_unproven`: this stock slice has no independent authority
to dismiss their economic effect or attribute them to a dividend. Even an
accepted unrelated cash subset is not a waiver. No source authority is rewritten.

Every bond is hard blocked with `bond_dirty_basis_source_unproven`, including
an artificial persisted `included` basis. All three result values remain null.
The three hypothetical assumptions can cover only unobserved events; they never
waive observed unsupported economics or assert complete inventory.

Always: `actual_instrument_return=null`, `whole_period_completeness=unknown`,
top-level `dependency_fingerprint=null`. #862's null fingerprint is preserved;
no reusable inventory certification is manufactured. Source/proof references
describe this read, not subsequent requests. A concurrent WAL commit is invisible
to the current coherent snapshot and is evaluated on the next request.

The existing Capital → Performance instrument selector contains the on-demand
panel. No checkbox is preselected. Selector/context/assumption changes, pending
refreshes, failed reads and mismatched nonce/method/nested scope suppress old
results. Nothing is persisted. Actual performance remains explicitly unavailable.

Focused verification:

```text
backend: pytest tests/test_instrument_what_if_service.py
frontend: npm test -- src/ui-v2/InstrumentWhatIf.test.tsx src/ui-v2/InstrumentCashIncome.test.tsx
frontend: npm run build
frontend: npx playwright test --project=instrument-what-if
```

The desktop journey starts only its own disposable fabricated database/backend
on loopback port 18865 (overridable), validates API parity, keyboard, 1440 width,
1280 width at 125% zoom, delayed A→B→A, failed reads and the blocked bond.
Installed Stable and Owner data are outside this verification path.

<a id="c7-source_intake_result-1"></a>
### Source-intake-bound conditional instrument result

Bounded first slice for [#891](https://github.com/LTstripes/hermes-finance/issues/891):
one visibly hypothetical per-instrument RUB/percent result from a durable saved
original (the journal itself is [chapter 3](#c3-source_intake-8)), with the
accepted #858 payouts and #862 executions reused read-only. This contract does
not authorize actual instrument performance, bonds or changing-quantity return
math.

`GET /api/broker-months/intakes/{intake_id}/instrument-result` recomputes one
saved `source_intake_v1` original and one ISIN inside it. Query parameters:
`isin`, `request_nonce`, and the three Boolean choices `no_unobserved_movements`,
`no_unobserved_payouts`, `no_other_costs_or_taxes` (default false). Responses use
`Cache-Control: no-store`. The endpoint is a GET: no journal revision, no
financial Apply and no second money ledger are required or written.

The observed block is the original's own native EOD facts for the ISIN position:
`beginning_value` (`previous_day_eod` basis at `covered_from - 1`) and
`ending_value` (`covered_to_eod` basis at `covered_to`), exact kopecks through
the shared Decimal discipline. The value change and its percent are reported
separately from the conditional total and are never labelled profit when the
quantity changed.

`P` is the exact supported net dividend sum once, from the unchanged #858 reader
inside the same coherent snapshot: every observed payout row must be
`included_in_known_net`, current and a dividend, and at least one event is
required. Embedded taxes and fees are shown as evidence and are never subtracted
a second time; an unknown tax breakdown stays NULL. `V1 - V0 + P` is computed
only when all three assumptions are explicitly selected and no hard blocker is
present. `actual_instrument_return` is always null and
`whole_period_completeness` always `unknown`.

The conditional total is unannualized (`percent_unit=percentage_points`,
`annualized=false`), uses Decimal precision 100 and no display rounding. For a
fixed holding 1000→900 with a proven 150 net dividend the result is `50.00` RUB,
fraction `0.05`, percent `5`.

What stays NULL with a finite reason:

- **Bonds**: `bond_dirty_basis_source_unproven`, `bond_nkd_basis=unknown`; no
  coupon or apparent value difference produces a number and no clean/dirty
  basis is invented. A separate accepted provenance contract is required.
- **Changed quantity / observed trades**: `quantity_changed_not_profit` and
  `changing_quantity_result_unavailable`. `V1 - V0 + P` does not apply; a dated
  cash-flow MWR needs its own reviewed contract. Observed source facts remain
  visible; the total is NULL.
- **Unattributed Money rows**: `money_economic_effect_unproven`. A stock
  dividend could hide in an unclassified posting; the slice has no authority to
  attribute or waive it, and no second payout is ever added.
- **Unproven payouts**: `proven_net_dividend_required`; absence of rows is never
  a zero. `net_distributions` stays NULL unless every observed row is fully
  supported.
- **Journal/identity**: unbound intake, missing/ambiguous ISIN proposal,
  unproven or conflicting currency, an unresolved identity deferral or review
  reason for the ISIN, a non-RUB catalogue card, unmapped or mismatched
  instrument card, inactive account.
- **Source controls**: syntax/endpoint blockers, the accepted cash and
  quantity-movement controls recomputed for the raw retained original (trade
  readiness is deliberately not claimed: any observed trade already blocks
  with its own reason), unparsed sections, REPO, principal or in-kind flows,
  and overlapping originals of the same native source account whose instrument
  economics disagree (`ambiguous_overlapping_originals`). Native-account
  membership uses the retained `native_accounts_json`, filename and row
  accounts plus the effective mapping registry, so an overlapping **unbound**
  original of the same native account is compared too; an overlap that cannot
  be attributed to a different account stays
  `overlapping_native_account_unproven` instead of being assumed irrelevant.

The response binds `intake.id`, `head_seq`, `manifest_digest`,
`document_sha256`, the covered period, the current finance-link state and the
journal exceptions, plus the exact position observation row reference. Repeated
GETs are recomputed against the current committed journal; a new revision
changes `head_seq` and the client suppresses the old result. `request_nonce`
binds a response to the caller's evaluation; `dependency_fingerprint` remains
null and is never a reusable completeness token.

The panel lives in the month-close source journal under the selected saved
original ("Условный результат бумаги из сохранённого оригинала"). No checkbox
is preselected; selection, assumption or original changes suppress the old
result. Actual performance is explicitly unavailable.

A source-only unbound corpus (no account binding and no booked payouts) yields
observed source facts and NULL totals only. On the current #769 corpus of
unbound originals this slice does **not** enable a numeric June/July instrument
result; a separate reviewed contract is required for unbound-native-scope
hypotheticals. Focused verification:

```text
backend: pytest tests/test_source_intake_result_service.py
frontend: npm test -- src/components/month-close/SourceIntakeInstrumentResult.test.tsx src/components/month-close/SourceIntakeJournal.test.tsx
frontend: npm run build
```

<a id="c7-asset_class_returns_contract-52"></a>
### Class metric distinction and C1–C5 evidence

<a id="c7-asset_class_returns_contract-52-1-three-different-quantities-must-stay-separate"></a>
#### 1. Three different quantities must stay separate

1. **Asset-class return** — XIRR/TWRR for one economic class over an interval.
2. **Account return** — existing portfolio/account Performance scope.
3. **#575 monthly monetary result** — cash income / realised result / unrealised snapshot grouped by current `instrument_type`.

They are not interchangeable. A specialised brokerage account does not prove class return. #575 numbers are not return inputs and must not be relabelled XIRR/TWRR.

`PerformanceScope` remains `portfolio|account` for the existing routes. #535 adds a separate bounded class-return API without changing that enum. PERF04B class/instrument additive attribution remains separately unsupported; Phase 1 rates do not implement it.


<a id="c7-asset_class_returns_contract-52-2-capability-matrix"></a>
#### 2. Capability matrix

This table retains the **original 2026-09-27 evidence inventory**, not current delivery status. Section 0.1 and the linked implementation contracts govern the delivered first subset.

| Class | Original authoritative evidence | Original blockers |
| --- | --- | --- |
| Deposits | Exact monthly deposit/savings balances; participation in portfolio/account valuations | No complete class-boundary principal history or dated opening/maturity transition contract; interest/empty rows do not prove no crossings |
| Bonds | Monthly quantities, persisted market value/cost/unrealised result, NKD and price provenance | Current catalogue type was not historical identity; buys/sells and coupon/redemption/fee facts did not form complete class history; missing holdings could not imply sale/zero |
| Equities | Same position envelope; dividend/realised cash facts could exist | No historical class or complete execution/class-crossing history; distribution needed explicit boundary treatment, without duplication |
| Gold | Position with persisted manual/known price and market value | Mixed `gold_other` presentation was not gold identity; no complete historical purchase/sale/fee/FX class ledger |


<a id="c7-asset_class_returns_contract-52-21-historical-classification-is-a-hard-blocker"></a>
#### 2.1 Historical classification is a hard blocker

The original baseline could relabel old position groupings via today's `Instrument.instrument_type`. #696 now provides persisted `historical_instrument_type` for the class-return path. Present-day catalogue edits must not rewrite it; legacy rows without evidence remain NULL/unavailable.

The governing requirement remains immutable snapshot identity, effective-dated membership with gap/overlap checks, or an equally strong accepted historical contract. A migration must never manufacture historical certainty from today's catalogue. Existing legacy analytics are not silently redefined by this new return surface.

Deposits already store `deposit_type` per snapshot, but that does not solve class-boundary cash evidence.


<a id="c7-asset_class_returns_contract-52-3-class-boundary-flows-are-not-accountportfolio-flows"></a>
#### 3. Class-boundary flows are not account/portfolio flows

A transaction can be internal to an account/portfolio but external to an asset class:

- Brokerage cash buying stock is a class contribution into equities.
- Selling stock into brokerage cash is a class withdrawal.
- Coupon/dividend into account cash is return leaving the security class and needs one accepted boundary treatment.
- Redemption principal crosses the bond-class boundary but is not passive income.
- Class reclassification cannot be modelled as a present-day label edit.

Canonical `ExternalFlow` is portfolio/account boundary evidence without class/instrument identity. `InvestmentCashFlow` contains useful income/cost facts, not a complete trade ledger. Phase 1 uses relevant facts as contradictions, not completeness proof.

Never derive class returns by filtering portfolio flows by current type, inferring flows from capital deltas, allocating unknown cash by current weights, counting distributions/principal twice, averaging/summing account returns, or substituting price change/YTM/coupon rate/#575 result for total return.


<a id="c7-asset_class_returns_contract-52-4-endpoint-valuations-are-necessary-but-insufficient"></a>
#### 4. Endpoint valuations are necessary but insufficient

Exact class endpoints need every required component's historical identity and explicit completeness. #698 supplies this for the bounded Phase 1 contract, including both whole-class inventory claims. A single persisted position or other-class footprint does not establish complete requested-class inventory.

Settlement cash is outside the Phase 1 security classes. Deposits remain unsupported. Archived/sold/disappeared/quantity-changing holdings fail closed unless existing accepted same-class internal-transfer evidence exactly reconciles them. Values are persisted RUB endpoints, not today's quotes. Unknown/unclassified components are not allocated by weight.

These rules do not independently enable flow-bearing histories; those still require their own complete event/coverage contract.


<a id="c7-asset_class_returns_contract-52-5-exact-twrr-needs-class-specific-prepost-evidence"></a>
#### 5. Exact TWRR needs class-specific PRE/POST evidence

Current observed boundaries remain portfolio/account-scoped. Exact class TWRR with crossings requires actual class values before/after each required boundary/group or an accepted equivalent proving exact subperiod inputs. Monthly snapshots alone do not prove intra-period ordering.

Do not extend `ObservedValuationPoint` ad hoc inside the thin return adapter. Class identity, target binding, grouping and correction/CLOSED lifecycle must be frozen first. C4 is vacuous only for the affirmatively proven no-crossing path.


<a id="c7-asset_class_returns_contract-52-6-evidence-prerequisites"></a>
#### 6. Evidence prerequisites

These are canonical capabilities, not a global all-or-nothing gate. Each metric/class/interval needs the prerequisites applicable to that capability.


<a id="c7-asset_class_returns_contract-52-c1--historical-class-identity"></a>
#### C1 — historical class identity

Immutable/effective class key for class-valued components; no current-catalogue rewrite, explicit unknown/gap/overlap states, correction invalidation and synthetic class-change regressions. The snapshot-scoped Phase 1 implementation is #696.


<a id="c7-asset_class_returns_contract-52-c2--class-boundary-event-ledger--coverage"></a>
#### C2 — class-boundary event ledger / coverage

Explicit dated class crossings with exact amount/direction/provenance, or accepted affirmative no-crossing coverage. Where applicable, cover purchases/sales, deposit principal, distributions, redemption principal separately from income, reclassification, attributable fees/taxes and in-kind movements.

Account-level external-cash attestation is not class-boundary completeness. Net-zero crossings are still crossings. Phase 1 #698 is an Owner-attested no-crossing path, not statement-verified execution history.


<a id="c7-asset_class_returns_contract-52-c3--class-valuation"></a>
#### C3 — class valuation

Exact opening/closing values with whole-class component coverage and historical identity. XIRR does not require a general daily valuation service; crossing TWRR additionally needs exact segmentation-boundary values. No current-weight backfill, survivor-only composition or partial-as-complete result.


<a id="c7-asset_class_returns_contract-52-c4--class-prepost-boundary-evidence-for-twrr"></a>
#### C4 — class PRE/POST boundary evidence for TWRR

Exact class-specific observations or an equally strong accepted transaction-aware valuation source for every crossing requiring segmentation. Not required for XIRR; vacuous for proven no-crossing intervals.


<a id="c7-asset_class_returns_contract-52-c5--currency--correction--lifecycle"></a>
#### C5 — currency / correction / lifecycle

Phase 1 consumes accepted already-RUB persisted PositionSnapshot values, not current catalogue currency or guessed conversion. Non-RUB application base currency is unsupported. A future foreign-amount path requires its own authoritative dated valuation/conversion evidence.

Material corrections invalidate dependent evidence; CLOSED rules stay fail-closed. No broadened FX architecture is implied.


<a id="c7-asset_class_returns_contract-52-7-smaller-exact-subset"></a>
#### 7. Smaller exact subset

Snapshots, an empty query or an apparently flat holding chart alone never establish no crossings. The implemented first subset requires C1, affirmative C2 no-crossing, exact complete C3 endpoints and bounded C5. With all present, existing XIRR and no-boundary TWRR may run without C4.

No-crossing includes no purchases/sales, class reclassification, distributions leaving the class, redemption/maturity principal, attributable boundary fees/taxes or external in-kind movements. A fully reconciled same-class transfer entirely within continuously included accounts is not itself a portfolio-wide class crossing. Unknown/contradictory facts defeat the assertion; they do not become guessed events.


<a id="c7-asset_class_returns_contract-52-8-reference-vectors-for-future-prerequisites"></a>
#### 8. Reference vectors for future prerequisites

These remain construction/availability vectors; the existing numerical solvers govern rates after evidence is valid.

| Vector | Evidence | Required outcome |
| --- | --- | --- |
| R1 — current type edit | Closed historical bond, catalogue later stock | Persisted historical bond or legacy unknown; never silently equity |
| R2 — sold holding | Opening holding, missing closing row, no withdrawal proof | Unavailable, not -100%, zero or inferred proceeds |
| R3 — in-account purchase | Cash buys equity without portfolio ExternalFlow | Requires equity class contribution evidence |
| R4 — coupon + redemption | Income and principal paid separately | Distinct accepted treatment; no passive-income principal or double counting |
| R5 — gold bucket | Mixed `gold_other` allocation | Not a gold-return input |
| R6 — positive control | Exact historical identity, complete endpoint inventories, RUB 1000 to 1100 over 365 days, affirmative no-crossing | Existing solvers support approximately +10% annualized XIRR and +10% period TWRR |
| R7 — unknown crossing | Exact endpoints but unknown class coverage | Both class metrics unavailable |


<a id="c7-asset_class_returns_contract-52-9-instrument-level-drill-down"></a>
#### 9. Instrument-level drill-down

Do not add individual instrument XIRR/TWRR in this milestone. It needs at least the same trade/disposal/history evidence and more specific identity/flow provenance. Informational price/value history must not be called total return. A future instrument-return surface should be on-demand, not a permanently expanded all-instruments table.

<a id="c7-class_returns_api-1"></a>
### Exact no-crossing class return DTO and construction

The bounded class API and read-only UI are integrated capabilities. Current acceptance/UAT scope is recorded only in [CURRENT_STATUS](CURRENT_STATUS.md#s2).

`GET /api/performance/class-returns?asset_class=stock&start_date=2030-01-31&end_date=2031-01-31`

This combined read-only endpoint supports `stock`, `bond` and `gold` over the
portfolio-wide historical Performance account universe, in RUB only. It consumes
the accepted [class endpoint eligibility](#c6-class_no_crossing_endpoints-7) result
once, under that reader's coherent committed snapshot. It does not reconstruct
evidence, select nearby dates or change portfolio/account `PerformanceScope`.
No new schema, writes, provider calls or result cache are introduced by #535.


<a id="c7-class_returns_api-1-response"></a>
#### Response

- `asset_class`, `historical_account_ids`: requested class and accepted historical universe.
- `requested_period`: requested `start_date` / `end_date`.
- `actual_covered_period`: exact observed endpoint dates, each nullable when missing;
  dates alone do not assert eligibility or complete coverage.
- `performance_currency`, `valuation_basis`: accepted currency and
  `persisted_rub_market_value_kopecks`. The declared basis describes the supported
  valuation contract; unavailable/unsupported evidence does not supply a value.
  Stored bond accrued-interest semantics are consumed unchanged, exactly once.
- `coverage_state`, `coverage_provenance`: safe #698 evidence fields, including
  Owner provenance, explicit opening/closing inventory claims and revisions.
  Internal material signatures are not exposed. Owner attestation remains an
  attestation, not independent statement verification.
- `eligibility_status`: `eligible`, `unavailable` or `unsupported`, unchanged from #698.
- `evidence_reason_codes`: deterministic #698 reasons, unchanged.
- Independent `xirr` / `twrr` objects: `availability` (`available` / `not_computable`),
  `quality` (`exact` / `unavailable`), `value` (decimal string or null),
  `value_unit=percentage_points`, `annualized`, `reason_codes`, `reason_source`.

`reason_source=evidence` means eligibility blocked calculation: neither solver
was called and both metrics carry the evidence reasons. Unsupported capability
is distinguished by `eligibility_status=unsupported`. For eligible evidence,
solver reasons propagate unchanged with `reason_source=solver`; a successful
metric has no reasons and a null reason source. Evidence and numerical reasons
must never be presented as the same missing-data instruction.

Dates use the existing date-only API convention. Missing/malformed query dates
and unordered/empty intervals return the existing 422 error response.
Unsupported class names return a normal evidence response with
`unsupported_class`, rather than coercing them into a supported class.


<a id="c7-class_returns_api-1-exact-metric-construction"></a>
#### Exact metric construction

Only `eligible` intervals reach the unchanged numerical primitives:

```python
calculate_xirr((
    XirrCashFlow(actual_opening_date, -opening_value_kopecks),
    XirrCashFlow(actual_closing_date, closing_value_kopecks),
))
calculate_twrr(opening_value_kopecks, closing_value_kopecks, boundaries=())
```

No intermediate flows, ExternalFlow reuse, capital deltas, current allocation,
#575 monetary results, class boundary rows or PRE/POST observations are created.
Exact internal same-class transfers affect the accepted aggregate endpoints
only. C4 is vacuous for this affirmatively proven no-crossing subset.

Solver fractional rates are multiplied by Decimal 100 at the response adapter.
XIRR is annualized; TWRR is the whole-period return. Availability and quality are
preserved independently from each solver, without fallback or rounding to zero.

For a 365-day interval, positive 1000 → 1100 supports approximately +10% XIRR
(within existing solver tolerance) and exact +10% TWRR. A shorter interval keeps
TWRR +10% but annualizes XIRR. Flat positive values support 0; positive losses
support negative returns. Zero opening makes both solvers unavailable; positive
opening and zero closing gives unavailable XIRR and exact −100% TWRR. These are
numerical outcomes with complete evidence, not evidence gaps.

Two endpoint flows have at most one sign variation, so ROOT_AMBIGUITY normally
does not arise here. Generic reason propagation preserves it or future solver
limitations without invented flows or changed numerical semantics.


<a id="c7-class_returns_api-1-delivered-ui-and-remaining-boundary"></a>
#### Delivered UI and remaining boundary

The existing Performance detail now presents Accounts/Classes with exact-date
presets, independent rates/reasons, safe provenance and responsive keyboard
support. `deposit` remains a truthful unsupported row. This UI reads the API;
it does not create class attestations or repair legacy C1 evidence.

Statement-backed crossings, FX, deposits/savings and instrument-level returns
remain outside this slice. Any statement-backed continuation requires its own accepted contract without changing this API implicitly. Owner UAT and any new release/local update
remain separate from technical integration.

<a id="c7-performance_readiness_api-1"></a>
### Metric-specific readiness reasons and actions

Implementation of #530 under the accepted #529 contract. This read endpoint does
not implement the #531 UI or the #532/#533 write adapters.

`GET /api/performance/readiness` requires `start_date` and `end_date`, with the
existing `scope=portfolio|account` and `account_id` contract. Repeated context
parameters are rejected. Unknown accounts and invalid intervals are context
errors, never a fallback to portfolio or another date range.

The response contains `schema_version=1`, request identity, final `xirr` and
`twrr` using the existing metric DTOs, the existing `evidence` blocks and
`diagnostics`. All three services execute inside one existing coherent read
snapshot. No new calculator, completeness semantics or persisted revision is
introduced. Old endpoints are unchanged.

`evidence.availability` is the prerequisite union, **not** a hide-switch for
either final metric. Final values retain percentage-point units and their
existing annualization flags; exact zero is a value. A prerequisite success
does not promise that the final solver succeeded.

Account sets retain their original names and meanings:

- `evidence.scope_membership.account_ids`: membership-checked catalog;
- `evidence.cash_boundary_coverage.account_ids`: accounts requiring cash evidence;
- `evidence.in_kind_boundary_coverage.account_ids`: accounts requiring in-kind evidence.

There is no reconstructed included-account set.

Diagnostics group exact final reason codes by affected metric. The external-flow
code also yields separate cash-history and legacy diagnostics where those
evidence fields prove them. Unknown codes receive `unknown_reason` with an
unsupported inspection action; they never acquire mutation advice from their
spelling. Refs identify only evidence-backed local records/dates. The whole
response identity supplies the selected scope and interval; refs do not assert
that an entire interval has been confirmed when coverage is missing.

Action kinds are a closed enum with typed local params, never a URL. `available`
means a supported inspection/selection or existing coverage API path;
`requires_reopen` uses the existing coverage edit guard for the requested
interval. Coverage review still requires actual Owner verification and explicit
attestation. Historical membership offers the [finite explicit writer](#c6-historical_membership_api-1);
existing open-ended rows remain read-only/blocking, and its own full old/new union
and observation-parent CLOSED checks remain authoritative. `not_implemented`
identifies absent legacy/transfer UI reconciliation or observation targets that
identity/grouping/duplicate state cannot repair. The supported
[PRE/POST observation capture](#c6-pui05_valuation_capture-9) reports `available`
or `requires_reopen` only for a concrete target that can accept fresh evidence
now. `source_required` does not claim a historical source is absent.
`unsupported` does not promise that editing or confirming coverage can fix
valuation/FX/solver limitations.
Every action requires rereading readiness to verify the final outcome.

Free-form provenance references and non-allowlisted provenance/source labels
are omitted from this projection. Evidence IDs, financial status and values
remain authoritative; old evidence endpoints are unchanged.

Unexpected read/serialization failures and mismatched result identity or value
contracts return HTTP 503 with `performance_readiness_technical_error` and a
retry-read message, without exception text or financial missing-data reasons.
Do not merge a failed response with cached metrics from a different generation.

<a id="c7-perf04_attribution_contract-9"></a>
### PERF04 aggregate monetary bridge

<a id="c7-perf04_attribution_contract-9-1-purpose-and-source-of-truth-boundary"></a>
#### 1. Purpose and source-of-truth boundary

PERF-04A defines the first truthful attribution surface that can be supported
by the accepted Hermes evidence. It is deliberately narrower than a general
investment-performance decomposition.

The accepted R08 contracts remain authoritative for:

- exact opening and closing valuation points;
- effective-dated performance-scope membership;
- affirmative cash-boundary and in-kind coverage;
- canonical `ExternalFlow` identity, direction, amount, date, currency and
  transfer classification;
- tax, fee, retained-income, redemption and direct-payout treatment;
- performance-currency conversion gates; and
- exact XIRR/TWRR availability and calculation semantics.

The contract is read together with:

- [the PERF-04 evidence matrix](#c7);
- [the PERF-04 reference vectors](#c7-perf04_reference_vectors-237);
- [the PERF-04 surface map](#c7);
- [the R08 performance availability contract](#c7-r08-01c-performance-availability-12);
- [the R08 XIRR contract](#c7-r08-02-portfolio-xirr-8);
- [the R08 TWRR contract](#c7-r08-03-twrr-contract-recon-32);
- [the observed-boundary contract](#c6-r08-03a-valuation-boundaries-8); and
- [the reconciled Performance v1 roadmap](#c6-performance_v1_reconciliation_2026-09-06-62).

The three discovery documents retain their historical `858d64c...` baseline
labels. Issue #346 states that they were accepted and integrated at the
`d572974...` synthesis baseline; their discovery status remains non-normative.
These are the accepted PERF-04A monetary-bridge rules.

The governing safety rule is:

> unavailable or unknown evidence is never converted to zero, estimated,
> interpolated, or labelled exact.


<a id="c7-perf04_attribution_contract-9-2-chosen-attribution-v1-semantics"></a>
#### 2. Chosen Attribution v1 semantics


<a id="c7-perf04_attribution_contract-9-21-primary-metric-selected-scope-value-change-after-external-flows"></a>
#### 2.1 Primary metric: selected-scope value change after external flows

Attribution v1 is a **signed contribution to value change**, not a return
decomposition. The only normative v1 measure is:

`value_change_after_external_flows`

It answers:

> How much did the selected performance scope's exact closing value change
> after removing the selected-scope external boundary flows recorded for the
> interval?

It does **not** answer:

- what the annualized or time-weighted return was;
- which instrument, asset class, trade, lot or price movement caused the
  change;
- how much was realized versus unrealized P/L;
- how much was FX, carry, coupon, dividend, redemption, fee or tax; or
- how a component would have performed under a counterfactual portfolio.

The result is an exact money amount. It is not a percentage, a percentage-point
contribution, XIRR, TWRR, Modified Dietz, benchmark-relative active return, or
an estimate of any of those metrics.


<a id="c7-perf04_attribution_contract-9-22-v1-grain-and-supported-dimensions"></a>
#### 2.2 V1 grain and supported dimensions

The v1 grain is one aggregate row for the **selected scope and exact interval**:

| Dimension | V1 decision |
| --- | --- |
| Scope | `portfolio` or one explicit `account`; follows the existing R08 scope contract. |
| Period | Exact `start_date` and `end_date` persisted valuation dates; both selected months must be closed. |
| Currency | The accepted R08 performance currency only; v1 does not add FX conversion. |
| Portfolio account rows | Not emitted. An account can be queried as its own selected scope, but that is not a portfolio decomposition. |
| Instrument rows | Not supported in v1. |
| Asset-class rows | Not supported in v1. `instrument_type` and analytics `asset_class` are not interchangeable. |
| Flow/event rows | Not attribution contributions in v1. They may be exposed only as sanitized evidence/context, not as a second performance result. |

The account-scope form is useful and exact when its own R08 prerequisites are
complete. It must not be described as an account's additive share of the
portfolio unless a future contract proves cross-scope reconciliation.

This deliberately chooses a **separate set of metrics**: one exact value-change
metric now, with income/cost/principal evidence kept conceptually separate.
The contract does not force unsupported account/instrument/asset-class
decomposition into the first slice.


<a id="c7-perf04_attribution_contract-9-23-why-v1-is-not-a-twrr-attribution"></a>
#### 2.3 Why v1 is not a TWRR attribution

The accepted exact TWRR is a parent return metric with explicit observed
pre/post valuation boundaries around each selected external-flow boundary.
The discovery evidence does not provide complete component-level pre/post
values, component flow allocation, trade-time composition membership, or
intra-period valuation for every candidate attribution row.

Therefore v1 does not apply a component-linking formula such as:

```text
g_ij = V+_ij - V-_ij - C_ij
q_ij = g_ij / D_j
linked_i = sum(q_ij * later_subperiod_factors)
```

That formula remains a possible future TWRR-attribution method only after its
component evidence and linking convention are separately accepted. XIRR is
nonlinear and remains a parent money-weighted metric; it is never an additive
attribution method.


<a id="c7-perf04_attribution_contract-9-3-exact-numerical-contract"></a>
#### 3. Exact numerical contract


<a id="c7-perf04_attribution_contract-9-31-inputs-and-signs"></a>
#### 3.1 Inputs and signs

Let:

- `V0` be the exact opening valuation of the selected scope;
- `V1` be the exact closing valuation of the selected scope;
- `C_j` be one canonical selected-scope external-flow amount, signed from the
  selected-scope perspective;
- a contribution have `C_j > 0`;
- a withdrawal have `C_j < 0`; and
- `C = sum(C_j)` be the signed external-flow total.

The normative value bridge is:

```text
value_change_after_external_flows = V1 - V0 - C
```

Equivalently:

```text
V0 + C + value_change_after_external_flows = V1
```

The bridge is a value-change identity. It is not a TWRR factor and has no
denominator or annualization rule. A zero or negative bridge amount is valid
when all evidence is otherwise exact.


<a id="c7-perf04_attribution_contract-9-32-money-precision-and-rounding"></a>
#### 3.2 Money, precision and rounding

- Persisted and internal arithmetic uses integer minor units (`kopecks`) under
  the existing Hermes money contract.
- Any future calculation layer must preserve exact integer arithmetic for the
  bridge and must not use binary floating-point financial semantics.
- API money values use the existing exact decimal-string plus three-letter
  currency representation.
- No intermediate bridge term is rounded before the identity is checked.
- Display formatting may round only at the presentation boundary; a display
  residual must not be silently assigned to an account, instrument or event.
- Explicit zero remains an available zero. Missing or unknown evidence remains
  `null`/unavailable.


<a id="c7-perf04_attribution_contract-9-33-scope-treatment-of-flows-and-transfers"></a>
#### 3.3 Scope treatment of flows and transfers

At portfolio scope:

- a fully linked transfer between historically in-scope accounts is internal;
- its two legs do not enter `C` as an owner contribution or withdrawal; and
- for every relevant linked portfolio transfer, inter-leg transfer identity and
  reconciliation are mandatory under the existing R08 rules, regardless of
  whether its transit interval intersects `start_date` or `end_date`; and
- asynchronous transit safety is required only for valuation dates actually
  consumed by the PERF04A bridge: `start_date` and `end_date`. No
  cash-in-transit value is synthesized for asynchronous settlement, and an
  intermediate TWRR flow-boundary date is not a PERF04A transit gate.

At account scope:

- a source-account transfer leg remains the canonical withdrawal from that
  account;
- a destination-account transfer leg remains the canonical contribution to
  that account; and
- the selected leg must have canonical identity/classification, its exact
  amount and date, accepted currency, effective scope membership and ordinary
  external-flow coverage.

For an account-scope bridge, reconciliation of the opposite leg and
inter-leg/asynchronous-transit safety are not prerequisites. The absence of
cross-leg reconciliation evidence, an unexplained difference,
or an unreconciled opposite leg alone does not block an otherwise exact
selected-account bridge. A one-sided or otherwise unresolved transfer identity,
or an unresolved identity or classification of the selected leg, still fails
closed under the existing R08 transfer reasons. At portfolio scope, unresolved
or partially linked identity, failed inter-leg reconciliation or unvalued
transit continues to fail closed; a difference between linked legs is not
silently treated as performance.

An in-kind movement is not a cash `ExternalFlow` and therefore has no term in
the v1 formula. The current R08 `InKindMovement` evidence carries no monetary
boundary value. A known in-kind movement remains `NOT_COMPUTABLE` for PERF04A
under `not_computable_in_kind_movement_unvalued` at both scopes: at portfolio
scope it is conceptually internal but valuation continuity is not proven; at
account scope its movement crosses the account boundary. Unspecified
“accepted event-date valuation evidence” cannot make v1 computable. A future
separately accepted contract would have to define an exact signed in-kind
boundary-value term and explicitly extend the formula; v1 does neither.


<a id="c7-perf04_attribution_contract-9-4-income-principal-costs-direct-payouts-and-fx"></a>
#### 4. Income, principal, costs, direct payouts and FX

These rules define what may affect or explain the value bridge. They do not
create an income/fee/price decomposition in v1.

| Evidence or event | PERF-04A treatment |
| --- | --- |
| Retained coupon, dividend or interest inside the selected scope | Internal event. It is already reflected in the exact valuation change and is not added as an external flow or added a second time to the bridge. |
| Deposit/savings interest | Use the existing `DepositSnapshot.actual_interest_received_kopecks` meaning. It must not be duplicated with an `InvestmentCashFlow.interest` row; the existing service rejects that duplicate for deposit/savings accounts. |
| Redemption retained inside the selected scope | Principal reclassification between position and in-scope cash, not passive income and not an external flow. The redemption amount is not emitted as an attribution gain. |
| Fee, commission or tax charged inside the selected scope | Internal cost reflected in the selected valuations; it is not an owner withdrawal merely because investment cash decreased. A standalone cost is not attached to an owner flow by account/date/currency alone. |
| Owner payment with internal withholding | The canonical external boundary is the proven net amount that crossed outside the selected scope. Any separately proven internal tax/fee remains an internal cost; gross debit is not substituted for the boundary. |
| Direct coupon/dividend payout outside brokerage cash | Requires actual payment evidence plus accepted account/holding provenance. The proven net payment is one external withdrawal; gross income is explanatory evidence only and is not injected again into return or bridge math. Expected/provider calendar rows are insufficient. |
| Realized profit/loss or unrealized result | Existing fields may support bounded snapshot/reporting views, but v1 does not claim transaction, lot, disposal, price-path or realized/unrealized attribution. |
| Foreign-currency amount | No conversion is inferred from a currency label. A non-performance-currency flow/component, missing dated conversion, or incomplete conversion provenance is unavailable under the existing R08 currency reason. |

The v1 parent bridge therefore never adds a separate `income`, `redemption`,
`tax`, `commission`, `fee`, `FX`, `realized`, or `unrealized` amount to the
formula. A future explanation slice may expose such evidence as separate
labelled facts only when its own identity, scope, currency and completeness
contract is accepted.


<a id="c7-perf04_attribution_contract-9-5-availability-and-fail-closed-gates"></a>
#### 5. Availability and fail-closed gates


<a id="c7-perf04_attribution_contract-9-51-request-and-boundary-gates"></a>
#### 5.1 Request and boundary gates

An implementation may calculate the v1 bridge only when all of the following
are true:

1. `start_date` and `end_date` are exact persisted valuation dates and
   `start_date < end_date`.
2. Opening and closing reporting months are closed and each date resolves to
   exactly one authoritative valuation point for the requested scope.
3. Every selected valuation component is complete, valid and in the accepted
   performance currency. Missing components are not zero.
4. Effective-dated historical scope membership is complete, non-overlapping
   and consistent with the selected scope for the full interval. A whole-
   portfolio membership transition inside the interval remains unavailable
   under the accepted R08 gate.
5. Affirmative cash-boundary coverage is complete for every historically
   included account. A closed month or an empty flow table is not proof of
   complete owner-boundary history.
6. Required in-kind boundary coverage is complete and contains no known
   movement. Any known in-kind movement makes PERF04A `NOT_COMPUTABLE` under
   `not_computable_in_kind_movement_unvalued`, including an account-scope
   transfer. The v1 formula has no monetary in-kind term; no unspecified
   event-date valuation evidence or synthetic cash can repair this gate.
7. Every selected external flow is a valid canonical `ExternalFlow` with exact
   date, non-negative boundary amount, explicit direction, authoritative scope
   membership and accepted performance currency.
   For a flow whose `event_date` equals `start_date` or `end_date`, the
   endpoint-order gate in section 5.3 also applies; a strictly interior flow
   does not require TWRR pre/post boundary evidence for this aggregate bridge.
8. Transfer gates are scope-specific:
   - for `scope=portfolio`, every relevant linked portfolio transfer must
     satisfy the existing R08 inter-leg identity and reconciliation rules,
     regardless of whether its transit interval intersects `start_date` or
     `end_date`;
     asynchronous transit safety is evaluated only against those
     bridge-consumed valuation dates, and intermediate TWRR flow-boundary dates
     are excluded from the PERF04A transit gate;
   - for `scope=account`, the selected leg has canonical identity/
     classification, exact amount and date, accepted currency, effective
     membership and ordinary external-flow completeness. Cross-leg
     reconciliation of the opposite leg is not required for the account
     bridge, while a one-sided or otherwise unresolved transfer identity
     remains fail closed under the existing R08 reason.
9. No legacy or ambiguous cash-flow evidence remains an unclassified blocker.
10. The bridge identity is evaluated in one scope and one performance currency;
    no cross-currency aggregation is performed.


<a id="c7-perf04_attribution_contract-9-52-dedicated-perf04a-bridge-prerequisite"></a>
#### 5.2 Dedicated PERF04A bridge prerequisite

The response's v1 `availability` MUST be derived from a dedicated
`perf04a_bridge_prerequisites` projection over the shared R08 evidence. The
projection requires, at the requested scope and interval:

- exact available opening and closing valuation points;
- complete historical scope membership;
- complete affirmative cash-boundary coverage;
- complete in-kind boundary coverage with **no known in-kind movement**;
- complete canonical external-flow evidence and accepted performance currency;
- for `scope=portfolio`, inter-leg transfer identity and reconciliation are
  mandatory for every relevant linked portfolio transfer, regardless of
  whether its transit interval intersects `start_date` or `end_date`;
- for `scope=portfolio`, asynchronous transit safety evaluated only against
  the bridge-consumed `start_date` and `end_date`; intermediate TWRR
  flow-boundary dates are not part of this PERF04A transit gate;
- for `scope=account`, canonical identity/classification, exact amount and
  date, accepted currency, effective membership and ordinary external-flow
  completeness for the selected leg, without requiring opposite-leg
  reconciliation or transit safety; a one-sided or otherwise unresolved
  transfer identity remains fail closed; and
- accepted endpoint-order evidence for every selected external flow on
  `start_date` or `end_date`; an unproven or ambiguous relation is a bridge
  prerequisite failure with
  `not_computable_valuation_boundary_order_unknown`; and
- no other applicable shared R08 coverage reason.

The implementation MUST NOT consume the top-level
`PerformanceAvailability.availability` as the PERF04A bridge gate, because
that field unions XIRR and TWRR reasons. It MUST NOT consume
`PerformanceAvailability.twrr.availability` or a `PortfolioTwrrResult` as the
bridge gate. It MUST NOT use an XIRR/TWRR calculated-result availability or
solver outcome as a substitute for this evidence projection. The projection
may reuse the existing evidence-only R08 prerequisite assessments, but its
contractual source is the shared endpoint/flow/scope/currency/cash/in-kind
evidence, not a return result.

The projection deliberately excludes:

- TWRR-only observed-boundary gaps and same-day-order reasons for strictly
  interior flows; endpoint-flow order is a PERF04A prerequisite and is not
  excluded; and
- XIRR root, convergence or other solver outcomes.

Its exact result state and reason codes are then mapped to the v1 response
fields in this document. The projection is allowed to be available while
TWRR is not; it is not required to equal any current top-level R08
availability field.


<a id="c7-perf04_attribution_contract-9-53-endpoint-flow-ordering-versus-interior-flow-ordering"></a>
#### 5.3 Endpoint-flow ordering versus interior-flow ordering

The bridge consumes the exact valuation points `V0` and `V1`. It therefore
distinguishes the date of a selected external flow from the relation of that
flow to a consumed endpoint valuation:

- If `start_date < event_date < end_date`, the flow is strictly interior.
  PERF04A does not require observed `pre_external_flow`/`post_external_flow`
  evidence for that flow. TWRR-only
  `not_computable_valuation_boundary_missing` and
  `not_computable_valuation_boundary_order_unknown` remain non-blocking for
  the aggregate bridge when every dedicated bridge prerequisite passes.
- If `event_date == start_date` or `event_date == end_date`, accepted evidence
  must prove the flow's relation/order relative to the exact consumed `V0` or
  `V1`. The bridge does not infer whether the flow is already included in that
  valuation from the date alone. A date-only snapshot is neither automatically
  pre-flow nor automatically post-flow. If the relation is absent, ambiguous
  or otherwise unproven, PERF04A is `NOT_COMPUTABLE` with
  `not_computable_valuation_boundary_order_unknown`.

The endpoint rule does not introduce a start-of-day or end-of-day convention,
and it does not introduce a half-open interval convention. It also does not
make the complete two-sided TWRR boundary around every flow a PERF04A gate.
Only the endpoint inclusion/order relation needed for a flow on an interval
endpoint is required by this bridge.

Under the current persistence model, an R08 `ObservedValuationPoint` is
explicitly related to an external flow or boundary group, but is not persisted
as a binding to the exact monthly valuation point consumed as `V0` or `V1`.
Its date, matching reporting month, or `pre_external_flow`/
`post_external_flow` label must not be treated as that missing binding.
Consequently, current v1 remains fail-closed for endpoint flows unless the
existing evidence actually proves the relation to the consumed endpoint. A
future accepted evidence model that directly proves that relation may permit
the unchanged bridge formula to be exact when all other gates pass; this
addendum creates no schema or new financial convention.


<a id="c7-perf04_attribution_contract-9-54-twrr-specific-evidence-is-not-a-v1-bridge-gate"></a>
#### 5.4 TWRR-specific evidence is not a v1 bridge gate

Observed `pre_external_flow`/`post_external_flow` boundaries are required by
exact TWRR, but the complete pair is not required by this additive
endpoint-value bridge. Consequently:

- for strictly interior flows, `not_computable_valuation_boundary_missing`
  and `not_computable_valuation_boundary_order_unknown` may make TWRR
  unavailable while leaving the v1 bridge available, provided the dedicated
  `perf04a_bridge_prerequisites` projection passes;
- for a flow on `start_date` or `end_date`, an unproven relation to the
  consumed endpoint is a bridge failure with
  `not_computable_valuation_boundary_order_unknown`, even though the bridge
  still does not require the full TWRR boundary pair; and
- v1 does not call the TWRR solver and does not emit a TWRR value; and
- a future return-attribution slice must inherit the full exact TWRR boundary
  gate rather than weakening it.

Likewise, XIRR solver outcomes such as root ambiguity or convergence failure do
not change the value identity. XIRR remains available or unavailable according
to its own contract and is not used as a bridge contribution.


<a id="c7-perf04_attribution_contract-9-55-result-states-and-reason-codes"></a>
#### 5.5 Result states and reason codes

The v1 response uses the existing performance state vocabulary:

| Field | Available result | Failed result |
| --- | --- | --- |
| `availability` | `available` | `not_computable` |
| `quality` | `exact` | `unavailable` |
| `value` | exact money | `null` |
| `reason_codes` | empty | sorted, stable R08 reason codes |

The parent bridge propagates the applicable existing R08 reasons, including:

```text
not_computable_opening_valuation_missing
not_computable_closing_valuation_missing
not_computable_reporting_month_not_closed
not_computable_snapshot_date_missing
not_computable_unsupported_position_valuation
not_computable_scope_coverage_incomplete
not_computable_scope_cash_unclassified
not_computable_scope_membership_history_missing
not_computable_scope_membership_changed
not_computable_external_flows_incomplete
not_computable_currency_conversion_incomplete
not_computable_transfer_identity_unresolved
not_computable_transfer_in_transit_unvalued
not_computable_transfer_reconciliation_incomplete
not_computable_in_kind_boundary_coverage_unknown
not_computable_in_kind_movement_unvalued
not_computable_valuation_boundary_order_unknown
```

The implementation must not introduce a new reason by reclassifying an
existing R08 condition. For PERF04A, the existing order-unknown reason is
bridge-blocking only for an external flow on `start_date` or `end_date`; it
remains TWRR-only for a strictly interior flow. Future component/event
decomposition slices may add
PERF-04-specific reason codes for missing component evidence, missing flow
allocation or failed component reconciliation, but those codes are not a
license to emit partial exact decomposition in v1.

An unavailable parent is never represented as a zero bridge. Evidence detail
may retain `unknown`/`unavailable` sub-states from R08, but the top-level v1
value is null unless the complete bridge is exact.


<a id="c7-perf04_attribution_contract-9-6-normative-apidto-boundary"></a>
#### 6. Normative API/DTO boundary

The first implementation should use a dedicated backend-owned read model and
endpoint, not extend the strict XIRR/TWRR response DTOs or current dashboard
result fields. The contract selects:

```text
GET /api/performance/attribution
    ?start_date=YYYY-MM-DD
    &end_date=YYYY-MM-DD
    &scope=portfolio|account
    [&account_id=<id>]
```

This is the delivered read-only monetary-bridge endpoint; deliberately excluded attribution families remain unsupported.


<a id="c7-perf04_attribution_contract-9-61-response-shape"></a>
#### 6.1 Response shape

The normative response fields are:

| Field | Contract |
| --- | --- |
| `contract` | Constant `PERF04A`. |
| `contract_version` | Integer `1`. |
| `metric` | Constant `value_change_after_external_flows`. |
| `grain` | Constant `selected_scope`. |
| `scope` | `portfolio` or `account`. |
| `account_id` | `null` for portfolio scope; required account identity for account scope. |
| `period` | Exact requested `start_date` and `end_date`. |
| `performance_currency` | The R08 performance currency. |
| `availability` | `available` or `not_computable`. |
| `quality` | `exact` only for an available result; otherwise `unavailable`. |
| `opening_value` | Exact opening valuation money or `null`. |
| `closing_value` | Exact closing valuation money or `null`. |
| `value` | Exact money `{amount: "...", currency: "..."}` or `null`; this is the bridge result, not a return. |
| `external_flow_summary` | `{contributions, withdrawals, signed_total}` with exact money values or `null`; contribution/withdrawal amounts are non-negative magnitudes and `signed_total = contributions - withdrawals`. Explicit zero is allowed when coverage is complete and no selected external flow exists. |
| `evidence` | Sanitized projections of opening/closing valuation, scope membership, cash/in-kind coverage and external-flow coverage; it must preserve R08 statuses and reasons rather than redefine them. |
| `reason_codes` | Empty for an exact result, otherwise stable sorted reason codes. |

The response contains no `return_rate`, `annualized`, `twrr_contribution`,
`xirr_contribution`, `instrument_rows`, `asset_class_rows`, `realized_pnl`,
`unrealized_pnl`, `price_effect`, `income_effect`, `fx_effect`, or
`counterfactual` field in v1. Omitting unsupported fields is intentional;
clients must not infer them from `value`.

An available response satisfies:

```json
{
  "contract": "PERF04A",
  "contract_version": 1,
  "metric": "value_change_after_external_flows",
  "grain": "selected_scope",
  "scope": "portfolio",
  "account_id": null,
  "period": {"start_date": "2026-01-01", "end_date": "2026-02-01"},
  "performance_currency": "RUB",
  "availability": "available",
  "quality": "exact",
  "opening_value": {"amount": "1000.00", "currency": "RUB"},
  "closing_value": {"amount": "1333.50", "currency": "RUB"},
  "value": {"amount": "283.50", "currency": "RUB"},
  "external_flow_summary": {
    "contributions": {"amount": "100.00", "currency": "RUB"},
    "withdrawals": {"amount": "50.00", "currency": "RUB"},
    "signed_total": {"amount": "50.00", "currency": "RUB"}
  },
  "evidence": {
    "opening_valuation": {"availability": "available", "reason_codes": []},
    "closing_valuation": {"availability": "available", "reason_codes": []},
    "scope_membership": {"status": "complete", "reason_codes": []},
    "cash_boundary_coverage": {"status": "complete", "reason_codes": []},
    "in_kind_boundary_coverage": {"status": "complete", "reason_codes": []},
    "external_flows": {"status": "complete", "reason_codes": []}
  },
  "reason_codes": []
}
```

The example is synthetic and illustrates the shape only. It is not owner data
or a fixture. The DTO uses strict fields (`extra="forbid"` in the
existing backend convention) and exact money strings; a frontend must render
backend values and must not group, sum, allocate, interpolate or infer them.


<a id="c7-perf04_attribution_contract-9-62-owner-facing-labels"></a>
#### 6.2 Owner-facing labels

The canonical owner-facing label for the v1 metric is:

> **Изменение стоимости после внешних потоков**

The UI must append or otherwise visibly preserve:

> **Это изменение стоимости, а не доходность.**

The label must not use “доходность”, “return”, “profit”, “market return”,
“realized”, or “unrealized” for the v1 parent value. Availability and reason
codes follow existing Analytics/Freshness presentation patterns: backend owns
the state and stable code; frontend maps it to safe explanatory text and does
not display an opaque code as the primary label.


<a id="c7-perf04_attribution_contract-9-7-reference-vector-reconciliation"></a>
#### 7. Reference-vector reconciliation

The accepted synthetic vectors are discovery evidence, not production fixtures.
The following behavior is normative for the v1 bridge:

| Discovery vector | V1 bridge consequence |
| --- | --- |
| No-flow split: `1,000.00 -> 1,160.00` | Selected-scope bridge is `+160.00`. The two account/instrument rows remain discovery-only; v1 does not emit them. |
| Contribution and withdrawal: `V0=1,000.00`, `C=+100.00-50.00`, `V1=1,333.50` | Bridge is `+283.50`. The reference TWRR `27.05%` is a separate parent return and is not emitted by v1. |
| Linked transfer `A → B` | In a synthetic same-currency `100.00` vector, portfolio scope treats the resolved linked legs as internal: `V0=1,500.00`, `C=0`, `V1=1,500.00`, bridge `0.00`. An account A query uses only A's source leg as the canonical withdrawal (`C=-100.00`): `1,000.00 -> 900.00` gives bridge `0.00`. An account B query uses only B's destination leg as the canonical contribution (`C=+100.00`): `500.00 -> 600.00` gives bridge `0.00`. Each account result still requires the selected leg's identity/classification, amount, currency, membership and ordinary external-flow coverage; unresolved or one-sided transfer identity fails closed. Absence of cross-leg reconciliation evidence, an unexplained difference or an unreconciled opposite leg alone does not block an otherwise exact account bridge. Portfolio inter-leg reconciliation remains required for every relevant linked portfolio transfer; only async transit safety is evaluated at `start_date`/`end_date`, not at intermediate TWRR flow-boundary dates. |
| Retained coupon | The `+20.00` retained in-scope value is reflected once in the bridge; it is not an additional external flow or second income injection. |
| Redemption principal | A position-to-cash reclassification with unchanged selected total gives bridge `0.00`; redemption is not passive income. |
| Internal fee/tax cost | A complete opening `1,000.00`, internal cost `13.00`, closing `987.00` gives bridge `-13.00`; it is not an owner withdrawal. |
| Composition change or rebalance | Aggregate bridge may be exact if all v1 gates pass, but no instrument-level contribution is emitted without component boundary evidence and allocation. |
| Interior contribution without a TWRR boundary | For `V0=1,000.00`, an interior `C=+100.00`, and `V1=1,250.00`, endpoint and external-flow evidence satisfy v1 gates while no observed TWRR boundary exists: the bridge is exact `+150.00`; TWRR remains unavailable with `not_computable_valuation_boundary_missing`. The bridge does not choose between the compatible TWRR paths. |
| Start-date contribution with unknown endpoint ordering | For `V0=1,000.00`, `C=+100.00` on `start_date` and `V1=1,250.00`, a date-only consumed opening valuation with no accepted relation is `NOT_COMPUTABLE`, `value=null`, with `not_computable_valuation_boundary_order_unknown`. The bridge must not assume start-of-day or end-of-day inclusion. |
| End-date withdrawal or contribution with unknown endpoint ordering | For an endpoint flow on `end_date` (`C=-100.00` withdrawal or `C=+100.00` contribution), a date-only consumed closing valuation with no accepted relation is `NOT_COMPUTABLE`, `value=null`, with `not_computable_valuation_boundary_order_unknown`. The bridge must not assume start-of-day or end-of-day inclusion. |
| Endpoint flow with an explicit accepted relation | With all other gates passing, an accepted evidence binding that proves the selected endpoint flow's relation to the exact consumed `V0` or `V1` may make the unchanged bridge formula exact. The current persisted `ObservedValuationPoint` binds to a flow/group, not to the consumed monthly endpoint valuation, so this remains future/unavailable in v1 unless current evidence independently proves that binding; this vector does not authorize a schema or a new inclusion convention. |

All vector arithmetic uses the same signed-flow convention as the accepted
R08 contracts. No vector authorizes a new trade, lot, price, FX or transit
assumption.


<a id="c7-perf04_attribution_contract-9-8-reconciliation-invariants"></a>
#### 8. Reconciliation invariants

An implementation must verify these invariants before returning an exact v1
result:

1. **Parent identity:**
   `V0 + signed_external_flow_total + value_change_after_external_flows = V1`.
2. **Flow sign identity:** contribution totals are positive, withdrawal totals
   are negative, and the signed total is their exact sum at the selected scope.
3. **Scope identity:** every value and flow belongs to the same requested
   portfolio/account scope; no current-state account flag rewrites history.
4. **Currency identity:** all terms use one accepted performance currency; a
   currency label is not a conversion rate.
5. **Transfer identity:** portfolio-internal linked transfers are excluded from
   the portfolio external-flow total; account-scope legs retain their actual
   signs and dates.
6. **No double count:** retained income, redemption principal, internal cost,
   direct payout gross amounts and external boundary amounts are not injected
   twice.
7. **No false allocation:** no amount is assigned to an instrument, asset
   class, account row, trade, lot or residual cause without exact evidence at
   that grain.
8. **Null-versus-zero:** an exact zero is returned only when evidence proves
   zero; missing or unknown evidence produces unavailable/null.
9. **No return substitution:** a v1 value bridge never substitutes XIRR,
   TWRR, Modified Dietz, a benchmark result or a capital delta labelled as a
   return.

If a future dimensioned implementation cannot prove the corresponding
component identity and flow allocation, it must return the component result as
unavailable and preserve any separately valid parent value/return metric. It
must not force a rounded residual into one row.


<a id="c7-perf04_attribution_contract-9-9-deliberately-excluded-decompositions"></a>
#### 9. Deliberately excluded decompositions

The following are explicitly outside PERF04A v1:

- linked component TWRR contribution or any other percentage-point return
  attribution;
- XIRR contribution, component XIRR, or any additive annualized attribution;
- realized versus unrealized P/L by trade, lot, instrument or account;
- price, carry, coupon, dividend, redemption, fee, tax or FX contribution
  totals that claim a complete value bridge;
- Brinson/Fachler/BHB benchmark-relative attribution;
- Modified Dietz or another approximate return presented as exact;
- Shapley/Owen or another counterfactual allocation;
- inferred trades, fills, orders, acquisition lots, disposal matching or cost
  basis history;
- any known in-kind movement in the v1 result; a future contract must define
  its exact signed monetary boundary term before it can participate in a
  bridge;
- interpolated, start-of-day, end-of-day or synthetic in-transit valuations;
- a half-open interval convention for endpoint-flow inclusion without a
  separate authoritative contract;
- historical asset-class remapping or FX conversion without accepted evidence;
- client-side grouping, aggregation, allocation, formula calculation or
  reclassification; and
- export/AI-bundle or portfolio-review-package projection in the first slice.

The existing dashboard `cash_income`, realized/unrealized result fields,
capital-composition buckets and XIRR/TWRR DTOs retain their existing meanings.
PERF-04A must not relabel or widen them.

<a id="c7-perf04b_component_attribution_contract-13"></a>
### PERF04 component monetary decomposition

<a id="c7-perf04b_component_attribution_contract-13-1-decision-and-boundary"></a>
#### 1. Decision and boundary

The only supported next grain is a narrow **portfolio decomposition of the
existing PERF04A value bridge**:

```text
B_portfolio = sum(B_account) + sum(T_internal_transfer)
```

This identity is exact only when every required parent, account and transfer
reconciliation input is exact. `B` is the existing PERF04A
`value_change_after_external_flows` money amount. It is a value-change bridge,
not a return, profit, XIRR, TWRR or causal investment attribution. XIRR and
TWRR remain separate non-additive parent metrics.

`PARTIAL GO` means that this one bounded decomposition may be implemented under
strict evidence. It does **not** authorize partial rows, estimated residuals or
an apparently complete portfolio split when any required row or reconciliation
effect is unavailable.

The contract is read with the accepted [PERF04A contract](#c7-perf04_attribution_contract-9),
[PERF04 evidence matrix](#c7), [R08 availability](#c7-r08-01c-performance-availability-12),
[R08 XIRR](#c7-r08-02-portfolio-xirr-8), [R08 TWRR](#c7-r08-03-twrr-contract-recon-32),
[observed-boundary contract](#c6-r08-03a-valuation-boundaries-8), and
[Performance v1 closeout](#c7).


<a id="c7-perf04b_component_attribution_contract-13-2-parent-quantity-and-row-meaning"></a>
#### 2. Parent quantity and row meaning

For any selected scope `s`, let:

- `V0_s` and `V1_s` be the exact opening and closing valuations;
- `C_s` be the signed external-flow total from that scope's perspective;
- contributions have positive `C` and withdrawals have negative `C`; and
- `B_s` be the existing PERF04A bridge:

```text
B_s = V1_s - V0_s - C_s
V0_s + C_s + B_s = V1_s
```

At account scope, a linked transfer leg crosses that account boundary: the
source leg is a negative withdrawal and the destination leg is a positive
contribution. At portfolio scope, a fully linked transfer between historically
in-scope accounts is internal and both legs are excluded from `C_portfolio`.
A transfer crossing the selected scope boundary is an ordinary external flow,
not an internal-transfer component.

An account row is therefore an exact **account-scope PERF04A value change**
when its own evidence passes. It is not automatically an additive portfolio
share, an account return or an account investment-profit attribution.


<a id="c7-perf04b_component_attribution_contract-13-3-capability-matrix"></a>
#### 3. Capability matrix

| Grain or effect | Capability verdict | Normative limit |
| --- | --- | --- |
| Portfolio → account decomposition | **`PARTIAL GO`** | Exact only when the parent, every required account row, every in-scope internal transfer effect, endpoint sums and all inherited R08 gates pass. |
| Account | **Exact under strict evidence** | The selected account's PERF04A bridge is usable for a bounded interval under its own R08 evidence. It may be published as a portfolio component only inside a complete parent decomposition. |
| Instrument | **Unsupported** | Monthly snapshots identify stored positions but do not prove component pre/post boundary values, flow allocation, trade path or complete composition history. |
| Asset class | **Unsupported** | `instrument_type` and analytics `asset_class` are not interchangeable, and historical classification/flow allocation is not authoritative. |
| Price / FX effect | **Unsupported** | No exact price-vs-FX decomposition is selected. Currency labels or transfer reconciliation metadata do not create a performance-currency amount. |
| Realised / unrealised P&L | **Unsupported** | Existing fields remain bounded snapshot/reporting evidence, not exact trade, disposal or causal component attribution. |
| Cost basis, lots and trades | **Unsupported** | No complete execution, acquisition-lot, disposal-allocation or cost-basis history exists for this contract. |

No supported row may be inferred from a capital delta, current account flag,
instrument label, cost basis, percentage return or rounded residual.


<a id="c7-perf04b_component_attribution_contract-13-4-exact-formula-and-transfer-signs"></a>
#### 4. Exact formula and transfer signs


<a id="c7-perf04b_component_attribution_contract-13-41-account-and-portfolio-bridges"></a>
#### 4.1 Account and portfolio bridges

For account `a`:

```text
C_a = sum(account contributions) - sum(account withdrawal magnitudes)
B_account(a) = V1_a - V0_a - C_a
```

For the selected portfolio:

```text
C_portfolio = sum(external contributions) - sum(external withdrawal magnitudes)
B_portfolio = V1_portfolio - V0_portfolio - C_portfolio
```

`C_portfolio` excludes a resolved linked transfer only when both legs belong to
the historically in-scope portfolio. It includes a flow that crosses the
selected scope, including a transfer to or from an out-of-scope account.


<a id="c7-perf04b_component_attribution_contract-13-42-internal-transfer-effect"></a>
#### 4.2 Internal-transfer effect

For one fully linked internal transfer `t`, define non-negative magnitudes:

- `S_t`: exact source withdrawal leg;
- `D_t`: exact destination contribution leg; and
- `e_{t,i}`: exact non-negative transfer-specific reconciliation amounts.

`T_internal_transfer(t)` is defined only after eligibility is proven:

```text
if S_t = D_t:
    T_internal_transfer(t) = 0
elif S_t > D_t and sum(e_{t,i}) = S_t - D_t:
    T_internal_transfer(t) = D_t - S_t = -sum(e_{t,i})
else:
    T_internal_transfer(t) = unavailable
```

The second case requires accepted evidence tied exclusively to this transfer
that explains the entire difference as an internal fee, commission or tax.
The evidence and both legs must already be exact in the same accepted
performance currency. An `fx_conversion_spread` metadata row does not by itself
create an exact performance-currency amount; cross-currency conversion remains
unavailable unless a separate accepted currency contract supplies that amount.

The following are not valid transfer effects:

- `S_t > D_t` with no accepted reconciliation evidence: the decomposition is
  unavailable/null, not an exact negative residual;
- `D_t > S_t`: unavailable, because current evidence has no accepted exact
  gain primitive; and
- a one-sided, unresolved, duplicated or ambiguously scoped link: unavailable,
  even if the leg arithmetic happens to balance.

When all terms are eligible, the additive identity is:

```text
B_portfolio = sum_a B_account(a) + sum_t T_internal_transfer(t)
```

The transfer effect is a reconciliation component. It is never relabelled as
account investment performance and is never added a second time as a fee/tax
performance row.


<a id="c7-perf04b_component_attribution_contract-13-5-availability-and-fail-closed-prerequisites"></a>
#### 5. Availability and fail-closed prerequisites

The decomposition is `available`/`exact` only when **all** of the following
hold:

1. The existing PERF04A parent bridge is exact/available from its dedicated
   `perf04a_bridge_prerequisites` projection. Do not substitute the top-level
   R08 union, an XIRR solver result or a TWRR result.
2. Opening and closing dates resolve to one closed, exact valuation point for
   the portfolio and for every historically required in-scope account.
3. Every required account row is exact under account-scope PERF04A semantics:
   complete historical membership, affirmative cash-boundary coverage,
   complete canonical external-flow evidence, accepted currency and valid
   valuation components. The current-state `include_in_returns` flag cannot
   repair history.
4. The set of account rows is complete. A subset of accounts is not a
   portfolio split, even when each displayed row is individually exact.
5. Every internal transfer pair is identity-resolved, opposite-direction and
   scoped correctly. Equal legs reconcile to exact zero; unequal legs satisfy
   the evidence rule in section 4.2. Evidence is linked one-to-one and is not
   reused across transfers.
6. Portfolio and account endpoint valuations reconcile in minor units:
   `V_portfolio,t = sum(V_account,t)` for `t` equal to opening and closing.
   Any mismatch is unavailable; no residual account or transfer row is made.
7. All terms are in one accepted performance currency. Missing dated FX,
   incomplete conversion provenance or a foreign-currency reconciliation
   metadata row without an exact converted amount fails closed.
8. No known unvalued in-kind movement, unknown in-kind coverage,
   unclassified cash, membership gap/change, legacy ambiguous flow, unresolved
   transfer, unvalued transit or endpoint order ambiguity remains.
9. The minor-unit parent identity and the additive decomposition identity both
   hold exactly before any display rounding.

The existing endpoint rule remains in force: a flow or transfer on the
consumed `start_date` or `end_date` needs accepted relation/order evidence.
Strictly interior TWRR-only observed-boundary gaps do not by themselves block
this value bridge; they do not authorize a TWRR contribution or an estimate.

Failure of any prerequisite returns no decomposition number or complete row
set. The parent PERF04A/XIRR/TWRR result may remain separately valid where its
own contract permits it, but a partial account list must not be published as a
complete portfolio split.


<a id="c7-perf04b_component_attribution_contract-13-stable-reason-handling"></a>
#### Stable reason handling

Propagate the narrowest accepted R08/PERF04A reason without reclassifying it.
Applicable reasons include:

```text
not_computable_opening_valuation_missing
not_computable_closing_valuation_missing
not_computable_reporting_month_not_closed
not_computable_snapshot_date_missing
not_computable_unsupported_position_valuation
not_computable_scope_coverage_incomplete
not_computable_scope_cash_unclassified
not_computable_scope_membership_history_missing
not_computable_scope_membership_changed
not_computable_external_flows_incomplete
not_computable_currency_conversion_incomplete
not_computable_transfer_identity_unresolved
not_computable_transfer_in_transit_unvalued
not_computable_transfer_reconciliation_incomplete
not_computable_in_kind_boundary_coverage_unknown
not_computable_in_kind_movement_unvalued
not_computable_valuation_boundary_order_unknown
```

`not_computable_valuation_boundary_missing` remains a TWRR-only reason for a
strictly interior flow and is not converted into a bridge estimate. A missing
or ambiguous relation at a consumed endpoint remains bridge-blocking with
`not_computable_valuation_boundary_order_unknown`. No new catch-all reason or
residual bucket is introduced by this candidate.


<a id="c7-perf04b_component_attribution_contract-13-6-minor-unit-reconciliation-invariant"></a>
#### 6. Minor-unit reconciliation invariant

All valuations, flow totals, account bridge values and transfer effects are
integer minor units (`kopecks`) until presentation. The implementation must
verify all of these identities in integer arithmetic:

```text
V_portfolio,0 = sum(V_account,0)
V_portfolio,1 = sum(V_account,1)
sum(C_account) = C_portfolio + sum(D_t - S_t)
B_account(a) = V1_a - V0_a - C_a
B_portfolio = sum(B_account) + sum(T_internal_transfer)
```

For an unequal reconciled pair, also verify:

```text
S_t - D_t = sum(e_{t,i})
T_internal_transfer(t) = D_t - S_t
```

No intermediate term is rounded. A presentation residual is not assigned to
an account, instrument, asset class, transfer or unexplained cause.


<a id="c7-perf04b_component_attribution_contract-13-7-null-versus-zero"></a>
#### 7. Null versus zero

| Evidence state | Required result |
| --- | --- |
| All prerequisites pass and the exact arithmetic result is zero | Available exact numeric `0` in the performance currency. |
| No selected external flow, with affirmative complete coverage | Exact `C = 0`; this is not the same as unknown flow history. |
| Missing, unknown, incomplete or contradictory evidence | `not_computable`, `null`, and the applicable stable reason. |
| Source `100.00` → destination `99.00` without accepted reconciliation | `null`/unavailable; never exact `T = -1.00`. |
| Cross-currency metadata without accepted conversion | `null`/unavailable; never `0`, a foreign amount relabelled as RUB, or an estimate. |

Unknown stays unknown. An exact zero is evidence-backed, not a default for
absence of rows.


<a id="c7-perf04b_component_attribution_contract-13-8-double-count-prohibition"></a>
#### 8. Double-count prohibition

The following are mandatory:

- Exclude a fully in-scope linked transfer from `C_portfolio`, include its
  selected legs in account-scope `C_account`, and add its exact `T` once.
- Do not add the transfer's internal fee/commission/tax again to an account
  bridge, portfolio bridge or separate residual.
- Retained coupon, dividend, interest and internal cost already reflected in
  the selected valuations are counted once through `B`; they are not injected
  again as external flows or transfer effects.
- Redemption principal is a position-to-in-scope-cash reclassification, not
  passive income.
- A direct outside-scope payout uses one proven net external boundary; gross
  income and withholding evidence are explanation data, not a second flow.
- Never use a missing reconciliation, transit amount, in-kind value, FX amount,
  membership change or valuation mismatch as a catch-all residual.


<a id="c7-perf04b_component_attribution_contract-13-9-required-synthetic-reference-vectors"></a>
#### 9. Required synthetic reference vectors

All vectors below are synthetic RUB examples unless stated otherwise. They are
hand-checkable contract vectors, not owner data or production fixtures. `B_A`
and `B_B` denote exact account bridges when the row is eligible.

| Required vector | Synthetic facts | Normative result |
| --- | --- | --- |
| Equal internal transfer | `A: 1000.00 → 900.00, C_A=-100.00`; `B: 500.00 → 600.00, C_B=+100.00`; `P: 1500.00 → 1500.00, C_P=0`. | `B_A=0`, `B_B=0`, `T=100-100=0`, `B_P=0`. The resolved equal pair is internal at portfolio scope. |
| Unequal reconciled transfer | `A: 1000.00 → 900.00, C_A=-100.00`; `B: 500.00 → 599.00, C_B=+99.00`; `P: 1500.00 → 1499.00, C_P=0`; accepted `internal_fee e=1.00`. | `B_A=0`, `B_B=0`, `T=99-100=-1.00=-e`, `B_P=-1.00`. The negative effect is exact only because the entire difference is accepted reconciliation evidence. |
| Unequal unreconciled transfer | Same `100.00 → 99.00` legs and endpoint values as above, but no accepted transfer-specific evidence. | The whole portfolio decomposition (and the affected PERF04A portfolio result under current fail-closed semantics) is unavailable/null with `not_computable_transfer_reconciliation_incomplete`; do not publish exact `-1.00`. |
| Destination-gain | `A: 1000.00 → 901.00, C_A=-99.00`; `B: 500.00 → 600.00, C_B=+100.00`; `P: 1500.00 → 1501.00, C_P=0`. | The arithmetic difference is `+1.00`, but `D>S` has no accepted exact gain primitive. Decomposition is unavailable/null with `not_computable_transfer_reconciliation_incomplete`; no positive `T` is emitted. |
| Cross-scope | `A` is in scope: `1000.00 → 900.00`, one `-100.00` withdrawal to out-of-scope `B`; `P` is `1000.00 → 900.00`. | `C_P=-100.00`, so `B_P=900-1000-(-100)=0`. The flow is external at the selected portfolio boundary; no internal `T` and no out-of-scope account row. |
| Unresolved / one-sided | One unresolved source leg `A: 1000.00 → 900.00, C_A=-100.00`; no resolved destination identity. | Account/decomposition result is unavailable/null with `not_computable_transfer_identity_unresolved`; balancing arithmetic does not repair identity. |
| Endpoint transit / order ambiguity | A linked `100.00` source leg occurs on `start_date` and the `100.00` destination leg later, without a trusted consumed-endpoint valuation through transit; same-day endpoint legs also lack explicit order. | Decomposition is unavailable/null with the applicable `not_computable_transfer_in_transit_unvalued` or `not_computable_valuation_boundary_order_unknown`. No synthetic transit value or day-order convention is used. |
| Interior equal transfer | The equal `100.00` pair is strictly interior to the interval and has no observed TWRR pre/post boundary. | PERF04B may still be exact under the other gates: `T=0` and the bridge identity above holds. TWRR may independently remain unavailable; its boundary gap is not a bridge estimate. |
| In-kind | One known in-scope security movement crosses the interval; endpoint portfolio totals happen to be `1000.00 → 1000.00`, but no accepted event-date monetary value exists. | Unavailable/null with `not_computable_in_kind_movement_unvalued`; no `C=0` inference, cash surrogate or `T=0` is created. |
| Membership change | Account `A` is in scope at opening and out of scope at closing (or has a gap/overlap in effective history); illustrative values are `1000.00 → 1100.00`. | Unavailable/null with `not_computable_scope_membership_changed` or the applicable membership-history reason. No partial account split is published. |
| Unclassified cash / valuation mismatch | (a) A `50.00` portfolio cash row has no account identity; or (b) `V_portfolio=1500.00` while the proposed account endpoint sum is `1499.00`. | (a) `not_computable_scope_cash_unclassified`, not an assigned account zero; (b) unavailable/null with `not_computable_scope_coverage_incomplete` (or a narrower accepted valuation reason), with no invented `1.00` residual. |
| Cross-currency incomplete | Source leg `100.00 EUR`, destination leg `99.00 USD`, and an `fx_conversion_spread` metadata item of `1.00 EUR`, but no accepted dated conversion into performance currency. | Unavailable/null with `not_computable_currency_conversion_incomplete`. Metadata does not become `-1.00 RUB`, `0`, or an exact performance-currency effect. |
| Double-count guard | Retained internal coupon: `V0=1000.00`, `V1=1020.00`, `C=0`; separately, the reconciled `100.00 → 99.00` transfer above has `T=-1.00`. | Coupon contributes `+20.00` once through `B`; transfer contributes `-1.00` once through `T`. Adding a second `+20.00` or `-1.00` cost would be invalid. |
| Parent unavailable / account exact | `A: V0=1000.00 → V1=1100.00, C_A=0`, so isolated `B_A=+100.00`; another required account has missing closing valuation. | The isolated account result may remain exact, but the portfolio parent/decomposition is `null`/unavailable (for example `not_computable_closing_valuation_missing`). `A` is not published as a complete portfolio split. |
| Minor-unit exact reconciliation | `A: 100000 → 89999` kopecks with `C_A=-10001`; `B: 50000 → 59998` with `C_B=+9998`; `P: 150000 → 149997`, `C_P=0`; accepted fee `e=3` kopecks. | `B_A=B_B=0`; `T=9998-10001=-3` kopecks (`-0.03 RUB`); `B_P=-3` kopecks. The identity holds without decimal rounding. |


<a id="c7-perf04b_component_attribution_contract-13-10-explicitly-out-of-scope"></a>
#### 10. Explicitly out of scope

This contract does not support or authorize:

- instrument or asset-class contribution rows;
- price, FX, carry, coupon, dividend, redemption, fee or tax decomposition as
  complete economic components;
- realised/unrealised P&L by account, instrument, trade or lot;
- trade, order, fill, acquisition-lot, disposal or cost-basis reconstruction;
- additive XIRR/TWRR contributions, Modified Dietz, Brinson, Shapley,
  Owen or another counterfactual/benchmark method;
- exact monetary attribution for a known in-kind movement without a separate
  accepted non-cash valuation contract;
- cross-currency conversion inferred from labels or reconciliation metadata;
- a positive destination-gain transfer effect;
- start/end-of-day, half-open interval, interpolation or in-transit
  assumptions;
- a catch-all residual, rounded residual or partial portfolio split;
- changes to PERF04A, XIRR, TWRR, availability, endpoint-order, membership,
  flow or in-kind semantics;
- production API, frontend/UI, schema, migration, provider/network,
  background-refresh, export or AI-bundle changes; or
- private owner data, provider payloads, credentials, databases, backups or
  reconstructive evidence.

<a id="c7-perf04_reference_vectors-237"></a>
### Attribution necessary numerical counterexamples

<a id="c7-perf04_reference_vectors-237-3-synthetic-reference-vectors"></a>
#### 3. Synthetic reference vectors


<a id="c7-perf04_reference_vectors-237-vector-1--no-flow-split-across-two-accountsinstruments"></a>
#### Vector 1 — no-flow split across two accounts/instruments

| Component | Opening | Closing | Gain | Opening weight | Return contribution |
| --- | ---: | ---: | ---: | ---: | ---: |
| Account A / Instrument X | 600.00 | 720.00 | 120.00 | 0.60 | `0.60 × 20% = 12%` |
| Account B / Instrument Y | 400.00 | 440.00 | 40.00 | 0.40 | `0.40 × 10% = 4%` |
| **Portfolio** | **1,000.00** | **1,160.00** | **160.00** | **1.00** | **16%** |

There is no external flow, so `TWRR = 1,160 / 1,000 - 1 = 16%`. The exact
opening-weight contributions are `12% + 4% = 16%`. This is a clean baseline
for a no-flow linked attribution; it does not prove that the same weighting
works after flows or composition changes.


<a id="c7-perf04_reference_vectors-237-vector-2--contribution-and-withdrawal-require-boundary-segmentation"></a>
#### Vector 2 — contribution and withdrawal require boundary segmentation

| Boundary | Observed value | Signed external flow | Factor |
| --- | ---: | ---: | ---: |
| Opening | 1,000.00 | — | — |
| Before contribution | 1,100.00 | — | `1,100 / 1,000 = 1.10` |
| After contribution | 1,200.00 | `+100.00` | `1,200 / (1,100 + 100) = 1.00` |
| Before withdrawal | 1,320.00 | — | `1,320 / 1,200 = 1.10` |
| After withdrawal | 1,270.00 | `-50.00` | `1,270 / (1,320 - 50) = 1.00` |
| Closing | 1,333.50 | — | `1,333.50 / 1,270 = 1.05` |

The chained factor is `1.10 × 1.00 × 1.10 × 1.00 × 1.05 = 1.2705`, hence
`TWRR = 27.05%`. The `+100.00` and `-50.00` are capital movements, not
attribution gains. If the contribution is not evidenced at component level,
its split among accounts/instruments is unavailable rather than guessed.


<a id="c7-perf04_reference_vectors-237-vector-3--internal-transfer-a---b"></a>
#### Vector 3 — internal transfer A -> B

| State | Account A | Account B | Portfolio total |
| --- | ---: | ---: | ---: |
| Before transfer | 600.00 | 400.00 | 1,000.00 |
| After internal transfer `200.00` | 400.00 | 600.00 | 1,000.00 |
| Closing after 10% growth in each account | 440.00 | 660.00 | 1,100.00 |

At portfolio scope, the transfer is `C = 0` and `TWRR = 1,100 / 1,000 - 1
= 10%`. At account scope, A has a `-200.00` withdrawal and B a `+200.00`
contribution: `440 / (600 - 200) - 1 = 10%` and `660 / (400 + 200) - 1
= 10%`. The transfer itself contributes zero to the portfolio result. If the
legs settle on different dates and required valuation falls inside unvalued
transit, the exact metric is unavailable; no cash-in-transit line may be
invented.


<a id="c7-perf04_reference_vectors-237-vector-4--retained-coupon-versus-direct-outside-scope-payout"></a>
#### Vector 4 — retained coupon versus direct outside-scope payout

**Retained in scope.** Start with total `1,000.00`. A proven coupon of
`20.00` is retained in selected-scope cash, with no external flow, and the
closing total is `1,020.00`. Therefore `TWRR = 1,020 / 1,000 - 1 = 2%`,
`I = +20.00`, and no separate `+20.00` external flow is added.

**Paid outside scope.** A separate synthetic event has gross dividend `20.00`,
outside withholding `2.60`, and net payment `17.40` to the owner:

```text
20.00 - 2.60 = 17.40
```

The proven boundary amount is the net `17.40` withdrawal. Gross income
evidence remains an explanation and is not injected again into XIRR/TWRR;
`2.60` is not a second in-scope tax event. If the required observed pre/post
valuation boundary is absent, exact TWRR is unavailable even though the
payment arithmetic is exact. Expected/provider calendar evidence alone does
not prove the realised payout.


<a id="c7-perf04_reference_vectors-237-vector-5--redemption-remains-principal-not-passive-income"></a>
#### Vector 5 — redemption remains principal, not passive income

| State/event | Position value | In-scope cash | Selected total |
| --- | ---: | ---: | ---: |
| Opening | 500.00 | 0.00 | 500.00 |
| Principal redemption | 400.00 | 100.00 | 500.00 |
| Closing | 400.00 | 100.00 | 500.00 |

The redemption reclassifies `100.00` from position to in-scope cash. There is
no external flow and `TWRR = 0%`; passive income is `0.00`, not `100.00`.
The amount belongs in principal/cash-flow explanation, not in the income
attribution bucket.


<a id="c7-perf04_reference_vectors-237-vector-6--internal-feetax-cost-versus-owner-boundary"></a>
#### Vector 6 — internal fee/tax cost versus owner boundary

**Standalone internal cost.** Opening total `1,000.00`, an evidenced in-scope
fee is `13.00`, and closing total is `987.00`:

```text
bridge_result = 987.00 - 1,000.00 - 0.00 = -13.00
TWRR = 987.00 / 1,000.00 - 1 = -1.30%
```

The fee is `K = -13.00`, not an owner withdrawal.

**Owner payment with withholding.** A synthetic scope debit of `100.00` pays
`87.00` outside scope and remits `13.00` as an in-scope tax:

```text
100.00 = 87.00 external withdrawal + 13.00 internal tax cost
```

The external boundary is `-87.00`; no synthetic `-100.00` boundary is valid.
Without transaction-specific evidence linking gross, tax and net, the
classification is unavailable rather than inferred from a field name.


<a id="c7-perf04_reference_vectors-237-vector-7--changing-instrument-weightscomposition"></a>
#### Vector 7 — changing instrument weights/composition

| State | Instrument A | Instrument B | Instrument C | Total |
| --- | ---: | ---: | ---: | ---: |
| Opening | 800.00 | 200.00 | 0.00 | 1,000.00 |
| Observed rebalance: A -> C `300.00` | 500.00 | 200.00 | 300.00 | 1,000.00 |
| Closing | 550.00 | 190.00 | 330.00 | 1,070.00 |

Assume the rebalance is an internal same-scope trade at an observed value, not
an owner flow. The pre-rebalance segment is flat. In the post-rebalance
segment the exact component gains are `+50.00`, `-10.00`, and `+30.00`, summing
to `+70.00`; the segment and whole-period TWRR are `1,070 / 1,000 - 1 = 7%`.
The new instrument C has no opening weight, so a whole-period opening-weight
attribution for C is undefined. A future component attribution needs an
observed trade/rebalance boundary and a declared treatment of the `300.00`
composition transfer. If that observation is missing, report the component
split as unavailable while preserving any separately valid portfolio metric.


<a id="c7-perf04_reference_vectors-237-vector-8--missing-intra-period-valuation-gives-multiple-valid-answers"></a>
#### Vector 8 — missing intra-period valuation gives multiple valid answers

Observed evidence is only:

```text
opening V0 = 1,000.00
contribution C = +200.00 on an interior date
closing V1 = 1,300.00
```

Two unobserved paths satisfy exactly the same endpoints and flow:

| Path | Before flow `V−` | After flow `V+` | Chained factor | TWRR |
| --- | ---: | ---: | ---: | ---: |
| A | 1,000.00 | 1,200.00 | `1,300 / 1,200 = 13/12` | `1/12 = 8 1/3%` |
| B | 1,100.00 | 1,300.00 | `(1,100/1,000) × (1,300/1,300) = 11/10` | `10%` |

Because `8 1/3%` and `10%` are both compatible with the captured evidence,
the exact TWRR and any flow-adjacent component attribution are
`not_computable_valuation_boundary_missing`. An estimate, interpolated price,
or start/end-of-day convention would select a normative answer without
evidence.

<a id="c8"></a>

Actual deposit interest is counted once from its canonical snapshot source; generic ICF interest cannot silently become a second deposit-interest bucket. Deposit forecast is an explicitly approximate annualisation of the selected-month snapshot plus additive manual interest with component breakdown; maturity/rate changes are not modeled. Planned IIS benefits stay separate from received actual benefits; eligible_close_at is an Owner-entered control date and is not a legal eligibility determination.

## 8. Tax, IIS, actual income, goals, risk and scenarios

The actual passive-income C03 eligibility boundary and rolling average own passive-income Goal current value. This supersedes ADR 0005's old forecast-based metric while preserving its no-invented-future-date rule. Forecast C04, actual history and hypothetical shocks remain separate. Tax calculations bind year/YTD/opening context and closed-year protections; missing context is not zero. Risk shares disclose their supported denominator, including partial known subtotals.

<a id="c8-master_spec-860"></a>
### Salary, bonus, tax and IIS base rules

<a id="c8-master_spec-860-1014-зарплата-и-ндфл"></a>
#### 10.14. Зарплата и НДФЛ

Налоговые ступени хранятся в конфигурационной таблице, а не зашиваются в компоненты интерфейса.

Алгоритм:

1. взять накопленный облагаемый gross с начала года;
2. разбить текущую выплату по действующим диапазонам;
3. применить ставку к части суммы внутри каждого диапазона;
4. суммировать налог;
5. рассчитать `calculated_net`;
6. сохранить отдельно фактический net, потому что выплата работодателя может отличаться из-за вычетов и перерасчётов.

Annual opening/YTD context is explicit Owner input under the current tax contract; no historical personal seed amount is a standing requirement.

Перед реализацией конкретных ставок разработчик должен проверить действующие правила по официальному источнику. Приложение должно позволять редактировать пороги и ставки без изменения кода.


<a id="c8-master_spec-860-1015-премия"></a>
#### 10.15. Премия

Премия хранится как отдельная фактическая выплата.

Нормализованный показатель:

```text
normalized_bonus_monthly = sum(bonuses for selected 12m period) / 12
```

Он используется только для аналитики и не подмешивается в фактический денежный поток других месяцев.


<a id="c8-master_spec-860-1016-иис"></a>
#### 10.16. ИИС

Показываются два результата:

```text
portfolio_result_without_tax_benefit
portfolio_result_with_tax_benefit =
    portfolio_result_without_tax_benefit
  + received_tax_benefits
```

Планируемый, но ещё не полученный вычет показывается отдельно и не прибавляется к фактическому результату.

---

<a id="c8-0002-opening-ytd-gross-21"></a>
### Opening tax YTD selection and double-count prevention

<a id="c8-0002-opening-ytd-gross-21-решение"></a>
#### Решение


<a id="c8-0002-opening-ytd-gross-21-1-вводится-годовой-opening-tax-context"></a>
#### 1. Вводится годовой opening tax context

Для каждого календарного года допускается не более одного runtime-контекста `salary_tax_year_context` со следующей семантикой:

- `tax_year` — календарный год;
- `effective_from_month` — первый месяц, начиная с которого месячная история приложения становится каноническим источником gross для расчёта НДФЛ, `1..12`;
- `opening_taxable_gross_kopecks` — накопленный облагаемый gross **с 1 января этого года до начала `effective_from_month`**, не включая сам `effective_from_month`.

Пример семантики:

```text
tax_year = 2031
effective_from_month = 5
opening_taxable_gross = 400000.00 RUB
```

означает: для расчётов с мая 2031 года известно, что облагаемый gross за январь–апрель 2031 года суммарно равен 400 000 ₽. Начиная с мая источником новых сумм становятся `reporting_months` и `income_entries`.


<a id="c8-0002-opening-ytd-gross-21-2-единицы-и-точность"></a>
#### 2. Единицы и точность

- В persistence `opening_taxable_gross` хранится как integer kopecks (`BigInteger` или эквивалентная точная схема проекта).
- В API и private seed сумма передаётся decimal string в RUB, например `"400000.00"`.
- `float` не используется.
- Значение не может быть отрицательным.
- Если `effective_from_month = 1`, `opening_taxable_gross` обязан быть равен нулю: внутри календарного года нет периода до января.


<a id="c8-0002-opening-ytd-gross-21-3-состав-налоговой-базы-не-меняется-этой-задачей"></a>
#### 3. Состав налоговой базы не меняется этой задачей

Opening value покрывает **ровно ту же налоговую базу, которую использует текущий salary-tax service**.

На момент принятия ADR это `gross_amount_kopecks` записей `IncomeType.SALARY`.

`BONUS`, `SIDE_INCOME`, инвестиционные доходы и иные налоговые базы не включаются автоматически. Если их участие в общей налоговой базе потребуется позже, это отдельное изменение финансового контракта и отдельная task-card.


<a id="c8-0002-opening-ytd-gross-21-4-нормативный-алгоритм-выбора-ytd-для-месяца-m"></a>
#### 4. Нормативный алгоритм выбора YTD для месяца `M`

Сначала вычисляется `payment_gross` как сумма `SALARY` gross текущего reporting month.

Далее application service обязан использовать **ровно следующий алгоритм**:

```text
if payment_gross == 0:
    return zero tax result without requiring complete prior history

if M == January:
    ytd_gross_before_payment = 0

else if opening context exists AND M >= effective_from_month:
    require every calendar month in [effective_from_month, M) to be a known month
    ytd_gross_before_payment =
        opening_taxable_gross
        + SUM(SALARY gross for known months in [effective_from_month, M))

else:
    require every calendar month in [January, M) to be a known month
    ytd_gross_before_payment =
        SUM(SALARY gross for known months in [January, M))

if any required prior month is not known:
    fail with salary_tax_history_incomplete
```

Текущая выплата месяца `M` в `ytd_gross_before_payment` не входит; она передаётся в pure-domain calculator как `payment_gross` и разбивается по налоговым ступеням поверх рассчитанного YTD.

Opening gross учитывается ровно один раз.

Алгоритм выше является нормативным и имеет приоритет над более общими пояснениями ниже.


<a id="c8-0002-opening-ytd-gross-21-5-что-такое-known-month"></a>
#### 5. Что такое known month

Для целей salary-tax history календарный месяц считается **known month** только если одновременно выполняются условия:

1. существует соответствующий `reporting_month` того же календарного года и месяца;
2. его статус — `closed`.

Само наличие строки `reporting_month` со статусом `draft` не доказывает, что отсутствие `SALARY` означает известный ноль: данные могли быть ещё не внесены.

Для закрытого месяца сумма `SALARY gross` определяется как сумма всех его `IncomeType.SALARY` entries. Если таких entries нет, это считается **известным нулём**, потому что `closed` является явным пользовательским подтверждением завершённости месяца.

Если ранее закрытый месяц сделан `reopen` и снова имеет статус `draft`, он немедленно перестаёт быть known month для расчётов последующих месяцев. До повторного `close` ненулевой salary-tax расчёт, зависящий от него, обязан возвращать `salary_tax_history_incomplete`.

Статус текущего месяца `M` не используется как условие известности его собственной выплаты: `payment_gross` берётся из текущих entries, а completeness проверяется только для **предыдущих** месяцев, входящих в YTD.


<a id="c8-0002-opening-ytd-gross-21-6-source-of-truth"></a>
#### 6. Source of truth

После загрузки данных runtime source of truth — строка в SQLite `salary_tax_year_context` плюс месячные `income_entries` после `effective_from_month` с учётом правила known month.

`data/private_seed.json` является только способом начальной локальной загрузки. После seed он не читается при каждом расчёте и не конкурирует с данными БД.

`app_settings` не используется для этого значения: opening YTD является годовым налоговым контекстом, а не глобальной настройкой приложения.


<a id="c8-0002-opening-ytd-gross-21-7-private-seed"></a>
#### 7. Private seed

Private seed расширяется необязательным массивом, например:

```json
{
  "salary_tax_opening_contexts": [
    {
      "tax_year": 2031,
      "effective_from_month": 5,
      "opening_taxable_gross": "400000.00"
    }
  ]
}
```

Точный пользовательский файл остаётся только локально и исключён из Git.

Публичный `private_seed.example.json` использует только синтетические значения.

Добавление необязательного поля не должно ломать существующие seed-файлы без этого поля; отсутствие opening context не трактуется автоматически как известный ноль.

Текущая публичная schema использует `additionalProperties: false`, поэтому R02-03 обязана явно расширить `docs/schemas/private_seed.schema.json`. Нужно ли повышать `schema_version` при обратно совместимом optional-поле — техническое решение R02-03, а не изменение финансовой семантики.


<a id="c8-0002-opening-ytd-gross-21-8-missing-context-не-равен-нулю"></a>
#### 8. Missing context не равен нулю

Если расчётный месяц содержит ненулевой `SALARY` gross, а приложению неизвестен полный YTD до этого месяца по нормативному алгоритму §4, сервис не имеет права молча подставить `0` или частичную сумму.

Для месяца с `payment_gross = 0` разрешён нулевой tax result без требования полного YTD, поскольку неизвестный YTD не меняет налог на нулевую выплату.

Для ненулевой выплаты при неполной истории application service **обязан** завершить расчёт доменной/application ошибкой с кодом:

```text
salary_tax_history_incomplete
```

Этот код является частью обязательного контракта R02-03, а не рекомендацией. Generic `ValueError`, иной error code или fallback к `0` не соответствуют ADR. UI/API не должны показывать такой расчёт как точный.


<a id="c8-0002-opening-ytd-gross-21-9-добавление-более-ранних-reporting-months-и-защита-от-double-count"></a>
#### 9. Добавление более ранних reporting months и защита от double count

Месяцы раньше `effective_from_month` считаются уже агрегированными внутри `opening_taxable_gross` для расчётов после этой границы.

Если пользователь позже создаёт или импортирует март/апрель при `effective_from_month = 5`:

- эти записи могут храниться для истории и аналитики;
- они **не добавляются повторно** к YTD мая и последующих месяцев;
- opening context не пересчитывается автоматически;
- расчёт НДФЛ для самого месяца, который лежит раньше `effective_from_month`, не может использовать baseline, содержащий этот же месяц: для него применяется ветка алгоритма без opening context и требуется известная закрытая история с января до этого месяца.

Чтобы сделать добавленные ранние месяцы каноническим источником налоговой истории для расчётов после baseline boundary, владелец должен явно изменить opening context: передвинуть `effective_from_month` назад и соответственно изменить `opening_taxable_gross`, либо перейти на полную историю с января и нулевой opening суммой.

Автоматически вычитать добавленный месяц из baseline запрещено: приложение не знает, совпадает ли его записанный gross с тем, что было включено в исходный opening total.


<a id="c8-0002-opening-ytd-gross-21-10-минимальный-persistenceapi-contract-для-r02-03"></a>
#### 10. Минимальный persistence/API contract для R02-03

Рекомендуемая таблица:

```text
salary_tax_year_contexts
- tax_year                         INTEGER PRIMARY KEY / UNIQUE
- effective_from_month             INTEGER NOT NULL CHECK 1..12
- opening_taxable_gross_kopecks    BIGINT NOT NULL CHECK >= 0
- created_at / updated_at          по действующим conventions проекта
```

Минимальный HTTP contract:

```text
GET    /api/salary-tax/years/{year}/opening-context
PUT    /api/salary-tax/years/{year}/opening-context
DELETE /api/salary-tax/years/{year}/opening-context
```

`PUT` принимает:

```json
{
  "effective_from_month": 5,
  "opening_taxable_gross": "400000.00"
}
```

Сумма в API — decimal string RUB. `PUT` является create-or-replace для одного календарного года.

`DELETE` удаляет только opening context. После удаления расчёты с неполной историей должны становиться `salary_tax_history_incomplete`, а не использовать скрытый fallback `0`.


<a id="c8-0002-opening-ytd-gross-21-11-migrationbackward-compatibility-для-010"></a>
#### 11. Migration/backward compatibility для 0.1.0

Alembic migration создаёт новую таблицу, но **не создаёт opening rows из догадок**.

Для существующей БД `0.1.0`:

- существующие `reporting_months`, income entries и tax brackets не меняются;
- никакая историческая сумма не вычисляется автоматически из отсутствующих месяцев;
- если история начинается после января, до явного seed/API заполнения контекста расчёт ненулевой зарплаты должен сообщать `salary_tax_history_incomplete`;
- если полная непрерывная **закрытая** история начинается с января, opening row не обязателен;
- существующий draft-месяц не считается доказательством известной нулевой зарплаты для последующих месяцев.

Это намеренно fail-closed поведение: лучше явно показать недостаточность данных, чем сохранить правдоподобный, но неверный налог.


<a id="c8-0002-opening-ytd-gross-21-контрольные-примеры"></a>
#### Контрольные примеры


<a id="c8-0002-opening-ytd-gross-21-a-история-начинается-в-мае"></a>
#### A. История начинается в мае

```text
opening: Jan–Apr = 400 000
May salary = 100 000
```

Для May:

```text
ytd_before_payment = 400 000
payment_gross = 100 000
```

Для расчёта May не требуется, чтобы сам May уже был `closed`: completeness относится только к предыдущим месяцам.


<a id="c8-0002-opening-ytd-gross-21-b-июнь-после-opening-context"></a>
#### B. Июнь после opening context

```text
opening Jan–Apr = 400 000
May reporting month = CLOSED
May salary = 100 000
June salary = 100 000
```

Для June:

```text
ytd_before_payment = 400 000 + 100 000 = 500 000
payment_gross = 100 000
```


<a id="c8-0002-opening-ytd-gross-21-c-may-существует-но-остаётся-draft"></a>
#### C. May существует, но остаётся draft

```text
opening Jan–Apr = 400 000
May reporting month = DRAFT
May salary entry отсутствует
June salary = 100 000
```

Для June May не является known month. Результат:

```text
salary_tax_history_incomplete
```

May нельзя молча интерпретировать как нулевую зарплату только потому, что строка reporting month существует.


<a id="c8-0002-opening-ytd-gross-21-d-позже-добавили-april"></a>
#### D. Позже добавили April

Opening context остаётся `Jan–Apr = 400 000`, `effective_from_month = 5`.

Добавленный April salary не прибавляется ещё раз к YTD May/June. Чтобы перейти на детальную историю April как source of truth, baseline меняется явно.


<a id="c8-0002-opening-ytd-gross-21-e-история-начинается-в-мае-context-отсутствует"></a>
#### E. История начинается в мае, context отсутствует

При ненулевой зарплате May расчёт не выполняется как будто YTD равен нулю; возвращается `salary_tax_history_incomplete`.


<a id="c8-0002-opening-ytd-gross-21-f-полная-история-без-opening-context"></a>
#### F. Полная история без opening context

Для July без opening context January–June должны все существовать и быть `closed`. Только тогда YTD July равен сумме их `SALARY gross`. Если хотя бы один месяц отсутствует или `draft`, результат — `salary_tax_history_incomplete`.

<a id="c8-0006-tax-brackets-administration-15"></a>
### Whole-year tax brackets and CLOSED locks

<a id="c8-0006-tax-brackets-administration-15-decision"></a>
#### Decision


<a id="c8-0006-tax-brackets-administration-15-1-version-and-effective-period"></a>
#### 1. Version and effective period

For v0.2, the configuration unit is one complete tax-bracket rule set per calendar tax year.

- `tax_brackets.year` is the rule-set version/effective key.
- A set for year `Y` is effective from `Y-01-01` through `Y-12-31`.
- Mid-year versions/effective dates are not modeled in v0.2.
- If a future legal change requires two scales inside one calendar year, that requires a new schema/ADR; the UI must not pretend that the current year-only model can represent it.


<a id="c8-0006-tax-brackets-administration-15-2-source-classification"></a>
#### 2. Source classification

The API exposes a semantic source label for the effective values:

- `official_default` — the effective set exactly matches the built-in official progressive scale used by Hermes Finance;
- `manual_configuration` — the effective set differs from that scale.

This is a classification of the effective values, not a historical audit trail of who changed them.

The API also exposes `contract_version = "tax_brackets_year_v1"`.


<a id="c8-0006-tax-brackets-administration-15-3-historical-lock"></a>
#### 3. Historical lock

A tax year is mutable only while it has no `reporting_month` with status `closed`.

If at least one closed reporting month exists in that year:

- create/update/delete/replace operations for the year fail closed;
- the API returns HTTP 409 with machine code `tax_brackets_year_locked`;
- the response identifies the closed months that lock the year;
- existing rules remain unchanged.

A `draft` month does not lock the year.

To deliberately change rules for a year that already contains closed months, the owner must explicitly reopen all closed months in that year first. That makes the historical recalculation visible and intentional; after the months are closed again, the year is locked again.


<a id="c8-0006-tax-brackets-administration-15-4-public-mutation-is-whole-set-replacement"></a>
#### 4. Public mutation is whole-set replacement

R02-17 does not expose public row-by-row bracket CRUD.

The public write operation replaces the complete set for one year atomically. This avoids intermediate invalid configurations and makes the user's intent explicit.

A valid complete set must:

- contain at least one bracket;
- start at exactly `0` kopecks;
- contain non-negative thresholds;
- be strictly contiguous: no gaps and no overlaps;
- have a finite upper bound on every bracket except the final one;
- have an open-ended final bracket (`threshold_to = null`);
- use integer basis-point rates in the range `0..10000` inclusive;
- use exact integer kopecks / `MoneyValue` decimal strings; binary float is forbidden.

Replacement happens in one transaction. Validation or lock failure leaves the previous set untouched.


<a id="c8-0006-tax-brackets-administration-15-5-read-behavior-and-defaults"></a>
#### 5. Read behavior and defaults

`GET /api/tax-brackets/{year}` returns the effective complete set for the year.

If no rows exist yet, the API may project the built-in official default set without requiring a write. Salary-tax calculation may continue to persist defaults through its existing compatibility path.

The response includes:

- tax year;
- effective-from/effective-to dates;
- source classification;
- contract version;
- whether the year is mutable;
- closed months that lock it;
- the ordered bracket list.


<a id="c8-0006-tax-brackets-administration-15-6-salary-tax-calculation"></a>
#### 6. Salary-tax calculation

R02-17 does not change the progressive-tax formula, opening-YTD contract, or known-month rules.

For a reporting month, salary tax still uses the effective bracket set for that reporting month's calendar year.

Changing a mutable year's brackets changes draft calculations for that year immediately. Closed months prevent such a change until explicitly reopened.


<a id="c8-0006-tax-brackets-administration-15-7-ui"></a>
#### 7. UI

Tax-bracket administration lives in Settings.

The UI must:

- show the selected tax year and its effective period;
- show whether values are the official default or a manual configuration;
- show all ranges and rates in user-facing Russian labels;
- allow editing only when `mutable=true`;
- explain that closed months lock a tax year;
- show the locking months when immutable;
- submit the complete set in one save operation;
- surface validation/409 errors without exposing raw internal identifiers as the primary message.


<a id="c8-0006-tax-brackets-administration-15-8-audit-expectations-for-v02"></a>
#### 8. Audit expectations for v0.2

No general immutable change-history table is added in v0.2.

Historical safety is provided by:

1. year-scoped rule sets;
2. whole-set atomic replacement;
3. explicit API/UI source/effective-period metadata;
4. hard lock whenever closed reporting months exist.

If later releases need multiple legal versions per year, author identity, or an immutable change ledger, that is a separate persistence design.

<a id="c8-0008-passive-income-history-eligibility-17"></a>
### One actual-income eligibility boundary

<a id="c8-0008-passive-income-history-eligibility-17-decision"></a>
#### Decision


<a id="c8-0008-passive-income-history-eligibility-17-1-one-canonical-global-lower-boundary"></a>
#### 1. One canonical global lower boundary

Introduce one logical application setting:

```text
passive_income_history_start_month: YYYY-MM | null
```

User-facing label:

```text
Учитывать пассивный доход начиная с
```

The value is a calendar reporting-month key, not a snapshot date and not a foreign key to a particular row. It is therefore valid even if that calendar month does not currently have a `reporting_month` record.

`null` means **no lower boundary**: all otherwise eligible historical months are considered. This is the backward-compatible legacy behavior.

The boundary is inclusive:

```text
(year, month) >= passive_income_history_start_month
```


<a id="c8-0008-passive-income-history-eligibility-17-2-eligibility-is-independent-of-amount"></a>
#### 2. Eligibility is independent of amount

A reporting month is eligible for historical passive-income calculations iff:

1. it satisfies the existing consumer's reporting-month scope;
2. its status is `closed`;
3. the boundary is `null`, or its `(year, month)` is on/after the configured boundary.

The amount does not affect eligibility.

Therefore:

- an eligible CLOSED month with `0 ₽` passive income **is included**;
- an eligible CLOSED month with negative net passive income **is included**;
- a pre-boundary CLOSED month is excluded even when it has non-zero passive income;
- DRAFT/open months are excluded;
- a reopened month immediately becomes ineligible until it is closed again;
- closing it again restores eligibility if it is on/after the boundary.

There is no per-month exclusion flag in 0.3.


<a id="c8-0008-passive-income-history-eligibility-17-3-missing-calendar-months-are-not-zeroes"></a>
#### 3. Missing calendar months are not zeroes

The boundary does not create synthetic months.

If a calendar month has no CLOSED `reporting_month`, it contributes neither a zero nor a denominator slot. Gaps remain gaps.

The rolling window is the latest **12 eligible CLOSED reporting-month records**, ordered by `(year, month)`, not 12 calendar slots and not a calendar-year average.

Before 12 eligible CLOSED months exist:

```text
actual_passive_income_avg =
    sum(actual_net_passive_income for eligible available months)
    / count(eligible available months)
```

After 12 eligible CLOSED months exist, only the latest 12 eligible CLOSED months participate.

Money remains integer minor units / `Decimal` with `ROUND_HALF_UP`; binary `float` remains forbidden.


<a id="c8-0008-passive-income-history-eligibility-17-4-backward-compatibility-and-migration"></a>
#### 4. Backward compatibility and migration

R03-17 must add the persisted setting without silently changing existing results.

Normative migration/default behavior:

- existing databases migrate with `passive_income_history_start_month = null`;
- new databases also default to `null`;
- `null` preserves the pre-R03-17 calculation exactly;
- no migration infers a start month from existing data, first non-zero passive income, first position, salary history, file timestamps or private owner values;
- changing the boundary is an explicit owner action and may intentionally change historical averages/forecast components;
- clearing the setting returns to all-history eligibility.

Because the default leaves outputs unchanged, the migration itself does not reinterpret any existing CLOSED month.


<a id="c8-0008-passive-income-history-eligibility-17-5-one-eligibility-source-for-all-derived-historical-passive-income-consumers"></a>
#### 5. One eligibility source for all derived historical passive-income consumers

The lower-bound selector must be implemented once in backend/application logic and reused. Frontend code must not reimplement the filter.

It applies to:


<a id="c8-0008-passive-income-history-eligibility-17-c03-actual-passive-income-rolling-average"></a>
#### C03 actual passive-income rolling average

The canonical average uses only eligible CLOSED months before the existing last-12 calculation.


<a id="c8-0008-passive-income-history-eligibility-17-passive-income-goal-current-valueprogress"></a>
#### Passive-income Goal current value/progress

Per R02-27, passive-income Goal `current_value` and `progress_pct` use the C03 rolling average of actual net passive income. They therefore inherit the exact same eligibility boundary automatically. No separate Goal setting/filter is allowed.

R03-16 does not change capital-goal semantics or the goal-achievement trajectory contract.


<a id="c8-0008-passive-income-history-eligibility-17-c04-actual-dividend-history-component"></a>
#### C04 actual-dividend history component

The forecast's dividend component is based on actual net dividends from CLOSED months and reuses the same rolling-average semantics. The same eligibility boundary must be applied to those actual dividend months before the last-12 calculation.

This boundary does **not** filter forward-looking `expected_cash_flows` for coupons, deposit interest or other expected capital income. Their existing forecast-window contract remains unchanged.


<a id="c8-0008-passive-income-history-eligibility-17-owner-facing-passive-income-history-presentation"></a>
#### Owner-facing passive-income history presentation

Any UI that presents a historical passive-income series specifically as the basis for the rolling average should use the backend-provided eligible history or clearly mark pre-boundary months as excluded. It must not visually imply that a pre-boundary month contributes to `N из 12`.

Per-month actual passive-income calculation remains available for older months; the boundary does not delete or rewrite historical rows.

Capital-history/analytics eligibility is unrelated and remains unchanged.


<a id="c8-0008-passive-income-history-eligibility-17-6-existing-consumer-upper-boundas-of-semantics-are-not-redefined-here"></a>
#### 6. Existing consumer upper-bound/as-of semantics are not redefined here

R03-16 defines only the new **lower eligibility boundary**. If a consumer already has an accepted upper/as-of scope, it keeps that scope and applies the lower boundary inside it.

R03-17 must not use this task as permission to redesign historical as-of semantics of Dashboard/Goals/exports beyond what their existing contracts require.


<a id="c8-0008-passive-income-history-eligibility-17-7-ui-and-read-contract-metadata"></a>
#### 7. UI and read-contract metadata

R03-17 must expose enough backend-derived metadata for UI/help text without recalculating financial logic in React.

At minimum the relevant read result(s) must make available:

```text
count_months
is_complete_12m
configured_start_month: YYYY-MM | null
months_used: ordered reporting-month keys, or equivalent backend-derived window metadata
```

The UI may summarize this as, for example:

```text
Среднее за 5 закрытых месяцев из 12 · учёт с мая 2026
```

or, with no boundary:

```text
Среднее за 5 закрытых месяцев из 12 · вся доступная история
```

When zero eligible CLOSED months exist, the UI must state that there are no closed months in the selected accounting period; it must not describe that state as a measured `0 ₽` month.

The setting belongs to Settings/financial-method preferences (or an equivalent single canonical settings surface). The same setting must not be duplicated independently on Dashboard and Goals.


<a id="c8-0008-passive-income-history-eligibility-17-8-boundary-changes-do-not-mutate-reporting-data"></a>
#### 8. Boundary changes do not mutate reporting data

Updating or clearing `passive_income_history_start_month`:

- does not open/close/reopen reporting months;
- does not alter `investment_cash_flows`, deposit snapshots or income rows;
- does not rewrite previously stored monthly passive-income inputs;
- only changes which already-readable historical CLOSED months are eligible for derived historical metrics.


<a id="c8-0008-passive-income-history-eligibility-17-normative-examples"></a>
#### Normative examples


<a id="c8-0008-passive-income-history-eligibility-17-example-a--technical-salary-history-before-real-passive-tracking"></a>
#### Example A — technical salary history before real passive tracking

CLOSED months and actual passive income:

```text
Jan  0
Feb  0
Mar  0
Apr  0
May  10 000
Jun  0
Jul  20 000
```

Configured boundary:

```text
2026-05
```

Eligible months are May, Jun, Jul. June is a genuine eligible zero.

```text
average = (10 000 + 0 + 20 000) / 3 = 10 000
count_months = 3
```

Jan-Apr do not participate.


<a id="c8-0008-passive-income-history-eligibility-17-example-b--more-than-12-eligible-months"></a>
#### Example B — more than 12 eligible months

There are 14 eligible CLOSED months on/after the boundary.

Only the chronologically latest 12 eligible CLOSED records participate. The first two eligible records fall out of the rolling window.


<a id="c8-0008-passive-income-history-eligibility-17-example-c--gap-draft-and-reopen"></a>
#### Example C — gap, draft and reopen

Boundary is `2026-05`.

```text
May  CLOSED  10 000
Jun  missing
Jul  DRAFT   15 000
Aug  CLOSED  20 000
```

Window initially contains May and Aug only:

```text
count_months = 2
average = 15 000
```

If Jul is CLOSED, it joins the eligible window. If May is then reopened, May immediately disappears until reclosed. June never becomes an implicit zero.


<a id="c8-0008-passive-income-history-eligibility-17-example-d--boundary-after-all-closed-history"></a>
#### Example D — boundary after all closed history

If the boundary is later than every CLOSED reporting month:

```text
count_months = 0
is_complete_12m = false
```

The UI reports no eligible closed history. No month is fabricated and no stored data is changed.


<a id="c8-0008-passive-income-history-eligibility-17-example-e--dividend-forecast-component"></a>
#### Example E — dividend forecast component

Pre-boundary months contain no reliable dividend tracking. On/after the boundary, eligible CLOSED months have actual net dividends:

```text
May  3 000
Jun  0
Jul  9 000
```

The C04 dividend average uses these three eligible months, including June's genuine zero, and annualises that average according to the existing forecast contract. Pre-boundary technical-history months do not depress the dividend component.

<a id="c8-0005-goal-achievement-forecast-22"></a>
### Goal attainment limits and result contract

<a id="c8-0005-goal-achievement-forecast-22-decision"></a>
#### Decision


<a id="c8-0005-goal-achievement-forecast-22-1-forecast-method-is-explicitly-versioned"></a>
#### 1. Forecast method is explicitly versioned

R02-12 introduces a separate goal-achievement method version:

```text
goal_achievement_v1
```

This is independent from the dashboard/monthly-summary `calculation_version` and from the expected-cash-flow `forecast_version`.

R02-12 does **not** change an existing financial formula, so it must not bump the global monthly-summary `calculation_version` merely for adding this new derived result.


<a id="c8-0005-goal-achievement-forecast-22-2-v1-does-not-invent-a-future-growth-trajectory"></a>
#### 2. v1 does not invent a future growth trajectory

`goal_achievement_v1` is deliberately conservative.

For a goal whose current canonical metric can be resolved:

- if `current_value >= target_value`, the goal is considered **achieved as of the selected reporting snapshot**;
- the returned `estimated_achievement_date` is the selected `ReportingMonth.snapshot_date`;
- this means "the goal is met at this snapshot, therefore no later than this date" and does **not** claim to identify the historical first-crossing date;
- if `current_value < target_value`, v1 returns no future date because the application has no canonical trajectory model.

The below-target result must therefore be:

```text
estimated_achievement_date = null
reason_code = "no_trajectory_model"
```

The backend must not extrapolate from recent history, assume regular contributions, assume a return rate, or use `target_date` as if it were a prediction.


<a id="c8-0005-goal-achievement-forecast-22-3-goal-type--calculation-mode-support-matrix"></a>
#### 3. Goal-type / calculation-mode support matrix

The forecast is determined by the pair `(goal_type, calculation_mode)`, not by a free-form interpretation of the goal name.

| Goal type | Calculation mode | Current metric | v1 achievement-date behavior |
|---|---|---|---|
| `passive_income` | `monthly_net_passive_income` | canonical actual C03 `passive_income_average` | supported current-state check; future date is `null` when below target |
| `capital` | `liquid_capital_net` | canonical `liquid_capital_for_month(...).liquid_capital_net` | supported current-state check; future date is `null` when below target |
| `expense_coverage` | any | — | unsupported in v1 |
| `mortgage_coverage` | any | — | unsupported in v1 |
| `other` | any | — | unsupported in v1 |
| `passive_income` / `capital` | any other mode | — | unsupported calculation mode |

Coverage goal types are unsupported because the current `goals.target_value_kopecks` storage/API is a money value, while coverage is naturally percentage/ratio semantics. R02-12 must not silently reinterpret money as a percentage. A future typed-target contract may enable those goal types.


<a id="c8-0005-goal-achievement-forecast-22-4-canonical-actual-c03-passive-income-metric"></a>
#### 4. Canonical actual C03 passive-income metric

For `passive_income + monthly_net_passive_income`, use the canonical actual C03 rolling average over the last 12 eligible CLOSED records, with the inclusive global eligibility boundary. This replaces the original forecast basis under ADR 0008/R02-27. Zero/negative eligible months participate; missing/DRAFT/reopened months do not; zero eligible count means no history. Forward expected flows and scenario forecast shocks never change actual progress. Carry its availability/coverage/reasons.


<a id="c8-0005-goal-achievement-forecast-22-5-canonical-capital-metric"></a>
#### 5. Canonical capital metric

For `capital + liquid_capital_net`, current value is:

```text
liquid_capital_for_month(session, reporting_month_id).liquid_capital_net
```

No trend is inferred from historical capital points in v1.


<a id="c8-0005-goal-achievement-forecast-22-6-exact-progress-and-remaining-amount"></a>
#### 6. Exact progress and remaining amount

For supported modes, backend returns:

```text
remaining_amount = max(target_value - current_value, 0)
```

and:

```text
progress_pct = current_value / target_value * 100
```

`progress_pct` uses `Decimal`, is quantized to `0.01`, and uses the existing financial `ROUND_HALF_UP` convention.

If `target_value == 0`, `progress_pct = null` to preserve the existing safe-zero-denominator behavior. A nonnegative current metric still means the zero target is achieved.

Money arithmetic uses integer kopecks / `RubleAmount`; binary `float` is forbidden.


<a id="c8-0005-goal-achievement-forecast-22-7-inactive-goals"></a>
#### 7. Inactive goals

An inactive goal is not actively tracked and therefore has no achievement forecast.

For inactive goals:

```text
status = "inactive"
estimated_achievement_date = null
reason_code = "goal_inactive"
current_value = null
remaining_amount = null
progress_pct = null
```

No financial calculator needs to run solely for an inactive goal.


<a id="c8-0005-goal-achievement-forecast-22-8-unsupported-goals-and-modes"></a>
#### 8. Unsupported goals and modes

For unsupported goal types:

```text
status = "unsupported"
reason_code = "unsupported_goal_type"
```

For a supported goal type with a noncanonical `calculation_mode`:

```text
status = "unsupported"
reason_code = "unsupported_calculation_mode"
```

In both cases:

- `estimated_achievement_date = null`;
- `current_value = null`;
- `remaining_amount = null`;
- `progress_pct = null`;
- the API includes a short user-displayable warning.

R02-12 must not change the R02-11 write contract to reject existing free-form calculation modes. Unsupported modes remain readable and are reported honestly.


<a id="c8-0005-goal-achievement-forecast-22-9-target_date-is-a-deadline-not-a-model-input"></a>
#### 9. `target_date` is a deadline, not a model input

`Goal.target_date` remains the user's desired/declared target date.

R02-12 does not use `target_date` to manufacture `estimated_achievement_date`, assume the goal will be achieved by the requested deadline, or derive a required monthly return/contribution from it.

The UI may later compare the declared target date with a non-null forecast, but that comparison is outside the v1 forecast formula.


<a id="c8-0005-goal-achievement-forecast-22-10-normative-result-contract"></a>
#### 10. Normative result contract

The pure domain/service result must expose enough information that React performs no financial calculation:

```text
GoalAchievementForecastResult
- goal_id: int
- reporting_month_id: int
- as_of_date: date
- method_version: "goal_achievement_v1"
- source_forecast_version: string | null
- status: "achieved" | "not_projectable" | "inactive" | "unsupported"
- reason_code: string | null
- current_value: RubleAmount | null
- target_value: RubleAmount
- remaining_amount: RubleAmount | null
- progress_pct: Decimal | null
- estimated_achievement_date: date | null
- is_approximate: bool
- warnings: tuple[str, ...]
```

For supported active goals:

- `status="achieved"` when `current_value >= target_value`;
- `status="not_projectable"` when `current_value < target_value`;
- `reason_code=null` when achieved;
- `reason_code="no_trajectory_model"` when below target.

`source_forecast_version` is `null` for the supported actual C03/capital summaries. The request forecast-version parameter remains a compatibility input; it does not select actual Goal progress or supply a future trajectory.


<a id="c8-0005-goal-achievement-forecast-22-11-api-contract"></a>
#### 11. API contract

Keep the R02-11 CRUD DTOs and write endpoints unchanged.

Add a read-only bulk summary endpoint for R02-13:

```text
GET /api/goals/summary
    ?reporting_month_id=<required int>
    &include_inactive=<bool, default false>
    &forecast_version=<string, default current canonical forecast version>
```

The response is a list of goal records plus a nested backend-derived `achievement_forecast` object matching the normative result contract. Money uses the existing `MoneyValue` decimal-string shape; percentages are decimal strings; dates are ISO dates.

Because the existing router already has `GET /api/goals/{goal_id}`, the static `/summary` route must be registered before the dynamic `/{goal_id}` route (or otherwise be structured so `summary` cannot be shadowed and parsed as a goal id).

The endpoint must compute shared source metrics once per request where practical (for example one canonical C03 actual passive-income average and one liquid-capital result), not once per goal via an N+1 calculator loop.

Existing `GET /api/goals`, `GET /api/goals/{id}`, `POST`, `PATCH`, and `DELETE` remain source-of-truth CRUD endpoints and do not require a reporting month.


<a id="c8-0005-goal-achievement-forecast-22-12-historicalread-time-behavior"></a>
#### 12. Historical/read-time behavior

The forecast is derived read-time output for the explicitly selected `reporting_month_id` and uses that month's `snapshot_date` as `as_of_date`.

R02-12 inherits existing canonical source-service behavior. It must not rewrite closed months or persist an achievement date.

No new DB column or migration is required.


<a id="c8-0005-goal-achievement-forecast-22-13-warnings-and-failure-behavior"></a>
#### 13. Warnings and failure behavior

The API must distinguish:

- a supported goal that is below target but lacks a trajectory (`no_trajectory_model`);
- an unsupported goal type/mode;
- an inactive goal;
- a supported actual passive-income result carrying its canonical C03 history/availability warnings (for example insufficient eligible history).

A missing reporting month or missing goal follows existing API not-found/error conventions; it is not represented as a successful forecast with `null` fields.

<a id="c8-336-financial-context-contract-1"></a>
### Financial context, nullable bps and clone

Accepted and implemented structured financial-context rules (#336/#342). Nullable rates, dates, month-local budget/plan-vs-actual, UI and clone behavior are delivered; no guessed historical backfill. This section owns the current rules formerly spread across MVP text and contract closeout. [Acceptance reconciliation](https://github.com/LTstripes/hermes-finance/issues/336#issuecomment-5669277048).


<a id="c8-336-financial-context-contract-1-0-scope-boundary"></a>
#### 0. Scope boundary

#336 adds **only missing owner-entered structured facts**:

- mortgage annual rate;
- debt APR/rate + due/end dates;
- month-local planned budget, separate from actuals.

Already persisted facts (`saving_allocations.destination`/`notes`, IIS
lifecycle fields, exact ISIN, position cost/price fields) are **not** part of
#336 — #331 consumes them as-is.

Hard non-goals (from #336): mortgage amortization schedule, automatic
credit-card interest computation, bank sync, credit scoring, envelope /
zero-based budgeting subsystem, any change to financial formulas.

If implementation reveals that planned budget or liability terms need a
separate subsystem (scheduler, amortization engine, budget rollover rules),
**STOP** and split instead of growing this issue.


<a id="c8-336-financial-context-contract-1-1-mortgage-rate-property_snapshots"></a>
#### 1. Mortgage rate (`property_snapshots`)

- New nullable column `mortgage_annual_rate_basis_points INTEGER NULL`
  with `CHECK (mortgage_annual_rate_basis_points >= 0)`.
- `NULL` = unknown. `0` = real zero rate. The value is never derived from
  monthly payment, mortgage balance, estimated value, or notes.
- Month-local snapshot field on the existing `property_snapshots` row.
  No separate mortgage/property profile table: one source of truth per
  reporting month. Rate history is read from successive monthly snapshots.
- Storage: integer basis points. API: `mortgage_annual_rate: str | None` —
  decimal percent string via the existing `PercentageRate` value object
  (same representation as deposit `annual_rate`). Domain math in `Decimal`;
  no binary float at any layer.
- Clone (`month_clone.py`): copied like the other permanent property state
  (value, balance, payment). A mortgage rate is a stable term, not an event.


<a id="c8-336-financial-context-contract-1-2-debt-terms-debts"></a>
#### 2. Debt terms (`debts`)

- New nullable `annual_rate_basis_points INTEGER NULL`
  with `CHECK (annual_rate_basis_points >= 0)`.
  `NULL` = unknown, `0` = real 0%. Covers credit-card APR and other-debt
  annual rates with one field; no per-type rate semantics.
- New nullable `next_due_date DATE NULL`: the nearest obligatory payment
  date **as known at the month's `snapshot_date`**, when applicable.
  Informational anchor ("when must I pay next"), not a scheduler input.
- New nullable `contract_end_date DATE NULL`: maturity / contract end,
  when applicable.
- The two dates are never merged: separate columns, separate API fields,
  separate UI inputs. A debt may carry either, both, or neither.
- Missing stays `NULL`. No invented defaults (in particular, no
  end-of-month or +30-days guess for `next_due_date`).
- API: `annual_rate: str | None` (`PercentageRate`), `next_due_date:
  date | None`, `contract_end_date: date | None` (ISO dates).
- Clone: `annual_rate_basis_points` and `contract_end_date` are copied
  (stable terms). `next_due_date` is **cleared** on clone: it is event-like
  (cf. the salary `received_at` clearing precedent in `month_clone.py`),
  and carrying a past due date into a new month would be stale data.
  The owner confirms/sets it in the draft month. See §10.1.


<a id="c8-336-financial-context-contract-1-3-planned-budget-new-month-local-table"></a>
#### 3. Planned budget (new month-local table)

Actual `expense_entries` and `saving_allocations` are never treated as a
budget. The plan lives in a separate table so actuals can never be
misread as plan and vice versa:

- New table `planned_budget_lines`: `id`, `reporting_month_id` (FK
  `reporting_months.id`, `ondelete="RESTRICT"`), `category`
  (`String(128)`, same shape as `expense_entries.category`),
  `expense_type` (`mandatory` / `comfortable` / `other`, same check
  constraint values as `expense_entries`), `planned_amount_kopecks`
  (`BigInteger`, `CHECK >= 0`), `notes` (`String(2000)`, nullable).
- Expense-side plan only. The saving-intent side already exists:
  `saving_allocations` rows (copied month to month, plan/fact per
  MASTER_SPEC §9.15) serve as the saving plan; no second saving-plan
  table.
- Optional: month close never requires planned lines. An empty plan is
  valid and means "no plan entered", not "plan is zero".
- Plan-vs-actual matching key: exact `(category, expense_type)` match
  against `expense_entries`. Unmatched plan lines and unmatched actuals
  are reported side by side, never force-joined. Residual cash-flow
  comparison built on top is #331 presentation over authoritative
  actuals; it introduces no new financial formula here.
- Clone: copied as a draft starting point (precedent: mandatory expenses
  are copied). See §10.2.
- Closed month: immutable through the existing `_guard` path (§5).


<a id="c8-336-financial-context-contract-1-4-0--unknown-global-rule"></a>
#### 4. `0 != unknown` (global rule)

- Every new numeric/date fact in §1–§3 is nullable at storage, service,
  and API layers. `NULL`/`None` = unknown/unentered. `0` / a real date =
  an explicit owner statement.
- UI renders unknown distinctly from zero (e.g. "не указано" vs "0 %");
  unknown never blocks month close.
- Migration rule: `ADD COLUMN ... NULL`. All pre-existing rows receive
  `NULL` (unknown). Backfilling `0`, payment-derived rates, or any other
  guess is forbidden. Downgrade drops the added columns.


<a id="c8-336-financial-context-contract-1-5-history--close--clone-semantics"></a>
#### 5. History / close / clone semantics

- All #336 facts are month-local snapshots on draft-or-closed month rows.
- Closed-month immutability is unchanged: all new create/update/delete
  service paths must call the existing `require_editable_reporting_month`
  / `require_editable_child_month` guards (`services/_guard.py`,
  "closed reporting month must be reopened before editing"). Explicit
  reopen remains the only way to edit a closed month.
- Clone source may be draft or closed (existing rule); the target is
  always a new draft; the operation stays single-transaction
  (all-or-nothing), extended with the §1–§3 copy rules.
- #331 history reads closed months as stored. Missing #336 facts in
  history are `unavailable` + reason codes, never `0.00`. No change to
  eligible-history rules (ADR 0008 untouched).


<a id="c8-336-financial-context-contract-1-6-storage--api-exactness"></a>
#### 6. Storage / API exactness

- Money: `BigInteger` kopecks at storage; `MoneyValue` API objects via
  `RubleAmount` (decimal string, two fraction digits). Same as all
  existing money fields.
- Rates: `Integer` basis points at storage; `PercentageRate` API percent
  string with two fraction digits (deposit `annual_rate` precedent).
  `ROUND_HALF_UP` on parse, exact `Decimal` in domain. #336 introduces
  no derived/calculated fields — pure owner-entered capture — so no new
  rounding paths appear.
- Dates: `Date` columns, ISO-8601 API dates. No datetime/timezone
  semantics for due/end dates.
- No binary `float` for these values in domain, storage, API DTOs, export
  builders, or frontend math. New DTOs use `extra="forbid"`; length and
  nonnegativity validation mirrors the existing debt/property/expense
  endpoints (422 on violation).


<a id="c8-336-financial-context-contract-1-7-consumption-by-331"></a>
#### 7. Consumption by #331

- #331 includes §1–§3 facts through its own versioned schema bump (owned
  by #331, not here): `debts[].annual_rate`, `debts[].next_due_date`,
  `debts[].contract_end_date`, `property.mortgage_annual_rate`,
  a `planned_budget[]` section, and plan-vs-actual comparison only where
  both sides are authoritative.
- Missing/unconfigured facts keep availability semantics in the existing
  style (`available` / `unavailable` + stable reason codes, cf.
  `ai_analysis_bundle`); zero and unknown stay distinct per §4.
- Arrays keep stable ordering (by `id`). Free-text `notes` are never
  parsed for numbers and never feed calculations.


<a id="c8-336-financial-context-contract-1-8-ui--owner-workflow"></a>
#### 8. UI / owner workflow

- New fields are edited inline in the existing month sections (debts,
  property, expenses area for the plan). No separate technical screen.
- Optional values are never required to close a month. Unknown is
  visually and semantically distinct from `0` (§4).


<a id="c8-336-financial-context-contract-1-9-required-regression-coverage"></a>
#### 9. Required regression coverage

Regression coverage preserves: contract/repository/API tests for 0-vs-null
rates, due/end date separation and nullability, migration no-guess
(pre-existing rows read back `NULL`), clone semantics (rate copied, due
date cleared, plan copied), and closed-month immutability of the new
paths; plus frontend tests for editing and unknown-vs-0 display.


<a id="c8-336-financial-context-contract-1-10-accepted-clone-and-budget-decisions"></a>
#### 10. Accepted clone and budget decisions

1. Clear next_due_date on clone and require monthly reconfirmation; never copy a stale due date as current obligation.
2. Copy planned budget into the new month as DRAFT, preserving the supported mandatory-expenses precedent.
3. Plan-vs-actual key is exactly `(category, expense_type)`, not category-only or a new inferred link.
4. Mortgage annual rate is month-local, without a competing global profile/synchronization source.
5. Rate validation is `>= 0`, matching deposits, with no newly inferred upper sanity cap.

<a id="c8-deterministic_insights-1"></a>
### Deterministic predicates and implications

**Status:** implementation contract for issue #178.
**Contract version:** `deterministic_insights_v1`
**Ruleset version:** `v1`
**Endpoint:** `GET /api/months/{month_id}/deterministic-insights`

The engine is a small read-only composition layer over accepted Hermes
contracts.  It does not recalculate their financial semantics.  The endpoint
uses only persisted local state and the caller's evaluation date; it never
calls a provider, performs network I/O, calls an LLM, predicts a future value,
or writes to the database.


<a id="c8-deterministic_insights-1-response-contract"></a>
#### Response contract

The top level identifies the selected reporting month, evaluation clock, and
forecast version used by the cash-flow rules:

```json
{
  "contract_version": "deterministic_insights_v1",
  "ruleset_version": "v1",
  "forecast_version": "v1",
  "reporting_month_id": 12,
  "year": 2030,
  "month": 5,
  "status": "draft",
  "snapshot_date": "2030-05-12",
  "evaluated_on": "2030-05-12",
  "insights": []
}
```

Every emitted item has the same structured shape:

| Field | Meaning |
| --- | --- |
| `code` | Stable machine-readable rule code. Existing accepted reason codes are reused where possible. |
| `type` | Stable rule family, such as `freshness_warning` or `concentration`. |
| `severity` | `error`, `warning`, or `info`; this is attention priority, not a risk score. |
| `message` | Short owner-facing explanation. |
| `evidence` | Values returned by the accepted source service, including support/coverage state where relevant. Money and percentages remain exact strings. |
| `comparison_period` | Reserved for a future accepted comparison; `null` in v1 because no rule invents a comparison series. |
| `source` | Accepted service/read-model path that supplied the evidence. |
| `as_of` | Financial snapshot or valuation target date when the source defines one. |
| `provenance` | Optional source/provider references; no raw payloads or credentials. |
| `reason` | Stable explanation of the predicate that fired. |

The list is deterministic: `error`, then `warning`, then `info`, followed by
`code`, `source`, and `reason`.  A repeated call with the same persisted state,
evaluation date, and forecast version returns the same logical insight list.


<a id="c8-deterministic_insights-1-v1-rules"></a>
#### v1 rules

There are six small rule families.  Concentration has two additional sibling
codes because payout and redemption are different accepted cash-flow
components.

| Rule family | Emitted code(s) | Predicate and evidence | Accepted source |
| --- | --- | --- | --- |
| Close guard | Existing hard-guard code, currently `snapshot_date_required` | The authoritative close-readiness contract returns a hard blocker. | #136 `close_readiness` / `close_hard_guards` |
| Important freshness | Existing warning reason code, for example `quote_stale`, `quote_unavailable`, or `mapped_quote_not_applied` | A #139 family reason has warning severity. Informational missing-data reasons do not become warnings. | #139 `freshness_provenance` |
| Payout reconciliation | `unresolved_payout_reconciliation` | The accepted merged payout calendar has a positive unresolved manual/provider reconciliation count. This is an advisory warning and does not change close behavior. | #136/#137 `close_readiness` and `merged_payout_calendar` |
| Cash-flow concentration | `upcoming_payout_concentration`, `redemption_concentration` | The top accepted dated payout or redemption item is at least `50.00%` of that metric's exact denominator. Redemption remains principal. Approximate or degraded source data downgrades the item to `info`. | #137/#169 `risk_allocation` |
| Portfolio concentration | `portfolio_concentration` | The top persisted position is at least `50.00%` of the accepted liquid-assets denominator. This is descriptive concentration only, never a recommendation. | #169 `risk_allocation.top_positions` |
| Asset-class coverage | `partial_asset_class_coverage` | The accepted asset-class metric has a positive denominator and a positive `unallocated_amount`. No class is inferred from names, tickers, or provider identity. | #169 `risk_allocation.allocation_by_asset_class` |
| Salary-tax history | `salary_tax_history_incomplete` | #171 explicitly reports incomplete salary-tax history. Taxable YTD and threshold values remain unavailable. | #171 `tax_iis_planner.salary_tax` |

The table contains six rule families, while the cash-flow family can emit two
independent deterministic signals.  v1 intentionally does not add a generic
risk score, target drift, issuer/maturity inference, or a tax-threshold
proximity alert.  #171 exposes an exact distance to a configured threshold,
but v1 has no accepted owner-facing proximity threshold; adding one would be a
new policy decision rather than a safe interpretation of that DTO.

Missing or incomplete data follows the source contract: it suppresses a rule
when the required value is absent, or downgrades a signal to `info` when a
known subset is explicitly available.  The engine never substitutes zero,
guesses context, or relabels unavailable values.  The selected forecast
version is echoed in the response so that cash-flow signals remain auditable.


<a id="c8-deterministic_insights-1-reconciliation-and-ai-analysis-bundle-boundaries"></a>
#### Reconciliation and AI Analysis Bundle boundaries

The #170 normalized broker-reconciliation result is transient and is produced
only during an explicit provider preview.  It is not persisted.  The v1 GET
endpoint therefore does not call #170, cache its result, or emit a broker
reconciliation insight from absent data.  A future follow-up may pass an
already-built normalized result into a pure evaluator or add an additive
preview-response integration, without introducing persistence or background
provider work.

The optional deterministic-insights section is preserved in current AI Analysis Bundle schema `1.4.0` with strict allowlists and version
invariants. This task's additive data-quality fields do not add deterministic
insights to the bundle; the insight DTO remains a separate endpoint and future
integration still requires its own reviewed contract decision.

No frontend formulas, migrations, new persistence tables, or UI are part of
this slice.

<a id="c8-r07-06a-risk-allocation-contract-10"></a>
### Supported risk and allocation denominators

<a id="c8-r07-06a-risk-allocation-contract-10-scope-and-common-rules"></a>
#### Scope and common rules

- The API is read-only and deterministic.
- The selected reporting month is the only valuation scope. Only rows marked
  `include_in_capital` (or the existing equivalent on the persisted source)
  participate in liquid-asset allocation.
- Amounts are integer RUB kopecks at the persistence boundary and decimal
  strings for API percentages. No binary `float` or FX conversion is used.
- The existing liquid-capital contract is authoritative for the valuation
  denominator: it sums included `CashBalance.amount_kopecks`,
  `DepositSnapshot.balance_kopecks`, and `PositionSnapshot.market_value_kopecks`
  as persisted RUB-valued amounts. `Instrument.currency` and
  `Instrument.instrument_type` do not gate a valid saved position valuation.
  `PropertySnapshot` is never part of this portfolio scope; real estate and
  mortgage remain separate.
- `VALUATION KNOWN` and `CLASSIFICATION KNOWN` are separate states. A valid
  persisted valuation remains in liquid assets, account allocation, and
  top-position concentration even when currency or asset-class metadata is
  missing or unsupported. Missing metadata is reported; it is never guessed.
- `supported`, `unavailable`, and `unknown` are data states, not risk levels.
  No state is a risk score, probability, recommendation, or alarm.
- A missing field is never replaced with a value inferred from an instrument
  name, ticker, ISIN, account name, provider identity, payout date, or notes.


<a id="c8-r07-06a-risk-allocation-contract-10-persisted-data-inventory"></a>
#### Persisted-data inventory

| Data need | Persisted source and fields | What is authoritative now | Boundary / consequence |
| --- | --- | --- | --- |
| Instrument type / explicit asset class | `instruments.instrument_type`; constrained to `stock`, `bond`, `fund`, `currency`, `gold`, `other` | The stored enum value is an explicit classification. `fund`, `currency`, `gold`, and `other` stay distinct; `other` is not reclassified. | Classification is supported only for a valid authoritative enum value. An unknown type keeps its valid valuation but is reported in `unknown_asset_class` and as unallocated asset-class coverage. No sector, issuer, or “safe/risky” subclass is inferred. |
| Account identity | `accounts.id`, `name`, `account_type`, `status`, `include_in_capital`; positions and deposits carry `account_id` | Account-level grouping is supported for account-linked positions and deposits. | `external_code` is an opaque optional code. It is not a broker/bank identity. No broker or bank grouping is claimed. |
| Current position valuation | `position_snapshots.reporting_month_id`, `account_id`, `instrument_id`, `market_value_kopecks`; `instruments.currency` | `market_value_kopecks` is the stored snapshot valuation produced by the existing position service and is already the RUB amount used by the liquid-capital contract. | A valid `market_value_kopecks` is included regardless of currency or type metadata. Missing currency is `unknown` and non-RUB currency is `unavailable` for currency exposure only; neither removes the saved RUB valuation. |
| Deposit valuation | `deposit_snapshots.reporting_month_id`, `account_id`, `balance_kopecks`, `deposit_type` | Existing deposit service/API contract treats the amount as RUB and the row is account-linked. | There is no per-row currency column, so deposits support liquid allocation under the existing RUB-only contract, but do not prove a standalone currency-exposure dimension. |
| Cash valuation | `cash_balances.reporting_month_id`, `amount_kopecks`, `currency`, `include_in_capital` | `amount_kopecks` is included by the existing liquid-capital contract; currency remains a separate persisted metadata capability. | There is no `account_id`; cash is included in asset-class allocation and reported as `unassigned_cash` for account allocation. Missing/non-RUB currency degrades currency support only. Cash is never assigned from `name`. |
| Issuer identity | No issuer column on `instruments`, positions, payouts, or mappings | None. | Issuer allocation/concentration is `unavailable` with `issuer_not_persisted`. Instrument name/ticker/ISIN are not issuer identity. |
| Currency identity / exposure | `instruments.currency`, `cash_balances.currency`; payout rows also carry currency | Explicit currency strings can be inspected without treating them as an FX instruction. | This is a separate capability from saved RUB valuation. Missing currency is `unknown`; non-RUB currency is `unavailable` because no FX/normalization contract exists. These states do not remove a valid persisted valuation. No currency is guessed from instrument type. |
| Maturity | No maturity field on `instruments` or position snapshots | None. | Maturity ladder/concentration is `unavailable` with `maturity_not_persisted`. A bond type, ISIN, payout date, or provider identity is not maturity metadata. |
| Expected payout/redemption | `expected_cash_flows` and active `applied_provider_payouts`, exposed through `merged_payout_calendar` / R07-05 ladder | #137 merged-calendar semantics: selected month `snapshot_date` to one year, manual/provider duplicate resolution, active provider lifecycle only, and explicit event dates. | Only dated ladder items are concentratable. Redemption remains capital cash flow and is excluded from passive payout totals. Deposit forecast has no dated account/instrument event and is not allocated to a recipient. |
| Real estate / mortgage | `property_snapshots.estimated_value_kopecks`, `mortgage_balance_kopecks` | Separate property-equity and mortgage contracts. | Not queried by risk/allocation metrics and never mixed into liquid capital. |


<a id="c8-r07-06a-risk-allocation-contract-10-support-state-contract"></a>
#### Support-state contract

Each metric and each excluded metadata dimension exposes:

```text
status: supported | unavailable | unknown
reason_codes: stable, machine-readable strings
```

The meanings are:

- `supported`: the metric is computable for the declared scope from
  authoritative persisted data. An empty supported collection has zero rows;
  it does not invent a position.
- `unavailable`: the schema or current contract cannot provide the requested
  capability safely, for example currency exposure without an accepted FX
  normalization contract. It does not mean that an already persisted RUB
  valuation is absent.
- `unknown`: the metric could be relevant, but a required persisted value is
  absent or unusable for the affected row. The service does not substitute a
  default.

When several row issues affect one metric, aggregate status is deterministic:
`unavailable` takes precedence over `unknown`, which takes precedence over
`supported`. All applicable reason codes remain present in sorted order.

Required reason codes for this slice include:

| Reason code | Meaning |
| --- | --- |
| `issuer_not_persisted` | No issuer field exists in the current schema. |
| `maturity_not_persisted` | No maturity field exists in the current schema. |
| `currency_not_persisted` | A currency-exposure row has no usable currency value; a saved RUB valuation is unaffected. |
| `currency_conversion_not_supported` | A non-RUB currency-bearing exposure/event has no accepted FX/normalization contract; a saved RUB valuation is unaffected. |
| `cash_not_account_linked` | Cash is persisted without `account_id`; it remains unassigned. |
| `no_dated_payouts` | No dated payout/redemption event exists in the accepted 12-month scope. |
| `deposit_forecast_not_concentratable` | #137 deposit estimate has no dated account/instrument event. |
| `unsupported_position_valuation` | The persisted position valuation field itself is missing or unusable; currency/type metadata alone never produces this reason. |
| `instrument_type_not_authoritative` | A position has no valid persisted instrument-type enum value; its valid valuation remains included outside class coverage. |
| `instrument_not_persisted` | A dated payout event has no instrument relation available for grouping. |
| `broker_identity_not_persisted` | No authoritative broker identity is persisted on the account. |
| `bank_identity_not_persisted` | No authoritative bank identity is persisted on the account. |


<a id="c8-r07-06a-risk-allocation-contract-10-implemented-metrics-in-this-slice"></a>
#### Implemented metrics in this slice


<a id="c8-r07-06a-risk-allocation-contract-10-allocation-by-explicit-type--asset-class"></a>
#### Allocation by explicit type / asset class

Rows use only these persisted, explicit buckets:

- `cash` from included cash balances under the liquid-capital contract;
- `deposits` from included account-linked deposit snapshots;
- each valid `Instrument.instrument_type` value independently for included
  position valuations;
- `unknown_asset_class` for valid position valuations whose instrument type is
  missing or not an authoritative enum value.

The service does not collapse all non-stock/non-bond instruments into a
synthetic `gold_other` class for this contract. Percentages use the full
authoritative RUB liquid-asset denominator from the existing liquid-capital
semantics. Known
class amounts are `covered_amount`; `unknown_asset_class` is explicit
`unallocated_amount`. A valid valuation with unknown class therefore remains
in the denominator while known-class percentages are not inflated. Currency
metadata issues are exposed by the separate currency capability and do not
exclude the amount.


<a id="c8-r07-06a-risk-allocation-contract-10-allocation-by-account"></a>
#### Allocation by account

Account rows sum included valued positions and deposits by `account_id`.
Included cash is exposed as an `unassigned_cash` row and in the unallocated
amount because the persisted cash row has no account relation. The service
never maps cash by account name, account type, or row order. Account shares use
the full authoritative liquid-asset denominator, so a valued position remains
account-linked even when its currency or asset-class metadata is unknown.


<a id="c8-r07-06a-risk-allocation-contract-10-top-n-positions-and-concentration"></a>
#### Top-N positions and concentration

Top positions are individual persisted `(account_id, instrument_id)` position
snapshots, ranked by `market_value_kopecks` descending and then stable IDs
ascending. The response includes each valid valued position's amount/share and
the sum/share of the selected top N, regardless of currency or asset-class
metadata. Shares use the full authoritative liquid-asset denominator. This is
descriptive concentration only; no threshold, score, probability, or
recommendation is produced.


<a id="c8-r07-06a-risk-allocation-contract-10-future-payout-and-redemption-concentration"></a>
#### Future payout and redemption concentration

The service first consumes the accepted #137 merged 12-month ladder. It does
not independently reimplement duplicate handling or resurrect cancelled,
dismissed, unresolved, or out-of-window provider rows.

- `payout` concentration uses dated `coupon`, `dividend`, `interest`, and
  `other` ladder events only. The `interest` event type is the explicit
  persisted cash-flow type, not the undated deposit estimate.
- `redemption` concentration uses dated `redemption` events only.
- Redemption amount is never included in passive payout totals.
- Events are grouped by their persisted account/instrument scope and retain
  the ladder's approximation flag and deterministic event count.
- A deposit monthly estimate contributes to #137 monthly totals, but it has no
  dated instrument/account event and is therefore not assigned to a
  concentration bucket; the response states that limitation explicitly.
- Missing/non-RUB event currency fails closed with `unknown` or `unavailable`;
  no conversion is attempted.


<a id="c8-r07-06a-risk-allocation-contract-10-api-shape"></a>
#### API shape

`GET /api/analytics/risk-allocation?month_id={id}&top_n=5&forecast_version=v1`
returns the deterministic read model. `month_id` selects the persisted
reporting-month snapshot; `top_n` is bounded to 1..100. Every money value is a
RUB `MoneyValue`. Percentages are nullable two-decimal decimal strings, so a
zero denominator is represented by `null`, not `0%`.

The response contains `allocation_by_asset_class`,
`allocation_by_account`, `top_positions`, `payout_concentration`, and
`redemption_concentration`. Each metric has `support`, exact denominator and
coverage fields, deterministic rows, and row-level `excluded` issues. The
top-level `support` map makes issuer, currency, maturity, broker, and bank
limitations explicit even when their corresponding metric is not computed.

<a id="c8-r07-09-scenario-lab-contract-13"></a>
### Frozen scenario base, supported shocks, matrices and examples

<a id="c8-r07-09-scenario-lab-contract-13-1-purpose"></a>
#### 1. Purpose

Scenario Lab v1 — deterministic, read-only what-if evaluator over an explicit frozen financial snapshot.

Scenario Lab:

- НЕ является market forecast;
- НЕ оценивает вероятность сценария;
- НЕ генерирует expected return;
- НЕ моделирует correlation/beta;
- НЕ предполагает recovery probability;
- НЕ прогнозирует действия пользователя;
- НЕ делает rebalancing;
- НЕ изменяет canonical financial data.

Scenario Lab отвечает только на вопрос:

> «Что получится с поддерживаемыми текущими метриками, если к известной базе детерминированно применить явно заданное пользователем предположение?»

В v1 contractually определены пять shock types:

1. `equity_drawdown`
2. `fx_translation_shock`
3. `issuer_impairment`
4. `deposit_rate_assumption`
5. `inflation_real_value`

Contractual existence shock type НЕ означает, что текущая runtime schema уже содержит данные для его точного расчёта.

При недостаточной authoritative metadata результат обязан быть `unknown` или `unavailable`, а не guessed.

---


<a id="c8-r07-09-scenario-lab-contract-13-2-canonical-base-case"></a>
#### 2. Canonical base case

Base case формируется для явно выбранного `ReportingMonth`.

Базовая valuation date:

`ReportingMonth.snapshot_date`

Scenario Lab НЕ имеет отдельной финансовой модели.

Он обязан переиспользовать существующие canonical read semantics для:

- liquid capital;
- Risk & Allocation;
- Goals;
- passive-income metrics;
- merged future cash-flow ladder.

Нельзя повторно реализовывать эти формулы внутри Scenario Lab с отличающейся семантикой.


<a id="c8-r07-09-scenario-lab-contract-13-21-position-valuation-source"></a>
#### 2.1 Position valuation source

Для текущей стоимости позиции Scenario Lab использует только canonical persisted:

`PositionSnapshot.market_value_kopecks`

из выбранного reporting snapshot.

Для Scenario Lab v1 запрещено:

- получать live quote;
- обращаться к provider ради обновления цены;
- заменять snapshot valuation текущей рыночной ценой;
- самостоятельно пересчитывать persisted valuation из ticker/quantity;
- использовать внешний FX lookup.

`PositionSnapshot.market_value_kopecks` является base reporting-currency value для Scenario Lab там, где соответствующий shock contract разрешает её трансформацию.


<a id="c8-r07-09-scenario-lab-contract-13-22-base-identity"></a>
#### 2.2 Base identity

Base case должен содержать как минимум:

- reporting month identifier;
- snapshot date;
- reporting month status;
- Scenario Lab contract/calculation version;
- upstream read-model/calculation versions, где применимо;
- reporting currency;
- deterministic semantic base fingerprint.


<a id="c8-r07-09-scenario-lab-contract-13-23-closed--draft--reopened"></a>
#### 2.3 CLOSED / DRAFT / reopened

CLOSED month является естественно стабильной frozen base.

DRAFT или reopened month также MAY быть evaluated read-only.

Но для mutable month reproducibility относится к фактически захваченному base payload, а не к будущему состоянию базы.

Если DRAFT/reopened month позже изменён, новый run обязан получить другой base fingerprint.

Scenario Lab никогда не превращает DRAFT/reopened month в frozen canonical state.

---


<a id="c8-r07-09-scenario-lab-contract-13-3-stress-case"></a>
#### 3. Stress case

В Scenario Lab v1 один scenario содержит РОВНО ОДИН shock.

Формально:

`stressed_case = scenario_lab_v1(frozen_base_case, exactly_one_shock, contract_version)`

Shock может менять только те факты, которые его контракт явно разрешает менять.

Все остальные известные факты остаются неизменными.

Неизвестный potentially affected факт НЕЛЬЗЯ автоматически считать unaffected.

---


<a id="c8-r07-09-scenario-lab-contract-13-4-applicability-and-support-states"></a>
#### 4. Applicability and support states


<a id="c8-r07-09-scenario-lab-contract-13-41-row-level-applicability"></a>
#### 4.1 Row-level applicability

Для каждой potentially affected row применяется одно состояние:

- `applied`
- `not_applicable`
- `unknown`


<a id="c8-r07-09-scenario-lab-contract-13-applied"></a>
#### applied

Достаточно authoritative metadata, и shock точно применим.


<a id="c8-r07-09-scenario-lab-contract-13-not_applicable"></a>
#### not_applicable

Authoritative metadata достаточно, чтобы доказать, что shock к row не относится.


<a id="c8-r07-09-scenario-lab-contract-13-unknown"></a>
#### unknown

Metadata недостаточно, чтобы доказать применимость или неприменимость.

`unknown` запрещено интерпретировать как `not_applicable`.


<a id="c8-r07-09-scenario-lab-contract-13-42-metric-level-support"></a>
#### 4.2 Metric-level support

Для aggregated metric используются существующие semantic states:

- `supported`
- `unknown`
- `unavailable`


<a id="c8-r07-09-scenario-lab-contract-13-supported"></a>
#### supported

Полный stressed result может быть детерминированно рассчитан.


<a id="c8-r07-09-scenario-lab-contract-13-unknown-1"></a>
#### unknown

Есть potentially affected scope, для которого applicability или value невозможно определить из сохранённых authoritative data.


<a id="c8-r07-09-scenario-lab-contract-13-unavailable"></a>
#### unavailable

Contract требует semantic/input basis, которой текущая data model вообще не предоставляет для данного расчёта.

Scenario Lab MAY показывать known-scope impact с explicit coverage.

Но если potentially affected rows имеют `unknown`, partial known-scope value НЕ может называться:

- exact stressed total;
- full portfolio stressed total;
- complete stressed metric.

Coverage и limitation должны быть видимыми.

---


<a id="c8-r07-09-scenario-lab-contract-13-5-shock-equity_drawdown"></a>
#### 5. Shock: equity_drawdown


<a id="c8-r07-09-scenario-lab-contract-13-51-input"></a>
#### 5.1 Input

`drawdown_pct`

Decimal percentage в диапазоне:

`0 <= drawdown_pct <= 100`

Например:

`20`

означает уменьшение applicable equity market value на 20%.


<a id="c8-r07-09-scenario-lab-contract-13-52-applicability"></a>
#### 5.2 Applicability

Scenario Lab v1 применяет equity drawdown ТОЛЬКО к позиции с authoritative:

`instrument_type = stock`

Никакие другие категории автоматически equity не считаются.

В частности НЕ считаются equity для этого shock:

- fund;
- bond;
- currency;
- gold;
- other.

Fund look-through отсутствует.

Даже если фонд экономически содержит акции, `instrument_type=fund` не подвергается v1 equity drawdown.

Если `instrument_type` отсутствует или невалиден:

row applicability = `unknown`.


<a id="c8-r07-09-scenario-lab-contract-13-53-base-valuation"></a>
#### 5.3 Base valuation

Единственный разрешённый valuation source:

`PositionSnapshot.market_value_kopecks`

выбранного reporting snapshot.

Никаких live/provider quotes.


<a id="c8-r07-09-scenario-lab-contract-13-54-formula"></a>
#### 5.4 Formula

Для applicable stock:

`stressed_market_value = base_market_value * (1 - drawdown_pct / 100)`

Financial calculation использует Decimal semantics и canonical money rounding boundary.


<a id="c8-r07-09-scenario-lab-contract-13-55-supported-effects"></a>
#### 5.5 Supported effects

При полном coverage могут быть пересчитаны:

- liquid assets;
- liquid capital;
- asset allocation;
- account allocation;
- top-position concentration;
- capital Goal current value;
- capital Goal gap;
- capital Goal progress;
- affected instrument impact.

Debts shock не затрагивает.

Liquid capital остаётся результатом canonical liquid-capital formula, только с transformed applicable position values.


<a id="c8-r07-09-scenario-lab-contract-13-56-explicitly-unchanged--unsupported-relationships"></a>
#### 5.6 Explicitly unchanged / unsupported relationships

Equity price drawdown НЕ означает автоматически:

- снижение dividend cash flow;
- снижение coupon cash flow;
- снижение bond redemption;
- снижение deposit income;
- изменение historical actual passive income.

Scenario Lab не предполагает фиксированный dividend yield.

Поэтому passive-income effect от equity drawdown без отдельной deterministic relationship:

`unavailable`

reason:

`no_deterministic_income_relationship`

Это НЕ является `0 income impact`.

Visible assumptions:

- explicit stock-only applicability;
- no fund look-through;
- no rebalancing;
- no dividend assumption;
- no coupon assumption;
- no tax assumption;
- no recovery/default assumption.

---


<a id="c8-r07-09-scenario-lab-contract-13-6-shock-fx_translation_shock"></a>
#### 6. Shock: fx_translation_shock


<a id="c8-r07-09-scenario-lab-contract-13-61-input"></a>
#### 6.1 Input

- `target_currency`
- `reporting_value_change_pct`

`target_currency` — explicit normalized currency identifier.

Sign convention задаётся С ТОЧКИ ЗРЕНИЯ reporting currency value.

Пример:

`target_currency = USD`

`reporting_value_change_pct = +10`

означает:

> одна и та же native USD value после shock стоит на 10% больше в reporting currency.

Отрицательное значение означает уменьшение reporting-currency value.


<a id="c8-r07-09-scenario-lab-contract-13-62-currency-tag-alone-is-insufficient"></a>
#### 6.2 Currency tag alone is insufficient

Наличие только:

`Instrument.currency`

НЕ является достаточным основанием для exact FX revaluation.

Currency tag может определить candidate scope, но НЕ доказывает:

- полную 1:1 FX exposure;
- native position amount;
- base FX rate;
- valuation currency mechanics;
- hedge;
- synthetic currency link.

Scenario Lab не имеет права делать:

`RUB market value × 1.10`

только потому, что `Instrument.currency = USD`.


<a id="c8-r07-09-scenario-lab-contract-13-63-exact-applicability-requirements"></a>
#### 6.3 Exact applicability requirements

Position может быть точно FX-shocked только при наличии authoritative translation semantics, достаточной для воспроизводимого преобразования reporting value.

Например, contract/data model должна явно предоставить необходимые компоненты вроде:

- exposure / valuation currency;
- native value;
- accepted base FX reference или эквивалентную deterministic translation basis.

Конкретный upstream FX metadata contract должен быть принят отдельно.


<a id="c8-r07-09-scenario-lab-contract-13-64-current-baseline-consequence"></a>
#### 6.4 Current-baseline consequence

В текущей baseline schema наличие только:

- `Instrument.currency`;
- и RUB-valued `market_value_kopecks`

НЕ позволяет выполнить exact FX translation.

Такая metric relationship:

`unavailable`

reason:

`fx_translation_basis_unavailable`

Если currency metadata отсутствует:

row applicability = `unknown`

reason:

`missing_currency`

Существующая saved RUB valuation при этом остаётся валидной base valuation.


<a id="c8-r07-09-scenario-lab-contract-13-65-formula-once-authoritative-basis-exists"></a>
#### 6.5 Formula once authoritative basis exists

Когда accepted translation basis существует:

`stressed_fx_rate = base_fx_rate * (1 + reporting_value_change_pct / 100)`

`stressed_reporting_value = native_value * stressed_fx_rate`

Никакого live FX lookup.


<a id="c8-r07-09-scenario-lab-contract-13-66-potential-supported-effects-once-metadata-exists"></a>
#### 6.6 Potential supported effects once metadata exists

При достаточной authoritative metadata FX shock MAY change:

- liquid capital;
- allocation/concentration;
- capital Goals;
- instrument impact;
- reporting-currency value future cash flows.

Future cash flow может быть FX-shocked только если сам flow имеет достаточную authoritative translation metadata.

Нельзя наследовать currency от unrelated position только по имени/issuer/ticker.


<a id="c8-r07-09-scenario-lab-contract-13-67-forbidden-inference"></a>
#### 6.7 Forbidden inference

Нельзя выводить FX exposure из:

- issuer domicile;
- ticker;
- exchange;
- instrument name;
- company revenue geography;
- exporter status;
- gold correlation;
- synthetic economic intuition;
- assumed hedge.

---


<a id="c8-r07-09-scenario-lab-contract-13-7-shock-issuer_impairment"></a>
#### 7. Shock: issuer_impairment


<a id="c8-r07-09-scenario-lab-contract-13-71-input"></a>
#### 7.1 Input

- canonical authoritative `issuer_id`
- `haircut_pct`
- `impact_scope`

`haircut_pct`:

`0 <= haircut_pct <= 100`

`impact_scope` обязан быть одним из:

- `capital_value`
- `future_cash_flows`
- `both`

Impact scope ОБЯЗАТЕЛЕН.

Scenario Lab никогда не трактует слово «issuer impairment» как implicit total default.


<a id="c8-r07-09-scenario-lab-contract-13-72-applicability"></a>
#### 7.2 Applicability

Shock применяется только к exact authoritative issuer identity match.

Запрещено определять issuer по:

- name;
- ticker;
- ISIN heuristics;
- account;
- provider;
- payout description;
- notes.


<a id="c8-r07-09-scenario-lab-contract-13-73-current-baseline-consequence"></a>
#### 7.3 Current-baseline consequence

В текущей baseline issuer identity для необходимых portfolio entities не persisted как canonical identity.

Следовательно issuer impairment сейчас:

`unavailable`

reason:

`issuer_not_persisted`

Это ожидаемый и корректный v1 result.

Scenario Lab НЕ должен создавать guessed issuer mapping внутри #141.


<a id="c8-r07-09-scenario-lab-contract-13-74-capital_value-mode"></a>
#### 7.4 capital_value mode

Для issuer-linked current capital row:

`stressed_market_value = base_market_value * (1 - haircut_pct / 100)`

Future cash flows не меняются.


<a id="c8-r07-09-scenario-lab-contract-13-75-future_cash_flows-mode"></a>
#### 7.5 future_cash_flows mode

Current market value не меняется.

Только explicitly issuer-linked known future flows:

`stressed_flow_amount = base_flow_amount * (1 - haircut_pct / 100)`

Flow kind не меняется.

То есть отдельно сохраняются:

- coupon;
- dividend;
- interest;
- other income;
- redemption/principal.

Redemption/principal НИКОГДА не становится passive income.


<a id="c8-r07-09-scenario-lab-contract-13-76-both-mode"></a>
#### 7.6 both mode

Один выбранный пользователем haircut percentage применяется независимо к:

- issuer-linked capital value;
- issuer-linked future known cash flows.

Но результаты остаются раздельными финансовыми категориями.


<a id="c8-r07-09-scenario-lab-contract-13-77-interpretation"></a>
#### 7.7 Interpretation

Haircut — explicit uniform WHAT-IF assumption.

Это НЕ:

- probability of default;
- prediction;
- recovery probability;
- default timing;
- seniority model;
- waterfall;
- contagion;
- correlation assumption.

---


<a id="c8-r07-09-scenario-lab-contract-13-8-shock-deposit_rate_assumption"></a>
#### 8. Shock: deposit_rate_assumption


<a id="c8-r07-09-scenario-lab-contract-13-81-input"></a>
#### 8.1 Input

- explicit deposit target set ИЛИ explicit `all_eligible_deposits`;
- `assumed_annual_rate_pct`.

`assumed_annual_rate_pct` — абсолютная hypothetical annual rate.

Это НЕ delta.

Например:

`12`

означает hypothetical rate = 12%, а не «+12 percentage points».


<a id="c8-r07-09-scenario-lab-contract-13-82-applicability"></a>
#### 8.2 Applicability

Shock применяется только к deposits, для которых canonical deposit semantics позволяют вычислять expected interest.

Нельзя применять его к:

- securities;
- bonds;
- equities;
- cash;
- unknown account-like assets;
- products, которые только по имени похожи на deposit.

Нельзя reverse-engineer rate из исторических interest payments.


<a id="c8-r07-09-scenario-lab-contract-13-83-formula"></a>
#### 8.3 Formula

Используется существующая canonical simplified deposit forecast semantics:

`expected_monthly_interest = balance * annual_rate / 12`

Для stressed case:

`stressed_expected_monthly_interest = balance * assumed_annual_rate / 12`

Principal balance не меняется.


<a id="c8-r07-09-scenario-lab-contract-13-84-effects"></a>
#### 8.4 Effects

Deposit-rate assumption:

UNCHANGED:

- deposit principal;
- liquid capital;
- capital allocation;
- capital Goals.

CHANGED, если canonical inputs полностью supported:

- expected monthly deposit interest;
- approximate monthly deposit-interest component будущего cash-flow ladder;
- passive-income forecast через existing canonical deposit-interest component.


<a id="c8-r07-09-scenario-lab-contract-13-85-cash-flow-calendar-rule"></a>
#### 8.5 Cash-flow calendar rule

Нельзя fabricated dated events из undated monthly deposit-interest forecast.

Существующая accepted cash-flow semantics сохраняется:

`DepositSnapshot.expected_monthly_interest_kopecks`

может оставаться approximate monthly ladder component.

Она НЕ превращается автоматически в:

- payment in 14 days;
- payment in 30 days;
- arbitrary monthly dated event.


<a id="c8-r07-09-scenario-lab-contract-13-86-passive-income-goal"></a>
#### 8.6 Passive-income Goal

Current canonical passive-income Goal progress использует historical actual passive-income rolling average.

Следовательно hypothetical future deposit-rate assumption НЕ изменяет:

- current passive-income Goal current value;
- current passive-income Goal progress;
- current passive-income Goal gap,

если эти canonical Goal metrics основаны на historical actual rolling average.

Scenario Lab обязан различать:

- passive-income FORECAST effect — может измениться;
- current passive-income GOAL progress — остаётся canonical actual-based.

Historical actual income никогда не переписывается scenario assumption.

---


<a id="c8-r07-09-scenario-lab-contract-13-9-shock-inflation_real_value"></a>
#### 9. Shock: inflation_real_value


<a id="c8-r07-09-scenario-lab-contract-13-91-nature"></a>
#### 9.1 Nature

Inflation shock в v1 является только secondary real-value presentation.

Он НЕ мутирует nominal financial facts.

Это не forecast рыночной стоимости капитала.


<a id="c8-r07-09-scenario-lab-contract-13-92-input"></a>
#### 9.2 Input

`annual_inflation_pct`

и выбранный base reporting month.


<a id="c8-r07-09-scenario-lab-contract-13-93-convention"></a>
#### 9.3 Convention

V1 использует явную monthly convention:

`monthly_rate = annual_inflation_pct / 12`

Для future amount на `months_ahead`:

`real_value = nominal_future_value / (1 + monthly_rate) ^ months_ahead`

`months_ahead` определяется deterministic calendar-month distance от base reporting month до month соответствующего future cash flow.

Используются Decimal semantics.

Rounding выполняется только на canonical money boundary.

Это намеренная v1 nominal monthly assumption.

Это НЕ утверждение о методологии CPI.


<a id="c8-r07-09-scenario-lab-contract-13-94-supported-outputs"></a>
#### 9.4 Supported outputs

Для future dated или month-known cash flows Scenario Lab может показывать:

- original nominal value;
- stressed real-value equivalent.

Income и redemption/principal остаются отдельными категориями.


<a id="c8-r07-09-scenario-lab-contract-13-95-current-capital"></a>
#### 9.5 Current capital

Current liquid capital на base date не изменяется inflation_real_value shock.

В base-period purchasing power:

`real current capital = nominal current capital`

Future purchasing power текущего капитала НЕ прогнозируется, потому что Scenario Lab v1 не имеет future capital trajectory/reinvestment contract.

Такой future-capital result:

`unavailable`


<a id="c8-r07-09-scenario-lab-contract-13-96-goals"></a>
#### 9.6 Goals

Scenario Lab v1 НЕ inflation-indexes Goal target automatically.

Current Goal schema не устанавливает нормативно, означает ли target:

- today's-money target;
- nominal target at target date;
- already inflation-adjusted target.

Следовательно inflation-adjusted Goal target/coverage:

`unavailable`

до отдельного Goal price-basis contract.

Нельзя самостоятельно выбирать одну из этих трактовок.

---


<a id="c8-r07-09-scenario-lab-contract-13-10-output-families"></a>
#### 10. Output families

Scenario result должен разделять как минимум:

- `base`
- `stressed`
- `impact`
- `support`
- `assumptions`

Supported output families:

1. liquid capital;
2. allocation/concentration;
3. Goal gap/coverage/current/progress — только если canonical Goal действительно зависит от изменённой shock metric;
4. passive-income effect — только при deterministic relationship;
5. future cash-flow effect;
6. issuer/instrument impact.

Historical actual passive income никогда не превращается в hypothetical stressed actual.

---


<a id="c8-r07-09-scenario-lab-contract-13-11-shock--output-semantic-matrix"></a>
#### 11. Shock × output semantic matrix

Ниже `changed` означает: shock contract разрешает deterministic изменение при полном required metadata coverage.

`unchanged` означает: shock contract явно не меняет эту metric.

`conditional` означает: изменение возможно только при достаточной authoritative metadata / canonical deterministic relationship.

`unavailable` означает: v1 contract намеренно не определяет такую relationship.


<a id="c8-r07-09-scenario-lab-contract-13-equity_drawdown"></a>
#### equity_drawdown

- liquid capital: `changed`
- allocation/concentration: `changed`
- capital Goals: `changed`
- passive-income forecast: `unavailable`, если нет отдельной deterministic income relationship
- historical passive income: `unchanged`
- future cash flow: `unchanged`
- redemption/principal: `unchanged`


<a id="c8-r07-09-scenario-lab-contract-13-fx_translation_shock"></a>
#### fx_translation_shock

При accepted authoritative FX translation basis:

- liquid capital: `conditional`
- allocation/concentration: `conditional`
- capital Goals: `conditional`
- passive-income forecast: `conditional` только для future income flows с sufficient FX translation metadata
- future cash flow: `conditional`
- redemption/principal: `conditional`

При текущей baseline без accepted translation basis exact stressed metrics:

`unavailable`

где соответствующий FX translation необходим.


<a id="c8-r07-09-scenario-lab-contract-13-issuer_impairment--capital_value"></a>
#### issuer_impairment — capital_value

- liquid capital: `changed`
- allocation/concentration: `changed`
- capital Goals: `changed`
- passive-income forecast: `unchanged`
- future cash flow: `unchanged`
- redemption/principal: `unchanged`

при наличии authoritative issuer identity.

В текущей baseline без issuer identity:

`unavailable`.


<a id="c8-r07-09-scenario-lab-contract-13-issuer_impairment--future_cash_flows"></a>
#### issuer_impairment — future_cash_flows

- current liquid capital: `unchanged`
- current allocation/concentration: `unchanged`
- capital Goals: `unchanged`
- passive-income forecast: `conditional`, только через explicitly affected income flows
- future cash flow: `changed`
- redemption/principal: `changed` только для explicitly issuer-linked redemption rows

при наличии authoritative issuer identity.


<a id="c8-r07-09-scenario-lab-contract-13-issuer_impairment--both"></a>
#### issuer_impairment — both

Комбинирует два предыдущих scope ВНУТРИ ОДНОГО issuer shock contract:

- capital metrics: `changed`
- future linked flows: `changed`
- passive-income forecast: `conditional`
- redemption/principal: `changed` separately

Это НЕ multi-shock composition.


<a id="c8-r07-09-scenario-lab-contract-13-deposit_rate_assumption"></a>
#### deposit_rate_assumption

- liquid capital: `unchanged`
- allocation/concentration: `unchanged`
- capital Goals: `unchanged`
- passive-income forecast: `changed`
- current actual-based passive-income Goal: `unchanged`
- future cash flow: `changed` только в canonical approximate monthly deposit-interest component
- redemption/principal: `unchanged`


<a id="c8-r07-09-scenario-lab-contract-13-inflation_real_value"></a>
#### inflation_real_value

Nominal metrics:

- liquid capital: `unchanged`
- allocation/concentration: `unchanged`
- current Goals: `unchanged`
- nominal passive-income forecast: `unchanged`
- nominal future cash flow: `unchanged`
- nominal redemption/principal: `unchanged`

Secondary real-value presentation:

- future income real-value: `changed`
- future redemption real-value: `changed`
- future other known cash-flow real-value: `changed`
- future capital purchasing-power forecast: `unavailable`
- inflation-adjusted Goal target/coverage: `unavailable`

---


<a id="c8-r07-09-scenario-lab-contract-13-12-missing-data-and-reason-semantics"></a>
#### 12. Missing data and reason semantics

Scenario Lab никогда не угадывает:

- currency;
- issuer;
- instrument type;
- rate semantics;
- FX translation basis;
- correlation;
- probability.

Examples:

Missing currency:

row applicability:

`unknown`

reason:

`missing_currency`

Currency exists but sufficient translation basis отсутствует:

metric support:

`unavailable`

reason:

`fx_translation_basis_unavailable`

Issuer identity отсутствует:

`unavailable`

reason:

`issuer_not_persisted`

Instrument type отсутствует для equity shock:

row applicability:

`unknown`

reason:

`unknown_asset_class`

Required deterministic rate semantics отсутствуют:

`unavailable`

reason:

`missing_rate_semantics`

Potentially affected flow lacks issuer/currency metadata:

row:

`unknown`

Aggregate full stressed metric не может называться exact, если эта row может изменить aggregate.

Отсутствует deterministic financial relationship:

`unavailable`

reason:

`no_deterministic_relationship`

Нельзя заменять это значением:

`impact = 0`.

---


<a id="c8-r07-09-scenario-lab-contract-13-13-scenario-composition"></a>
#### 13. Scenario composition

Scenario Lab v1 поддерживает РОВНО ОДИН shock на scenario.

Допускается сравнивать несколько независимых scenarios, каждый построенный от одного и того же base case.

Например:

- Scenario A = equity drawdown -20%;
- Scenario B = USD reporting value +10%.

Но один Scenario v1 НЕ может содержать одновременно equity + FX.

Combined input возвращает:

`unsupported_composition_v1`

V1 намеренно НЕ определяет:

- additive composition;
- multiplicative composition;
- shock ordering;
- correlation;
- overlapping exposure semantics;
- double-shock avoidance.

Если combined scenarios понадобятся, требуется отдельный future contract.

Нельзя молча выбрать порядок или математику комбинации в implementation #141.

---


<a id="c8-r07-09-scenario-lab-contract-13-14-export-and-reproducibility"></a>
#### 14. Export and reproducibility

Scenario Lab export должен быть deterministic semantic artifact.

Он содержит как минимум:

- Scenario Lab contract/calculation version;
- reporting month;
- snapshot date;
- reporting month status;
- semantic base fingerprint;
- relevant upstream calculation/read-model versions;
- reporting currency;
- normalized shock type;
- normalized shock parameters;
- normalized target scope;
- explicit assumptions;
- base outputs;
- stressed outputs;
- impacts;
- support states;
- reason codes;
- row-level applicability;
- coverage information;
- affected canonical refs;
- financial math/rounding convention.

Financial values:

- money serialized as deterministic decimal/minor-unit representation consistent with project contracts;
- rates and percentages serialized as decimal strings;
- no binary float.

Ordering must быть stable.

`generated_at` MAY присутствовать как UX/audit metadata.

Но `generated_at` MUST NOT входить в semantic fingerprint.

Normative invariant:

> same frozen base payload + same Scenario Lab contract version + same normalized scenario input = same semantic output and same semantic fingerprint.

Если mutable DRAFT/reopened base изменён, новый base payload обязан иметь другой base fingerprint и может дать другой result.

Scenario export НЕ является canonical financial state и не должен изменять database state.

---


<a id="c8-r07-09-scenario-lab-contract-13-15-acceptance-examples"></a>
#### 15. Acceptance examples


<a id="c8-r07-09-scenario-lab-contract-13-example-a--clean-stock-drawdown"></a>
#### Example A — clean stock drawdown

Base:

- stock market value = 1000
- deposit = 500
- no debt

Scenario:

`equity_drawdown = 20%`

Result:

- stock = 800
- deposit = 500
- liquid capital = 1300

Dividend/coupon/redemption не меняются автоматически.

Passive-income reduction НЕ выводится только из price drawdown.


<a id="c8-r07-09-scenario-lab-contract-13-example-b--unknown-asset-type"></a>
#### Example B — unknown asset type

Base:

- explicit stock = 1000
- position with missing instrument type = 400

Scenario:

`equity_drawdown = 20%`

Known-scope impact:

- stock impact = -200

Но potentially affected 400-position имеет unknown applicability.

Следовательно implementation НЕ может назвать:

`1200`

exact full stressed capital только потому, что unknown row была оставлена без shock.

Должен быть explicit unknown/coverage state.


<a id="c8-r07-09-scenario-lab-contract-13-example-c--deposit-rate"></a>
#### Example C — deposit rate

Base deposit:

- balance = 120000
- current annual rate = 6%

Scenario:

`assumed_annual_rate_pct = 12`

Stressed expected monthly interest:

`120000 * 0.12 / 12 = 1200`

Deposit principal остаётся 120000.

Liquid capital не меняется.

Approximate monthly ladder component может измениться.

Fabricated dated payment не создаётся.

Passive-income forecast может измениться.

Current passive-income Goal progress, основанный на historical actual rolling average, не меняется.


<a id="c8-r07-09-scenario-lab-contract-13-example-d--issuer-shock-on-current-baseline"></a>
#### Example D — issuer shock on current baseline

Scenario:

issuer X, haircut 40%, scope `both`.

Current schema не содержит authoritative canonical issuer identity.

Result:

`unavailable`

reason:

`issuer_not_persisted`

Нельзя искать X по ticker/name/ISIN heuristic.


<a id="c8-r07-09-scenario-lab-contract-13-example-e--future-issuer-capable-fixture"></a>
#### Example E — future issuer-capable fixture

Предположим future accepted schema содержит authoritative issuer identity.

Base:

- issuer-linked market value = 1000
- coupon = 100
- redemption principal = 1000

Scenario:

- haircut = 40%
- impact_scope = both

Result:

- market value = 600
- coupon = 60
- redemption principal = 600

Coupon остаётся income.

Redemption 600 остаётся principal/capital return.

Redemption НЕ входит в passive income.


<a id="c8-r07-09-scenario-lab-contract-13-example-f--currency-tag-without-translation-basis"></a>
#### Example F — currency tag without translation basis

Base:

- instrument currency = USD
- market_value_kopecks = RUB 1000 equivalent
- native value absent
- accepted base FX translation basis absent

Scenario:

USD reporting value +10%.

Result:

`unavailable`

reason:

`fx_translation_basis_unavailable`

Расчёт:

`1000 × 1.10 = 1100`

только на основании currency tag ЗАПРЕЩЁН.


<a id="c8-r07-09-scenario-lab-contract-13-example-g--inflation-real-value"></a>
#### Example G — inflation real-value

Base month = M0.

Known future payment через 6 calendar months.

Nominal payment = N.

Scenario:

annual inflation = 12%.

V1 monthly rate:

`1%`

Real-value equivalent:

`N / 1.01^6`

Nominal payment N остаётся неизменным.


<a id="c8-r07-09-scenario-lab-contract-13-example-h--combined-shocks"></a>
#### Example H — combined shocks

Input содержит одновременно:

- equity_drawdown;
- fx_translation_shock.

Result:

`unsupported_composition_v1`

Implementation не выбирает additive/multiplicative/order semantics.


<a id="c8-r07-09-scenario-lab-contract-13-example-i--deterministic-replay"></a>
#### Example I — deterministic replay

Run 1:

- frozen base payload X
- contract version V
- normalized scenario S

Run 2:

- frozen base payload X
- contract version V
- normalized scenario S

Semantic outputs и fingerprint обязаны совпасть.

Разница `generated_at` не влияет на semantic fingerprint.


<a id="c8-r07-09-scenario-lab-contract-13-example-j--no-db-mutation"></a>
#### Example J — no DB mutation

После любого Scenario Lab evaluation не изменяются:

- ReportingMonth;
- PositionSnapshot;
- DepositSnapshot;
- CashBalance;
- canonical future cash flows;
- provider data;
- actual income;
- Goals;
- other canonical financial state.

Любой Scenario Lab write path в эти данные — BLOCKER.

---


<a id="c8-r07-09-scenario-lab-contract-13-16-explicit-controversial-decisions"></a>
#### 16. Explicit controversial decisions

Следующие решения являются намеренными v1 decisions.


<a id="c8-r07-09-scenario-lab-contract-13-c1--single-shock-only"></a>
#### C1 — single-shock only

ACCEPT.

Combined scenarios вне v1.


<a id="c8-r07-09-scenario-lab-contract-13-c2--equity-means-explicit-stock-only"></a>
#### C2 — equity means explicit stock only

ACCEPT.

Fund и другие market-priced assets автоматически equity не считаются.


<a id="c8-r07-09-scenario-lab-contract-13-c3--instrumentcurrency-alone-is-insufficient-for-fx-revaluation"></a>
#### C3 — Instrument.currency alone is insufficient for FX revaluation

ACCEPT.

Это намеренно консервативная semantics.

Current FX scenario может быть largely unavailable до принятия authoritative FX translation contract.

Это лучше, чем технически точная, но финансово выдуманная цифра.


<a id="c8-r07-09-scenario-lab-contract-13-c4--issuer-impairment-requires-explicit-impact_scope"></a>
#### C4 — issuer impairment requires explicit impact_scope

ACCEPT.

Нельзя implicit решить, что «issuer impairment» означает одновременно падение market value, cancellation coupons и haircut redemption.


<a id="c8-r07-09-scenario-lab-contract-13-c5--future-flow-issuer-haircut"></a>
#### C5 — future-flow issuer haircut

Если impact_scope включает future cash flows, выбранный haircut применяется одинаковым explicit percentage к issuer-linked known flows.

Но income и redemption/principal остаются разными output categories.

Это uniform deterministic what-if, не recovery model.


<a id="c8-r07-09-scenario-lab-contract-13-c6--future-forecast-shocks-не-переписывают-current-actual-based-passive-income-goal-progress"></a>
#### C6 — future forecast shocks не переписывают current actual-based passive-income Goal progress

ACCEPT.

Canonical Goal semantics имеют приоритет.


<a id="c8-r07-09-scenario-lab-contract-13-c7--inflation-is-real-value-view-not-future-capital-forecast"></a>
#### C7 — inflation is real-value view, not future-capital forecast

ACCEPT.

Future capital trajectory отсутствует.

---


<a id="c8-r07-09-scenario-lab-contract-13-17-explicitly-outside-scenario-lab-v1"></a>
#### 17. Explicitly outside Scenario Lab v1

Вне scope:

- combined/multi-shock scenarios;
- Monte Carlo;
- probabilities;
- VaR;
- correlations;
- beta;
- likelihood presets;
- market forecasts;
- expected returns;
- issuer default probability;
- recovery timing;
- seniority waterfall;
- contagion;
- sector shocks;
- bond duration/rate-price modeling;
- FX beta inference;
- synthetic currency exposure inference;
- fund look-through;
- reinvestment assumptions;
- hypothetical sale tax;
- behavioral response;
- automatic rebalancing;
- provider refresh;
- network refresh;
- canonical financial writes.

Если один из этих пунктов нужен реализации, задача должна STOP + re-scope и получить отдельный contract.

---

<a id="c8-r07-09-scenario-lab-contract-1353"></a>
### Accepted scenario edge cases

<a id="c8-r07-09-scenario-lab-contract-1353-accepted-reviewer-additions"></a>
#### Accepted reviewer additions

В canonical Git document добавь следующие три уточнения, не меняя остальную семантику.


<a id="c8-r07-09-scenario-lab-contract-1353-addition-1--fx-reporting-currency-edge"></a>
#### Addition 1 — FX reporting-currency edge

В `fx_translation_shock` нормативно добавить:

если:

`target_currency == reporting_currency`

то для reporting-currency exposure:

- row applicability = `not_applicable`;
- value = `unchanged`.

Это не FX translation.


<a id="c8-r07-09-scenario-lab-contract-1353-addition-2--inflation-same-month-acceptance-case"></a>
#### Addition 2 — inflation same-month acceptance case

Основную inflation formula НЕ менять.

Добавить acceptance case:

при:

`months_ahead = 0`

получаем:

`real_value = nominal_value`.


<a id="c8-r07-09-scenario-lab-contract-1353-addition-3--all_eligible_deposits-reproducibility"></a>
#### Addition 3 — all_eligible_deposits reproducibility

Если `deposit_rate_assumption.target_scope = all_eligible_deposits`:

- eligibility set определяется один раз из frozen base payload scenario;
- этот frozen eligibility set становится частью `normalized_target_scope`;
- он участвует в semantic fingerprint;
- selector НЕ переоценивается позднее против изменившейся database.

<a id="c9"></a>

Selective quote Apply reuses its immutable reviewed Preview, exact target snapshot/date, explicit mapping and selected fields; refetch/changed-source guards are atomic and no network refetch occurs under a financial commit. Existing manual/immutable quote provenance is not overwritten by unrelated provider snapshots. Alfa provider Price/UchPrice/NKD/P&L remain comparison observations; the later approved baseline/mapping contract supplies only its explicitly allowed persisted fields. The earlier release-wide ban on all persistent broker mappings is superseded by that accepted registry, not by arbitrary provider payload persistence.

## 9. Providers, freshness, reconciliation and source units

T-Invest market data, Alfa current snapshots, MyBroker historical originals, PDF realised payouts and MOEX identity/reference data have separate authority. No provider omission or empty/error result silently deletes facts or proves zero. Reconciliation preview is not Apply eligibility. Retain immutable source/quote provenance, exact Decimal parsing and version-specific typed diagnostics; never invent fallback protocol behavior.

<a id="c9-freshness_provenance-1"></a>
### Independent freshness clocks and provenance

**Status:** implementation contract for issue #139.
**Endpoint:** `GET /api/months/{month_id}/freshness-provenance`
**Assembly:** `hermes_finance.services.freshness_provenance.build_freshness_provenance_summary`

This is a read-only summary of **already persisted** provenance. It does not fetch
providers, refresh quotes, apply snapshots, or invent timestamps.


<a id="c9-freshness_provenance-1-four-clocks-that-must-not-be-mixed"></a>
#### Four clocks that must not be mixed

| Clock | Meaning | Used for freshness? |
|---|---|---|
| Source timestamp | Provider observation or event date that Hermes actually stored (`price_date`, `payment_date`, `event_date`, `fetched_at` when that is the observation) | Only when the family has a defined freshness rule |
| Import/apply time | When the owner accepted the data into Hermes | Never |
| Reporting month | Selected `year`/`month` plus `snapshot_date` | Identifies the slice; not a freshness clock |
| Local edit time | Hermes `updated_at` for manual rows | Never |

`generated_at` / `evaluated_on` are evaluation-clock inputs, not financial observations.

Quote valuation target is `min(snapshot_date, evaluated_on)` (ADR 0009). That target is
**not** the reporting month itself and **not** the apply timestamp.


<a id="c9-freshness_provenance-1-no-universal-score"></a>
#### No universal score

The summary never emits a freshness percentage, index, or blended score. Families are
not averaged. A missing Alfa PRO observation timestamp does not pull quotes toward
“stale”. Manual rows do not enter a denominator.


<a id="c9-freshness_provenance-1-family-semantics"></a>
#### Family semantics


<a id="c9-freshness_provenance-1-market_quotes"></a>
#### `market_quotes`

Persisted `PositionSnapshot` rows for the selected month plus latest append-only
`position_quote_provenance` for that snapshot.

- Freshness is classified only for a **current** provider price source (`t_invest`, `moex`)
  that still has provenance with a `price_date`.
- Classifier: ADR 0009 `classify_freshness(quote_valuation_target_date, price_date)`.
  `ok` → `current`; 8..30 day gap → `stale`; >30 days → `unavailable`.
- A later manual override is current-source `manual`. Historical quote provenance remains
  visible as history and does **not** keep classifying the row as stale.
- Manual / `alfa_pdf` prices without a provider timestamp are `not_applicable`, never stale.
- Mapped-but-never-applied quotes are a coverage warning (`mapped_quote_not_applied`), not stale.
- `fetched_at` is the provider-read time. `applied_at` is owner apply. Neither is `price_date`.


<a id="c9-freshness_provenance-1-t_invest_payouts"></a>
#### `t_invest_payouts`

Active applied T-Invest payout events for the month.

- `payment_date` is an event date, not a quote observation.
- Events are not classified current/stale by age. Family status is `not_applicable` when
  rows exist, `missing` when none exist.
- Latest revision supplies `fetched_at` (provider read) and `applied_at` (owner apply).


<a id="c9-freshness_provenance-1-alfa_pro_positions"></a>
#### `alfa_pro_positions`

Reads persisted owner-approved baseline provenance (ADR 0016 §8). `source_as_of` is the
observation clock. `confirmed_at` is import/apply time and is **not** freshness.
`baseline_date`, `snapshot_date`, and `updated_at` are not freshness clocks.

- No persisted baseline for the month → family status `unknown`, reason
  `alfa_pro_observation_not_persisted`. `providers` stays empty so capability alone
  cannot list `alfa_pro` or create `multiple_providers`.
- Persisted baseline present → family status `not_applicable` (holdings observation is
  not quote-stale). Reasons `alfa_pro_baseline_present` and
  `alfa_pro_observation_not_freshness_classified`. `providers` lists the baseline
  provider (`alfa_pro`).
- Do not classify this family current/stale/unavailable by the quote 8/30-day window.


<a id="c9-freshness_provenance-1-alfa_statement_payouts"></a>
#### `alfa_statement_payouts`

Active Alfa depository income-report events linked to this month’s investment cash flows.

- `event_date` / `record_date` are document event dates, not quote freshness.
- `applied_at` is import/apply time.
- Not classified current/stale by age.


<a id="c9-freshness_provenance-1-manual_month_data"></a>
#### `manual_month_data`

Local month entries that Hermes already treats as owner-maintained: incomes, expenses,
savings, expected cash flows, and position snapshots whose current `price_source` is
`manual` or `alfa_pdf`.

- No provider timestamp → `not_applicable`, never stale.
- Local `updated_at` is reported only as `local_edit_time` when the table has it.


<a id="c9-freshness_provenance-1-deposit_cash_snapshots"></a>
#### `deposit_cash_snapshots`

Deposit snapshots and cash balances for the month.

- Locally entered. Freshness is `not_applicable` when rows exist, `missing` when none exist.
- Deposit `updated_at` is `local_edit_time` only. Cash balances have no edit timestamp;
  that absence is `source_timestamp_unavailable` / `local_edit_time` null, not stale.


<a id="c9-freshness_provenance-1-status-values"></a>
#### Status values

Per classifiable observation (`freshness_status` on an item):

- `current` — provider observation is within the family rule
- `stale` — provider observation is inside the stale window
- `unavailable` — observation exists but is outside the usable window (quotes >30 days)
- `unknown` — family/item cannot be classified (missing observation timestamp)
- `not_applicable` — no provider freshness rule applies
- `missing` — used on family coverage when the family has no rows (not on quote items)

Family `status` additionally allows `mixed` when classifiable quotes contain both
`current` and `stale`/`unavailable`.


<a id="c9-freshness_provenance-1-reason-codes"></a>
#### Reason codes

Stable machine codes for later Close Cockpit (#136) consumption. Severity here is
informational vs warning only. This endpoint never promotes a warning to a close blocker.

| Code | Typical severity | Meaning |
|---|---|---|
| `quote_current` | info | At least one applied quote is current vs valuation target |
| `quote_stale` | warning | At least one applied quote is stale vs valuation target |
| `quote_unavailable` | warning | Applied quote `price_date` is beyond the 30-day lookback |
| `quote_source_timestamp_inconsistent` | warning | Stored `price_date` is after the valuation target |
| `mapped_quote_not_applied` | warning | Refresh-eligible mapping exists, no current provider quote |
| `manual_source_no_provider_timestamp` | info | Manual/local value; not stale |
| `historical_quote_provenance_present` | info | Snapshot was overridden; old quote provenance kept |
| `payout_event_present` | info | Applied T-Invest payouts exist |
| `payout_none_for_month` | info | No applied T-Invest payouts in this month |
| `payout_not_freshness_classified` | info | Payout events are not quote-stale |
| `alfa_pro_observation_not_persisted` | info | Cannot classify Alfa PRO observation time |
| `alfa_pro_baseline_present` | info | Owner-approved Alfa PRO current-state baseline is persisted for the month |
| `alfa_pro_observation_not_freshness_classified` | info | Persisted `source_as_of` is observation time, not quote freshness |
| `statement_event_present` | info | Active statement events exist for the month |
| `statement_none_for_month` | info | No active statement events in this month |
| `statement_not_freshness_classified` | info | Statement events are not quote-stale |
| `manual_month_data_present` | info | Owner-maintained month rows exist |
| `manual_month_data_empty` | info | No manual month rows |
| `deposit_cash_present` | info | Deposit/cash snapshots exist |
| `deposit_cash_empty` | info | No deposit/cash snapshots |
| `deposit_cash_local_edit_only` | info | Only local edit time exists |
| `source_timestamp_unavailable` | info | This clock is absent; do not infer stale |
| `multiple_providers` | info | More than one provider appears in the selected month |


<a id="c9-freshness_provenance-1-privacy-and-non-goals"></a>
#### Privacy and non-goals

- No raw provider payloads, tokens, document bytes, hashes, provider account/instrument
  UIDs, or filesystem paths.
- No background refresh or network on this path.
- Provenance tables remain append-only; this endpoint does not write.
- Close Cockpit (#136) should import these reason codes rather than re-derive quote
  freshness or treat apply time as observation time.

<a id="c9-t-invest-market-data-1"></a>
### T-Invest authority, quote units and payout support

Hermes Finance uses **T-Invest** as the production read-only source for owner-triggered quote preview and, in 0.5, future investment payout events. Direct MOEX ISS is not a production quote fallback. The separate explicit bounded official identity/denomination lookup in C4 is supported and is not quote authority.

Alfa PRO current snapshot and the accepted Alfa depository income-payment PDF import are 0.6 product paths; their complete current authority is specified in C3/C4/C9. This file remains the T-Invest quote/payout guide.


<a id="c9-t-invest-market-data-1-what-this-does"></a>
#### What this does

After a local read-only token is configured, you can:

1. open an instrument;
2. press **Найти в T-Invest**;
3. choose one candidate and save the mapping;
4. press **Обновить котировки** in a reporting month;
5. inspect the preview. Nothing is applied to snapshots in this task.

There is no background refresh and no trading.


<a id="c9-t-invest-market-data-1-provider-capabilities"></a>
#### Provider capabilities

The local diagnostics endpoint `GET /api/market-data/providers/capabilities`
exposes the registered market-provider profiles without constructing a client or
calling a remote service. Each capability is marked `production_enabled`,
`verification_only` or `unsupported`, with supported instrument types and
limitations. T-Invest payout/calendar support is represented by its separate
owner-triggered payout adapter; Alfa PRO broker snapshots are not part of this
market-data contract.


<a id="c9-t-invest-market-data-1-token"></a>
#### Token

You need a T-Invest / T-Bank brokerage account, even an empty one.

1. Open the official token page: <https://developer.tbank.ru/invest/intro/intro/token>
2. Create a **read-only** token. Do **not** create Full Access. Do **not** create Transfer access.
3. Put it only in the ignored repository-root `.env` file (next to `.env.example`, not in `backend/`):

```env
HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN=
```

Hermes always reads `<repository-root>/.env`, including when `scripts/start-local.ps1` starts the backend from the `backend/` directory. Process environment variables still override the file.

4. Restart the local Hermes backend after changing the token.

The token never belongs in Git, the SQLite database, the browser, API responses, logs, tests, or reports.

Hermes cannot prove that a pasted token is read-only without calling forbidden trading methods. The guarantee on our side is documentation plus a client that implements **no** order, cancel, replace, sandbox-trading, or money-transfer methods.


<a id="c9-t-invest-market-data-1-preview"></a>
#### Preview

Quote preview remains an explicit button. A missing token fails calmly and does not fall back to MOEX. An old `moex_iss` mapping stays readable; production does not call MOEX for it. Remapping to T-Invest is an explicit owner action.


<a id="c9-t-invest-market-data-1-payouts-05"></a>
#### Payouts (0.5)

Future coupons, dividends and redemptions are fetched only after an explicit owner preview. Hermes positions remain local: there is no broker portfolio/account import. Apply freezes the quantity from the local `PositionSnapshot` and never edits manual expected-flow rows. Unresolved duplicates stay manual-only. Provider coupons may feed C04; provider dividends stay calendar-visible and do not change the historical C04 dividend component; redemption is cash flow, never passive income. Reaching an event date does not create a realized investment cash flow. Startup, dashboard and month reads do not call T-Invest.


<a id="c9-t-invest-market-data-1-live-probe-developer-only"></a>
#### Live probe (developer only)

CI never runs this. From `backend/`:

```text
uv run python -m hermes_finance.market_data.t_invest_probe --live
```

The quote probe reads only `HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN` from the ignored repository-root `.env`. It calls FindInstrument, GetInstrumentBy, BondBy, GetLastPrices and GetCandles. It does not call Accounts, Operations, Orders, Sandbox or Transfer. It does not write a mapping or a monthly snapshot. Optional `--write-fixture` stores a sanitized public payload under `backend/tests/fixtures/t_invest/`.

Payout-event evidence (R05-01) is a separate developer-only probe:

```text
uv run python -m hermes_finance.market_data.t_invest_payout_probe --live
```

It may call only `FindInstrument`, `GetInstrumentBy`, `BondBy`, `GetBondCoupons`, `GetBondEvents` and `GetDividends`. It does not implement the payout calendar, apply events, or call account/portfolio/trading APIs. Optional `--write-fixture` writes `backend/tests/fixtures/t_invest/official_payout_shape.json`.


<a id="c9-t-invest-market-data-1-troubleshooting-the-live-probe"></a>
#### Troubleshooting the live probe

On the owner's Windows environment, the official T-Invest API was unreachable while a VPN was active and the same probe succeeded after the VPN was disabled. If the live probe has a network/connection failure, retry once with the VPN disabled before diagnosing the adapter. This is troubleshooting guidance for the observed environment, not an application networking requirement.

If authentication is rejected, verify that the token is a current **read-only** T-Invest token. The owner-side acceptance probe succeeded after an invalid/rejected token was reissued. Never print or paste the token into logs, reports, GitHub issues, or chat.

`--write-fixture` is optional and is not needed for a routine owner acceptance probe. Use it only when intentionally refreshing the sanitized deterministic fixture after an official API shape change; review the generated public fixture before committing it.

<a id="c9-reconciliation-normalized-contract-8"></a>
### Normalized comparison states and eligibility

<a id="c9-reconciliation-normalized-contract-8-endpoint"></a>
#### Endpoint

`POST /api/months/{reporting_month_id}/broker-reconciliation-preview`

`POST /api/months/{reporting_month_id}/reconciliation-preview` is an equivalent
short alias. The request has the existing broker snapshot preview mapping
shape:

```json
{
  "accounts": [
    {"hermes_account_id": 1, "provider_account_id": "SYN-ACCOUNT-001"}
  ],
  "instruments": [
    {"hermes_instrument_id": 10, "provider_instrument_id": "SYN-INSTRUMENT-001"}
  ],
  "expected_rows": [
    {"hermes_account_id": 1, "instrument_id": 10, "fingerprint": "..."}
  ],
  "expected_snapshot_fingerprint": "..."
}
```

`expected_rows` and `expected_snapshot_fingerprint` are optional. When present,
they reuse the accepted preview/apply fingerprint semantics and a mismatch
returns a stale, non-actionable result. The provider is called only during
this explicit request.


<a id="c9-reconciliation-normalized-contract-8-normalized-position-states"></a>
#### Normalized position states

Each response `rows[]` item has exactly one canonical `state`:

| State | Meaning |
|---|---|
| `matched` | Account/instrument identity is resolved and Decimal quantities are equal. |
| `differs` | Identity is resolved and the provider/local quantities differ. |
| `missing_local` | A resolved provider position has no local Hermes position. |
| `missing_provider` | A local Hermes position has no resolved provider row. |
| `unresolved` | Mapping, duplicate identity, quantity, compatibility or freshness prevents a safe comparison. |

An unresolved provider position is retained as a row with an explicit
`reason`; it is never silently relabelled as `missing_local`. Safe display
identifiers are limited to the existing mapping contract and normalized
account/instrument label, ticker and ISIN fields where available.


<a id="c9-reconciliation-normalized-contract-8-values-and-gates"></a>
#### Values and gates

- `provider_broker_unit_price`, `provider_accounting_price`,
  `provider_market_value`, `provider_accrued_interest_nkd` and
  `provider_unrealized_result` are comparison-only observations. Their names
  are listed in `comparison_only_fields`; none can overwrite Hermes values.
- Identity reuses explicit account mapping, explicit instrument mapping and
  exact unique ISIN matching from the accepted reconciliation preview.
- An incomplete, stale, non-eligible or compatibility-unknown snapshot is
  fail-closed. The response keeps the diagnostic state/reason and exposes no
  actionable position rows.
- `diagnostics` and `diagnostic_report` reuse the sanitized Alfa compatibility
  and fingerprint contract. They contain no raw provider payload, credential,
  private value or runtime path.
- `read_only` is always `true` and `eligible_for_apply` is always `false` for
  this slice. There is no new apply endpoint, transaction import or background
  refresh.

<a id="c9-0009-moex-market-identity-and-quote-semantics-18"></a>
### Exact MOEX identity and source units

<a id="c9-0009-moex-market-identity-and-quote-semantics-18-decision"></a>
#### Decision


<a id="c9-0009-moex-market-identity-and-quote-semantics-18-1-scope-of-supported-instruments-in-04"></a>
#### 1. Scope of supported instruments in 0.4

Automatic MOEX quote refresh supports only:

- `stock`;
- `fund`;
- `bond`.

A candidate is eligible only when the quote can be represented in the application's existing RUB per-unit money model without FX conversion.

The following remain manual/unsupported in 0.4:

- `currency`;
- `gold`;
- `other`;
- any stock/fund/bond whose applicable quote or required face-value conversion is not RUB-compatible;
- frozen/unlisted/non-MOEX assets without a valid compatible board mapping.

Unsupported is a normal product state, not a system error. Manual prices remain a first-class workflow wherever `manual_price_allowed` permits them.


<a id="c9-0009-moex-market-identity-and-quote-semantics-18-2-canonical-moex-identity"></a>
#### 2. Canonical MOEX identity

`SECID` alone is not sufficient because one security can exist on more than one trading board and board semantics affect the quote.

The logical canonical external identity is:

```text
provider = "moex_iss"
engine
market
boardid
secid
```

For 0.4 the expected compatible market families are:

```text
stock/fund -> engine=stock, market=shares
bond       -> engine=stock, market=bonds
```

`ISIN` remains a validation/discovery attribute, not the whole identity. `ticker` is a human-facing hint, not a normative external key.

If a local instrument has an ISIN and the candidate MOEX security exposes a different ISIN, the candidate is a hard mismatch and must not be persisted automatically.

The existing `moex_secid` field may participate in migration/discovery, but a fully accepted mapping must include the board-aware logical identity above.


<a id="c9-0009-moex-market-identity-and-quote-semantics-18-3-mapping-must-be-explicit"></a>
#### 3. Mapping must be explicit

Discovery may propose candidates; it must not persist a guessed mapping as truth.

Logical mapping states are:

- `unmapped` — no accepted external identity;
- `mapped` — one explicit accepted MOEX identity;
- `excluded` — owner has explicitly disabled external quote refresh for this instrument.

If there are multiple compatible candidates/boards and no already accepted mapping, the result is `ambiguous` and requires owner choice.

An exclusion is reversible. It skips the instrument during refresh without deleting manual values. Implementations may preserve the last mapping while disabled, but disabled state must win over the mapping for refresh eligibility.

Exact persistence shape is owned by R04-03, but it must preserve all logical fields above and must not infer a mapping during migration.


<a id="c9-0009-moex-market-identity-and-quote-semantics-18-4-refresh-is-always-target-dateas-of-never-blindly-now"></a>
#### 4. Refresh is always target-date/as-of, never blindly "now"

Quote refresh targets one reporting month and therefore one valuation date.

Define:

```text
target_date = min(reporting_month.snapshot_date, current_date_in_Europe/Moscow)
```

A MOEX proposal is valid only when:

```text
price_date <= target_date
```

The integration must never apply a later quote to an earlier monthly snapshot.

For a current target trading day:

1. use a valid `LAST` trade on the accepted board when available;
2. otherwise fall back to the latest valid completed trading result on or before `target_date`.

For a historical target date:

1. use the latest valid historical trading-result price on the accepted board on or before `target_date`;
2. never forward-fill from a later day.

The client may search back at most 30 calendar days from `target_date`. If no valid quote exists in that window, status is `unavailable` and the manual price remains unchanged.

`price_date` is the MOEX trading date of the selected quote, not the local HTTP-fetch date and not an invented reporting-month date.

An optional exchange trade time may be returned as preview metadata, but the current persisted snapshot contract remains date-based.


<a id="c9-0009-moex-market-identity-and-quote-semantics-18-5-freshness-policy"></a>
#### 5. Freshness policy

Freshness is a presentation/apply policy, not a financial formula.

Define quote age:

```text
age_days = target_date - price_date
```

Classification:

- `0..7` calendar days -> usable;
- `8..30` calendar days -> `stale`;
- older than 30 days -> no proposal / `unavailable`.

This deliberately handles ordinary weekends/holidays without requiring an exchange-calendar dependency in 0.4, while flagging illiquid or suspended instruments.

A stale proposal may be shown, but it is not selected for apply by default and requires explicit per-row owner selection. The UI must display its actual `price_date`.


<a id="c9-0009-moex-market-identity-and-quote-semantics-18-6-quote-field-semantics-for-stocks-and-funds"></a>
#### 6. Quote field semantics for stocks and funds

For a compatible stock/fund board:

- current-day primary raw field: `LAST`;
- historical raw field: the trading-result last/close value for that board/date, parsed according to the ISS history schema;
- bid/offer midpoint is never synthesized;
- `BID`, `OFFER`, indicative yields and unrelated reference fields are not fallback prices;
- settlement/quote currency must be RUB-compatible for the 0.4 write path.

The raw number is interpreted as cash RUB per one instrument only when the board metadata indicates a cash-per-instrument basis (`QUOTEBASIS=R`) or the applicable MOEX schema for the supported shares market defines the value as a monetary per-instrument price.

Non-positive, non-finite or structurally malformed prices are rejected as `malformed_response`.


<a id="c9-0009-moex-market-identity-and-quote-semantics-18-7-bond-quote-conversion-is-mandatory-and-exact"></a>
#### 7. Bond quote conversion is mandatory and exact

MOEX bond prices may be quoted as a percentage of face value. A percentage quote must never be written directly into `market_price_per_unit_kopecks`.

For a RUB bond with:

```text
QUOTEBASIS = F
FACEVALUE = face value of one security
raw_price = percent of face value
```

the proposed clean price per unit is:

```text
clean_price_rub = FACEVALUE * raw_price / 100
```

Conversion uses `Decimal` and the project financial rounding rule `ROUND_HALF_UP`, then stores integer kopecks.

Example with synthetic values:

```text
FACEVALUE = 1000.00 RUB
LAST/LASTPRICE = 97.25
proposed clean price = 972.50 RUB per bond
```

If `QUOTEBASIS=R`, the raw value is cash per instrument and no percentage conversion is performed.

Unknown quote basis, missing face value for `F`, or non-RUB face/settlement semantics -> `unsupported` or `malformed_response`; never guess.


<a id="c9-0009-moex-market-identity-and-quote-semantics-18-8-accrued-interest-is-deliberately-not-automated-in-04"></a>
#### 8. Accrued interest is deliberately not automated in 0.4

MOEX exposes accrued-interest data, but 0.4 refresh updates only the existing clean `market_price_per_unit` proposal.

It must not silently overwrite `PositionSnapshot.accrued_interest_kopecks`.

Reason: the current snapshot model treats accrued interest as a separate additive value in market-value calculation, and automatically changing it would extend the financial/storage contract beyond the quote-only release.

Therefore for bonds:

- external proposal = clean price per unit;
- existing accrued-interest value remains unchanged;
- UI/provenance must not imply that the MOEX clean quote already includes the locally stored accrued interest.

Automatic accrued-interest sourcing, if wanted later, requires a separate task/contract.


<a id="c9-0009-moex-market-identity-and-quote-semantics-18-9-numeric-parsing"></a>
#### 9. Numeric parsing

External JSON numeric values must not introduce binary-float financial arithmetic.

Normative boundary rule:

- parse external numeric tokens/values into exact decimal representation immediately;
- if an HTTP/JSON library materializes a Python/JS float first, convert only from its textual representation and never perform financial arithmetic on the binary float;
- all bond conversion and RUB/kopeck conversion uses `Decimal` + `ROUND_HALF_UP`;
- frontend never recomputes the authoritative proposed monetary value.


<a id="c9-0009-moex-market-identity-and-quote-semantics-18-10-preview-and-error-model"></a>
#### 10. Preview and error model

A batch refresh is allowed to partially succeed.

Per-instrument preview status set:

```text
ok
stale
unmapped
excluded
unsupported
ambiguous
unavailable
network_error
malformed_response
```

`ok` and explicitly selected `stale` rows are the only rows eligible for later apply.

One failed instrument must not erase successful proposals for other instruments.

A total transport failure may additionally produce a batch-level error, but local stored data remains unchanged.

No background retry loop, cron, daemon or startup fetch is allowed. Retry is an explicit owner action. R04-02 must use bounded HTTP timeouts and bounded request/concurrency behavior.


<a id="c9-0009-moex-market-identity-and-quote-semantics-18-11-draftclosed-month-semantics"></a>
#### 11. Draft/closed month semantics

Read-only preview may be requested explicitly for a closed month, but it must expose `apply_allowed=false`.

Actual apply:

- is allowed only for a `draft`/explicitly reopened reporting month;
- must pass the existing editable-month guard on the backend write boundary;
- never silently reopens or mutates a closed month.

Mapping is instrument-level reference configuration and may be edited independently of historical month values, but editing mapping never rewrites historical snapshots.


<a id="c9-0009-moex-market-identity-and-quote-semantics-18-12-data-usage--production-activation-gate"></a>
#### 12. Data-usage / production-activation gate

Technical architecture and parser work are allowed to proceed before production activation, but the product must not assume that unauthenticated delayed ISS automatically grants every intended automated-use right.

Before R04-06 is accepted for real live apply, and again before 0.4 release, the owner/reviewer must record one of:

1. the applicable MOEX terms/service explicitly permit this local single-user button-triggered usage; or
2. the owner has obtained/accepted the appropriate MOEX information service/terms; or
3. the production provider is changed to another source whose terms permit the intended use.

Until that gate is recorded:

- R04-02 may implement the provider adapter, deterministic parsers, mocked/public synthetic fixtures and a developer-only bounded live probe;
- no startup/background fetch;
- no release claim that live automated MOEX refresh is production-authorized;
- normal stable `main` remains unaffected.

This is a data-source usage gate, not a change to the local-only/no-auth architecture.


<a id="c9-0009-moex-market-identity-and-quote-semantics-18-13-minimal-immutable-provenance-on-apply"></a>
#### 13. Minimal immutable provenance on apply

Changing an instrument mapping later must not rewrite the meaning of an already applied historical quote.

Every externally applied quote must retain immutable minimal provenance logically equivalent to:

```text
provider = moex_iss (or accepted replacement provider)
engine
market
boardid
secid
raw_price_kind
raw_price_basis
raw_price_decimal
converted_price_kopecks
price_date
fetched_at_utc
position_snapshot_id / target
```

Do not persist the full raw provider payload.

`PositionSnapshot.price_source=moex` and `price_date` remain part of the normal snapshot contract. The exact additional storage representation is deferred to R04-06, but it must be snapshot/apply-specific rather than reconstructed from the instrument's current mapping.

<a id="c9-0010-market-and-broker-provider-strategy-17"></a>
### Provider bounded contexts

<a id="c9-0010-market-and-broker-provider-strategy-17-1-t-invest-is-the-selected-production-market-data-provider-for-04"></a>
#### 1. T-Invest is the selected production market-data provider for 0.4

The production market-data path for 0.4 will use T-Invest API through a dedicated read-only adapter behind the existing `MarketDataProvider` boundary.

Reasons:

- official read-only token exists and cannot submit trading orders;
- token may be restricted to one account;
- remote API works without a desktop terminal running;
- stock, fund/ETF and bond market data are documented;
- historical daily candles support deterministic as-of lookup beyond the 30-day ADR window;
- bond market price semantics are documented as percent of nominal, with nominal and currency available through exact `MoneyValue`/`Quotation` values;
- official materials support downloading/storing market history for private statistics; redistribution/public retransmission remains outside Hermes Finance scope;
- API limits are far above the expected manual monthly refresh load.

Recommended T-Invest identity:

- provider: `t_invest`;
- canonical provider key: `instrument_uid`;
- validation/display attributes: ticker, class_code, ISIN;
- FIGI is not canonical because T-Invest documents it as legacy/deprecated for new integrations.

The current MOEX-shaped identity (`provider + engine + market + boardid + secid`) must not be perpetuated by stuffing T-Invest values into semantically incorrect fields. Before implementing the T-Invest adapter, R04 receives a small provider-neutral identity refactor.


<a id="c9-0010-market-and-broker-provider-strategy-17-2-alfa-pro-is-the-bounded-broker-portfolio-snapshot-provider-for-alfa-accounts"></a>
#### 2. Alfa PRO is the bounded broker-portfolio snapshot provider for Alfa accounts

Alfa PRO is not selected as the primary 0.4 market-data source, but it is retained as a valuable future `BrokerPortfolioProvider` for the owner's Alfa brokerage/IIS data.

Documented useful capabilities include:

- account/subaccount data;
- current positions and quantities;
- accounting/average-price-related fields;
- cash and broker valuation;
- accrued coupon/NKD;
- unrealized P/L;
- identifiers correlating positions with instruments;
- at least partial operation/trade data.

Important Alfa limitations:

- PRO terminal must be installed, running and authenticated during API use;
- API is a localhost WebSocket router (`ws://127.0.0.1:3366/router/`);
- no true API read-only scope is documented; the same socket exposes order methods;
- bond market-data Last/Close unit is not documented clearly enough for authoritative conversion;
- IIS-vs-ordinary-account classification is not documented as an explicit API field;
- private persistence of quotes/account payloads needs confirmation from Alfa under the applicable terms.

For the owner's workflow, launching PRO manually once per month is considered acceptable if it enables local portfolio reconciliation. No Alfa broker import is part of 0.4.


<a id="c9-0010-market-and-broker-provider-strategy-17-3-market-data-and-broker-holdings-are-separate-bounded-contexts"></a>
#### 3. Market data and broker holdings are separate bounded contexts

A single Hermes instrument may have multiple provider projections.

Example conceptually:

```text
Hermes Instrument
  stable local identity / ISIN / ticker metadata

MarketData mapping
  provider = t_invest
  provider instrument key = instrument_uid
  -> current/historical market quote

BrokerPortfolio mapping
  provider = alfa_pro
  provider account/instrument identifiers
  -> actual account, position, quantity, broker valuation, NKD, cash
```

The market provider and broker provider must not be forced to share one identity schema.

Future broker integrations should use a separate boundary, e.g. `BrokerPortfolioProvider`, with provider-specific adapters such as:

- `AlfaProBrokerPortfolioProvider`;
- `TInvestBrokerPortfolioProvider`.

T-Invest broker data may later support T-Invest accounts, but it cannot read Alfa accounts; Alfa PRO cannot read T-Invest accounts.


<a id="c9-0010-market-and-broker-provider-strategy-17-provider-neutral-identity-requirement"></a>
#### Provider-neutral identity requirement

The accepted R04-03 mapping schema was designed around MOEX board identity. That assumption is now too narrow.

Before the T-Invest adapter is implemented:

1. introduce a provider-neutral canonical market identity contract;
2. preserve explicit owner mapping and no-silent-auto-map behavior;
3. preserve existing MOEX mappings without fabricating T-Invest mappings;
4. keep ISIN/ticker/class-code-like values as validation/discovery/display metadata, not necessarily the canonical provider key;
5. keep R04-04 preview and R04-05 UI behavior provider-neutral;
6. do not use field-name aliases that duplicate T-Invest `class_code` into both `market` and `boardid` merely to satisfy the old schema.

The exact storage shape is an implementation decision for the dedicated identity-refactor task, but it must represent both:

- MOEX ISS board-aware identity;
- T-Invest `instrument_uid` identity;

without semantic lying.

<a id="c9-0011-automatic-investment-payout-calendar-18"></a>
### Payout identity, dates, quantity, revision and coverage

<a id="c9-0011-automatic-investment-payout-calendar-18-decision-summary"></a>
#### Decision summary

Hermes SHALL use a separate provider-payout bounded context rather than silently inserting provider rows into the existing owner-entered `expected_cash_flows` table.

The lifecycle is:

```text
owner click
  -> fetch provider data
  -> normalize provider events
  -> compare with applied provider events + manual expected flows
  -> preview
  -> explicit owner selection
  -> apply with provider/local re-read and preview_changed guard
  -> append-only revision/provenance
```

The dashboard SHALL merge countable manual expected flows with countable applied provider payouts at read time. Manual owner records remain first-class and are never silently overwritten, deleted or reclassified.

The current C04 passive-income forecast formula remains unchanged in 0.5: expected coupons can improve C04, announced provider dividends appear in the payout calendar but do not replace the historical dividend component, and principal redemption never counts as passive income.


<a id="c9-0011-automatic-investment-payout-calendar-18-non-negotiable-invariants"></a>
#### Non-negotiable invariants

1. Windows-only/local-only product; runtime remains `127.0.0.1:8000`.
2. No cloud/auth/telemetry.
3. External provider access only after an explicit owner action.
4. No background refresh, startup fetch, cron, polling or retry loop.
5. Production provider is T-Invest read-only. No MOEX production fallback.
6. No `Accounts`, `Operations`, `Orders`, `StopOrders`, `Sandbox`, `Transfer` or broker-portfolio import in R05.
7. Financial arithmetic uses `Decimal` and/or integer minor units with `ROUND_HALF_UP`; binary float is forbidden.
8. Closed reporting months are immutable until explicit reopen. Preview MAY read a closed month; apply MUST reject it.
9. Provider-derived expected events and actual realized investment cash flows are separate concepts. Reaching an expected payment date MUST NOT auto-create an actual cash flow.
10. Principal redemption/repayment is future cash flow, not passive income.
11. Existing manual expected flows are owner data and MUST NOT be silently overwritten, deleted, reclassified or merged by provider refresh.
12. Tokens, account IDs, private DB/export contents and full raw provider payloads MUST NOT be persisted for payout audit purposes.
13. Owner-facing provider failures MUST be sanitized; raw provider bodies/tokens/stacks are not returned to the browser.


<a id="c9-0011-automatic-investment-payout-calendar-18-existing-local-semantics-that-remain-authoritative"></a>
#### Existing local semantics that remain authoritative

The existing `expected_cash_flows` model is month-scoped and versioned, and its calendar already distinguishes coupon/dividend/interest/redemption/other. Redemption is included in total cash flow but excluded from passive income.

The current forecast formula remains:

```text
forecast_12m_net_passive_income =
    expected_deposit_interest_next_12m
  + expected_coupon_net_next_12m
  + expected_dividend_component_from_eligible_closed_actual_history
  + other_expected_capital_income
```

Expected dividend rows are intentionally not used by C04 today. R05 MUST NOT change that formula implicitly.


<a id="c9-0011-automatic-investment-payout-calendar-18-provider-boundary"></a>
#### Provider boundary

Introduce a provider-neutral payout boundary separate from quote retrieval.

A normalized provider event MUST contain only normalized/public event data needed for identity, classification, amount, dates, coverage and audit. The adapter MUST NOT own financial policy such as whether redemption counts as income or how manual duplicates are resolved.

Production routing in 0.5 is T-Invest only.


<a id="c9-0011-automatic-investment-payout-calendar-18-canonical-event-kinds"></a>
#### Canonical event kinds

0.5 recognizes these normalized event kinds:

- `coupon`
- `dividend`
- `redemption`

Unsupported provider event kinds remain visible as `unsupported` when useful, but are not applied.

For T-Invest bond events specifically:

- `EVENT_TYPE_MTY` is a redemption candidate;
- `EVENT_TYPE_CALL` is an offer/call event, not automatically a redemption cash flow;
- `EVENT_TYPE_CONV` is conversion, not a redemption cash flow;
- `EVENT_TYPE_CPN` MUST NOT be imported in parallel with `GetBondCoupons` unless a later live probe proves a non-duplicating use.


<a id="c9-0011-automatic-investment-payout-calendar-18-event-identity"></a>
#### Event identity


<a id="c9-0011-automatic-investment-payout-calendar-18-general-rule"></a>
#### General rule

Canonical identity is:

```text
(provider, instrument_uid, event_kind, identity_key)
```

For 0.5 `provider = t_invest`.

`instrument_uid` is the canonical T-Invest instrument identity accepted in ADR 0010. FIGI is not the canonical persisted payout identity.

A provider-native event identifier MAY replace/further qualify the natural key only after a live probe demonstrates that it exists and is stable across refreshes/revisions.

Mutable fields MUST NOT be part of identity merely for convenience. In particular, amount, owner quantity, tax estimate and normally payment date are revision data rather than identity data.


<a id="c9-0011-automatic-investment-payout-calendar-18-coupon-identity"></a>
#### Coupon identity

Preferred `identity_key`:

1. `n:{coupon_number}` when `coupon_number > 0`;
2. otherwise `p:{coupon_start_date}:{coupon_end_date}` only when both dates exist and the pair is unambiguous for the instrument;
3. otherwise the event is `ambiguous_identity` and MUST NOT be applied automatically.

`coupon_date`, amount, coupon type, quantity and tax do not enter identity.


<a id="c9-0011-automatic-investment-payout-calendar-18-dividend-identity"></a>
#### Dividend identity

Preferred `identity_key`:

1. a stable provider event ID, if a later live probe proves one exists and is stable;
2. otherwise `r:{record_date}`.

`dividend_type` MUST NOT be part of identity because provider state such as `Cancelled` is lifecycle/revision information for the same declared event, not necessarily a distinct payout.

If more than one distinct provider dividend for one instrument resolves to the same natural identity and no stable provider ID disambiguates them, the rows are `ambiguous_identity` and MUST NOT be applied automatically.

If neither stable provider ID nor `record_date` is available, the dividend is not automatically applyable.


<a id="c9-0011-automatic-investment-payout-calendar-18-redemption-identity"></a>
#### Redemption identity

Preferred source is `GetBondEvents` with `EVENT_TYPE_MTY`.

Preferred `identity_key`:

1. `mty:{event_number}` when `event_number > 0`;
2. otherwise `mty-date:{event_date}` only when the date is present and uniquely identifies one MTY event for the instrument;
3. otherwise `ambiguous_identity`.

A synthetic maturity event derived from `BondBy.maturity_date` plus nominal is **not** enabled by this ADR by default. R05-01 live probe MUST establish whether this is safe, and any later enabling MUST at minimum exclude perpetual bonds and handle amortizing bonds conservatively.


<a id="c9-0011-automatic-investment-payout-calendar-18-date-semantics"></a>
#### Date semantics

All provider timestamps used as financial calendar dates MUST be converted through the project's Moscow calendar-date normalization and persisted/compared as date-only values where the business concept is a date rather than an instant.


<a id="c9-0011-automatic-investment-payout-calendar-18-coupon"></a>
#### Coupon

- announcement/declaration: metadata only if present;
- `fix_date`: record/fix date, metadata only;
- `coupon_start_date` / `coupon_end_date`: coupon-period metadata and possible identity fallback;
- `coupon_date`: **canonical payout calendar date**.

If `coupon_date` is absent, Hermes MUST NOT invent the payout date from `coupon_end_date`; the row is tentative/incomplete and not applyable.


<a id="c9-0011-automatic-investment-payout-calendar-18-dividend"></a>
#### Dividend

- `declared_date`: announcement date;
- `last_buy_date`: eligibility/ex-date-adjacent metadata, not payout date;
- `record_date`: owner registry/fix date and preferred natural identity anchor;
- `payment_date`: **canonical payout calendar date**.

If `payment_date` is absent, Hermes MAY show the event as tentative in preview but MUST NOT synthesize a date or apply it to the cash-flow calendar.

No rule such as `record_date + N business days` is part of 0.5.


<a id="c9-0011-automatic-investment-payout-calendar-18-redemption"></a>
#### Redemption

For a validated MTY event:

1. `pay_date` is preferred calendar date when present;
2. otherwise `event_date` may be used if the live probe confirms its meaning for MTY events;
3. a `BondBy.maturity_date` fallback requires the explicit post-probe decision described above.


<a id="c9-0011-automatic-investment-payout-calendar-18-amount-semantics"></a>
#### Amount semantics


<a id="c9-0011-automatic-investment-payout-calendar-18-general-calculation"></a>
#### General calculation

Provider amounts are normalized from exact MoneyValue/Quotation representations to Decimal without binary float.

For an applyable per-unit amount:

```text
total_amount = ROUND_HALF_UP(per_unit_decimal * exact_snapshot_quantity, 0.01 RUB)
```

Do not round the per-unit amount prematurely to kopecks and then multiply if that can change the final result. Provenance SHOULD retain the exact normalized per-unit decimal representation plus the final integer-kopek total.

R05 is RUB-only. Non-RUB payout events are `unsupported`; there is no FX conversion.


<a id="c9-0011-automatic-investment-payout-calendar-18-coupon-1"></a>
#### Coupon

Use provider per-bond payout when present and valid. Do not derive a coupon from percentage/nominal when the authoritative per-unit payout is missing.

Unknown personal tax semantics remain unknown:

- expected tax = unknown/null;
- expected cash amount = provider announced amount;
- result is marked approximate for net-income purposes.

Floating/variable coupon rows with missing or clearly non-final payout amount are tentative until the live probe defines observed behavior.


<a id="c9-0011-automatic-investment-payout-calendar-18-dividend-1"></a>
#### Dividend

T-Invest currently documents `dividend_net` as the dividend amount per security including currency. The field name MUST NOT be interpreted as proof of the owner's personal after-tax cash receipt.

0.5 stores/interprets it as the provider-announced per-unit payout amount unless the live probe establishes a stronger semantic contract.

Hermes MUST NOT fabricate 13%/15% or any other personal tax amount. Tax remains unknown; the UI must label the amount accordingly.

`Daily Accrual`, `Return of Capital` and other non-ordinary dividend types are not silently treated as ordinary passive-income dividends. They require explicit normalization rules or remain unsupported. `Return of Capital` is not passive income.


<a id="c9-0011-automatic-investment-payout-calendar-18-redemption-1"></a>
#### Redemption

Use validated per-bond principal repayment from the MTY event when available.

Redemption is included in future cash flow and excluded from passive income.

Amortizing principal schedules require live-probe evidence; `amortization_flag` alone is not a sufficient schedule.


<a id="c9-0011-automatic-investment-payout-calendar-18-position-quantity-semantics"></a>
#### Position quantity semantics

The driver of quantity is the `PositionSnapshot` for the **selected reporting month, account and instrument** on which the owner invoked payout preview.

Do not use:

- latest known quantity across arbitrary months;
- broker account holdings from T-Invest;
- a silently substituted later/earlier month.

Preview uses the exact selected snapshot quantity. On successful apply, quantity and total amount are frozen in the applied revision/provenance.

If the owner changes draft quantity afterward, existing applied totals do not silently recalculate. A later preview shows `revised` and an explicit apply is required.

If a position disappears after an earlier apply, the event is not auto-deleted. Preview may surface `position_gone`; owner action is required to dismiss/reconcile it.

Closed-month applied data is never rewritten by refresh of another month.


<a id="c9-0011-automatic-investment-payout-calendar-18-horizon-and-provider-coverage"></a>
#### Horizon and provider coverage

The owner-facing cash-flow horizon remains the existing 12-month interval from the selected reporting month's `snapshot_date`.

Provider request windows MAY be wider than the calendar horizon to accommodate provider filtering semantics, but they must be bounded and explicit.

Every successful provider fetch used for refresh comparison MUST produce coverage metadata sufficient to answer:

```text
method
instrument_uid
requested_from
requested_to
provider_filter_basis
successful/failed
```


<a id="c9-0011-automatic-investment-payout-calendar-18-coverage-aware-missing-rule"></a>
#### Coverage-aware missing rule

A previously applied event MUST NOT be labeled `missing_from_provider` merely because it is absent from a response.

`missing_from_provider` is valid only when all are true:

1. fetch for that exact instrument/method succeeded;
2. response was structurally valid;
3. the event's provider comparison/filter key lies inside the proven coverage of the request;
4. the event is absent from that successful covered response.

If network/auth/malformed/unknown-window conditions exist, no `missing_from_provider` inference is made.

This is especially important for dividends because T-Invest `GetDividends` filters requests by `record_date`, while Hermes calendars cash by `payment_date`.

`missing_from_provider` is a **derived refresh/preview state**, not automatic cancellation and not automatic database deletion. The last applied event remains active/countable unless the owner explicitly changes its lifecycle.


<a id="c9-0011-automatic-investment-payout-calendar-18-preview-state-machine"></a>
#### Preview state machine

Preview is read-only. It MUST NOT mutate manual expected flows, applied provider payouts, reporting months or position snapshots.

Minimum row statuses:

- `new`
- `unchanged`
- `revised`
- `possible_manual_duplicate`
- `cancelled_by_provider` when cancellation is explicit and identity is stable
- `missing_from_provider` under the coverage-aware rule
- `tentative`
- `ambiguous_identity`
- `unsupported`
- `unavailable`
- sanitized provider/local `error`
- `position_gone` where applicable

Defaults:

- `new`: selectable; default selection MAY be true for clearly valid non-duplicate rows;
- `revised`: selectable only by explicit owner choice;
- `possible_manual_duplicate`: not selected by default;
- cancellation/missing/tentative/ambiguous/unsupported/error: not auto-selected.


<a id="c9-0011-automatic-investment-payout-calendar-18-apply-and-preview_changed"></a>
#### Apply and preview_changed

Apply is allowed only in draft/reopened months.

Apply is selective and transactional for the selected set. If any selected row fails validation, re-fetch consistency, persistence or provenance write, the entire selected set rolls back.

Before mutation, apply MUST re-read both:

1. current provider-normalized event data through the same normalization path used by preview;
2. current local position snapshot/quantity and any manual reconciliation state referenced by the selection.

The apply selection carries the preview fingerprint. Material fields include at minimum:

```text
provider
instrument_uid
event_kind
identity_key
canonical payment_date
exact normalized per-unit amount
currency
provider lifecycle/status relevant to counting
position_snapshot_id
reporting_month_id
account_id
instrument_id
exact quantity
manual duplicate/link target when an owner decision depends on it
```

Any material mismatch produces `preview_changed`, performs zero writes, and requires a new explicit preview. Apply MUST NOT silently use the newly fetched values instead.


<a id="c9-0011-automatic-investment-payout-calendar-18-revision-and-disappearance-semantics"></a>
#### Revision and disappearance semantics


<a id="c9-0011-automatic-investment-payout-calendar-18-provider-changes-amountdate"></a>
#### Provider changes amount/date

Same stable identity + changed material attributes => `revised`.

Owner apply creates a new append-only revision/provenance record. Earlier revision data is retained.


<a id="c9-0011-automatic-investment-payout-calendar-18-explicit-provider-cancellation"></a>
#### Explicit provider cancellation

If the provider explicitly communicates cancellation for the same stable identity, preview shows `cancelled_by_provider`. Only explicit owner apply moves the applied payout lifecycle to cancelled. History remains.


<a id="c9-0011-automatic-investment-payout-calendar-18-provider-omission"></a>
#### Provider omission

Omission alone never deletes/cancels. Under proven coverage it may produce `missing_from_provider`; otherwise no missing inference is made.


<a id="c9-0011-automatic-investment-payout-calendar-18-event-reappears"></a>
#### Event reappears

If the same identity reappears, it becomes `unchanged` or `revised`. There is no delete/recreate cycle.


<a id="c9-0011-automatic-investment-payout-calendar-18-identity-changes"></a>
#### Identity changes

If the provider changes data such that the stable identity no longer matches and equivalence cannot be proved, Hermes represents old `missing` plus new `new`. It MUST NOT heuristic-auto-merge identities.


<a id="c9-0011-automatic-investment-payout-calendar-18-manual-reconciliation"></a>
#### Manual reconciliation

Manual `expected_cash_flows` remain untouched owner data.

Provider refresh MUST NOT change a manual row's:

- amount/tax/net;
- date;
- flow type;
- notes;
- confirmation state;
- source;
- existence.


<a id="c9-0011-automatic-investment-payout-calendar-18-duplicate-candidate"></a>
#### Duplicate candidate

`possible_manual_duplicate` is a warning, not identity.

A provider event is a duplicate candidate only within the same reporting month/account/instrument/flow type and when dates are sufficiently close for a plausible match. The implementation may use a deterministic conservative window, but amount MUST NOT be required for duplicate matching because provider vs manual tax/rounding semantics can differ.

If multiple manual candidates match, reconciliation is ambiguous and no automatic link is created.


<a id="c9-0011-automatic-investment-payout-calendar-18-owner-actions"></a>
#### Owner actions

For a duplicate candidate, 0.5 supports explicit outcomes:

- **Skip provider:** no provider apply.
- **Keep both:** provider is applied and both are deliberately countable; the UI warns before apply.
- **Link/reconcile:** both records remain auditable, but exactly one counting survivor is selected. Default survivor is manual unless owner explicitly selects provider.

R05 MUST NOT automatically replace/archive/delete a manual row as part of provider apply. Existing manual CRUD remains the only direct owner-edit/delete path for manual records.

An unresolved duplicate that the owner has not explicitly chosen to keep both MUST NOT silently double-count. The safe default is manual-only counting until resolution.


<a id="c9-0011-automatic-investment-payout-calendar-18-persistence-semantics"></a>
#### Persistence semantics

Exact SQL table names are implementation details, but the model has three logical concepts.


<a id="c9-0011-automatic-investment-payout-calendar-18-applied-provider-payout"></a>
#### Applied provider payout

Month/account/instrument/position scoped applied state containing at minimum:

- provider + provider instrument UID;
- event kind + stable identity key;
- current active lifecycle (`active`, `cancelled`, `dismissed` as needed);
- canonical payment date;
- frozen quantity;
- exact normalized per-unit source amount representation;
- final total integer-kopek amount;
- currency;
- approximation/amount-basis metadata;
- first applied timestamp;
- optional explicit manual reconciliation relation.

One provider identity may be applied separately to two accounts because quantities differ.

A uniqueness invariant MUST prevent duplicate applied copies of the same provider identity within one reporting-month/account/instrument scope.


<a id="c9-0011-automatic-investment-payout-calendar-18-payout-revisionprovenance"></a>
#### Payout revision/provenance

Append-only record on each successful new/revised/cancellation apply containing enough data to audit what the owner accepted:

- applied payout reference;
- revision kind;
- provider identity;
- dates;
- per-unit amount representation;
- frozen quantity;
- final totals;
- relevant provider status/type metadata;
- fetched timestamp;
- applied timestamp.

Do not store full raw provider payloads.


<a id="c9-0011-automatic-investment-payout-calendar-18-manual-reconciliation-relation"></a>
#### Manual reconciliation relation

An explicit relation may link one applied provider payout to one manual expected-flow row and record the counting decision. It MUST NOT mutate the manual row merely by creating the link.


<a id="c9-0011-automatic-investment-payout-calendar-18-dashboard-semantics"></a>
#### Dashboard semantics


<a id="c9-0011-automatic-investment-payout-calendar-18-a-future-cash-flow-calendar"></a>
#### A. Future cash-flow calendar

The 12-month calendar is the union of:

1. countable manual `expected_cash_flows` for the selected forecast version;
2. countable applied provider payouts for the selected reporting month.

The calendar distinguishes:

- coupon
- dividend
- interest (manual/deposit scope)
- redemption
- other

`total_net` / future cash inflow includes redemption.

`passive_net` excludes redemption.

An active event temporarily `missing_from_provider` remains counted at the last owner-applied value, with a visible warning, because omission is not evidence of cancellation.

Duplicate/reconciliation state determines one vs two countable rows; there must be no hidden accidental double count.


<a id="c9-0011-automatic-investment-payout-calendar-18-b-forecast-passive-income-c04"></a>
#### B. Forecast passive income (C04)

R05 preserves the accepted C04 formula.

- applied provider coupon: eligible to contribute like an expected coupon, subject to duplicate/reconciliation counting rules;
- applied provider dividend: shown in the cash-flow calendar but **does not** replace/add to the C04 dividend component in formula version v1;
- redemption: never contributes;
- actual `investment_cash_flows`: remain separate and do not become expected rows.

A future formula that substitutes announced dividends for some historical-average months requires a separate explicit financial-contract change/version and is outside R05-00.


<a id="c9-0011-automatic-investment-payout-calendar-18-failure-model"></a>
#### Failure model

Provider failures reuse the sanitized 0.4 philosophy.

At minimum distinguish:

- `token_unavailable` / auth failure;
- provider network/timeout/5xx;
- malformed response;
- unsupported event/instrument/currency;
- unmapped/excluded instrument;
- provider data unavailable;
- `preview_changed` on apply.

Mixed-success preview is allowed: one instrument's failure does not discard valid rows from other instruments.

For apply, selected rows are one transaction. A failure in any selected row rolls back the selected set.

Manual expected-flow entry remains available in editable months regardless of provider/token/network state.

Retry is a new explicit owner action only.


<a id="c9-0011-automatic-investment-payout-calendar-18-migration-and-backward-compatibility"></a>
#### Migration and backward compatibility

0.5 migration MUST be additive/fail-safe.

- Existing `expected_cash_flows` rows remain unchanged and retain current CRUD, unique constraints, `forecast_version`, `source_as_of_date` and semantics.
- Do not backfill existing manual rows into provider identities.
- Do not fetch T-Invest during Alembic upgrade.
- Prefer new provider-payout/revision/reconciliation tables rather than overloading the existing manual-row uniqueness contract.
- Existing calendar/C04 readers may be refactored behind a merged read model, but their accepted financial semantics remain covered by regression tests.
- Existing expected dividends remain ignored by C04 v1.
- Month clone MUST NOT silently copy applied provider payout provenance as if it were newly accepted for the new month. New month's payout state is derived by a new owner-triggered preview/apply against its copied positions.

<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30"></a>
### Alfa current snapshot transport and safe reconciliation

<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-decision"></a>
#### Decision


<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-1-introduce-a-dedicated-brokersnapshotprovider-boundary"></a>
#### 1. Introduce a dedicated `BrokerSnapshotProvider` boundary

0.6 defines a provider-neutral read-only boundary for **current broker state**.

Conceptually:

```text
BrokerSnapshotProvider
    fetch_snapshot()
        -> BrokerSnapshot

BrokerSnapshot
    provider
    source_as_of
    accounts[]
    positions[]
    cash_balances[]
    warnings[]
    provenance
```

The exact Python DTO names may vary in R06-03, but the semantics are normative:

- a snapshot is an observation of current provider state at a known `source_as_of` time;
- it is not a reporting month by itself;
- it is not an authoritative historical transaction ledger;
- it performs no writes to Hermes persistence;
- it performs no reconciliation or apply by itself.

`MarketDataProvider`, `BrokerSnapshotProvider`, and future `BrokerStatementImporter` remain separate bounded contexts.


<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-2-alfa-pro-authentication-is-bus-gated-and-fail-closed"></a>
#### 2. Alfa PRO authentication is bus-gated and fail-closed

The Alfa adapter must establish the session in this order:

1. connect only to the approved loopback router;
2. `listen` to `#ConnectionState.Bus`;
3. wait within a bounded overall deadline, treating a per-receive timeout as idle rather than successful completion;
4. observe `AuthStatus` from the bus;
5. issue client-data reads only after an actually observed `AuthStatus == 2`;
6. if status is missing, changes away from `2`, the socket fails, or the deadline expires, stop and return a non-applicable failure/unavailable result.

The adapter must **not** use ConnectionState `#Data.Query` as the production auth gate on the current compatibility contract. It must not translate undocumented error code `6` into an authentication state.

If authentication becomes non-`2` while a snapshot is being collected, the collection is not eligible for apply. A partial snapshot may be surfaced diagnostically only if it remains sanitized and clearly marked non-applicable.


<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-3-read-only-safety-is-structural-not-credential-scoped"></a>
#### 3. Read-only safety is structural, not credential-scoped

No separate provider-level read-only credential/scope has been established for the observed PRO integration. The same authenticated terminal can be ready to sign trading instructions. Therefore Hermes read-only safety must exist **by construction**.

The production Alfa snapshot adapter must have:

- no public generic `send(channel, payload)` interface;
- a closed allowlist of router commands and channels;
- `request` only to `#Data.Query`;
- `listen` / `unlisten` only for explicitly approved data buses;
- a hard runtime rejection for every `#Order.*` channel before any send;
- no order, limit, cancel, transfer, signing, certificate-management or mutation DTO/service/helper;
- source-level and deterministic tests that keep the trading surface absent;
- sanitized errors that never dump provider frames or payloads.

`ReadyToSign` is observation-only. Hermes must never try to change it, create/sign certificates, or make snapshot reads contingent on manipulating signing state.


<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-4-minimize-the-production-snapshot-entity-surface"></a>
#### 4. Minimize the production snapshot entity surface

R06-01 used a wider evidence surface. The production snapshot provider is narrower.

Approved snapshot entities are limited to the data required for current state:

- `ClientAccountEntity`;
- `ClientSubAccountEntity`;
- `SubAccountRazdelEntity`;
- `ClientPositionEntity`;
- `ClientBalanceEntity`;
- `AssetInfoEntity`, bounded to the provider object IDs needed by observed positions where possible.

`ClientOperationEntity` is **not part of the production snapshot contract** and must not be queried by default in R06-03. Its R06-01 use was evidence gathering only.

Order entities, order book, trade tape, archive/candles, trading limits, order services and all other non-allowlisted surfaces are outside this adapter.

Each live fetch is one-shot, bounded and owner-initiated. It must unlisten/close after collection and must not maintain or renew long-lived subscriptions in the background.


<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-5-snapshot-financial-values-are-observations-with-explicit-semantics"></a>
#### 5. Snapshot financial values are observations with explicit semantics

The provider-neutral snapshot may expose, when available:

- position quantity;
- provider/broker unit price or valuation input;
- provider-reported market value;
- accounting/average-cost-related unit price;
- accrued interest / NKD;
- unrealized result;
- cash balance by account/subaccount/currency;
- provider field/source metadata required to explain provenance.

R06-03 must document and test the exact Alfa raw-field mapping before a field is promoted into one of these normalized semantics. A field name alone is not sufficient evidence of meaning.

Provider-reported market value and a Hermes-derived value must not silently replace one another. Reconciliation may compare them, but provenance must preserve which value came from the broker and which was calculated by Hermes.

Alfa values observed as JSON numbers must cross the provider boundary into exact domain representations without binary floating-point financial arithmetic. Financial amounts/prices/rates use `Decimal` or exact minor-unit representations according to existing Hermes rules; quantities also use a decimal-safe representation where the provider permits non-integer values. R06-03 must not build financial domain values from a binary `float` round-trip.


<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-6-hermes-identity-remains-canonical-alfa-identity-is-a-provider-projection"></a>
#### 6. Hermes identity remains canonical; Alfa identity is a provider projection

A provider identifier is useful correlation metadata, not Hermes canonical identity.

For instruments:

- Hermes local `instrument_id` remains canonical inside the product;
- ISIN is the preferred cross-provider external identity when present;
- Alfa `IdObject` and related provider IDs may be retained as Alfa provenance/mapping metadata only under the persistence gate below;
- ticker/name are discovery/display hints and must not create a silent mapping;
- the observed `29/29` ISIN coverage is positive evidence for this strategy, not a permanent provider guarantee.

For accounts:

- Alfa account/subaccount/section IDs are provider identities;
- mapping to Hermes `accounts` is explicit owner-controlled mapping;
- one clean-restart stability observation is useful evidence but not a promise of stability across terminal upgrades, reinstallations, broker migrations or provider data resets;
- missing/changed provider identity must produce a reconciliation conflict, not silently remap an account.


<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-7-iis-classification-remains-owner-controlled-until-semantics-are-accepted"></a>
#### 7. IIS classification remains owner-controlled until semantics are accepted

R06-01 observed an `IIAType` field in live `ClientAccountEntity` field names, but Alfa PRO API v2.1 does not document that field or its values. Therefore its semantic meaning is `UNRESOLVED`.

Hermes must not infer IIS from:

- `IIAType` until an official accepted mapping exists;
- account numbers/codes;
- names or text substrings;
- section names/codes.

The existing Hermes account type / IIS profile remains the source of truth through explicit owner mapping. A later narrow ADR/task may accept an official provider mapping if evidence becomes available.


<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-8-reconciliation-preview-is-mandatory-before-persistenceapply"></a>
#### 8. Reconciliation preview is mandatory before persistence/apply

The flow is:

```text
Alfa PRO
  -> AlfaProBrokerSnapshotProvider
  -> immutable in-memory BrokerSnapshot
  -> reconciliation preview
  -> owner selects/accepts changes
  -> selective apply
```

There is no direct provider-to-database write path.

Preview must surface at least:

- matched/unmatched accounts;
- matched/unmatched instruments;
- provider-only and Hermes-only positions;
- quantity differences;
- cash differences;
- provider valuation/accounting-price/NKD/unrealized differences where supported;
- source timestamp and provider provenance;
- incomplete/error/truncation state.

No missing provider row may silently delete a Hermes position. No provider-only row may silently create or map an instrument/account.

Any future apply is explicit, selective and transactional. A CLOSED reporting month cannot be changed by broker sync; the owner must explicitly reopen it first under the existing month lifecycle rules.


<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-9-current-snapshot-and-historical-broker-ledger-are-deliberately-separated"></a>
#### 9. Current snapshot and historical broker ledger are deliberately separated

`ClientOperationEntity` must not be treated as the source of truth for payouts, taxes, commissions, deposits, withdrawals or complete historical activity.

Reasons:

- the official v2.1 entity is described as operations/trades;
- the live bounded initial load was only three rows over two dates;
- no accepted date-filter/pagination/retention contract has been established;
- live numeric operation type IDs `3` and `14` have no accepted official mapping in this ADR;
- the same short observed operation set surviving one restart proves only restart persistence of that observed set, not historical completeness.

Historical cash activity therefore belongs to a separate future `BrokerStatementImporter` based on broker reports/statements or another later accepted authoritative contract.

R06-03 must not write `ClientOperationEntity` rows into `investment_cash_flows`.


<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-10-browserfrontend-must-never-proxy-the-alfa-router"></a>
#### 10. Browser/frontend must never proxy the Alfa router

The foreign-Origin handshake acceptance from R06-01 is a threat-model fact, not by itself a vulnerability finding.

Consequences for Hermes are normative:

- Alfa WebSocket communication occurs only in backend/server-side code;
- the frontend never receives a raw Alfa WebSocket URL, generic channel proxy, raw provider frame or provider credential/session primitive;
- a future UI may expose only a high-level explicit owner action such as “read broker snapshot” and a sanitized reconciliation result;
- localhost request-security protections remain governed by ADR 0004;
- broker sync must not create a browser-accessible generic tunnel to local trading services.


<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-11-persistence-is-gated-and-minimized"></a>
#### 11. Persistence is gated and minimized

Raw Alfa frames/payloads are never persisted as a normal product feature and are never logged.

The legal/terms basis for persistent storage of Alfa private API-derived broker data remains `NEEDS_CONFIRMATION`. Until that gate is explicitly resolved:

- R06-03 may implement transient read-only acquisition and normalized in-memory DTOs;
- R06-04 may implement in-memory reconciliation/preview;
- persistence of provider IDs/mappings or selected Alfa-derived snapshot values must not silently become accepted merely because the technical adapter works;
- R06-05 selective apply is blocked from release acceptance if the required persistence permission remains unresolved.

If persistence becomes accepted, store only the minimum normalized/provenance fields required for owner mapping, reconciliation and audit. Do not store raw provider payloads “for debugging”.


<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-12-compatibility-failures-are-explicit-no-speculative-protocol-fallback"></a>
#### 12. Compatibility failures are explicit; no speculative protocol fallback

The PRO terminal updates automatically and API documentation may lag observed terminal behavior. Therefore compatibility failures must fail safely.

The adapter must not respond to undocumented errors by trying arbitrary request shapes/channels. New compatibility behavior requires:

- official documentation/example evidence or a deliberately bounded owner-only probe;
- synthetic tests;
- independent review when the network/security boundary changes.

Observed code `6` remains an opaque provider SubscribeResponse code in this architecture.


<a id="c9-0013-broker-snapshot-and-alfa-pro-security-30-provider-neutral-status-expectations"></a>
#### Provider-neutral status expectations

R06-03 may choose exact class/enum names, but callers must be able to distinguish at least:

- successful complete snapshot;
- provider unavailable / terminal not running;
- authentication unresolved or not authorized;
- compatibility/protocol error;
- partial/incomplete snapshot;
- malformed provider response.

A partial/incomplete snapshot is not eligible for selective apply unless a later contract explicitly defines safe field-level applicability. Required snapshot entity errors, truncation or loss of authenticated state fail closed.

<a id="c9-0015-alfa-pro-compatibility-diagnostics-19"></a>
### Typed compatibility failures and no fallback

<a id="c9-0015-alfa-pro-compatibility-diagnostics-19-decision"></a>
#### Decision

The transient `BrokerSnapshot` contains an `AlfaDiagnosticReport` with two
versioned contracts:

- `alfa-pro-diagnostics/v1` is the owner-facing report contract.
- `alfa-pro-fingerprint/v1` is the deterministic SHA-256 fingerprint contract.

The fingerprint covers only the documented API version, bounded allowlisted
version hints, observed router message shapes, entity payload field names,
entity row field names, and capability labels. It does not cover row keys or
any field values. Version hints are read only from bounded allowlisted fields;
an absent or invalid hint remains `unresolved`.

The current accepted contract does not prove that an Alfa API version hint or a
router/protocol version hint uses the API-documentation version namespace. The
adapter therefore records both as observational evidence and does not compare
either value to `api_doc_version`. An observed value that differs from `2.1`
does not by itself mean `unsupported`; compatibility is decided by the
confirmed structural protocol and layout guards below. A future `unsupported`
classification requires a separately accepted supported-protocol/version
contract or mapping.

Compatibility has three explicit states:

- `compatible`: the expected bus/query shapes and required current-state layout
  were observed, with no material protocol or layout anomaly.
- `unknown`: the observation is incomplete or a protocol/layout anomaly was
  seen; the adapter cannot prove safe compatibility.
- `unsupported`: a separately accepted API/protocol version contract explicitly
  marks the observed version outside the adapter contract. No such version
  mapping is assumed by this v1 implementation.

Diagnostics classify the first actionable boundary as `connection`, `auth`,
`routing`, `protocol`, `layout`, or `mapping`. Failure codes are bounded,
developer-readable labels; raw provider error text is not copied into the
artifact.


<a id="c9-0015-alfa-pro-compatibility-diagnostics-19-safety-and-apply-rules"></a>
#### Safety and apply rules

The existing lifecycle remains authoritative: explicit refresh, preview,
owner mapping, explicit prepare/select decisions, and persisted staleness
fingerprints. `BrokerSnapshot.status` becomes `compatibility_error` when the
required read completes but compatibility is `unknown` or `unsupported`, and
`eligible_for_apply` remains false. The API does not refresh in the background,
does not broaden the channel allowlist, and does not bypass mapping or
staleness checks.

The preview response exposes both structured `diagnostics` and a text
`diagnostic_report`. The Alfa PRO panel displays the report behind an explicit
details disclosure and provides an owner-triggered copy action. The text form
repeats the safety assertions so it can be transferred without accompanying
application logs.

<a id="c9-2026-08-20-r06-03-alfa-pro-field-mapping-10"></a>
### Complete accepted Alfa v2.1 field and unit table

The production adapter does not query historical operation entities.


<a id="c9-2026-08-20-r06-03-alfa-pro-field-mapping-10-accepted-mappings"></a>
#### Accepted mappings

| Alfa entity | Alfa field | Official wording | Snapshot field | Units |
|---|---|---|---|---|
| ClientAccountEntity | IdAccount | Идентификатор счёта | provider_account_id | opaque id |
| ClientSubAccountEntity | IdSubAccount | Идентификатор субсчёта | provider_subaccount_id | opaque id |
| ClientSubAccountEntity | IdAccount | Счёт клиента | provider_account_id | opaque id |
| SubAccountRazdelEntity | IdRazdel | Идентификатор портфеля | provider_section_id | opaque id |
| SubAccountRazdelEntity | IdAccount | Счёт клиента | provider_account_id | opaque id |
| SubAccountRazdelEntity | IdSubAccount | Субсчёт клиента | provider_subaccount_id | opaque id |
| SubAccountRazdelEntity | IdRazdelGroup | Группа портфелей 1–4 | section_group | official int |
| SubAccountRazdelEntity | RCode | Код раздела | section_code | string |
| ClientPositionEntity | IdAccount / IdSubAccount / IdRazdel / IdObject | Счёт / Субсчёт / Портфель / Выпуск | provider_* ids | opaque id |
| ClientPositionEntity | TorgPos | Текущая позиция | quantity | Decimal quantity |
| ClientPositionEntity | Price | Текущая цена | broker_unit_price | provider price number |
| ClientPositionEntity | UchPrice | Учётная цена | accounting_price | provider price number |
| ClientPositionEntity | NKD | НКД (накопленный купонный доход) | accrued_interest_nkd | provider money number |
| ClientPositionEntity | NPLtoMarketCurPrice | Номинальная прибыль/убыток (НПУ) | unrealized_result | provider money number |
| ClientPositionEntity | IsMoney | Деньги — валютная позиция | is_money | bool |
| ClientBalanceEntity | Money | Рубли | amount + currency RUB | RUB cash |
| ClientBalanceEntity | IdAccount / IdSubAccount / IdRazdelGroup | Счёт / Субсчёт / Группа портфелей | provider refs | ids / group int |
| AssetInfoEntity | ISIN / Ticker / Name / IdObject | Международный идентификатор / тикер / наименование / выпуск | isin, ticker, display_name, provider_instrument_id | reconciliation metadata |

JSON financial numbers are decoded with `parse_float=Decimal` at the payload boundary. Binary `float` is rejected, not recovered via `Decimal(str(float))`.

`source_as_of` is a timezone-aware **local observation time**. The official current-state entities do not document an authoritative snapshot timestamp.


<a id="c9-2026-08-20-r06-03-alfa-pro-field-mapping-10-unresolved--kept-none--ignored"></a>
#### Unresolved — kept None / ignored

| Alfa field | Official wording | Why not mapped |
|---|---|---|
| ClientAccountEntity extras (including undocumented live account-kind fields) | not in v2.1 schema (schema lists only IdAccount) | IIS remains owner-controlled; no inference from name/code/substring |
| ClientPositionEntity.PSTNKD | НКД | insufficient to distinguish from documented NKD |
| ClientPositionEntity.DailyPL | Текущая прибыль/убыток (ПУдн) | daily P/L is not the unrealized-result mapping |
| ClientBalanceEntity.PortfolioCost | Стоимость портфеля | portfolio-level; not a position market value |
| position market_value | (none) | no official position market-value field |

Hermes must not compute a silent `TorgPos * Price` stand-in for provider market value.


<a id="c9-2026-08-20-r06-03-alfa-pro-field-mapping-10-explicitly-out-of-this-adapter"></a>
#### Explicitly out of this adapter

- Historical operation entities and their type codes
- `#Order.*`, limits, archive, order book, trade tape
- Persistence, reconciliation, apply, API/UI

<a id="c10"></a>
## 10. Export formats, schema versions and compatibility

Machine schemas and their synthetic/example packages live together in `docs/schemas/`: `ai_analysis_bundle.schema.json`, `ai_financial_review.schema.json`, `portfolio_review_package.schema.json` and their fixtures; `legacy_month_mapping.schema.json`/example and `private_seed.schema.json`/example remain public supported formats. Co-location preserves relative schema references; schema identifiers, bytes and format versions are unchanged by the directory move. Format versions are independent of application version. AI analysis bundle format is 1.4.0. Integers/Decimal strings, units, nullable values, coverage and compatibility remain explicit. `portfolio_review_package.assistant-evaluation.json` is a synthetic expected-answer contract, not model accounting.

Legacy mapping imports require their declared schema and explicit field mappings; unsupported columns/identity never silently become financial facts. Private seed is an explicit local bootstrap input outside Git with real payloads excluded from CI; the retained public example is synthetic. Preserve historical receipt formats and reject unsupported versions rather than reinterpreting them. The detailed consumer contracts follow.

<a id="c10-ai_analysis_bundle-1"></a>
### AI analysis bundle 1.4.0 human contract

**Schema name:** `hermes.finance.ai_analysis_bundle`

**Current schema version:** `1.4.0`

**Normative schema:** [`ai_analysis_bundle.schema.json`](schemas/ai_analysis_bundle.schema.json)

**Synthetic example:** [`ai_analysis_bundle.synthetic.json`](schemas/ai_analysis_bundle.synthetic.json)

**Recommended #331 handoff:** [`AI_FINANCIAL_REVIEW.md`](#c10-ai_financial_review-1)

**R08 portfolio-review package:** [`PORTFOLIO_REVIEW_PACKAGE.md`](#c10-portfolio_review_package-1)

The R08 package is the profiled owner-review output envelope built from this
bundle contract. It adds explicit scope, section states, allocation and
freshness coverage without changing the financial meanings or creating a second
calculation model. Its package version and its declared
`metadata.source_contract_version` each advance with the schema revision they
project, so the two never silently disagree.

For ordinary monthly AI analysis, #331 defines one higher-level recommended
report. This bundle remains a compact semantic/source contract and stays
available as a technical export; it is not silently version-bumped or replaced
by the #331 report.


<a id="c10-ai_analysis_bundle-1-purpose-and-boundary"></a>
#### Purpose and boundary

The AI Analysis Bundle is a deterministic, read-only export of the financial picture already
defined by Hermes Finance. It is intended for an explicit owner download and later, separate
submission to an AI assistant. Hermes does not send the bundle anywhere, call an LLM or cloud
API, persist an AI interpretation, or change financial data while generating it.

This contract does not introduce a financial model. A future exporter must call the existing
backend services and map their results. It must not reproduce formulas in an export service,
router, frontend component, or prompt. R07-01 defines only this contract, its synthetic fixture,
and validation; it does not define an endpoint, UI, or file-generation workflow.


<a id="c10-ai_analysis_bundle-1-representation-rules"></a>
#### Representation rules

- Money is a decimal string in major RUB units, always with two fractional digits. JSON numbers
  are not used for money, rates, percentages, prices, or quantities.
- Every analytically optional metric carries `availability`, `precision`, `source`, and
  `reason_codes`. An unavailable value is `null`, has `precision=unknown`, and explains why.
- Actual and forecast breakdown components use the same metric shape as their totals. A missing
  component is unavailable; an exporter must not invent zero or retain a stale numeric placeholder.
- Missing calendar months are unknown history. They are listed in
  `coverage.missing_calendar_periods` and are never synthesized as zero-valued months.
- A reporting month without any persisted capital/debt snapshot exposes capital metrics as
  unavailable with `portfolio_snapshot_missing`; a persisted zero row remains an exact zero.
- A configured `passive_income_history_start_month` makes earlier passive-income metrics
  unavailable with `passive_income_history_before_configured_start`. Export never infers this
  boundary from first non-zero data, positions, timestamps, or notes.
- A draft month may be exported, but its values carry `draft_value` and the point has partial
  coverage. Draft months never enter eligible CLOSED-month historical averages.
- Export-local refs (`acct-*`, `inst-*`, `goal-*`, `flow-*`) exist only to join objects inside one
  bundle. They are deterministically assigned by the exporter and are not database IDs, provider
  IDs, account numbers, or credentials.
- Arrays have stable ordering. Reporting periods and rolling-average periods are ascending by
  `(year, month)`; accounts, instruments, and goals by export ref; positions by
  `(account_ref, instrument_ref)`; upcoming flows by `(expected_date, event_ref)`; warnings by
  `(severity, code, scope)`. The same persisted state, generation inputs, and `generated_at`
  produce byte-equivalent logical content after canonical JSON serialization.
- `generated_at` is an explicit generation input, not a financial observation. Financial
  freshness is expressed by snapshot, price, source-as-of, or event dates where Hermes really
  has them. The contract does not invent freshness timestamps.


<a id="c10-ai_analysis_bundle-1-normative-semantic-sources"></a>
#### Normative semantic sources

| Bundle area | Authoritative Hermes source | Required interpretation |
|---|---|---|
| Reporting period and status | `ReportingMonth` and reporting-month lifecycle | `closed` is immutable history; `draft` remains provisional. |
| Liquid assets and net capital | `liquid_capital_for_month` and `asset_allocation_for_month` / ADR 0007 | `liquid_assets_total - included_debts = liquid_capital_net`; real estate and mortgage are outside liquid capital. |
| Actual passive income | `passive_income_for_month` | Deposit actual interest + coupon net + dividend net + other capital income net. Cashback, active income, deposits, withdrawals, redemption, and price growth are excluded. Persisted net amounts are not taxed or commissioned twice. |
| Rolling actual average | `passive_income_average` / ADR 0008 | Last at most 12 eligible CLOSED records on/after the configured history boundary. Missing or draft months do not enter the denominator. |
| Passive-income forecast | `forecast_passive_income` | Expected interest/coupons/other plus the actual CLOSED-month dividend component. Expected dividends are not added again. Redemption remains principal and is excluded. Persisted deposit monthly estimates are annualized by the current approximate method and labelled accordingly. |
| Main passive-income goal | persisted `goals` plus `build_goal_achievement_summary` | Current value is the rolling actual average after R02-27, not the C04 forecast. A below-target future date remains `not_projectable` when no trajectory exists. |
| Monthly cash context | `cash_balance_for_month`, `actual_net_for_month`, expense and saving services | `cash_flow_after_allocations` is the derived surplus. `monthly_cash_balance` remains a backward-compatible alias and is never physical cash. Persisted cash is only `current_portfolio.cash_balances`. |
| Market value change / return | no accepted aggregate service currently exists | Both fields stay unavailable in v1. A consumer may inspect point-in-time valuations, but must not relabel liquid-capital delta as market value change or market value change as investment return. |
| Current portfolio | the selected reporting month's persisted accounts, instruments, position/deposit snapshots, and cash balances | Portfolio completeness and `valuation_freshness` are independent. `oldest_price_date`, `latest_price_date`, stale count/share, and `stale_valuation` expose old prices without dropping the persisted position. A missing snapshot on an active capital-included account is `active_account_snapshot_missing`: the account stays in the catalog and in missing-account metadata, its snapshot value is absent from the known liquid-capital subtotal, that subtotal stays `available`/`exact`, and history-point plus capital-domain coverage are `partial`. `CashBalance.account_id = NULL` is synthetic/unassigned cash (#497) and does not satisfy any real account. See [`financial-completeness-contract.md`](#c2-financial-completeness-contract-8). |
| Debt and property | debt, property, liquid-capital, and mortgage services | Included short-term debt affects liquid capital; mortgage/property remain reference context. Property equity is separate. |
| IIS | `iis_result` plus persisted IIS profile, contributions, and benefit states | `iis_coverage` distinguishes no active IIS (`iis_account_absent`) from an active IIS with unconfigured (`iis_tax_data_unconfigured`) or partial (`iis_tax_data_partial`) tax data. Only received tax benefits increase the result with benefit. Every known active IIS account appears in `iis_accounts`: when the account has no profile, `iis_type`/`opened_at`/`eligible_close_at` are `null`, persisted contributions/benefits are still exported, and both portfolio-result metrics are `unavailable` with `iis_tax_data_unconfigured` instead of being omitted or guessed. |
| Salary tax | `calculate_salary_tax` and salary-tax opening context | YTD/bracket values appear only if backend calculation succeeds with complete known history. `salary_tax_history_incomplete` is an unavailable state, never an assumed zero. `salary_tax_context.selected_month` always carries the selected reporting month's reconciliation (see the salary-consistency row). |
| Salary consistency | persisted salary gross/net plus the read-only salary-tax calculation | `reporting_history[].kpis.salary` retains `gross`, `calculated_tax`, `calculated_net`, and `actual_net` as separate facts. `salary_net_mismatch` is a warning when `gross - calculated_tax != actual_net`. The same mapping is exposed for the selected month as `salary_tax_context.selected_month`: authoritative persisted `gross`/`actual_net`, derived `calculated_tax`/`calculated_net` that become `unavailable` when the tax history is incomplete, and `consistency` of `consistent`/`mismatch`/`unavailable`. It is read from the same builder as the KPI block; export code computes no tax itself. |
| Property quality | structured `PropertySnapshot` rows | Each row remains authoritative and notes are excluded and never parsed as a competing balance. When `property_equity_suspicious_jump` or `duplicate_property_snapshot` affects a reporting month, the affected aggregate property value, mortgage, equity, payment and coverage metrics are unavailable with those reason codes; raw rows remain available in the canonical report. No deterministic dedupe is attempted without authoritative identity. |
| Upcoming cash flows | `merged_payout_calendar` / ADR 0011 | Manual/provider reconciliation decides which row counts. Provider totals with unknown personal tax remain provider-announced approximate amounts, never labelled net. An unresolved duplicate uses the existing safe manual-only behavior. Calendar total, non-principal calendar amount total, and principal total are separate. |
| Provenance | persisted manual/provider/statement provenance already accepted by Hermes | `manual`, `t_invest`, `alfa_pro`, and `alfa_statement` are reported only where meaningful. Raw protocol payloads and provider correlation IDs are excluded. |
| Deterministic insights | `build_deterministic_insights` (close readiness, freshness, payouts, risk, tax) | Optional `deterministic_insights` carries the sanitized allowlist (`code`, `type`, `severity`, `message`, `source`, `as_of`, `provenance`, `reason`). The open `evidence` map remains on the dedicated `GET /deterministic-insights` endpoint and never enters the bundle. The section is evaluated for the bundle's selected `reporting_period` at `generated_at` (`evaluated_on`), preserving the engine's deterministic `(severity, code, source, reason)` order. |

The historical `actual_history_metric_path` is a path, not a duplicate series. A consumer reads
actual passive-income history from `reporting_history[].kpis.passive_income_actual`. This prevents
the same actual totals from being summed once from reporting history and again from a second copy.


<a id="c10-ai_analysis_bundle-1-counting-rules-for-upcoming-flows"></a>
#### Counting rules for upcoming flows

`upcoming_cash_flows.items` is the owner-visible merged calendar. Three fields make the two
different totals unambiguous:

- `included_in_calendar_total` says whether the row is present in the merged cash calendar;
- `included_in_passive_income_forecast` says whether the row feeds the current forecast formula;
- `forecast_treatment` explains `included`, `represented_by_historical_component`, or
  `excluded_principal`.

The neutral `amount` field is interpreted only together with `amount_semantics` and
`personal_tax_status`:

- `owner_expected_net` means the owner-entered expected tax is known/accounted in the amount;
- `owner_expected_amount_tax_unknown` remains approximate and carries
  `personal_tax_unknown`;
- `provider_announced_amount_tax_unknown` is the provider-announced total, not a promise of
  personal net income; it is always approximate and carries `personal_tax_unknown`;
- `principal` applies to redemption and has tax status `not_applicable` for passive-income
  classification.

Therefore:

- coupon, interest, and other expected capital income may be included in the forecast;
- expected dividends remain useful calendar events but use
  `represented_by_historical_component` because the forecast already annualizes actual dividend
  history;
- redemption uses `excluded_principal` and never increases passive income;
- `calendar_total = non_principal_calendar_amount_total + principal_total`;
- duplicate resolution is explicit and never permits a provider/manual pair to count twice by
  accident.

The JSON Schema validates shape and states. Targeted tests additionally validate monetary
reconciliation and the counting rules because JSON Schema is not an arithmetic engine.


<a id="c10-ai_analysis_bundle-1-coverage-approximation-and-warnings"></a>
#### Coverage, approximation, and warnings

Coverage is reported twice on purpose:

- `coverage.domains` summarizes whether each analytical domain is complete, partial, or
  unavailable across the bundle;
- a section or metric reports its local availability and reason codes.

`precision=exact` means the value is an exact representation of its authoritative persisted or
backend-derived source. It does not claim the underlying manual estimate is objectively current.
It also does not claim portfolio-source coverage is complete: a known liquid-capital subtotal may
be `available` and `exact` while `active_account_snapshot_missing` makes coverage `partial`.
The canonical reading, including the closed two-account case, is
[`financial-completeness-contract.md`](#c2-financial-completeness-contract-8).
Approximate forecast methods use `precision=approximate` and a warning code. `unknown` is reserved
for unavailable values.

Warnings contain a stable machine code, severity, scope, and concise owner-safe explanation.
They must not contain stack traces, SQL, filesystem paths, private payload fragments, credentials,
or debug dumps.

The #285 data-quality codes are intentionally additive: `portfolio_snapshot_missing` and
`active_account_snapshot_missing` mean persisted capital evidence is absent; `stale_valuation`
means the position remains present but its price date is older than the reporting snapshot;
`salary_net_mismatch` means actual employer-paid net differs from the derived calculation;
`iis_account_absent`, `iis_tax_data_unconfigured`, and `iis_tax_data_partial` describe distinct
IIS coverage states; and property warning codes request review without changing structured facts.
Warnings are deduplicated by code, while `scope` and `message` remain explanatory fields.


<a id="c10-ai_analysis_bundle-1-current-portfolio-selection"></a>
#### Current portfolio selection

The exporter records both the selected `reporting_period` and `selection_reason`. The preferred
R07-02 behavior is `latest_closed`, because it provides a stable current analytical snapshot while
still retaining later draft months in `reporting_history`. If no closed month exists, an exporter
may select `latest_available`, must preserve its `draft` status, and must mark coverage partial.
No later price, quantity, or balance may be backfilled into an earlier reporting snapshot.


<a id="c10-ai_analysis_bundle-1-versioning-and-compatibility"></a>
#### Versioning and compatibility

`schema_version` follows SemVer:

- patch: clarification or validation correction that does not change valid instance meaning;
- minor: backward-compatible optional fields, optional sections, or additive enum values;
- major: removal/rename, changed requiredness, changed units, changed counting/source semantics,
  or another change that can alter an existing consumer's interpretation.

`1.4.0` records the #498 completeness metadata for each history point. When a
required active capital account lacks a snapshot, its known liquid-capital subtotals
remain `available` / `exact`, while the point and capital domain become `partial`
with `active_account_snapshot_missing`. A month without capital evidence remains
`unavailable` / `null` with `portfolio_snapshot_missing`.

`1.3.0` adds the IIS-account presence semantics for partially configured
profiles and the directly analyzable `salary_tax_context.selected_month`
reconciliation while retaining all v1.2 fields. `1.2.0` adds the optional
`deterministic_insights` section (sanitized engine insights without the open `evidence` map) while retaining all v1.1 financial fields.
`1.1.0` adds data-quality fields while retaining all v1.0 financial fields, including the
deprecated `monthly_cash_balance` alias. New consumers should use `cash_flow_after_allocations`.
Consumers must dispatch on the major version. A consumer supporting major `1` must ignore unknown
optional fields after validating the instance with the schema declared by that instance. The
checked-in `1.0.0` schema is intentionally strict (`additionalProperties=false`) to detect exporter
leaks and typos; a later minor version publishes its matching strict schema rather than weakening
the old schema. New required fields or new financial meanings require major `2`.

`metadata.calculation_versions` is also an allowlisted object. v1.2 accepts
`monthly_summary`, `passive_income_forecast`, `goal_achievement`, and `deterministic_insights`; it is not an extension map
for arbitrary runtime metadata.

Fields are required when their semantic state must always be known. Potentially absent financial
values are not omitted: they use the explicit unavailable shape. An optional application version
is represented as `null` when it cannot be obtained safely.

No schema registry or remote lookup is required. The exported file identifies the version, and
Hermes ships the matching schema with the application.


<a id="c10-ai_analysis_bundle-1-privacy-and-intentional-exclusions"></a>
#### Privacy and intentional exclusions

The bundle is intentionally rich in user-approved financial information, but it excludes
technical and low-value identifiers. A future exporter must use an allowlist mapping and must not
serialize ORM objects, provider DTOs, request objects, or debug structures wholesale.

Excluded fields and data include:

- API tokens, secrets, passwords, cookies, credentials, certificates, and session primitives;
- `.env` values, database/backup/export paths, filesystem paths, hostnames, and local router URLs;
- raw Alfa/T-Invest/statement protocol payloads, frames, uploaded documents, hashes, stack traces,
  SQL, and debugging payloads;
- database primary keys, reporting-month IDs, raw account numbers/external codes, provider account
  or subaccount IDs, provider instrument UIDs/identity keys, reconciliation row IDs, and import
  session IDs;
- notes/comments and free-form provider text by default; a later explicitly reviewed contract may
  add a bounded owner-selected narrative field;
- unrealized market value change relabelled as return, inferred IIS classification, guessed tax
  brackets/YTD, fabricated freshness, or inferred missing-month zeroes.

Application and formula version strings are allowed because they help interpretation and do not
expose local infrastructure. Instrument ISIN/ticker and human-readable account/instrument names
are allowed because they materially improve analysis of an explicitly exported financial file.


<a id="c10-ai_analysis_bundle-1-consumer-implementation-constraints"></a>
#### Consumer implementation constraints

Issue #129 may implement assembly/export on top of this contract, subject to independent review.
It must:

1. remain a read-only query path with no cloud or LLM call;
2. map only allowlisted fields into dedicated DTOs;
3. reuse the authoritative services in the table above;
4. assign deterministic export-local refs and stable ordering;
5. validate the generated instance against the declared schema before offering it for download;
6. add integration tests proving no persistence writes and no technical-secret fields;
7. keep UI/download behavior, filename, and explicit owner action in #129 scope rather than
   retrofitting them into R07-01.

<a id="c10-ai_financial_review-1"></a>
### Financial review composition and consumer constraints

**Status:** implemented and shipped. The read-only backend assembler and export
endpoints (`GET /api/export/ai-financial-review` and
`GET /api/export/ai-financial-review/json`) exist on canonical `main` and have
been part of the published application since v1.0.0; the Export page presents
the recommended report and its technical alternatives. This document and its
schema remain the normative contract for the generated report. The
implementation adds no migration, provider call, cloud upload or LLM call, and
later staged UAT work does not change this contract.

**Schema name:** `hermes.finance.ai_financial_review`

**Schema version:** `1.3.0`

**Normative schema:** [`ai_financial_review.schema.json`](schemas/ai_financial_review.schema.json)

**Synthetic fixture:** [`ai_financial_review.synthetic.json`](schemas/ai_financial_review.synthetic.json)


<a id="c10-ai_financial_review-1-1-purpose-and-product-role"></a>
#### 1. Purpose and product role

`hermes.finance.ai_financial_review` is the one canonical, full-scope export
that the owner should choose for a normal monthly review in ChatGPT or another
AI assistant. It is a deterministic, read-only handoff of Hermes facts and
owner-entered context. The JSON file is canonical; a future Markdown download
may be rendered from the same DTO in a later scope and must not have separate
financial semantics. Markdown is not part of the #331 implementation scope.

The existing contracts remain available during the transition:

| Existing export | Role after #331 | Use it when |
| --- | --- | --- |
| `hermes.finance.ai_analysis_bundle` | Compact semantic/source contract | Debugging the AI contract, coverage and reason codes, or inspecting the lowest-level export source. It is not the recommended monthly handoff. |
| `hermes.finance.portfolio_review_package` | Detailed portfolio-review envelope | Diagnosing allocation, concentration, freshness and profile-specific section states. Its full profile is a source for the canonical report. |
| Legacy/raw finance report | Technical compatibility export | Migration, troubleshooting or repository-specific investigation. It is not recommended for ordinary AI analysis. |

The recommended report has no concise/full selector. It is always the
owner-facing full review. Technical package profiles remain independent and do
not change the recommended choice.


<a id="c10-ai_financial_review-1-2-composition-boundary"></a>
#### 2. Composition boundary

The implementation must compose existing authoritative builders/read models and
map them into this contract. It must not calculate a second financial model.

The intended source map is:

| Report section | Authoritative source and mapping rule |
| --- | --- |
| `current_capital`, `historical_dynamics`, `passive_income`, `future_cash_flows`, `current_portfolio`, `goals`, `iis_and_tax` | The full `portfolio_review_package` and its underlying `ai_analysis_bundle`; use the richer `cash_flow_after_allocations`, passive-income breakdown and salary facts from the bundle where the package projection is narrower. |
| `allocation_and_concentration` | Existing `risk_allocation` read model as already adapted by `portfolio_review_package`. Amounts, shares and export-local refs are preserved. When the denominator is a partial known subtotal, support is `partial` with `active_account_snapshot_missing`. |
| `current_portfolio.freshness` | Existing freshness/provenance summary and the bundle's valuation freshness fields. No universal freshness score is introduced. |
| `debts_and_real_estate` | Existing package context plus direct allowlisted debt/property read models for persisted rows and the #336 fields (`annual_rate`, due/end dates, mortgage rate). The report may expose facts that the old package did not project, but must not derive new debt or property semantics. |
| `user_context` | Persisted `monthly_comments` and explicitly owner-entered notes. Text is carried with provenance and is never parsed as a number or used in a calculation. |
| `budget_and_saving` | Persisted `saving_allocations`, actual `expense_entries`, and #336 `planned_budget_lines`. Plan-vs-actual rows use the exact `(period, category, expense_type)` key and are a side-by-side presentation only. |
| `performance` | Existing R08-02 XIRR, R08-03 exact TWRR and PERF04A value-bridge builders over the adjacent closed reporting-month window. The report preserves their availability, quality, coverage, reason codes, exact units, method identity and version metadata; it does not calculate a second return or attribution model. |
| `current_capital.linked_pairs`, `historical_dynamics[].linked_pairs` | Canonical #365 `LinkedPairReadModel` facts for the selected month and each represented month. Current rows use current debt-catalog refs; historical rows use explicitly period-scoped debt identities and do not join the current debt catalog. The adapter exposes gross asset/debt balances and the explanatory net contribution without recalculating them or changing capital totals. |
| `data_quality`, `warnings`, `field_states` | Existing deterministic insights, coverage states and stable warning codes. Open evidence maps, raw diagnostics and provider payloads stay out of the export. |

The adapter uses an allowlist. It must not serialize ORM objects, API request
objects, provider DTOs or debug structures wholesale. Export-local refs such as
`acct-*`, `inst-*`, `debt-*`, `linked-pair-*`, `comment-*` and `expense-*` are
deterministic identifiers inside one file; they are not database IDs, account
numbers or provider identifiers. Account refs remain stable wherever the same
account is represented. In `current_capital.linked_pairs`, `debt_ref` uses the
current-month debt-catalog ref and joins `debts_and_real_estate.data.debts[]`.
In `historical_dynamics[].linked_pairs`, `debt_ref_scope` is
`historical_period` and `debt_ref` is a period-scoped
`debt-history-YYYY-MM-*` identity; it is not a join key to current `debts[]`,
and no old debt snapshot is aliased to the current one. Pair `ref` values remain
stable wherever the same persisted pair is represented in the report.


<a id="c10-ai_financial_review-1-3-top-level-contract"></a>
#### 3. Top-level contract

The normative top-level shape is:

```text
schema_name
schema_version
metadata
scope
coverage
provenance_summary
sections
field_states
warnings
```

`sections` always contains the same named sections. A section has
`status`, sorted `reason_codes`, and `data`:

- `included` means the authoritative source is available;
- `partial` means the source is present but has explicit gaps or approximate
  values;
- `unavailable` means the source cannot provide an authoritative value and
  `data` is `null`.

An empty array inside an `included` section means that the available source has
no persisted rows. It is not a synonym for an unavailable section.

The required sections are:

1. `current_capital` — selected-period liquid assets, included debt, liquid
   capital net, month-local linked asset/debt pairs with current-snapshot debt
   refs, property equity, a separate `cash_flow_after_allocations` KPI,
   and `total_net_worth` only when an authoritative aggregate exists.
2. `historical_dynamics` — ordered month points with capital, month-local
   linked asset/debt pairs using period-scoped historical debt refs, actual passive income and breakdown, active income,
   mandatory expenses, saving allocations, cash flow after allocations,
   property equity and only authoritative return fields. A pair appears only
   when the canonical relation and balance facts exist for that month; history
   is not backfilled or guessed.
3. `current_portfolio` — accounts, instruments, positions, deposits, cash,
   exact ISIN/ticker where stored, acquisition cost/cost basis, selected price,
   price date/source and freshness/provenance.
4. `allocation_and_concentration` — asset-class/account allocation and accepted
   concentration read models, including support states and export-local refs.
5. `passive_income` — actual history path, rolling actual average, current
   breakdown and forecast with its existing assumptions/warnings.
6. `future_cash_flows` — coupons, dividends, interest, redemptions/principal,
   dates, tax semantics, approximation flags and calendar totals.
7. `goals` — target/current/gap/progress/deadline and supportable projection
   state for each goal.
8. `debts_and_real_estate` — debt rows, rates and dates, property snapshots,
   mortgage rate/payment/balance, property equity, coverage and data-quality
   warnings.
9. `iis_and_tax` — IIS type/opening/eligible-close dates, contributions,
   benefits, result semantics and salary-tax coverage. Every known active IIS
   account is listed even when its lifecycle/tax profile is unconfigured: those
   fields are `null`, the persisted contributions/benefits still appear, and the
   portfolio-result metrics stay `unavailable` with
   `iis_tax_data_unconfigured` rather than being guessed. The selected reporting
   month's salary/tax reconciliation is available directly under
   `salary_tax_context.selected_month`.
10. `user_context` — monthly comments plus owner-entered entity notes with
    `source=persisted_user_note`.
11. `budget_and_saving` — saving destinations/amounts/notes, actual expense
    lines, #336 planned budget lines, and side-by-side plan-vs-actual rows.
12. `data_quality` — deterministic insights and the report-level quality
    summary; warnings and unavailable/partial paths are also repeated in the
    canonical top-level `warnings`/`field_states` lists.
13. `performance` — the exact selected-scope Performance v1 window, portfolio
    and supported-account XIRR/TWRR, PERF04A monetary bridge evidence, and an
    explicit separation between external contributions/withdrawals, return
    metrics and value change after external flows.


<a id="c10-ai_financial_review-1-4-financial-and-availability-invariants"></a>
#### 4. Financial and availability invariants

- Money, rates, percentages and quantities use the existing exact string
  representations. No JSON floating-point financial values are introduced.
- `null`/`unavailable`/`unknown` never becomes `0.00`. A persisted explicit zero
  remains an exact zero. This applies to capital, rates, dates, plans, tax data,
  and every metric.
- Missing calendar history is unknown and remains listed in
  `scope.missing_calendar_periods`; it is never synthesized as a zero month.
- A draft month is provisional and never enters the eligible CLOSED-month
  rolling average. Its history point remains marked partial/provisional.
- `liquid_capital_net` excludes real estate and mortgage. `property_equity` is
  a separate reference metric. `cash_flow_after_allocations` is a derived
  monthly surplus and is never labelled as physical cash; persisted cash is
  reported only under the portfolio cash balances.
- An `available`/`exact` `liquid_capital_net` is the known subtotal of persisted
  included rows. When an active capital-included account has no snapshot,
  portfolio-source coverage is `partial` with `active_account_snapshot_missing`.
  That reason travels with the capital metric, the history point, and the
  capital and history coverage domains. A capital goal's current value and
  progress keep the same known subtotal and carry the reason. Allocation and
  top-position concentration keep their existing shares; support becomes
  `partial` with the same reason when the denominator is that subtotal.
  The account stays in the catalog and
  in missing-account metadata; only its snapshot value is absent from the
  subtotal. `CashBalance.account_id = NULL` is synthetic/unassigned cash
  (#497) and does not satisfy any real account. This is independent of
  `total_net_worth_unavailable` and of performance or cash-boundary coverage.
  Payout and redemption concentration are not this denominator.
  See [`financial-completeness-contract.md`](#c2-financial-completeness-contract-8).
- Passive income keeps existing semantics: salary, cashback, contributions,
  withdrawals, redemption principal and unrealized price growth are excluded;
  persisted net amounts are not taxed or commissioned twice.
- Redemption remains principal. A provider-announced amount with unknown
  personal tax remains approximate and is never labelled personal net income.
- `market_value_change` and cash-flow-adjusted `investment_return` are
  unavailable unless an accepted authoritative aggregate exists. Liquid-capital
  movement is not relabelled as return.
- Performance v1 is exposed in its own section. XIRR/TWRR remain percentage
  return metrics; PERF04A remains the monetary `value_change_after_external_flows`
  identity with its contribution/withdrawal summary and evidence. It is not
  component profit attribution, and no export-layer formula is introduced.
- Linked-pair rows are attribution-only facts from the canonical #365 read
  model. Gross asset and linked-debt balances already participate in the
  canonical liquid-capital totals; `net_economic_contribution` is explanatory
  only and no additional capital adjustment is applied. Invalid or missing
  canonical linked-pair facts fail the whole report closed with
  `linked_pair_read_model_unavailable`.
- Linked-pair history is month-local. The exporter does not backfill, infer or
  guess a relation or balance from another month. Explicit zero balances remain
  exact zero money objects.
- Current debt refs are allocated only from the current-month debt catalog, so a
  unique current debt name keeps the unsuffixed ref behavior of the prior
  contract. Historical pair rows use `debt_ref_scope=historical_period` and
  `debt-history-YYYY-MM-*` refs; they cannot join or alias current `debts[]`.
- The report includes an exact stored ISIN when present and universal position
  fields for gold and other instruments. Gold does not get a parallel formula.
- Free text is context, not a structured financial fact. Numbers in comments or
  notes must not affect calculations, matching, coverage or warnings.
- Plan-vs-actual uses the exact `(period, category, expense_type)` key. A
  missing side is `null`; an explicit zero is a money object with `amount` set
  to `"0.00"`. No variance or budget formula is invented by this contract.
- #336 facts are consumed as already implemented in current `main`: `0%` is a
  real fact, `null` is unknown, planned budget is separate from actuals, and
  missing optional values do not block export.


<a id="c10-ai_financial_review-1-5-provenance-and-privacy"></a>
#### 5. Provenance and privacy

`metadata.source_contracts` pins the source schemas used by the adapter:

- `hermes.finance.ai_analysis_bundle` `1.4.0`;
- `hermes.finance.portfolio_review_package` `1.1.0`.

The performance section records the accepted builder identities as method
metadata: `R08-02` for XIRR, `R08-03` for exact TWRR and `PERF04A/1` for the
monetary bridge. These identifiers describe the source contracts; they do not
create a second calculation implementation.

Linked-pair metrics use `source=linked_pair_read_model`; this identifies the
canonical #365 read model rather than a provider payload or an exporter-side
calculation.

The metadata also records the integrated `#336` financial-context contract by
name, without pretending that it is a separate calculation schema.

Allowed owner context is limited to persisted monthly comments and explicitly
stored notes on exported owner facts. The report excludes tokens, credentials,
cookies, database/backup/export paths, local host/router details, database IDs,
raw account/external codes, provider IDs, raw protocol payloads, uploaded
documents, stack traces, SQL and open-ended diagnostic evidence.


<a id="c10-ai_financial_review-1-6-versioning-and-compatibility"></a>
#### 6. Versioning and compatibility

`schema_version` follows SemVer:

- patch: clarification or validation correction without changing valid-instance
  meaning;
- minor: additive optional fields/sections or backward-compatible enum values;
- major: removal/rename, changed requiredness/units, changed source meaning or
  changed financial counting semantics.

Version `1.2.0` adds the required `performance` section. Version `1.3.0`
adds optional month-local linked-pair fields to `current_capital` and
`historical_dynamics`; the canonical exporter emits them on every generated
report, including empty arrays. It changes no capital formula or counting
semantics. The generated canonical v1.3 instance validates strictly.

Consumers dispatch on the major version and validate the exact schema declared
by the file. The v1 contract is strict (`additionalProperties=false` in the
normative schema) so exporter leaks and typos fail early. Existing bundle and
package versions are not silently mutated by this report.

The canonical recommended export is one JSON file. A future Markdown export,
if added, must be generated from the same read-only snapshot and must not have
separate financial semantics. Generation must not persist an export, refresh a
provider, send data to a cloud/LLM service or alter the database.


<a id="c10-ai_financial_review-1-7-export-page-hierarchy-contract"></a>
#### 7. Export-page hierarchy contract

The future Export-page implementation must make the choice obvious in this
order:


<a id="c10-ai_financial_review-1-71-recommended-block--first-export-content"></a>
#### 7.1 Recommended block — first export content

Label/badge: **Рекомендуется для AI-анализа**

Title: **Полный финансовый отчёт для AI**

Copy:

> Рекомендуемый вариант для ежемесячного анализа. Содержит капитал,
> динамику, портфель, распределение и концентрацию, доходы, цели, долги,
> недвижимость, будущие выплаты, качество данных, план накоплений и ваши
> комментарии.

Primary CTA: **Выгрузить отчёт для AI (JSON)**

The block must state that the file contains financial data, is created locally,
is not sent automatically, and should be checked before manual upload. A small
preview may show the selected period, covered history, section states and warning
count without recomputing any value. There is no Markdown companion or
secondary AI-report CTA in the #331 implementation scope; Markdown remains a
future/out-of-scope option.


<a id="c10-ai_financial_review-1-72-additionaltechnical-exports--collapsed-and-secondary"></a>
#### 7.2 Additional/technical exports — collapsed and secondary

Use a `<details>`/secondary panel titled **Дополнительные / технические
выгрузки**. Every item must explain what it contains, how it differs, when to
use it and when not to choose it:

- **AI Analysis Bundle** — compact semantic KPI/coverage/reason-code source;
  use for contract debugging, not for the ordinary monthly handoff.
- **Portfolio Review Package / Full** — detailed investment review with
  allocation, concentration, freshness and section states; use for portfolio
  diagnostics, while the recommended report already includes its useful data.
- **Concise Portfolio Review Package** — profile-limited diagnostic view; use
  only when a deliberately smaller technical package is needed.
- **Legacy/raw finance export** — compatibility/debugging dump; use for
  migration or investigation, not for ordinary AI analysis.

Backup/restore remains a separate lower-priority local-database section and is
not presented as an AI export.


<a id="c10-ai_financial_review-1-73-delivered-ui-hierarchy-and-regression-boundary"></a>
#### 7.3 Delivered UI hierarchy and regression boundary

Frontend coverage preserves for the hierarchy and
copy: the recommended block appears before additional exports, has one primary
CTA, every technical export has a purpose/difference explanation, and the local
no-cloud warning is visible. The accepted export page implements this hierarchy.


<a id="c10-ai_financial_review-1-8-required-semantic-regression-cases"></a>
#### 8. Required semantic regression cases

Schema validation and synthetic regression coverage preserve, at minimum:

1. a monthly comment containing a number, proving the text is preserved but not
   used as an authoritative value;
2. a bond with exact ISIN;
3. a gold position with average acquisition cost/cost basis and current price;
4. a saving allocation with destination and note;
5. IIS type/opening/eligible-close metadata;
6. one #336 zero rate and one unknown rate;
7. an unentered planned budget that is not serialized as a zero budget;
8. a missing historical month and an unavailable aggregate that remain unknown.

Verification must prove read-only generation, stable ordering, no technical
secret fields, and unchanged behavior of the three existing export families.

<a id="c10-portfolio_review_package-1"></a>
### Portfolio review identity and scope

**Status:** first bounded slice for [issue #237](https://github.com/LTstripes/hermes-finance/issues/237).

**Contract:** `hermes.finance.portfolio_review_package` version `1.1.0`.

**Normative schema:** [`portfolio_review_package.schema.json`](schemas/portfolio_review_package.schema.json)

**Synthetic fixture:** [`portfolio_review_package.synthetic.json`](schemas/portfolio_review_package.synthetic.json)

**Recommended #331 handoff:** [`AI_FINANCIAL_REVIEW.md`](#c10-ai_financial_review-1)

This package remains the detailed portfolio-review/source envelope. The one
recommended monthly AI handoff is the #331 report; this package is an additional
technical/diagnostic export and is not the default choice in Export UI.


<a id="c10-portfolio_review_package-1-scope-of-this-slice"></a>
#### Scope of this slice

This slice records the gap audit, freezes the transport contract, and provides the
local owner-triggered portfolio-review handoff. It adds a read-only package
endpoint, a human-readable companion report, and a preview/download UI. It does
not upload data, call a cloud service or LLM, persist an export, or refresh a
provider.

The current `hermes.finance.ai_analysis_bundle` contract is the source
implementation for the first adapter. The review package `1.1.0` reports the bundle
schema version it was projected from in `metadata.source_contract_version`, so that
metadata advances with the bundle instead of being frozen at the initial value. The
review package
is one new output contract, not a second financial model: its sections deliberately reuse
the existing bundle's money, availability, provenance, payout-counting, and
closed-month semantics. A later assembler maps existing DTOs/read models into this
contract without recalculating them.

<a id="c10-portfolio_review_package-58"></a>
### Portfolio review profiles and coverage

<a id="c10-portfolio_review_package-58-profile-semantics"></a>
#### Profile semantics

Both profiles have the same top-level shape. Section state is never inferred from
an absent JSON key.

| Section | `concise` | `full` |
| --- | --- | --- |
| `capital` | Included selected-period capital summary | Included selected-period capital summary |
| `positions` | Included current positions and valuation | Included current positions, cash, deposits, and valuation/provenance |
| `dynamics` | Included ordered history and explicit gaps | Included ordered history and explicit gaps |
| `passive_income` | Included actual/average/forecast | Included actual/average/forecast and full breakdown |
| `future_cash_flows` | Included totals and dated items | Included totals and dated items |
| `freshness` | Included family status and coverage | Included family status and coverage |
| `allocation` | Omitted by profile unless a later concise policy opts in | Included when the accepted risk-allocation read model is available |
| `context` (goals, debt/property, IIS/tax) | Omitted by profile | Included when each source is available; individual metrics can still be unavailable |
| `deterministic_insights` | Omitted by profile | Included only as the typed, sanitized insight shape; unavailable/omitted is explicit if not assembled |

The contract allows a full profile to mark a source `unavailable` when Hermes has
no authoritative value. `omitted` means the owner/profile intentionally did not
request the field. These states are different and must not be collapsed into an
empty array or zero.


<a id="c10-portfolio_review_package-58-state-and-privacy-rules"></a>
#### State and privacy rules

- A section envelope always contains `status`, sorted unique `reason_codes`, and
  `data`. `included`/`partial` requires non-null data; `unavailable`/`omitted`
  requires `data: null`.
- Money, rates, percentages, and quantities are strings. No binary JSON floats
  are part of the contract.
- `money_metric` and `ratio_metric` carry the authoritative value, availability,
  precision, source, and reason codes. An unavailable metric is `null` with
  `precision=unknown`; it is never a guessed zero.
- `field_states` records unavailable or omitted non-metric paths and section
  paths. Metric-local availability remains the source of truth for metric fields.
- `freshness.evaluated_on` and `metadata.generated_at` are evaluation/generation
  clocks, not financial observations. Quote freshness uses the accepted
  `quote_valuation_target_date`; no apply time or local edit time is substituted.
- Current and historical financial semantics come from existing services/read
  models. The package does not calculate a net-worth sum, return, tax, forecast,
  concentration, or freshness score in the exporter.
- Provenance is limited to the existing safe source/provider vocabulary. Export
  refs such as `acct-*`, `inst-*`, and `flow-*` are local join keys, not database
  or provider identifiers.
- Warnings are short owner-safe messages. They contain no tokens, credentials,
  local paths, database IDs, SQL, stack traces, raw provider payloads, or private
  diagnostics.


<a id="c10-portfolio_review_package-58-authoritative-source-map"></a>
#### Authoritative source map

| Package section | Existing source/read model | Boundary |
| --- | --- | --- |
| `capital` | `liquid_capital_for_month`, `property_equity` | Liquid capital remains separate from property equity and mortgage |
| `positions` | current `ai_analysis_bundle` projection over account/instrument/position/deposit/cash snapshots | Provider observations do not replace Hermes valuation or identity |
| `dynamics` | `reporting_history` from the current bundle and historical batch/read models | Missing months stay unknown; no fabricated deltas/returns |
| `passive_income` | `passive_income_for_month`, `passive_income_average`, `forecast_passive_income` | Actual, forecast, dividend-history component, and redemption remain distinct |
| `future_cash_flows` | `merged_payout_calendar` | Calendar total, non-principal total, and principal total remain separate |
| `freshness` | `build_freshness_provenance_summary` | Family statuses and reason codes are carried over; no provider call |
| `allocation` | `risk_allocation` / dashboard allocation DTOs | DB/provider IDs are replaced by export-local refs or omitted |
| `context` | existing goals, debt/property, IIS/tax read models | Received benefits only affect actual IIS result; incomplete salary history stays unavailable. Every known active IIS account is listed even with an unconfigured lifecycle/tax profile (`null` lifecycle fields, `iis_tax_data_unconfigured` result metrics), and the selected month's salary/tax reconciliation is projected under `salary_tax_context.selected_month` |
| `deterministic_insights` | `build_deterministic_insights` | Only the closed typed projection is safe for this contract; open evidence maps are not copied |

When the selected history point is `partial` with `active_account_snapshot_missing`,
the known liquid-capital subtotal stays `available` / `exact`. The capital
section carries that reason beside `total_net_worth_unavailable`;
`total_net_worth` stays unavailable with `no_authoritative_aggregate`.
Historical-dynamics coverage follows the history point. A capital goal's
current value and progress keep the subtotal and carry the same reason.
Asset-class allocation, account allocation and top-position concentration
keep the risk-allocation shares and amounts; their support becomes `partial`
with the same reason. Payout and redemption concentration, performance and
cash-boundary coverage stay separate. See
[`financial-completeness-contract.md`](#c2-financial-completeness-contract-8).


<a id="c10-portfolio_review_package-58-versioning-and-follow-ups"></a>
#### Versioning and follow-ups

`schema_version` follows SemVer. A minor version may add optional sections or
profile-compatible fields; a major version is required for changed requiredness,
units, counting semantics, or source meaning. Consumers dispatch on the major
version and must validate the exact schema identified by the package.

The package endpoint is available at `GET /api/export/portfolio-review-package`
for an explicit local preview. `GET /api/export/portfolio-review-package/json`
and `/markdown` download the same assembled DTO as JSON or a human-readable
Markdown companion. The owner UI exposes concise/full profile selection, section
status preview, and both downloads from the Export screen. Synthetic assistant
evaluation remains fixture-based and does not use owner data. Owner UAT with real
local data remains separate and no real package belongs in Git.
