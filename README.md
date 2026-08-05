# Hermes Finance

Локальное однопользовательское веб-приложение для ежемесячного учёта личных финансов, анализа ликвидного капитала, фактического и прогнозного пассивного дохода, расходов и финансовых целей.

Проект развивается небольшими последовательными задачами. Сейчас доступны минимальный FastAPI backend, React frontend с проверкой подключения и конфигурация локальной SQLite через SQLAlchemy 2; схема данных, миграции и финансовая логика ещё не реализованы.

## Быстрый старт на Windows

Требования: Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22.22+ и npm. Один раз установите зависимости из корня репозитория:

```powershell
Set-Location backend
uv sync --group dev
Set-Location ..\frontend
npm ci
Set-Location ..
```

Запустите backend и frontend одной командой:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

После сообщения `Hermes Finance is ready` откройте `http://127.0.0.1:5173`. Нажмите `Ctrl+C`, чтобы остановить оба процесса. Локальный `-ExecutionPolicy Bypass` нужен для запуска доверенного локального скрипта при системной политике `Restricted`; политика Windows при этом не изменяется.

Все backend/frontend тесты и production build запускаются из корня:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

Скрипты заранее проверяют `uv`, `npm`, структуру проекта и frontend-зависимости и выводят конкретную команду исправления. Для короткой проверки запуска с автоматической остановкой доступен `dev.ps1 -ExitAfterReady`.

Проверки стиля также запускаются из корня для обеих частей проекта:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\lint.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\format-check.ps1
```

Backend проверяется Ruff, frontend — Biome. `format-check.ps1` ничего не перезаписывает. Для применения форматирования используйте `uv run ruff format .` в `backend` и `npm run format` во `frontend`.

## Continuous Integration

GitHub Actions workflow `.github/workflows/ci.yml` запускается для push в `main` и pull request. Независимые backend/frontend jobs устанавливают только lockfile-зависимости, выполняют lint, format-check, тесты и frontend build. CI не читает локальную базу, `data/`, `private/`, `.env` или GitHub secrets.

## Backend: установка и запуск

Требования: Python 3.13 и [uv](https://docs.astral.sh/uv/). Версия Python закреплена в `backend/.python-version`: Python 3.13 корректно обрабатывает UTF-8 пути editable-пакетов на Windows, включая каталог `Рабочий стол`.

```bash
cd backend
uv sync --group dev
uv run hermes-finance-api
```

По умолчанию API слушает только `http://127.0.0.1:8000`. Проверка:

```bash
curl http://127.0.0.1:8000/api/health
```

Ожидаемый ответ:

```json
{"status":"ok","version":"0.1.0"}
```

Локальные настройки можно задать через environment variables или файл `backend/.env`, используя `backend/.env.example` как безопасный шаблон:

| Переменная | Значение по умолчанию | Назначение |
|---|---:|---|
| `HERMES_FINANCE_HOST` | `127.0.0.1` | адрес Uvicorn; не открывать наружу без отдельного решения по безопасности |
| `HERMES_FINANCE_PORT` | `8000` | локальный HTTP-порт |
| `HERMES_FINANCE_RELOAD` | `false` | автоматическая перезагрузка dev-сервера |
| `HERMES_FINANCE_DATABASE_PATH` | `./data/finance.db` от корня репозитория | путь локальной SQLite; содержимое `data/` не попадает в Git |

При запуске backend создаёт родительский каталог базы, конфигурирует SQLAlchemy engine/session и включает SQLite foreign keys для каждого соединения. Относительный override из `backend/.env.example` рассчитан на запуск из каталога `backend`. Автотесты используют только временные синтетические базы и не открывают production path.

### Тесты backend

```bash
cd backend
uv run python -I -m pytest
```

`-I` не позволяет внешнему `PYTHONPATH` подмешивать пакеты из окружения Hermes или других Python-проектов.

## Frontend: установка и запуск

Требования: Node.js 22.22+ и npm. Backend должен работать в отдельном терминале на `127.0.0.1:8000`.

```bash
cd frontend
npm ci
npm run dev
```

Frontend откроется на `http://127.0.0.1:5173`. Vite проксирует запросы `/api` в локальный backend, поэтому браузеру не требуется отдельная CORS-конфигурация.

### Тесты и production build frontend

```bash
cd frontend
npm test
npm run build
```

## Документы

- [Мастер-спецификация](docs/MASTER_SPEC.md) — бизнес-правила, границы продукта и требования.
- [Последовательный backlog](docs/HERMES_TASKS.md) — задачи и критерии приёмки.
- [Стартовый протокол Hermes](docs/HERMES_START_PROMPT.md) — правила рабочей итерации.
- [Project Wiki](docs/PROJECT_WIKI.md) — принятые уточнения и долговременный контекст.
- [Архитектурные решения](docs/adr/) — ADR проекта.

## Приватность

Реальные финансовые данные, номера счетов, базы SQLite, PDF/XLSX, экспорты и резервные копии не должны попадать в Git. Они хранятся только локально в исключённых каталогах, прежде всего `data/` и `private/`.

В коде, тестах и документации используются только синтетические примеры.

## Лицензия

Лицензия пока не выбрана. Файл `LICENSE` намеренно отсутствует до решения владельца проекта.
