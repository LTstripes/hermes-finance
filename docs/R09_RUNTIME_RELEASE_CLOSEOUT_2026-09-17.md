# R09 runtime/release closeout — 2026-09-17

## Outcome

R09 proved the redesigned Hermes Finance owner runtime/release lifecycle end to end on a real release transition.

The visible Windows launcher intentionally remains familiar. The architectural change is underneath it: release publication, exact Preview/UAT preparation, Stable release mutation, runtime preparation and deterministic Start are now separate composable operations with independent fail-closed contracts instead of one launcher-owned update state machine.

## Published release identity

- Published Stable: `v0.9.0`.
- Release source / owner-UAT code identity: `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`.
- Exact-main CI before publication: #700 / run `35207551120` — SUCCESS.
- Guarded Release: #253 / run `35235369797` — SUCCESS.
- Annotated tag object: `07c06d44f8b780e721be346a21909ca02585d57d`.
- Tag peels exactly to `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`.
- GitHub Release `Hermes Finance 0.9.0`: published, draft=false, prerelease=false.

Known non-blocking metadata follow-up: #410 corrects the published GitHub Release description, which inherited pre-publication `UAT-PENDING` wording. Tag/code/release identity is unaffected.

## OPS01 — Prepare + deterministic Start

Canonical implementation: #380 / PR #385.

The accepted runtime is split into two explicit phases:

1. `scripts/prepare-runtime.ps1` installs/synchronizes locked dependencies, builds the production frontend and records exact prepared-state proof.
2. `scripts/start-local.ps1` validates that proof and starts without silently moving Git refs or rebuilding/installing dependencies.

This makes ordinary Start deterministic and auditable rather than an implicit update/build operation.

## OPS02 — explicit Stable update

Canonical implementation: #386 / PR #393.

The updater is `scripts/update-stable.ps1`, run from a trusted control checkout outside mutable Stable. It:

1. proves the selected published annotated release;
2. proves current Stable identity/safety prerequisites;
3. creates a verified SQLite backup before Git mutation;
4. fetches only the selected immutable tag;
5. pins Stable to the exact peeled release commit;
6. runs target Prepare + Validate;
7. stops without starting Hermes or migrating the database.

It does not choose `latest`, follow `main`, update Preview, auto-start, publish a release or perform automatic rollback.

### First real owner OPS02 UAT — PASS

Real transition exercised on 2026-09-17:

`v0.8.2 -> v0.9.0`

Owner evidence:

- before Stable HEAD: `a22542d7b20ebdf34e38384004162d409f163ab3`;
- before Stable tag: `v0.8.2`;
- verified backup id: `finance_backup_20260917T144656192481Z`;
- after Stable HEAD: `c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`;
- local `v0.9.0^{}` peeled commit: exact same SHA;
- production DB hash unchanged by OPS02 before explicit Start;
- updater reported prepared + validated and did not auto-start/migrate.

Verdict: **PASS**.

## OPS03 — exact-SHA isolated Preview/UAT

Canonical implementation: #404 / PR #407.

OPS03 prepares an independent Preview clone pinned to one full 40-character candidate SHA. It does not follow later `main`, does not alias production data, composes the accepted Prepare + Validate operations, and stops without Start.

### First real owner OPS03 UAT — PASS

The `v0.9.0` release candidate was tested at exact SHA:

`c90a842ec5e85fc5ac0de4aedd5d7fd14c09ae36`

Owner used an isolated Preview checkout and a verified physical copy of production SQLite data. The tested Preview remained pinned to the exact candidate, production DB remained unchanged, health returned `0.9.0`, and owner product checks passed.

Verdict: **PASS**.

## Production v0.9.0 Start — PASS

After the successful OPS02 code transition, owner explicitly started Stable `v0.9.0` against the production database.

Verified:

- production readiness smoke: PASS;
- `/api/health`: `status=ok`, `version=0.9.0`;
- owner data continuity: PASS;
- familiar product surfaces/data remained available after the guarded startup/migration path.

Verdict: **PASS**.

## What changed in quality even though the launcher looks similar

The success is architectural and operational, not cosmetic.

### Before R09

The failed launcher self-update experiment attempted to combine:

- release discovery;
- tag/commit proof;
- Git mutation;
- production backup;
- filesystem/data identity safety;
- dependency preparation;
- process lifecycle;
- profile migration;
- Start/Stop UI.

Real owner UAT repeatedly exposed edge cases and the state machine grew substantially for small owner-visible fixes.

### After R09

Responsibilities are separated:

- launcher — owner-facing profile/status/Start/Stop shell;
- OPS01 Prepare/Validate — exact prepared runtime state;
- deterministic Start — explicit runtime start;
- OPS02 — one selected immutable Stable release transition;
- OPS03 — one selected exact-SHA Preview/UAT preparation;
- #124 — guarded publication of immutable releases.

Each operation has a smaller contract, explicit inputs and narrower failure boundary. A failure in update no longer silently implies Start, migration, Preview mutation or release publication.

This gives Hermes Finance:

- reproducibility — the exact code identity tested is the one published and installed;
- rollback evidence — verified backup exists before Stable mutation even though automatic rollback is intentionally not performed;
- lower blast radius — Preview, Stable update, Start and publication are independent actions;
- better diagnosis — failures are attributable to a specific operation instead of a large launcher state machine;
- safer owner workflow — dangerous steps are explicit and fail closed;
- easier future UI wrapping — launcher can later call accepted operations without reimplementing their semantics.

## Launcher conclusion

The launcher is not retired and therefore does not need to look radically different.

Its proven useful role is the owner-facing shell for profile/status and ordinary Start/Stop. It is **not** the canonical Stable updater.

Future launcher work is optional product polish/thin wrapping over accepted operations, not a prerequisite for safe releases.

## #313 acceptance

The redesign acceptance criteria are now materially proven on a real owner release transition:

1. simple explicit owner path from old Stable to new Stable — PASS;
2. exact immutable published tag/commit proof — PASS;
3. verified backup before mutation — PASS;
4. production DB/data preserved through update and available after Start — PASS;
5. Preview remains an isolated operation — PASS;
6. task/worktree candidate cannot silently become Stable; target is the proven release commit — PASS;
7. no auto-start after update — PASS;
8. runtime version proof after explicit Start — PASS;
9. real owner release-transition UAT — PASS;
10. bounded composable implementation/verification model — PASS.

#313 can therefore close as completed. Further diagnosis/recovery or launcher-wrapper work should be separate bounded follow-ups rather than keeping the redesign parent artificially open.

## Next direction

- Lift the temporary `v0.9.0` release-window freeze; UI v2 may resume normal integration through its own gates.
- Keep #124 open permanently as Release Control.
- Resolve #410 as metadata/docs-only release-description cleanup.
- Continue UI v2 toward a coherent owner experience; `1.0.0` remains a reasonable future milestone only after the new primary UX and production lifecycle are both accepted.
- Instrument/asset-class exact attribution still requires a separately accepted data/evidence foundation; do not infer it from the runtime closeout.
