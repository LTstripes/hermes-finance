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
exception. It adds no coverage dates; H2-A1 v1/v2 retain their frozen raw-S1 blockers.
An independently complete quiet interval still needs continuous membership,
resolved Money/exposure, all four reviewed claims and explicit zero crossings.
Section-aware v2 accepts and explicitly reviewed same-identity reaffirmations bind v2 context;
v1 reads/replays retain their original evidence and never inherit section grants.
Relevant source/section/base/dependency changes append retirement and UNKNOWN in
the same transaction, including CLOSED and receipts from later lifecycle hooks.
ABA and replay cannot revive retirement. Coherent GET rechecks without writes;
positive edits/reaffirm/revoke still require explicit Reopen when CLOSED.
`material_account_exposure_unassessed`, overlapping-source and all other retained
null reasons remain in force. Cash compatibility alone grants no numerical return.

The [#819 accepted implementation contract](https://github.com/LTstripes/hermes-finance/issues/819#issuecomment-6170897968)
introduces separate `h2-a1-owner-rub-v3` account crossing evidence. Each source in
the full discovered account/date cohort binds canonical #800 provenance before
blocker union: raw/effective codes, absent/present heads, exact original/month
geometry, full relevant journal and current source/base/mapping/dependency support.
Only its own current Transfers/UFSR authority removes those named codes. Another
unsafe or ambiguous source still blocks; section authority supplies neither an
economic zero nor Owner externality. Exact signed RUB cash, complete occurrence
claims and permanent H2/Money ownership remain required. No month or financial
cash is created by Preview/GET or metadata acceptance.

V1/v2 serialized identities, builders, evidence, signatures and replay retain
their original contracts. Cross-version acceptance requires reviewed same-core
`reaffirm` with expected revision and freshly bound claims. Accepted v3 support
is compared after every sanctioned flush, including receipts from late listeners;
dependency loss appends retirement in the same transaction, then retires dependent
A2 evidence. CLOSED calendar overlap and ordinary Close alone do not retire A1;
dependency-loss retirement does not reopen or change CLOSED financial facts.
ABA, section reacceptance and old request replay cannot restore A1/A2 authority.
Retired v3 needs explicit reviewed A1 reaffirmation, followed by separate A2 review.
Source-aware/noncomplete A2 coverage is excluded from intrinsic v3 dependencies,
preserving the directed S1/section → A1 → A2 relationship and legacy COMPLETE conflicts.

Existing BrokerMoney account_funding creation/reuse/proof and only the A2 v2
account reader accept exact independently effective A1 v2/v3, binding the actual
version/revision/signature. Money's default remains v2; A2 v1 and shared assessor
ledger/portfolio dispatch are unchanged. Money reserves an authority-free typed
envelope during its atomic staging, then seals the final receipt; transient staging
must not look like a malformed #800 journal. Reuse, corroboration and replay add no
second economic amount, CashBalance, ExternalFlow or InvestmentCashFlow. No new
coupon/NKD/trade exemption, portfolio authority or numerical return follows.

The [#820 coupon contract and CODE GO](https://github.com/LTstripes/hermes-finance/issues/820#issuecomment-6172319178)
adds `h2-a2-source-cash-rub-v3`. This remains the frozen coupon-only version.
V1/v2 retain their literal evidence, signatures, readback and replay;
v3 continues to accept independently effective A1 v2/v3 revisions.
Only a current target-specific BrokerMoney proof can classify a permanently
owned exact Money occurrence as `accepted_non_owner_coupon`. V3 binds the full
target occurrence/owner cohort, relevant Money journal, canonical existing ICF,
account/month/instrument/source facts and optional typed PDF event/revision
support. No PDF is invented for net-native payouts; unavailable tax stays null.
The same exhaustive authority partitions only those existing effective coupon
ICF IDs out of legacy overlap. Every other ICF, ExternalFlow, unresolved Money,
NKD, membership, source gap and retained exposure blocker remains effective.
Coupon cash creates no second payout, cash row or Owner/investor external flow.

Receipt, ownership, target and typed PDF changes retire accepted v3 in the
dependency transaction, including CLOSED and late listeners. Presence and
absence participate in review binding. Restoring facts, replaying an old request
or independently reaffirming Money does not revive H2-A2; fresh reviewed coverage
reaffirmation is required. Reads only assess current authority and never repair it.

Under [#849](https://github.com/LTstripes/hermes-finance/issues/849), an otherwise
validated exact source/account/interval with no coverage row also reads the
existing H2-A2 inventory under the current accepted contract, in that
same coherent snapshot. Its stable blockers join `reason_codes`; the full relevant
dependency material and contract version participate in the opaque fingerprint.
Raw diagnostic rows/identifiers are not added to the response or logs. Source,
binding or currentness failures prevent this diagnostic lookup; no guessed scope
is used. GET, original Preview, desktop reasons and JSON export retain parity.
Even a valid inventory with no blockers is not accepted coverage: the generic
`account_crossing_coverage_unproved` and null rate remain. Existing coverage-row
branches retain their established versioned readers and availability. Accepted
paid-NKD has no disposition in v1-v3; the diagnostic itself grants no authority.

The [#870 accepted v4 contract](https://github.com/LTstripes/hermes-finance/issues/870#issuecomment-6237129361)
adds `h2-a2-source-cash-rub-v4` for new accepts and explicit reviewed reaffirmations.
V1/v2/v3 retain their literal evidence, readbacks and receipt replay, including v3
coupon currentness and unresolved paid NKD. V4 preserves A1 v2/v3 compatibility.

`source_cash_trade_money` is a query-only adapter from permanent trade ownership
and the latest target-specific Money receipt to the frozen trade revision and
full current canonical source union. Only a unique exact original Money
occurrence in the reviewed `nkd_leg` may become `accepted_non_owner_paid_nkd`.
The complete three-leg owner/receipt cohort, ordered native ID pair, current
active settled RUB bond BUY revision, account/mapping/month/settlement/custody
support and all independent claims must agree. Exact signed kopecks validate
an already proved includes/excludes basis; arithmetic never selects that basis.
Overlapping originals, duplicate roles/rows, missing owners, stale/retracted
proofs and unknown operations remain unresolved. There is no cross-original
paid-NKD deduplication or new authority from date/amount/ISIN matching.

V4 freezes relevant target/history, journal, source, owner and absence sets in
`paid_nkd_authority`. Trade revision/occurrence and Money dependencies participate
in the full post-flush comparison, including receipts appended by later listeners.
Dependency loss appends retirement in the same transaction even in CLOSED;
rollback restores both dependency and retirement. Close alone changes no proof.
ABA, replay, reopening and independent Money reaffirmation cannot revive A2:
fresh claims, expected revision and separate A2 reaffirmation are required.
GET/Preview/export only read currentness and never repair persisted authority.

Synthetic acceptance uses the original reviewed Money fixture: S -10,000.00,
N -125.50, F -10.00, debit 10,135.50 RUB; opening cash 10,000.00, coupons
+3,000.00 and Owner funding +50,000.00 yield EOD 52,864.50 and zero residual.
Six occurrences partition into two coupons, one Owner funding, two trade cash
legs and one paid-NKD non-Owner occurrence. Economic row counts remain
CashBalance/ICF/HistoricalOwnerFlow/ExternalFlow/ExecutedTrade = 1/2/1/0/1.
The adapter adds zero economic rows or amounts. It grants neither automatic
A2 COMPLETE nor S3 numeric; all independent coverage, membership, endpoint and
exposure gates still apply. Paid NKD is not a coupon, Owner contribution or
bond EOD accrued NKD. Real September source authority (0/5 independently proved
links under #814), actual S3/Close and exact-return/export authority remain BLOCKED.

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

H2-A2 still rejects unrelated legacy cash, transfers, unproved payouts and
unresolved Money inventories. This adapter preserves those
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
