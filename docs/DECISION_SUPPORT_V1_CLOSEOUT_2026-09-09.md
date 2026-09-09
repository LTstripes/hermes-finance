# Decision Support v1 closeout — Scenario Lab (2026-09-09)

> Compact durable record of the completed `integration/decision-support-v1`
> workstream. Normative behavior stays in `docs/MASTER_SPEC.md`, accepted
> ADRs and `docs/r07-09-scenario-lab-contract.md`; this file records what
> shipped, why the architecture looks the way it does, and what was
> deliberately deferred. No private financial values, DB names, exports or
> credentials are recorded here.

## Canonical identity

- Staging tip (last implementation commit): `26cf35afa3cb9e8803cff66473454ea768f191f7`
- Integration PR: #335 (`integration/decision-support-v1` → `main`), merged 2026-09-09
- Canonical `main` merge SHA: `420e10046a7adbe17078dcd47d8b803927f0a86a`
- Exact-main push CI run `34384056201`: all product gates green (backend
  lanes, frontend, privacy guard, Windows production smoke, release safety,
  launcher safety); `Synthetic visual audit` failed on runner environment
  only (Playwright Chromium apt install hash mismatch), unrelated to merge content
- Parent feature #141 — closed completed; roadmap #127 received
  completed-workstream status comment and stays open as umbrella
- Owner Preview UAT #333 — `PASS`; FX presentation fix #334 — completed,
  re-UAT `PASS`
- Related slices: #329 (read-only API + export), #332 (owner UI)

## Goal and safety model

Give the owner a deterministic read-only "what if" tool over a frozen
month snapshot: select a reporting month, configure exactly one supported
scenario, run it explicitly, inspect Base vs Scenario results with visible
limitations, optionally download the deterministic JSON result.

Safety model, unchanged through the workstream:

- local single-user loopback product; no cloud/auth/telemetry/trading;
- no DB writes from Scenario Lab; no scenario persistence/history;
- no auto-run, no background execution, no network/provider refresh beyond
  normal local API calls;
- exactly one shock per run; no multi-shock composition;
- frontend formats server values and validates input; it never recomputes
  financial results;
- `unknown` / `unavailable` evidence is never guessed and never presented
  as zero.

## Final delivered scope

- `POST /api/months/{month_id}/scenario-lab` — deterministic evaluation
  envelope (`metric_support`, `coverage`, `row_applicability`,
  `warnings`, reason codes, fingerprints);
- `POST /api/months/{month_id}/scenario-lab/export` — the same envelope
  as an `application/json` attachment for the exact same scenario input;
- UI route `/scenario-lab` under Planning → `Сценарии`: month picker,
  one-scenario controls, explicit `Рассчитать сценарий`, Base vs Scenario
  summary, scenario-specific detail, support/limitations panel,
  assumptions panel, explicit `Скачать JSON`;
- four v1 scenario families (below) with exact support boundaries.

## Architecture

`FrozenScenarioBase`: one capture materializes every semantic input for a
reporting month; all surfaces (evaluation, export, fingerprints) project
from that single capture with no further DB reads. This is why the mixed
frozen/live read defect (below) mattered: any second live read breaks the
"same snapshot + same normalized input = same result" guarantee that
fingerprints promise.

## Four v1 scenario families and support boundaries

- `equity_drawdown` — drawdown on authoritative `instrument_type=stock`
  rows only; no fund look-through; unknown instrument types stay
  `unknown`, never inferred.
- `deposit_rate_assumption` — hypothetical absolute annual rate over all
  eligible deposits (UI v1: `all_eligible_deposits=true`); principal and
  liquid capital unchanged, only forecast interest is projected.
- `inflation_real_value` — purchasing-power view of known future cash-flow
  rows at an annual rate (v1 monthly convention: annual ÷ 12); nominal
  facts unchanged; not a future-capital forecast.
- `fx_translation_shock` — conservative candidate-scope baseline:
  `Instrument.currency` is candidate scope only. Candidate rows stay
  untransformed as row-level `unknown` with
  `fx_translation_basis_unavailable` and make exact capital aggregates
  `unavailable`; missing/invalid currency alone is aggregate `unknown`
  (`missing_currency`); an empty affected scope is aggregate `supported`
  with exact zero impact. The UI renders all three states distinctly
  (#334) and never coerces `unknown`/`unavailable` into zero certainty.

## Owner UAT outcomes (#333, #334)

- UAT ran on an isolated copy DB; production/preview data never entered
  agent workspaces.
- June 2026 / USD +10% produced the empty-scope case live: 0 candidates,
  0 unknown, only not-applicable rows, supported unchanged liquid
  assets/capital with exact 0 impact — while the UI still claimed
  `Недоступен точный пересчёт`. Filed as #334, fixed frontend-only,
  re-UAT `PASS`.

## Bugs caught before merge and why they matter

- Ambient `Decimal` precision bugs in equity/rate/deposit math — local
  decimal context leaked into domain math; fixed so money stays exact.
- Mixed frozen/live DB reads during Scenario capture — broke the
  frozen-base guarantee; fixed to single capture → pure projection.
- Invalid `metric_support=unchanged` state — a non-contract status that
  would have hidden limitation semantics; removed.
- API machine-readable validation code loss — UI/debugging needs exact
  codes (`reporting_month_not_found`, `unsupported_*`, `invalid_*`);
  preserved through the API seam.
- Client range narrowing vs backend semantics — FX is signed `>= -100`
  with no positive cap (`-10`, `150` valid); deposit/inflation have no
  `100` cap; only equity drawdown is `0..100`. UI validates as string
  decimals and lets the backend enforce financial bounds.
- Stale async result race — an in-flight POST resolving after
  month/scenario/parameter changes could publish a stale result as
  current; fixed with request sequence + `AbortController` and
  deferred-promise regressions.
- FX empty-scope `supported` presented as `unavailable` — caught by real
  owner UAT (#333 → #334); fixed by branching the FX detail callout on
  server aggregate support.

## Deferred work (explicit, not started)

- Issuer impairment — waits for authoritative issuer identity.
- Exact FX translation — waits for authoritative native-value/base-FX
  semantics.
- Multi-shock composition (`unsupported_composition_v1` stays).
- Monte Carlo / VaR / probabilities / correlations — out of scope.
- Dedicated Insights UI and projection expansion beyond current-state
  Tax/IIS Planner v1 remain deferred alongside.

## Workstream sequence

1. Post-v0.8.2 baseline and contract-first start (#306 consolidation,
   three-workstream split).
2. Scenario Lab contract + adversarial review.
3. 141-A equity implementation and fixes.
4. 141-B deposit-rate + `FrozenScenarioBase` refactor.
5. 141-C inflation real-value.
6. Reconciliation with the canonical `main` FX baseline.
7. #329 read-only API + deterministic JSON export.
8. #332 owner UI (+ integrator blockers: signed FX validation,
   stale-result race).
9. #333 owner Preview UAT on isolated copy DB.
10. #334 FX empty-scope presentation fix discovered by real UAT.
11. PR #335 → canonical `main` merge `420e10046a7adbe17078dcd47d8b803927f0a86a`.

## Follow-up

The Decision Support staging workstream is completed. Future work starts
from canonical `main`, not from `integration/decision-support-v1`.
This closeout is linked from `docs/PROJECT_WIKI.md` and
`docs/EXECUTION_HISTORY.md`.
