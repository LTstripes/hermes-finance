# Hermes Finance

Локальное однопользовательское веб-приложение для ежемесячного учёта личных финансов. Hermes Finance показывает ликвидный капитал, фактический и прогнозный пассивный доход, расходы, долги, инвестиционные результаты и историю закрытых месяцев.

Приложение рассчитано на **Windows 10/11**, работает локально и по умолчанию слушает только `127.0.0.1`. Облачный аккаунт, авторизация, телеметрия и публичный доступ не нужны.

## Содержание

- [Требования](#требования)
- [Установка](#установка)
- [Первый запуск](#первый-запуск)
- [Приватный seed](#приватный-seed)
- [Ежемесячный workflow](#ежемесячный-workflow)
- [Backup и восстановление](#backup-и-восстановление)
- [Export](#export)
- [Обновление приложения](#обновление-приложения)
- [Типовые проблемы](#типовые-проблемы)
- [Что входит в MVP и ограничения](#что-входит-в-mvp-и-ограничения)
- [Для разработчика](#для-разработчика)
- [Приватность](#приватность)

## Требования

Установите:

- Windows 10 или Windows 11;
- Python **3.13**;
- [uv](https://docs.astral.sh/uv/);
- Node.js **22.22 или новее** и npm;
- современный браузер.

Docker, отдельный PostgreSQL и отдельный веб-сервер для локального MVP не требуются.

## Установка

Откройте PowerShell и выполните из каталога репозитория:

```powershell
Set-Location backend
uv sync --group dev
Set-Location ..\frontend
npm ci
Set-Location ..
```

`uv sync` устанавливает backend-зависимости по `backend/uv.lock`, а `npm ci` — frontend-зависимости по `frontend/package-lock.json`. При обновлении зависимостей используйте именно эти команды, а не произвольный `pip install` или `npm install`.

## Первый запуск

### Рекомендуемый production local build

Из корня репозитория:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Скрипт:

1. собирает frontend production bundle;
2. проверяет наличие `frontend/dist/index.html`;
3. запускает backend через `uv`;
4. проверяет API и HTML-интерфейс;
5. печатает URL;
6. останавливает backend после `Ctrl+C`.

После сообщения:

```text
Hermes Finance is ready: http://127.0.0.1:8000
```

откройте в браузере:

```text
http://127.0.0.1:8000
```

Для короткой проверки запуска с автоматической остановкой используйте:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -ExitAfterReady
```

`ExecutionPolicy Bypass` действует только для этого локального вызова PowerShell и не меняет системную политику Windows.

### Режим разработки

Если нужны hot reload и отдельные процессы, используйте:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

Интерфейс будет доступен на `http://127.0.0.1:5173`, а Vite проксирует `/api` в backend на `http://127.0.0.1:8000`. Для обычного использования владельцу достаточно production-команды выше.

### Проверка backend

В отдельном PowerShell можно проверить состояние API:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Ожидаемый результат содержит:

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

Первый экран пустого приложения нормален: сначала создайте отчётный месяц.

### Локальные настройки

Без настроек приложение использует SQLite-базу `data/finance.db` от корня репозитория и слушает только `127.0.0.1:8000`. Для ручных overrides скопируйте безопасный шаблон:

```powershell
Copy-Item .\backend\.env.example .\backend\.env
```

Основные переменные:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `HERMES_FINANCE_HOST` | `127.0.0.1` | адрес backend; не открывайте наружу без отдельного security review |
| `HERMES_FINANCE_PORT` | `8000` | локальный HTTP-порт |
| `HERMES_FINANCE_RELOAD` | `false` | reload для ручного dev-запуска |
| `HERMES_FINANCE_DATABASE_PATH` | `../data/finance.db` в `.env.example` | путь локальной SQLite-базы |
| `HERMES_FINANCE_FRONTEND_DIST` | `frontend/dist` | production frontend build |

Production launcher временно задаёт `127.0.0.1`, порт `8000`, `reload=false` и путь к свежему `frontend/dist`; после завершения он восстанавливает окружение PowerShell.

## Приватный seed

Private seed нужен, чтобы локально создать реальные счета и глобальные настройки без помещения персональных значений в Git. Seed загружается только в локальную SQLite-базу.

### Подготовка

1. Скопируйте безопасный синтетический пример:

   ```powershell
   Copy-Item .\docs\private_seed.example.json .\data\private_seed.json
   ```

2. Отредактируйте `data/private_seed.json` локально и замените synthetic values на свои.
3. Не добавляйте этот файл в Git и не вставляйте реальные значения в README, тесты, issue или логи.

Схема и пример находятся здесь:

- `docs/private_seed.schema.json`;
- `docs/private_seed.example.json`.

Файл по умолчанию должен лежать рядом с базой: `data/private_seed.json`.

### Загрузка

Из корня репозитория:

```powershell
Set-Location backend
$env:PYTHONPATH = ""
uv run hermes-finance-seed --database ..\data\finance.db --seed ..\data\private_seed.json
Set-Location ..
```

Команда валидирует seed и применяет его транзакционно. Повторный запуск безопасен: существующие счета обновляются, дубликаты account keys отклоняются. В выводе отображаются только количества созданных/обновлённых объектов; полные внешние коды не печатаются.

Если seed не нужен, пропустите этот раздел: приложение создаёт пустую локальную базу автоматически при первом запуске.

## Ежемесячный workflow

Рабочий сценарий рассчитан на один отчётный месяц за раз.

### 1. Создать месяц

1. Откройте **Месяцы**.
2. Создайте новый месяц и укажите `year`, `month` и `snapshot date`.
3. Откройте созданный draft.

Отчётный месяц и дата снимка хранятся отдельно: например, снимок можно внести 2 августа для отчёта за июль.

### 2. Внести доходы

В редакторе месяца заполните зарплату и дополнительные доходы:

- gross;
- премия;
- side income;
- cashback;
- фактический employer net.

Расчётный налог и net приходят из backend summary. Не вводите их как замену backend-расчёту и не считайте НДФЛ вручную в браузере. Cashback хранится отдельно и не считается пассивным доходом.

### 3. Зафиксировать активы

Заполните доступные секции редактора:

- депозиты и накопительные счета;
- cash balances;
- брокерские позиции;
- цены, количество и дату оценки;
- реальные и ожидаемые выплаты.

Market value, cost basis, unrealized result и ожидаемый процентный доход рассчитываются backend и только отображаются frontend.

### 4. Добавить бюджет и обязательства

При необходимости внесите:

- mandatory и прочие расходы;
- savings allocations;
- кредитные и прочие долги;
- недвижимость и ипотеку;
- IIS profile, contributions и tax benefits;
- комментарии к месяцу.

Недвижимость не входит в ликвидный капитал. Налоговая выгода IIS в MVP информационная и не является налоговой декларацией.

### 5. Проверить дашборд

На дашборде проверьте:

- ликвидный капитал;
- изменение за месяц;
- прогнозный и фактический пассивный доход;
- mandatory expenses и coverage;
- mortgage coverage;
- распределение активов;
- инвестиционный результат по счетам и классам;
- предупреждения расчёта.

Купоны, дивиденды и проценты относятся к пассивному доходу; погашение номинала облигации — отдельный денежный поток и не является доходом.

### 6. Закрыть месяц

После проверки нажмите **Закрыть месяц** и подтвердите действие. Закрытый месяц становится read-only. Для исправлений сначала используйте явное **Открыть заново**, затем после правок закройте месяц снова.

### 7. Создать следующий месяц

На странице месяцев используйте действие клонирования. Клон переносит состояния и snapshots, но фактические investment cash flows не копируются: новые купоны, дивиденды и другие события нужно вводить в соответствующем месяце заново.

## Backup и восстановление

Backup хранится локально рядом с базой, обычно в:

```text
data/backups/
```

Имена имеют формат:

```text
finance_backup_YYYYMMDDTHHMMSSffffffZ.sqlite3
```

### Создать backup

1. Откройте **Экспорт и бэкапы**.
2. Нажмите **Создать backup**.
3. Убедитесь, что новая копия появилась в списке.

Приложение использует SQLite online backup API, а не простое копирование открытого файла. Backup-каталог и базы исключены из Git.

### Восстановить backup

1. Откройте **Экспорт и бэкапы**.
2. Выберите нужную копию.
3. Нажмите **Восстановить**.
4. Прочитайте предупреждение и подтвердите действие.

Перед restore приложение автоматически создаёт pre-restore backup. Кандидат проверяется на целостность SQLite и совместимость схемы. Не заменяйте `data/finance.db` вручную во время работы приложения.

Перед важным импортом или массовым исправлением сначала создайте backup и убедитесь, что файл появился в списке.

## Export

1. Откройте **Экспорт и бэкапы**.
2. Выберите отчётный месяц.
3. Нажмите **Скачать Markdown** или **Скачать JSON**.

Файлы скачиваются браузером с безопасными именами:

```text
finance_report_YYYY-MM.md
finance_data_YYYY-MM.json
```

Markdown удобен для чтения и анализа в ChatGPT/Hermes. JSON содержит машинно-читаемые raw и derived данные, версии схемы/расчётов и однозначное денежное представление.

Export — read-only операция: он не изменяет данные месяца. Не отправляйте экспорт третьим лицам без проверки содержимого: в нём могут быть личные финансовые сведения.

## Обновление приложения

Перед обновлением:

1. Создайте backup через **Экспорт и бэкапы**.
2. Остановите приложение (`Ctrl+C` в окне запуска).
3. Закройте локальные окна/терминалы, которые используют проект.

Затем из корня рабочей копии:

```powershell
git pull --ff-only
Set-Location backend
uv sync --group dev
Set-Location ..\frontend
npm ci
Set-Location ..
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Локальные `data/`, `private/`, backup и export-файлы не должны попадать в commit. Если Git сообщает о незакоммиченных изменениях, сначала разберитесь с ними и не используйте `reset --hard` для «починки» обновления.

## Типовые проблемы

### `uv` или `npm` не найдены

Установите [uv](https://docs.astral.sh/uv/) и Node.js 22.22+, перезапустите PowerShell и повторите установку зависимостей.

### `Frontend dependencies are missing`

Выполните из корня:

```powershell
Set-Location frontend
npm ci
Set-Location ..
```

### Порт `8000` уже занят

Остановите старый экземпляр приложения. Найти процесс можно так:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
```

После этого завершите только найденный процесс и повторите запуск. Не запускайте несколько экземпляров на одной базе одновременно.

### Ошибка `pydantic_core` или импорт пакета из Hermes Agent

Это обычно означает, что backend получил чужой `PYTHONPATH`. Используйте launcher `scripts/start-local.ps1` или запускайте backend так:

```powershell
Set-Location backend
$env:PYTHONPATH = ""
uv run python -I -m pytest -q
uv run hermes-finance-api
Set-Location ..
```

### Приложение открылось, но месяцев нет

Это чистая база. Откройте **Месяцы** и создайте первый draft; затем заполните его вручную или загрузите локальный private seed для счетов и настроек.

### Backup не создаётся

Проверьте, что каталог рядом с базой доступен для записи и что база находится там, где ожидает настройка `HERMES_FINANCE_DATABASE_PATH`. Не создавайте backup вручную внутри открытого SQLite-файла; используйте кнопку приложения.

### Restore отклонён

Backup может быть повреждён, не быть SQLite-базой или иметь несовместимую схему. Не удаляйте автоматически созданный pre-restore backup; сначала сохраните диагностику и проверьте список копий.

### Нужны котировки или импорт PDF

Автоматические котировки MOEX и импорт PDF Альфа-Инвестиций не входят в текущий MVP. Цены и события для текущей версии вносятся вручную.

## Что входит в MVP и ограничения

Сейчас доступны:

- локальная SQLite-база;
- месячные snapshots и clone следующего месяца;
- зарплата, дополнительные доходы и прогрессивный НДФЛ;
- депозиты, cash, позиции и investment flows;
- расходы, savings, debts, properties и IIS closeout;
- dashboard KPI и графики;
- Markdown/JSON export;
- локальные backup и restore;
- приватный seed loader;
- production local build через один PowerShell launcher.

Осознанные ограничения:

- один локальный пользователь, без авторизации;
- нет публичного/VPS-режима и HTTPS-контура;
- нет автоматических котировок;
- нет PDF-импорта в обычном пользовательском workflow;
- разделы **Цели**, **Настройки** и справочник **Счета и инструменты** в основном UI пока содержат staged placeholders; базовые операции доступны из month editor и backend API;
- приложение не является бухгалтерской, налоговой или торговой системой.

## Для разработчика

### Backend

```powershell
Set-Location backend
uv run python -I -m pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
Set-Location ..
```

### Frontend

```powershell
Set-Location frontend
npm test -- --run
npm run lint
npm run format-check
npm run build
Set-Location ..
```

### Все локальные проверки

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\lint.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\format-check.ps1
python .\scripts\privacy_check.py
```

### Документы проекта

- [Changelog](CHANGELOG.md) — история релизов и известные ограничения.
- [Мастер-спецификация](docs/MASTER_SPEC.md) — бизнес-правила и границы продукта.
- [Backlog](docs/HERMES_TASKS.md) — последовательность задач и acceptance criteria.
- [Project Wiki](docs/PROJECT_WIKI.md) — принятые уточнения и журнал решений.
- [Архитектурные решения](docs/adr/) — ADR проекта.
- [Пример private seed](docs/private_seed.example.json) и [его schema](docs/private_seed.schema.json).

README описывает пользовательский MVP. Для изменения бизнес-правил сначала сверяйтесь с `docs/MASTER_SPEC.md`, а не с краткими примерами из этого файла.

## Приватность

Никогда не коммитьте:

- `data/` и SQLite-базы;
- `data/private_seed.json`;
- реальные номера счетов, ISIN, позиции и суммы;
- PDF/XLS/XLSX;
- exports и backups;
- `.env` и credentials.

Проверьте Git перед публикацией:

```powershell
git status --short
python .\scripts\privacy_check.py
```

Все примеры в tracked-файлах должны оставаться синтетическими. Локальные данные остаются на компьютере владельца.

## Лицензия

Лицензия пока не выбрана. Файл `LICENSE` намеренно отсутствует до отдельного решения владельца проекта.
