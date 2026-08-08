# Finance Dashboard — Project Wiki

> Живой контекст проекта для длительной разработки. Обновлять после принятых архитектурных и продуктовых решений, но не дублировать сюда весь backlog и не помещать персональные финансовые данные.

## 1. Что мы строим

Локальное однопользовательское веб-приложение для ежемесячного ведения личных финансов. Оно заменяет текущую Excel-модель, хранит финансовые снимки по отчётным месяцам и показывает:

- ликвидный капитал после краткосрочных долгов;
- динамику капитала;
- фактический и прогнозный чистый пассивный доход;
- прогресс к цели пассивного дохода;
- покрытие обязательных расходов;
- инвестиционный результат без ложного смешения с денежными потоками;
- показатели ИИС и полученной налоговой выгоды;
- справочную стоимость недвижимости и покрытие ипотеки ликвидными активами.

Приложение не является бухгалтерской, налоговой или торговой системой.

## 2. Источники истины

При конфликте документов использовать такой приоритет:

1. `MASTER_SPEC.md` — бизнес-правила, границы продукта и архитектурные решения.
2. `HERMES_TASKS.md` — порядок и scope отдельных задач.
3. `HERMES_START_PROMPT.md` — рабочий протокол одной итерации.
4. `IDEA.md` — исходная краткая идея, не подробная спецификация.
5. Этот wiki — принятые уточнения, открытые вопросы и долговременный контекст.

`PRIVATE_SEED_NOT_FOR_GIT.md` содержит только локальные персональные данные. Его нельзя коммитить, цитировать в публичных документах, тестах, логах и примерах.

Проектные документы хранятся в `docs/`, ADR — в `docs/adr/`, а локальный private seed — в исключённом из Git каталоге `private/`.

## 3. Зафиксированные границы MVP 0.1

### Входит

- Windows-first локальный запуск, браузерный UI, SQLite;
- один пользователь без авторизации;
- ручной месячный ввод и клонирование предыдущего месяца;
- счета, позиции, депозиты, cash, золото/другие ликвидные активы;
- доходы, расходы, savings, долги, недвижимость, ипотека, ИИС и цели;
- расчёты на backend;
- dashboard, Markdown/JSON export, backup/restore;
- разовая проверяемая миграция истории из Excel.

### Не входит

- торговые операции;
- автоматические банковские транзакции;
- автоматические котировки и PDF-импорт до следующих версий;
- облачный сервис, VPS, авторизация и многопользовательский режим;
- фоновая телеметрия и фоновые обновления;
- универсальный импортёр любого Excel;
- точная доходность до реализации датированных потоков и Modified Dietz.

## 4. Зафиксированный технический контур

- Backend: Python, FastAPI, SQLAlchemy 2, Alembic, Pydantic.
- Хранилище MVP: SQLite с включёнными foreign keys.
- Frontend: React, TypeScript, Vite, React Router, TanStack Query, Recharts, Tailwind CSS и простые UI-примитивы.
- Тесты: pytest, Vitest/Testing Library, минимальные Playwright-сценарии.
- Доменная логика отделяется от API и UI.
- Frontend получает рассчитанные финансовые показатели и не дублирует формулы.
- Локальный backend по умолчанию слушает только `127.0.0.1`.

## 5. Неприкосновенные бизнес-инварианты

Без явного решения владельца нельзя:

- использовать binary `float` для денег;
- включать кэшбэк в пассивный доход;
- включать недвижимость в ликвидный капитал;
- считать погашение номинала облигации доходом;
- называть изменение стоимости портфеля доходностью без учёта внешних потоков;
- прибавлять планируемый, но ещё не полученный вычет ИИС к фактическому результату;
- доверять рассчитанным значениям, присланным frontend;
- коммитить реальные номера счетов, базы, PDF, Excel, exports и backups;
- добавлять авторизацию, облако, фоновые котировки или торговые действия в MVP.

## 6. Масштаб roadmap

Backlog содержит 112 задач:

| Фаза | Задач | Смысл |
|---|---:|---|
| A | 7 | каркас, инструменты и GitHub Actions CI |
| B | 19 | база и доменная модель |
| C | 10 | расчётный слой |
| D | 8 | API |
| E | 18 | frontend MVP |
| F | 10 | export, backup и миграция Excel |
| G | 8 | системная проверка и выпуск 0.1 |
| H | 6 | котировки MOEX |
| I | 12 | PDF Альфа-Инвестиций |
| J | 8 | точная доходность |
| K | 6 | позднее развитие |

Рабочее правило: одна задача backlog за итерацию; следующая не начинается автоматически. Контрольные точки из backlog сохраняются.

## 7. Принятые уточнения финансовых контрактов

1. **Деньги.** В БД денежные значения хранятся целым количеством minor units (для RUB — копеек). Доменная арифметика использует `Decimal`. API передаёт объект с ISO currency и decimal string в major units, например `{"amount": "1234.56", "currency": "RUB"}`. Преобразование в minor units явно использует `ROUND_HALF_UP` до ближайшей копейки; половинные значения округляются от нуля.
2. **Процентные ставки.** В БД ставки хранятся integer basis points. API передаёт decimal string в процентных пунктах: `"13.50"` означает 13,50%. На доменной границе значение преобразуется в `Decimal`; binary `float` не используется. Преобразование в basis points использует тот же `ROUND_HALF_UP` до ближайшего basis point.
3. **Мультивалютность MVP.** Исходная сумма и валюта сохраняются. Для включения в RUB-агрегаты хранится ручная RUB-оценка вместе с датой и источником курса. Автоматические FX-котировки в MVP не добавляются.
4. **Ожидаемые выплаты.** Прогнозный набор привязывается к отчётному месяцу и версии снимка прогноза. Минимальный контракт включает `reporting_month_id`, `source_as_of_date` и `forecast_version`; агрегаты используют выбранную актуальную версию и не смешивают снимки.
5. **Проценты по депозитам.** `deposit_snapshots.actual_interest_received` является единственным источником фактических процентов депозитов и накопительных счетов. `investment_cash_flows.interest` не дублирует эти суммы и используется для других инвестиционных процентных событий.
6. **Клонирование месяца.** `accounts` и `instruments` остаются глобальными справочниками. Клонируются только месячные snapshots, состояния и плановые значения; сами справочники не копируются.
7. **Закрытый месяц.** Любое изменение финансовых данных закрытого месяца запрещено до явного `reopen`. После повторного открытия редактирование снова разрешено, а время изменения фиксируется.
8. **Прогноз депозитов.** `balance × annual_rate / 12` маркируется как оценка, а не точное банковское начисление.
9. **Лицензия.** Не добавлять до решения владельца.
10. **Размер MVP.** Backlog не сокращать молча; рабочие вертикальные срезы оцениваются на контрольных точках.
11. **НДФЛ (C07).** Прогрессивная шкала хранится в конфигурационной таблице `tax_brackets` (пороги в копейках, ставки в basis points, верхняя граница может быть открытой) и редактируется без изменения кода. Официальные ставки 2025+ (ФЗ-176-ФЗ от 12.07.2024, источник https://www.nalog.gov.ru/rn77/news/tax_doc_news/15562179/): 13% до 2,4 млн ₽/год, 15% от 2,4 до 5 млн, 18% от 5 до 20 млн, 20% от 20 до 50 млн, 22% свыше 50 млн; ставка применяется только к части дохода внутри диапазона. Seed вставляется только для пустого года и не перезаписывает пользовательские правки. Алгоритм: YTD gross (SALARY строго более ранних месяцев того же года) → разбиение текущей выплаты по диапазонам → налог части = `Decimal(taxable) × rate_bps / 10000` с `ROUND_HALF_UP`; фактический net (employer) хранится отдельно от расчётного.
12. **ИИС-результат (C09, зафиксировано владельцем на launch gate).** `portfolio_result_without_tax_benefit` — накопленный с открытия счёта: unrealized (position_snapshots счёта на конец отчётного месяца) + все полученные купоны и дивиденды за всё время (net_amount) + весь realized PnL за всё время (realized_profit + realized_loss, убыток со знаком). Взносы, депозиты, выводы и погашения облигаций (redemption — возврат номинала, не доход) никогда не входят в результат. `portfolio_result_with_tax_benefit = without + received_tax_benefits`; planned/submitted показываются только в разбивке и не прибавляются; rejected игнорируется.

## 8. Стратегия работы с моделями

> Операционный источник истины — `docs/MODEL_ROUTING.md`. Перед каждым backlog launch он требует recommendation модели и явный выбор владельца; здесь остаётся только долговременная архитектурная договорённость.

### Рекомендация

Проектный skill полезен, но не как копия спецификации. Лучшее разделение:

- проектный `.hermes.md` или `AGENTS.md` — автоматически загружаемые правила репозитория: источники истины, приватность, одна задача за итерацию, команды проверок;
- skill `hermes-finance-orchestration` — процедурная маршрутизация задач между моделями, шаблон handoff и независимая проверка результатов;
- этот wiki и `MASTER_SPEC.md` — знания и решения проекта.

Skill разумно создавать после `A01`/`A02`, когда структура, команды и ADR стабилизированы. До этого он будет повторять черновые пути и быстро протухнет.

### Роли

| Уровень | Рекомендуемый владелец | Примеры |
|---|---|---|
| High | Sol 5.6 | новый/конфликтующий архитектурный контракт, destructive migration semantics, privacy/auth и редкие checkpoint reviews |
| High | Terra 5.6 | сложная финансовая семантика, налоги, потоки и формулы по утверждённой архитектуре |
| High | Luna 5.6 | основной исполнитель schema/CRUD/API/frontend, графиков, форм, тестов, документации и мелкого рефакторинга |
| Внешний, free | DeepSeek V4 Flash Free | bounded standard implementation в изоляции или review; без private seed, commit/push и финальной приёмки |

### Техническая реальность Hermes

- `delegate_task` сейчас не имеет per-call выбора модели; пустая настройка `delegation.model/provider` означает наследование модели родительской сессии.
- Для гарантированного Luna/Terra/DeepSeek route используется отдельная session/profile или bounded Hermes one-shot с подтверждёнными provider/model/level.
- Изменение общей delegation route или model default выполняется только после отдельного согласования владельца.
- Write-worker работает в изолированном worktree/session, не делает commit/push и не получает private seed; несколько агентов не редактируют одну миграцию/schema/subtree параллельно.
- Отчёт worker/reviewer не является доказательством: принимающий primary проверяет diff, scope, тесты и отсутствие приватных данных.
- До конца B19 стандартная работа максимально маршрутизируется на Luna High/DeepSeek Free, сложные финансовые задачи — на Terra High. После B19 выполняется один blocker-level архитектурный обзор на Sol High без автоматического переписывания кода.

### Состояние доступности моделей

- текущий runtime model и reasoning level фиксируются для каждой задачи и не считаются постоянным default;
- публичная документация Hermes не является доказательством сравнительной силы внутренних Sol/Terra/Luna tiers; проектная карта маршрутизации — решение владельца об уровне риска и расходовании лимитов;
- проверенный внешний free route: `custom:open.cherryin.ai` / `deepseek/deepseek-v4-flash(free)`;
- direct provider или configured route не доказывает, что конкретный child его использовал: нужна runtime confirmation;
- точная карта B01–B19, escalation rules и settling gate находятся в `docs/MODEL_ROUTING.md`.

После всех checks/commit/push/CI/guard retries агент делает финальный state read-back и короткий settling checkpoint, а затем отправляет один отчёт с меткой **«Канонический итог»**. До этого progress-сообщения не называют задачу готовой; последующие дубли итогов не отправляются без запроса владельца.

## 9. Протокол делегированной задачи

Каждый handoff должен содержать:

1. один ID из backlog и точный outcome;
2. связанные разделы `MASTER_SPEC.md`;
3. разрешённые файлы и запрет scope creep;
4. критерии приёмки и команды тестов;
5. запрет commit/push и доступа к приватным данным без явного разрешения;
6. требование перечислить изменённые файлы, команды и ограничения.

После возврата результата Sol обязана независимо проверить полный diff и реально запустить проверки.

## 10. Решения и открытые вопросы

### Принято

- Рабочее имя: Finance Dashboard / `hermes-finance`.
- Локальный репозиторий отделяется от родительского `hermes-dashboard` собственным `.git`.
- Удалённый хостинг: приватный GitHub-репозиторий `LTstripes/hermes-finance`.
- CI реализуется через GitHub Actions; прежнее упоминание GitLab CI в backlog заменено.
- Для общих правил разных агентов создан корневой `AGENTS.md`; знания проекта остаются в спецификации и wiki.
- Создан user-local skill `hermes-finance-orchestration` для маршрутизации Sol/Terra/Luna/DeepSeek, handoff и независимой приёмки.
- Финансовые контракты из раздела 7 одобрены владельцем.
- Backend использует Python 3.13: версия закреплена в `backend/.python-version`, чтобы editable install корректно работал с UTF-8 путями Windows.
- Frontend использует Node.js 22.22+, React 19, React Router 8, TypeScript, Vite и Vitest; `/api` проксируется только в локальный backend.
- Корневые PowerShell 5.1-compatible скрипты `scripts/dev.ps1` и `scripts/test.ps1` запускают общий dev stack и единый набор проверок; для локального `Restricted` policy README использует process-only `-ExecutionPolicy Bypass`.
- Python форматируется и проверяется Ruff; TypeScript/React/CSS — Biome. Biome выбран вместо ESLint TypeScript stack, потому что stable `typescript-eslint` не поддерживает закреплённый TypeScript 7 без принудительного обхода peer dependency.
- Корневые PowerShell-команды `scripts/lint.ps1` и `scripts/format-check.ps1` проверяют обе части проекта и ничего не форматируют автоматически.
- GitHub Actions CI состоит из независимых backend/frontend jobs на `ubuntu-latest`, использует только lockfile-зависимости и не обращается к локальной базе, private-файлам или secrets context.
- До B19 стандартные задачи экономно маршрутизируются на Luna High/DeepSeek Free, сложные финансовые задачи — на Terra High; Sol High используется для новых/конфликтующих контрактов и одного архитектурного checkpoint после B19.
- Итог по задаче отправляется один раз после settling gate: все side effects/CI/guard retries завершены, выполнен финальный state read-back, временные probes удалены.
- `A01`–`A07` и `B01`–`B07` выполнены по явному разрешению владельца и прошли локальную приёмку; `B08` автоматически не начинается.
- `B08`–`B12` выполнены по явному разрешению владельца (primary DeepSeek V4 Flash) и прошли локальную приёмку; `B13` автоматически не начинается.
- `instruments` — глобальный справочник: `instrument_type` из фиксированного набора, ISIN необязателен, но при заполнении уникален (нормализация в верхний регистр и strip; `NULL` может встречаться многократно), `nominal_value` хранится в копейках через `RubleAmount` и допускается только для неотрицательных значений, `currency` нормализуется в верхний регистр (дефолт `RUB`).
- `position_snapshots` — уникальность месяц+счёт+инструмент; `quantity` — `Numeric(18,6)` (дробные лоты допустимы); расчётные `market_value`/`cost_basis`/`unrealized_result` всегда пересчитываются сервисом по формуле спецификации §10.11 и не принимаются от вызывающего; `price_source` из `manual/moex/alfa_pdf`; `accrued_interest` необязателен и неотрицателен.
- `deposit_snapshots` — `expected_monthly_interest` всегда пересчитывается сервисом как `balance × annual_rate / 12` с `ROUND_HALF_UP`; `actual_interest_received` хранится отдельно и прогнозом не заменяется.
- `cash_balances` — простая сумма по месяцу через `total_cash()`; отсутствие данных трактуется как ноль; флаг `include_in_capital` фильтрует агрегат.
- `income_entries` — кэшбэк никогда не включается в passive income (инвариант): явный `include_in_passive_income=True` для `cashback` отклоняется; фактический `net_amount` может отличаться от расчётного `gross − tax` и не валидируется на равенство.
- `investment_cash_flows` — gross/tax/commission хранятся как неотрицательные абсолютные величины, а `net_amount` валидируется как `gross − tax − commission` и может быть отрицательным для отдельного tax/commission event. В passive income попадают только `interest`, `coupon`, `dividend` и `other`; `redemption`, `deposit`, `withdrawal`, комиссии, налоги и realised P/L исключены. Для account типов deposit/savings поток `interest` отклоняется: фактический процент — исключительно `deposit_snapshots.actual_interest_received`.
- `expected_cash_flows` привязаны к `reporting_month_id` и `forecast_version`; в рамках одной пары месяц+версия разрешена только одна `source_as_of_date`, поэтому агрегаты не смешивают прогнозные snapshots. Окно календаря — `[snapshot_date, snapshot_date + 1 year)`. При известном expected tax service валидирует `expected_net = gross − tax`; при неизвестном tax хранится `NULL`, net равен gross и флаг `is_approximate=true`. Redemption отображается в календаре, но исключён из forecast passive income.
- `expense_entries` и `saving_allocations` разделены: `total_mandatory_expenses()` считает только тип `mandatory`, `total_saving_allocations()` — отдельный агрегат; откладывание не является расходом для покрытия обязательных расходов, но уменьшает остаток месяца.
- `debts` — `total_included_debts()` вычитает только долги с `include_in_liquid_capital=true` (кредитка по умолчанию включена).
- `property_snapshots` — недвижимость не входит в liquid capital; `property_equity = value − mortgage`; `mortgage_coverage()` возвращает `None` вместо деления на ноль при нулевом остатке ипотеки (UI показывает «ипотека закрыта»).
- `goals` — глобальная справочная таблица (без привязки к месяцу); `get_or_create_main_goal()` создаётся из `app_settings.passive_income_goal_kopecks` с `calculation_mode="monthly_net_passive_income"`; цель не хардкодится в frontend.
- `monthly_comments` — несколько упорядоченных заметок месяца; `position >= 1`, уникальность (месяц, позиция), перестановка и удаление компактируют позиции двухфазным обновлением (обход UNIQUE-конфликта при сдвиге).
- Post-B19 Sol checkpoint выполнен на `8031aa6`: canonical suite и exact-HEAD GitHub CI зелёные, но ad-hoc probes воспроизвели четыре blocker-level gap — mixed-currency arithmetic без RUB valuation, изменение дочерних данных закрытого месяца, сохранение passive flag при update типа дохода на cashback и расхождение settings/main goal.
- До C01 обязательны две remediation-итерации: `B19-R1` фиксирует точный валютный/RUB valuation contract; `B19-R2` централизует closed-month guard, cashback invariant и единственный runtime source основной цели.
- Для C-слоя принят контур `ORM query/assembler → pure domain calculator → immutable domain result DTO → API mapping`. Новые финансовые формулы не принимают SQLAlchemy `Session` и не зависят от FastAPI/Pydantic/React.
- `goals` является runtime source of truth основной цели; `app_settings.passive_income_goal_kopecks` после seed используется как default/template, а не независимое конкурирующее значение.
- Явная команда владельца `начинаем <ID>` или `запускай <ID>` одновременно назначает задачу и одобряет её canonical model route из `MODEL_ROUTING.md`; оркестратор сам запускает exact per-run models без изменения shared config и останавливается при невозможности подтвердить runtime route.
- Composite write operations должны владеть одной транзакцией. Текущие CRUD commits не переписываются в checkpoint, но до D03 cloning и bulk import nested mutations должны поддерживать `flush` без самостоятельного commit.
- `C01`–`C10` выполнены по явному разрешению владельца (маршрутизация GLM 5.2 / DeepSeek V4 Flash через opencode-go по `MODEL_ROUTING.md`) и прошли локальную приёмку + exact-HEAD CI; `D01` автоматически не начинается.
- Block review фазы C выполнен Kimi k3 (`moonshotai/kimi-k3`, read-only, exact HEAD `67e99c3`): **0 блокеров, 9/9 критериев PASS**, 212 C-тестов зелёные, репозиторий не изменён. Четыре неблокирующих наблюдения: (1) C03-DTO не несёт warnings, слот в C10 пустой (осознанно, зафиксировано); (2) флаг `include_in_passive_income` широкий — SALARY/BONUS могут попасть в other_capital_income, соответствует §10.4; (3) C04: annual = avg×12, monthly = annual/12 — теоретическое ±1 коп. двойное округление, контракт не нарушен; (4) `get_or_create_default_tax_brackets` делает `session.commit()` внутри read-цепочки `calculate_salary_tax` — скрытый write; **deferred**: учесть при composite-транзакциях D-фазы (D03 clone) и при GET-эндпоинтах поверх monthly_summary.
- `D01`+`D02`+`D08` выполнены батчем по явному разрешению владельца: API месяцев CRUD + close/reopen + единый error-контракт `{"error": {code, message, details}}` (404/409/422/405 маппинг, логирование без финансовых payload); duplicate period → 409 через аддитивный `get_reporting_month_by_period` без изменения ValueError-контракта B-сервиса; `D03` автоматически не начинается.
- `D04`+`D05` выполнены батчем по явному разрешению владельца: CRUD-API accounts/instruments/iis (профиль, взносы, выгоды) с фильтрами active/hidden/status и pre-check дублей → 409; CRUD позиций и депозитов месяца с server-side пересчётом (B09/B10 не тронуты) и optimistic concurrency: миграция 0019 добавила `updated_at` в position/deposit snapshots (SQLite batch_alter_table), PATCH требует `If-Match` (нет → 428, устарел → 409 ConcurrencyError); общий `LookupError → 404` и `ConcurrencyError → 409` в errors.py. По замечанию DeepSeek-тестов: 404 для всех *NotFoundError-наследников вместо 500, дубли IIS → 409. Suite 406, `D03` автоматически не начинается.
- `D06` выполнен Grok 4.5 primary (xai-oauth): отдельные CRUD-API incomes / investment-flows / expected-flows / expenses / savings / debts / properties / comments (не универсальный endpoint); month-scoped list filters, enum validation, cashback≠passive, closed-month → 409, unified error contract; 8 API-тестов, suite 414. `D03`/`D07` автоматически не начинаются. Временный route фазы D: Grok 4.5 primary (OpenCode-квоты исчерпаны); Kimi — точечный reviewer по запросу.

### Требует ответа владельца

1. Выбрать лицензию или подтвердить отсутствие лицензии на первом этапе.


## 11. Журнал изменений wiki

- 2026-08-04 — создан первичный проектный контекст по `MASTER_SPEC.md`, `HERMES_TASKS.md`, `HERMES_START_PROMPT.md`, `IDEA.md` и локальному private seed; кодирование и `A01` не начинались.
- 2026-08-04 — создан приватный `LTstripes/hermes-finance`, выполнен каркас `A01`, принят ADR `0001`, GitLab CI заменён на GitHub Actions, а финансовые контракты уточнены владельцем.
- 2026-08-04 — добавлены корневой `AGENTS.md` и user-local skill `hermes-finance-orchestration`; следующий backlog `A03` не начат.
- 2026-08-04 — выполнен `A03`: создан минимальный FastAPI backend, env-settings, package dev-команда и pytest для `/api/health`; `A04` не начат.
- 2026-08-04 — выполнен `A04`: создан React/TypeScript/Vite frontend с router, Dashboard, health-индикатором, dev proxy и компонентными тестами; `A05` не начат.
- 2026-08-04 — выполнен `A05`: добавлены единые Windows-команды запуска и тестирования с dependency checks, readiness probe и очисткой дочерних процессов; `A06` не начат.
- 2026-08-05 — выполнен `A06`: добавлены Ruff и Biome, единые команды `lint`/`format-check`, а существующий scaffold приведён к зафиксированному формату; `A07` не начат.
- 2026-08-05 — выполнен `A07`: добавлен GitHub Actions CI для backend/frontend tests, lint, format-check и frontend build без зависимости от локальных финансовых данных; оба удалённых job успешно прошли, `B01` не начат.
- 2026-08-05 — выполнен `B01`: добавлены конфиг пути SQLite, SQLAlchemy 2 engine/session, обязательный `PRAGMA foreign_keys=ON`, создание каталога при local startup и изолированные тесты на временной БД; `B02` не начат.
- 2026-08-05 — выполнен `B02`: добавлены Alembic config, пустая service baseline migration, команды upgrade/downgrade и проверка новой временной SQLite до head; `B03` не начат.
- 2026-08-05 — выполнен `B03`: добавлены точные доменные типы RUB и процентной ставки, преобразования API string ↔ `Decimal` ↔ integer minor units, единое `ROUND_HALF_UP` и тесты запрета binary `float`; `B04` не начат.
- 2026-08-05 — выполнен `B04`: добавлены singleton `app_settings` с базовыми RUB/ru-RU/Europe/Moscow, целью 100 000 ₽ и версией формул, Alembic migration, `GET/PUT /api/settings`, точный money-object API и валидация; `B05` не начат.
- 2026-08-05 — выполнен `B05`: добавлены `reporting_months`, период отдельно от snapshot date, уникальность year+month, статусы draft/closed, source enum, Alembic migration и CRUD service с close/reopen guards; `B06` не начат.
- 2026-08-05 — выполнен `B06`: добавлены account type/status enums, `accounts` migration/model/service, capital/returns flags, nullable unique external code и unit-тесты frozen account/statuses; `B07` не начат.
- 2026-08-05 — выполнен `B07`: добавлены IIS profiles, contributions и tax benefits, статусы planned/submitted/received/rejected, точные суммы в копейках, FK/unique/check constraints и тест, исключающий planned benefit из received результата; `B08` не начат.
- 2026-08-06 — выполнен `B08`: добавлен справочник `instruments` (тип из фиксированного набора, ISIN/ticker/MOEX SECID, валюта, номинал в копейках, флаги `is_active` и `manual_price_allowed`, notes), миграция, CRUD-сервис с уникальностью ISIN при заполнении (нормализация в верхний регистр) и unit/migration тесты; API остаётся в фазе D (D04); `B09` не начат.
- 2026-08-06 — выполнен `B09`: добавлены `position_snapshots` (уникальность месяц+счёт+инструмент, `quantity` как `Numeric(18,6)`, расчётные market value/cost basis/unrealized result по спецификации §10.11 с пересчётом при изменении цены, `price_source`/`manual_adjustment`) с миграцией, сервисом и тестами; `B10` не начата.
- 2026-08-06 — выполнен `B10`: добавлены `deposit_snapshots` (deposit/savings, баланс и ставка в точных единицах, `expected_monthly_interest = balance × rate / 12` с `ROUND_HALF_UP`, фактический процент хранится отдельно) с миграцией, сервисом и тестами; `B11` не начата.
- 2026-08-06 — выполнен `B11`: добавлены `cash_balances` (сумма по месяцу через `total_cash()`, отсутствие данных = ноль, флаг `include_in_capital`) с миграцией, сервисом и тестами; `B12` не начата.
- 2026-08-06 — выполнен `B12`: добавлены `income_entries` (типы salary/bonus/side_income/cashback/other, gross/tax/net в копейках, фактический net не обязан равняться расчётному, кэшбэк исключён из passive income) с миграцией, сервисом и тестами; `B13` не начата.
- 2026-08-07 — выполнен `B13`: добавлены `investment_cash_flows` с complete type set, exact net validation (`gross − tax − commission`), исключением redemption/deposit/withdrawal/commission/tax/realised P/L из passive income и защитой от дублирования процентов deposit/savings; миграция, CRUD/query-сервис и unit-тесты; `B14` не начата.
- 2026-08-07 — выполнен `B14`: добавлены versioned `expected_cash_flows`, привязанные к отчётному месяцу и единой `source_as_of_date` на forecast version; календарная выборка `[snapshot_date, +1 year)`, known/unknown tax семантика с `is_approximate`, redemption остаётся в календаре, но исключён из forecast passive income; миграция, CRUD/query-сервис и unit-тесты; `B15` не начата.
- 2026-08-07 — выполнен `B15`: добавлены `expense_entries` (mandatory/comfortable/other) и `saving_allocations` с раздельными агрегатами сумм; откладывание не входит в покрытие обязательных расходов; миграция, CRUD-сервисы и unit-тесты; `B16` не начата.
- 2026-08-07 — выполнен `B16`: добавлены `debts` (credit_card/other), агрегат `total_included_debts()` для вычета из liquid capital; миграция, CRUD-сервис и unit-тесты; `B17` не начата.
- 2026-08-07 — выполнен `B17`: добавлены `property_snapshots`, сервисы `property_equity` и `mortgage_coverage` с защитой от деления на ноль при нулевой ипотеке; недвижимость не входит в liquid capital; миграция, CRUD-сервис и unit-тесты; `B18` не начата.
- 2026-08-07 — выполнен `B18`: добавлены `goals` с типами из спецификации, `get_or_create_main_goal()` создаётся из настроек (100 000 ₽/мес, `monthly_net_passive_income`); миграция, CRUD-сервис и unit-тесты; `B19` не начата.
- 2026-08-07 — выполнен `B19`: добавлены `monthly_comments` с позиционной упорядоченностью, перестановкой и компактированием позиций (двухфазное обновление против UNIQUE-конфликта); миграция, CRUD/move-сервис и unit-тесты; после B19 по маршрутизации следует Sol High checkpoint, `C01` не начат.
- 2026-08-07 — выполнен post-B19 Sol High architecture checkpoint: зафиксированы B19-R1/B19-R2 remediation gates, pure calculation boundary, routes C01–C10 и standing approval на автоматический exact-model launch по явной команде владельца; кодовые исправления и C01 не начаты.
- 2026-08-08 — выполнен `C01`: доменный расчёт ликвидного капитала после краткосрочных долгов (cash + deposits + securities + other liquid − included debts) с разбивкой по классам и тестами; `C02` не начат.
- 2026-08-08 — выполнен `C02`: фактический net passive income месяца (проценты депозитов из `deposit_snapshots.actual_interest_received` + купоны/дивиденды/other из `investment_cash_flows` без redemption/deposit/withdrawal; кэшбэк исключён) с разбивкой и тестами; `C03` не начат.
- 2026-08-08 — выполнен `C03`: средний пассивный доход за доступный период (rolling-окно последних ≤12 закрытых месяцев, среднее с `ROUND_HALF_UP`, warning при неполном окне) с переиспользованием окна в C04/C08; `C04` не начат.
- 2026-08-08 — выполнен `C04`: прогноз пассивного дохода на 12 месяцев (ожидаемые проценты депозитов + купоны net + дивидендный компонент из закрытой истории + other; redemption исключён; warning при неполной дивидендной истории) с `forecast_version` и тестами; `C05` не начат.
- 2026-08-08 — выполнен `C05`: покрытие обязательных расходов и прогресс к цели (`coverage_pct`, `goal_progress_pct`; нулевые знаменатели → `None`; цель — runtime source из `goals`; расходы — только mandatory) с warnings и тестами; `C06` не начат.
- 2026-08-08 — выполнен `C06`: денежный остаток месяца по §10.9 (`salary + bonus + side + cashback + passive − mandatory − other − savings`; кэшбэк отдельной строкой и никогда в passive; `other = total − mandatory`) с разбивкой и тестами; `C07` не начат.
- 2026-08-08 — выполнен `C07`: конфигурируемые налоговые ступени НДФЛ (таблица `tax_brackets` + миграция `0018_tax_brackets`, официальный seed по ФЗ-176-ФЗ, CRUD с overlap-валидацией), прогрессивный калькулятор (YTD gross → разбиение выплаты по ступеням, налог части с `ROUND_HALF_UP`), расчётный налог/net отдельно от фактического employer net; тесты перехода через порог; `C08` не начат.
- 2026-08-08 — выполнен `C08`: нормализованная премия (сумма BONUS net за окно ≤12 закрытых месяцев / 12, `ROUND_HALF_UP`, закрытый месяц без премии = ноль через LEFT JOIN; только аналитика, не в cash flow) и тесты; `C09` не начат.
- 2026-08-08 — выполнен `C09`: результат ИИС-счёта без налоговой выгоды и с ней (состав зафиксирован владельцем на launch gate — см. раздел 7 п.12; received benefits прибавляются, planned/submitted отдельно, rejected игнорируется, redemption/взносы не входят) с разбивкой и тестами; `C10` не начат.
- 2026-08-08 — выполнен `C10`: единый Monthly Summary DTO (KPI и разбивки C01–C09, дельты к предыдущему месяцу для liquid capital и фактического passive income, агрегация warnings, `calculation_version="v1"`, IIS-результаты по всем профилям) с тестами; раздел C завершён, `D01` не начат.
- 2026-08-08 — выполнен block review фазы C на Kimi k3 (read-only, exact HEAD `67e99c3`): 0 блокеров, 9/9 PASS, 212 C-тестов; четыре неблокирующих наблюдения зафиксированы, №4 (seed-commit в read-цепочке C07) отложен до D-фазы.
- 2026-08-08 — выполнен батч `D01`+`D02`+`D08`: API отчётных месяцев (CRUD, delete draft only), close/reopen с обязательной датой снимка, единый error-контракт и exception handlers (404/409/422/405, per-field validation details, логирование без финансовых payload), duplicate → 409 через аддитивный query-хелпер; 7 API-тестов, suite 348; `D03` не начат.
- 2026-08-08 — выполнен батч `D04`+`D05`: CRUD-API справочников (accounts/instruments/iis profile+contributions+benefits, фильтры status/active/tax_year, pre-check дублей → 409) и редакторов активов месяца (positions/deposits: server-side пересчёты из B09/B10, optimistic concurrency через `updated_at` + `If-Match`: миграция 0019, 428 без заголовка, 409 при устаревшем значении); общий LookupError → 404 (все NotFoundError-наследники), ConcurrencyError → 409; 58 API-тестов, suite 406; `D03` не начат.
- 2026-08-08 — выполнен `D06` (Grok 4.5 primary): API финансовых событий — 8 отдельных роутеров (incomes, investment-flows, expected-flows, expenses, savings, debts, properties, comments); month-scoped lists, enum validation, closed-month 409; 8 API-тестов, suite 414; `D03`/`D07` не начаты.
- 2026-08-05 — по решению владельца routing переписан на экономный режим Luna High/Terra High/DeepSeek Free, Sol оставлен для новых архитектурных контрактов и checkpoint после B19; добавлен settling gate с одним каноническим итогом.
