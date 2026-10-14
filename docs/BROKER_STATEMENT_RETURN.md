# Broker statement period return (S3)

Accepted assignment: #774 and Integrator GO 6132724218; #768 amendment
6106797516. This is a separate read-only account result. It creates no financial
projection, previous ReportingMonth, rate record, attestation or provider request.

## Frozen interface

`BrokerStatementReturn` uses `method=broker_statement_mwr_period_v1`, `scope=account`,
actual `account_id`, `t0`/`t1` EOD dates, `currency=RUB`, `annualized=false`,
`status=quality=indicative|unavailable`, and `rate_fraction` as a Decimal string or
null. Fraction `0.0201` means **2.01% over the actual period**. Money in the JSON
DTO is a signed integer kopeck **string**, preserving values beyond JavaScript's
safe integer range. Unknown money stays null.

Both endpoints disclose each native position's ISIN, instrument identity,
actual quantity, native value and source ordinal, the position sum, **separate**
RUB cash and total. Source provenance includes original hash, parser identity,
source signature, source-month request and confirmation digest. The response
discloses effective crossing IDs, dates, signs, revisions and material signatures,
cash coverage state/revision, membership, exposure, NKD basis and reason codes.
The material fingerprint binds current source, receipt, dependencies and evidence.

#815 diagnostic CODE GO [6166582304](https://github.com/LTstripes/hermes-finance/issues/815#issuecomment-6166582304)
adds immutable `section_authority` entries for the selected and intersecting
account sources, separately for Transfers and UFSR. Each entry binds import,
account and reporting month; reports `effective|missing|blocked`, current head
request ID and proof material signature when a head exists. A safe `pattern` is
disclosed only after the existing #800 chain and current dependency resolver
validate the exact proof. Raw inventory and safe original XML alone leave the
grant missing; stale, malformed or conflicting authority remains blocked without
falling back to an older receipt. Superseded history does not override a valid
fresh head. Head IDs, proof material, blocked/conflicting histories and relevant
source changes participate in the S3 fingerprint even while reasons and rate
remain unchanged. GET, original Preview and JSON attachment export share this DTO.

These are three separate evidence layers: original-safe XML structure, accepted
source-scoped metadata grant, and independently accepted economic-period coverage.
Section entries always retain `period_scope=unknown`. They do not assess material
exposure, dated crossings or continuous historical performance membership.
`cash_coverage_state` remains owned by the H2-A2 reader. The #816
[accepted compatibility contract](https://github.com/LTstripes/hermes-finance/issues/816#issuecomment-6168054932)
introduces `h2-a2-source-cash-rub-v2`: each intersecting source records raw and
effective syntax blockers, absent/current section heads, full scoped receipt
chains and current base/grammar/mapping/dependency bindings before blocker union.
Only current exact-month #800 authority removes its own named Transfers/UFSR
exception. It adds no coverage dates and does not override frozen H2-A1 blockers.
An independently complete quiet interval still needs continuous membership,
resolved Money/exposure, all four reviewed claims and explicit zero crossings.
New accepts and explicitly reviewed same-identity reaffirmations bind v2 context;
v1 reads/replays retain their original evidence and never inherit section grants.
Relevant source/section/base/dependency changes append retirement and UNKNOWN in
the same transaction, including CLOSED and receipts from later lifecycle hooks.
ABA and replay cannot revive retirement. Coherent GET rechecks without writes;
positive edits/reaffirm/revoke still require explicit Reopen when CLOSED.
`material_account_exposure_unassessed`, overlapping-source and all other retained
null reasons remain in force. Cash compatibility alone grants no numerical return.

Routes (all read-only, including POST preview):

- `GET /api/broker-statement-returns/sources?account_id=...` lists accepted source
  receipts for selection. Listing is discovery, not rate authority.
- `GET /api/broker-statement-returns?account_id=...&request_id=...` rebuilds evidence
  in one coherent committed read snapshot.
- `POST /api/broker-statement-returns/preview` accepts original XML plus
  `account_id`/`request_id` form fields. The existing accepted source is required;
  parser facts must match its unchanged original, allowing only established S1
  service enrichment. No client-supplied amount, rate or evidence override.
- `GET /api/broker-statement-returns/export` returns the same DTO as JSON.
  Optional `expected_fingerprint` on GET/export requires the viewed evidence;
  changed evidence returns a fresh unavailable DTO with `statement_preview_stale`.

Desktop route `/v2/capital/statement-return` is linked from the performance page.
Account/source query identities and response identities must agree. Switching
account clears the selected source; pending/failed refresh hides the old result
and export. The export link pins the displayed fingerprint. It cannot export an
old percentage after the source or coverage changes.

## Inputs and availability

The valuation adapter reads the unchanged original-bound S1 document linked to
the existing BrokerMonthApply source receipt. `t0=covered_from-1 day` follows the
accepted `previous_day_eod` legend; `t1=covered_to` follows `covered_to_eod`.
Both source endpoints are used together; no monthly/historical valuation fallback.
Source hash/parser/range, account aliases, instrument types/currency, source-owned
projection, current dependencies, endpoint completeness, cash/quantity controls
and competing overlapping reports are rechecked. Untrusted changed source values
are not exposed as accepted facts.

Crossings come only from effective existing HistoricalOwnerFlow revisions, with
independently accepted, currently effective source CashBoundaryCoverage for the
exact `(t0,t1]` interval. The coverage reader rechecks its whole source inventory,
enumerated flow IDs, membership and revision binding. An empty ExternalFlow table,
an incomplete DRAFT or `include_in_returns=false` proves no zero-crossing schedule.
Positive crossings enter this **account**; portfolio externality is not inferred.
No new H2 acceptance or source classification is performed here.

The existing H2-A2 contract currently rejects some legacy cash, transfers,
net-only payouts and unresolved Money inventories. This adapter preserves those
unavailable results; it does not invent a compatible broader coverage contract.
It also blocks competing sources and unassessed REPO/pending/Transfers/UFSR
exposure, including diagnostic-only wrapper evidence. Structural disposition
does not establish absence of financial impact.

Known source valuation facts remain visible when only flow/coverage/exposure
proof is missing. All availability reasons remain machine-readable. Bond NKD
UNKNOWN can permit **indicative** when every other gate passes, with the exact
warning **"По оценке брокера; учёт НКД в стоимости облигаций не подтверждён"**.
There is no invented zero NKD, tax, cost or error interval.

## Mathematics and isolation

Investor vector: `-V0@t0`, `-Ei@(t0,t1]`, `+V1@t1`. Coupon, dividends, posted
fees, settlement and summaries already reflected in cash are not extra investor
flows. Only the existing Decimal/ACT365 `calculate_xirr` numerical kernel is
reused. Convert its internal annualized root to
`R=(1+r)^((t1-t0).days/365)-1` at Decimal precision 60. Ambiguity, no-root and
convergence failures remain null with reasons. Solver quality never grants exact
financial authority to this DTO.

Synthetic tests cover midpoint 2.01%, contribution/withdrawal 0%, internal net
coupon/fee 2.8%, negative return, independently compounded residual below 0.01
RUB and absolute fraction error at most 1e-8, root guards, missing coverage,
source/membership/date/projection changes, overlap, percent units, stale account
responses, preview/export parity and no database writes. Existing exact
XIRR/TWRR/class readers and guards are unchanged. Real September percentage and
Owner financial/UAT acceptance require their separately authorized evidence.
