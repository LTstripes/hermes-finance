# Finance Dashboard — Project Wiki

> Долгоживущий контекст Hermes Finance. Подробная история выполнения хранится в `docs/EXECUTION_HISTORY.md`, release notes, closeout-документах и Git history. Персональные финансовые данные сюда не помещаются.
>
> Current-status companion: [`docs/CURRENT_STATUS.md`](CURRENT_STATUS.md).
>
> Last synchronized: **2026-09-22**.

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

Текущая опубликованная и реально owner-tested Stable-версия — **v1.0.0**.

- published: 2026-09-21;
- release/source/Owner-OPS03 SHA: `caf4fdad99cc02f5bc171ec3b1d726b8516ad45e`;
- annotated tag object: `f99ee8ecac1acde7f559d92ee8f45ddcfcdfaa47`;
- tag peels exactly to the released SHA;
- Guarded Release run `35580890145`: SUCCESS;
- exact-main release-candidate CI #880 / `35579583692`: SUCCESS;
- Owner OPS03 exact-SHA Preview/UAT: **PASS**;
- real backup-first OPS02 `v0.9.0 -> v1.0.0`: **PASS**;
- production Stable Start + owner data continuity: **PASS**;
- UI v2 is primary at `/`; previous UI stays at `/v1`.

Detailed evidence: `docs/R10_RELEASE_CLOSEOUT_2026-09-21.md`.

The predecessor `v0.9.0` remains immutable release history.

### Canonical development checkpoints

The `v1.0.0` release source is `caf4fdad99cc02f5bc171ec3b1d726b8516ad45e`.

The live development SHA is always current GitHub `main`; documentation-only synchronization commits may advance it after publication without changing the immutable `v1.0.0` tag identity.

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

#400 / PR #402 реализовал bounded backend read model и прошёл independent financial-semantics review.

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

## 7. Runtime и launcher — proven architecture

### Исторический вывод

Launcher-owned Stable self-update из #298/#311/#312 — failed experiment. Его не продолжаем латать.

Проблемой была не сама безопасность, а попытка собрать слишком много ответственности в одной launcher state machine: release proof, Git mutation, backup, filesystem identity, dependency preparation, profile migration и process lifecycle.

Parent redesign: #313.

### Что вместо этого

R09 разделил lifecycle на независимые операции:

- launcher — owner-facing profile/status/Start/Stop shell;
- OPS01 Prepare/Validate — `scripts/prepare-runtime.ps1`;
- deterministic Start — `scripts/start-local.ps1`;
- OPS02 Stable transition — `scripts/update-stable.ps1`;
- OPS03 exact candidate Preview/UAT — `scripts/prepare-preview.ps1`;
- release publication — permanent guarded Release Control #124.

Главная ценность — меньший blast radius и более понятная диагностика: update failure не означает автоматический Start/migration, Preview mutation или release publication.

### OPS01 — canonical + production-proven

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

Prepare installs/synchronizes locked dependencies, builds production frontend and writes ignored exact prepared-state proof. Start validates that proof and does not silently install/build/update Git.

The production `v0.9.0` readiness smoke and normal Start passed after the real Stable transition.

### OPS02 — canonical + first real owner transition PASS

#386 / PR #393 реализовали explicit Stable update to one published immutable release.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-stable.ps1 `
  -StableCheckout <stable-checkout-path> `
  -TargetVersion X.Y.Z
```

Updater работает из trusted control checkout и:

- proves requested published annotated release;
- proves current Stable safety prerequisites;
- creates verified SQLite backup **before** Git mutation;
- fetches only the selected tag;
- detaches Stable at the exact proven release commit;
- runs target Prepare + Validate;
- stops.

Он не выбирает `latest`, не следует `main`, не запускает Hermes, не делает DB migration, не обновляет Preview, не публикует release/tag и не делает automatic rollback.

Первый настоящий owner UAT completed:

`v0.8.2 -> v0.9.0`

Evidence:

- before HEAD `a22542d7b20ebdf34e38384004162d409f163ab3` / `v0.8.2`;
- verified backup `finance_backup_20260917T144656192481Z`;
- after HEAD `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`;
- `v0.9.0^{}` peeled to that exact SHA;
- production DB hash unchanged by OPS02 before explicit Start;
- Prepare + Validate passed;
- no auto-start/migration during update.

Verdict: **PASS**.

### OPS03 — canonical + first real owner release UAT PASS

#404 / PR #407 реализовали independent exact-SHA Preview/UAT preparation.

Properties:

- explicit full 40-character candidate SHA;
- independent Preview Git clone;
- separate Preview data identity;
- no production DB alias;
- candidate Prepare + Validate;
- no follow-main;
- no Start/direct migration.

First real release UAT pinned Preview exactly to `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36` and passed against isolated owner-controlled data.

Verdict: **PASS**.

### #313 conclusion

The redesign acceptance boundary is now fulfilled on a real owner release transition:

- exact immutable release identity proved;
- backup-before-mutation proved;
- production data preserved;
- Preview isolated;
- no accidental task candidate promoted to Stable;
- no auto-start after update;
- runtime version proved after explicit Start;
- real release-to-release owner UAT passed;
- architecture stayed composable rather than rebuilding the old state machine.

#313 is closed **completed**. Any later diagnosis/recovery or launcher-wrapper work becomes a separate bounded follow-up.

Detailed closeout: `docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md`.

## 8. Windows launcher — what changed and what did not

Launcher не retired, и внешне он специально не обязан выглядеть новым.

Его полезная роль:

- owner-facing Stable/Preview profile/status UI;
- ordinary Start/Stop;
- shortcut/install shell;
- diagnostics/status presentation.

Но launcher **не является canonical Stable updater**.

Поэтому главный результат R09 — не новая кнопка, а качественно другая система под ней:

- exact code tested = exact code published = exact code installed;
- backup exists before mutation;
- publication, update, Preview and Start are separate actions;
- failures локализованы по операции;
- future UI can wrap proven primitives instead of duplicating their safety semantics.

Если позже launcher получает новые кнопки, они должны быть thin wrappers над accepted operations, а не вторая state machine.

## 9. Release flow — теперь доказанный

Permanent control endpoint: #124.

Нормальный release flow:

1. prepare one exact candidate on canonical `main`;
2. OPS03 exact-SHA owner Preview/UAT;
3. owner PASS;
4. guarded immutable publication through #124;
5. independent tag/release read-back;
6. OPS02 explicit Stable update;
7. explicit Start;
8. health/version + owner data continuity proof.

`v0.9.0` — первый релиз, который прошёл эту цепочку полностью.

Publication не равна Stable installation/update: release создаёт immutable published tag/release; local Stable меняется только отдельным OPS02 owner action.

## 10. UI v2 — core roadmap complete / primary interface

UI v2 is now the primary owner interface on development `main`.

Implementation/completion milestone evidence:
- exact aggregate Owner-UAT SHA `edd6a32d94ba322badaea1cab804c4e5cc13574d` — PASS;
- aggregate PR #455;
- canonical completion merge `424ba7bf018c8e4ac01cfda825af7394a3068267`;
- exact-main CI #838 / `35517935019`: SUCCESS.

Final controlled cutover evidence:
- Gate A comparative read-only review: ACCEPT;
- frozen switch candidate `09649bb1d71d6bdff636bb6becbf16d9f0cd5083`;
- Owner UAT: **PASS**;
- PR #474;
- canonical merge `583f9167ae14509202ef47978e7b9f20180e188d`;
- exact-main CI #872 / `35573224359`: SUCCESS.

Current route contract:
- `/` -> primary UI v2 Home;
- `/v1` -> previous UI Dashboard / durable rollback home;
- `/v2` and all existing v2 deep links remain valid;
- legacy editors/routes keep their historical URLs;
- permanent version rollback is separate from contextual month/editor handoffs.

The final candidate was produced only after #475 restore-outcome ambiguity safety was independently accepted and integrated. Thus the cutover tree preserves both truthful restore-result semantics and the default-switch routing/copy contract.

Completed native surface:
- «Мои финансы» Home;
- Capital;
- «Доход и планы»;
- contextual Reports/history;
- native Monthly Close;
- complete «Данные и приложение»;
- owner-facing copy/terminology polish;
- back-to-top support;
- controlled default switch with tested rollback.

V1 is **not retired**. Its Dashboard remains at `/v1`, and retained legacy editors/routes remain available. Any future retirement requires a separate explicit decision based on real-use evidence.

Closeouts:
- `docs/UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md`;
- `docs/UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md`.

### Protected recovery-point publisher and restore-result safety

#459 / PR #466 is accepted and canonical:
- managed provider-neutral protected destination;
- explicit attestation boundary;
- staged verification before exposure;
- destination read-back;
- independent security/recovery review ACCEPT.

#475 / PR #477 is also complete:
- confirmed negative restore outcomes remain distinct from ambiguous possibly-mutated outcomes;
- machine-readable `restore_outcome_ambiguous`;
- ambiguous UI state never claims success/failure and never blind-retries;
- shared reads refresh after ambiguity;
- cleanup cannot overwrite the ambiguity classification;
- independent safety re-review ACCEPT.

#460 / PR #473 bounded verified retention and #461 / PR #483 isolated DR implementation are integrated. Post-merge exact-main verification found a real Windows process-disposition defect; PR #499 closed it, with final canonical `main` `16df86d5eb3923cbe106938d6e81ec360397d00d` and CI #894 / `35734575867` SUCCESS. #462 focused post-restore state reload remains. Real Owner off-device backup/recovery remains a later Owner-controlled gate.

## 11. Что идёт дальше

### UI / product

The core UI v2 roadmap (#387) is complete.

UI v2 is primary at `/`; v1 remains available at `/v1` plus retained legacy routes/editors.

There is no remaining cutover gate. Separate future work:
- #476 — one real-backend synthetic G04 browser regression gate;
- #389 — future configurable dashboards, separate from the completed core roadmap;
- v1 retirement — only as a later explicit task if real use shows rollback/legacy paths are no longer needed.

`v1.0.0` is published and running as Stable after exact-SHA Owner OPS03 PASS, guarded publication, backup-first OPS02 transition and production data-continuity PASS.

### Runtime / durability

#313 завершён. #459 protected recovery-point publisher, #460 retention, #461 isolated DR implementation и #475 restore outcome semantics завершены и интегрированы.

Под #417:
- #461 закрыт канонически после PR #483 и follow-up PR #499;
- #462 post-restore month-state reload остаётся следующим implementation slice;
- реальный protected off-device recovery point, independently held recovery material и clean Owner DR rehearsal остаются Owner-controlled gates.

Не возрождать monolithic launcher updater.

### Performance

Account + internal-transfer decomposition backend завершён.

Следующая exact instrument/asset-class attribution работа возможна только после отдельного data/evidence foundation contract.

### Release metadata

#410 закрыт completed. Published Stable `v0.9.0` остаётся immutable.

`v1.0.0` is now published and installed as real Stable after exact-SHA Owner OPS03 PASS, guarded #124 publication and backup-first OPS02 transition.

## 12. CI/test execution optimization — closeout 2026-09-16

Отдельный bounded pass по CI завершён. Целью было убрать лишнюю работу, не сокращая regression coverage.

Принятые изменения:

- PR #397 — full Windows launcher safety harness больше не запускается дважды; 88 сценариев выполняются один раз через canonical package/install chain;
- PR #399 — Windows timezone lane сокращён с 35 до 7 Windows-specific nodes; исключённые 28 nodes продолжают обязательное выполнение в Linux lanes;
- PR #401 — Synthetic visual audit сохраняет те же 84 nodes, но безопасно выполняется двумя Playwright workers при `fullyParallel: false`.

Итог:

- примерно 116 redundant test/scenario executions убраны из каждого полного CI;
- удалённых regression tests: 0;
- visual coverage и screenshot inventory сохранены;
- whole-CI wall time на closeout checkpoint сократился примерно до 3.5 минут, с обычной оговоркой о GitHub-runner variance.

После отдельного read-only launcher audit принят STOP: оставшийся безопасный резерв в несколько секунд не оправдывает дополнительную сложность safety fixtures.

Project-specific evidence: `docs/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-09-16.md`.

Reusable process: `docs/CI_TEST_OPTIMIZATION_PLAYBOOK.md`.

## 13. Open control/umbrella issues

- #124 — permanent Release Control; intentionally stays open;
- #127 — roadmap umbrella;
- #417 — durability umbrella; #459/#460/#461/#475 complete, #462 and Owner-live gates remain.

Separate follow-up:
- #476 — real-backend synthetic G04 browser regression gate.

Completed: #313, #387, #410, #429, #430, #459, #460, #461, #475 and #480.

## 14. Canonical reference documents

- `AGENTS.md`
- `docs/MASTER_SPEC.md`
- `docs/VERIFICATION_POLICY.md`
- `docs/MODEL_ROUTING.md`
- `docs/AGENT_ORCHESTRATION.md`
- `docs/CURRENT_STATUS.md`
- `docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md`
- `docs/DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md`
- `docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`
- `docs/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-09-16.md`
- `docs/CI_TEST_OPTIMIZATION_PLAYBOOK.md`
- `docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`
- `docs/RELEASE_AUTOMATION.md`
- `docs/releases/1.0.0.md`
- `docs/release-notes-1.0.0.md`
- `docs/releases/0.9.0.md`
- `docs/release-notes-0.9.0.md`
- `docs/EXECUTION_HISTORY.md`

Historical detail remains recoverable from Git history, release docs and execution journal; this wiki intentionally prioritizes current truth over repeating every old release-era paragraph.