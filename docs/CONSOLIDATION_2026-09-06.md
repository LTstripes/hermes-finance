# Hermes Finance — post-v0.8.2 consolidation

> **Task:** #306
> **Audit date:** 2026-09-06
> **Audit baseline:** canonical `main` `96f97b0424370be93e327587633c424ee6c33a8a`
> **Scope:** integrator-only consolidation; no product feature or launcher redesign implementation

## Outcome

The v0.8.2 release is published and the repository is ready for three isolated
next-wave staging lines. `main` remains the only canonical source of truth and
the only release source. Integration branches are staging/coordination lines,
not alternate mains; every implementation task still uses its own child branch
and physical workspace.

## Release and CI identity

- GitHub Release: [v0.8.2](https://github.com/LTstripes/hermes-finance/releases/tag/v0.8.2), published 2026-09-05.
- Annotated tag object: `bfa1194d4151bb72882f4230f144b039d240eda9`.
- Peeled release commit: `a22542d7b20ebdf34e38384004162d409f163ab3`.
- Canonical development `main` at audit start: `96f97b0424370be93e327587633c424ee6c33a8a`.
- Exact-main CI for the audit baseline: [run 34021826830](https://github.com/LTstripes/hermes-finance/actions/runs/34021826830), `success`.
- No new release or tag is created by #306.

## GitHub issue and PR disposition

- Open PRs: none at audit start.
- Open #306: this consolidation gate; close only after the documentation, CI and branch deliverables in this report are complete.
- Open #313: backlog/architecture review for the failed Stable self-update experiment; do not implement here.
- Open #308: non-blocking cosmetic follow-up.
- Open #236: first Monthly Close workstream task, owner UAT preparation on a copied Preview DB; not started.
- Open #141: first Decision Support workstream task, Scenario Lab contract-only slice; not started.
- Open #127: permanent roadmap umbrella; remains open.
- Open #124: permanent guarded Release Control; remains open.
- Closed/not planned #298: launcher Stable self-update experiment. Merged #311 and #312 are historical follow-ups, not a request to continue patching.

## Branch and workspace audit

The live remote inventory contained 145 branches: 136 tips are ancestors of
current `main`, and 9 retain commits not reachable from it. No open PR points
at a stale task branch. Merged task branches and branches with unresolved or
historical provenance were preserved.

Cleanup decision:

- `noop-check-should-not-create` was an accidental no-op branch at
  `12610aa20c0ab8162a0b5f08f1d971291c8f749d`, already an ancestor of `main`; it
  is safe to remove through the owner/integrator-controlled remote cleanup.
- `__should_not_create`, `noop-ignore`, `integration-placeholder-do-not-use`
  and all nine non-ancestor tips were preserved because their exact intent or
  provenance was not needed to be destroyed by this task.
- The three new integration branches are created only after the final green
  post-consolidation `main` read-back and share that exact baseline SHA.

No production Stable, owner Preview or private runtime workspace was inspected
or modified. The local checkout used for this task is an independent clone.

## Stable provenance finding: `d53204d…`

Facts established from GitHub refs and issue/PR history:

1. PR #312 had candidate head `d53204d696e8b60d2241dfa6f4f83a9f3d7f886c`.
2. Remote branch `issue-298-gitkeep-upgrade-allowlist` still points to that
   candidate; it is an ancestor of current `main` through merge PR #312.
3. The published `v0.8.2` release peels to `a22542d7…`, not `d53204d…`.
4. During owner UAT, Stable was observed at `d53204d…` while its release
   contract expected `v0.8.2` / `a22542d…`; the launcher correctly failed closed
   with an identity mismatch. The owner then used the explicit recovery path.

These facts establish candidate/release identity divergence. They do **not**
establish the local operational cause of how the owner Stable checkout reached
the candidate. #306 records the provenance risk; it does not touch owner
runtime data or invent a causal explanation.

## Durable rules added or refreshed

- A bounded/microfix that expands into new architecture, invariants, test
  infrastructure or materially larger scope requires STOP, a root-cause/options
  report and explicit integrator re-scope.
- Development uses targeted tests during iteration, one full relevant harness
  before worker handoff, then package/install smoke as the final gate when
  applicable.
- Accepted PR CI and exact-main push CI are both mandatory integration evidence.
- `main` is the sole canonical/release source; `integration/*` branches are
  staging only, and task work remains on isolated child branches/workspaces.
- Production, Preview, private data and owner runtime checkouts remain outside
  implementation-agent workspaces.
- Spark/Muse-class models may handle bounded UI/docs/tests, but independent
  senior/integrator review remains mandatory for financial semantics and other
  high-risk contracts.
- Launcher Stable self-update is not a proven canonical flow. Until #313 is
  accepted, prefer composable explicit owner operations and recovery-only
  release updates.

## Documents reviewed and changed

Changed because materially stale: `AGENTS.md`, `docs/VERIFICATION_POLICY.md`,
`docs/MODEL_ROUTING.md`, `README.md`, `CHANGELOG.md`, `docs/PROJECT_WIKI.md`,
`docs/EXECUTION_HISTORY.md`, `docs/releases/0.8.2.md`,
`docs/adr/0014-launcher-runtime-profile-safety.md`,
`docs/release-notes-0.8.2.md`, `launcher/windows/README.md`, and this report.

Reviewed and retained without semantic change: `docs/MASTER_SPEC.md`, the
accepted ADR set/index, `docs/RELEASE_AUTOMATION.md`, and all client adapters
under `docs/agents/`. Their privacy, loopback, financial exactness, release
control and workspace isolation rules remain compatible with this consolidation.

## Three staging workstreams

The branches below are created from the same final green canonical `main` SHA;
the exact SHA is the post-merge read-back recorded in the #306 closeout report.

| Branch | First bounded task | Status |
|---|---|---|
| `integration/monthly-close-uat` | #236 owner UAT preparation/plan on a copied Preview DB; workers never receive real owner data | not started |
| `integration/performance-v1` | PERF-01 contract-only dated external cash flows and valuation boundaries; no XIRR/TWRR implementation | not started |
| `integration/decision-support-v1` | #141 Scenario Lab contract-only slice; deterministic read-only semantics, no write-back/forecast claims | not started |

No first task above has begun. No release/tag is created by this consolidation.

## 2026-09-06 correction — Investment Performance reconciliation

After the three workstreams were created, independent review of the proposed
PERF-01 contract found a material roadmap/documentation mismatch: the canonical
baseline already contains the accepted R08 performance foundation and released
whole-portfolio XIRR/exact-TWRR implementation.

The historical #306 audit above is preserved as-written. This correction
supersedes only its statement that the first Performance task is a new PERF-01
flow/valuation contract.

Canonical reconciliation is recorded in:

`docs/PERFORMANCE_V1_RECONCILIATION_2026-09-06.md`

and tracked by #315.

Reconciled status:

- PERF-01-equivalent foundation: **DONE** via #145/#179/#190/#197/#213/#214;
- whole-portfolio XIRR: **DONE** via #146;
- whole-portfolio exact TWRR: **DONE** via #147/#215;
- attribution: still not started.

The new Performance workstream sequence is therefore:

1. PERF-R0 reconciliation (#315);
2. accepted PERF-H1 additive edge-case hardening;
3. PERF-H2a async-transfer transit/reconciliation fail-closed implementation;
4. PERF-H2b in-kind boundary coverage persistence/fail-closed implementation;
5. PERF-H3 tax/direct-payout evidence/regression hardening;
6. owner-only performance readiness UAT on Preview/copy DB;
7. account-level XIRR;
8. account-level exact TWRR;
9. attribution contract and bounded attribution slices.

Do not create a second performance ledger, availability API, XIRR implementation
or TWRR implementation merely to follow the stale pre-reconciliation wording.
