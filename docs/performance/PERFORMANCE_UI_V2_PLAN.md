# Performance UI v2 — план отдельного потока

Дата: 2026-09-25. Parent: [#528](https://github.com/LTstripes/hermes-finance/issues/528).

**Статус: план / backlog, не реализовано.** Этот документ фиксирует Owner direction и последовательность задач. Детальный UX/data contract принимает #529; новый class scope — #534. План не заменяет MASTER_SPEC, принятые ADR и performance contracts.

## 1. Изоляция и исходное состояние

- Новая staging-ветка: `integration/performance-ui-v2`.
- Создана GitHub-native от canonical main `f328c82b6c7c3af0f6cd436c7e1d408bb54a8885`.
- В этом planning change меняется только этот документ. Product code, main, Stable, Owner data, релизы и чужие ветки не меняются.
- Каждый Worker работает в отдельной child branch и отдельном физическом workspace. До запуска Integrator назначает точный baseline и абсолютный локальный путь; машинные пути не записываются в Git.
- PR Workers направляются только в staging. Workers не merge main/siblings, не self-accept и не запускают следующую задачу. Delivery-loop не активирован.
- Staging не является alternate main/release source. Интеграция — только exact reviewed aggregate + CI + applicable Owner UAT; релиз отдельно.

Проверенные основания на split SHA:

1. В [UiV2CapitalPage.tsx](../../frontend/src/ui-v2/UiV2CapitalPage.tsx) уже есть `PerformanceBlock`, XIRR/TWRR и monetary bridge. Развиваем существующий блок, а не дублируем его.
2. [XIRR API](../../backend/src/hermes_finance/api/portfolio_xirr.py) и [TWRR API](../../backend/src/hermes_finance/api/portfolio_twrr.py) поддерживают portfolio/account. Class/instrument scope ещё не реализован этими API.
3. [Availability contract](../r08-01c-performance-availability.md) содержит оценки, historical membership, cash-history completeness, external flows и PRE/POST evidence; верхнее объединённое availability не заменяет metric-specific states.
4. [Performance v1 closeout](../PERFORMANCE_V1_CLOSEOUT_2026-09-12.md): #358 уже PASS. На реальной неполной истории подтверждён правильный отказ, а не наличие вычислимой доходности. Предстоящая проверка — новый UX/data-workflow UAT.
5. [PERF04B](PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md) не разрешает вывести class/instrument performance из текущих snapshot labels. Денежный bridge — не прибыль/P&L и не attribution доходности.

Приватный Owner-скрин/суммы не публикуются и не используются как fixture. Общая фраза на скрине не доказывает, какая именно операция отсутствует.

## 2. Предлагаемая структура интерфейса

Один вход: **Капитал → Доходность**. Без нового пункта глобального меню и новых карточек на Home.

На обычном Capital overview — существующий блок, сведённый к одному компактному summary. Полный разбор — отдельное локальное представление внутри Capital. Поведение navigation/deep link замораживает #529, реализует #531.

Схематично, не текущие данные Owner:

```text
Капитал
Обзор | Доходность

Доходность портфеля                  Период: [выбранный]
Фактические даты начала и конца · валюта · состав расчёта

Доходность за период       Доходность ваших вложений
TWRR: +… %                XIRR: +… % годовых

[Подробнее]               [Проверить данные]
```

В detail view — один переключатель «По счетам / По классам», одна компактная таблица: название, TWRR за период, XIRR годовых, состояние. Классы появляются только с принятым и реализованным backend, не как обещающая пустая вкладка.

Строка раскрывает основание/охват и причины. Не показывать одновременно отдельные карточки на каждый счёт, класс и инструмент. Таблица всех бумаг, heatmap, несколько графиков, benchmark, dashboard composer и новый экспорт вне scope.

По отдельному инструменту — потенциальный будущий drill-down из класса или карточки инструмента. Не реализуется автоматически: #534 оценивает, есть ли корректная история. Доходность бумаги, изменение её цены и вклад в портфель не взаимозаменяемы.

## 3. Периоды, единицы и финансовый смысл

- Период определяется реальными датами подтверждённых снимков. Возможные пресеты: месяц, 3 месяца, 12 месяцев, с начала года, вся доступная история; точные правила и состав замораживает #529.
- Нет точной требуемой границы — объяснить ограничение. Не подставлять ближайшую дату или более короткое окно ради available.
- XIRR — годовая приведённая ставка, TWRR — доходность выбранного интервала. На короткой истории нужна оговорка, что annualization не является прогнозом.
- Состав Performance не равен автоматически всему ликвидному капиталу Home. Отдельно показывать исторический scope, охват и валюту.
- Rates счетов/классов не суммируются и не усредняются для получения итога. Parent result — из backend своего scope.
- Exact zero остаётся нулём; unavailable остаётся unavailable. Одна доступная метрика не скрывается из-за другой.
- Monetary `value_change_after_external_flows` — вторичное раскрываемое пояснение с точным названием «Изменение стоимости после внешних потоков», не карточка «Заработано»/«Прибыль».

## 4. Отказ должен вести к следующему действию

Рабочий шаблон: **что не подтверждено → где → что можно сделать → как проверить результат**.

Illustrative states, не диагноз Owner screenshot:

| Причина | Что сообщить | Поддержанное действие |
| --- | --- | --- |
| История операций не подтверждена | Нет подтверждения полноты для указанного счёта/интервала | Показать известный ledger и условия явного Owner attestation |
| Есть неразобранные/legacy операции | Какие evidence rows требуют проверки, только когда они известны | Открыть конкретные записи; не конвертировать их автоматически |
| Нет исторического состава/связи cash со счётом | Какая связь или период не подтверждены | Перейти к существующему разрешённому owner path либо честно обозначить отсутствующую возможность |
| XIRR доступен, TWRR нет | Не хватает наблюдений до/после определённой внешней операции | Показать boundary и разрешить фактический capture, если есть источник и accepted service |
| Исторических PRE/POST наблюдений нет | Месячные итоги не восстанавливают точную TWRR boundary | Не предлагать подставить вычисленные суммы; объяснить требования к будущим наблюдениям |
| Технический сбой | Проверка не завершилась | Безопасный retry чтения, не приглашение исправлять финансы |
| Новый class scope не поддержан | Ограничение приложения/контракта, не ошибка Owner | Не показывать неработающую кнопку ввода |

Summary показывает максимум две приоритетные причины и вход в полный список. В деталях нет выдуманных счётчиков «готово на 80%» или отсутствующих операций. Mapping по точным codes, а не substring `flow`.

Owner attestation — подтверждение проверенной истории, не магическое создание evidence. Отсутствие строк само по себе не значит нулевые потоки. Закрытые месяцы остаются неизменяемыми без явного reopen. После записи: перечитать диагностику и метрики, а не объявить успех заранее.

## 5. Backlog для Workers

В каждой issue есть пользовательский результат, scope/non-goals, критерии, сложности/риски, зависимости, review и короткий launch template. Модели/effort, exact baseline и реальные workspace paths намеренно не выдуманы: их назначает Integrator при запуске. Шаблон с placeholders не считается готовой к исполнению командой.

| ID | Issue | Deliverable | Сложность | Зависимость |
| --- | --- | --- | --- | --- |
| PUI-01 | [#529](https://github.com/LTstripes/hermes-finance/issues/529) | UX/data-path contract, evidence/action matrix | Средняя | Первая задача |
| PUI-02 | [#530](https://github.com/LTstripes/hermes-finance/issues/530) | Read-only metric-specific диагностика | Средняя | Accepted #529 |
| PUI-03 | [#531](https://github.com/LTstripes/hermes-finance/issues/531) | Compact portfolio/account UI и периоды | Средняя | Accepted #529/#530 |
| PUI-04 | [#532](https://github.com/LTstripes/hermes-finance/issues/532) | Owner ledger/coverage/membership correction path | Сложная | Accepted #529/#530; UI integration после #531 |
| PUI-05 | [#533](https://github.com/LTstripes/hermes-finance/issues/533) | Version-bound observed PRE/POST capture API/UI | Сложная | Accepted #529/#530/#494; UI integration после #531/#532 |
| PUI-06 | [#534](https://github.com/LTstripes/hermes-finance/issues/534) | Class-return evidence/capability contract | Сложная | Может идти docs-only параллельно PUI-01 |
| PUI-07 | [#535](https://github.com/LTstripes/hermes-finance/issues/535) | Class backend/API после явного GO | Сложная, уточнить после контракта | BLOCKED ON #534 и prerequisites |
| PUI-08 | [#540](https://github.com/LTstripes/hermes-finance/issues/540) | Одна таблица «По классам» и drill-in | Средняя | Accepted #531/#534/#535 |
| PUI-09 | [#541](https://github.com/LTstripes/hermes-finance/issues/541) | Real-backend synthetic journey + Owner UAT/checkpoints | Средняя/сложная | Exact aggregate выбранной фазы |

Фаза A: PUI-01 → PUI-02 → PUI-03/PUI-04 → PUI-05 → PUI-09 checkpoint A.

Фаза B: PUI-06 → принятие scope/необходимых prerequisites → PUI-07 → PUI-08 → PUI-09 checkpoint B.

Shared files не правятся одновременно независимыми writers: route/navigation spine принадлежит PUI-03/Integrator, PUI-04/05 добавляют согласованные leaf surfaces. Parallel готовность не отменяет проверку совместимости accepted staging head.

Фаза B не задерживает отдельную поставку A. BLOCK по классам не считается их реализацией; новые ledger/migration/import prerequisites выделяются явно перед кодом.

## 6. Не мешать текущим работам

- [#494](https://github.com/LTstripes/hermes-finance/issues/494) / [PR #526](https://github.com/LTstripes/hermes-finance/pull/526): accepted version binding обязателен перед публичным capture PUI-05. Не дублировать и не переносить непринятый фикс.
- [PR #509](https://github.com/LTstripes/hermes-finance/pull/509), `integration/data-integrity-hardening`: согласовать lifecycle/invalidation/coherent reads и migration chain на нужном этапе. Ветка не подмешивается автоматически.
- [#498](https://github.com/LTstripes/hermes-finance/issues/498) / [PR #521](https://github.com/LTstripes/hermes-finance/pull/521): не создавать альтернативные capital completeness semantics; Performance gates остаются отдельными.
- [#476](https://github.com/LTstripes/hermes-finance/issues/476): существующий G04 regression work не превращать в дубликат или широкий E2E redesign.
- [#389](https://github.com/LTstripes/hermes-finance/issues/389): dashboard composer остаётся отдельной будущей задачей.

Исходный split main не содержит автоматически весь незавершённый hardening stream. Перед write-capture/final integration Integrator фиксирует конкретные accepted зависимости и точную совместимую базу.

## 7. Критерий полезности и завершения

Нельзя ограничиться тестом «три надписи unavailable видны».

Минимальный synthetic journey: неполная история → понятная причина → известный ledger → явное подтверждение полноты → XIRR доступен при достаточных остальных данных → фактические PRE/POST → TWRR доступен. Отдельно отсутствие исторического источника остаётся честно unavailable.

Проверить zero/loss, XIRR-only, scope/date changes, unknown code, errors, cash/member/transfer ambiguity, stale evidence after correction, CLOSED guard и stale UI после reopen/delete/restore. Desktop/narrow/keyboard/deep links обязательны для затронутого UI.

Новый Owner UAT проводится на одном exact reviewed aggregate в isolated Preview. Синтетика остаётся в agent workspace; private данные туда не попадают. Owner PASS не требует невозможного восстановления отсутствующей истории, но требует понятного supported действия/ограничения. Результаты A/B записываются отдельно в #541.

Checks пропорционально [VERIFICATION_POLICY](../VERIFICATION_POLICY.md). Высокий риск требует независимого Reviewer по [MODEL_ROUTING](../MODEL_ROUTING.md). Создание этого плана не означает запуска suites, implementation, UAT или release.
