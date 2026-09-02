# Changelog

Все заметные изменения Hermes Finance фиксируются в этом файле.

## [0.8.0] — 2026-09-02

Published owner-workflow release. This entry records the already published `v0.8.0` identity; it does not introduce new product code, financial semantics or provider write behavior.

### Added

- Guided Monthly Close Wizard (#236 A–H): one month-scoped workflow for exact-month review, Alfa baseline/reconciliation, explicit T-Invest/provider actions, payout PDF orchestration, final review and explicit Close/Reopen;
- owner-facing month/readiness/Dashboard/Risk wording and layout polish;
- safe duplicate/inactive instrument cleanup with read-only inspection and fail-closed deletion guards;
- explicit concise/full portfolio review handoff packages in JSON and Markdown from the same backend facts, with no automatic upload/LLM call/write-back;
- Windows launcher package/install artifact verification, shortcut validation and synthetic start/stop/Git-mutation guards.

### Changed

- product/package identity synchronized to `0.8.0` across backend/frontend metadata and lock files;
- Backend CI timeout temporarily raised from 15 to 30 minutes after one hosted runner reached ~83% of the monolithic suite and hit the old limit; durable parallel-lane/slow-test work is tracked in #282;
- owner workflow keeps provider Price/UchPrice/NKD/P&L comparison-only and preserves unknown/unavailable states instead of converting them to financial zero.

### Release evidence

- release candidate: `920cca87066190a7776e8583e3d639ecfd89c5be`;
- exact-head PR CI run `33665746651`: SUCCESS;
- PR #281 merge / released main commit: `ec185deab8d3fe949e7d579e5041d23216a6d73f`;
- post-merge exact-main CI run `33668924186`: SUCCESS;
- guarded Release run `33669922698`: SUCCESS;
- published annotated tag `v0.8.0` object `2f27d9e34271843d97eed1138bd8b388630bd7a8`, peeled to `ec185deab8d3fe949e7d579e5041d23216a6d73f`.

### Owner acceptance note

Pre-release Preview UAT was intentionally not represented as passed because the current launcher cannot update an unreleased Preview checkout itself. Hands-on acceptance is performed on released Stable 0.8.0. Concrete defects become patch/follow-up work. Launcher normalization begins with #277.

### Follow-up / tech debt

- #277–#279 launcher normalization and owner update flows;
- #280 controlled cleanup of old `D:\Finance` workspaces/artifacts;
- #282 split backend pytest into parallel lanes and add slow-test telemetry.

## [0.7.0] — 2026-08-30

Published 0.7.0 for the accepted R07 tree. This entry records already integrated product work and the post-release identity; it does not change product code, financial semantics or provider write behavior.

### Added

- AI Analysis Bundle: schema-valid, explicit owner-downloadable, read-only JSON without LLM/cloud calls, persistence or formula duplication;
- Monthly Close Cockpit with server-derived blockers, advisory warnings and context;
- Cash-flow Ladder for upcoming dated treasury events, keeping redemption principal separate from passive income;
- Risk & Allocation for selected-month persisted RUB valuation, explicit allocation and payout/redemption concentration;
- Freshness & Provenance Center with persisted clocks and reason codes;
- Reconciliation Center with normalized row states and compatibility diagnostics;
- current-state Tax/IIS Planner v1;
- deterministic Insights backend v1 over persisted evidence, without claiming full UI or AI Analysis Bundle integration;
- XIRR and exact TWRR contracts with persisted evidence and fail-closed unavailable states;
- guarded Windows Stable/Preview launcher owner Start/Stop controls, without Git branch/state mutation;
- persistent owner-confirmed Alfa account/instrument mapping registry and owner-approved baseline quantity apply with provenance;
- row-scoped selective apply: unrelated unresolved/conflicting rows do not block a safe selected subset, while selected unsafe/stale rows fail closed;
- UI/visual-audit polish and semantic test-taxonomy/verification work.

### Changed

- product/package identity is synchronized to `0.7.0` in backend/frontend metadata, generated lock metadata, health/release expectations and Windows smoke expectations;
- backend CI timeout is 15 minutes;
- provider Price/UchPrice/NKD/P&L remain comparison-only and never silently overwrite Hermes;
- canonical Alembic head for the accepted tree is `0036_broker_baseline_provenance`.

### Release evidence

- published stable identity: `v0.7.0` @ exact released main SHA `06dc3ba3f4a8a8d150eca1879949a6984e1ac6b7`;
- exact-main CI #425 (run `33325251688`) completed successfully; published 2026-08-30;
- owner Stable promotion for 0.7.0: `PASS`, 2026-08-30;
- owner UAT for issue #201 is recorded as `PASS` on 2026-08-30;
- final accepted selective-apply integration is merge `d51427989bbe7a195668208318d1eaa2316da6f1`;
- launcher owner-controls integration is baseline commit `72dabb27ffeac3ba59b90ba7aad67e40ac61b79f`.

### Not changed

- no cloud, auth, telemetry, trading or provider write path;
- no Preview → Stable data copy and no private account IDs, balances, tokens, databases or UAT payloads in the repository;
- XIRR/TWRR never infer missing historical membership, valuation boundaries, cash-flow order or roots; ambiguous or incomplete evidence remains unavailable;
- local runtime remains Windows-first and loopback-only at `127.0.0.1:8000`.

### Deferred

- #141 Scenario Lab;
- #142 projection expansion beyond current-state Tax/IIS v1;
- #143 Insights UI and AI Analysis Bundle integration beyond deterministic backend v1;
- #203 Phase 2B test rehome/dedupe;
- #202 residual workspace/ACL cleanup;
- #229 owner workflow/Alfa UX consolidation.

## [0.6.3] — 2026-08-25

Maintenance on top of 0.6.2: dashboard information architecture and payout readability, approximate deposit-interest forecast completeness, and explicit T-Invest batch refresh with clearer payout-calendar UX. No new product line, provider write or trading semantics.

### Added

- dashboard cards now distinguish passive-income fact, forecast/goal and mandatory-expense coverage;
- selected-month deposit snapshots contribute an explicitly approximate annualised monthly forecast component; manual expected interest remains additive;
- explicit owner-triggered `Проверить все позиции T-Invest` and `Проверить изменённые` preview actions;
- clearer payout-calendar month disclosure and instrument/company-first payout rows with account secondary, source/provenance and redemption-as-capital context.

### Changed

- actual mandatory-expense coverage remains a backend/domain Decimal calculation distinct from forecast coverage;
- mortgage context is visible without the old hidden extra-metric interaction;
- `Ручные ожидаемые выплаты` is clearly manual-only/additive and follows the merged calendar in DOM order;
- single-position preview and explicit Apply/re-fetch/stale-preview guards remain available.

### Not changed

- deposit forecast is an approximation from the selected month snapshot; maturity and rate changes are not modeled;
- T-Invest refresh is explicit and owner-triggered; quantity changes do not start background provider/network refresh;
- batch preview does not imply cross-position atomic Apply;
- statement retract/edit/delete semantics, provider counting semantics, CLOSED guards and provider/privacy boundaries remain unchanged;
- no cloud, auth, telemetry, trading or provider write operations were added;
- no new Alembic revision; canonical head remains `0029_statement_event_retract`;
- local runtime remains loopback-only (`127.0.0.1:8000`).

## [0.6.2] — 2026-08-25

Maintenance on top of 0.6.1: auditable retract for wrongly applied Alfa statement payouts, plus month-editor / statement-review layout polish. No new product line, provider or trading semantics.

### Added

- safe undo/retract for wrongly applied Alfa statement payouts:
  - auditable `active | retracted` statement-event lifecycle;
  - `retract` append-only revision;
  - statement-created payout retract removes its financial effect while retaining audit evidence;
  - linked-existing retract only detaches statement provenance and preserves the original manual flow;
  - the same statement can be re-imported after retract with a corrected mapping;
  - CLOSED/missing month fail closed;
  - explicit owner UI `Отменить импорт` / `Отвязать выписку`.

### Changed

#### Month editor and statement review

- unnecessary desktop horizontal overflow removed in targeted month tables (deposits, positions, debts, property);
- position inline-edit uses a dedicated readable layout instead of wrapping Save/Cancel in the action column;
- Alfa prepared-import review is denser: identity, account, event/date, class badge and concise decision text;
- simple new rows use a short decision label instead of a long repeated sentence;
- actual-payout green accent no longer crosses the date text.

### Not changed

- no OCR;
- no persistent raw Alfa/provider payload;
- no persistent Alfa account mapping;
- Apply remains explicit and selected-row only;
- duplicate/idempotency guards remain;
- CLOSED and missing-month operations still fail closed;
- generic investment-flow delete must not silently destroy statement provenance;
- retract is statement-specific and auditable;
- no provider or trading semantic change;
- no new Alembic revision in this prep task; canonical head remains `0029_statement_event_retract` (already on main from M06-04);
- local runtime remains loopback-only (`127.0.0.1:8000`).

## [0.6.1] — 2026-08-25

Maintenance UX on top of 0.6.0. No schema, provider or persistence change.

### Changed

#### Month editor

- deposit and table actions moved into the shared three-dot overflow menu;
- missing Edit actions added for manual investment flows, expenses, savings, debts and property/mortgage using the existing PATCH contracts;
- position valuation provenance moved into a compact HelpTip/details control;
- spacing tightened in dense month tables.

#### Quotes and Alfa statement review

- quote preview hierarchy made readable: proposed price and quote date grouped; secondary provenance and long guidance moved behind accessible detail;
- transient Alfa PDF mappings retained while the import panel remains mounted, with an explicit reset; no persistent Alfa provider mapping;
- an explicit owner action can save a statement ISIN into canonical `Instrument.isin` only when safe; a conflicting non-empty ISIN is never silently overwritten; T-Invest mapping remains separate;
- prepared Alfa statement rows show human-readable account, instrument, event, date, gross, tax, net and classification;
- candidate reconciliation shows meaningful evidence instead of only row IDs;
- safe `select all ready` and clear-selection controls.

### Not changed

- no OCR;
- no persistent raw Alfa/provider payload;
- no persistent Alfa account mapping;
- Apply remains explicit and selected-row only;
- duplicate/idempotency guards remain;
- CLOSED and missing-month operations still fail closed;
- no provider or trading semantic change;
- no Alembic migration;
- local runtime remains loopback-only (`127.0.0.1:8000`).

## [0.6.0] — 2026-08-25

Owner-triggered Alfa PRO current snapshot review/apply and a narrow Alfa depository income-payment PDF import.

### Added

- explicit owner-triggered Alfa PRO current-state snapshot: local loopback only, transient account/instrument mapping, preview, then selected apply;
- provider Price / UchPrice / NKD / P&L remain evidence for comparison, not silent authoritative writes;
- Inspect → transient mapping → Prepare → explicit selected Apply for the accepted Alfa depository income-payment PDF family (`Отчет о произведенных выплатах доходов по ценным бумагам`);
- text-layer PDF parse only (no OCR); exact-same PDF is idempotent / duplicate-protected;
- manual matching cash-flow candidates require an explicit `create_separate` or `link_existing` decision;
- additive statement provenance tables; CLOSED and missing-month operations fail atomically and never auto-reopen.

### Changed

- Alfa snapshot and statement network/file work happen only after an explicit owner action; startup, dashboard and month reads stay local;
- no persistent Alfa provider account/instrument mapping is stored;
- no automatic creation of account, instrument or reporting month from provider or report data.

### Not changed

- T-Invest quotes and payout calendar remain owner-triggered and read-only;
- local runtime remains loopback-only (`127.0.0.1:8000`); no auth, cloud, VPS, telemetry, background provider refresh, browser → Alfa WebSocket, or trading/order/signing APIs;
- this is not generic brokerage or bank transaction import.

## [0.5.0] — 2026-08-18

Owner-controlled future investment payout calendar on top of locally stored Hermes positions.

### Added

- explicit Fetch → Normalize → Preview → owner selection → Apply workflow for T-Invest coupons, dividends and redemptions;
- provider-neutral payout domain, deterministic T-Invest payout adapter and additive applied-payout / revision / reconciliation persistence;
- merged 12-month payout calendar that keeps manual expected flows first-class and records append-only provider provenance;
- dedicated payout preview/apply UI and Month → Payments calendar that distinguishes manual vs provider rows;
- countable applied provider coupons feed the existing C04 forecast through the merged read model.

### Changed

- payout fetch remains read-only and happens only after an explicit owner action; startup, dashboard and month reads stay local;
- successful apply freezes quantity/total from the local `PositionSnapshot` and never edits manual expected-flow rows;
- unresolved plausible duplicates stay manual-only until the owner chooses `keep_both`, `count_manual` or `count_provider`.

### Fixed

- T-Invest mapping discovery now shows name, ticker, class code, venue and API-trade availability so the owner can choose among several valid candidates;
- a long mapping dialog stays inside the viewport and scrolls without moving the Accounts page behind it;
- payout preview without an accepted T-Invest mapping explains that a saved source is required instead of a generic validation phrase.

### Not changed

- provider dividends stay calendar-visible and do not replace or supplement C04's historical dividend component;
- principal redemption remains future cash flow and is never passive income;
- reaching an expected event date does not create a realized investment cash flow;
- local runtime remains loopback-only (`127.0.0.1:8000`); no auth, cloud, VPS, telemetry or trading workflow.

### Release status

- Released 2026-08-18 as `v0.5.0`.
- GitHub Release `0.5.0` published as Latest.
- Exact released commit: `7a032eb8c61c675f3a779f9afda59d47e9c8dc81`.
- Final exact-main CI `32140936658` passed.
- Owner live T-Invest smoke passed.

## [0.4.0] — 2026-08-16

Owner-triggered T-Invest market quotes with preview, selective apply and append-only provenance.

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

- Tagged as `v0.4.0` @ `5a29afb9870304faffb9c5911d4c23bcb2563349`.
- The Git tag is the verified immutable identity of 0.4.0.
- `r04` is a closed historical development lineage.
- After publication, canonical `main` may advance; it need not equal `v0.4.0`.

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
