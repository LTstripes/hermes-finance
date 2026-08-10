# Release 0.2 — active backlog

> **Статус:** ACTIVE  
> **Релиз:** `0.2.0`  
> **Главная спецификация:** `docs/MASTER_SPEC.md`  
> **Модельный протокол:** `docs/MODEL_ROUTING.md`  
> **Исторический MVP backlog:** `docs/HERMES_TASKS.md`

## 0. Назначение файла

Этот файл — активный исполняемый backlog версии `0.2.0` после завершения MVP `0.1.0`.

`docs/HERMES_TASKS.md` сохраняется как исторический пошаговый backlog строительства MVP и больше не является источником новых post-MVP задач. Старые разделы H/I/J/K в нём являются legacy roadmap: они не входят в `0.2.0` автоматически. Любая такая идея сначала должна быть явно перенесена владельцем в активный release backlog отдельной `R02-*` task-card.

Правило работы остаётся прежним: **одна task-card за одну итерацию; следующая задача не начинается без явной команды владельца**.

### Статусы

`IDEA → SPECIFIED → READY → IN_PROGRESS → REVIEW → DONE`

Дополнительно:

- `BLOCKED` — есть обязательная зависимость или нерешённый контракт;
- `DEFERRED` — задача сознательно отложена и не блокирует релиз.

### Приоритеты

- **P0** — корректность данных/финансов или возможность штатно запустить/обновить приложение; блокирует релиз.
- **P1** — существенная надёжность, безопасность или продуктовая функция; обычно должна попасть в релиз.
- **P2** — улучшение UX/качества; может быть перенесено без нарушения корректности продукта.

### Общий Definition of Done

Для каждой `R02-*` задачи:

1. Прочитаны эта task-card, связанные разделы `MASTER_SPEC.md`, актуальные ADR и `MODEL_ROUTING.md`.
2. Перед кодом дан короткий план; scope не расширяется «заодно».
3. Финансовая логика сохраняет `Decimal`/integer minor units и `ROUND_HALF_UP`; финансовые вычисления через binary `float` не добавляются.
4. Изменение покрыто минимально достаточными тестами/проверками.
5. Приватные финансовые данные, локальная БД, backup/export/seed не попадают в Git или логи.
6. Не добавляются cloud, auth, telemetry, VPS или trading capabilities.
7. Primary принимает фактический diff и проверки согласно settling gate из `MODEL_ROUTING.md`.
8. Документация обновляется, если изменён контракт, запуск или пользовательский workflow.

---

## 1. Сводный backlog

| ID | Задача | Priority | Status | Proposed route | Depends on |
|---|---|---:|---|---|---|
| R02-01 | Startup migrations + schema readiness gate | P0 | DONE | Luna High / — / Terra High | — |
| R02-02 | Контракт opening YTD gross для НДФЛ | P0 | READY | Sol High / — / Terra High | — |
| R02-03 | Реализация opening YTD gross для НДФЛ | P0 | BLOCKED | Terra High / Luna High optional / Terra High | R02-02 |
| R02-04 | Passive-income invariants и защита от double count | P0 | READY | Terra High / DeepSeek Free optional / Terra High | — |
| R02-05 | Localhost Host/Origin protection | P1 | READY | Sol High / Luna High bounded worker / Sol High | — |
| R02-06 | Убрать внешние Google Fonts / true-offline UI | P2 | READY | Luna High / DeepSeek Free optional / Luna | — |
| R02-07 | Убрать финансовые вычисления через JS `Number` | P1 | READY | Luna High / DeepSeek Free bounded worker / Terra High spot review | — |
| R02-08 | Windows production smoke в CI | P1 | READY | Luna High / DeepSeek Free optional / Luna | R02-01 |
| R02-09 | Безопасная сериализация backup restore на Windows | P1 | READY | Terra High / Luna High bounded worker / Terra High | — |
| R02-10 | SQLite lock hardening (`busy_timeout`/WAL decision) | P2 | DEFERRED | Luna High / — / Terra only if semantics change | — |
| R02-11 | Goals API + единый source of truth основной цели | P1 | READY | Terra High / Luna High bounded worker / Terra High | — |
| R02-12 | Контракт и backend прогноза даты достижения цели | P1 | BLOCKED | Sol High / Terra High bounded worker / Sol High | R02-11 |
| R02-13 | Полноценный Goals UI + прогресс основной цели на Dashboard | P1 | BLOCKED | Luna High / DeepSeek Free optional / Luna | R02-11, R02-12 |
| R02-14 | Зафиксировать левую панель на desktop | P2 | READY | Luna High / DeepSeek Free optional / Luna | — |
| R02-15 | Accounts & Instruments UI вместо placeholder | P2 | READY | Luna High / DeepSeek Free optional / Luna | — |
| R02-16 | Settings UI baseline вместо placeholder | P2 | READY | Luna High / DeepSeek Free optional / Luna | — |
| R02-17 | Tax brackets administration contract/API/UI | P2 | DEFERRED | Terra High / Luna High bounded worker / Terra High | R02-16 |

`Proposed route` означает `primary / worker / reviewer`. Владелец может явно переопределить маршрут при запуске task-card; escalation gate из `MODEL_ROUTING.md` остаётся обязательным.

---

# R02-01. Startup migrations + schema readiness gate

**Priority:** P0  
**Status:** DONE  
**Route:** Luna High / — / Terra High reviewer

## Проблема

Production launcher строит frontend и запускает API, но штатный путь запуска не гарантирует `alembic upgrade head`. Health/root могут вернуть `200`, даже если SQLite существует без актуальной схемы. На clean install или после будущей миграции приложение может выглядеть «запущенным», а первый реальный DB endpoint упадёт.

## Сделать

- встроить применение/проверку Alembic migrations в канонический local startup;
- запуск должен оставаться локальным на `127.0.0.1`;
- readiness должен проверять не только HTTP-process, но и пригодность DB schema;
- повторный запуск на уже актуальной БД должен быть безопасным и идемпотентным;
- README update workflow должен соответствовать реальному поведению launcher.

## Не делать

- не использовать `Base.metadata.create_all()` как замену versioned migrations;
- не добавлять внешний installer/service/cloud database.

## Acceptance

- новая пустая local DB → standard launcher → `/api/months` работает без ручного `alembic upgrade`;
- существующая DB на head не повреждается и запускается повторно;
- тестовая DB на предыдущей revision обновляется до head;
- readiness не сообщает успех при schema mismatch/migration failure;
- regression test покрывает production startup contract настолько близко, насколько позволяет test harness.

---

# R02-02. Контракт opening YTD gross для НДФЛ

**Priority:** P0  
**Status:** READY  
**Route:** Sol High / — / Terra High reviewer

## Проблема

Расчёт прогрессивного НДФЛ суммирует gross только из существующих `reporting_months`. Если история приложения начинается не с января, ранее полученный в том же календарном году доход отсутствует из YTD и пороги налога сдвигаются.

## Сделать

До реализации зафиксировать один канонический способ задать taxable gross до первого месяца истории приложения, например opening YTD baseline/annual tax context.

Контракт должен определить:

- единицы и точный смысл opening value;
- привязку к календарному году;
- взаимодействие с импортированной историей, чтобы не возник double count;
- где хранится source of truth;
- как значение попадает из private/local seed без персональных данных в Git;
- поведение при добавлении более ранних reporting months;
- migration/backward compatibility для существующей `0.1.0` базы.

## Acceptance

- решение записано в `MASTER_SPEC.md` или отдельный принятый ADR/contract section;
- приведён контрольный пример: первая история начинается в мае, но YTD до мая ненулевой;
- реализация R02-03 может быть выполнена без самостоятельного придумывания финансовой семантики worker-моделью.

---

# R02-03. Реализация opening YTD gross для НДФЛ

**Priority:** P0  
**Status:** BLOCKED by R02-02  
**Route:** Terra High / Luna High optional worker / Terra High reviewer

## Сделать

- реализовать утверждённый R02-02 storage/domain/API/seed contract;
- salary-tax service должен учитывать opening YTD ровно один раз;
- private seed example остаётся синтетическим, реальные суммы — только локально;
- миграция существующей БД не должна выдумывать исторический доход.

## Acceptance

- первая reporting month = May, opening Jan–Apr gross задан → правильная tax bracket progression;
- Jan–Apr присутствуют как реальные reporting months → opening не дублирует их;
- переход через порог внутри выплаты остаётся корректным;
- `Decimal`/minor units/`ROUND_HALF_UP` invariants сохранены.

---

# R02-04. Passive-income invariants и защита от double count

**Priority:** P0  
**Status:** READY  
**Route:** Terra High / DeepSeek Free optional tests worker / Terra High reviewer

## Проблема

Сейчас `salary`, `bonus` и `side_income` технически могут получить `include_in_passive_income=true`. `cash_balance` отдельно учитывает активный доход и затем добавляет passive income, поэтому такая запись может попасть в итог дважды. Дополнительно generic `investment_cash_flows.interest` не должен автоматически маркироваться как deposit interest, если фактический процент депозита берётся из `deposit_snapshots.actual_interest_received`.

## Сделать

- enforce business invariant: salary/bonus/side income/cashback не являются passive income;
- passive flag нельзя сохранить в несовместимом состоянии ни create, ни update путём;
- устранить double-count в monthly cash balance даже для legacy/invalid data;
- проверить mapping `investment_cash_flows.interest` к корректному passive-income bucket;
- не дублировать фактический процент депозита между двумя источниками.

## Acceptance

- type-matrix tests на все income types;
- update income type не позволяет оставить запрещённый passive flag;
- cash balance regression подтверждает отсутствие двойного учёта;
- deposit actual interest учитывается ровно из канонического источника;
- passive breakdown имеет семантически правильные buckets.

---

# R02-05. Localhost Host/Origin protection

**Priority:** P1  
**Status:** READY  
**Route:** Sol High / Luna High bounded worker / Sol High reviewer

## Контекст

Приложение сознательно single-user, без auth и слушает только `127.0.0.1:8000`. Это решение не меняется. При этом отсутствие CORS само по себе не является защитой от всех cross-origin write requests к localhost.

## Сделать

- зафиксировать allowlist `Host` для local production (`127.0.0.1`, при необходимости `localhost`, с ожидаемым port behavior);
- unsafe HTTP methods принимать только с ожидаемого own-origin contract; dev-origin (`Vite`) поддержать явно, а не wildcard;
- сохранить API удобным для штатного local UI;
- добавить security regression tests для чужого Host/Origin и разрешённого local flow.

## Не делать

- auth/login/accounts;
- cloud/VPS/HTTPS reverse proxy;
- wildcard CORS.

## Acceptance

- обычный local UI продолжает работать;
- чужой Host/Origin не может выполнить state-changing request;
- GET/read-only contract не становится случайно недоступным штатному UI;
- security assumptions документированы.

---

# R02-06. Убрать внешние Google Fonts / true-offline UI

**Priority:** P2  
**Status:** READY  
**Route:** Luna High / DeepSeek Free optional / Luna reviewer

## Сделать

- удалить runtime requests к `fonts.googleapis.com`/`fonts.gstatic.com`;
- использовать system font stack или локально поставляемые assets без внешнего запроса;
- сохранить визуальную иерархию и layout без заметной деградации.

## Acceptance

- production page не делает обязательных внешних network requests для шрифтов;
- frontend build/tests green;
- приложение визуально приемлемо offline.

---

# R02-07. Убрать финансовые вычисления через JS `Number`

**Priority:** P1  
**Status:** READY  
**Route:** Luna High / DeepSeek Free bounded worker / Terra High spot review

## Проблема

Backend следует `Decimal`/integer minor-unit contract, но frontend helper/chart code местами преобразует денежные строки в JS `Number` и самостоятельно суммирует/вычисляет доли.

## Сделать

- финансовые суммы и derived values получать готовыми из backend там, где это публичный финансовый показатель;
- для необходимой frontend агрегации использовать integer minor units/`BigInt` или иной exact representation;
- `Number` допускается только на последней границе визуализации chart geometry, когда точное значение уже посчитано и не становится source of truth;
- документировать эту boundary в helper tests/comments без дублирования backend formulas.

## Acceptance

- helper с комментарием «no binary float» фактически не использует `Number` для денежных вычислений;
- asset allocation total/share не выводятся из неточной финансовой арифметики клиента;
- Recharts получает числа только как presentation boundary;
- frontend tests на крупные суммы и копейки.

---

# R02-08. Windows production smoke в CI

**Priority:** P1  
**Status:** READY  
**Route:** Luna High / DeepSeek Free optional / Luna reviewer

## Сделать

Добавить небольшой Windows job/smoke, ориентированный на реальный product contract, не дублируя весь Linux CI:

- install минимально нужных зависимостей;
- production frontend build;
- clean local DB startup через канонический launcher или максимально близкий эквивалент;
- schema/migration check из R02-01;
- `/api/health`, `/`, один DB endpoint;
- корректное завершение процесса.

## Acceptance

- Windows job запускается на `windows-latest`;
- clean install path проверяется автоматически;
- job не требует private seed/real DB.

---

# R02-09. Безопасная сериализация backup restore на Windows

**Priority:** P1  
**Status:** READY  
**Route:** Terra High / Luna High bounded worker / Terra High reviewer

## Проблема

Restore валидирует backup и делает pre-restore copy, но замена SQLite-файла может пересечься с активным request/session. `engine.dispose()` не является гарантией отсутствия checked-out connections; на Windows открытые handles особенно важны.

## Сделать

- определить и реализовать application-level serialization/maintenance guard для restore;
- во время критической секции новые DB операции не должны стартовать или должны fail predictably;
- существующие активные DB операции должны быть корректно завершены/остановлены до file replace;
- сохранить pre-restore backup и validation contract.

## Acceptance

- integration test моделирует конкурирующий DB access вокруг restore;
- restore либо безопасно сериализуется, либо возвращает понятный conflict, не оставляя DB в промежуточном состоянии;
- сценарий ориентирован на Windows filesystem semantics;
- после restore приложение снова читает новую БД.

---

# R02-10. SQLite lock hardening (`busy_timeout`/WAL decision)

**Priority:** P2  
**Status:** DEFERRED

## Контекст

Single-user SQLite сейчас достаточен. Не нужно заранее усложнять архитектуру без воспроизводимого `database is locked` сценария.

## Возобновить, если

- появится реальная конкуренция нескольких write requests;
- тесты или пользовательский workflow воспроизводят lock errors.

Тогда отдельно оценить `busy_timeout`, WAL и transaction boundaries. Не включать PostgreSQL/VPS как «решение» локальной проблемы.

---

# R02-11. Goals API + единый source of truth основной цели

**Priority:** P1  
**Status:** READY  
**Route:** Terra High / Luna High bounded worker / Terra High reviewer

## Текущее состояние

Persistence/service для `goals` уже существуют, включая `list/create/update/delete` и helper основной passive-income goal, но HTTP router `/api/goals` не подключён. Текущий helper фактически выбирает первый passive-income goal, а settings и goals не должны становиться двумя независимыми runtime source of truth.

## Сделать

- проверить текущую schema/migrations/service перед изменениями;
- закрепить `goals` как runtime source of truth значений целей;
- обеспечить **явный persisted contract выбора одной основной цели**, а не зависимость от «первой строки»/порядка ID;
- не дублировать target value в новом независимом runtime storage;
- сохранить backward compatibility существующего settings passive-income target как seed/default или согласованный compatibility path;
- добавить router и DTO:
  - `GET /api/goals` — список;
  - `POST /api/goals` — создание;
  - `PATCH /api/goals/{id}` — изменение;
  - `DELETE /api/goals/{id}` — удаление;
  - endpoint/action для выбора основной цели либо однозначное поле существующего PATCH contract;
- money values в API — decimal strings согласно общему контракту;
- определить поведение удаления/деактивации основной цели.

## Acceptance

- router зарегистрирован в FastAPI;
- CRUD и validation покрыты integration tests;
- одновременно существует не более одной однозначно выбранной основной цели;
- main goal selection переживает restart;
- изменение не создаёт competing target между settings и goals;
- existing DB мигрируется без потери текущей passive-income цели.

---

# R02-12. Контракт и backend прогноза даты достижения цели

**Priority:** P1  
**Status:** BLOCKED by R02-11  
**Route:** Sol High / Terra High bounded worker / Sol High reviewer

## Почему отдельная задача

«Прогнозная дата достижения» — не просто UI. Дата зависит от допущений: какой показатель растёт, используются ли регулярные взносы, доходность, forecast passive income, trailing average, target date и т.д. Worker не должен молча выбрать формулу.

## Сделать

1. Для каждого поддерживаемого goal type определить, существует ли вообще осмысленный forecast.
2. Зафиксировать входные данные, assumptions, units, rounding и insufficient-data behavior.
3. Не обещать точную дату, если данных недостаточно: API должен уметь вернуть `null` + reason/warning.
4. Реализовать backend-derived forecast только после фиксации контракта.
5. Frontend не рассчитывает дату сам.

## Acceptance

- формула/методика задокументирована и versioned, если влияет на финансовую интерпретацию;
- deterministic unit tests на контрольные сценарии;
- `null`/warning при невозможности честного прогноза;
- goal DTO/summary отдаёт готовое значение для UI.

---

# R02-13. Полноценный Goals UI + прогресс основной цели на Dashboard

**Priority:** P1  
**Status:** BLOCKED by R02-11, R02-12  
**Route:** Luna High / DeepSeek Free optional / Luna reviewer

## Сделать

### Страница «Цели»

- убрать placeholder;
- показать список active/inactive goals;
- создать цель;
- изменить название, тип, target value, target date и разрешённые параметры;
- удалить/деактивировать с безопасным UX;
- выбрать основную цель;
- loading/error/empty states.

### Dashboard

Для основной цели показывать готовые backend values:

- текущая сумма/текущее значение;
- целевая сумма;
- процент выполнения;
- прогнозная дата достижения или честный `нет прогноза`/warning;
- понятный переход к странице целей.

## Acceptance

- никаких hardcoded `100 000 ₽` как runtime source;
- percentage/current/forecast не пересчитываются собственной финансовой формулой React;
- выбор основной цели сразу отражается на Dashboard;
- component/integration tests на CRUD, main selection и dashboard states;
- mobile/desktop layout не ломается.

---

# R02-14. Зафиксировать левую панель на desktop

**Priority:** P2  
**Status:** READY  
**Route:** Luna High / DeepSeek Free optional / Luna reviewer

## Сделать

- на desktop sidebar остаётся видимым при вертикальной прокрутке контента;
- основной контент справа скроллится независимо/естественно;
- сохранить текущую ширину, визуальную иерархию и active navigation;
- на узком viewport не заставлять fixed desktop sidebar ломать layout: оставить normal flow или существующий compact/mobile pattern;
- проверить viewport минимум 1366×768 и Full HD плюс узкий экран.

## Acceptance

- длинная Dashboard/Month page прокручивается, navigation остаётся доступной на desktop;
- нет horizontal overflow из-за sidebar;
- keyboard focus/navigation не ухудшены;
- component/layout tests обновлены при необходимости.

> Внешняя UI-модель, подключённая владельцем, может быть назначена bounded worker этой задачи только явным override route и в отдельной ветке/worktree. Пока она не добавлена в `MODEL_ROUTING.md`, это не канонический default route.

---

# R02-15. Accounts & Instruments UI вместо placeholder

**Priority:** P2  
**Status:** READY  
**Route:** Luna High / DeepSeek Free optional / Luna reviewer

## Контекст

Backend CRUD счетов и инструментов уже в основном существует; главный gap — полноценная пользовательская страница.

## Сделать

- убрать placeholder `/accounts`;
- список счетов и инструментов с понятным разделением;
- create/edit/delete или deactivate/hide согласно существующему backend contract;
- показать важные флаги (`include_in_capital`, `include_in_returns`, status/type) без придумывания новой финансовой семантики;
- client validation должна дополнять, а не заменять server validation;
- loading/error/empty states.

## Acceptance

- основные CRUD операции доступны без ручного API;
- existing backend semantics не меняются «ради формы»;
- duplicate/validation errors отображаются понятно;
- UI tests покрывают базовый happy path и error state.

---

# R02-16. Settings UI baseline вместо placeholder

**Priority:** P2  
**Status:** READY  
**Route:** Luna High / DeepSeek Free optional / Luna reviewer

## Сделать

- подключить существующий `/api/settings`;
- убрать placeholder `/settings`;
- показывать и редактировать только уже определённые безопасные настройки;
- passive-income target не должен становиться вторым source of truth в обход R02-11;
- явно отделить настройки, для которых backend contract пока отсутствует.

## Не делать

- не придумывать UI редактирования tax brackets до R02-17;
- не добавлять auth/cloud/telemetry preferences.

## Acceptance

- settings читаются/сохраняются через backend;
- validation/errors видны пользователю;
- изменение совместимых goal settings соблюдает source-of-truth contract R02-11.

---

# R02-17. Tax brackets administration contract/API/UI

**Priority:** P2  
**Status:** DEFERRED  
**Route:** Terra High / Luna High bounded worker / Terra High reviewer

Tax brackets уже участвуют в чувствительной налоговой логике, поэтому отсутствие UI не следует закрывать обычным CRUD «на глаз». Возобновить отдельно, если владельцу реально нужно ручное управление ставками из приложения.

Перед implementation определить:

- source/version/effective dates правил;
- можно ли редактировать прошлые tax rules;
- связь изменения rules с уже закрытыми месяцами;
- API validation и audit expectations.

---

# 2. Release Gate перед `0.2.0`

Перед созданием tag/release `0.2.0` выполнить отдельный release checkpoint.

## Обязательный gate

- [ ] Все **P0** task-cards имеют статус `DONE`.
- [ ] Нет открытых blocker/high findings по финансовой корректности, миграциям или риску потери данных.
- [ ] Backend canonical test suite green.
- [ ] Frontend tests/lint/build green.
- [ ] Windows production smoke green.
- [ ] Clean install: пустая DB → standard launcher → рабочий DB endpoint.
- [ ] Upgrade smoke: schema/data `0.1.0` → current Alembic head → приложение стартует и читает данные.
- [ ] Regression tests финансовых invariants (`Decimal`, rounding, passive-income exclusions, tax YTD) green.
- [ ] Backup create → validate → restore smoke green.
- [ ] Privacy check: никаких private DB/seed/export/backup/financial payload в Git/logs; приложение по умолчанию остаётся local-only.
- [ ] Host/Origin security contract проверен для production local flow.
- [ ] `MASTER_SPEC.md`, `README.md`, `PROJECT_WIKI.md` и `CHANGELOG.md` актуальны для фактического поведения.
- [ ] Все `DEFERRED` задачи явно перечислены как non-blocking known follow-ups.
- [ ] **Sol High release review** выполнен на exact candidate `HEAD`: blocker-level review без автоматического broad rewrite.
- [ ] После review исправления, если были, снова прошли релевантные проверки; зафиксирован exact final `HEAD`.
- [ ] Только после этого создаётся `v0.2.0`.

## Release review route

**Primary/reviewer:** Sol High.  
**Worker:** не нужен по умолчанию; найденные bounded fixes запускаются как отдельные task-cards/iterations соответствующего класса риска.

---

# 3. Параллельная работа агентов

Для `0.2.0` допускается несколько исполнителей, но не параллельное редактирование одного и того же контракта.

- У каждой активной write-задачи должен быть один owner/primary.
- Параллельные workers работают в отдельных branch/worktree/session.
- Нельзя одновременно менять одну migration, shared domain model, `main.py` routing block, общий financial helper или один frontend layout subtree без заранее определённого порядка интеграции.
- Хороший параллелизм: один агент делает backend invariant, другой — независимый UI component/ticket.
- Плохой параллелизм: два агента одновременно «улучшают Goals», sidebar/layout или одну и ту же tax/passive-income семантику.
- Интегрировать изменения последовательно; следующий diff ревьюится уже относительно нового HEAD.
- Отчёт модели не заменяет diff/tests review primary.

Это правило дополняет, а не отменяет `MODEL_ROUTING.md`.
