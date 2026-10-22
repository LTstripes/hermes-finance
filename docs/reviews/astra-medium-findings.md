# Astra medium/low methodology findings

Baseline/target: fd51120dd763a13d3ee98e3619d92c6bbca2db5c (main, PR #926).
Worker branch: test/astra-medium-xfail. Synthetic observations only.
These are counterexamples and proposed expectations, not accepted product changes.

The assignment is the Owner's current task message. The local PR #926 commit receipt and
applicable C7 clauses were read: numerical limitations (5432–5451), monthly chain
(5734–5749), classification precedence (5766–5777), and income/coverage (5791–5826).
CURRENT_STATUS's draft wording predates the pinned merge. GitHub CLI was unauthenticated,
so live issue/Integrator comments could not be retrieved; no credentials were inspected
and no live comment review is claimed.

Each finding has exactly one strict xfail in
[test_astra_medium_xfail.py](../../backend/tests/test_astra_medium_xfail.py).
Tests assert desired behavior. All marks use strict=True and raises=AssertionError,
so unexpected setup/import/runtime exceptions cannot count as expected failures.
Existing synthetic builders are reused; there are no new fixture files.

All file references below are relative to backend/src/hermes_finance/.

| N | Severity | Area | File:line | Synthetic case | Actual on baseline | Expected | Fix idea |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Low | Position blocker scope | services/source_monthly_returns.py:31, :308; statement_import/mybroker.py:392 | Fully parsed April RUB Money with no movements; additional USD position with opening/closing quantity zero | position_row_unclassified makes monthly/period contributions and withdrawals NULL with unknown_flow; valuations also withheld | Flow totals remain (0, 0). No FX valuation or removal of position warning is required | Separate valuation completeness from flow completeness; assess whether the position limitation can conceal cash movements |
| 2 | Medium | Transfer/income precedence | services/source_money_classifications.py:46, :70 | Перевод; description купонный доход Synthetic bond; +10 RUB; unsupported kind | coupon | unknown for this undirected transfer; generic income words do not prove coupon receipt | Resolve explicit transfer semantics before generic coupon words while preserving supported exact coupon patterns |
| 3 | Low | Narrative case | services/source_money_classifications.py:46 | Перевод; −10 RUB; в АО Synthetic / В АО Synthetic / в ао Synthetic | external_withdrawal / unknown / unknown | Same withdrawal classification for all three | Normalize case consistently in the AO rule |
| 4 | Medium | Short period / solver range | domain/xirr.py:20, :168, :282 | −100 kopecks on 2030-01-01; +200 on 2030-01-02 | NULL, not_computable_xirr_no_valid_root, zero iterations | Unique finite annualized root 2**365−1, about 7.52e109; exhausted search is not proof of no root | Expand the certified single-root log bracket adaptively, or distinguish numerical search limits from mathematical nonexistence |
| 5 | Low | Decimal context isolation | domain/xirr.py:249–260 | −10,000 kopecks on Jan 1; +11,000 on Feb 1, 2030; caller precision 6 | Available/exact 2.071606131452619… rather than 2.071605853472129…; error about 2.78e−7 | Agreement with independent (11/10)**(365/31)−1 to 1e−24, independent of caller precision | Build year fractions inside the solver's high-precision local context |
| 6 | Low | Missing-month income | services/source_monthly_returns.py:371, :492 | April and June sources, no May source or observed May income | May has no intake IDs and flow_coverage_gap, yet coupons/dividends both zero | Both income totals NULL for an uncovered month; a covered quiet month may be zero | Make income subtotals coverage-aware, retaining any observed partial subtotal separately |
| 7 | Low | No-history flow totals | domain/monthly_return_chain.py:182–198; services/source_monthly_returns.py:408 | Empty database; requested account has no source-backed interval | No months, NULL growth/rates and insufficient_boundaries, but contributions/withdrawals (0, 0) | Flow totals (NULL, NULL) without source history | Preserve unknown totals in insufficient-boundaries/no-history results; reserve zero for an evidenced schedule |

## Verified OK; no xfails added

- Mandatory nit 4: operation Расчёты по сделке, narrative Выплата НКД Synthetic trade,
  unsupported kind, −10 RUB returns trade_settlement. The settlement check at
  services/source_money_classifications.py:60 precedes NKD/coupon fallbacks.
- No sign change returns not_computable_xirr_no_valid_root. Multiple/hidden roots
  fail closed with root_ambiguity. An iteration limit of one reports
  convergence_failed. Conservative rejection of multiple coefficient sign variations
  is the accepted C7 certificate, not a new defect.
- Non-positive Dietz denominators withhold the rate and preserve growth. A large
  withdrawal uses signed remaining-day capital; a closing-day contribution has zero
  weight. Negative factors withhold chaining; a zero factor remains allowed.
- Chained Dietz and period XIRR can differ under timed flows. The UI already labels
  the chain “Цепной Modified Dietz (≈TWRR, приблизительно)” at
  frontend/src/ui-v2/UiV2MonthlyReturnsPage.tsx:311; it does not claim exact twrr.py.
- Return-schedule assumption flags are ORed across months and chain reasons unioned.
  Income assumptions intentionally have their separate monthly flag (C7:5791–5796).
  Instrument all-time aggregation ORs income_assumptions_used and unions flags
  (services/source_instrument_returns.py:618–655). No xfail is justified here.
- Coupon/dividend income uses the posted source month and is not added again as
  external investor flow. NKD verbal variants and stored-assumption re-evaluation
  were excluded from this task.

## Verification

Fresh checkout-local backend/.venv: CPython 3.13.16 and locked dev dependencies.
The normal sync could not download packages because network sockets are blocked.
A copy of the package-only uv cache was placed inside this checkout; then
uv --cache-dir .uv-cache sync --project backend --locked --group dev --offline
succeeded. No sibling venv or private data was used.

Commands run from backend unless stated otherwise:

- python -m pytest -q tests/test_astra_medium_xfail.py --tb=short → 7 xfailed,
  exit 0; no XPASS, skips or errors.
- python -m pytest -q tests/test_astra_medium_xfail.py --runxfail --tb=short →
  7 failed, exit 1. Every failure is the intended expected-behavior assertion,
  not collection, import or setup failure.
- uv run --locked --offline ruff check tests/test_astra_medium_xfail.py tests/_test_taxonomy.py
  → passed (the actual invocation used --project backend from the repo root).
- uv run --locked --offline ruff format --check tests/test_astra_medium_xfail.py tests/_test_taxonomy.py
  → 2 files already formatted (same root invocation).
- python -I -m pytest -q tests/test_ci_lane_ownership.py → 19 passed.
- Focused existing controls: test_monthly_return_chain.py; three solver controls
  in test_r08_02_portfolio_xirr.py (coalescing/no root, multiple roots/convergence,
  hidden roots); and source-monthly income/withdrawal plus negative-factor
  reaggregation controls → 31 passed.

Two test-only entries in tests/_test_taxonomy.py register the mandated new filename
in ci_core / ci_core_a without moving existing shard anchors. An initial run before
registration correctly rejected the unclassified file; no collection bypass was used.
The task's filename rule is preserved: all new tests are in the one new file.
The tracked-file privacy guard passed (1,325 existing tracked files). The same
path/content guards were also applied directly to all three changed files,
including both untracked files: passed. Git diff --check passed for the tracked diff.
No full backend suite, independent review, remote CI or Owner UAT was run.

Delivery limitation: git add failed before staging because the sandbox denied
creation of index.lock under the worktree's external Git administration directory.
No commit was created. HEAD remains the pinned baseline; the working-tree candidate
contains the three reviewed files. No branch was pushed. Completing the requested
commit requires writable access to that Git directory in the execution environment.

Excluded: B1 conflicting XIRR boundary observations, C1 NKD verbal forms, C2 internal
transfer scope, C3 stored assumed classifications, PR #927 fixtures/astra_hunt, and
P1–P3 partial-period statements. Finding 1 tests only the requested position blocker
nit. No product implementation, migration, runtime, private data or stored choices
are changed. No push, merge, release or Owner UAT is implied.
