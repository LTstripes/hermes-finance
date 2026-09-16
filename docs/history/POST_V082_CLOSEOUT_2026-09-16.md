# Hermes Finance — post-v0.8.2 closeout ledger (2026-09-16)

> Durable checkpoint for accepted/integrated work after the published `v0.8.2` release.
>
> This supplements `docs/EXECUTION_HISTORY.md`; it does not replace historical release/task records. Private owner data is intentionally omitted.

## Canonical checkpoint

At this closeout:

- published Stable remains **v0.8.2**;
- published Stable peeled commit remains `a22542d7b20ebdf34e38384004162d409f163ab3`;
- canonical development `main` is `e5c09d55a21d4d4a25a9505a819977ed9a162f8c`;
- exact-main push CI #688 / run `35137779786` completed `SUCCESS`;
- no release publication was performed by the work below.

## Recent accepted product / integrity work

### #365 — linked asset / credit-card debt

- Status: CLOSED / owner UAT PASS.
- Outcome: accepted linked financing semantics and owner-facing flow integrated before this checkpoint.
- Privacy boundary: no private owner values are repeated here.

### #366 — AI financial review hardening

- Status: CLOSED / owner re-download UAT PASS.
- Outcome: accepted AI financial-review hardening integrated; owner re-download acceptance completed.

### #331 — canonical AI report / export UX

- Status: CLOSED.
- Outcome: canonical AI report/export UX line completed.

### #367 — Monthly Close actionable-panel scroll/focus bookkeeping

- Status: CLOSED because the implementation had already landed through PR #368.
- Outcome: stale bookkeeping removed; no duplicate implementation created.

### #376 — AI review capital-goal `source_metric_path`

- Status: CLOSED via PR #383.
- Outcome: bounded source-metric-path correctness fix integrated.

### #379 — linked financing integrity

- Status: CLOSED via PR #384.
- Outcome: linked financing integrity hardening integrated before the runtime slices below.

### #381 — policy/privacy hygiene

- Status: CLOSED via PR #382.
- Outcome: repository policy/privacy hygiene synchronized without product-scope expansion.

## Runtime / launcher redesign

### #380 — R09-OPS01: prepared runtime state and fast deterministic start

- Parent: #313.
- Accepted candidate: `665b871dd0b0eb9459f7d8d99af8a0b8aba58fec`.
- PR: #385.
- Canonical merge: `cc85ad80c58fabb74de36f8bc67b04ccff14b6a4`.
- Exact-main CI: #665 — SUCCESS.
- Independent review: runtime/safety ACCEPT.

Delivered:

- explicit `scripts/prepare-runtime.ps1 -Prepare`;
- explicit `-Validate`;
- ignored prepared-state proof tied to exact code/dependency/frontend build inputs;
- ordinary `scripts/start-local.ps1` validates prepared state and does not silently build/install/update Git;
- loopback-only runtime boundary preserved.

Not delivered:

- no Stable release switching;
- no Preview exact-SHA lifecycle;
- no launcher updater state-machine resurrection.

### #386 — R09-OPS02: explicit Stable update to one published immutable release

- Parent: #313.
- Accepted candidate: `44c70166bc4527f7740e2516559fc841bec47de4`.
- PR: #393.
- Canonical merge: `c2eab48ef4e20fb14f64c527f543422a6d46f76a`.
- Exact-head PR CI: #672 / run `35113977412` — SUCCESS.
- Exact-main CI: #673 / run `35116088146` — SUCCESS.
- Independent Grok 4.6 runtime/safety review: ACCEPT, blockers 0.

Delivered:

- `scripts/update-stable.ps1` owner operation from a trusted control checkout;
- explicit target published immutable version only;
- read-only remote proof before mutation;
- verified SQLite backup before Git/ref/worktree mutation;
- tag-only fetch + annotated target reproof;
- detached exact target commit pinning;
- ignored/private/reparse safety protections;
- target release Prepare + Validate;
- no auto-start and no DB migration inside update.

Acceptance boundary:

- implementation is canonical;
- **real owner Stable release-to-release UAT is pending** until the next genuine published Stable release;
- no throwaway release should be published merely to exercise OPS02;
- #313 therefore remains open.

## Performance component-decomposition line

### #396 — PERF-04B: component attribution go/no-go and contract

- Verdict: **PARTIAL GO**.
- Accepted docs candidate: `e8e6783157db3899c7c5a5e6127192dadbcbef40`.
- PR: #398.
- Canonical merge: `2c76c82065d560c895aa377ec036860ec857f0b2`.
- Exact-head PR CI: #681 — SUCCESS.
- Exact-main CI: #682 / run `35128956952` — SUCCESS.
- Independent financial-semantics review: ACCEPT.

Accepted parent identity:

```text
B_portfolio = Σ B_account + Σ T_internal_transfer
```

where `B` is existing PERF04A `value_change_after_external_flows` and `T_internal_transfer` is a strict reconciliation component.

Critical contract limits:

- no false exact `100 → 99 = -1` without accepted reconciliation evidence;
- `D>S` unavailable;
- cross-currency amount unavailable;
- `fx_conversion_spread` alone is not exact PERF04C cost evidence;
- no residual bucket;
- instrument/asset-class and realised/unrealised/cost-basis attribution remain unsupported.

Canonical contract: `docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`.

### #400 — PERF-04C: account + internal-transfer decomposition read model

- Baseline: `2c76c82065d560c895aa377ec036860ec857f0b2`.
- Accepted candidate: `65563330f16cf7191ac3b3560d0c3cfee2cbb57a`.
- Branch: `task/400-perf04c-account-transfer-decomposition`.
- PR: #402.
- Canonical merge: `e5c09d55a21d4d4a25a9505a819977ed9a162f8c`.
- Exact-head PR CI: #687 / run `35137363144` — SUCCESS.
- Exact-main push CI: #688 / run `35137779786` — SUCCESS.
- Independent Grok 4.6 financial-semantics/backend review: ACCEPT, blockers 0.

Implementation files:

- `backend/src/hermes_finance/domain/performance_decomposition.py`;
- `backend/src/hermes_finance/services/performance_decomposition.py`;
- `backend/src/hermes_finance/domain/__init__.py`;
- `backend/tests/test_perf04a_attribution.py`.

Accepted implementation properties:

- parent is existing portfolio PERF04A;
- account rows reuse existing account-scope PERF04A;
- integer minor-unit endpoint/flow/additive identities verified before publish;
- unavailable decomposition returns `value=null` and no exact-looking component rows;
- same-currency `fx_conversion_spread` can leave parent PERF04A available under existing R08 semantics but does not make PERF04C exact;
- cross-scope transfer remains an external portfolio flow and is not a `T` row;
- no API/UI/schema/migration/XIRR/TWRR/PERF04A formula change.

Worker reported targeted PERF04A/PERF04C `42 passed`, R08 regressions `87 passed`, full backend `1866 passed`, Ruff/format/privacy/diff checks green. Canonical CI independently passed after merge.

## What is deliberately not closed by these tasks

### Launcher/runtime

#313 remains open for:

- first real OPS02 Stable release transition UAT;
- exact Preview/UAT candidate pinning operation;
- later bounded diagnosis/recovery if useful;
- later decision whether launcher should become a thin wrapper over accepted operations.

The old monolithic launcher updater remains rejected as an architecture direction.

### Performance

PERF04C completes exact **account + internal-transfer money decomposition** only.

Still unsupported as exact:

- instrument contribution;
- asset-class contribution;
- price-vs-FX decomposition;
- realised/unrealised P&L;
- trade/lot/cost-basis attribution;
- additive XIRR/TWRR contribution.

A future exact slice requires a new accepted data/evidence foundation, not frontend approximation.

### UI v2

UI v2 is a separate independent workstream. This closeout intentionally does not redefine or integrate its task sequencing.

## Next non-UI direction

The next bounded runtime slice under #313 should be an exact **Preview/UAT preparation pinned to one explicit candidate SHA**:

- explicit exact commit identity;
- separate non-production checkout;
- isolated UAT DB / synthetic data;
- no production DB alias;
- no automatic following of newer `main` during owner UAT;
- reuse accepted Prepare/Validate/Start primitives;
- no launcher UI initially.

## References

- `docs/CURRENT_STATUS.md`
- `docs/PROJECT_WIKI.md`
- `docs/OWNER_RUNTIME_OPERATIONS.md`
- `docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md`
- `docs/performance/PERF04B_COMPONENT_ATTRIBUTION_CONTRACT.md`
- #127, #313, #380, #386, #396, #400
- PR #385, #393, #398, #402
