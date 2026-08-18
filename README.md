# Hermes Finance

Hermes Finance — локальное однопользовательское приложение для ежемесячного учёта личных финансов. Оно показывает ликвидный капитал, фактический и прогнозный пассивный доход, расходы, долги, инвестиционный результат, цели и историю закрытых месяцев.

Версия этого release candidate — **0.5.0**.

Приложение рассчитано на Windows 10/11, хранит данные в локальной SQLite-базе и по умолчанию слушает только `127.0.0.1:8000`. Облачный аккаунт, авторизация, телеметрия и публичный/VPS-режим сознательно не используются.

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

## Запуск

Рекомендуемый production local build:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Launcher:

1. собирает production frontend;
2. применяет `alembic upgrade head`;
3. запускает backend на `127.0.0.1:8000`;
4. проверяет `/api/health`, `/api/months` и HTML-интерфейс;
5. освобождает порт после остановки.

После готовности откройте:

```text
http://127.0.0.1:8000
```

Короткий production smoke с автоматической остановкой:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -ExitAfterReady
```

Dev-режим с Vite:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

Frontend будет на `127.0.0.1:5173`, `/api` проксируется в локальный backend.

Для котировок 0.4 и выплат 0.5 нужен локальный **read-only** токен T-Invest в **корневом** `.env` репозитория (`HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN=`), рядом с `.env.example`. Не кладите его в `backend/` и не коммитьте. Не выпускайте Full Access / Transfer. Запрос к T-Invest уходит только после явной кнопки владельца. Подробности: `docs/t-invest-market-data.md`.

### Health

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Для 0.5.0 ожидается:

```json
{
  "status": "ok",
  "version": "0.5.0"
}
```

## Что доступно в 0.5.0

Основной UI больше не содержит staged placeholders для ключевых разделов. Доступны:

- **Дашборд** — KPI, графики капитала/пассивного дохода, распределение активов, инвестиционный результат и основная цель;
- **Месяцы** — draft/closed lifecycle, клонирование, ввод данных, reopen/close и безопасное удаление draft вместе с его месячными данными;
- **Счета и инструменты** — справочники счетов и инструментов;
- **Цели** — CRUD целей, выбор основной цели и backend-derived progress/forecast status;
- **Экспорт и бэкапы** — Markdown/JSON export, SQLite online backup и защищённый restore;
- **Настройки** — базовые настройки и управление годовой шкалой НДФЛ с защитой истории закрытых месяцев;
- **Рыночные котировки** — явная привязка инструмента к T-Invest, preview по кнопке владельца и выборочный apply с неизменяемой историей provenance;
- **Автоматические выплаты** — явная загрузка купонов/дивидендов/погашений из T-Invest, preview, выборочный apply и объединённый календарь с ручными ожидаемыми выплатами.

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

### Календарь ожидаемых выплат

В **0.5.0** календарь объединяет ручные ожидаемые выплаты и уже применённые события провайдера.

- количество для провайдерской выплаты берётся из локального `PositionSnapshot`, не из брокерского портфеля;
- apply не редактирует и не удаляет ручные `expected_cash_flows`;
- неразрешённый дубль считается только вручную, пока владелец явно не выберет `keep_both`, `count_manual` или `count_provider`;
- применённые купоны провайдера входят в прогноз C04; объявленные дивиденды видны в календаре, но не заменяют исторический dividend component; погашение — денежный поток, не пассивный доход;
- наступление даты события не создаёт фактическую инвестиционную выплату.

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

## Обновление приложения

1. Создайте backup.
2. Остановите приложение.
3. Выполните:

```powershell
git pull --ff-only
Set-Location backend
uv sync --group dev
Set-Location ..\frontend
npm ci
Set-Location ..
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Launcher сам применит Alembic migrations перед readiness-check.

## Известные ограничения 0.5.0

- только один локальный пользователь, без auth/cloud/VPS/HTTPS;
- котировки и выплаты T-Invest только после явного preview/apply владельца; фонового обновления, polling и startup-сети нет; MOEX не является production fallback;
- позиции остаются локальными данными Hermes; брокерский портфель/счета не импортируются;
- суммы провайдера могут оставаться приблизительными, если нет личной налоговой/net-уверенности;
- PDF-импорт Альфа-Инвестиций не входит в обычный пользовательский workflow;
- точная time-weighted/Money-weighted доходность с датированными внешними потоками отложена;
- приложение не является бухгалтерской, налоговой или торговой системой.

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

Публикация релиза — только после явного решения владельца и только с exact `origin/main` SHA:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release.ps1 `
  -Version 0.5.0 `
  -ExpectedMainSha <полный-40-символьный-sha> `
  -ReleaseNotes .\docs\release-notes-0.5.0.md
```

Хелпер не двигает ветки, не делает force-update тега, не создаёт коммиты и не читает `.env`.

Verification policy: [`docs/VERIFICATION_POLICY.md`](docs/VERIFICATION_POLICY.md).

## Документы проекта

- [`docs/MASTER_SPEC.md`](docs/MASTER_SPEC.md) — бизнес-инварианты и границы продукта;
- [`docs/releases/0.5.0.md`](docs/releases/0.5.0.md) — current 0.5 release candidate;
- [`docs/release-notes-0.5.0.md`](docs/release-notes-0.5.0.md) — public notes for the later guarded release helper;
- [`docs/releases/0.4.0.md`](docs/releases/0.4.0.md) — historical release 0.4 archive;
- [`docs/releases/0.3.0.md`](docs/releases/0.3.0.md) — historical release 0.3 archive;
- [`docs/releases/0.2.0.md`](docs/releases/0.2.0.md) — historical release 0.2 archive;
- [`docs/MODEL_ROUTING.md`](docs/MODEL_ROUTING.md) — модельный routing;
- [`docs/HERMES_START_PROMPT.md`](docs/HERMES_START_PROMPT.md) — рабочий протокол;
- [`docs/HERMES_TASKS.md`](docs/HERMES_TASKS.md) — исторический backlog MVP 0.1;
- [`docs/PROJECT_WIKI.md`](docs/PROJECT_WIKI.md) — долгоживущий контекст;
- [`CHANGELOG.md`](CHANGELOG.md) — релизные изменения.

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
