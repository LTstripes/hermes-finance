# Hermes Finance — current status

> Canonical owner/integrator checkpoint. This document summarizes what is true **now** on canonical `main`; detailed historical evidence remains in issues, PRs, closeout documents, `CHANGELOG.md` and `docs/EXECUTION_HISTORY.md`.
>
> Last synchronized: **2026-09-16**.

## Canonical identity

- Published Stable release: **v0.8.2**.
- Published Stable peeled commit: `a22542d7b20ebdf34e38384004162d409f163ab3`.
- Canonical development `main`: `e5c09d55a21d4d4a25a9505a819977ed9a162f8c`.
- Latest canonical merge: PR #402 / issue #400 — PERF04C account + internal-transfer decomposition read model.
- Exact-main push CI: **#688 / run `35137779786` — SUCCESS**.
- `main` remains the only canonical source of truth and the only release source.
- Published Stable is intentionally behind development `main`; merged development work does not become Stable until a separately guarded release is published.

## Product/runtime invariants

Hermes Finance remains a local single-user Windows-first application:

- production binds only to `127.0.0.1:8000`;
- SQLite is local;
- no cloud account, auth, telemetry, trading or background provider refresh;
- provider/network operations remain explicit owner actions;
- production Stable data, Preview/UAT data, `.env`, backups, credentials and private exports never enter agent/development workspaces;
- closed-month and financial calculation contracts remain authoritative;
- exact money uses integer minor units / Decimal semantics, not binary float shortcuts.

## Major completed product lines

### Monthly Close / owner workflow

Guided Monthly Close and its owner UAT are complete. The current workflow is server-owned, fail-closed where evidence is incomplete, and remains available independently of the UI v2 workstream.

Relevant closeout: #236 and its accepted owner UAT.

### Decision Support v1

Decision Support v1 is complete and integrated.

Delivered capabilities include Scenario Lab v1, AI Analysis Bundle, Monthly Close Cockpit, Cash-flow Ladder, Risk & Allocation, Freshness & Provenance, Reconciliation Center, Tax/IIS Planner Lite and deterministic Insights backend.

Scenario Lab is deterministic and read-only; it does not forecast markets or write financial data.

Closeout: `docs/DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md`.

### Performance v1

Performance v1 is complete and integrated.

Delivered:

- external-flow / valuation / scope-membership hardening;
- transfer reconciliation and in-kind fail-closed handling;
- portfolio and account XIRR;
- portfolio and account exact TWRR;
- PERF04A aggregate selected-scope `value_change_after_external_flows` monetary bridge;
- exact-zero versus unavailable/null distinction.

Closeout: `docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`.

### PERF04B / PERF04C component decomposition

The next Performance slice has now also completed its accepted backend stage.

#396 froze the financial contract with verdict **PARTIAL GO**:

`B_portfolio = Σ B_account + Σ T_internal_transfer`

where the parent and account rows are existing PERF04A `value_change_after_external_flows` bridges and `T_internal_transfer` is a strict reconciliation component, not return/profit attribution.

#400 then implemented the bounded backend read model and was accepted through PR #402.

Canonical completion:

- contract: #396 / PR #398;
- implementation: #400 / PR #402;
- accepted candidate: `65563330f16cf7191ac3b3560d0c3cfee2cbb57a`;
- canonical merge: `e5c09d55a21d4d4a25a9505a819977ed9a162f8c`;
- exact-head CI #687: SUCCESS;
- exact-main CI #688: SUCCESS;
- independent financial-semantics review: ACCEPT, no blockers.

Important limits:

- this is a **backend read model only**;
- there is no API/UI exposure yet;
- instrument/asset-class contribution remains unsupported from current evidence;
- price-vs-FX and realised/unrealised/cost-basis attribution remain unsupported;
- unknown evidence remains unavailable/null rather than estimated.

Canonical contract: `docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`.

## Runtime / launcher redesign status

The old launcher-owned Stable self-update state machine from #298/#311/#312 remains a **failed experiment** and must not be revived incrementally.

#313 was deliberately redesigned around small composable owner operations.

### OPS01 — Prepare + deterministic Start — complete

#380 / PR #385 is canonical.

A checkout can be explicitly prepared with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout <checkout-path> `
  -Prepare
```

Prepare installs only required locked dependencies, builds the production frontend and writes ignored `.hermes-runtime-prepared.json` proof tied to the exact checkout/build inputs.

Validate without changing preparation:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout <checkout-path> `
  -Validate
```

Ordinary start:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Start validates the prepared proof and does not silently build, install dependencies or update Git.

Canonical OPS01 merge: `cc85ad80c58fabb74de36f8bc67b04ccff14b6a4`; exact-main CI #665 succeeded.

### OPS02 — explicit Stable update to one immutable release — complete in code

#386 / PR #393 is canonical.

Owner-selected Stable update is now a separate script, intentionally **outside** the launcher state machine:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-stable.ps1 `
  -StableCheckout <stable-checkout-path> `
  -TargetVersion X.Y.Z
```

The operation:

1. proves the requested published annotated release;
2. proves the current Stable state and safety prerequisites;
3. creates a verified production SQLite backup before mutation;
4. fetches only the selected tag;
5. switches Stable to the exact proven release commit;
6. invokes the target release's Prepare and Validate operations;
7. stops without starting Hermes or running a DB migration.

Canonical OPS02 merge: `c2eab48ef4e20fb14f64c527f543422a6d46f76a`; exact-main CI #673 succeeded; independent runtime/safety review accepted it with no blockers.

### What is still not proven

OPS02 has not yet had a **real owner Stable release-to-release transition UAT**, because no newer Stable release existed when it was implemented.

Do not publish a release merely to exercise this path.

The first genuine proof should happen on the next real release transition from current Stable `v0.8.2` to the next published immutable Stable release.

Until that UAT passes, #313 remains open.

## Current Windows launcher conclusion

The Windows launcher itself is still useful for the existing prepared/pinned runtime profiles and ordinary owner Start/Stop workflow.

It should **not** own Stable release mutation.

Current architecture is therefore:

- **launcher** — owner-facing profile/status/start/stop shell for the currently configured Stable/Preview runtimes;
- **Prepare/Validate** — `scripts/prepare-runtime.ps1`;
- **Start** — `scripts/start-local.ps1`;
- **Stable release update** — `scripts/update-stable.ps1` from a trusted control checkout outside the mutable Stable checkout;
- **release publication** — guarded repository-owned flow through permanent issue #124;
- future launcher work, if retained, should become a thin wrapper over accepted operations rather than a second state machine.

The current published `v0.8.2` predates OPS01/OPS02. Therefore the redesigned release-update flow is development-canonical now but will first become available inside a published target release at the next guarded release.

## Current owner-test boundary

What can be checked now without creating a fake release:

- open the already installed launcher and use the current pinned `v0.8.2` Stable profile for ordinary Start/Stop;
- install/reinstall the existing launcher from the published Stable checkout if needed;
- exercise Prepare/Validate/Start on a non-production development/Preview-style checkout with synthetic or owner-controlled isolated data;
- run repository CI/runtime synthetic verification, which already covers real-Git update semantics.

What should wait for the next real release:

- production Stable transition through `update-stable.ps1`;
- proving the full #313 release-to-release owner flow on real Stable data;
- deciding whether a thin launcher wrapper around the new operations is worth adding.

## Active roadmap / what comes next

UI v2 is an independent workstream tracked by #387 and its child issues. It is intentionally not managed from this non-UI checkpoint.

For the non-UI/runtime stream the next accepted architectural direction under #313 is:

1. exact Preview/UAT preparation pinned to one explicit candidate SHA, without auto-following newer `main` during UAT;
2. bounded diagnosis/recovery operations if owner value justifies them;
3. only then decide whether the launcher needs a thin wrapper around these accepted operations.

For Performance, account decomposition backend support is now complete. Before instrument/asset-class attribution can become exact, Hermes still needs a separately accepted data/evidence foundation; no approximate attribution should be added merely to fill a UI.

## Open umbrella/control issues

- #127 — product/technical roadmap umbrella;
- #313 — runtime/launcher redesign parent; remains open until real Stable transition UAT and later accepted slices;
- #124 — permanent Release Control; intentionally stays open;
- #387 and children — UI v2, separate stream.

## Canonical references

- `AGENTS.md`
- `docs/MASTER_SPEC.md`
- `docs/VERIFICATION_POLICY.md`
- `docs/PROJECT_WIKI.md`
- `docs/EXECUTION_HISTORY.md`
- `docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`
- `docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`
- `docs/RELEASE_AUTOMATION.md`
- #127, #313, #380, #386, #396, #400
