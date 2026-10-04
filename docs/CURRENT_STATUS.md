# Hermes Finance — current status

Owner/Integrator closeout, **2026-10-04**. Live GitHub refs and completed CI are authoritative. Current coordination: [#554](https://github.com/LTstripes/hermes-finance/issues/554). Restart brief: [SESSION_CLOSEOUT_2026-10-04](SESSION_CLOSEOUT_2026-10-04.md).

## Release, development and local runtime are separate

| Surface | Verified checkpoint / limitation |
| --- | --- |
| Published release | **v1.2.0**, source `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`, annotated tag object `f9311d26c1aae7295361937096844f4dde615b55`; not draft/prerelease |
| Release checks | Exact-main CI `37206069556` SUCCESS on attempt 2 after a targeted transient `ECONNRESET` retry; Guarded Release `37206660242` SUCCESS |
| Development code | `8ae9ead35d6a988cd2e4c8d967a04bc2c27825a4`, merge #701; exact-main push CI `37226437369` SUCCESS. This is the code milestone, not a moving HEAD alias |
| Local Stable | Last confirmed installation is v1.1.0. Owner authorized v1.2.0 and received OPS02 instructions, but an installation/readiness completion report is not recorded here. Do not infer installation from publication |
| Persistent Test | Last reported pin `d282d09647f129cd83c99e14a10024901a1cf6da`; not refreshed by this session |

**Class-return Phase 1 is integrated in development main, not in published v1.2.0 or automatically in Stable/Test.** A documentation closeout may advance main without changing the code milestone or release tag. [Release record](releases/1.2.0.md) retains publication evidence.

#572 remains CLOSED with **Owner PASS WITH DOCUMENTED LIMITATIONS**, including manual/v1 use. It is not universal provider or real-history Performance success. [Actual acceptance](https://github.com/LTstripes/hermes-finance/issues/572#issuecomment-5937693786) supersedes the historical pre-publication deferral.

## Asset-class returns — Phase 1 integrated

| Slice | Delivered | Merge / exact-main CI |
| --- | --- | --- |
| #534 amendment / #695 | Metric-specific evidence gates; no-crossing subset before statement-backed crossings | `1f3b3415a48819e0c48e08fc2b16e794aafec490` / `37209163282` SUCCESS |
| #696 / #697 | Snapshot-scoped historical class identity; legacy stays NULL, no current-catalogue backfill | `c5a3018b9f9bb7bce1e937fcb2b28fb18e609486` / `37212895008` SUCCESS |
| #698 / #699 | Explicit Owner no-crossing and opening/closing whole-class inventory claims, exact persisted RUB endpoints, revision/material invalidation | `906c5eda9a7e8e466bffe67ac6cf45e1b1dfd78d` / `37219891736` SUCCESS |
| #535 / #700 | Read-only `/api/performance/class-returns`; independent annualized XIRR and period TWRR | `c3ee0cc0215fa650e80de04f8aa38346ce8c3ae3` / `37222285255` SUCCESS |
| #540 / #701 | Existing Performance detail: Accounts/Classes, four visible rows, independent states, provenance, exact-date presets, 390px/keyboard support | `8ae9ead35d6a988cd2e4c8d967a04bc2c27825a4` / `37226437369` SUCCESS |

All four implementation issues are CLOSED / COMPLETED after independent review and canonical checks. No open PR existed at the code milestone. Migrations 0045–0047 belong to this development wave, not v1.2.0.

The supported capability is **whole-portfolio RUB stock/bond/gold over an affirmatively proven no-crossing interval**. Both exact endpoint inventories must be explicitly complete. Current `instrument_type`/`Instrument.currency` are not historical proof; persisted RUB market values preserve the existing accrued-interest basis. XIRR uses only negative opening and positive closing; TWRR uses the no-boundary path. Evidence and solver limitations stay separate.

**Not delivered:** statement-backed purchases/sales/distributions, deposits/savings class returns, flow-bearing class TWRR, FX conversion, or an Owner-facing class-attestation form. The deposit UI row is deliberately unsupported. Backend evidence writes exist, but the class screen is read-only; legacy C1 is not automatically repaired. Owner UAT may therefore correctly show unavailable values, not percentages for every class/month.

Canonical detail: [class contract](performance/ASSET_CLASS_RETURNS_CONTRACT.md), [C1](performance/POSITION_CLASS_IDENTITY.md), [C2/C3/C5](performance/CLASS_NO_CROSSING_ENDPOINTS.md), [return API](performance/CLASS_RETURNS_API.md).

## Owner actions and next work

- **Owner UAT is pending**, planned by the Owner for tomorrow or the following days. Development continues meanwhile. No automatic UAT PASS, local Test refresh, new release or Stable promotion follows from this closeout.
- To test class returns, first use an explicitly prepared exact development candidate on persistent Test (or a separately authorized later release). v1.2.0 cannot show this post-release feature. Preparation is a bounded local Worker operation, not an Owner JSON/PowerShell exercise. Do not repeat the full accepted #662 UAT.
- [#702](https://github.com/LTstripes/hermes-finance/issues/702) is the selected next task: **read-only Phase 2A statement/event contract research**, pinned to the verified code milestone. Produce a source/coverage matrix and the smallest proposed statement-backed class XIRR path. It can run independently of documentation and Owner UAT; it does not authorize implementation.
- Record the missing class-attestation/legacy-C1 repair UI as a product dependency where needed. Do not substitute manual database edits or promise universal historical returns.
- #646 remains external Alfa PRO follow-up. Owner elected to wait several days/about a week for documentation before support/probing; no automatic monitoring or support submission is claimed. #389 composer remains deferred. #124 is permanent release control; #554 coordinates current work.

Worker launch prompts stay short (normally 5–10 lines): issue/latest note, role, baseline, result and delivery. Acceptance criteria stay in the issue/contract, not a second prompt specification. No Model evidence, benchmark collection or reporting telemetry.

## Alfa PRO — known limitation, not a confirmed protocol diagnosis

Owner observed the new Trading core switch in Integrations, port 3366 and Online status, then issued a read-only token. Hermes still reports an unrecognized protocol. The earlier pre-reboot absence of a listener was measured; the later Online UI and changed error are not packet-level proof of a new handshake. No supported token transport/replacement protocol has been established in the accepted investigation. Do not guess headers, ports or frames, request the secret, or call this fixed. Alfa is optional for #702's historical statement route.

## Earlier delivered product, runtime and CI lines

v1.2.0 packages the accepted #662 post-v1.1.0 product wave, #667/#674 follow-up, maintenance #663/#664/#665/#672, CI optimization #668–#671 and repository Launcher retirement #629. The [post-release UAT closeout](POST_RELEASE_UAT_CLOSEOUT_2026-10-03.md) and [CI/test closeout](history/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-10-04.md) retain detailed evidence and measured results. #691 was NO-GO with no optimization code delivered; do not invent an additional speed-up or restart the completed optimization wave.

Portfolio/account Performance Phase A and preparation remain delivered. #541/#528 are CLOSED for that coordination. #630, #573 and historical roadmap #127 are CLOSED / NOT_PLANNED; `/v1` remains intentionally available. AI export schema 1.3.0 is independent of application release identity.

**#679/#666 filesystem migration, legacy cleanup and janitor deployment are COMPLETE.** Stable/Main/Test/Owner/client roots are established. Local and repository Launcher removal is complete; direct Prepare/Validate/Start, backup-first update and recovery protections remain. Do not repeat migration/inventory/restore/client setup or delete anything as part of documentation.

The active janitor lives in the separate **`<FINANCE_CONTAINER>/ops`** boundary; preserve it. The recorded schedule is daily 12:00 local, Apply, retention 7 days, IgnoreNew/StartWhenAvailable. Deployment and dry-run (8 PRESERVE, 0 deletions) are confirmed, not a guaranteed scheduled deletion. Reported historical cleanup space was about 34.03 GiB in total, not a new disk audit. [Layout](OWNER_MACHINE_LAYOUT.md) and [janitor](WORKSPACE_JANITOR.md) own operational details.

## Operating boundaries

[AGENTS](../AGENTS.md), [verification](VERIFICATION_POLICY.md), [routing](MODEL_ROUTING.md) and [runtime operations](OWNER_RUNTIME_OPERATIONS.md) remain authoritative. One physical task workspace and no duplicate heavy local suites; exact-candidate PR and exact-main CI remain distinct. Ordinary tasks use synthetic data. Private runtime payloads never enter Git/CI/agent artifacts. No release, runtime promotion, provider request or broad deletion is authorized by this documentation closeout.
