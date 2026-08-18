# Finance Dashboard — Project Wiki

> Долгоживущий контекст Hermes Finance. Здесь фиксируется текущее состояние проекта и принятые решения; подробный execution journal остаётся в Git history, release/backlog docs и `CHANGELOG.md`. Персональные финансовые данные сюда не помещаются.

## 1. Что мы строим

Hermes Finance — локальное однопользовательское Windows-first веб-приложение для ежемесячного ведения личных финансов. Оно хранит snapshots по отчётным месяцам и показывает:

- ликвидный капитал после включённых долгов;
- динамику капитала;
- фактический и прогнозный чистый пассивный доход;
- прогресс основной цели;
- покрытие обязательных расходов;
- инвестиционный результат отдельно от денежных потоков;
- ИИС и полученную/планируемую налоговую выгоду;
- справочную недвижимость и покрытие ипотеки;
- рыночные котировки и календарь инвестиционных выплат по явному действию владельца.

Приложение не является бухгалтерской, налоговой или торговой системой.

## 2. Источники истины

При конфликте документов использовать такой порядок:

1. `docs/MASTER_SPEC.md` — бизнес-инварианты, формулы и границы продукта.
2. Принятые ADR в `docs/adr/` — более конкретные нормативные решения.
3. Активный release или task-документ, если он есть.
4. `docs/VERIFICATION_POLICY.md` — стратегия targeted/full-suite/CI проверок.
5. `docs/MODEL_ROUTING.md` — роли, класс риска и эскалация.
6. Этот wiki — долговременный контекст.
7. Исторические документы (`docs/HERMES_TASKS.md`, `docs/HERMES_START_PROMPT.md`, `docs/IDEA.md`, старые release-файлы) — только как исторический контекст.

Операционный протокол агентов — `AGENTS.md`. Адаптеры клиентов — `docs/agents/`.

Private seed, SQLite DB, exports, backups и реальные финансовые значения остаются локальными и Git-ignored.

## 3. Текущее стабильное состояние

Текущий стабильный релиз — **0.5.0**.

- `main` = `r05` = `v0.5.0` = `7a032eb8c61c675f3a779f9afda59d47e9c8dc81`
- GitHub Release `0.5.0` опубликован как Latest
- финальный exact-main CI `32140936658` зелёный
- owner live smoke, включая T-Invest, пройден
- линия R05 закрыта; новых R05-задач нет

В 0.4 появились явные T-Invest котировки (mapping → preview → selective apply, append-only provenance). В 0.5 добавлен owner-controlled календарь купонов/дивидендов/погашений с тем же явным lifecycle.

Runtime по-прежнему local-only: loopback `127.0.0.1:8000`, провайдер только read-only, сеть только после явного действия владельца. Нет cloud/auth/telemetry, background refresh или trading API.

Канонический общий источник — GitHub-репозиторий. Development-агенты работают в независимых clone и синхронизируются с каноническим `main`. Продакшен живёт в отдельном runtime-checkout. См. ADR 0012.

## 4. Продуктовые границы

### Входит в текущий локальный продукт

- Windows-first production launcher;
- SQLite;
- один пользователь без авторизации;
- месячный draft/closed lifecycle, reopen и клонирование;
- счета, инструменты, позиции, депозиты, cash и другие ликвидные активы;
- зарплата/доходы, прогрессивный НДФЛ, расходы, savings, долги, недвижимость, ипотека и ИИС;
- фактические инвестиционные выплаты и ручные ожидаемые потоки;
- T-Invest котировки по явной кнопке владельца;
- T-Invest календарь выплат (preview/apply) поверх локальных позиций Hermes;
- Goals и основная цель;
- Dashboard и графики;
- Markdown/JSON export;
- SQLite online backup/restore;
- private seed и legacy Excel migration tooling.

### Не входит без отдельного решения

- торговые операции;
- автоматические банковские транзакции;
- импорт брокерского портфеля, счетов или операций;
- cloud/VPS/multi-user/auth;
- фоновая телеметрия;
- фоновое обновление котировок или выплат;
- production fallback на MOEX;
- универсальный импорт любого Excel/PDF;
- точная доходность с датированными внешними потоками до отдельного контракта.

## 5. Технический контур

- Backend: Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Pydantic.
- Storage: SQLite с foreign keys.
- Frontend: React 19, TypeScript, Vite, React Router 8, Recharts и собственные UI/CSS primitives.
- Backend tests: pytest; lint/format: Ruff.
- Frontend tests: Vitest + Testing Library; lint/format: Biome; минимальный Playwright smoke.
- Production UI и API обслуживаются локально на `127.0.0.1:8000`.
- Dev frontend работает на `127.0.0.1:5173` и проксирует `/api` в локальный backend.
- Финансовые формулы живут на backend. Frontend получает exact API values и занимается presentation/UI validation, но не дублирует денежные формулы.

## 6. Неприкосновенные инварианты

Без явного решения владельца нельзя:

- использовать binary `float` для денег;
- включать кэшбэк в пассивный доход;
- включать недвижимость в liquid capital;
- считать redemption номинала облигации доходом;
- называть изменение стоимости портфеля доходностью без учёта потоков;
- прибавлять planned/submitted IIS benefit к фактически полученному результату;
- доверять рассчитанным финансовым значениям от frontend;
- молча изменять данные закрытого месяца;
- коммитить private DB/seed/export/backup/реальные финансовые payload;
- добавлять cloud/auth/telemetry/trading capabilities в локальный продукт без отдельного scope decision;
- давать development-агенту доступ к production runtime data.

Деньги в persistence/domain используют integer minor units/`Decimal` и `ROUND_HALF_UP`. API передаёт деньги как decimal string + ISO currency.

## 7. Ключевые финансовые контракты

### Пассивный доход

Фактический passive income включает проценты депозитов, купоны, дивиденды и прочий доход от капитала; active income, cashback и redemption исключены.

`deposit_snapshots.actual_interest_received` — канонический источник фактического процента депозита/накопительного счёта. Generic `investment_cash_flows.interest` не дублирует его.

Фактический dividend остаётся полностью в месяце получения. Forecast dividend component использует среднее фактических net dividends по доступным закрытым месяцам, максимум rolling 12.

### Income cash flow

`include_in_cash_flow` нормативно управляет попаданием income row в месячный cash balance. Active/non-passive и passive OTHER не должны double-count между active и passive buckets. Контракт R02-18/R02-19 является нормативным уточнением к общим формулам `MASTER_SPEC`.

### НДФЛ и opening YTD

Прогрессивный salary tax считается backend по календарному YTD.

- `known month` = существующий reporting month со статусом `closed`;
- draft не считается известным нулём;
- reopen снова делает месяц unknown для downstream YTD;
- при неполной истории используется fail-closed `salary_tax_history_incomplete`;
- для года, история которого начинается позже января, может быть задан annual opening tax context с `effective_from_month` и aggregate taxable gross до boundary;
- opening context учитывается ровно один раз и не должен double-count реальные месяцы;
- редактор старого draft остаётся доступным даже если расчётная налоговая часть временно недоступна.

Нормативный контракт opening YTD находится в `docs/adr/0002-opening-ytd-gross.md`.

### Tax bracket administration

Шкала хранится как полный набор ступеней на календарный год. API/UI валидирует целостную шкалу атомарно. Если в этом году существует хотя бы один `closed` reporting month, шкала защищена от молчаливого исторического изменения. Сознательная историческая правка требует явного reopen закрытых месяцев соответствующего года.

Month editor показывает ставки из backend `salary_tax.parts`; при пересечении порога одной выплатой UI показывает несколько применённых ставок и текущую marginal bracket, а не вычисляет «ставку» делением tax/gross.

### Goals

`goals` — runtime source of truth. `app_settings.passive_income_goal_kopecks` используется только как compatibility/default seed path, а не как конкурирующее runtime-значение.

Основная passive-income цель использует rolling average фактического net passive income по `closed` reporting months (C03, максимум последние 12) как `current_value` и источник `progress_pct`. C04 forecast остаётся отдельной прогнозной метрикой и не подменяет фактический прогресс. Прогноз даты достижения по-прежнему не придумывает future growth: если траектории нет, статус остаётся `not_projectable`/локализованным пользовательским сообщением. Это уточнение R02-27 сознательно supersede'ит только выбор source metric из R02-12, не меняя exact progress/gap formula.

## 8. Месяцы и защита истории

- один reporting month на `year + month`;
- draft редактируем;
- closed read-only до явного reopen;
- sanctioned delete разрешён только для draft и удаляет принадлежащие месяцу строки транзакционно до parent row;
- DB `ON DELETE RESTRICT` остаётся общей защитой вне sanctioned service path;
- clone переносит permanent state/snapshots, но не копирует фактические выплаты/комментарии как новые события.

## 9. Позиции и количества

Persistence допускает точность `Numeric(18,6)` для типов, где дробное количество легитимно. Для `stock` количество должно быть положительным целым (`>= 1`) на API/backend boundary. UI скрывает бессмысленные trailing zeroes и форматирует user-facing quantity без перевода финансовых денег в JS float.

Market value/cost basis/unrealized result пересчитываются backend и не принимаются от frontend как source of truth.

Котировки T-Invest применяются только после явного preview/apply. Историческая provenance неизменяема. Количество позиции остаётся локальными данными Hermes, не брокерским портфелем.

## 10. Ожидаемые выплаты и календарь провайдера

Ручные `expected_cash_flows` привязаны к reporting month + `forecast_version` и одному `source_as_of_date` внутри версии. Они остаются first-class owner data.

С 0.5 календарь объединяет ручные ожидаемые выплаты и уже применённые события T-Invest:

- lifecycle: Fetch → Normalize → Preview → owner selection → Apply;
- количество для провайдерской выплаты берётся из локального `PositionSnapshot`;
- apply не редактирует и не удаляет ручные строки;
- неразрешённый дубль считается только вручную, пока владелец явно не выберет `keep_both`, `count_manual` или `count_provider`;
- применённые купоны провайдера могут кормить C04; объявленные дивиденды видны в календаре и не заменяют исторический dividend component;
- погашение — денежный поток, не пассивный доход;
- наступление даты события не создаёт фактическую инвестиционную выплату.

Нормативный контракт: `docs/adr/0011-automatic-investment-payout-calendar.md`.

## 11. Backup, SQLite и локальная безопасность

- startup применяет Alembic migrations до readiness;
- backup/restore защищены process-local maintenance guard;
- restore дожидается активных DB requests, создаёт pre-restore backup и проверяет SQLite/schema candidate;
- SQLite остаётся в rollback journal (`journal_mode=delete`) с effective `busy_timeout=5000 ms`; WAL не включён без воспроизводимой необходимости, чтобы не усложнять Windows backup/restore sidecars;
- production unsafe requests ограничены localhost Host/Origin contract;
- приложение по умолчанию слушает только `127.0.0.1:8000`.

## 12. Verification policy

`docs/VERIFICATION_POLICY.md` — нормативный процесс проверок.

Коротко:

- targeted tests во время реализации;
- после стабилизации — один full suite затронутого слоя;
- docs-only не требуют локального full suite;
- API/shared-contract — проверки затронутых слоёв;
- Windows/migrations/backup/restore/security/concurrency — targeted → relevant full suite → task probe → exact-HEAD CI;
- task-card может только усилить policy.

GitHub Actions включает backend, frontend, privacy guard и Windows production smoke.

## 13. Workspace и агенты

Репозиторий — канонический общий source. После 0.5.0 runtime и development разведены:

- один production runtime clone с локальными ignored runtime-данными;
- независимый clone на каждого development-агента, со своим Git directory;
- агент не видит и не линкует production `.env`, DB, backups, `private/` или owner payloads.

Перед новой задачей чистый clone синхронизируется с каноническим `main`. Несколько писателей в одном scope не работают. Machine-specific абсолютные пути — локальная конфигурация, не архитектура репозитория.

Подробности: ADR 0012, `AGENTS.md`, `docs/agents/`, `docs/MODEL_ROUTING.md`.

## 14. История

Детальный phase-by-phase execution journal MVP 0.1 сохранён в `docs/HERMES_TASKS.md` и Git history. Релизы 0.2–0.5 зафиксированы в `docs/releases/`, `CHANGELOG.md` и `docs/EXECUTION_HISTORY.md`. Wiki не дублирует позадачную историю.

`docs/IDEA.md` намеренно сохранён как исходная концепция.
