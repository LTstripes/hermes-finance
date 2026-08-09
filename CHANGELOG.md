# Changelog

Все заметные изменения Hermes Finance фиксируются в этом файле.

## [0.1.0] — 2026-08-09

Первый локальный MVP для ежемесячного контроля личных финансов.

### Добавлено

- локальный FastAPI + React/Vite application на SQLite;
- production local build с единым PowerShell launcher на `127.0.0.1:8000`;
- месячные snapshots, draft/closed lifecycle и clone следующего месяца;
- зарплата, прогрессивный НДФЛ, премии и дополнительные доходы;
- депозиты, cash balances, брокерские позиции и backend-расчёт market value;
- фактические и ожидаемые investment cash flows;
- расходы, savings allocations, долги, недвижимость и ипотека;
- IIS profile, contributions и информационные tax benefits;
- comments и month closeout;
- dashboard KPI, capital/passive-income charts и asset allocation;
- инвестиционный результат по счетам и инструментальным классам;
- Markdown и JSON export с безопасными именами файлов;
- SQLite online backup, список backup и защищённый restore с pre-restore backup;
- локальный private seed loader без вывода полных внешних кодов;
- backend API, frontend component tests и Playwright smoke coverage;
- privacy guard для tracked paths/content и пользовательская документация запуска.

### Известные ограничения

- MVP рассчитан на одного пользователя на локальном Windows-компьютере; авторизации, облачного режима, VPS и HTTPS нет;
- котировки MOEX не обновляются автоматически, цены вводятся вручную;
- импорт PDF Альфа-Инвестиций не входит в обычный пользовательский workflow;
- страницы «Цели», «Настройки» и справочник «Счета и инструменты» в основном frontend navigation пока содержат staged placeholders;
- приложение не является бухгалтерской, налоговой или торговой системой;
- private seed, база, exports и backups должны оставаться локальными и не попадать в Git.

[0.1.0]: https://github.com/LTstripes/hermes-finance/releases/tag/v0.1.0
