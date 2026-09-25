# Hermes Finance — current status

> Canonical owner/integrator checkpoint. This document summarizes what is true **now**; detailed historical evidence remains in issues, PRs, closeout documents, `CHANGELOG.md` and `docs/EXECUTION_HISTORY.md`.
>
> Last synchronized: **2026-09-25**.

## Canonical identity

- Published Stable release: **v1.0.0**.
- Current accepted implementation checkpoint: `744c613884d074e6f9d35d61523603f257371713`.
- Exact-main CI for that checkpoint: **#947 / run `36139627216` — SUCCESS**.
- Published release / Owner-OPS03-tested code identity: `caf4fdad99cc02f5bc171ec3b1d726b8516ad45e`.
- Annotated tag object: `f99ee8ecac1acde7f559d92ee8f45ddcfcdfaa47`; tag peels exactly to the released SHA.
- Guarded Release run `35580890145`: **SUCCESS**.
- Exact-main release-candidate CI: **#880 / run `35579583692` — SUCCESS**.
- Owner OPS03 exact-SHA Preview/UAT: **PASS**.
- Real backup-first OPS02 Stable transition `v0.9.0 -> v1.0.0`: **PASS**.
- Production Stable Start / owner data continuity: **PASS**.
- Owner durability #417: **PASS / completed** — fresh plaintext synced recovery point published + destination read-back verified, off-device visibility confirmed, clean isolated DR returned `readiness=verified` with source unchanged.
- UI v2 is primary at `/`; previous UI remains available at `/v1`.
- Published predecessor `v0.9.0` remains immutable historical evidence.
- GitHub `main` is authoritative for live development; documentation-only closeout commits may advance it beyond the released code without changing the immutable `v1.0.0` tag identity.

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

### Production Stable v1.0.0 transition — PASS

After exact-SHA OPS03 PASS and guarded publication of `v1.0.0`, the owner completed the real backup-first OPS02 transition:

`v0.9.0 -> v1.0.0`

Accepted owner result:

- published annotated `v1.0.0` peeled to `caf4fdad99cc02f5bc171ec3b1d726b8516ad45e`;
- OPS02 Stable transition: **PASS**;
- explicit Stable Start on the production database: **PASS**;
- owner data continuity / real working data present: **PASS**;
- `/api/health` expected application version: `1.0.0`.

No private database, backup identifier or financial values are recorded in repository documentation.

Detailed closeout: `docs/R10_RELEASE_CLOSEOUT_2026-09-21.md`.

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

## Owner durability + isolated DR — completed

The durability line under #417 is complete.

Implementation history:
- #459 / PR #466 — managed recovery-point publisher;
- #460 / PR #473 — bounded verified retention;
- #461 / PR #483 + PR #499 — isolated DR implementation plus Windows process-disposition hardening;
- #462 / PR #502 — focused post-restore month-state reload;
- #475 / PR #477 — truthful ambiguous restore-outcome handling;
- #511 / PR #518 — real Owner rehearsal fix for Windows PowerShell singleton-month JSON handling;
- #524 / PR #525 — real Owner rehearsal fix for Windows readiness ownership/classification TOCTOU;
- #527 / PR #542 — explicit Owner-accepted plaintext synced-filesystem mode with pair-bound manifest/read-back/retention/DR semantics.

Canonical durability checkpoint: `744c613884d074e6f9d35d61523603f257371713`.
Exact-main CI #947 / `36139627216`: **SUCCESS**.
Independent security/recovery re-review of #527: **ACCEPT**.

Owner-live acceptance on 2026-09-25:
- fresh `owner_accepted_plaintext / synced_filesystem_destination_v1` recovery point: **published / verified / read_back=verified / retention=completed**;
- exact new artifact independently visible off-device: **PASS**;
- clean isolated Owner DR from that artifact: **PASS** — `status=rehearsed`, `source_verified=true`, `source_unchanged=true`, `restored=true`, `prepared=true`, `validated=true`, `readiness=verified`, `schema_relationship=same_revision`;
- broad privacy-safe restored structure: 8 reporting months, 43 user tables, 25 populated user tables, 25 user indexes, 0 user views.

The Owner explicitly accepted plaintext-at-rest storage in the ordinary synced folder. Hermes does not claim cloud delivery and still has no Google API/OAuth/key-management/cloud architecture. The encrypted mode remains available only for genuinely encrypted destinations; older protected attestations are not reclassified.

Parent #417 is **closed completed**. #543 is a separate non-blocking hardening follow-up (neutral parse-failure identity, explicit 12+12+1 mixed-retention regression, pair-scoped listing documentation).

Closeout: `docs/OWNER_DURABILITY_CLOSEOUT_2026-09-25.md`.

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

The runtime redesign parent #313 is complete. Owner durability parent #417 is also complete.

Accepted durability chain:
- #459 publisher;
- #460 pair-bound bounded retention;
- #461 / PR #499 isolated DR + Windows cleanup hardening;
- #462 post-restore read-state reload;
- #475 ambiguous restore truthfulness;
- real-rehearsal fixes #511 and #524;
- #527 plaintext synced-filesystem mode.

The final Owner-live flow passed on canonical checkpoint `744c613884d074e6f9d35d61523603f257371713`:
1. fresh plaintext recovery point published and destination-read-back verified;
2. exact new artifact confirmed visible off-device;
3. clean isolated DR restored and started successfully with `readiness=verified` and unchanged source artifact.

#543 tracks non-blocking post-closeout hardening and does not reopen #417.

### Performance

Account + internal-transfer decomposition backend support is complete. Exact instrument/asset-class attribution still requires a separately accepted data/evidence foundation.

### Release / regression infrastructure

Published Stable is `v1.0.0`. #480 release preparation, exact-SHA OPS03 Owner UAT, guarded #124 publication and backup-first OPS02 Stable transition are complete.

#476 tracks one deterministic real-backend synthetic G04 browser journey and an explicit CI gate without expanding into a broad E2E redesign.

## Open umbrella/control issues

- #124 — permanent Release Control; intentionally stays open;
- #127 — product/technical roadmap umbrella;
- #543 — post-closeout recovery hardening; non-blocking and does not reopen completed #417;

Separate follow-up:
- #476 — real-backend synthetic G04 browser regression gate.

Completed: #313, #387, #410, #417, #429, #430, #432–#434, #444–#448, #459, #460, #461, #462, #475, #480, #511, #524 and #527.

## Canonical references

- `AGENTS.md`
- `docs/MASTER_SPEC.md`
- `docs/VERIFICATION_POLICY.md`
- `docs/PROJECT_WIKI.md`
- `docs/EXECUTION_HISTORY.md`
- `docs/R10_RELEASE_CLOSEOUT_2026-09-21.md`
- `docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md`
- `docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`
- `docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`
- `docs/RELEASE_AUTOMATION.md`
- `docs/releases/1.0.0.md`
- `docs/release-notes-1.0.0.md`
- `docs/releases/0.9.0.md`
- `docs/release-notes-0.9.0.md`
- #124, #127, #476, #543; completed #313, #387, #410, #417, #429, #430, #432–#434, #444–#448, #459, #460, #461, #462, #475, #480, #511, #524, #527.
