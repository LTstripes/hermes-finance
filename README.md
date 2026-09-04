# Hermes Finance

Hermes Finance — локальное однопользовательское приложение для ежемесячного учёта личных финансов. Оно показывает ликвидный капитал, фактический и прогнозный пассивный доход, расходы, долги, инвестиционный результат, цели и историю закрытых месяцев.

Опубликованная стабильная идентичность **0.8.0** — неизменяемый Git-тег `v0.8.0`, peel'ящийся в exact released main SHA `ec185deab8d3fe949e7d579e5041d23216a6d73f`. Exact-head PR CI run `33665746651`, post-merge exact-main CI run `33668924186` и guarded Release run `33669922698` завершились успешно; публикация состоялась 2026-09-02. Предрелизный Preview UAT сознательно не заявляется как пройденный: owner acceptance выполняется на released Stable 0.8.0, а найденные дефекты оформляются отдельными follow-up/patch задачами.

Приложение рассчитано на Windows 10/11, хранит данные в локальной SQLite-базе и по умолчанию слушает только `127.0.0.1:8000`. Облачный аккаунт, авторизация, телеметрия и публичный/VPS-режим сознательно не используются.

Продакшен запускается из **runtime-checkout**: в нём лежат локальные ignored-данные (`.env`, SQLite, backup, private files). Разработка и работа агентов идут в **отдельном чистом clone**. Не копируйте и не пробрасывайте runtime-данные в dev-clone через copy, symlink, junction, hardlink или любой другой filesystem indirection.

## Требования

- Windows 10/11;
- Python 3.13;
- [uv](https://docs.astral.sh/uv/);
- Node.js 22.22+ и npm;
- современный браузер.

Docker, PostgreSQL и отдельный веб-сервер для локального использования не требуются.

## Установка

Из корня репозитория:

```powershell
Set-Location backend
uv sync --group dev
Set-Location ..\frontend
npm ci
Set-Location ..
```

Backend-зависимости фиксируются `backend/uv.lock`, frontend-зависимости — `frontend/package-lock.json`.

## Запуск — launcher-first (Windows)

**Каноническая owner-точка входа — Windows launcher.** Никаких логов, PowerShell, Git и ручного JSON для обычного запуска.

1. Установите launcher один раз из подготовленного checkout (pinned релиз `v0.8.0`):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\launcher\windows\install.ps1
```

Скрипт собирает `HermesFinance.Launcher.exe`, кладёт его в `%LOCALAPPDATA%\HermesFinance\launcher` (branded cat icon), создаёт ярлыки на Desktop и Start menu. Ярлыки не зависят от ephemeral checkout.

2. Откройте **Hermes Finance** (Desktop/Start menu) — выберите карту:

 - **Stable** — pinned production runtime: показывает `Release v0.8.0` + короткий SHA + `Canonical production data` (зелёный акцент). Это единственная карточка, которая может открыть production DB.
 - **Preview** — `main / UNRELEASED` + `Isolated UAT / synthetic data` (фиолетовый), показывает `main <cur> → <target> · UNRELEASED`. Никогда не смешивает данные с Stable.

3. Нажмите **одну очевидную primary кнопку** по состоянию (ровно одна подсвечена):

 - `Обновить Preview` / `Обновить и запустить` — только для Preview, явный owner action, `fetch origin/main` + `ff-only` только для настроенного Preview checkout;
 - `Подготовить` — явная установка только missing/stale locked зависимостей (`uv sync --locked`, `npm ci`);
 - `Исправить` — принудительное восстановление обеих locked-сред;
 - `Запустить` — обычный старт без download/install;
 - `Открыть Hermes` — только после health probes, `http://127.0.0.1:8000`;
 - `Остановить` — останавливает запущенный guarded startup.

Проверка перед стартом (человеческим языком, кратко):

 - **Code identity** — совпадает ли checkout с ожидаемым `expected_ref` (Stable: `refs/tags/v0.8.0`, Preview: `refs/remotes/origin/main`);
 - **Data boundary** — защита от alias production (path + file-id + sidecar `.hermes-data-identity.json`);
 - **Locked dependencies** — `backend pyproject/uv.lock` + `frontend package-lock/node_modules` (offline `uv --offline --dry-run`, `npm ls --json`);
 - **Loopback service** — `127.0.0.1:8000` свободен + `alembic`/схема совместима (offline, миграция — только в guarded startup).

Raw-диагностика — вторичный слой: кнопка `Диагностика и логи` (скрыта по умолчанию, не меняет поведение). Конфиг `%LOCALAPPDATA%\HermesFinance\launcher\config.json` создаётся/мигрируется launcher’ом автоматически где безопасно и однозначно; обычный workflow не требует ручного редактирования JSON.

После готовности откройте:

```text
http://127.0.0.1:8000
```

### Recovery-only (не для обычного запуска)

> PowerShell/Git/ручное JSON — только для восстановления, когда launcher сообщил о блокере и показал корректное действие.

Короткий production smoke с автоматической остановкой (без launcher):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -ExitAfterReady
```

Ручной guarded startup (что делает launcher под капотом):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

 - собирает production frontend;
 - применяет `alembic upgrade head` к **той же** validated DB (`HERMES_FINANCE_DATABASE_PATH`);
 - запускает backend на `127.0.0.1:8000`;
 - проверяет `/api/health`, `/api/months` и HTML;
 - освобождает порт после остановки.

Dev-режим с Vite (только для разработки):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

Frontend будет на `127.0.0.1:5173`, `/api` проксируется в локальный backend.

Для котировок 0.4 и выплат 0.5 нужен локальный **read-only** токен T-Invest в **корневом** `.env` репозитория (`HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN=`), рядом с `.env.example`. Не кладите его в `backend/` и не коммитьте. Не выпускайте Full Access / Transfer. Запрос к T-Invest уходит только после явной кнопки владельца. Подробности: `docs/t-invest-market-data.md`.

### Health

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Для 0.8.0 ожидается:

```json
{
  "status": "ok",
  "version": "0.8.0"
}
```

## Что доступно в 0.8.0

Released `0.8.0` фиксирует owner-workflow release поверх принятого R07/R08 tree: Guided Monthly Close Wizard объединяет monthly close, Alfa/reconciliation, T-Invest/provider steps, final review и explicit Close/Reopen в один локальный workflow; добавлены safe instrument cleanup и explicit portfolio review handoff в JSON/Markdown. Все provider- и owner-triggered действия остаются явными, а вычисления и финансовые границы — backend-authoritative. Доступны:

- **Дашборд** — KPI, графики капитала/пассивного дохода, распределение активов, инвестиционный результат и основная цель;
- **Месяцы** — draft/closed lifecycle, клонирование, ввод данных, reopen/close и безопасное удаление draft вместе с его месячными данными;
- **Счета и инструменты** — справочники счетов и инструментов;
- **Цели** — CRUD целей, выбор основной цели и backend-derived progress/forecast status;
- **Экспорт и бэкапы** — Markdown/JSON export, SQLite online backup и защищённый restore;
- **Настройки** — базовые настройки и управление годовой шкалой НДФЛ с защитой истории закрытых месяцев;
- **Рыночные котировки** — явная привязка инструмента к T-Invest, preview по кнопке владельца и выборочный apply с неизменяемой историей provenance;
- **Автоматические выплаты** — явная загрузка купонов/дивидендов/погашений из T-Invest, preview, выборочный apply и объединённый календарь с ручными ожидаемыми выплатами;
- **Снимок Alfa PRO** — явная кнопка владельца, только локальный loopback терминала, persistent owner-confirmed registry счетов/инструментов и owner-approved baseline quantity apply с provenance; Price/UchPrice/NKD/P&L остаются сравнением, а выборочный apply безопасного поднабора не блокируется unrelated unresolved/conflicting rows;
- **PDF выплат Alfa** — только принятый депозитарный отчёт `Отчет о произведенных выплатах доходов по ценным бумагам`: Inspect → mapping → Prepare → явный selected Apply, без OCR и без generic import; ошибочно применённую строку можно auditable-отменить (`Отменить импорт` / `Отвязать выписку`) без молчаливого уничтожения provenance.
- **AI Analysis Bundle** — schema-valid read-only JSON для явного owner download; он не вызывает LLM/cloud, не пишет в базу и не заменяет финансовые формулы.
- **Monthly Close Cockpit** — серверный checklist из blockers, warnings и context; `can_close` следует hard guards закрытия, а advisory warnings не превращаются в блокировки.
- **Cash-flow Ladder / upcoming treasury events** — читаемая лестница ближайших датированных выплат и других treasury events; redemption principal остаётся капиталом, а не passive income.
- **Risk & Allocation** — allocation выбранного месяца по persisted RUB valuation и явным asset-class/account/top-position с концентрацией payout/redemption; отсутствие metadata остаётся unavailable state, а не risk score или рекомендацией.
- **Freshness & Provenance Center** — persisted source/freshness clocks и reason codes без universal score и без background refresh.
- **Reconciliation Center** — explicit read-only snapshot preview с normalized row states и compatibility diagnostics; provider Price/UchPrice/NKD/P&L — comparison-only и не перезаписывают Hermes.
- **Tax/IIS Planner** — current-state v1 для фактических и текущих налоговых данных; расширение projection scope отложено.
- **Deterministic Insights backend v1** — read-only persisted-evidence rules без LLM и future prediction; полного UI/AI-bundle integration в 0.7.0 не заявляется.
- **XIRR и exact TWRR** — XIRR доступен для whole portfolio при однозначном валидном корне; TWRR использует persisted observed valuation boundaries и pre/post observations для потоков. Missing/gapped evidence, неизвестный порядок событий и неоднозначный XIRR root fail closed.
- **Windows Stable/Preview launcher** — guarded runtime profiles, owner Prepare/Repair/Start/Stop controls, explicit Preview update, package/install verification и shortcut/start-stop smoke; Stable остаётся на pinned release identity, Preview — на отдельном unreleased checkout.
- **UI и verification** — visual-audit polish, semantic test-taxonomy work и backend CI входят в release evidence; Backend timeout временно поднят с 15 до 30 минут как release unblock, а durable split/slow-test telemetry tracked в #282.

В редакторе месяца доступны зарплата и прочие доходы, депозиты/cash, позиции, фактические и ожидаемые investment flows, расходы/savings, долги/недвижимость, ИИС и комментарии.

## Ежемесячный workflow

1. Создайте новый draft в **Месяцы** или клонируйте предыдущий месяц.
2. Заполните зарплату, доходы и фактический employer net. Расчётный НДФЛ/net и текущая применённая ставка приходят из backend; frontend не рассчитывает налог самостоятельно.
3. Обновите депозиты, cash и позиции. Для акций количество должно быть положительным целым; для типов, где дробное количество допустимо, сохраняется точная decimal-семантика.
4. Добавьте фактические инвестиционные выплаты. Купон, дивиденд и процент нужно выбирать по фактическому типу события; погашение номинала не считается доходом.
5. При необходимости внесите ожидаемые выплаты вручную или откройте **Автоматические выплаты**, сделайте preview по выбранной позиции и явно примените нужные события. Ручные записи не перезаписываются.
6. Проверьте Dashboard/closeout warnings.
7. Закройте месяц. Закрытый месяц read-only; для исправления сначала явно выполните reopen.
8. Создайте следующий месяц.

### История НДФЛ и backfill

Прогрессивный НДФЛ использует YTD-историю текущего календарного года. Известным считается только `closed` reporting month; draft не трактуется как известный ноль. Если детальная история приложения начинается позже января, используйте annual opening tax context по принятому ADR. Неполная налоговая история не должна блокировать редактирование старого draft: недоступной остаётся только расчётная налоговая часть.

Шкала НДФЛ администрируется целиком на календарный год. После появления закрытого месяца этого года шкала защищена от молчаливого ретроактивного изменения; для сознательного изменения исторического года сначала требуется явный reopen соответствующих закрытых месяцев.

## Пассивный доход и прогноз

Фактические выплаты не размазываются по истории: дивиденд остаётся целиком в месяце фактического получения. Для прогнозного dividend component используется среднее фактических net-дивидендов по доступным закрытым месяцам, максимум за последние 12 месяцев.

Основная passive-income цель использует rolling average фактического net passive income по закрытым месяцам (до последних 12). Это же фактическое среднее является `Текущим значением` и источником прогресса цели. C04 forecast остаётся отдельной прогнозной метрикой и не подменяет фактический прогресс; при истории короче 12 месяцев UI явно показывает, сколько закрытых месяцев учтено.

Автоматический deposit component прогноза строится из `DepositSnapshot.expected_monthly_interest_kopecks` выбранного месяца и annualises monthly estimate × 12. Это приблизительная оценка: maturity и изменения ставки не моделируются. Ручной expected `interest` остаётся additive.

### Календарь ожидаемых выплат

В **0.8.0** календарь объединяет ручные ожидаемые выплаты и уже применённые события T-Invest; раскрытие месяца очевидно, а expanded rows показывают instrument/company первично, account вторично, source/provenance, amount и redemption-as-capital context. `Ручные ожидаемые выплаты` остаются manual-only/additive и стоят после merged calendar в DOM. Alfa statement import — отдельный явный путь фактических выплат, не автозаполнение календаря.

- количество для провайдерской выплаты берётся из локального `PositionSnapshot`, не из брокерского портфеля;
- apply не редактирует и не удаляет ручные `expected_cash_flows`;
- неразрешённый дубль считается только вручную, пока владелец явно не выберет `keep_both`, `count_manual` или `count_provider`;
- применённые купоны провайдера входят в прогноз C04; объявленные дивиденды видны в календаре, но не заменяют исторический dividend component; погашение — денежный поток, не пассивный доход;
- наступление даты события не создаёт фактическую инвестиционную выплату.

### Cash-flow Ladder

Cash-flow Ladder показывает ближайшие датированные upcoming treasury events поверх локальных данных и различает income events и возврат капитала. Отсутствующие дата, scope или provenance не заполняются догадкой; reconciliation и provider comparison остаются отдельными явными путями.

## Приватный seed

Реальные стартовые счета и настройки можно загрузить только локально. Скопируйте синтетический пример:

```powershell
Copy-Item .\docs\private_seed.example.json .\data\private_seed.json
```

Отредактируйте `data/private_seed.json` локально. Файл, база и реальные значения не должны попадать в Git.

Загрузка:

```powershell
Set-Location backend
$env:PYTHONPATH = ""
uv run hermes-finance-seed --database ..\data\finance.db --seed ..\data\private_seed.json
Set-Location ..
```

## Backup и восстановление

Перед обновлением приложения, массовым backfill или потенциально рискованной операцией создайте backup в **Экспорт и бэкапы**. Backup создаётся через SQLite online backup API.

Restore:

- выполняется только после явного подтверждения;
- перед восстановлением создаёт pre-restore backup;
- проверяет целостность SQLite и совместимость схемы;
- сериализован с другими DB-maintenance операциями.

Не заменяйте `data/finance.db` вручную во время работы приложения.

## Export

В **Экспорт и бэкапы** доступны:

```text
finance_report_YYYY-MM.md
finance_data_YYYY-MM.json
```

Export read-only и не изменяет месяц. Файлы могут содержать личные финансовые данные — проверяйте их перед передачей третьим лицам.

## Обновление приложения — через launcher ( Stable pinned )

1. Создайте backup в **Экспорт и бэкапы**.
2. Остановите Hermes в launcher (`Остановить`) или закройте окно — `127.0.0.1:8000` должен освободиться.
3. Подготовьте **отдельный Stable checkout** на неизменяемом release tag ( `git fetch origin && git switch --detach refs/tags/v0.8.0` ); launcher сам Git не меняет — это recovery-шаг вне ежедневного `Запустить`.
4. Для обновления packaged launcher и ярлыков выполните **из этого подготовленного checkout**:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\launcher\windows\install.ps1
```

5. Откройте **Hermes Finance — Stable** в launcher. Launcher покажет `Release v0.8.0 · SHA <short> · production data` ( зелёная карточка ) и человеческую сводку 4 checks. Если зависимости missing/stale — единственная primary будет `Подготовить` ( `Исправить` — для принудительного восстановления ); обычный `Запустить` никогда не качает скрытно. После `Запустить` guarded startup применит Alembic к той же validated DB на `127.0.0.1:8000`.

## Известные ограничения 0.7.0

- только один локальный пользователь, без auth/cloud/VPS/HTTPS;
- котировки и выплаты T-Invest только после явного preview/apply владельца; изменение количества позиции не запускает background refresh, polling или startup-сеть; MOEX не является production fallback;
- снимок Alfa PRO только после явной кнопки и только к локальному терминалу; нет background refresh, browser → Alfa WebSocket и trading/order/signing API;
- PDF-импорт Alfa — только принятое семейство депозитарного отчёта о выплатах доходов, text layer, без OCR; это не generic import брокерского портфеля, сделок или банковских транзакций;
- Alfa account/instrument mapping хранится только после owner confirmation; account/instrument/month из провайдера или PDF автоматически не создаются, а baseline quantity apply требует отдельного owner approval и сохраняет provenance;
- суммы провайдера могут оставаться приблизительными, если нет личной налоговой/net-уверенности;
- XIRR/TWRR не вычисляются при неполной persisted evidence, пропущенной valuation boundary, неизвестном same-day order или неоднозначном XIRR root; первая TWRR API-поверхность ограничена whole portfolio;
- приложение не является бухгалтерской, налоговой или торговой системой.

### Явно отложено за пределы 0.7.0

- #141 Scenario Lab;
- #142 projection expansion за пределы current-state Tax/IIS v1;
- #143 Insights UI и AI Analysis Bundle integration за пределами deterministic backend v1;
- #203 Phase 2B test rehome/dedupe;
- #202 residual workspace/ACL cleanup;
- #229 owner workflow/Alfa UX consolidation.

## Типовые проблемы

### Порт 8000 занят

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
```

Остановите только старый экземпляр Hermes Finance и повторите запуск. Не запускайте несколько процессов на одной локальной базе.

### `uv`/`npm` не найдены

Установите uv и Node.js 22.22+, затем перезапустите PowerShell.

### `pydantic_core` или чужой `PYTHONPATH`

Используйте штатный launcher. Для ручного backend-запуска:

```powershell
Set-Location backend
$env:PYTHONPATH = ""
uv run python -I -m pytest -q
uv run hermes-finance-api
Set-Location ..
```

### Месяцев нет

Это нормальное состояние чистой базы. Создайте первый draft в **Месяцы**.

## Для разработчика

### Безопасная очистка Windows workspaces

Сначала выполните явный remote refresh и dry-run:

`./scripts/cleanup-finance-workspaces.ps1 -RefreshRemote`

Для удаления Git worktrees нужны оба явных флага:

`./scripts/cleanup-finance-workspaces.ps1 -RefreshRemote -Apply`

`-Apply` без `-RefreshRemote` отклоняется, если Git worktrees не отключены.
Artifact-only режим `-Apply -SkipGitWorktrees` не требует remote refresh.
Dirty/unmerged/unknown paths, launcher profiles, `.env`, SQLite, недоступные
деревья и reparse points скрипт сохраняет fail-closed.

Перед новой задачей в чистом development clone синхронизируйтесь с каноническим `main` так, как описано в [`AGENTS.md`](AGENTS.md). Не делайте `switch`/`reset`/`pull` поверх незаконченной task-работы.

Карта semantic test lanes, ownership и правило добавления новых регрессий описаны в [`docs/TEST_SUITE_GUIDE.md`](docs/TEST_SUITE_GUIDE.md).

Backend:

```powershell
Set-Location backend
uv run python -I -m pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
Set-Location ..
```

Frontend:

```powershell
Set-Location frontend
npm test -- --run
npm run lint
npm run format-check
npm run build
Set-Location ..
```

Общие проверки:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\lint.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\format-check.ps1
python .\scripts\privacy_check.py
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\tests\test-release.ps1
```

Публикация `0.7.0` выполнена через guarded release process; её immutable identity и exact-main CI зафиксированы выше. Для будущих релизов применяется тот же процесс с exact `origin/main` SHA:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release.ps1 `
  -Version 0.7.0 `
  -ExpectedMainSha <полный-40-символьный-sha-принятого-origin/main> `
  -ReleaseNotes .\docs\release-notes-0.7.0.md
```

Хелпер не двигает ветки, не делает force-update тега, не создаёт коммиты и не читает `.env`.

В release line 0.7.0 backend CI job имеет timeout 15 минут. Это не меняет локальный loopback/no-cloud/no-auth safety boundary.

Verification policy: [`docs/VERIFICATION_POLICY.md`](docs/VERIFICATION_POLICY.md).

## Документы проекта

Active:

- [`AGENTS.md`](AGENTS.md) — конституция репозитория для агентов;
- [`docs/agents/`](docs/agents/) — адаптеры клиентов (Codex, Hermes, Grok, Gemini);
- [`docs/MASTER_SPEC.md`](docs/MASTER_SPEC.md) — бизнес-инварианты и границы продукта;
- [`docs/MODEL_ROUTING.md`](docs/MODEL_ROUTING.md) — роли, класс риска и эскалация;
- [`docs/VERIFICATION_POLICY.md`](docs/VERIFICATION_POLICY.md) — стратегия проверок;
- [`docs/PROJECT_WIKI.md`](docs/PROJECT_WIKI.md) — долгоживущий контекст;
- [`docs/EXECUTION_HISTORY.md`](docs/EXECUTION_HISTORY.md) — журнал исполнения;
- [`CHANGELOG.md`](CHANGELOG.md) — релизные изменения;
- [`docs/releases/0.7.0.md`](docs/releases/0.7.0.md) — опубликованный 0.7.0 release record;
- [`docs/release-notes-0.7.0.md`](docs/release-notes-0.7.0.md) — public notes опубликованного 0.7.0.

Исторические release records 0.6.3 и старше остаются без переписывания.

Historical:

- [`docs/history/`](docs/history/) — архив старых Hermes process/backlog документов;
- [`docs/releases/`](docs/releases/) — исторические release records, включая [`0.6.2`](docs/releases/0.6.2.md), [`0.6.1`](docs/releases/0.6.1.md), [`0.6.0`](docs/releases/0.6.0.md), [`0.5.0`](docs/releases/0.5.0.md) и [`0.4.0`](docs/releases/0.4.0.md);
- [`docs/reviews/`](docs/reviews/) — исторические review notes;
- [`sketches/`](sketches/) — исторические UI-эскизы, не source of truth.

## Приватность

Никогда не коммитьте `data/`, SQLite-базы, private seed, реальные account identifiers/позиции/суммы, PDF/XLS/XLSX, exports, backups, `.env` или credentials.

Перед публикацией:

```powershell
git status --short
python .\scripts\privacy_check.py
```

Все tracked-примеры должны оставаться синтетическими.

## Лицензия

Лицензия пока не выбрана; `LICENSE` намеренно отсутствует до отдельного решения владельца.
