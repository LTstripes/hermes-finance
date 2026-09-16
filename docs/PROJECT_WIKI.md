# Finance Dashboard — Project Wiki

> Долгоживущий контекст Hermes Finance. Подробная история выполнения хранится в `docs/EXECUTION_HISTORY.md`, release notes, closeout-документах и Git history. Персональные финансовые данные сюда не помещаются.
>
> Current-status companion: [`docs/CURRENT_STATUS.md`](CURRENT_STATUS.md).
>
> Last synchronized: **2026-09-16**.

## 1. Что мы строим

Hermes Finance — локальное однопользовательское Windows-first приложение для ежемесячного учёта и анализа личных финансов.

Продукт должен помогать владельцу:

- закрывать месяц явным управляемым workflow;
- видеть ликвидный капитал, долги и динамику;
- отделять инвестиционный результат от денежных потоков;
- видеть фактический и прогнозный пассивный доход;
- понимать upcoming cash-flow / погашения / выплаты;
- анализировать риск, allocation, freshness, provenance и reconciliation;
- работать с целями, Tax/IIS и Scenario Lab;
- безопасно передавать полный read-only финансовый контекст в AI Analysis Bundle;
- запускать локальный runtime без cloud/auth/background automation.

Hermes Finance не является торговой, банковской, бухгалтерской или налоговой системой и не должен изображать точность там, где authoritative evidence отсутствует.

## 2. Источники истины

При конфликте документов использовать порядок из `AGENTS.md`:

1. `docs/MASTER_SPEC.md`;
2. accepted ADRs;
3. active issue/accepted contract;
4. `docs/VERIFICATION_POLICY.md`;
5. `docs/MODEL_ROUTING.md`;
6. `docs/AGENT_ORCHESTRATION.md`;
7. этот wiki;
8. historical docs.

`main` — единственный canonical/release source.

## 3. Текущая идентичность

### Published Stable

Текущая опубликованная Stable-версия — **v0.8.2**.

- release date: 2026-09-05;
- annotated tag object: `bfa1194d4151bb72882f4230f144b039d240eda9`;
- peeled released commit: `a22542d7b20ebdf34e38384004162d409f163ab3`.

Published Stable не меняется просто потому, что development `main` ушёл вперёд.

### Canonical development main

Current canonical `main`:

`e5c09d55a21d4d4a25a9505a819977ed9a162f8c`

Последний canonical merge на этом checkpoint — PR #402 / issue #400 (`PERF-04C — account + internal-transfer decomposition read model`).

Exact-main push CI:

- run number: **#688**;
- run id: `35137779786`;
- conclusion: **SUCCESS**.

## 4. Неподвижные продуктовые и privacy-инварианты

- Windows-first, single-user, local-only.
- Production слушает только `127.0.0.1:8000`.
- SQLite остаётся локальной.
- Нет cloud account/auth/telemetry/trading/background provider refresh.
- Provider/network действия — только explicit owner action.
- Production Stable, Preview/UAT, `.env`, databases, backups, credentials и private exports не попадают в agent/dev workspaces.
- Closed month immutable до explicit Reopen.
- Backend/domain — финансовый source of truth; frontend не пересчитывает финансовую семантику самостоятельно.
- Exact money/rates — Decimal/integer minor units, без binary-float financial semantics.
- Unknown/unavailable не превращается в ноль или approximate exact.

## 5. Что уже построено

### Owner workflow / Monthly Close

Guided Monthly Close полностью пройден и принят owner UAT. Workflow остаётся server-owned и fail-closed там, где evidence недостаточно.

Основной closeout: #236.

### Decision Support v1

Decision Support v1 завершён и интегрирован.

Включает:

- AI Analysis Bundle;
- Monthly Close Cockpit;
- Cash-flow Ladder / upcoming treasury events;
- Risk & Allocation;
- Freshness & Provenance Center;
- Reconciliation Center;
- current-state Tax/IIS Planner Lite;
- deterministic Insights backend;
- Scenario Lab v1.

Scenario Lab детерминированный, read-only и не делает market forecasts/probabilities.

Closeout: `docs/DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md`.

### Performance v1

Performance v1 принят owner UAT и полностью интегрирован.

Delivered:

- flow / valuation / scope-membership hardening;
- cash-boundary coverage;
- transfer reconciliation;
- async transfer transit fail-closed semantics;
- in-kind fail-closed evidence;
- portfolio + account XIRR;
- portfolio + account exact TWRR;
- PERF04A aggregate `value_change_after_external_flows` money bridge;
- exact-zero versus unavailable/null distinction.

Closeout: `docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`.

### PERF04B / PERF04C

После Performance v1 был отдельно проверен вопрос component attribution.

#396 принял verdict **PARTIAL GO**: current evidence позволяет exact decomposition на account grain плюс отдельный strict internal-transfer reconciliation effect, но не instrument/asset-class return attribution.

Canonical identity:

`B_portfolio = Σ B_account + Σ T_internal_transfer`

где `B` — existing PERF04A `value_change_after_external_flows`, а не return/profit/P&L.

Жёсткие границы:

- `100 → 99` без accepted reconciliation evidence — unavailable/null, не exact `-1`;
- `S>D` разрешается только когда transfer-specific fee/commission/tax evidence полностью объясняет difference;
- `D>S` — unavailable;
- same-currency `fx_conversion_spread` сам по себе не авторизует exact PERF04C `T`;
- cross-currency gaps остаются unavailable;
- partial decomposition не публикуется как complete exact split;
- residual bucket запрещён.

Contract: `docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`.

#400 реализовал этот bounded backend read model. PR #402 merged в canonical `main`; exact-head CI #687 и exact-main CI #688 — SUCCESS; independent financial-semantics review — ACCEPT.

Важно: PERF04C пока **backend-only**. API/UI exposure отдельно не разблокирован автоматически.

## 6. Что по-прежнему нельзя называть exact attribution

Текущий evidence model не даёт права exact-раскладывать результат по:

- instrument;
- asset class;
- price versus FX;
- realised versus unrealised;
- lots / trades / acquisition cost;
- causal event attribution;
- additive XIRR/TWRR contribution.

Для этого нужен отдельный accepted data/evidence foundation. Approximation не должна маскироваться как exact.

## 7. Runtime и launcher — актуальная архитектура

### Исторический вывод

Launcher-owned Stable self-update из #298/#311/#312 — failed experiment. Его не продолжаем латать.

Причина — не безопасность как цель, а чрезмерная сложность единой launcher state machine, которая одновременно пыталась отвечать за Git/release proof, backup, filesystem identity, update, dependency preparation, profile migration и process lifecycle.

Parent redesign: #313.

### OPS01 — canonical

#380 / PR #385 реализовали explicit Prepare + deterministic Start.

Prepare:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout <checkout-path> `
  -Prepare
```

Validate:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout <checkout-path> `
  -Validate
```

Start:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Prepare installs missing locked dependencies, builds production frontend and writes ignored `.hermes-runtime-prepared.json` tied to the exact code/build inputs. Start validates that proof and does not silently install/build/update Git.

OPS01 canonical merge: `cc85ad80c58fabb74de36f8bc67b04ccff14b6a4`; exact-main CI #665 SUCCESS.

### OPS02 — canonical implementation, real owner transition UAT pending

#386 / PR #393 реализовали explicit Stable update to one published immutable release.

Owner operation:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-stable.ps1 `
  -StableCheckout <stable-checkout-path> `
  -TargetVersion X.Y.Z
```

Updater работает из trusted control checkout, а не из mutable Stable checkout, и делает только:

- prove requested published annotated release;
- prove current Stable safety prerequisites;
- verified SQLite backup **before** Git mutation;
- exact tag-only fetch;
- detach Stable at the exact proven release commit;
- run target release Prepare + Validate;
- stop.

Он не:

- выбирает `latest`;
- следует `main`;
- запускает Hermes;
- выполняет DB migration;
- обновляет Preview;
- публикует release/tag;
- делает automatic rollback.

OPS02 canonical merge: `c2eab48ef4e20fb14f64c527f543422a6d46f76a`; exact-main CI #673 SUCCESS; independent runtime/safety review ACCEPT.

### Реальный acceptance boundary

OPS02 пока не прошёл real owner Stable release-to-release transition, потому что после его реализации не было нового реального Stable release.

Первый настоящий UAT должен выполняться на следующем реальном релизе:

`v0.8.2 → next published immutable Stable release`.

До этого #313 остаётся open.

Не публиковать throwaway release только ради теста updater.

## 8. Что осталось от Windows launcher

Launcher не retired.

Его полезная роль сейчас:

- owner-facing Stable/Preview profile/status UI;
- ordinary Start/Stop текущего настроенного/pinned runtime;
- shortcut/install shell;
- diagnostics/status presentation.

Но launcher **не является canonical Stable updater**.

Архитектурно роли разделены:

- launcher — profile/status/start/stop shell;
- Prepare/Validate — `scripts/prepare-runtime.ps1`;
- deterministic Start — `scripts/start-local.ps1`;
- Stable version switch — `scripts/update-stable.ps1`;
- release publication — guarded Release Control #124.

Если позже launcher останется, он должен стать thin wrapper над accepted owner operations, а не держать вторую независимую update/state machine.

### Что owner может проверить прямо сейчас

Current published Stable `v0.8.2` можно продолжать запускать/останавливать установленным launcher в его текущем pinned profile.

Можно также отдельно проверять Prepare/Validate/Start на non-production checkout с synthetic/isolated data.

Нельзя полноценно доказать новый Stable updater реальным production transition до появления следующего реального опубликованного релиза.

## 9. Release flow

Release publication остаётся отдельным guarded repository-owned действием.

Permanent control endpoint: #124.

Нормальный chat-first release flow описан в `docs/RELEASE_AUTOMATION.md`.

Publication не равна Stable installation/update: release создаёт immutable published tag/release; Stable owner update выполняется отдельным OPS02 operation.

## 10. UI v2 — отдельный поток

UI v2 tracked отдельно через #387 и children. Этот wiki фиксирует coexistence, но не смешивает UI v2 delivery с non-UI/runtime/performance интеграцией.

Текущее направление UI v2:

- Home = `Мои финансы`;
- latest closed report as normal financial view;
- Monthly Close как contextual work mode;
- v1 сохраняется до отдельного controlled cutover.

Конкретные UI задачи и owner visual UAT смотреть в #387 и его child issues.

## 11. Что идёт дальше

### Non-UI/runtime

Следующий логичный bounded slice под #313 — **exact Preview/UAT preparation pinned to one explicit candidate SHA**:

- explicit exact SHA;
- separate Preview/UAT checkout + isolated UAT DB;
- no automatic following of newer `main` while UAT is running;
- no production DB alias/mutation;
- same accepted Prepare/Validate/Start primitives where applicable.

После этого — только при реальной owner value — bounded diagnosis/recovery operations и решение, нужен ли thin launcher wrapper.

### Performance

Account + internal-transfer decomposition backend завершён.

Следующая exact instrument/asset-class attribution работа возможна только после отдельного data/evidence foundation contract. Пока это не готовая implementation task.

### Stable

Stable остаётся `v0.8.2` до следующего реального guarded release.

Следующий реальный release даст первую возможность провести обязательный OPS02 owner transition UAT.

## 12. Open control/umbrella issues

- #124 — permanent Release Control; intentionally stays open;
- #127 — roadmap umbrella;
- #313 — runtime/launcher redesign parent;
- #387 and children — UI v2 separate stream.

## 13. Canonical reference documents

- `AGENTS.md`
- `docs/MASTER_SPEC.md`
- `docs/VERIFICATION_POLICY.md`
- `docs/MODEL_ROUTING.md`
- `docs/AGENT_ORCHESTRATION.md`
- `docs/CURRENT_STATUS.md`
- `docs/DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md`
- `docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`
- `docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`
- `docs/RELEASE_AUTOMATION.md`
- `docs/EXECUTION_HISTORY.md`

Historical detail remains recoverable from Git history, release docs and the execution journal; this wiki intentionally prioritizes current truth over repeating every old release-era paragraph.
