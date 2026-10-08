# Hermes Finance — current status

Owner/Integrator status refreshed **2026-10-08** after the #740/#741 historical-source integration and protected Test UAT. Live GitHub refs and completed CI are authoritative. Current coordination: [#554](https://github.com/LTstripes/hermes-finance/issues/554). Restart brief: [SESSION_CLOSEOUT_2026-10-04](SESSION_CLOSEOUT_2026-10-04.md).

## Release, development and local runtime are separate

| Surface | Verified checkpoint / limitation |
| --- | --- |
| Published release | **v1.2.0**, source `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`, annotated tag object `f9311d26c1aae7295361937096844f4dde615b55`; not draft/prerelease |
| Release checks | Exact-main CI `37206069556` SUCCESS on attempt 2 after a targeted transient `ECONNRESET` retry; Guarded Release `37206660242` SUCCESS |
| Development main | `e2864668a7357365656ace4ac681288313d0ee9f`, merge #741; code-only H0 optimization after #740. Exact #740 post-main CI `37827387788` SUCCESS; [#741 post-main push CI](https://github.com/LTstripes/hermes-finance/actions/runs/37835529213) must be checked live before citing its result |
| Local Stable | Later isolated Owner-local preflight observed the Stable **checkout code SHA** `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`, matching published v1.2.0. A separate production Start/health/data-continuity completion record remains unavailable; code pin alone does not prove runtime readiness |
| Persistent Test | Owner-local #741 H0 UAT reported code pin `9f028150475bb14dfb3c43c8bdbb9d6e2512e2fc`, independent DB on schema `0054`, read-only complete H0 Preview twice under 45s with no DB changes. Test is not Stable and remains separate |

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

At the dated class-return code milestone, all four implementation issues were CLOSED / COMPLETED after independent review and canonical checks. Later source-first/H0 integration is tracked separately in #709. Migrations 0045–0047 belong to this development wave, not v1.2.0.

The supported capability is **whole-portfolio RUB stock/bond/gold over an affirmatively proven no-crossing interval**. Both exact endpoint inventories must be explicitly complete. Current `instrument_type`/`Instrument.currency` are not historical proof; persisted RUB market values preserve the existing accrued-interest basis. XIRR uses only negative opening and positive closing; TWRR uses the no-boundary path. Evidence and solver limitations stay separate.

**Not delivered:** universally complete statement-backed purchases/sales/distributions, deposits/savings class returns, flow-bearing class TWRR or FX conversion. The deposit row is deliberately unsupported. Bounded C1 correction and no-crossing/endpoint inventory preparation UI from #705/#706 has since been integrated, but this does not automatically repair legacy C1 or create full history. Dedicated Owner class-return UI UAT remains pending; unavailable percentages are correct when proof is missing.

Canonical detail: [class contract](performance/ASSET_CLASS_RETURNS_CONTRACT.md), [C1](performance/POSITION_CLASS_IDENTITY.md), [C2/C3/C5](performance/CLASS_NO_CROSSING_ENDPOINTS.md), [return API](performance/CLASS_RETURNS_API.md).

## Owner actions and next work

- **#709 source-first historical reconstruction remains OPEN.** #708's MyBroker import is integrated; #736/#738 B-REPO and reviewed archived-instrument Skip shipped in combined [PR #740](https://github.com/LTstripes/hermes-finance/pull/740). Protected original XML 1/2/4 source replay and Performance reason/display Owner-local UAT passed, with exact-main CI [37827387788](https://github.com/LTstripes/hermes-finance/actions/runs/37827387788) SUCCESS. A skipped historical instrument never proves an unaffected financial scope or a zero position.
- **H0 Preview performance is repaired in development main via [PR #741](https://github.com/LTstripes/hermes-finance/pull/741).** Independent read-only code review ACCEPT, exact-head CI [37831179270](https://github.com/LTstripes/hermes-finance/actions/runs/37831179270) SUCCESS. On the preserved Test DB, the original read-only H0 API returned complete HTTP 200 in 0.538s and 0.524s with equal response/digest, no writes or migration, and existing 18 reports and three imports unchanged. The original timed-out H0 response cannot be compared; ordinary Start/shutdown smoke was not repeated.
- **Financial XIRR/TWRR truth is still separate:** use H0's account/date/source-range/endpoint structural inventory to identify exactly which H1, H2-B1, H2 cash/in-kind, H3, membership and valuation evidence is missing. Do not infer amounts, full coverage, missing owner flows, prices, class returns or positive historical returns. H0 does not calculate XIRR. Full #709 Owner financial acceptance remains pending.
- **Focused Owner UI follow-up:** actual-history «Капитал → Доходность → По классам» plus C1/no-crossing preparation from #705/#706 need their own no-write acceptance. Do not replay the already accepted full #572 monthly UI route.
- **Local/release boundary:** current published v1.2.0 is not current development main. Future Stable promotion requires a separately authorized release and backup-first OPS02, then explicitly reviewed source mappings and fresh real XML upload in Stable. Do not copy Test SQLite. Established exact Owner account identity decisions are retained privately and must not be replaced by a general suffix heuristic.
- #702 source research is CLOSED; #711 source-first ingestion roadmap and #714 deposit/savings research remain OPEN. #646 Alfa PRO is waiting for a documented supported token contract, not guessed protocol changes. #389 composer is deferred; #124 is permanent release control; #554 coordinates ongoing work.

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
