# Financial completeness — known subtotal and portfolio-source coverage

- **Status:** #498 canonical contract. Runtime behavior is unchanged in this change.
- **Baseline:** `integration/data-integrity-hardening` at `31dc9af` (Merge PR #520).
- **Issue:** [#498](https://github.com/LTstripes/hermes-finance/issues/498)
- **Review:** independent product/financial-semantics review is required before any follow-up implementation.

This document defines how a mathematically exact sum of persisted rows relates to coverage words. It does not change `MASTER_SPEC` §10.1 arithmetic, ADR 0007 composition classes, close guards, or performance formulas.

## 1. Three axes

These words are separate. A single field must not collapse them.

| Axis | Words | Meaning |
|---|---|---|
| Known subtotal | the canonical formula over persisted included rows that exist | Integer-kopeck sum. A required account with no snapshot stays in the catalog. Its snapshot value is absent from this sum and is never stored or displayed as `0.00`. |
| Availability | `available`, `unavailable` | `available` means the numeric claim is present. `unavailable` means the value is withheld (`null`), including when no capital evidence exists. |
| Precision | `exact`, `approximate`, `unknown` | `exact` means the number is the exact minor-unit result of its declared formula over its declared inputs. |
| Coverage | `complete`, `partial`, `unavailable` | Whether the named source set for that claim is fully represented. |

`exact` is precision. `partial` and `complete` are coverage. An available exact known subtotal can sit beside partial coverage.

`unavailable` on a metric withholds the number. `unavailable` on coverage means the named source set cannot be judged or the claim has no usable evidence. Read the field, not the word alone.

## 2. Portfolio-source coverage

This claim answers one question: for this reporting month, does every account required for liquid capital have a persisted snapshot?

**Required set (read time, current catalog).** An account is required when `status = active` and `include_in_capital = true`. Hermes has no effective-dated capital-inclusion history. ADR 0007 does not snapshot global account flags. Until a separate architecture adds that history, this current catalog is the required set. Closed-month immutability protects persisted month rows. It does not freeze this coverage label.

**Represented.** The month represents that account when it has at least one of:

- a position snapshot for the account;
- a deposit snapshot for the account;
- a cash-balance row whose `account_id` is that account.

`CashBalance.account_id = NULL` is synthetic/unassigned cash, the same identity as integrated #497. It does not satisfy the snapshot requirement of any real account, including an account with `account_type = cash`. When `include_in_capital` is true, that row's amount can still sit in the known subtotal as unassigned cash. It is not a catalog account.

An explicit zero amount is a real snapshot. Frozen, closed, hidden, and `include_in_capital = false` accounts are outside this required set.

**Outcomes.**

- `complete` — every required account is represented.
- `partial`, reason `active_account_snapshot_missing` — at least one required account is missing a snapshot, and the month still has some persisted capital or included-debt evidence. The known subtotal stays `available` and `exact`.
- Capital metric `unavailable`, reason `portfolio_snapshot_missing` — the month has no persisted portfolio or included-debt snapshot rows. The total is withheld. It is not published as `0.00`.

`stale_valuation` stays a freshness fact. A stale price keeps the persisted position and does not by itself make portfolio-source coverage partial. `future_dated_valuation` stays the stronger existing rule: the affected capital value is withheld for that period. `draft_value` / `draft_month_incomplete` stay additional draft defects. A closed month does not carry them.

## 3. Reproduced two-account case

Closed reporting month:

- active capital-included account A has a snapshot worth `100.00` RUB;
- active capital-included account B has no position, deposit, or cash snapshot;
- the `100.00` RUB figure is the sum of the included rows that exist.

Canonical reading on every surface:

| Claim | Result |
|---|---|
| Known subtotal `liquid_capital_net` | `100.00` RUB |
| Availability of that subtotal | `available` |
| Precision of that subtotal | `exact` |
| Portfolio-source coverage | `partial` |
| Reason | `active_account_snapshot_missing` |
| Account B | stays in the account catalog and in missing-account metadata. Its snapshot value is absent from the subtotal and is never `0.00` |
| Complete liquid capital / complete portfolio value | not established |

Included debt or extra persisted rows stay inside the known subtotal. They do not cure account B.

A consumer may show `100.00` as the known subtotal. The same payload or screen must carry `partial` / `active_account_snapshot_missing`. A consumer that cannot carry that marker must not present `100.00` as the period's complete capital.

Close stays allowed. The existing close-readiness warning is about the missing account. It is not an instruction to null the period subtotal, and it is not a hard close blocker.

## 4. What `history.coverage = complete` attests

`reporting_history[].coverage` is the point-level coverage aggregate already used for that history point: portfolio-source coverage, draft, gap versus the previous stored reporting month, future-dated included valuation, property-quality codes on that point, and passive-history-before-start.

`complete` means none of those defect classes fired for that point. Portfolio-source incompleteness is one of those classes. In the two-account case the point is `partial` with `active_account_snapshot_missing`.

That field does not attest:

- cash-boundary / cash-history completeness;
- performance computability;
- price freshness;
- salary-tax history (`salary_tax_context.history_coverage` is a separate claim);
- a gap-free calendar across the whole archive (`coverage.missing_calendar_periods` / `reporting_history_gap`).

`coverage.domains.portfolio` is the selected period's portfolio-source coverage. `coverage.domains.capital` is partial when any reporting-history point has `active_account_snapshot_missing`. `coverage.domains.history` on the financial review follows the same point coverage through historical dynamics.

`total_net_worth` remains unavailable (`no_authoritative_aggregate` / `total_net_worth_unavailable`). That partial is a different claim. It can appear together with `active_account_snapshot_missing`. One reason does not stand in for the other.

## 5. Source / coverage matrix

The two-account case, same closed period.

| Surface | `100.00` means | Coverage that must travel with it | Current behavior at this baseline | Follow-up |
|---|---|---|---|---|
| v1 Dashboard and month detail; v2 Home via closed-report comparison | known subtotal | `partial` / `active_account_snapshot_missing` | number only | F3 |
| v2 Capital: net, composition, allocation shares | known subtotal; shares are shares of that subtotal | same marker on the net and on allocation support | number and shares only | F3 |
| v2 Reports / history archive | known subtotal of each closed point | per-point marker | amount only | F3 |
| Closed-to-closed delta | exact difference of the two known subtotals | partial when either endpoint is partial | unmarked delta | F3 |
| Month close readiness and deterministic insight | warning for the missing account | already `active_account_snapshot_missing`; close still allowed | two-account warning aligned. One `account_id` NULL cash row still treats every active capital-included cash account as represented | F4 |
| AI bundle `reporting_history[]` KPI | known subtotal, `available` / `exact` | point `coverage` partial, and the same reason on `liquid_assets_total`, `included_debts`, `liquid_capital_net` | point `coverage` can be `complete`; KPI reason list can be empty; value is the subtotal | F1 |
| AI bundle `coverage.domains.capital` | — | `partial` with the same reason | can be `complete` | F1 |
| AI bundle `current_portfolio.coverage` and `coverage.domains.portfolio` | — | `partial` / `active_account_snapshot_missing` | already this | none |
| Portfolio-review and financial-review capital section | known subtotal | snapshot reason in addition to the net-worth reason | section is partial only because total net worth is unavailable; metric reasons can be empty | F2 |
| Financial-review `coverage.domains.history` | — | `partial` once the history point is partial | can be `complete` | F2, via F1 |
| Capital goal current value / progress | known subtotal | same snapshot reason; not complete-capital progress | reason can be absent | F2 |
| Allocation / concentration denominator | shares of the known subtotal | support `partial` with the same reason | can be included with no snapshot reason | F2 |
| Performance availability, XIRR, TWRR, valuation point | not this subtotal | fail closed when a historically selected account lacks a required component | already withholds an exact total | none |
| Cash-boundary coverage | unrelated owner attestation of cash crossings | independent `complete` / `unknown` | independent | none |

Comparison, goals, and allocation keep their existing arithmetic. Only the coverage metadata changes in the follow-ups.

## 6. Current catalog and historical membership

| Question | Rule |
|---|---|
| Which accounts are required for this portfolio-source claim? | Current `active` + `include_in_capital`. Read time. |
| Which rows enter the known subtotal? | The rows `liquid_capital_for_month` already includes. Current `include_in_capital` still filters deposits and securities. This contract does not change that sum. |
| Which accounts are in a historical performance scope? | `account_performance_scope_memberships` only. Current `include_in_returns` must not rewrite that history. |
| Account in capital, outside performance membership | Affects portfolio-source coverage and the known subtotal. It does not become a performance member. |
| Account in historical performance membership, outside capital | Can block performance. It is not a required capital snapshot. |

Changing `status` or `include_in_capital` can change the coverage label of an already closed month without rewriting snapshot amounts. That is the accepted interim. Effective-dated capital membership is out of scope.

## 7. Performance prerequisites stay separate

Performance quality `exact` means the accepted performance prerequisite set is satisfied. Capital precision `exact` means the known-subtotal arithmetic is exact. Those two uses of `exact` must not be copied onto each other.

For a valuation point, each account selected by historical performance membership still needs positions, deposits, and performance cash, or the point stays non-exact with `not_computable_scope_coverage_incomplete`. A single position snapshot of `100.00` RUB does not satisfy that set. Portfolio-source coverage is the only claim for which one position, deposit, or account-linked cash snapshot represents that real account.

Cash-boundary coverage (`docs/r08-01c-performance-availability.md`) is an owner attestation that cash crossings are known. It stores no amount. Snapshot presence does not prove it. Its absence does not change the capital known subtotal and does not create `active_account_snapshot_missing`.

## 8. Follow-up implementation

File these only after independent review of this contract. Do not change formulas, close blockers, performance component rules, or cash-boundary rules inside them.

### F1 — AI analysis bundle metadata

`backend/src/hermes_finance/services/ai_analysis_bundle.py` and `backend/tests/test_ai_analysis_bundle_export.py`.

For each reporting-history point, when portfolio-source coverage is partial:

- `reporting_history[].coverage` is `partial` and includes `active_account_snapshot_missing`;
- `liquid_assets_total`, `included_debts`, and `liquid_capital_net` stay the known subtotal: `available`, `exact`, value present;
- those three metrics include `active_account_snapshot_missing` in `reason_codes`;
- `coverage.domains.capital` is `partial` with that reason when any point has it.

Keep `portfolio_snapshot_missing` for a month with no capital evidence, value `null`. Keep the selected-portfolio block as it is: the missing account stays in the account catalog and in `missing_snapshot_account_refs`. `test_cash_snapshot_detection_is_account_specific` is the closest fixture; extend it to the history point and the KPI reason list. Reason codes are already free-form strings in the bundle schema. Emitting a new status/reason combination changes instance meaning, so the follow-up records a bundle `schema_version` minor bump under `docs/AI_ANALYSIS_BUNDLE.md`.

### F2 — Review, goals, and allocation metadata

`portfolio_review_package.py`, `ai_financial_review.py`, and their tests.

- Capital-section reasons include `active_account_snapshot_missing` when the selected point has it, and still include the existing net-worth reason.
- The capital metric stays `available` / `exact`.
- Historical-dynamics coverage follows the history point, so the review history domain becomes `partial`.
- A capital goal's current value and progress keep the known subtotal and carry the same reason.
- Allocation / concentration support becomes `partial` with the same reason when its denominator is that partial subtotal. Shares are not recomputed.

### F3 — Owner-facing marker

Add portfolio-source coverage, computed with the section 2 rule, onto the read models that already emit the known subtotal: month dashboard liquid capital, closed-report comparison (including the delta), and capital composition. Render that marker beside the figure on v1 Dashboard, v1 month detail, v2 Home, v2 Capital, and v2 Reports/history. Do not reimplement the required-account rule in React. Do not hide or restate `100.00`. The missing account stays visible in the account list.

### F4 — Close-readiness cash identity

`backend/src/hermes_finance/services/close_readiness.py`, and the deterministic insight that repeats its warning.

A `CashBalance` row with `account_id = NULL` must not count as the snapshot of any real account. The AI bundle missing-snapshot check already requires a matching `account_id` (#497). Leave the known-subtotal formula unchanged. This docs change does not edit that detector.

## 9. Non-goals

- No formula, migration, or UI change in the #498 contract change.
- No new account-membership history.
- No change to close hard guards.
- No weakening of performance fail-closed behavior.
- No use of cash-boundary coverage as a proxy for missing snapshots.
- No freshness or property-identity redesign.
- No second capital total that zero-fills account B.
- No removal of a missing account from the catalog or from missing-account metadata.
- No use of unassigned cash as the snapshot of a real account.
