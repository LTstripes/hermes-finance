# Performance UI v2 — UX и контракт подготовки данных

Issue: #529. Parent: #528. Дата: 2026-09-27.

**Статус: CANDIDATE / independent review required.** Это docs-only результат Worker в чате, не реализованный UI, не независимый ACCEPT и не Owner UAT. Принятие документа не разрешает пропустить отдельные write-contract gates ниже.

Исследованный код: `988090419b6edfbfa5f6ef5c0a02064fedb07fb2` (main, push CI `36307812833` SUCCESS). База задачи: `3254f0dd413118cf6b88032346c5434330bf280a` — обновлённая `integration/performance-ui-v2`, продуктовый код совпадает с исследованным main. Формулы и финансовые контракты не меняются.

## 1. Задача и границы

Владелец должен увидеть доходность портфеля/счёта за явно выбранный интервал либо понять: что не подтверждено, где проверить, какое действие реально поддержано, почему после действия результат всё ещё может быть недоступен.

Один компактный блок на «Капитал» и один локальный detail. Без новых Home-карточек, глобального выбора исторического месяца, нового бокового меню, обязательного длинного мастера, графика с множеством линий или таблицы всех бумаг.

Доходность классов — отдельные #534/#535/#540. Денежный результат месяца — отдельная #575 (`/v2/capital/monthly-result`), не замена XIRR/TWRR и не источник их расчёта. Старые маршруты не удаляются.

## 2. Проверенная карта текущих возможностей

Ссылки ниже относятся к коду исследованного SHA, сохранённому в базе этой ветки. Наличие API/service не означает наличие удобного UI или достаточность реальных данных Owner.

| Возможность | Реальный источник | Что уже есть / чего не утверждаем |
| --- | --- | --- |
| Portfolio/account XIRR и TWRR | [XIRR API](../../backend/src/hermes_finance/api/portfolio_xirr.py), [TWRR API](../../backend/src/hermes_finance/api/portfolio_twrr.py), [frontend client](../../frontend/src/api/performance.ts) | GET `/api/performance/xirr` и `/twrr`; backend понимает portfolio/account. Текущий frontend client запрашивает portfolio; account UI расширяет client, не solver. |
| Достаточность исходных данных | [availability API](../../backend/src/hermes_finance/api/performance_availability.py), [domain codes](../../backend/src/hermes_finance/domain/performance_availability.py) | GET `/api/performance/availability`: оценки, membership, cash/in-kind coverage, flows, PRE/POST; XIRR/TWRR prerequisites отдельно. Это не результат solver. |
| Canonical внешние операции и переводы | [external_flows API](../../backend/src/hermes_finance/api/external_flows.py) | `/api/external-flows`, `/api/transfer-links`, transfer reconciliation evidence. Обычная broker reconciliation не заменяет проверку этих связей. |
| Подтверждение полноты денежных пересечений | [cash coverage API](../../backend/src/hermes_finance/api/cash_boundary_coverage.py) | GET/POST `/api/cash-boundary-coverages`, GET/PATCH отдельной записи. Даже при default complete в DTO UI не отправляет подтверждение без явного действия. |
| Неденежные пересечения | [in-kind API](../../backend/src/hermes_finance/api/in_kind_boundary_coverage.py) | GET/POST/PATCH coverage; GET/POST movements. Наличие movement record не даёт принятой оценки неденежного потока. |
| Исторический состав | [valuation_points](../../backend/src/hermes_finance/services/valuation_points.py), [accounts API](../../backend/src/hermes_finance/api/accounts.py), [accounts service](../../backend/src/hermes_finance/services/accounts.py) | Чтение использует `AccountPerformanceScopeMembership`. Accounts API/service меняют текущий include flag, не создают историческую membership-запись. Публичный historical-membership editor не зарегистрирован в [main.py](../../backend/src/hermes_finance/main.py). Нельзя обещать исправление исторического пробела обычным флажком. |
| PRE/POST и группы операций | [valuation_boundaries service](../../backend/src/hermes_finance/services/valuation_boundaries.py), [контракт](../r08-03a-valuation-boundaries.md) | Есть staged create/delete групп и staged capture наблюдений с `expected_material_signature`; публичный capture router не зарегистрирован в main.py. API/UI adapter — #533, не готовая кнопка. |
| Текущий UI | [Capital](../../frontend/src/ui-v2/UiV2CapitalPage.tsx), [routes](../../frontend/src/app/App.tsx), [MonthFlowsSection](../../frontend/src/components/MonthFlowsSection.tsx) | В Capital уже есть PerformanceBlock. `/months/:monthId` содержит legacy investment flows, не canonical external-flow editor. Нельзя направлять туда как к универсальному исправлению Performance. |

Нормативные границы: [R08 availability](../r08-01c-performance-availability.md), [XIRR](../r08-02-portfolio-xirr.md), [Performance closeout](../PERFORMANCE_V1_CLOSEOUT_2026-09-12.md), [financial completeness](../financial-completeness-contract.md), [PERF04B](PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md), MASTER_SPEC/принятые ADR по их обычному приоритету.

## 3. Информационная архитектура

### 3.1. Обзор Capital

Существующий PerformanceBlock заменяется компактным summary, не дублируется:

- «Доходность за период · TWRR»;
- «Доходность ваших вложений · XIRR, годовых»;
- даты интервала, валюта и вход «Состав расчёта»;
- один основной переход «Подробнее» либо «Проверить данные» по состоянию.

На первом экране максимум две приоритетные причины. Доступная метрика остаётся видимой независимо от другой. Нулевое значение показывается как 0%, убыток со знаком; unavailable не получает зелёный ноль. Денежный bridge убран из ряда процентных KPI и доступен только в деталях с названием «Изменение стоимости после внешних потоков» и оговоркой «Не прибыль и не доходность».

### 3.2. Detail и подготовка данных — целевые, ещё не существующие маршруты

- `/v2/capital/performance`: интервал, scope, две метрики, одна таблица по счетам, раскрываемые основания/методика.
- `/v2/capital/performance/data`: контекстная проверка данных и только реально реализованные действия. Пока writes не доставлены, экран остаётся read-only с явной границей возможности.
- Phase B добавляет «По счетам / По классам» в том же detail; до реализации классов нет обещающей пустой вкладки.

URL-параметры: `start`, `end` (ISO dates), `scope=portfolio|account`, `account_id` только для account, `view=accounts|classes` для detail. Это локальный контекст, не глобальные настройки приложения. Открытие account row сохраняет даты. Возврат из проверки восстанавливает тот же контекст.

Отсутствующие start/end допускают документированный дефолт. Частично заданные, повторённые, malformed, одинаковые или перевёрнутые даты — ошибка контекста, не тихая замена. Неизвестный/удалённый счёт и недопустимые scope/account сочетания не заменяются портфелем. Explicit dates, ставшие недоступными после reopen/delete/restore, остаются выбранными с объяснением, а не перескакивают на другой интервал.

`view=classes` до Phase B сообщает «Этот разрез ещё не поддерживается» и предлагает явный переход к счетам; это не нехватка данных Owner. Разрешённые переходы задаются enum/параметрами; произвольный redirect URL из данных не выполняется.

Общие `frontend/src/app/App.tsx`, UiV2Entry, Capital/Reports links и навигация интегрируются одним последовательным Integrator slot совместно с #554/#555/#569/#575. Leaf UI не перетягивает соседнюю ветку. Существующие PortfolioCoverageNote и смысл partial subtotal сохраняются.

## 4. Период и состав

Дефолт: последний и предыдущий закрытые отчёты с различными однозначными snapshot dates, по порядку отчётных периодов; подпись «Между отчётами» с фактическими датами. При неоднозначности/нехронологичности нет поиска другой удобной пары: предложить ручной выбор. Меньше двух границ — объяснение, без запроса несуществующего интервала.

Ручной выбор двух подтверждённых дат обязателен. Не путать reporting month с snapshot date: снимок за июль может быть датирован августом.

Пресеты 1/3/12 месяцев отсчитываются от показанной конечной snapshot date календарным сдвигом назад: сохраняется номер дня, а для последнего дня месяца сохраняется конец целевого месяца; иначе день ограничивается длиной целевого месяца. «С начала года» требует снимок 31 декабря предыдущего года. «Вся история» выбирает самую раннюю закрытую границу, не первый успешный для solver интервал. Пресет доступен только при однозначном существовании обеих требуемых дат. Нельзя подменять отсутствующую дату соседней, интерполировать или сокращать период для получения available. Пропуск промежуточного месяца не заполняется: достаточность конкретного интервала определяет backend.

Все выбранные даты передаются в canonical API без клиентского пересчёта доходности. Каждая показанная метрика обязана соответствовать запрошенным scope/account/date/currency/units. XIRR annualized, TWRR не annualized. При интервале короче 365 дней рядом с XIRR: «Приведено к году по короткому периоду; это не прогноз». Это presentation warning, не изменение значения/availability.

Состав Performance — исторический, не список текущих active accounts и не весь капитал Home. В текущем availability **нет одного готового поля «вот эти счета исторически включены в расчёт»**. На portfolio scope `scope_membership.account_ids` — это все каталожные счета, для которых проверяется история участия; туда попадает и счёт с цельной историей `include_in_returns=false`. Поэтому этот список, в том числе после вычитания `missing_or_ambiguous_account_ids`, нельзя показывать как состав доходности. `missing_or_ambiguous_account_ids` означает только пробел/неоднозначность истории участия.

Для выбранного интервала текущий авторитетный список счетов, которым нужна **денежная** проверка Performance, — `cash_boundary_coverage.account_ids`: это счета, чья effective-dated history содержит `include_in_returns=true` на пересечении с интервалом. Отдельный `in_kind_boundary_coverage.account_ids` уже и означает только счета, для которых требуется **неденежная** проверка (brokerage/IIS либо счета с position history по принятому сервису). Эти списки нельзя взаимозаменять.

«Состав расчёта» поэтому показывает три разные вещи: (1) счета денежной проверки из `cash_boundary_coverage.account_ids`; (2) отдельный, при наличии, список счетов неденежной проверки из `in_kind_boundary_coverage.account_ids`; (3) состояние проверки истории участия, где `scope_membership.account_ids` — именно проверяемый каталог, а `missing_or_ambiguous_account_ids` — проблемные identity. До появления отдельного canonical included-set нельзя переименовывать membership `account_ids` в «включённые счета». Для названий допустим lookup всех accounts, но не реконструкция membership из имён/текущих флагов. Исчезнувшее название не разрешает подменить identity.

В таблице счетов rates не суммируются и не усредняются. У каждой строки свои final availability/quality при одинаковом запрошенном интервале; доступные отдельные счета не делают итог портфеля доступным. Отсутствие одного ответа не прячется за сообщением «все счета проверены».

## 5. Диагностика и приоритеты

Источник причин — точные canonical reason codes плюс подтверждающие вложенные evidence fields. `code.includes("flow")` запрещён для нового mapping. Одному code могут соответствовать несколько подтверждённых причин; без нужных деталей выводится общее честное объяснение, не выдуманные счёт/дата/число операций.

Приоритет summary: (1) некорректный контекст/транспортный сбой, (2) исходные границы и membership, (3) cash/in-kind history/legacy/transfer, (4) наблюдения и валюта, (5) solver/unsupported. Приоритет не удаляет остальных причин из details и не блокирует независимо доступную метрику. Одинаковый blocker группируется между метриками с пометками XIRR/TWRR.

В следующей таблице `NC_` обозначает точный префикс `not_computable_`, а не поиск подстроки. Коды полностью определены в canonical domain/API; будущий неизвестный code получает нейтральный fallback.

| Code + подтверждающее evidence | Человеческий смысл / место проверки | Action и проверка результата |
| --- | --- | --- |
| `NC_opening_valuation_missing`, `NC_closing_valuation_missing`; соответствующая boundary | Нет однозначной подтверждённой оценки на выбранную дату. Не сообщать «месяц отсутствует», если причина может быть неоднозначностью. | Выбрать даты или открыть существующий month ID из boundary. Только после исправления/закрытия перечитать boundary и final metrics. |
| `NC_reporting_month_not_closed`, `NC_snapshot_date_missing`, `NC_unsupported_position_valuation`; component IDs, если есть | Отчёт ещё не закрыт, дата/оценка не подтверждена. | Проверить конкретный отчёт через поддержанный month editor/close. Не закрывать автоматически и не обещать, что одного close достаточно. |
| `NC_scope_membership_history_missing`; missing/ambiguous account IDs | Не подтверждён исторический состав за интервал. | Details показывают scope и счета. До принятого historical write path — «Ввод истории участия пока не поддержан»; не ссылка на текущий include flag как на исправление. Gate #532 ниже. |
| `NC_scope_membership_changed` | Состав менялся; текущий контракт не подтверждает расчёт этого интервала. | Показать имеющееся evidence; допустим явный ручной выбор другого интервала. Не переписывать историю ради расчёта. |
| `NC_scope_cash_unclassified`, `NC_scope_coverage_incomplete`; boundary components | Не подтверждены принадлежность денег или компоненты выбранного scope. | Открыть нужный month/component только при подтверждённом ID; иначе section-level проверка. Не использовать capital-source coverage как замену Performance gate. |
| `NC_external_flows_incomplete` + cash coverage missing IDs | Нет подтверждения полноты истории денежных пересечений у указанных счетов. | #532: известные canonical операции → проверка Owner → явный POST/PATCH cash coverage → новые reads. Отсутствие строк не доказывает нулевую активность. |
| Тот же code + `legacy_unclassified_flow_ids` | Есть legacy операции, которые нельзя автоматически использовать в расчёте. | Показать именно эти записи и canonical crossings. Не удалять legacy evidence и не конвертировать gross/net эвристикой. Отсутствующий safe reconciliation path обозначить отдельно. |
| Тот же code без достаточной детализации | Полнота/классификация внешних потоков не подтверждена; точная причина не локализована. | Read-only details и общая проверка ledger. Не утверждать, что нужно добавить определённое пополнение или просто поставить complete. |
| `NC_transfer_identity_unresolved`, `NC_transfer_reconciliation_incomplete`; flow/link IDs | Перевод не связан/не сверён по существующим правилам. | Canonical transfer-link/evidence path в #532, когда реализован. Broker reconciliation page не является его заменой; никаких residual fees. |
| `NC_transfer_in_transit_unvalued` | Нет принятой оценки денег в пути. | Показать ограничение и имеющиеся факты; не обещать «связать перевод» как гарантированное исправление стоимости в пути. |
| `NC_in_kind_boundary_coverage_unknown`; missing account IDs | Не проверена история неденежных перемещений. | #532: отдельная проверка/явное attestation через существующий in-kind coverage API; не выводить его из cash coverage. |
| `NC_in_kind_movement_unvalued`; known movements | Известно неденежное перемещение, но его стоимость для Performance не подтверждена. | Показать факт и ограничение. Ни complete, ни ввод cash-flow вместо бумаг не снимают его. Новая оценочная семантика вне #532. |
| `NC_valuation_boundary_missing`; flow/group/дата/PRE/POST из evidence | Нет полного подтверждённого наблюдения до/после операции; старое evidence также могло утратить пригодность. | #533 после реализации: фактическое observation + provenance и current signature. Не утверждать «устарело», если API не отличает это от отсутствия. |
| `NC_valuation_boundary_order_unknown` | Порядок относительно потока/группы не подтверждён. | Только явная принятая relation/group; не сортировка по ID или условное начало дня. Для endpoint flows это может блокировать не только TWRR: следовать final metric reasons. |
| `NC_currency_conversion_incomplete` | Нет принятого перевода в валюту расчёта на нужную дату. | Сообщить неподдержанный historical FX path. Текущий курс/переименование валюты не исправление. |
| `NC_xirr_no_valid_root`, `NC_xirr_root_ambiguity`, `NC_xirr_convergence_failed` | Final XIRR не получен однозначно/надёжно даже при пройденных prerequisites. | Показать ограничение и данные расчёта. Не повторять запись/attestation; не подставлять 0 и не скрывать TWRR. |
| Любой иной final code, включая числовую проблему TWRR | Подтверждённый результат не получен; приложение не умеет подробнее объяснить эту причину. | Безопасные read-only details, raw code только в техническом раскрытии. Не угадывать новую формулу или mutation action. |
| Network/HTTP/DTO mismatch | Проверка не завершилась, это не доказательство неполноты финансов. | Retry чтения; никакой рекомендации править данные или менять scope автоматически. |

Для action различаются: `available` (действие реально реализовано), `requires_reopen`, `not_implemented`, `source_required`, `unsupported`. `source_required` означает, что нужен фактический источник; приложение не может доказать его отсутствие по пустой таблице. «Исторических наблюдений нет» допустимо как подтверждение Owner, а не автоматический диагноз.

## 6. Read projection — граница #530

Рекомендуемый минимальный endpoint: **новый**, ещё не существующий GET `/api/performance/readiness` с теми же `start_date/end_date/scope/account_id`. Он возвращает `schema_version=1`, identity запроса, финальные XIRR/TWRR DTO, существующее evidence и список diagnostics/actions. Это композиция существующих services в одном coherent SQLite read, не второй calculator/availability engine. Сохранить старые endpoints совместимыми. Если Worker доказывает более узкую композицию с теми же guarantees, решение фиксируется Integrator до реализации.

Diagnostic item: стабильный UI diagnostic key, исходные canonical reason codes, affected metrics, только доказанные refs/даты, action kind/params/capability. UI diagnostics keys не становятся новыми финансовыми reason codes. Не включать private paths, raw provider payload, credentials или произвольный executable URL. Capability включается сервером только вместе с поддержанной операцией; frontend не выводит её из слов причины.

Successful prerequisites не заменяют final solver result. Top-level union availability не применяется как общий hide-switch. Финальный процент показывается только при available/exact, непустом value, правильных units/annualized и совпадающей identity. Несогласованный DTO — технический сбой, не вычисленный UI fallback.

Для запроса отдельного счёта не нужны все остальные account solver calls. Таблица допускает отдельные ленивые запросы, но не должна называться атомарной сверкой всего портфеля. Readiness DTO обязан сохранять различие между `membership_checked_account_ids` (источник: `scope_membership.account_ids`), `cash_required_account_ids` (источник: `cash_boundary_coverage.account_ids`) и `in_kind_required_account_ids` (источник: `in_kind_boundary_coverage.account_ids`) либо передавать исходные evidence blocks без переименования. Нельзя создавать `included_account_ids` простым `scope_membership.account_ids - missing_or_ambiguous`: это ошибочно включает исторически исключённые счета. Если #530 захочет добавить отдельный canonical included-set, его семантика должна переиспользовать effective-dated membership selection и получить отдельную contract/test фиксацию, а не выводиться во frontend.

После финансового изменения все затронутые results/diagnostics инвалидируются; новый ответ другой генерации не склеивается со старым. Не требуется новая persisted revision/schema только ради UI.

## 7. Поддержанный путь записи — #532/#533

#532 сначала использует существующие canonical external flows, cash coverage, in-kind coverage и cash-account linkage, с явным Owner action и действующими guards. Ledger review и attestation раздельны; оба вида coverage нельзя подтвердить одним неявным действием. Кнопка подтверждения не выбрана по умолчанию. Указывать, что остаётся проверить после сохранения.

**Отдельный gate historical membership:** из просмотренных публичных API не следует наличие принятого editor/write lifecycle. Перед его реализацией #532 обязан принести bounded sub-contract: actual existing writer или необходимый новый service, интервалы/перекрытия, корректировка и invalidation, closed-month guard, транзакционная атомарность. Нельзя реализовать direct ORM insert, backfill из текущего флага или новый HTTP endpoint без этого принятия. Отсутствие такого пути явно показывается пользователю, а не маскируется обещанием. Это уточнение объёма, не утверждение, что data-integrity audit не завершён.

#533 расширяет только принятый capture service: сначала получить реальный target и его current material signature, затем сохранять observation с подписью, прочитанной при начале capture. Нельзя вычислить подпись на сервере только в момент POST и тем самым принять старую форму как новую. Согласовать узкий capture/read-target DTO до кодирования. PRE/POST должны относиться к одной актуальной версии. Частично сохранённая пара остаётся неполной; UI честно показывает, какая сторона сохранена, и не повторяет запись вслепую.

Никаких PRE+flow, интерполяций, копирования month totals как intra-day evidence, вывода completeness из quote refresh. Изменение amount/date/group требует свежих допустимых свидетельств. Старые unbound observations не становятся exact миграцией. #494 уже в базе; не портировать его повторно.

Reopen — отдельное явное действие в существующем owner lifecycle; исторический источник затем проверяется/исправляется и месяц закрывается владельцем заново. По одному клику «Проверить данные» нет reopen/close, provider calls или записи. После ambiguous write outcome — read-back и объяснение, не автоматический retry POST.

## 8. Проверяемые acceptance vectors

Это specification vectors, **не выполненные runtime-тесты**. Конкретные synthetic fixtures строят Workers в существующих suites. Во всех сравнениях UI получает числа из backend, а не рассчитывает их.

| ID | Вход/действие | Ожидаемый результат |
| --- | --- | --- |
| V01 | Обе final metrics available/exact | Две цифры, XIRR годовых/TWRR за период, одинаковые identity и валюта. |
| V02 | XIRR available, TWRR missing PRE/POST | XIRR виден; одна конкретная TWRR причина и action согласно capability. |
| V03 | XIRR prerequisite available, final root ambiguous | XIRR недоступен с solver explanation; available TWRR сохранён. |
| V04 | Missing cash coverage + legacy IDs | Две доказанные причины, а не сообщение «добавьте одно пополнение». |
| V05 | Пустой ledger, cash coverage unknown | Не 0 flows complete; требуется отдельное явное attestation. |
| V06 | Cash coverage complete, in-kind coverage unknown | XIRR/TWRR не объявляются готовыми; показана независимая причина. |
| V07 | Known in-kind movement unvalued | Complete coverage не превращает движение в оценённое. |
| V08 | Portfolio содержит счёт с цельной историей `include_in_returns=false` и отдельный historical gap; текущий include flag меняется | Исторически исключённый счёт может присутствовать в `scope_membership.account_ids`, но не показывается участником расчёта; денежный состав берётся из `cash_boundary_coverage.account_ids`, gap остаётся отдельным blocker, текущий flag прошлое не лечит. |
| V09 | Нет snapshot на точную дату пресета / duplicate date | Пресет недоступен с объяснением, без соседней даты или shorter window. |
| V10 | Scope/период изменены, поздний старый ответ | Старая цифра не показана как текущая; back/refresh восстанавливает валидный URL. |
| V11 | Reopen/delete/restore затронули выбранную границу | Старый успех скрыт; explicit выбор не заменён последним периодом. |
| V12 | Нулевой/отрицательный backend result | Корректный 0%/знак убытка, не unavailable и не отсутствие текста. |
| V13 | Неизвестный reason / техошибка | Generic limitation либо retry чтения; никаких угаданных writes. |
| V14 | Linked transfer внутри портфеля, account drill-in | Классификация берётся для каждого scope, не переносится из portfolio в account. |
| V15 | PRE capture начат, flow изменён перед POST | Expected signature rejected; form не переподписывается автоматически. |
| V16 | Поддержанные данные проверены и явно сохранены | Read-back показывает оставшиеся blockers либо реальные final metrics; success save не равен success calculation. |
| V17 | 390px, keyboard, 200% zoom, длинные названия/причины | Нет горизонтального page overflow; видны даты/units/основной action, раскрытие и возврат с управляемым focus. |
| V18 | Переход между #575 и Performance | Денежный месяц и интервал доходности не смешаны; один экран не подменяет другой. |

## 9. Порядок поставки и review

#529 → independent review/Integrator decision → #530 → #531 и согласованные #532 leaf paths → #533 → #541 checkpoint A. Исторический membership write gate и capture DTO проверяются отдельно; нельзя закрыть весь actionable milestone только красивым read-only экраном.

#534 read-only inventory может идти параллельно, но финансовый class contract принимает отдельный Reviewer; #535/#540 ждут его и необходимые данные. Instrument scope остаётся вне первой поставки.

#484–#498/#536–#539/#509 уже интегрированы; migration head `0044_observed_valuation_material_signature`. Capital completeness и G04 уже не будущие проекты. Совместимость с продолжающимся UI parity проверяется при serialized navigation slot и финальном aggregate, а не ежедневным churn веток.

Worker checks здесь: проверка источников/документального diff и privacy, без запуска backend/frontend/Windows UAT. Последующие проверки пропорциональны VERIFICATION_POLICY; high-risk writes требуют независимого Reviewer. Owner UAT — на exact aggregate в owner-only Preview, никогда в agent workspace.
