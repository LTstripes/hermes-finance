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
- рыночные котировки и календарь инвестиционных выплат по явному действию владельца;
- текущий снимок Alfa PRO и узкий импорт депозитарного PDF о выплатах доходов — тоже только по явному действию владельца.

Приложение не является бухгалтерской, налоговой или торговой системой.

## 2. Источники истины

При конфликте документов использовать такой порядок:

1. `docs/MASTER_SPEC.md` — бизнес-инварианты, формулы и границы продукта.
2. Принятые ADR в `docs/adr/` — более конкретные нормативные решения.
3. Активный release или task-документ, если он есть.
4. `docs/VERIFICATION_POLICY.md` — стратегия targeted/full-suite/CI проверок.
5. `docs/MODEL_ROUTING.md` — роли, класс риска и эскалация.
6. Этот wiki — долговременный контекст.
7. Исторические документы (`docs/history/HERMES_TASKS.md`, `docs/history/HERMES_START_PROMPT.md`, `docs/IDEA.md`, старые release-файлы) — только как исторический контекст.

Операционный протокол агентов — `AGENTS.md`. Адаптеры клиентов — `docs/agents/`.

Private seed, SQLite DB, exports, backups и реальные финансовые значения остаются локальными и Git-ignored.

## 3. Текущее стабильное состояние

Это дерево содержит содержимое release-prep **0.6.3**. Это maintenance поверх **0.6.2**: dashboard information architecture и payout readability, approximate deposit-interest forecast completeness и explicit T-Invest batch refresh / payout-calendar UX. Provider/trading семантика не меняется. Канонический Alembic head — `0029_statement_event_retract`. Опубликованная идентичность определяется неизменяемым Git-тегом и GitHub Release.

Историческая линия **0.6.0** / R06 остаётся в разделе 15: Gate A принят; Gate B — `UAT_PASS` / `GATE_B_PASS`; Gate C accepted and integrated.

Историческая опубликованная идентичность **0.5.0**:

- released artifact: `v0.5.0` @ `7a032eb8c61c675f3a779f9afda59d47e9c8dc81`;
- на публикации 0.5.0 `main`, `r05` и `v0.5.0` указывали на этот exact SHA;
- после публикации канонический development `main` может уходить вперёд post-release docs, maintenance и будущей работой;
- тег и released SHA остаются неизменяемой идентичностью 0.5.0;
- финальный exact-main CI `32140936658` зелёный;
- owner live smoke, включая T-Invest, пройден;
- линия R05 закрыта; новых R05-задач нет.

В 0.4 появились явные T-Invest котировки (mapping → preview → selective apply, append-only provenance). В 0.5 добавлен owner-controlled календарь купонов/дивидендов/погашений с тем же явным lifecycle. В 0.6 добавляются owner-triggered Alfa PRO snapshot и узкий Alfa depository income-payment PDF import. `0.6.1` не расширяет эти пути — только UX review/edit поверх уже принятого 0.6.0. `0.6.2` добавляет auditable retract ошибочно применённых statement payouts и polish layout. `0.6.3` фиксирует M06-07/M06-08/M06-09; deposit forecast остаётся approximate, T-Invest refresh — explicit owner-triggered, parser/provider/trading семантика не меняется.

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
- Alfa PRO current snapshot по явной кнопке, только local loopback, transient mapping, selected apply;
- импорт принятого Alfa депозитарного PDF о выплатах доходов: Inspect → mapping → Prepare → selected Apply;
- Goals и основная цель;
- Dashboard и графики;
- Markdown/JSON export;
- SQLite online backup/restore;
- private seed и legacy Excel migration tooling.

### Не входит без отдельного решения

- торговые операции;
- автоматические банковские транзакции;
- generic import брокерского портфеля, сделок, комиссий, пополнений/выводов или произвольных PDF/Excel;
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

Детальный phase-by-phase execution journal MVP 0.1 сохранён в `docs/history/HERMES_TASKS.md` и Git history. Релизы 0.2–0.5 зафиксированы в `docs/releases/`, `CHANGELOG.md` и `docs/EXECUTION_HISTORY.md`. Wiki не дублирует позадачную историю.

`docs/IDEA.md` намеренно сохранён как исходная концепция.

## 15. Линия 0.6.0 / R06

Линия 0.6.0 закрыта как published product line: Gate A/B/C пройдены; R06-10 accepted and integrated. Опубликованная идентичность 0.6.0 определяется неизменяемым Git-тегом и GitHub Release. Текущее дерево — release-prep maintenance 0.6.3, см. раздел 18. Не переписывайте записи ниже так, будто работа 0.6.0 происходила уже под 0.6.1, 0.6.2 или 0.6.3.

R06 добавляет два owner-controlled пути Alfa поверх существующей локальной модели Hermes:

- явный snapshot review/apply из Alfa PRO без background sync/trading;
- явный импорт стандартизированного депозитарного PDF `Отчет о произведенных выплатах доходов по ценным бумагам` с server-side reparse, fail-closed mapping, idempotency/correction provenance и защитой CLOSED month.

### R06-10 Gate B — owner UAT, состояние на 2026-08-24

Технический Gate A был принят ранее. Owner UAT выполняется только на отдельной копии runtime data; production не используется как тестовый workspace.

Материальные живые находки и fix-cycle:

1. snapshot preview падал после account mapping из-за fingerprint по display DTO вместо persisted `PositionSnapshot`; исправлено без ослабления stale/fingerprint gate;
2. snapshot Apply UI не позволял безопасно идентифицировать строку по owner-facing счёту/инструменту/ISIN; UI усилен;
3. реальный Alfa income-payment PDF выявил, что synthetic parser assumptions не совпадают с текущим `pypdf layout`: сначала были отброшены pipe-only и затем слишком общие multi-line assumptions;
4. parser переведён на bounded fail-closed 21-column report-family structure с точным `1..21` anchor, затем live UAT потребовал несколько узких корректировок реального layout: rank-aligned header reconstruction, актуальная форма заголовков, различение beneficiary columns, игнорирование нетабличного tail и mapping полного data row по физическому column order.

Финальная проверенная code-candidate цепочка после принятого `fa4125a632c8017e076a74c1375502af87866ed6` линейна и содержит пять узких follow-up commit:

- `6a4be2817308bf7e4337e2a1809adede7a9de4c4` — align current Alfa header by rank;
- `76937cd88c9f2bda350be5f0167a7ff9fc4fca8e` — match current Alfa header layout;
- `2c24fd2d5551a7823163e994c8c9d62140af57a8` — keep Alfa beneficiary headers distinct;
- `eeaed4b2ebba5d399f4f712f99ac67a008494d20` — ignore Alfa layout trailing fragments;
- `c4bb8ff15631f82b957ae82f2508a6598d0cc6e3` — map anchored Alfa data by column order.

`c4bb8ff15631f82b957ae82f2508a6598d0cc6e3` — accepted Gate B code. Независимый repository read-back подтверждает линейность `fa4125a6… → c4bb8ff…`: `ahead_by=5`, `behind_by=0`, изменения остаются в четырёх parser/schema/synthetic-test файлах. На том этапе `r06` и `main` ещё не менялись.

По owner/Work UAT-report для exact `c4bb8ff…`:

- full backend: `1218 passed` (известное предупреждение pytest cache не считается blocker);
- independent Terra review: ACCEPT по отчёту Work; эта model-attribution не выводится из Git metadata;
- тот же owner-local Alfa PDF распознан ровно в 4 строки;
- локальная сверка event type, ISIN, dates, gross/tax/net с исходным PDF прошла;
- UI показывает все 4 строки как требующие явного сопоставления, unsupported rows нет;
- подготовка/apply не выполнялись, persistent writes по этим строкам не делались;
- owner UAT и dev workspace оставлены clean, localhost остановлен;
- production runtime, `main`, `r06`, PR/merge/tag/release не затрагивались.

Следующий Gate B шаг на момент промежуточной записи 2026-08-24 — только явный owner mapping найденного отчётного счёта и инструментов в UAT-копии, затем отдельное решение о Prepare/Apply.

### R06-10 Gate B — UAT_PASS / GATE_B_PASS

Каноническое owner-UAT evidence записано в issue #98. Exact Gate B code остаётся `c4bb8ff15631f82b957ae82f2508a6598d0cc6e3`. Production runtime не использовался.

Сводка без частных значений:

- statement Inspect = 4 rows, unsupported 0;
- mapping/reconciliation PASS;
- one-row statement Apply PASS;
- duplicate/idempotency PASS;
- CLOSED statement PASS;
- manual candidate explicit decision / zero-write PASS;
- one-row matched existing snapshot Apply PASS;
- UNCHANGED no-op behavior observed correctly;
- CLOSED snapshot PASS;
- restart stability PASS;
- no blockers.

### R06-10 Gate C — version/docs finalization

Gate C синхронизировал version metadata, release-facing docs и повторный verification gate. Принятый worker head `1fc35d173f4c5dbb68cf76c0aaa2a1b20210d421` интегрирован в `r06` через PR #99 (`2222ba016854d52e88eb9a5404c81203655ccd3a`, CI #302). Публикация — отдельный guarded step; exact main/tag/CI identity записывается после release.

## 16. Линия 0.6.1 / M06 maintenance

`0.6.1` — maintenance поверх 0.6.0. Исторические записи 0.6.0 выше не переписываются.

- **M06-01** (issue/PR #103): плотность таблиц редактора месяца, общие overflow-действия, недостающие Edit для ручных investment/expense/savings/debt/property потоков через существующие PATCH, provenance оценки позиции в HelpTip. Backend/schema не менялись. Интегрировано merge `a00e0768db2827bdfad917559c82aab01aea745d`.
- **M06-02** (issue #104 / PR #105): читаемая иерархия quote preview; transient Alfa mapping только пока панель импорта смонтирована; явный безопасный save ISIN в канонический `Instrument.isin`; человекочитаемое evidence в prepared/candidate review; `select all ready`. Backend/schema/provider persistence не менялись. Интегрировано merge `196e992c7b3a72255c7b91ca7ec11ef9e1e32281`.
- **M06-03** (issue #106): только подготовка release identity `0.6.1` (version metadata, CHANGELOG, public notes, wiki/history). Не feature work. Не merge/tag/GitHub Release из этой задачи.

Safety contract 0.6 остаётся: нет OCR, нет persistent raw Alfa/provider payload, нет persistent Alfa account mapping, explicit selected Apply, duplicate/idempotency, CLOSED/missing month fail closed, без изменения provider/trading семантики.

## 17. Линия 0.6.2 / M06 maintenance

`0.6.2` — maintenance поверх 0.6.1. Исторические записи 0.6.0 и 0.6.1 выше не переписываются.

- **M06-04** (issue #108 / PR #110): безопасный auditable retract ошибочно применённых Alfa statement payouts; Alembic `0029_statement_event_retract`; UI `Отменить импорт` / `Отвязать выписку`. Интегрировано merge `53610ce370f70bdf028d85d97692f83b8ba79014`.
- **M06-05** (issue #109 / PR #112): polish layout таблиц редактора месяца, dedicated position inline-edit, плотность Alfa prepared-import, accent даты выплат. Frontend/layout only поверх already-merged retract. Интегрировано merge `382d572a2da976c76bd7dc873153dae61948c6c2`.
- **M06-06** (issue #113): только подготовка release identity `0.6.2` (version metadata, CHANGELOG, public notes, wiki/history). Не feature work. Не merge/tag/GitHub Release из этой задачи.

Safety contract 0.6.2: предыдущий контракт 0.6 плюс statement-specific auditable retract; generic investment-flow delete не уничтожает statement provenance молча; Alembic head остаётся `0029_statement_event_retract`.

## 18. Линия 0.6.3 / M06 maintenance

`0.6.3` — release-prep maintenance поверх 0.6.2. Исторические записи 0.6.0, 0.6.1 и 0.6.2 выше не переписываются.

- **M06-07** (issue #115 / PR #118): dashboard cards разделяют passive-income fact, forecast/goal и mandatory-expense coverage; actual coverage остаётся backend/domain Decimal calculation; mortgage context и instrument/company-first payout rows стали читаемее. Интегрировано merge `407dad4238e8dbd0c96eed44fd0c195ca5ada63d`.
- **M06-08** (issue #116 / PR #119): selected-month persisted deposit snapshots дают annualised monthly estimate × 12; этот deposit component явно approximate, manual expected interest additive; forecast breakdown показывает deposits/coupons/dividend component/other. Интегрировано merge `0a4210e5898e6674742f2ad2874d7bb8f62a7c19`.
- **M06-09** (issue #117 / PR #120): `Проверить все позиции T-Invest` и `Проверить изменённые` остаются explicit owner-triggered preview actions; изменения количества не запускают background refresh; Apply остаётся отдельным explicit действием; payout calendar получил явное раскрытие месяца и instrument/company-first rows. Интегрировано merge `f20ac97ba792f3e7ccf549c7df99f592172806da`.
- **M06-10** (issue #121): только подготовка release identity `0.6.3` — version surfaces, health/release expectations, CHANGELOG, public notes, release record, README/wiki/history. Exact baseline `f20ac97ba792f3e7ccf549c7df99f592172806da`; task branch `m06-10-release-063`. Не feature work, не merge/tag/GitHub Release.

Safety contract 0.6.3: deposit forecast is approximate and not maturity-aware; T-Invest provider/network refresh is explicit and owner-triggered with no background refresh; batch preview не означает cross-position atomic Apply; нет cloud/auth/telemetry/trading/provider writes; no new migration; canonical Alembic head остаётся `0029_statement_event_retract`.
