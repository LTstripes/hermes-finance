# Astra audit data-integrity hardening closeout — 2026-09-27

## Status

**COMPLETE / CANONICAL MAIN.**

The post-audit hardening wave raised from the Astra review is fully implemented, independently/integrator reviewed as required, integrated through PR #509 and verified on canonical `main`.

- final integration head: `ad59be98450599c0253e9dbf027385d06f1eabb1`;
- aggregate PR: #509;
- canonical merge/main: `b6f3ff1aff93f06ae0a563ba8704b91086a80924`;
- merge-ref CI: run `36306528111` — **SUCCESS**;
- merge-ref UI comparison: run `36306528183` — **SUCCESS**;
- exact-main push CI: run `36306845860` — **SUCCESS**;
- canonical Alembic head after the wave: `0044_observed_valuation_material_signature`.

Published Stable remains immutable **v1.0.0**. This closeout describes accepted development `main`; it does not publish or promote a new Stable release.

## Scope closed

All audit issues in the wave are closed:

- core integrity: #484–#498;
- financial-completeness implementation follow-ups: #536–#539.

No remaining implementation task from this Astra-audit wave is open.

## What changed

### 1. Writes are atomic against the state they validated

The wave removed several “validate, then race, then commit stale state” classes:

- optimistic financial writes use database-level compare-and-swap semantics (#484);
- a reporting month cannot become CLOSED between edit validation and commit (#485);
- statement correction and append-only revision history stay coherent under competing corrections/retractions (#488);
- linked-debt balance evidence cannot be removed by two competing writers that both observed the old state (#489);
- transfer-link leg ownership/reconciliation evidence is serialized before relink/delete decisions (#490);
- salary canonical-cardinality races cannot create a second canonical salary row (#491);
- month clone reads one coherent source state and publishes the target atomically (#492).

**Effect:** concurrent owner/API actions fail with a conflict instead of silently producing hybrid or stale financial state.

### 2. Composite financial reads are coherent

#496 introduced one SQLite snapshot boundary for composite financial reads, while keeping provider/network I/O outside the read transaction and revalidating afterward.

**Effect:** one API/report response no longer mixes “before” and “after” rows from concurrent commits.

### 3. Historical payout/provenance data survives corrections safely

#486 added a supported DRAFT correction lifecycle for positions/months that already have provider payout history:

- the active financial snapshot can be removed/recreated;
- provider payout identity and append-only revisions remain auditable;
- historical reconciliation remains preserved without permanently occupying the active manual-flow slot;
- foreign-key integrity and rollback semantics remain fail-closed.

#487 keeps payout counting conservative when a previously resolved provider/manual match becomes newly ambiguous.

**Effect:** owner corrections no longer require destroying audit history, and ambiguous payout data cannot silently double-count or disappear.

### 4. Performance exactness cannot be resurrected from stale evidence

- reporting-month deletion invalidates affected cash-boundary completeness (#493);
- PRE/POST valuation capture is bound to the material event version it observed (#494);
- explicit valuation boundary groups fail closed when member dates/membership no longer match the persisted group (#495).

**Effect:** XIRR/TWRR cannot become “exact” again merely because stale evidence still exists after an underlying financial event changed.

### 5. Cash/account identity remains explicit through AI/export

#497 preserves real cash-account identity through AI bundle/review assembly; unassigned cash stays a synthetic/unassigned identity rather than being guessed onto a real account.

**Effect:** AI/export consumers cannot accidentally treat an unassigned cash row as evidence for a specific account.

### 6. “Exact known subtotal” is now distinct from “complete portfolio coverage”

#498 froze the financial-completeness contract:

- a mathematically exact subtotal over persisted rows may remain `available / exact`;
- if an active capital-included account has no snapshot, portfolio-source coverage is `partial` with `active_account_snapshot_missing`;
- the missing account stays missing; its value is never zero-filled;
- with no usable portfolio/included-debt evidence, the capital metric is `unavailable` with `portfolio_snapshot_missing`.

Implementation was completed end-to-end:

- #536 — AI Analysis Bundle/history/capital-domain metadata;
- #537 — portfolio/financial review, capital goals and allocation/concentration support;
- #538 — canonical read-model coverage plus compact owner-facing markers on v1/v2 Home, Capital, Reports/history and month surfaces;
- #539 — close-readiness no longer lets unassigned cash satisfy a real cash account.

The canonical coverage helper is shared with the AI bundle so owner-facing and AI/export surfaces cannot diverge on what counts as capital evidence.

**Effect:** Hermes can show “known subtotal: exact, coverage: partial” truthfully instead of choosing between a false zero and a falsely complete total.

## Integration and drift proof

During the long integration wave, `main` advanced independently. Before final merge, drift from the original #509 base was checked explicitly:

- current `main` before final integration: `10d545882041593f37d65cf8f56b42b3a18ccebd`;
- only one file overlapped at file level with the hardening diff: `docs/PROJECT_WIKI.md`;
- no production-code overlap existed.

GitHub built test merge `4c918569cb940519118e50522ab5f1202a7a4d3e` as the hardening head merged into that current `main`. Aggregate CI checked out that exact `refs/pull/509/merge` tree and passed before #509 was merged.

## Product boundaries unchanged

This wave did **not** add:

- cloud hosting, cloud account or auth;
- telemetry;
- trading/provider writes;
- background provider refresh;
- approximate financial formulas disguised as exact;
- a second frontend financial model.

Hermes remains local, single-user, Windows-first, SQLite-backed and loopback-only at `127.0.0.1:8000`.

## What this gives the Owner

The practical result is less visible “new functionality” and much stronger trust in existing functionality:

- simultaneous saves are much less likely to corrupt or overwrite each other silently;
- month close/delete/clone/correction operations keep their invariants under races;
- reports and AI exports describe one coherent database state;
- historical audit/provenance survives corrections;
- performance metrics fail closed when their evidence becomes stale;
- missing account data is visible as incomplete coverage instead of being mistaken for zero;
- the same completeness truth now reaches API, AI exports and owner UI.

Future work starts from canonical `main` after this closeout; the temporary `integration/data-integrity-hardening` line is no longer an active project source.
