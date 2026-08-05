# Маршрутизация моделей и launch gate

> **Статус:** обязательный проектный протокол. Маршруты ниже — решение владельца о расходовании лимитов и классе риска, а не универсальный рейтинг моделей. Фактическая модель и reasoning level подтверждаются runtime metadata.

## Обязательный launch gate

До начала **каждой** backlog-задачи агент обязан:

1. прочитать этот файл, точную карточку из `HERMES_TASKS.md` и связанные ADR/спецификацию;
2. предложить владельцу route в форме `primary / worker / reviewer`, указав reasoning level, причину и необходимость делегирования;
3. дождаться выбора владельца; не начинать задачу и не менять Hermes-конфиг заранее;
4. после завершения задачи указать рекомендуемый route следующей задачи и явно отметить её как не начатую.

Маршрут определяется уже зафиксированным контрактом. Luna или DeepSeek могут реализовать финансовую сущность, если единицы, формулы, округление и инварианты однозначно заданы спецификацией и тестами. Если контракт неоднозначен или конфликтует с документами, реализация останавливается и решение поднимается на Terra либо Sol.

## Экономная политика до сброса лимитов

- Не использовать Sol для обычного CRUD, UI, тестов, документации и механического рефакторинга.
- **Luna High** — основной исполнитель стандартной реализации, включая schema/CRUD по готовому контракту.
- **Terra High** — сложная финансовая семантика, налоги, потоки и расчёты, где требуется сильное рассуждение, но архитектура уже задана.
- **DeepSeek V4 Flash Free** — бесплатная альтернатива для bounded implementation/review стандартных задач. Write-задача выполняется только в изолированном worktree/session, без private seed, commit и push; её diff и проверки независимо принимает primary.
- **Sol High** — новые архитектурные контракты, конфликтующие требования, риск потери/переинтерпретации данных и редкие архитектурные checkpoint review.
- После `B19` провести один архитектурный обзор на Sol High. Это review существующей реализации, а не разрешение переписать код без blocker-level причины.

## Уровни и роли

| Уровень | Модель/route | Допустимая роль |
|---|---|---|
| High | GPT-5.6 Sol | новые архитектурные решения, конфликтующие финансовые контракты, destructive migration semantics, privacy/auth, архитектурный checkpoint |
| High | GPT-5.6 Terra | сложная bounded backend/domain implementation, налоги, финансовые потоки и формулы по утверждённой архитектуре |
| High | GPT-5.6 Luna | основной исполнитель schema/CRUD/API/frontend, графиков, форм, тестов, документации и локального рефакторинга |
| Внешний, free | DeepSeek V4 Flash Free — `custom:open.cherryin.ai` / `deepseek/deepseek-v4-flash(free)` | bounded implementation или review стандартной задачи под независимой приёмкой primary |

Для бесплатного route использовать `custom:open.cherryin.ai` / `deepseek/deepseek-v4-flash(free)`. `delegate_task` не умеет выбрать этот route на один вызов; точная модель требует отдельной session/profile или bounded Hermes one-shot с runtime confirmation.

## Утверждённые routes фазы B

| Задача | Primary | Worker / альтернатива | Reviewer | Основание |
|---|---|---|---|---|
| B01 SQLite | Luna High | — | Luna self-review | стандартная persistence-инфраструктура; завершена |
| B02 Alembic | Luna High | — | Luna self-review | service migration baseline; завершена |
| B03 money/rates | Sol High | — | Sol self-review | фундаментальный контракт единиц и округления; завершена |
| B04 app settings | Luna High | DeepSeek Free допустим | Luna | singleton/defaults и обычный API по готовому money contract |
| B05 reporting months | Luna High | DeepSeek Free допустим | Terra только при споре об immutability | period/snapshot/status CRUD; closed-month contract уже задан |
| B06 accounts | Luna High | DeepSeek Free допустим | Luna | справочник и ограничения |
| B07 IIS | Terra High | Luna High по закрытому контракту | Terra | налоговая семантика и статусы вычетов |
| B08 instruments | Luna High | DeepSeek Free как альтернатива | Luna | справочник и uniqueness ISIN |
| B09 positions | Terra High | Luna High по закрытому контракту | Terra | market value, cost basis и результат |
| B10 deposits | Luna High | DeepSeek Free как альтернатива | Terra только при конфликте формулы | формула и ROUND_HALF_UP уже закреплены |
| B11 cash/liquid assets | Luna High | DeepSeek Free как альтернатива | Luna | простые агрегаты без нового контракта |
| B12 incomes | Luna High | DeepSeek Free как альтернатива | Terra только при конфликте passive-income rules | правила cashback/gross/tax/net уже заданы |
| B13 investment flows | Terra High | Luna High по закрытому контракту | Terra | tax/commission/net и классификация событий |
| B14 expected flows | Terra High | Luna High по закрытому контракту | Terra | forecast semantics и versioned snapshots |
| B15 expenses/savings | Luna High | DeepSeek Free как альтернатива | Luna | стандартные сущности и суммы по готовым правилам |
| B16 debts | Luna High | DeepSeek Free как альтернатива | Luna | простой вычет долга из капитала |
| B17 property/mortgage | Luna High | DeepSeek Free как альтернатива | Terra только при новом контракте | formula contract и zero-division behavior уже заданы |
| B18 goals | Luna High | DeepSeek Free как альтернатива | Luna | конфигурируемые цели без UI hardcode |
| B19 comments | Luna High | DeepSeek Free как альтернатива | Luna | упорядоченный CRUD без финансовой логики |
| checkpoint после B19 | Sol High | — | Sol | один blocker-level архитектурный обзор без автоматического rewrite |

## Routes для следующих слоёв

- Почти весь обычный CRUD API: **Luna High**; Terra только если endpoint вводит новую финансовую семантику.
- React UI, графики, формы, TanStack Query wiring и component tests: **Luna High**.
- Boilerplate tests, fixtures, документация и мелкий локальный рефакторинг: **Luna High** или **DeepSeek Free**.
- Расчётный слой, налоги и классификация денежных потоков: по умолчанию **Terra High** после Sol checkpoint; Sol подключается только к новому/конфликтующему контракту.
- Импорт/экспорт реальных данных, auth/VPS и destructive migration остаются отдельным launch gate по наивысшему риску.

## Делегирование в Hermes

- `delegate_task` не принимает provider/model на один вызов.
- Пустые `delegation.provider/model` означают наследование route родителя; нельзя приписывать ребёнку модель без runtime confirmation.
- Для гарантированного Luna/Terra/DeepSeek route использовать отдельную session/profile или bounded Hermes one-shot с явно выбранными provider/model и level.
- Изменение `config.yaml`, default model или общей delegation route выполняется только после отдельного согласования владельца.
- Read-only research может идти в общей рабочей копии. Любой write-worker использует изолированный worktree/session и не делает commit/push.
- Несколько агентов не изменяют параллельно одну миграцию, shared domain model, dependency manifest или один frontend subtree.
- Отчёт worker/reviewer не является доказательством: принимающий primary читает фактический diff и запускает проверки самостоятельно.

## Escalation gate

Luna/DeepSeek останавливаются и поднимают задачу на Terra или Sol, если:

- спецификация и backlog конфликтуют;
- единицы денег/ставок, rounding или источник истины не определены;
- миграция может потерять или переинтерпретировать существующие данные;
- требуется private seed;
- формула меняет tax, return, passive income, capital или goal progress вопреки готовому контракту;
- тест падает за пределами заявленного scope;
- задача незаметно добавляет auth, cloud, telemetry или будущую функциональность.

## Settling gate и единственный итог

После implementation агент не пишет пользователю «готово», пока не завершены все этапы:

1. targeted checks и пропорциональный canonical suite;
2. полный diff/scope/privacy review;
3. разрешённые commit, push и проверка CI точного `HEAD`, если они входят в iteration contract;
4. обработка verification guard: при требовании — отдельный временный `hermes-verify-*` probe через OS-safe tempfile, запуск, явная очистка и повторный state check;
5. финальный read-back: `HEAD`, `origin`, clean status, CI/probe result и отсутствие временных файлов;
6. короткий settling checkpoint после последнего tool result — убедиться, что не пришёл новый guard/error и не осталось side effects;
7. только затем один отчёт с явной меткой **«Канонический итог»**.

До канонического итога допустимы только progress-сообщения без слова «готово». После него не посылать второй итог или уточняющий дубль, если пользователь сам не попросил.

## Частота обновления сессий

Не открывать новую сессию механически после каждой задачи. Session boundary нужен при смене primary model, после принятой schema/migration boundary, долгого расследования, сжатого неоднозначного контекста или перед Sol checkpoint. Для серии близких Luna-задач допустимы 2–3 задачи в одной сессии, но launch gate и явный выбор владельца сохраняются перед каждой.
