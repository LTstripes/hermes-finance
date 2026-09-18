# Hermes Finance — current status

> Canonical owner/integrator checkpoint. This document summarizes what is true **now**; detailed historical evidence remains in issues, PRs, closeout documents, `CHANGELOG.md` and `docs/EXECUTION_HISTORY.md`.
>
> Last synchronized: **2026-09-18**.

## Canonical identity

- Published Stable release: **v0.9.0**.
- Published release/source code identity: `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`.
- Annotated tag object: `07c06d44f8b780e721be346a21909ca02585d57d`.
- Guarded Release: **#253 / run `35235369797` — SUCCESS**.
- Exact-main CI at the release gate: **#700 / run `35207551120` — SUCCESS**.
- Latest accepted UI v2 milestone integration: PR #441 / `3bd0cd742672955538a70d895ddba3ff654f9434`.
- Staged-integration process rules: PR #443 / `34ae76f0cbb6bc31c333e30e3feef83b746ba2ca`.
- Canonical `main` may advance with documentation-only closeout commits; GitHub `main` is authoritative for the live SHA.
- PR #409 / issue #408 prepared the `0.9.0` candidate; the release was published only after owner OPS03 PASS.
- `main` remains the only canonical source and release source. Post-release docs/product commits do not change the immutable `v0.9.0` tag identity.
- Known non-blocking release-metadata follow-up: #410 corrects stale pre-publication wording in the GitHub Release description and remaining changelog/history lifecycle metadata. Tag/code identity is correct.

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

## Active roadmap / what comes next

### UI v2 — owner-UAT milestone integrated

UI v2 remains the main active product stream under #387. The first cohesive owner-facing milestone has now passed combined owner UAT on real-data Preview and is integrated into canonical `main`.

Owner-UAT aggregate:

- exact candidate: `fa8db7f0b22857499a6b05432caa1cd0a24131ef`;
- aggregate PR: #441;
- owner verdict: **PASS**;
- canonical integration commit: `3bd0cd742672955538a70d895ddba3ff654f9434`.

Canonical opt-in UI v2 now includes:

- Home «Мои финансы»;
- Capital;
- Income & Plans;
- contextual Reports/history;
- native Monthly Close over authoritative `monthly_close_workflow_v1`;
- Data/App shell with freshness/provenance and explicit read-only reconciliation.

v1 remains the default/rollback path. History and Monthly Close remain contextual rather than permanent sidebar destinations.

The remaining functional Data/App work is:

1. #432 — catalogs and persistent mappings;
2. #433 — exports and safety-gated local backup/restore;
3. #434 — application settings, tax brackets and runtime diagnostics.

Owner-UAT polish backlog is non-blocking:

- #444 — global «Наверх» affordance for long pages;
- #445 — Russian terminology/copy consistency audit;
- #446 — Expected payouts hierarchy/alignment/page order;
- #447 — Reports archive desktop spacing;
- #448 — Reconciliation copy deduplication and owner-facing labels.

Process lesson from this milestone is now durable in `AGENTS.md`: for parallel slices that share application spine files, create the milestone `integration/*` staging line early, integrate accepted heads incrementally, keep shared spine reconciliation Integrator-owned, and run owner UAT on one exact aggregate SHA rather than reconstructing a different tree afterward.

The controlled v2 default switch and any v1 retirement remain later decisions after the remaining Data/App slices and final comparative acceptance.

`1.0.0` remains a reasonable future milestone only after the new primary owner UX is cohesive and the proven production lifecycle remains intact.

### Runtime

The redesign parent #313 is complete. Future runtime work should be evidence-driven and bounded:

- diagnosis/recovery operations only if owner value justifies them;
- optional thin launcher wrappers over accepted primitives;
- no revival of the old launcher updater state machine.

### Performance

Account + internal-transfer decomposition backend support is complete. Exact instrument/asset-class attribution still requires a separately accepted data/evidence foundation.

### Release metadata

#410 remains a non-blocking metadata/history follow-up. It tracks the stale candidate wording in the published `v0.9.0` GitHub Release body, `CHANGELOG.md` publication-state sync, final `EXECUTION_HISTORY` release closeout entry and future release-note lifecycle hardening. None of these items change the already-proven tag/code/Stable identity.

## Open umbrella/control issues

- #124 — permanent Release Control; intentionally stays open;
- #127 — product/technical roadmap umbrella;
- #387 and children — UI v2; core owner-UAT milestone is integrated, with #432–#434 plus polish #444–#448 still open;
- #410 — non-blocking `v0.9.0` release-metadata/history cleanup.

#313 is closed completed after the real `v0.8.2 -> v0.9.0` owner UAT.

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
- `docs/releases/0.9.0.md`
- `docs/release-notes-0.9.0.md`
- #124, #127, #313, #380, #386, #387, #404, #408, #410, #432–#434, #444–#448
