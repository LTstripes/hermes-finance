# Finance Dashboard — Project Wiki

> Долгоживущий контекст Hermes Finance. Подробная история выполнения хранится в `docs/EXECUTION_HISTORY.md`, release notes, closeout-документах и Git history. Персональные финансовые данные сюда не помещаются.
>
> Current-status companion: [`docs/CURRENT_STATUS.md`](CURRENT_STATUS.md).
>
> Last synchronized: **2026-09-20**.

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

Текущая опубликованная Stable-версия — **v0.9.0**.

- published: 2026-09-17;
- release/source code identity: `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`;
- annotated tag object: `07c06d44f8b780e721be346a21909ca02585d57d`;
- tag peels exactly to the release/source SHA above;
- Guarded Release #253 / run `35235369797`: SUCCESS;
- exact-main release-gate CI #700 / run `35207551120`: SUCCESS.

Owner acceptance for this exact code identity is complete:

- OPS03 exact-SHA Preview/UAT: **PASS**;
- real OPS02 Stable transition `v0.8.2 -> v0.9.0`: **PASS**;
- production readiness smoke: **PASS**;
- `/api/health`: `0.9.0`;
- owner data continuity: **PASS**.

Detailed evidence: `docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md`.

Known non-blocking metadata follow-up: #410 corrects the GitHub Release description that inherited pre-publication `UAT-PENDING` wording plus remaining changelog/history lifecycle metadata. Tag/code/release identity is correct.

### Canonical development checkpoints

Latest product/runtime integration checkpoint before the documentation sync:

`49144da863c93e5afc505e16be6817c55ff2b50d` — #459 protected recovery-point publisher, exact-main CI #839 / run `35518134142`: **SUCCESS**.

UI v2 completion entered `main` one parent earlier at `424ba7bf018c8e4ac01cfda825af7394a3068267` (CI #838 / `35517935019`: SUCCESS).

The live development SHA is always the current GitHub `main`; documentation-only synchronization commits may advance it. The immutable released code remains `c90a842...`; post-release development does not change the published `v0.9.0` tag.

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

## 10. UI v2 — complete opt-in product integrated

UI v2 is tracked through #387. The full opt-in owner-facing product is now accepted as one exact aggregate, not merely as a collection of synthetic pages.

Final completion evidence:

- exact Owner-UAT candidate: `edd6a32d94ba322badaea1cab804c4e5cc13574d`;
- aggregate PR: #455;
- owner verdict: **PASS**;
- canonical integration: `424ba7bf018c8e4ac01cfda825af7394a3068267`;
- exact-main CI #838 / run `35517935019`: **SUCCESS**.

Completed native surface:

- Home = «Мои финансы»;
- Capital;
- «Доход и планы»;
- contextual Reports/history;
- native Monthly Close over the server-owned workflow;
- complete «Данные и приложение»:
  - sources/freshness/provenance;
  - explicit read-only reconciliation;
  - catalogs/mappings;
  - exports and local backup/restore;
  - settings, tax brackets and runtime diagnostics;
- global «Наверх» for long v2 pages;
- final owner-facing Russian copy/terminology pass;
- accepted Expected payouts hierarchy, Reports archive spacing and Reconciliation copy polish.

S13 umbrella #429 and children #432–#434 are closed. Owner-UAT polish #444–#448 is closed.

Backup/restore #433 received an independent safety review before acceptance. The accepted contract includes exact-target confirmation, success-only pre-restore evidence, safe QueryClient refresh after successful or ambiguous restore outcomes, fail-safe ambiguous transport/body handling, focus containment and mutual mutation guards.

History/Reports and Monthly Close remain contextual. v1 remains the default/rollback surface until #430.

The milestone reinforced the staged-integration rule now recorded in `AGENTS.md`: accepted sibling heads are integrated incrementally into one milestone staging line, shared App/Entry/Shell/navigation reconciliation is Integrator-owned, and Owner UAT validates one exact aggregate tree that is not reconstructed afterward.

Closeout: `docs/UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md`.

### Protected recovery-point publisher

#459 / PR #466 is accepted and canonical:

- accepted candidate `8eb47bb1261861354bf1dbec1271cc538f4b1bc4`;
- canonical merge `49144da863c93e5afc505e16be6817c55ff2b50d`;
- independent security/recovery review: ACCEPT;
- exact-main CI #839 / `35518134142`: SUCCESS.

The publisher supports only an explicitly attested `external_encrypted_destination_v1` filesystem destination. It proves staged artifact integrity/schema identity before final exposure and re-verifies destination bytes after publication. It does not prove cloud delivery or validate encryption keys, and it adds no cloud API/OAuth/custom cryptography.

#460 retention, #461 isolated DR rehearsal and #462 focused post-restore state reload remain open. Real Owner backup/recovery use remains a later Owner-controlled gate.

## 11. Что идёт дальше

### UI / product

UI v2 implementation/completion is finished on canonical `main`.

The next and only remaining core gate is #430:

1. comparative read-only v1/v2 audit;
2. owner checklist and blocker-only findings;
3. bounded root/default-switch candidate if the audit is clean;
4. exact-SHA Owner Preview/UAT;
5. controlled merge only after explicit Owner PASS.

The switch must preserve v1 as an obvious rollback/legacy route. V1 retirement remains a separate decision after cutover.

`1.0.0` is reasonable only after this controlled default switch is accepted and the proven production lifecycle remains intact.

### Runtime / durability

#313 завершён. #459 protected recovery-point publisher также завершён и интегрирован.

Под #417 остаются:
- #460 retention;
- #461 isolated DR rehearsal;
- #462 post-restore month-state reload.

Real protected off-device backup/recovery rehearsal остаются Owner-controlled. Не возрождать monolithic launcher updater.

### Performance

Account + internal-transfer decomposition backend завершён.

Следующая exact instrument/asset-class attribution работа возможна только после отдельного data/evidence foundation contract.

### Release metadata

#410 — non-blocking metadata/history follow-up. Это не влияет на уже доказанные release/tag/Stable identities.

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
- #387 — UI v2 roadmap; implementation is complete, only #430 controlled default-switch gate remains open;
- #417 — durability umbrella; #459 complete, #460–#462 open.

#313, #410, #429 and #459 are completed.

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
- `docs/releases/0.9.0.md`
- `docs/release-notes-0.9.0.md`
- `docs/EXECUTION_HISTORY.md`

Historical detail remains recoverable from Git history, release docs and execution journal; this wiki intentionally prioritizes current truth over repeating every old release-era paragraph.