# Маршрутизация моделей и launch gate

> **Статус:** обязательный проектный протокол. Уровни ниже — рабочая классификация риска, а не маркетинговый рейтинг моделей. Любой фактический запуск подтверждается runtime metadata.

## Обязательный launch gate

До начала **каждой** backlog-задачи агент обязан:

1. прочитать этот файл, точную карточку из `HERMES_TASKS.md` и связанные ADR/спецификацию;
2. предложить владельцу route в форме `primary / worker / reviewer`, указав уровень, причину и необходимость делегирования;
3. дождаться выбора владельца; не начинать задачу и не менять Hermes-конфиг заранее;
4. после завершения задачи указать рекомендуемый route следующей задачи и явно отметить её как не начатую.

Если задача меняет финансовую семантику, миграции, модель данных, privacy или auth, более дешёвая модель не получает право самостоятельно принимать решение: она может реализовывать только уже утверждённый контракт.

## Уровни и роли

| Уровень | Модель/route | Допустимая роль |
|---|---|---|
| High | GPT-5.6 Sol | архитектура, деньги/ставки/налоги, миграционная семантика, приватность, финальная приёмка |
| Mid-high | GPT-5.6 Terra | bounded backend/frontend implementation по утверждённому контракту, интеграционные тесты, локальный рефакторинг |
| Mid-high, экспериментально | Token Router: `moonshotai/kimi-k3-free` | read-only analysis, test matrix, documentation, review; запись кода — только после успешной калибровки на безопасной задаче |
| Mid | GPT-5.6 Luna | scaffolding, повторяемый UI/CRUD, fixtures, boilerplate tests, docs |
| Mid, внешний | DeepSeek V4 Flash | независимый read-only review и исследования; результаты не являются proof |

`Kimi K3 Free` доступна через уже настроенный named provider `tokenrouter`. Платные `moonshotai/kimi-k3` и `moonshotai/kimi-k2.7-code` не выбираются без отдельного решения владельца.

## Рекомендованные routes фазы B

| Задача | Primary | Worker | Reviewer | Почему |
|---|---|---|---|---|
| B02 Alembic | Terra (mid-high) | — | Kimi K3 Free (read-only, опционально) | инфраструктура миграций без доменной схемы |
| B03 money/rates | Sol (high) | Terra только по закрытому контракту | Sol | единицы, Decimal, rounding становятся фундаментом всех расчётов |
| B04 app settings | Terra (mid-high) | Kimi только boilerplate после контракта | Sol при изменении денежной семантики | singleton, defaults и API |
| B05 reporting months | Terra (mid-high) | — | Sol на инвариантах draft/closed | период, snapshot date и иммутабельность |
| B06 accounts | Terra (mid-high) | Kimi после утверждённой схемы | Terra | справочник с ограничениями |
| B07 IIS | Sol (high) | Terra по контракту | Sol | налоговая семантика и статусы вычетов |
| B08 instruments | Terra (mid-high) | Kimi после калибровки | Terra | справочник и uniqueness ISIN |
| B09 positions | Sol (high) | Terra по контракту | Sol | market value, cost basis и результат |
| B10 deposits | Sol (high) | Terra по контракту | Sol | процент и согласованное округление |
| B11 cash/liquid assets | Terra (mid-high) | Kimi после калибровки | Terra | агрегаты без новых формул |
| B12 incomes | Sol (high) | Terra по контракту | Sol | passive-income rules |
| B13 investment flows | Sol (high) | Terra по контракту | Sol | tax/commission/net и классификация событий |
| B14 expected flows | Sol (high) | Terra по контракту | Sol | forecast semantics |
| B15 expenses/savings | Sol (high) | Terra по контракту | Sol | влияние на остаток и обязательные расходы |
| B16 debts | Terra (mid-high) | Kimi после калибровки | Sol на liquid-capital rule | вычет долга из капитала |
| B17 property/mortgage | Sol (high) | Terra по контракту | Sol | property equity, coverage, division by zero |
| B18 goals | Terra (mid-high) | Kimi после калибровки | Terra | конфигурируемая цель без UI hardcode |
| B19 comments | Luna (mid) | Kimi после калибровки | Terra | упорядоченные заметки без финансовой логики |

Расчётный слой C, импорт/экспорт с личными данными, auth/VPS и release tasks по умолчанию начинаются с **Sol (high)**. UI без формул обычно начинается с **Terra (mid-high)** или **Luna (mid)**.

## Делегирование в Hermes

- `delegate_task` не принимает provider/model на один вызов.
- Если `delegation.provider` и `delegation.model` пусты, ребёнок наследует route родительской сессии. Это было состоянием при B01; runtime отчитался `Model: ?`, поэтому модель reviewer B01 не подтверждена и не должна называться DeepSeek.
- Единая настройка `delegation` переключает **всех** built-in children. Она полезна для серии однотипных read-only задач, но не для смешивания моделей в одной итерации.
- Для гарантированно другого worker-model нужна отдельная session/profile или bounded Hermes one-shot с явно выбранными provider/model. Write-worker всегда работает изолированно и не принимает commit/push.
- Перед запуском child агент обязан объявить запланированный route; после возврата — показать runtime model, если он её сообщил. Без runtime confirmation в отчёте писать `модель не подтверждена`.

### Предлагаемая первая калибровка Kimi

Для B02 Kimi K3 Free получает только read-only prompt: проверить план Alembic, перечислить риски и test matrix. Код, конфиг Hermes и Git она не меняет. Terra остаётся primary implementation. Если результат точный и полезный, Kimi можно назначать на следующий безопасный закрытый scope.

## Частота обновления сессий

Не обновлять сессию механически после каждой задачи. Новый session boundary обязателен при смене primary model, после принятой миграции/схемы, после долгого расследования или когда контекст сжат и становится неоднозначным. Для близких Terra-задач допустимы 2–3 последовательные задачи, но launch gate и явный выбор владельца остаются перед каждой.
