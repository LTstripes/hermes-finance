# Investment Performance v1 — reconciled roadmap

> **Task:** #315 (`PERF-R0`)
> **Reconciliation date:** 2026-09-06
> **Baseline:** `49b290df5d407fafff05a8aac6e3c081fdd8ea45`
> **Staging:** `integration/performance-v1`
> **Canonical/release source:** `main`

## Why this reconciliation exists

The post-v0.8.2 roadmap and consolidation report described a new sequence
`PERF-01 -> PERF-02 -> PERF-03`, but the canonical baseline already contains
and has released the corresponding R08 foundation and whole-portfolio return
metrics. Starting that sequence again would create duplicate contracts and
risk conflicting financial semantics.

This document reconciles the new workstream with the accepted R08 state. It is
an additive correction; it does not rewrite the historical R08 implementation
or the original #306 audit.

## Canonical R08 state already DONE

The following foundations are accepted and must not be reimplemented as a
parallel performance stack:

- #145 — dated external-flow / valuation contract, including accepted v2
  blocker resolutions;
- #179 — external-flow persistence and durable transfer linkage;
- #190 — valuation points and performance coverage;
- #197 — performance availability API with stable fail-closed reasons;
- #146 — production whole-portfolio XIRR;
- #147 plus #213/#214/#215 — production exact whole-portfolio TWRR using
  persisted observed pre/post external-flow valuation boundaries.

Current R08 remains authoritative for its released scope:

- externality is relative to the selected performance boundary;
- portfolio transfers between proven in-scope accounts are internal;
- account-scope linked transfer legs cross each account boundary;
- existing `investment_cash_flows` are not automatically external flows;
- coupons/dividends/redemptions/fees/taxes are not injected a second time into
  total-return math while they remain internal to the selected scope;
- external boundary amount is exact, non-negative and direction is explicit;
- historical ambiguity is fail-closed, never guessed or converted to zero;
- current-state broker snapshots are not historical performance truth;
- exact TWRR uses observed boundary evidence only: no interpolation,
  start-of-day/end-of-day assumption, or arithmetic boundary derivation;
- missing historical FX, cash classification, scope membership, valuation or
  transfer identity remains `NOT_COMPUTABLE` under stable reason codes;
- exact arbitrary-period performance requires trusted opening history; Hermes
  does not invent an inception-zero merely because local data begins there.

## Reconciled status of the old roadmap

| Old roadmap item | Canonical result | Reconciled status |
|---|---|---|
| PERF-01 — dated external investment cash flows / valuation boundaries | #145/#179/#190/#197/#213/#214 | DONE for existing R08 scope |
| PERF-02 — XIRR / money-weighted return | #146 | DONE for whole portfolio |
| PERF-03 — exact TWRR | #147/#215 | DONE for whole portfolio |
| PERF-04 — attribution | no accepted implementation | NOT STARTED |

## Accepted PERF-H1 hardening contract

Independent review of PERF-H1 v2 returned `ACCEPT`. A subsequent independent
Astra audit found two additional completeness gaps in canonical R08. Direct
baseline inspection confirmed both gaps: interval membership coverage currently
permits known `false -> true` / `true -> false` changes, while external-flow
coverage currently becomes `COMPLETE` from the absence of known blockers rather
than from affirmative boundary-history coverage. PERF-H1 is therefore finalized
as v3 with six additive sections A-F below.

The contract does not redesign R08. Its policy remains:

**false unavailable > false exact**.

### H1-A — asynchronous owned-account transfer transit

A linked A -> B transfer between two historically proven in-scope accounts
remains `INTERNAL_TRANSFER` for whole-portfolio scope even when its legs settle
on different dates. Different settlement dates never turn it into an owner
contribution/withdrawal.

If `source_leg.event_date < destination_leg.event_date`, the interval from the
source departure through destination arrival is transfer transit. Money in
transit is economically still part of the owner portfolio, but current Hermes
valuation components do not represent a synthetic in-transit asset.

Hermes must not synthesize cash-in-transit, move leg dates, temporarily classify
the transfer as external, or silently treat omitted transit value as return.

A required whole-portfolio valuation is unsafe when its effective/observation
date falls on or between those date-only endpoints and there is no explicit
trusted provenance proving that the valuation includes the transferred capital.
Same-day ordering continues to use the existing fail-closed boundary-order
semantics unless explicit provenance proves order.

Metric-specific effect:

- XIRR checks only the required opening and closing valuations;
- exact TWRR checks opening, closing and every observed pre/post valuation
  boundary actually consumed by an external-flow subperiod split;
- an unrelated intermediate TWRR boundary inside transit does not by itself
  make XIRR unavailable;
- account-scope legs remain withdrawal/contribution on their actual dates and
  are not blocked merely because the aggregate portfolio transfer has transit.

New stable reason:

`not_computable_transfer_in_transit_unvalued`

Structural linkage alone is not proof that whole-portfolio value reconciles.
For same-currency v1 performance, transfer legs must either have equal boundary
amounts or the difference must be explained by authoritative canonical evidence
from this closed set:

- broker fee / commission charged inside scope;
- tax charged inside scope;
- accepted FX conversion/spread evidence under an existing currency contract.

Reconciliation evidence must identify the specific transfer it explains; one
fee/tax item cannot be reused to reconcile multiple overlapping transfers. FX
reconciliation never bypasses the existing performance-currency completeness
gate.

No other unexplained reconciliation category is allowed without a future
accepted contract. An unexplained difference remains fail-closed with:

`not_computable_transfer_reconciliation_incomplete`

Partially linked/one-legged transfers continue using the existing unresolved
transfer reason. Overlapping transit intervals are evaluated independently;
intersection with any unvalued transit interval blocks the affected required
whole-portfolio valuation. Detection must not be limited to transfer legs whose
own event dates fall inside the requested interval: a transit interval may span
a required valuation even when both leg dates lie outside that request window.

### H1-B — in-kind securities crossing a performance boundary

Hermes must never synthesize cash for a security or other non-cash asset merely
to satisfy XIRR/TWRR inputs.

Absence of `ExternalFlow` or legacy cash deposit/withdrawal rows is not proof
that no in-kind movement occurred. Exact performance therefore requires
explicit in-kind boundary coverage for accounts capable of holding transferable
investment instruments.

For current v1, that population is deterministic and restricted to accounts
that are historically relevant to the selected performance scope:

- canonical account type `brokerage`;
- canonical account type `iis`;
- any account that has persisted `position_snapshots` in or before the requested
  interval, even if its generic account type is broader.

Cash-only/other accounts with no persisted investment positions do not acquire
an in-kind coverage requirement merely because they exist.

Minimum coverage states:

- `COMPLETE` — the required account/interval is explicitly covered and every
  in-kind boundary movement is known, including the valid case where there
  were none;
- `UNKNOWN` — Hermes cannot establish whether such movement occurred.

`COMPLETE` means the history is known; it does not mean the movement set is
empty. A known but unvalued movement continues to block exact performance.
Coverage must retain account/interval identity and provenance. It may be
established only by explicit owner attestation or a future accepted authoritative
statement/import contract. Existing history is never automatically migrated to
`COMPLETE`. Corrections that change closed historical evidence must preserve the
existing explicit reopen semantics rather than silently mutating closed history.

Unknown coverage:

`not_computable_in_kind_boundary_coverage_unknown`

A known in-kind movement without an accepted event-date non-cash valuation
contract:

`not_computable_in_kind_movement_unvalued`

An in-kind movement between two historically in-scope accounts is conceptually
internal at portfolio scope, but until Hermes has accepted non-cash
transfer/valuation evidence sufficient to preserve valuation continuity, exact
portfolio performance across that known movement remains unavailable rather
than assuming continuity. Full non-cash flow support is deferred.

### H1-C — tax/fee treatment and performance basis

R08 performance is explicitly frozen as after-tax / after-internal-cost
performance. Taxes and commissions charged inside the selected investment
scope reduce performance and do not become owner capital withdrawals merely
because investment cash decreases.

Example: brokerage cash falls by 100,000 RUB while an owner withdrawal is
processed; 87,000 RUB reaches the owner and 13,000 RUB is withheld/remitted as
tax from inside the investment scope.

Canonical semantics:

- external withdrawal boundary amount = 87,000 RUB;
- internal tax cost = 13,000 RUB;
- no synthetic 100,000 RUB external withdrawal.

The separation is deterministic only when accepted source evidence establishes
the actual outside-scope amount and the tax/fee component. Evidence may be one
authoritative source contract with explicit gross/tax/net meaning or multiple
canonical events that deterministically reconcile to the same primary owner
transaction. Hermes must not infer boundary meaning from legacy field names.
If the actual boundary amount cannot be proven:

`not_computable_external_flows_incomplete`

A standalone tax charged from in-scope investment cash without a related owner
withdrawal remains an internal cost. It creates no `ExternalFlow` and does not
make external-flow coverage incomplete merely because no withdrawal exists.

### H1-D — direct realised coupon/dividend payout outside brokerage cash

If a realised coupon/dividend is paid directly from issuer/broker/source to the
owner outside the investment scope without first entering in-scope brokerage
cash:

- the coupon/dividend remains economic/passive-income explanation evidence;
- the separately proven actual payment crossing the investment boundary is
  represented using existing external-withdrawal semantics;
- the economic income event is not injected separately into XIRR/TWRR;
- no new external-flow kind is introduced.

The flow belongs to the canonical investment account that generated the
entitlement, established by accepted source/account/holding provenance, never by
guessing from a later snapshot. If the same instrument is held in multiple
accounts, each independently evidenced account payout is separate.

`event_date` is the actual payout/settlement date and reporting-month association
follows the month containing that event date. A matching debit from
`CashBalance` is not required when the cash never entered in-scope brokerage
cash.

Withholding outside scope is distinct from H1-C. Example: gross dividend
10,000 RUB, 1,300 withheld before payment, 8,700 paid directly to owner.

- external boundary amount = 8,700 RUB;
- 1,300 is not a separate internal brokerage-cash tax event;
- gross 10,000 may remain passive-income/explanation evidence;
- return math consumes the 8,700 external boundary flow and valuations without
  adding the gross dividend again.

Expected/provider calendar events are not proof of realised payment. Accepted
actual-cash evidence is required; otherwise the affected interval remains
`not_computable_external_flows_incomplete`.

A proven direct payout is sufficient boundary-flow evidence for the payment,
but it never substitutes for the observed pre/post valuation boundaries required
by exact TWRR. Internal tax/commission is not added a second time on top of a
valuation that already reflects that cost.

### H1-E — stable whole-portfolio scope membership

Gap-free effective-dated membership history is necessary but not sufficient for
exact whole-portfolio return. Current R08 can know that an account changed from
out-of-scope to in-scope (or the reverse) while opening and closing valuations
select different portfolio compositions. Without an accepted scope-transition
value, that composition change can be misreported as investment return.

Until a future accepted scope-transition valuation contract exists, exact
whole-portfolio XIRR/TWRR is available only when every historically relevant
account has one constant `include_in_returns` state for every date in the closed
requested interval `[start_date, end_date]`.

A transition strictly before `start_date` or strictly after `end_date` is
irrelevant. A transition whose effective date lies inside the requested closed
interval makes exact whole-portfolio performance unavailable. No synthetic
contribution/withdrawal is created from the entering/leaving account value.

New stable reason:

`not_computable_scope_membership_changed`

Explicit flow-level membership evidence must also agree with the effective-dated
history at that flow's `event_date`:

- `stable_in_scope` requires effective membership `true` on that date;
- `stable_out_of_scope` requires effective membership `false` on that date;
- `unknown` retains the existing non-authoritative fail-closed behavior.

A contradiction is scope-coverage failure and must not be silently resolved in
favour of either record. The existing `not_computable_scope_coverage_incomplete`
reason may represent this inconsistency; response metadata should identify the
affected account/flow evidence.

This restriction applies to whole-portfolio performance. Existing explicit
account-scope fail-closed membership rules remain authoritative.

### H1-F — explicit cash-boundary history coverage

The absence of known bad `ExternalFlow` or legacy deposit/withdrawal rows is not
proof that all owner cash crossings were captured. A missing contribution or
withdrawal can otherwise appear as investment return even when valuations are
perfectly observed.

Exact XIRR/TWRR therefore requires affirmative cash-boundary history coverage
for every account historically included in the selected performance scope over
the requested interval. In-kind coverage and cash-boundary coverage are
independent proofs; satisfying one never satisfies the other.

Minimum coverage states:

- `COMPLETE` — authoritative/owner-confirmed evidence establishes that all
  owner cash boundary crossings for the covered account/interval are known and
  represented under the accepted `ExternalFlow` contract, including the valid
  case of zero crossings;
- `UNKNOWN` — completeness cannot be established.

Coverage may be established by explicit owner attestation or a future accepted
authoritative statement/import contract. Existing historical intervals are not
automatically migrated to `COMPLETE` merely because no blocking rows exist or a
reporting month is closed.

`COMPLETE` is a completeness assertion, not a replacement for the flows
it covers: any known contribution/withdrawal still requires its canonical
`ExternalFlow` evidence and all ordinary amount/date/currency/transfer rules.
A direct payout covered by H1-D is part of cash-boundary history and must be
represented explicitly; expected/provider calendar evidence remains
insufficient.

When cash-boundary coverage is `UNKNOWN`, exact performance remains
`NOT_COMPUTABLE` using the existing stable reason:

`not_computable_external_flows_incomplete`

Coverage persistence must retain account/interval identity and provenance.
Corrections to evidence belonging to closed historical months must preserve
explicit reopen semantics; closing a month alone never attests cash-boundary
completeness.

## New stable reason codes from H1

- `not_computable_transfer_in_transit_unvalued`
- `not_computable_transfer_reconciliation_incomplete`
- `not_computable_in_kind_boundary_coverage_unknown`
- `not_computable_in_kind_movement_unvalued`
- `not_computable_scope_membership_changed`

Cash-boundary coverage intentionally reuses
`not_computable_external_flows_incomplete`. Existing R08 reasons remain
authoritative where applicable.

## Normative regression vectors

1. Async transfer 10 -> 15 Feb, requested closing valuation 12 Feb: portfolio
   XIRR and TWRR are `NOT_COMPUTABLE` due unvalued transit.
2. Same async transfer wholly inside a 1 -> 28 Feb interval, with no required
   TWRR valuation inside transit: portfolio XIRR/TWRR may remain available if
   all other prerequisites are complete.
3. External owner flow on 12 Feb during the 10 -> 15 Feb transit: XIRR is not
   blocked solely by the unsafe TWRR boundary; exact TWRR is blocked.
4. A transit interval spanning a required valuation is detected even when both
   transfer-leg dates themselves lie outside the requested metric interval.
5. Transfer 100,000 -> 99,900 with no accepted reconciliation: unavailable.
   With authoritative 100 RUB internal fee evidence linked to that transfer:
   may reconcile.
6. Brokerage/IIS interval with unknown in-kind coverage: exact performance is
   unavailable.
7. Known external transfer of shares without accepted event-date non-cash
   valuation: exact performance is unavailable.
8. Withdrawal processing debits 100,000 from scope, pays owner 87,000 and
   withholds 13,000 inside scope: external withdrawal 87,000 + internal tax
   cost 13,000.
9. Standalone in-scope tax with no owner withdrawal: no external flow.
10. Retained dividend: no external flow.
11. Dividend enters brokerage cash then owner withdraws it: separate internal
    income event + external withdrawal; no double counting.
12. Direct gross dividend 10,000 with 1,300 withheld outside scope and 8,700
    paid directly to owner: external withdrawal 8,700; no internal 1,300 tax
    event. Exact TWRR still requires its ordinary observed boundary evidence.
13. Portfolio A remains worth 100 while portfolio account B remains worth 50
    but B changes `include_in_returns=false -> true` inside the interval:
    whole-portfolio exact XIRR/TWRR are unavailable rather than reporting a
    synthetic +50% return.
14. `ExternalFlow.scope_membership=stable_in_scope` on a date where effective
    membership is false: scope coverage is inconsistent and exact performance
    is unavailable.
15. Opening valuation 100, closing valuation 200, no recorded flow rows and no
    affirmative cash-boundary coverage: exact performance is unavailable rather
    than inferring +100% return.
16. The same interval with explicit COMPLETE cash-boundary coverage and zero
    actual owner crossings may proceed if every other prerequisite is complete.

## New workstream sequence

1. `PERF-R0` — reconciliation and durable documentation (#315).
2. `PERF-H1` — accepted/finalized additive hardening contract (recorded here).
3. `PERF-H2a` — stable whole-portfolio membership gate.
4. `PERF-H2b` — explicit cash-boundary completeness coverage.
5. `PERF-H2c` — transfer-in-transit and reconciliation fail-closed implementation.
6. `PERF-H2d` — in-kind boundary coverage persistence/fail-closed implementation.
7. `PERF-H3` — tax/direct-payout regression and evidence hardening.
8. Owner-only performance readiness UAT on Preview/copy DB; implementation
   agents receive only sanitized outcomes.
9. Account-level XIRR using the accepted availability foundation and existing
   solver semantics.
10. Account-level exact TWRR using the accepted observed-boundary foundation.
11. `PERF-04A` — attribution contract, then bounded attribution slices.

The long-history synthetic performance benchmark may run in parallel if it
changes no financial semantics.

## Deferred until owner need / separate contract

- supported valuation semantics for portfolio-scope membership transitions;
- full non-cash `ExternalAssetFlow` model;
- historical FX provider/conversion expansion;
- margin/negative-cash performance semantics;
- approximate/Modified-Dietz return;
- transaction/cost-basis realised-vs-unrealised attribution.

## Workstream rules

- `main` is the only canonical source of truth and release source;
- `integration/performance-v1` is staging only;
- every implementation task uses its own child branch/workspace;
- financial semantics and migrations require independent senior/integrator
  review regardless of builder model;
- production/Preview/private runtime data is forbidden to implementation agents;
- scope expansion requires STOP + explicit re-scope.
