# Hermes Finance — current status

> Canonical owner/integrator checkpoint. This document summarizes what is true **now**; detailed historical evidence remains in issues, PRs, closeout documents, `CHANGELOG.md` and `docs/EXECUTION_HISTORY.md`.
>
> Last synchronized: **2026-09-21**.

## Canonical identity

- Published Stable release: **v0.9.0**.
- Published release/source code identity: `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`.
- Prepared release candidate: **v1.0.0** under #480 — PREPARED / UAT-PENDING; no tag/GitHub Release yet and Stable remains v0.9.0.
- Release-prep baseline: canonical `main @ ab002c2215bc35c62b95c00452b9541e077b78c2`, exact-main CI #874 / `35574331652` — SUCCESS.
- Annotated tag object: `07c06d44f8b780e721be346a21909ca02585d57d`.
- Guarded Release: **#253 / run `35235369797` — SUCCESS**.
- Exact-main CI at the release gate: **#700 / run `35207551120` — SUCCESS**.
- Latest product/runtime integration checkpoint before this documentation sync: `583f9167ae14509202ef47978e7b9f20180e188d` — controlled UI v2 default switch.
- Exact-main CI for that checkpoint: **#872 / run `35573224359` — SUCCESS**.
- Frozen Owner-UAT switch candidate: PR #474 / `09649bb1d71d6bdff636bb6becbf16d9f0cd5083` — **PASS**.
- Restore outcome-semantics safety #475 / PR #477: accepted candidate `676b330b59deb4abea89f7807af8b382a1ac4c87`, canonical merge `a11c1b3580ffa2dad0b6bd7f19fe6d2dae2e6fba`, exact-main CI #869 / `35571951532` — SUCCESS.
- GitHub `main` is authoritative for the live development SHA; documentation-only synchronization commits may advance it without changing the product/runtime checkpoints they describe.
- UI v2 implementation/completion aggregate: PR #455 / Owner-UAT SHA `edd6a32d94ba322badaea1cab804c4e5cc13574d` — PASS; canonical merge `424ba7bf018c8e4ac01cfda825af7394a3068267`.
- Staged-integration process rules: PR #443 / `34ae76f0cbb6bc31c333e30e3feef83b746ba2ca`.
- `main` remains the only canonical source and release source. Post-release development work does not change the immutable `v0.9.0` tag identity.

## Product/runtime invariants

Hermes Finance remains a local single-user Windows-first application:

- production binds only to `127.0.0.1:8000`;
- SQLite is local;
- no cloud account, auth, telemetry, trading or background provider refresh;
- provider/network operations remain explicit owner actions;
- production Stable data, Preview/UAT data, `.env`, backups, credentials and private exports never enter agent/development workspaces;
- closed-month and financial calculation contracts remain authoritative;
- exact money uses integer minor units / Decimal semantics;
- unknown/unavailable evidence is never silently converted to zero or approximate exact.

## Major completed product lines

### Monthly Close / owner workflow

Guided Monthly Close and owner UAT are complete. The workflow is server-owned and fail-closed where evidence is incomplete.

Primary closeout: #236.

### Decision Support v1

Complete and integrated:

- Scenario Lab v1;
- AI Analysis Bundle;
- Monthly Close Cockpit;
- Cash-flow Ladder;
- Risk & Allocation;
- Freshness & Provenance;
- Reconciliation Center;
- current-state Tax/IIS Planner Lite;
- deterministic Insights backend.

Scenario Lab is deterministic/read-only and does not forecast markets or write financial data.

Closeout: `docs/DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md`.

### Performance v1

Complete and integrated:

- flow / valuation / scope-membership hardening;
- transfer reconciliation and in-kind fail-closed handling;
- portfolio and account XIRR;
- portfolio and account exact TWRR;
- PERF04A aggregate selected-scope `value_change_after_external_flows` bridge;
- exact-zero versus unavailable/null distinction.

Closeout: `docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`.

### PERF04B / PERF04C bounded decomposition

#396 froze a **PARTIAL GO** contract:

`B_portfolio = Σ B_account + Σ T_internal_transfer`

#400 / PR #402 implemented the bounded backend read model.

Limits remain explicit:

- backend read model only;
- no instrument/asset-class contribution from current evidence;
- no price-vs-FX or realised/unrealised/cost-basis attribution;
- unknown evidence remains unavailable/null rather than estimated.

Contract: `docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`.

## Runtime/release redesign — completed and real-owner proven

The launcher-owned Stable self-update experiment from #298/#311/#312 remains a historical failed experiment. It is not the canonical update path.

#313 redesigned the runtime around small composable owner operations and is now closed **completed** after the real `v0.8.2 -> v0.9.0` owner transition.

### OPS01 — Prepare + deterministic Start — PASS

Canonical: #380 / PR #385.

- Prepare/Validate: `scripts/prepare-runtime.ps1`.
- Start: `scripts/start-local.ps1`.
- Start validates exact prepared-state proof and does not silently update Git, sync dependencies or rebuild.

### OPS02 — explicit Stable update — real owner PASS

Canonical implementation: #386 / PR #393.

Operation: `scripts/update-stable.ps1` from a trusted control checkout outside mutable Stable.

It proves one selected published annotated release, creates a verified production SQLite backup before mutation, fetches only that tag, pins Stable to the exact peeled release commit, runs target Prepare + Validate, and stops without Start/migration.

First real owner transition completed successfully on 2026-09-17:

`v0.8.2 -> v0.9.0`

Owner evidence:

- before Stable: `v0.8.2` / `a22542d7b20ebdf34e38384004162d409f163ab3`;
- verified backup: `finance_backup_20260917T144656192481Z`;
- after Stable HEAD: `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`;
- local `v0.9.0^{}` peeled to the exact same SHA;
- production DB hash unchanged by OPS02 before explicit Start;
- target Prepare + Validate passed;
- no auto-start or migration occurred inside OPS02.

Verdict: **PASS**.

### OPS03 — exact-SHA isolated Preview/UAT — real owner PASS

Canonical implementation: #404 / PR #407.

The first real OPS03 release UAT pinned Preview exactly to:

`c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`

The owner used an independent Preview checkout and verified physical copy of production SQLite data. Exact SHA pinning, isolation, health/version and product checks passed; production DB remained unchanged.

Verdict: **PASS**.

### Production Stable v0.9.0 Start — PASS

After the successful OPS02 code transition, owner explicitly started Stable `v0.9.0` on production data.

Verified:

- production readiness smoke: PASS;
- `/api/health`: `status=ok`, `version=0.9.0`;
- owner data continuity: PASS.

This completes the real-world acceptance boundary that intentionally remained open when OPS02 was originally integrated.

Detailed closeout: `docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md`.

## Why the launcher looks similar — and why quality changed

The redesign was intentionally not a visual launcher rewrite.

The launcher remains useful as an owner-facing profile/status/Start/Stop shell. What changed is responsibility and blast radius:

- **launcher** — presentation + ordinary Start/Stop;
- **Prepare/Validate** — `scripts/prepare-runtime.ps1`;
- **deterministic Start** — `scripts/start-local.ps1`;
- **Stable release transition** — `scripts/update-stable.ps1`;
- **exact candidate Preview/UAT** — `scripts/prepare-preview.ps1`;
- **release publication** — guarded #124 flow.

This provides reproducible exact code identity, backup-before-mutation, smaller failure boundaries, clearer diagnosis and no accidental coupling between update, Preview, migration, Start and publication.

A future launcher may wrap these accepted operations, but must not recreate an independent update state machine.

## Release flow

Release publication and local Stable installation are separate operations:

1. exact candidate owner UAT through OPS03;
2. guarded publication through permanent Release Control #124;
3. explicit owner OPS02 Stable transition;
4. explicit Start and data-continuity verification.

`v0.9.0` is the first release to complete this full chain successfully.

## Protected recovery-point publisher — implementation accepted

#459 / PR #466 is complete on canonical `main`.

- accepted candidate: `8eb47bb1261861354bf1dbec1271cc538f4b1bc4`;
- canonical merge: `49144da863c93e5afc505e16be6817c55ff2b50d`;
- independent security/recovery review: **ACCEPT**;
- exact-head CI #837 / run `35516975089`: SUCCESS;
- exact-main CI #839 / run `35518134142`: SUCCESS.

Delivered: provider-neutral managed protected-destination publisher for explicitly attested `external_encrypted_destination_v1`, including staged verification before final exposure, destination read-back, producer/schema identity, privacy-safe CLI failure handling and no plaintext verification scratch in default temp storage.

Not yet done: retention deletion (#460), clean isolated DR rehearsal (#461), focused legacy Export/Backup restore-state reload (#462), or any real Owner Drive/off-device backup run. No Google API/OAuth/key-management/cloud architecture was introduced.

## Active roadmap / what comes next

### UI v2 — core roadmap complete / primary interface

The core UI v2 roadmap (#387) is complete.

Final controlled cutover:
- comparative Gate A review: ACCEPT;
- frozen Owner-UAT candidate: `09649bb1d71d6bdff636bb6becbf16d9f0cd5083`;
- Owner verdict: **PASS**;
- PR #474;
- canonical merge: `583f9167ae14509202ef47978e7b9f20180e188d`;
- exact-main CI #872 / `35573224359`: SUCCESS.

Current route contract:
- `/` -> primary UI v2;
- `/v1` -> previous UI Dashboard / durable rollback home;
- `/v2` and existing `/v2/...` routes remain valid;
- legacy deep links/editors remain available at their historical URLs;
- contextual handoffs preserve month/step/query/fragment context.

V1 retirement is **not** implied by this completion. If later desired, it requires a separate explicit task after real-use evidence.

#476 remains a separate browser-regression-infrastructure follow-up and is not a cutover blocker.

Detailed closeouts:
- `docs/UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md`;
- `docs/UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md`.

### Runtime / durability

The runtime redesign parent #313 is complete. #459 protected recovery-point publisher is canonical.

#475 restore outcome semantics is also complete:
- post-/possibly-mutated failure uses machine-readable `restore_outcome_ambiguous`;
- confirmed negative outcomes remain distinct;
- ambiguous UI state does not claim success/failure, refreshes shared reads and does not blindly retry;
- cleanup cannot overwrite the ambiguity classification;
- independent safety re-review: ACCEPT.

Active durability sequence under #417:
- #460 — bounded verified retention;
- #461 — isolated disaster-recovery rehearsal;
- #462 — focused legacy Export/Backup post-restore month-state reload.

Real protected off-device backup and recovery rehearsal remain Owner-controlled gates.

### Performance

Account + internal-transfer decomposition backend support is complete. Exact instrument/asset-class attribution still requires a separately accepted data/evidence foundation.

### Release / regression infrastructure

Published Stable remains immutable `v0.9.0`; development-main acceptance is not a release publication.

#480 prepares `v1.0.0` from the accepted development-main state. The candidate is UAT-PENDING: next gate is exact-SHA OPS03 Owner UAT, then guarded #124 publication, then backup-first OPS02 Stable update.

#476 tracks one deterministic real-backend synthetic G04 browser journey and an explicit CI gate without expanding into a broad E2E redesign.

## Open umbrella/control issues

- #124 — permanent Release Control; intentionally stays open;
- #127 — product/technical roadmap umbrella;
- #38## Open umbrella/control issues

- #124 — permanent Release Control; intentionally stays open;
- #127 — product/technical roadmap umbrella;
- #417 — owner durability umbrella; #459 and #475 complete, #460–#462 remain.
- #480 — v1.0.0 release preparation / exact-SHA Owner UAT gate.

Separate follow-up:
- #476 — real-backend synthetic G04 browser regression gate.

Completed: #313, #387, #410, #429, #430, #432–#434, #444–#448, #459 and #475.

## Canonical references

- `AGENTS.md`
- `docs/MASTER_SPEC.md`
- `docs/VERIFICATION_POLICY.md`
- `docs/PROJECT_WIKI.md`
- `docs/EXECUTION_HISTORY.md`
- `docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md`
- `docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`
- `docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`
- `docs/RELEASE_AUTOMATION.md`
- `docs/releases/1.0.0.md`
- `docs/release-notes-1.0.0.md`
- `docs/releases/0.9.0.md`
- `docs/release-notes-0.9.0.md`
- #124, #127, #417, #460–#462, #476; completed #313, #387, #410, #429, #430, #432–#434, #444–#448, #459, #475
