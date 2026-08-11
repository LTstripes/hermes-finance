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
- справочную недвижимость и покрытие ипотеки.

Приложение не является бухгалтерской, налоговой или торговой системой.

## 2. Источники истины

При конфликте документов использовать такой порядок:

1. `docs/MASTER_SPEC.md` — бизнес-инварианты, формулы и границы продукта.
2. Принятые ADR в `docs/adr/` — более конкретные нормативные решения по отдельным контрактам.
3. Активный release backlog (`docs/RELEASE_0_2.md` для 0.2) — текущие task-cards, статусы и release gate.
4. `docs/MODEL_ROUTING.md` — текущий routing/settling protocol.
5. `docs/VERIFICATION_POLICY.md` — обязательная стратегия targeted/full-suite/CI проверок.
6. `docs/HERMES_START_PROMPT.md` и `AGENTS.md` — рабочий протокол агентов.
7. Этот wiki — долговременный контекст и краткая карта принятых решений.
8. `docs/HERMES_TASKS.md` — исторический backlog строительства MVP 0.1, не источник новых post-MVP задач.

Private seed, SQLite DB, exports, backups и реальные финансовые значения остаются локальными и Git-ignored.

## 3. Продуктовые границы

### Входит в текущий локальный продукт

- Windows-first production launcher;
- SQLite;
- один пользователь без авторизации;
- месячный draft/closed lifecycle, reopen и клонирование;
- счета, инструменты, позиции, депозиты, cash и другие ликвидные активы;
- зарплата/доходы, прогрессивный НДФЛ, расходы, savings, долги, недвижимость, ипотека и ИИС;
- фактические/ожидаемые investment cash flows;
- Goals и основная цель;
- Dashboard и графики;
- Markdown/JSON export;
- SQLite online backup/restore;
- private seed и legacy Excel migration tooling.

### Не входит без отдельного решения

- торговые операции;
- автоматические банковские транзакции;
- cloud/VPS/multi-user/auth;
- фоновая телеметрия;
- автоматические котировки в текущем 0.2;
- автоматическое формирование календаря купонов/дивидендов/погашений в 0.2;
- универсальный импорт любого Excel/PDF;
- точная доходность с датированными внешними потоками до отдельного контракта.

## 4. Технический контур 0.2

- Backend: Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Pydantic.
- Storage: SQLite с foreign keys.
- Frontend: React 19, TypeScript, Vite, React Router 8, Recharts и собственные UI/CSS primitives.
- Backend tests: pytest; lint/format: Ruff.
- Frontend tests: Vitest + Testing Library; lint/format: Biome; минимальный Playwright smoke.
- Production UI и API обслуживаются локально на `127.0.0.1:8000`.
- Dev frontend работает на `127.0.0.1:5173` и проксирует `/api` в локальный backend.
- Финансовые формулы живут на backend. Frontend получает exact API values и занимается presentation/UI validation, но не дублирует денежные формулы.

## 5. Неприкосновенные инварианты

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
- добавлять cloud/auth/telemetry/trading capabilities в локальный продукт без отдельного scope decision.

Деньги в persistence/domain используют integer minor units/`Decimal` и `ROUND_HALF_UP`. API передаёт деньги как decimal string + ISO currency.

## 6. Ключевые финансовые контракты

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

## 7. Месяцы и защита истории

- один reporting month на `year + month`;
- draft редактируем;
- closed read-only до явного reopen;
- sanctioned delete разрешён только для draft и удаляет принадлежащие месяцу строки транзакционно до parent row;
- DB `ON DELETE RESTRICT` остаётся общей защитой вне sanctioned service path;
- clone переносит permanent state/snapshots, но не копирует фактические выплаты/комментарии как новые события.

## 8. Позиции и количества

Persistence допускает точность `Numeric(18,6)` для типов, где дробное количество легитимно. В 0.2 введён более строгий invariant для `stock`: количество должно быть положительным целым (`>= 1`) на API/backend boundary. UI скрывает бессмысленные trailing zeroes и форматирует user-facing quantity без перевода финансовых денег в JS float.

Market value/cost basis/unrealized result пересчитываются backend и не принимаются от frontend как source of truth.

## 9. Expected payments

`expected_cash_flows` привязаны к reporting month + `forecast_version` и одному `source_as_of_date` внутри версии. Redemption отображается, но не входит в passive-income forecast.

В 0.2 expected payment calendar **ручной**: пользователь создаёт persisted expected flows. Автогенерация из позиций/MOEX отложена; до реализации нужно определить source provenance, refresh/version semantics, reconciliation и запрет неоднозначных дублей manual/generated rows.

## 10. Backup, SQLite и локальная безопасность

- startup применяет Alembic migrations до readiness;
- backup/restore защищены process-local maintenance guard;
- restore дожидается активных DB requests, создаёт pre-restore backup и проверяет SQLite/schema candidate;
- SQLite остаётся в rollback journal (`journal_mode=delete`) с effective `busy_timeout=5000 ms`; WAL не включён без воспроизводимой необходимости, чтобы не усложнять Windows backup/restore sidecars;
- production unsafe requests ограничены localhost Host/Origin contract;
- приложение по умолчанию слушает только `127.0.0.1:8000`.

## 11. Verification policy

`docs/VERIFICATION_POLICY.md` — нормативный процесс проверок.

Коротко:

- targeted tests во время реализации;
- после стабилизации — один full suite затронутого слоя;
- docs-only не требуют локального full suite;
- API/shared-contract — проверки затронутых слоёв;
- Windows/migrations/backup/restore/security/concurrency — targeted → relevant full suite → task probe → exact-HEAD CI;
- task-card может только усилить policy.

GitHub Actions включает backend, frontend, privacy guard и Windows production smoke.

## 12. Release 0.2

К 2026-08-11 выполнены основные R02-01…R02-24 изменения, включая owner-led smoke hotfixes. Диагностика R02-25 закрыта без code fix: заявленные дивиденды были заведены владельцем как `coupon`, поэтому нулевой dividend component соответствовал данным и расчётная цепочка не теряла ненулевое значение.

R02-26 (автоматическое наполнение expected-payments calendar) сознательно переносится как non-blocking follow-up; для 0.2 нормативен ручной workflow.

R02-21 синхронизирует version/docs. Tag `v0.2.0` создаётся только после release gate и blocker-level review exact candidate HEAD.

## 13. Работа агентов

- одна write-задача имеет одного primary/owner;
- параллельная работа допустима только по независимым файлам/контрактам;
- explicit `начинаем <ID>`/`запускай <ID>` авторизует конкретную task-card;
- worker report не заменяет diff/tests review primary;
- приватные данные не передаются внешним workers;
- после side effects/CI выполняется final state read-back и один canonical итог.

Операционный routing находится в `docs/MODEL_ROUTING.md`.

## 14. История

Детальный phase-by-phase execution journal MVP 0.1 сохранён в `docs/HERMES_TASKS.md` и Git history. Изменения 0.2 фиксируются в `docs/RELEASE_0_2.md`, smoke/follow-up logs и `CHANGELOG.md`; wiki намеренно не дублирует сотни завершённых шагов.
