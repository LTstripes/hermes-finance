# Session closeout — 2026-10-04

Latest restart brief for Hermes Finance. Supersedes the moving-state portions of [2026-10-03](SESSION_CLOSEOUT_2026-10-03.md); historical acceptance remains dated. Read live #554/main/release/CI/PRs before action. This document does not authorize a release or local runtime change.

## 1. Verified identities

| Item | Evidence |
| --- | --- |
| Code checkpoint | `8ae9ead35d6a988cd2e4c8d967a04bc2c27825a4`, merge #701 |
| Canonical code CI | `37226437369`, push to main on that exact SHA, SUCCESS |
| Final UI candidate | `19f106b6fe27ba113c8a634766e6ce16a2a4c7e1`; PR CI `37225916093` and UI comparison `37225916095` SUCCESS |
| Published release | v1.2.0 at `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`; annotated tag `f9311d26c1aae7295361937096844f4dde615b55` |
| Release verification | Canonical CI `37206069556` SUCCESS; Guarded Release `37206660242` SUCCESS |
| Local Stable | Last confirmed v1.1.0; v1.2.0 update authorized/instructions supplied, but actual installation not confirmed in this session |
| Persistent Test | Last reported `d282d09647f129cd83c99e14a10024901a1cf6da`; no refresh/start performed here |

No open PR at the code checkpoint. Final documentation PR/merge/CI evidence belongs to the latest #554 handoff so this file does not chase its own SHA. **Class-return work is post-v1.2.0 development, not already installed Stable functionality.**

## 2. Completed work and reviews

| Issue / PR | Result and accepted boundary |
| --- | --- |
| #534 amendment / #695 | Original evidence block preserved for unsupported histories; XIRR does not require PRE/POST, and a proven no-crossing interval can support both metrics |
| #696 / #697 | Nullable snapshot-scoped historical class; legacy NULL preserved, explicit correction through accepted lifecycle |
| #698 / #699 | Owner-attested no-crossing plus separate whole-class opening/closing inventory claims; exact persisted RUB endpoints, coherent reads and lifecycle/material invalidation |
| #535 / #700 | Thin read-only class return adapter/API over accepted evidence; unchanged numerical primitives, independent metric availability and reason sources |
| #540 / #701 | Accounts/Classes UI, stock/bond/gold plus unsupported deposit, exact-date controls/presets, provenance and unavailable states, 390px/keyboard support |

#696, #698, #535 and #540 are CLOSED / COMPLETED. Independent reviews were recorded on the exact accepted candidates. #699 required two fixes (whole-class inventory proof and removal of mutable catalogue currency as historical proof); #701 required restoration of exact-date presets. Remediations were accepted, then exact-main CI passed. No local full-suite repetition or new provider access was needed for the Integrator reviews.

Accepted merges and canonical CI:
- C1: `c5a3018b9f9bb7bce1e937fcb2b28fb18e609486` / `37212895008` SUCCESS.
- Endpoint evidence: `906c5eda9a7e8e466bffe67ac6cf45e1b1dfd78d` / `37219891736` SUCCESS.
- Return API: `c3ee0cc0215fa650e80de04f8aa38346ce8c3ae3` / `37222285255` SUCCESS.
- UI: `8ae9ead35d6a988cd2e4c8d967a04bc2c27825a4` / `37226437369` SUCCESS.

## 3. What Phase 1 actually provides

Whole-portfolio RUB `stock`, `bond`, `gold` for an exact interval with no class crossings, complete historical identity and explicit full inventory at both endpoints. Empty queries, unrelated position footprints and present-day catalogue metadata cannot manufacture proof. Existing persisted RUB valuation retains its accrued-interest semantics.

XIRR receives exactly negative opening and positive closing on their actual dates; TWRR receives endpoints with no boundaries. XIRR is annualized; TWRR is period return. Positive opening/zero closing can give unavailable XIRR and -100% TWRR; zero opening remains undefined under existing numerical contracts. Solver limits are not evidence gaps.

**Not delivered:** statement-backed trade/distribution history; deposits/savings class returns; flow-bearing class TWRR/PRE-POST; FX/lot accounting; or an Owner class-attestation form. The screen is read-only. Legacy history is not backfilled and may stay unavailable. UI/API delivery is not universal real-history availability or automatic separation of all monthly purchases from performance.

Sources: [accepted contract](performance/ASSET_CLASS_RETURNS_CONTRACT.md), [C1](performance/POSITION_CLASS_IDENTITY.md), [endpoint evidence](performance/CLASS_NO_CROSSING_ENDPOINTS.md), [API](performance/CLASS_RETURNS_API.md).

## 4. Next Worker — #702

Owner selected [#702](https://github.com/LTstripes/hermes-finance/issues/702): **Phase 2A read-only statement-backed class event/source contract research**.

It may run in parallel with the docs closeout and pending Owner UAT on pinned code `8ae9ead35d6a988cd2e4c8d967a04bc2c27825a4`. A prose-only newer main does not require another checkout/restart. No duplicate Worker should be launched if the Owner already sent this task out.

Expected report: verified source/coverage matrix; one first report family; proposed minimum class-boundary events/amount/date/correction contract; reconciliation/no-double-counting; minimum XIRR path; Owner-effort and missing UI/data dependencies; ordered implementation slices and synthetic vectors. Publish one report comment on #702, with source references and READY FOR IMPLEMENTATION or CONTRACT BLOCKED. No code, schema, PR, providers or private samples.

The next Integrator reads that report, reviews financial/data semantics and only then freezes implementation slices. A report verdict does not self-authorize code or a broader queue. Alfa PRO is optional; statements must be assessed from actual fields, not assumed complete.

## 5. What awaits the Owner

Owner UAT is planned for tomorrow or the next few days, not performed/PASS. Development continues meanwhile. Do not demand it before read-only #702 or re-run the full accepted #662 route.

Before a class-screen UAT, establish that the running code actually contains #701. Published v1.2.0 does not. Any exact Test preparation/backup/Start is an explicitly bounded local Worker assignment using the existing persistent Test and runtime-operation contract; do not silently repoint Stable at main or request a new environment inventory.

Focused checks when the Owner is ready: Accounts/Classes and exact presets, independent rates/reasons, no stale old-period values, expected unsupported deposit, and representative real-history availability. Include remaining #667/portfolio/account checks only where still useful. No positive class-return UAT claim from unavailable legacy evidence; no manual SQL/JSON/PowerShell workaround for the missing evidence-entry UI.

The missing class-attestation/legacy-C1 repair user path is a retained product gap for #702/next-session planning, not proof that already accepted Phase 1 code must be reimplemented.

## 6. Alfa and other intentional holds

#646 remains open. Owner saw Trading core Online on 3366, issued a read-only token and still received unrecognized protocol in Hermes. No secret was shared. This narrows the incident but does not prove a new wire handshake or vendor-wide breakage. Owner chose several days/about a week of waiting for documentation before support; no scheduled monitoring or support submission was created here. Do not guess token headers/messages/ports, probe private data or change mappings.

#389 composer remains deferred. #124 is permanent release control and #554 current coordination. #127/#528/#541 are closed umbrellas; #630/#573 are closed not-planned; /v1 stays. #668–#671/#629 optimization/retirement is complete; #691 remains NO-GO without delivered optimization code.

## 7. Runtime, process and restart rules

#679/#666 migration/cleanup/janitor setup is complete. Retain existing `stable/main/test/owner/workspaces/<client>` roles and the separate active Ops directory. Machine paths stay local; see [layout](OWNER_MACHINE_LAYOUT.md), [runtime operations](OWNER_RUNTIME_OPERATIONS.md), [janitor](WORKSPACE_JANITOR.md). No migration/inventory/restore/client setup, release, Stable promotion or deletion is part of this closeout.

**Keep Worker prompts short, normally 5–10 lines.** Issue/latest accepted note owns scope and tests; launch/remediation prompts only locate it. The Owner explicitly reiterated this preference. Do not regenerate a long duplicate specification. Model/provider evidence, benchmark collection and telemetry remain retired; route selection is not execution reporting.

Use current AGENTS and relevant contracts only. One physical task workspace, targeted verification, exact-candidate CI plus exact-main CI. Network/permission-tool timeouts are tooling failures, not financial architecture STOPs; retry only through permitted paths without bypassing security controls or disabling TLS. Previous specific sibling-seed permission is not general workspace reuse authority.
