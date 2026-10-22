# MyBroker: synthetic import bug hunt after #926

Baseline / target: `main`, `fd51120dd763a13d3ee98e3619d92c6bbca2db5c` (merge #926).
Branch: `test/astra-import-hunt-926`. Scope: tests and fixtures only; no product changes.

Все 25 XML сгенерированы из существующих **синтетических** фабрик тестов.
Содержимое внешних каталогов данных, реальные выписки, суммы и БД владельца не
использовались. Идентификаторы, даты 2030 года и суммы вымышлены. Каждый файл
содержит `synthetic_only` и уникальный `synthetic_case`. Имя для передачи парсеру
берётся из [manifest.json](manifest.json): имя файла является частью договора периода,
поэтому нельзя передавать парсеру короткое имя `01_control.xml`.

## Результат и пределы проверки

Найдено шесть воспроизводимых проблем: пять HIGH и одна MEDIUM. Каждая имеет
`xfail(strict=True, raises=AssertionError)` для двух путей чтения: сохранённый
журнал и повторно приложенный оригинал. Метки не скрывают исключения подготовки
данных; исправление поведения приводит к XPASS и требует обновления теста.

Маршрут: XML → `parse_mybroker` → `source_intake.save_intake` → независимый
`read_intake` → `read_monthly_returns` (два режима) и `read_instrument_returns`.
На каждом успешно разобранном файле также вызваны настоящие сервисы
`portfolio_xirr_for_interval` и `portfolio_twrr_for_interval`. До/после чтений
сравниваются все строки всех таблиц; финансовые таблицы остаются пустыми.

**Точный XIRR/TWRR во всех 24 принятых XML возвращает `not_computable` и NULL:**
source-only Save не создаёт принятые оценки и подтверждённый scope. Причины:
`not_computable_opening_valuation_missing`, `not_computable_closing_valuation_missing`,
`not_computable_scope_coverage_incomplete`. Это проверка барьера допуска, а не
проверка численного ядра точного TWRR на принятых финансовых записях. Числа ниже —
предварительный source XIRR и Modified Dietz, **не точный TWRR**. Файл 08 отклонён
парсером; расчёт после такого отказа намеренно не запускается.

[results.json](results.json) содержит полный фактический вывод всех читателей:
годовой/периодный XIRR, месячный Dietz, цепочку, причины, классификации,
инструментальные результаты и точные XIRR/TWRR. Последняя запись — совместный
прогон 01+25 с пропущенным маем. Значения Decimal записаны строками без float.

## Подтверждённые находки

Строки кода относятся к зафиксированному baseline, а не к будущему исправлению.
Проценты в таблице округлены для чтения; точные строки находятся в results.json.

| ID / severity | Кейс | Факт | Ожидание | Файл:строка | Идея фикса |
| --- | --- | --- | --- | --- | --- |
| AH-01 / HIGH | [03_typo_withdrawal.xml](03_typo_withdrawal.xml), `Вывoд дивидендов` с латинской `o` | Классификация `dividend`, доход −100000 коп., withdrawals=0. Source XIRR/Dietz **−10%**, gaps пуст. Повторное приложение XML не помогает. | Неподдержанное имя операции → unknown, NULL и причина. Не выводить вид операции только из слова «дивиденд». | [`services/source_money_classifications.py:72`](https://github.com/LTstripes/hermes-finance/blob/fd51120dd763a13d3ee98e3619d92c6bbca2db5c/backend/src/hermes_finance/services/source_money_classifications.py#L72) | Ограничить fallback доходов подтверждёнными полными шаблонами; конфликт направления или неизвестное название сохранять как unknown. Не добавлять угадывание опечаток. |
| AH-02 / HIGH | [04_account_transfer.xml](04_account_transfer.xml), −1000 на другой счёт | `internal_transfer` исключён из потока **отдельного source_account**. V0=10000, V1=9000, withdrawals=0, growth=−1000, XIRR/Dietz **−10%**, gaps пуст. | Перевод за границу счёта — внешний для этого счёта: при доказанном направлении withdrawals=1000 и результат 0%; до доказательства — NULL/блокер. | [`services/source_monthly_returns.py:400`](https://github.com/LTstripes/hermes-finance/blob/fd51120dd763a13d3ee98e3619d92c6bbca2db5c/backend/src/hermes_finance/services/source_monthly_returns.py#L400), [`services/source_money_classifications.py:45`](https://github.com/LTstripes/hermes-finance/blob/fd51120dd763a13d3ee98e3619d92c6bbca2db5c/backend/src/hermes_finance/services/source_money_classifications.py#L45) | Учитывать scope и границы перевода; нейтрализовать его только внутри подтверждённого портфеля. Не разрешать `internal_transfer` автоматически обнулять поток одного счёта. |
| AH-03 / MEDIUM | [11_duplicate_position.xml](11_duplicate_position.xml), точный дубль account/ISIN | Бумага посчитана дважды: V0=19000, V1=20800 вместо 10000/10900. XIRR/Dietz **9.473684%** вместо контрольных 9%; ни конфликта, ни раскрытия. У инструмента удвоены quantity/value/growth. | Конфликт дублирующих позиций и NULL до разрешения кратности; автоматическая агрегация не доказана. | [`services/source_monthly_returns.py:164`](https://github.com/LTstripes/hermes-finance/blob/fd51120dd763a13d3ee98e3619d92c6bbca2db5c/backend/src/hermes_finance/services/source_monthly_returns.py#L164), [`services/source_instrument_returns.py:234`](https://github.com/LTstripes/hermes-finance/blob/fd51120dd763a13d3ee98e3619d92c6bbca2db5c/backend/src/hermes_finance/services/source_instrument_returns.py#L234) | Перед суммой обнаруживать повтор account/ISIN и сохранять обе ссылки как конфликт. Не применять механическую дедупликацию Money к позициям. Основание: C, запрет неявной агрегации дублирующих позиций, строки 2918/2952. |
| AH-04 / HIGH | [21_outside_period.xml](21_outside_period.xml), событие 01.05 в апрельском XML | Есть `invalid_external_flow`, но его month=May. Апрель и period остаются **9%**, growth=900, хотя событие исключено. `flow_coverage_gap` отсутствует: filename-период непрерывен. | Ошибка даты должна блокировать интервал **владеющего документа**, либо XML должен быть отклонён; нельзя оставлять число с ошибкой вне отображаемого периода. | [`services/source_monthly_returns.py:231`](https://github.com/LTstripes/hermes-finance/blob/fd51120dd763a13d3ee98e3619d92c6bbca2db5c/backend/src/hermes_finance/services/source_monthly_returns.py#L231), [`services/source_monthly_returns.py:421`](https://github.com/LTstripes/hermes-finance/blob/fd51120dd763a13d3ee98e3619d92c6bbca2db5c/backend/src/hermes_finance/services/source_monthly_returns.py#L421) | Отделить reported event date от affected source interval; out-of-range помечать по covered_from/covered_to, не только по ошибочной дате. |
| AH-05 / HIGH | [22_hidden_amount.xml](22_hidden_amount.xml), лишний `p_code volume=1000` | Разобрана только известная нулевая комиссия; лишний денежный leaf пропущен. syntax blockers/gaps пусты, XIRR/Dietz **9%**. | Непотреблённый денежный узел → `unparsed_source_rows` и NULL либо отказ парсера. | [`statement_import/mybroker.py:446`](https://github.com/LTstripes/hermes-finance/blob/fd51120dd763a13d3ee98e3619d92c6bbca2db5c/backend/src/hermes_finance/statement_import/mybroker.py#L446), [`statement_import/mybroker.py:476`](https://github.com/LTstripes/hermes-finance/blob/fd51120dd763a13d3ee98e3619d92c6bbca2db5c/backend/src/hermes_finance/statement_import/mybroker.py#L476) | Проверять потребление всех финансовых листьев и их размещение. Разрешённый tag и совпавшее количество rn не доказывают полноту всех сумм. |
| AH-06 / HIGH | [23_hidden_wrapper.xml](23_hidden_wrapper.xml), rn рядом с Report | Проверяется только вложенный Report; rn во внешнем известном Trades2 не попадает в inventory/blockers. XIRR/Dietz **9%**, gaps пуст. | Финансовый узел вне поддержанной структуры → отказ либо финансовый blocker, который доходит до расчёта. | [`statement_import/mybroker.py:294`](https://github.com/LTstripes/hermes-finance/blob/fd51120dd763a13d3ee98e3619d92c6bbca2db5c/backend/src/hermes_finance/statement_import/mybroker.py#L294), [`statement_import/mybroker.py:335`](https://github.com/LTstripes/hermes-finance/blob/fd51120dd763a13d3ee98e3619d92c6bbca2db5c/backend/src/hermes_finance/statement_import/mybroker.py#L335) | Валидировать целиком wrapper и все узлы документа, а не только поддеревья выбранных Report. Сохранять непотреблённые узлы в структурных причинах. |

## Матрица 25 файлов

XIRR — периодный source return; Dietz — месячный (для этих одиночных месяцев
равен цепочке). «Gap» означает именно `flow_coverage_gap`, а не любой blocker.
Точный TWRR для каждого принятого файла NULL по причинам допуска выше.

| Файл | XIRR, % | Dietz, % | Gap | Результат |
| --- | ---: | ---: | --- | --- |
| 01_control | 9 | 9 | нет | Контроль без потоков |
| 02_unknown | NULL | NULL | нет | unknown_flow / unrecognized_money |
| 03_typo_withdrawal | −10 | −10 | нет | AH-01 |
| 04_account_transfer | −10 | −10 | нет | AH-02 |
| 05_usd_deposit | NULL | NULL | нет | USD, курс 90 в неподдержанном атрибуте: currency_unsupported |
| 06_fx_zero_rate | NULL | NULL | нет | Две валютные ноги, нулевой курс: currency_unsupported / unknown_flow |
| 07_empty_money | 9 | 9 | нет | Явно пустая Money, допустимый контроль |
| 08_missing_money | не запускался | не запускался | н/п | required_section_invalid |
| 09_empty_positions | NULL | NULL | нет | Нет native membership/оценок; пустой source result |
| 10_duplicate_money | 6.931843 | 6.930693 | нет | Обе одинаковые денежные строки сохранены, внесено 200 |
| 11_duplicate_position | 9.473684 | 9.473684 | нет | AH-03 |
| 12_partial_month | NULL | NULL | да | 10–30 апреля: partial_month_source / missing_endpoint |
| 13_negative_deposit | NULL | NULL | нет | Отрицательный взнос: invalid_external_flow |
| 14_zero_deposit | NULL | NULL | нет | Нулевой взнос: invalid_external_flow |
| 15_negative_withdrawal | 10.049043 | 10.050251 | нет | Вывод −100 принят, withdrawals=100 |
| 16_zero_fee | 9 | 9 | нет | Нулевая комиссия не является отсутствующей суммой |
| 17_nkd_buy | 9 | 9 | нет | settlement, купоны=0; инструмент: покупка 200+5=205 |
| 18_nkd_sell | 9 | 9 | нет | settlement, купоны=0; инструмент: продажа 200+5=205 |
| 19_partial_redemption | NULL | NULL | нет | Неподдержанное погашение не угадано как купон |
| 20_unknown_security | 9 | 9 | нет | Native endpoint оценка известна; тип бумаги unknown раскрыт в инструменте |
| 21_outside_period | 9 | 9 | нет | AH-04: invalid_external_flow не блокирует апрель |
| 22_hidden_amount | 9 | 9 | нет | AH-05 |
| 23_hidden_wrapper | 9 | 9 | нет | AH-06 |
| 24_transfer_section | NULL | NULL | нет | 4_Transfers_unsupported / unknown_flow |
| 25_june_gap | 9 | 9 | нет | Полный отдельный июнь |
| 01 + 25 | NULL | NULL | да | Между апрелем и июнем отсутствует май; оба независимых сегмента доступны |

Unknown security здесь не объявлен дефектом: задана явная денежная оценка
концов периода, поэтому суммарный provisional результат не требует каталожного
типа бумаги. `instrument_type_unknown` и `approximate=true` раскрываются.
Сохранение одинаковых Money occurrences также соответствует контракту C:
совпадение строк само по себе не доказывает дублирование экономического события.

## Воспроизведение

Из корня свежего клона, Python 3.13, зависимости из `backend/uv.lock`:

```powershell
uv sync --project backend --locked --group dev
backend/.venv/Scripts/python.exe backend/tests/astra_hunt_generate.py
backend/.venv/Scripts/python.exe backend/tests/astra_hunt_runner.py
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/test_source_monthly_returns_service.py -k astra_hunt -q
```

На Linux используйте `backend/.venv/bin/python`. Генератор воспроизводит 25 XML
и manifest; runner обновляет results.json. Его scratch БД создаются только
в checkout-local `backend/.pytest_cache/` и удаляются после чтения.
В ограниченной Windows-среде pytest можно передать новый checkout-local
`--basetemp=backend/.pytest_cache/astra-<unique-run>`.

Для просмотра настоящих падений (ожидаемый exit 1):

```powershell
backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests/test_source_monthly_returns_service.py -k 'astra_hunt_uncertain_import or astra_hunt_account_transfer' --runxfail -q --tb=short
```

Тесты добавлены в [test_source_monthly_returns_service.py](../../../backend/tests/test_source_monthly_returns_service.py),
поэтому выполняются в уже назначенной CI lane этого файла. Генератор и runner —
вспомогательные тестовые модули; taxonomy/продуктовый код не меняются.

Проверки и точный candidate SHA фиксируются в draft PR. Слияние, финансовый
Apply, runtime/UAT и исправление найденных дефектов в эту задачу не входят.
