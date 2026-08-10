# ADR 0002: Opening YTD gross для расчёта НДФЛ

- **Статус:** принято
- **Дата:** 2026-08-10
- **Связанные документы:** [MASTER_SPEC](../MASTER_SPEC.md), [Release 0.2](../RELEASE_0_2.md), [Model routing](../MODEL_ROUTING.md)
- **Связанная задача:** `R02-02`

## Контекст

`MASTER_SPEC.md` §10.14 требует рассчитывать прогрессивный НДФЛ от накопленного облагаемого gross с начала календарного года. При этом история приложения может начинаться не с января. Для 2026 года спецификация отдельно предусматривает gross за январь–апрель в приватном локальном seed.

Текущий сервис `calculate_salary_tax()` считает YTD только как сумму `SALARY` gross из существующих более ранних `reporting_months`. Если первая история начинается, например, в мае, январь–апрель отсутствуют из YTD и налоговые пороги сдвигаются.

Нужен явный контракт для дохода до начала доступной месячной истории. Контракт не должен:

- выдумывать неизвестный исторический доход;
- задваивать gross, если более ранние месяцы позже добавятся в приложение;
- расширять состав налоговой базы без отдельного решения;
- хранить реальные персональные суммы в Git.

## Решение

### 1. Вводится годовой opening tax context

Для каждого календарного года допускается не более одного runtime-контекста `salary_tax_year_context` со следующей семантикой:

- `tax_year` — календарный год;
- `effective_from_month` — первый месяц, начиная с которого месячная история приложения становится каноническим источником gross для расчёта НДФЛ, `1..12`;
- `opening_taxable_gross_kopecks` — накопленный облагаемый gross **с 1 января этого года до начала `effective_from_month`**, не включая сам `effective_from_month`.

Пример семантики:

```text
tax_year = 2031
effective_from_month = 5
opening_taxable_gross = 400000.00 RUB
```

означает: для расчётов с мая 2031 года известно, что облагаемый gross за январь–апрель 2031 года суммарно равен 400 000 ₽. Начиная с мая источником новых сумм становятся `reporting_months` и `income_entries`.

### 2. Единицы и точность

- В persistence `opening_taxable_gross` хранится как integer kopecks (`BigInteger` или эквивалентная точная схема проекта).
- В API и private seed сумма передаётся decimal string в RUB, например `"400000.00"`.
- `float` не используется.
- Значение не может быть отрицательным.
- Если `effective_from_month = 1`, `opening_taxable_gross` обязан быть равен нулю: внутри календарного года нет периода до января.

### 3. Состав налоговой базы не меняется этой задачей

Opening value покрывает **ровно ту же налоговую базу, которую использует текущий salary-tax service**.

На момент принятия ADR это `gross_amount_kopecks` записей `IncomeType.SALARY`.

`BONUS`, `SIDE_INCOME`, инвестиционные доходы и иные налоговые базы не включаются автоматически. Если их участие в общей налоговой базе потребуется позже, это отдельное изменение финансового контракта и отдельная task-card.

### 4. Нормативный алгоритм выбора YTD для месяца `M`

Сначала вычисляется `payment_gross` как сумма `SALARY` gross текущего reporting month.

Далее application service обязан использовать **ровно следующий алгоритм**:

```text
if payment_gross == 0:
    return zero tax result without requiring complete prior history

if M == January:
    ytd_gross_before_payment = 0

else if opening context exists AND M >= effective_from_month:
    require every calendar month in [effective_from_month, M) to be a known month
    ytd_gross_before_payment =
        opening_taxable_gross
        + SUM(SALARY gross for known months in [effective_from_month, M))

else:
    require every calendar month in [January, M) to be a known month
    ytd_gross_before_payment =
        SUM(SALARY gross for known months in [January, M))

if any required prior month is not known:
    fail with salary_tax_history_incomplete
```

Текущая выплата месяца `M` в `ytd_gross_before_payment` не входит; она передаётся в pure-domain calculator как `payment_gross` и разбивается по налоговым ступеням поверх рассчитанного YTD.

Opening gross учитывается ровно один раз.

Алгоритм выше является нормативным и имеет приоритет над более общими пояснениями ниже.

### 5. Что такое known month

Для целей salary-tax history календарный месяц считается **known month** только если одновременно выполняются условия:

1. существует соответствующий `reporting_month` того же календарного года и месяца;
2. его статус — `closed`.

Само наличие строки `reporting_month` со статусом `draft` не доказывает, что отсутствие `SALARY` означает известный ноль: данные могли быть ещё не внесены.

Для закрытого месяца сумма `SALARY gross` определяется как сумма всех его `IncomeType.SALARY` entries. Если таких entries нет, это считается **известным нулём**, потому что `closed` является явным пользовательским подтверждением завершённости месяца.

Если ранее закрытый месяц сделан `reopen` и снова имеет статус `draft`, он немедленно перестаёт быть known month для расчётов последующих месяцев. До повторного `close` ненулевой salary-tax расчёт, зависящий от него, обязан возвращать `salary_tax_history_incomplete`.

Статус текущего месяца `M` не используется как условие известности его собственной выплаты: `payment_gross` берётся из текущих entries, а completeness проверяется только для **предыдущих** месяцев, входящих в YTD.

### 6. Source of truth

После загрузки данных runtime source of truth — строка в SQLite `salary_tax_year_context` плюс месячные `income_entries` после `effective_from_month` с учётом правила known month.

`data/private_seed.json` является только способом начальной локальной загрузки. После seed он не читается при каждом расчёте и не конкурирует с данными БД.

`app_settings` не используется для этого значения: opening YTD является годовым налоговым контекстом, а не глобальной настройкой приложения.

### 7. Private seed

Private seed расширяется необязательным массивом, например:

```json
{
  "salary_tax_opening_contexts": [
    {
      "tax_year": 2031,
      "effective_from_month": 5,
      "opening_taxable_gross": "400000.00"
    }
  ]
}
```

Точный пользовательский файл остаётся только локально и исключён из Git.

Публичный `private_seed.example.json` использует только синтетические значения.

Добавление необязательного поля не должно ломать существующие seed-файлы без этого поля; отсутствие opening context не трактуется автоматически как известный ноль.

Текущая публичная schema использует `additionalProperties: false`, поэтому R02-03 обязана явно расширить `docs/private_seed.schema.json`. Нужно ли повышать `schema_version` при обратно совместимом optional-поле — техническое решение R02-03, а не изменение финансовой семантики.

### 8. Missing context не равен нулю

Если расчётный месяц содержит ненулевой `SALARY` gross, а приложению неизвестен полный YTD до этого месяца по нормативному алгоритму §4, сервис не имеет права молча подставить `0` или частичную сумму.

Для месяца с `payment_gross = 0` разрешён нулевой tax result без требования полного YTD, поскольку неизвестный YTD не меняет налог на нулевую выплату.

Для ненулевой выплаты при неполной истории application service **обязан** завершить расчёт доменной/application ошибкой с кодом:

```text
salary_tax_history_incomplete
```

Этот код является частью обязательного контракта R02-03, а не рекомендацией. Generic `ValueError`, иной error code или fallback к `0` не соответствуют ADR. UI/API не должны показывать такой расчёт как точный.

### 9. Добавление более ранних reporting months и защита от double count

Месяцы раньше `effective_from_month` считаются уже агрегированными внутри `opening_taxable_gross` для расчётов после этой границы.

Если пользователь позже создаёт или импортирует март/апрель при `effective_from_month = 5`:

- эти записи могут храниться для истории и аналитики;
- они **не добавляются повторно** к YTD мая и последующих месяцев;
- opening context не пересчитывается автоматически;
- расчёт НДФЛ для самого месяца, который лежит раньше `effective_from_month`, не может использовать baseline, содержащий этот же месяц: для него применяется ветка алгоритма без opening context и требуется известная закрытая история с января до этого месяца.

Чтобы сделать добавленные ранние месяцы каноническим источником налоговой истории для расчётов после baseline boundary, владелец должен явно изменить opening context: передвинуть `effective_from_month` назад и соответственно изменить `opening_taxable_gross`, либо перейти на полную историю с января и нулевой opening суммой.

Автоматически вычитать добавленный месяц из baseline запрещено: приложение не знает, совпадает ли его записанный gross с тем, что было включено в исходный opening total.

### 10. Минимальный persistence/API contract для R02-03

Рекомендуемая таблица:

```text
salary_tax_year_contexts
- tax_year                         INTEGER PRIMARY KEY / UNIQUE
- effective_from_month             INTEGER NOT NULL CHECK 1..12
- opening_taxable_gross_kopecks    BIGINT NOT NULL CHECK >= 0
- created_at / updated_at          по действующим conventions проекта
```

Минимальный HTTP contract:

```text
GET    /api/salary-tax/years/{year}/opening-context
PUT    /api/salary-tax/years/{year}/opening-context
DELETE /api/salary-tax/years/{year}/opening-context
```

`PUT` принимает:

```json
{
  "effective_from_month": 5,
  "opening_taxable_gross": "400000.00"
}
```

Сумма в API — decimal string RUB. `PUT` является create-or-replace для одного календарного года.

`DELETE` удаляет только opening context. После удаления расчёты с неполной историей должны становиться `salary_tax_history_incomplete`, а не использовать скрытый fallback `0`.

### 11. Migration/backward compatibility для 0.1.0

Alembic migration создаёт новую таблицу, но **не создаёт opening rows из догадок**.

Для существующей БД `0.1.0`:

- существующие `reporting_months`, income entries и tax brackets не меняются;
- никакая историческая сумма не вычисляется автоматически из отсутствующих месяцев;
- если история начинается после января, до явного seed/API заполнения контекста расчёт ненулевой зарплаты должен сообщать `salary_tax_history_incomplete`;
- если полная непрерывная **закрытая** история начинается с января, opening row не обязателен;
- существующий draft-месяц не считается доказательством известной нулевой зарплаты для последующих месяцев.

Это намеренно fail-closed поведение: лучше явно показать недостаточность данных, чем сохранить правдоподобный, но неверный налог.

## Контрольные примеры

### A. История начинается в мае

```text
opening: Jan–Apr = 400 000
May salary = 100 000
```

Для May:

```text
ytd_before_payment = 400 000
payment_gross = 100 000
```

Для расчёта May не требуется, чтобы сам May уже был `closed`: completeness относится только к предыдущим месяцам.

### B. Июнь после opening context

```text
opening Jan–Apr = 400 000
May reporting month = CLOSED
May salary = 100 000
June salary = 100 000
```

Для June:

```text
ytd_before_payment = 400 000 + 100 000 = 500 000
payment_gross = 100 000
```

### C. May существует, но остаётся draft

```text
opening Jan–Apr = 400 000
May reporting month = DRAFT
May salary entry отсутствует
June salary = 100 000
```

Для June May не является known month. Результат:

```text
salary_tax_history_incomplete
```

May нельзя молча интерпретировать как нулевую зарплату только потому, что строка reporting month существует.

### D. Позже добавили April

Opening context остаётся `Jan–Apr = 400 000`, `effective_from_month = 5`.

Добавленный April salary не прибавляется ещё раз к YTD May/June. Чтобы перейти на детальную историю April как source of truth, baseline меняется явно.

### E. История начинается в мае, context отсутствует

При ненулевой зарплате May расчёт не выполняется как будто YTD равен нулю; возвращается `salary_tax_history_incomplete`.

### F. Полная история без opening context

Для July без opening context January–June должны все существовать и быть `closed`. Только тогда YTD July равен сумме их `SALARY gross`. Если хотя бы один месяц отсутствует или `draft`, результат — `salary_tax_history_incomplete`.

## Последствия

### Положительные

- прогрессивные пороги не сдвигаются из-за короткой истории приложения;
- baseline нельзя случайно задвоить с добавленными позднее историческими месяцами;
- draft/пустой месяц не маскирует неизвестную зарплату под известный ноль;
- неизвестное значение отличается от известного нуля;
- единый нормативный алгоритм закрывает месяцы по обе стороны `effective_from_month`;
- обязательный error code делает API/worker contract проверяемым;
- существующая БД мигрируется без выдумывания персональных данных;
- worker R02-03 получает однозначный storage/domain/API/seed contract.

### Ограничения

- при частичном добавлении истории до baseline налог за эти ранние месяцы может оставаться `incomplete`, пока владелец явно не пересоберёт opening context;
- reopening старого месяца временно делает зависящие от него последующие salary-tax расчёты incomplete до повторного close;
- контракт пока охватывает только действующую salary tax base (`IncomeType.SALARY`);
- автоматический импорт налоговой истории и отдельный полноценный UI редактирования tax-year context не входят в R02-02.

## Не принято этим ADR

- изменение налоговых ставок и порогов;
- включение bonus/side income/инвестиционных доходов в salary tax base;
- автоматическое получение данных работодателя или ФНС;
- пересчёт закрытых месяцев без явного пользовательского действия;
- cloud/auth/VPS/telemetry.
