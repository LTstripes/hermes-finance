# Changelog

Все заметные изменения Hermes Finance фиксируются в этом файле.

## [0.4.0] — 2026-08-16

Release candidate for owner-triggered T-Invest market quotes with preview, selective apply and append-only provenance.

### Added

- provider-neutral market identity (`provider` + `provider_instrument_id` + optional `provider_venue_id`);
- T-Invest read-only production market-data path: instrument mapping, quote preview and selective apply;
- explicit owner-triggered quote preview with no startup or background refresh;
- selective explicit apply, atomic selected-set semantics and a `preview_changed` guard;
- append-only immutable snapshot-scoped quote provenance that survives later manual or mapping edits;
- sanitized provider-failure and manual-fallback UX for editable months.

### Changed

- production runtime remains loopback-only (`127.0.0.1`); external market network happens only after an explicit owner action;
- T-Invest is the only production quote source for 0.4; MOEX ISS stays a reference adapter and is not a silent fallback.

### Release status

- This is a release candidate. No tag or GitHub release is created by R04-09.

## [0.3.0] — 2026-08-13

Release candidate focused on the completed 0.3 product pass and safe local delivery.

### Added

- persisted passive-income history boundary with migration-safe defaults and shared backend eligibility semantics;
- capital composition analytics history and the completed Dashboard, Analytics, Goals, Accounts, Settings, and month-workspace UI pass;
- canonical Windows production launcher checks for frontend build, migrations, readiness, and localhost-only serving.

### Changed

- user-facing copy and state presentation now use product language across the main application flows;
- responsive and accessible action presentation was tightened without changing financial formulas or persisted financial contracts.

### Release status

- This is a release candidate. No tag or GitHub release is created by R03-15.

## [0.2.0] — 2026-08-11

Первый post-MVP релиз, сфокусированный на финансовых инвариантах, локальной надёжности, полноценных пользовательских разделах и owner-led smoke/backfill.

### Добавлено

- annual opening YTD gross context для корректного прогрессивного НДФЛ при неполной истории календарного года;
- fail-closed ошибка `salary_tax_history_incomplete` и нормативная семантика `closed`/`draft`/`reopen` для известности прошлых месяцев;
- Goals API/UI, единый source of truth основной цели и backend-derived status/progress/forecast;
- Accounts & Instruments и Settings как полноценные UI-разделы вместо staged placeholders;
- безопасное администрирование налоговой шкалы целиком на календарный год с блокировкой ретроактивной правки года, содержащего закрытые месяцы;
- отображение backend-derived текущей ставки НДФЛ и нескольких ставок при пересечении порога одной выплатой;
- Windows production smoke в CI;
- localhost Host/Origin protection для state-changing запросов;
- process-local DB maintenance guard для backup/restore;
- явная verification policy для targeted/full-suite проверок;
- полная локализация основных user-facing error/reason/domain labels;
- единое user-facing форматирование количества позиций и backend validation: акции — положительное целое количество, дробность сохраняется для типов, где она допустима.

### Изменено

- frontend exact-money boundary больше не использует JS `Number` для финансовой арифметики; деньги остаются exact decimal/minor-unit до presentation boundary;
- SQLite locking contract зафиксирован на rollback journal + эффективном `busy_timeout=5000 ms`; WAL не включён без воспроизводимой необходимости, чтобы не усложнять локальный Windows backup/restore;
- cash-flow contract явно учитывает `include_in_cash_flow` и исключает double count active/passive income;
- optional instrument в новой фактической инвестиционной выплате теперь по умолчанию пуст и сбрасывается после сохранения;
- прогресс основной passive-income цели теперь использует rolling average фактического net passive income по закрытым месяцам, а не C04 forecast monthly total; forecast остаётся отдельной прогнозной метрикой;
- пользовательская документация и runtime/package metadata синхронизированы с 0.2.0.

### Исправлено по owner smoke

- неполная YTD-история НДФЛ больше не блокирует открытие и заполнение исторического draft-месяца: недоступной остаётся только расчётная налоговая часть;
- заполненный draft-месяц можно штатно удалить вместе с принадлежащими ему месячными строками в одной транзакции, сохраняя DB-level `ON DELETE RESTRICT` как общий safety guard;
- диагностированный `0 ₽` dividend component не оказался потерей данных: owner подтвердил, что выплата была заведена как `coupon`; отдельный последующий smoke выявил уже продуктовую семантику Goal — фактические купоны/проценты не должны исчезать из `Текущего значения` только из-за пустого expected-calendar, что исправлено R02-27.

### Известные ограничения

- приложение остаётся single-user/local-only: auth, cloud, VPS и HTTPS-контур не входят в 0.2.0;
- автоматические MOEX-котировки не загружаются;
- календарь ожидаемых выплат в 0.2.0 заполняется вручную через `expected_cash_flows`; автоматическая генерация по позициям/MOEX отложена до отдельного контракта источника и refresh semantics;
- PDF-импорт Альфа-Инвестиций не входит в обычный пользовательский workflow;
- точная доходность с датированными внешними потоками (например Modified Dietz) остаётся будущей задачей;
- приложение не является бухгалтерской, налоговой или торговой системой;
- private seed, база, exports и backups должны оставаться локальными и не попадать в Git.

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

[0.2.0]: https://github.com/LTstripes/hermes-finance/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/LTstripes/hermes-finance/releases/tag/v0.1.0
