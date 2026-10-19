# Hermes Finance 0.7.0

> **Status:** RELEASED
> **Published:** 2026-08-30
> **Published identity:** `v0.7.0` @ `06dc3ba3f4a8a8d150eca1879949a6984e1ac6b7`

Hermes Finance 0.7.0 records the accepted and published R07 tree. This document is the public release-notes body for the already published release; the post-release documentation sync changes no product code or financial semantics.

## Included product surface

- **AI Analysis Bundle:** schema-valid, read-only JSON for an explicit owner download. It does not call an LLM or cloud service, persist a bundle, or duplicate financial formulas.
- **Monthly Close Cockpit:** backend-derived blockers, advisory warnings and context for the selected month. Warnings do not become close blockers unless the close contract requires it.
- **Cash-flow Ladder:** upcoming dated treasury events with income and capital-return context. Redemption principal is not passive income.
- **Risk & Allocation:** selected-month allocation from persisted RUB valuations, explicit asset-class/account/top-position breakdown and payout/redemption concentration. Missing metadata is represented as unavailable, not guessed as a score or recommendation.
- **Freshness & Provenance Center:** persisted source/freshness clocks and reason codes, with no universal score or background refresh.
- **Reconciliation Center:** explicit read-only snapshot preview with normalized row states and compatibility diagnostics. Provider Price/UchPrice/NKD/P&L values are comparison-only and do not silently overwrite Hermes.
- **Tax/IIS Planner:** current-state v1. Projection expansion is deferred.
- **Deterministic Insights backend v1:** read-only rules over persisted evidence. Full UI and AI Analysis Bundle integration is not claimed for this release.
- **Performance:** XIRR is available only for a valid unambiguous whole-portfolio root. Exact TWRR uses persisted observed valuation boundaries and explicit pre/post observations for flows; missing/gapped evidence, unknown same-day order and ambiguous roots fail closed.
- **Alfa workflows:** compatibility diagnostics, persistent owner-confirmed account/instrument mapping, owner-approved baseline quantity apply with provenance, and row-scoped selective apply. Unrelated unresolved/conflicting rows do not block a safe selected subset; selected unsafe or stale rows fail closed.
- **Windows launcher:** guarded Stable/Preview runtime profiles and owner Start/Stop controls. The launcher does not list or mutate Git branches/state and does not copy Preview data into Stable.
- **Verification/UI:** visual-audit polish, semantic test-taxonomy work and a 15-minute backend CI timeout are part of the release evidence.

## Safety and scope

- The canonical Alembic head is `0036_broker_baseline_provenance`.
- The application remains Windows-first, local and loopback-only at `127.0.0.1:8000`; no cloud, auth, telemetry, trading or provider write path is introduced.
- Historical financial membership, valuations, cash-flow order and return roots are not inferred. Unavailable states remain explicit and fail closed.
- No real account IDs, balances, tokens, private database paths, backups or Preview/UAT payloads are included.

## Evidence

- Exact-main CI #425 / run `33325251688`: `success`.
- Owner Stable promotion: `PASS`, 2026-08-30.
- Owner UAT for issue #201: `PASS`, 2026-08-30.
- Final accepted selective-apply integration: `d51427989bbe7a195668208318d1eaa2316da6f1`.
- Launcher owner-controls integration: `72dabb27ffeac3ba59b90ba7aad67e40ac61b79f`.

## Deferred

- #141 Scenario Lab;
- #142 projection expansion beyond current-state Tax/IIS v1;
- #143 Insights UI and AI Analysis Bundle integration beyond deterministic backend v1;
- #203 Phase 2B test rehome/dedupe;
- #202 residual workspace/ACL cleanup;
- #229 owner workflow/Alfa UX consolidation.

## Publication record

The immutable published identity is `v0.7.0` @ `06dc3ba3f4a8a8d150eca1879949a6984e1ac6b7`, with exact-main CI #425 / run `33325251688` successful and owner Stable promotion confirmed `PASS` on 2026-08-30. These notes are suitable as the GitHub Release body for that published identity.
