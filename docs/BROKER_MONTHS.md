# Source-first MyBroker month (S2b supported slice)

The [durable source-intake journal](SOURCE_INTAKE.md) (#889 first slice) saves
recognized observations, opaque inventories, Owner RUB assumptions and grouped
decisions without relaxing this financial writer. Bound pending intake participates
in scoped readiness/Close/returns even before a financial receipt exists. A
verified journal-only finance link can satisfy supported obligations after the
existing strict Apply/GET; it neither posts money nor removes incomplete-source
blockers. Reload requires exact-original reattachment for review mutations.

Issue #773 adds original XML → zero-write whole-account Preview → reviewed atomic
DRAFT Apply → independent GET → existing global Close. The receipt joins existing
immutable S1, stage-only identities, canonical S2 trades and native finance rows;
it does not introduce another trade, cash or payout ledger.

The supported slice requires an existing exact-compatible RUB stock/bond catalogue,
one explicitly bound active broker/IIS account and the exact existing DRAFT month
with its final-day snapshot. New currency remains `instrument_currency_unproven`
under #777. Unsupported instruments cannot be skipped to make the account complete.
Position quantity and native total, beginning and ending values, separate RUB cash
and the full Money inventory remain distinct. Source cash is not incremented again
by settlement or payouts. Missing tax, cost and bond NKD stay null.
Affirmative zero holdings remain in source inventory without fabricated position
rows. Missing security inventory is unproven, not observed zero; fractional stock
quantities are explicit Preview conflicts. Balanced endpoints cannot clear an
unresolved canonical settlement principal, commission or cash ownership.

Accepted S1 trade settlement/commission patterns and canonical native trade keys
retain their authority. The #782 extension under accepted #781 adds only explicitly
reviewed actual net coupons and account funding to an existing source-owned DRAFT.
Coupons use InvestmentCashFlow; funding uses H2 v2 HistoricalOwnerFlow. Neither
creates ExternalFlow nor adds source cash again. Accepted #783 additionally handles
an individually proved settled RUB **bond BUY** with negative posted paid NKD and
a separately charged nonzero native-linked fee through the existing
ExecutedTradeRevision. No duplicate endpoint cash or inferred EOD NKD/cost arises.
Accepted #790 adds a separate, typed **settled RUB stock BUY** proof
(`stock_buy_separate_fee_v1`) using exact native settlement S and separately
charged fee F, individually reviewed fee-excluded `summ_trade=T`, `bank_tax=B`,
and the existing ExecutedTradeRevision. It adds no paid NKD leg, extra cash,
payout or ledger. A source evidence reference is required; an entered reference
or matching equation alone is not independent brokerage fee-basis proof.
Unknown dividends, opaque Money and unsupported source sections remain
visible scoped exceptions. An incomplete DRAFT is allowed; unresolved
evidence blocks its covered account at Close.

The [incomplete DRAFT identity separation](MYBROKER_IDENTITY.md#incomplete-draft-structural-separation)
allows only server-validated Positions/Money structural side branches to remain
bookkeeping exceptions rather than identity conflicts. Preview and reserved
Apply use the same versioned original-bound classification. It never deletes
`unparsed_source_rows` from S1 or GET/Close, accepts a hidden identity row, creates
tax/NKD/fee economics or changes exact/indicative return readiness. A successful
partial Apply is not financial completeness or permission to Close.

The Money Preview requires original bytes for the complete accepted overlapping
source union. Original observations guide specific instrument/payment/boundary
review; they do not mint payment identity from date, amount or narrative. The server
assigns coupon identity and retains permanent occurrence-to-target ownership,
including old H2/S2 owners and revoked evidence. Indistinguishable repetitions and
missing events in a covering report block acceptance. A typed PDF can explicitly
link the same ICF; it cannot invent missing gross, tax or commission components.

Money Apply reserves the writer, revalidates all dependencies and stages ICF, H2,
ownership links and proof in one transaction, followed by independent GET. Versioned
Money proof and monotonic retirement/dependency tokens use the existing append-only
BrokerMonthApply journal; legacy receipt JSON and S1 are unchanged. A → B → A cannot
revive stale review. Retired proof requires reviewed reaffirmation of the same core
targets. Replay returns current disputed/readiness state without adding money.
Journal revision order is assigned under the writer reservation, independently of
wall-clock timestamps. A compatible staged coupon addition preserves unchanged
earlier payouts. Legacy PDF technical tax zero is displayed as unknown when its
accepted provenance marks tax unavailable; stored legacy facts are not rewritten.
Claim-free coupon reuse is limited to the already proven complete occurrence set.
A distinguishable second coupon cannot be linked to that payout even with matching
amount/date and supplied claims. Money funding requires H2 v2; legacy v1 authority
needs explicit version-bound reaffirmation, retaining its original receipts.
Independent GET retains batch targets and also returns all current targets for the
source-owned account/month, so the desktop panel preserves earlier acceptances.
Compatible additive typed PDF LINK_EXISTING keeps the original Money authority:
the ICF facts and existing PDF support must remain identical, and each added
attachment must contain one matching initial link revision for that exact target.
Later PDF revisions, retractions or contradictions retain monotonic retirement.
Lifecycle retirement follows the affected target and reporting period (including
old scope when a row moves), so cash/payout/PDF changes in another month of the
same account do not retire independent accepted Money.

Preview confirmation binds original bytes, selected account/month, identity/source
revisions, financial dependencies and supplied optional-document hashes. Apply
reserves the writer, revalidates and stages all changes in one transaction. Any
failure rolls back identity/source/trade/position/cash/receipt writes. Same-intent
request replay returns the original receipt with zero new economic rows, including
after Close; it cannot mutate CLOSED. Overlaps reuse canonical trade identity.
Manual or conflicting facts require explicit reconciliation rather than overwrite.

GET reads the accepted immutable S1 source and current authority/projection under
one snapshot. Readiness and reserved server Close share the same source checks:
all positions and cash must still match, mappings/source authority must remain
valid, intersecting evidence must have no material unresolved conflicts. Hard
guards apply only to accounts explicitly covered by source-owned receipts.
Supplied optional evidence remains attached to its receipt. Source/control and
authority failures are recomputed rather than frozen: successful compatible
canonical enrichment clears its temporary projection blocker. Preview and GET
also retain every applicable receipt's unresolved evidence at account level.
Unrelated active accounts retain `active_account_snapshot_missing` warnings;
ordinary months keep existing behavior. Account readiness does not attest whole
portfolio coverage: `coverage_state=unknown`, exact XIRR/TWRR remain unavailable.

Optional documents are absent by default. Supplied documents without an accepted
typed reader are hashed and disclosed as `optional_evidence_unsupported`, blocking
Close rather than producing guessed corroboration. Dedicated optional adapters
remain deferred. The desktop route currently accepts the original XML only.

Migration 0057 adds an empty append-only ownership receipt table with source/month/
account foreign keys. It neither backfills financial data nor reparses legacy S1.
Downgrade refuses populated source-owned receipts to prevent lost ownership.
Migration 0058 adds only permanent Money occurrence links with ICF/H2 target and
receipt foreign keys; it performs no financial backfill and refuses downgrade when
links are populated. The desktop extension accepts the required original XML set.

Synthetic backend regressions cover exact values/missingness, replay, both overlap
orders, distinct native IDs, stale review, full rollback, conflicts and reserved
Close concurrency. Desktop tests verify explicit review, failed/mismatched GET,
CLOSED reading and real API Preview → Apply → GET → global Close at desktop widths,
including the incomplete Money path. Synthetic evidence is not Owner acceptance.

## Real September Owner-local UAT — 2026-10-12, bounded DRAFT PASS

The preceding 11 October Gate 0 below is **historical, superseded only for incomplete-DRAFT UAT**. After [#804 / PR #805](https://github.com/LTstripes/hermes-finance/pull/805) the server validates original-bound Positions/Money structural exceptions separately from identity conflicts. It retains frozen S1 source warnings and all financial Close guards. Code merged at `main@d4ff5ea1d1500117d4b57ba348c09fa5452330bc`, [exact post-main CI 38301062183 SUCCESS](https://github.com/LTstripes/hermes-finance/actions/runs/38301062183), technical #804 CLOSED.

The Owner authorized and the local operator reported a genuine isolated scratch run:

| UAT stage | Accepted evidence | Boundary |
| --- | --- | --- |
| Original → Preview | Unchanged complete original; fresh zero-write HTTP 200 Preview, `can_apply=true`, hard `conflicts=[]` | Source exceptions still visible; `bookkeeping_ready=false` |
| Reviewed incomplete DRAFT Apply | **One atomic Apply**; independent GET; 11/11 source position quantity checks and signed RUB cash residual all zero | One receipt, canonical trades, original-valued positions and one source cash state; no duplicate payouts/ExternalFlow |
| Replay and integrity | Same-intent replay `duplicate=true` without new rows; local SQLite integrity/FK and protected-isolation checks clean | No second financial Apply or historical/protected mutation |
| Capital participation | Scratch-only ordinary account PATCH `include_in_capital=true`, `include_in_returns=false`; source total = monthly summary GET | Account exposure in Capital is not performance membership/availability |
| Windows desktop | Operator opened real read-only local viewer, reloaded desktop, confirmed source values, DRAFT, expanded warnings and disabled Close | Integrator did not independently inspect private screenshot pixels |

[Owner-local delivery](https://github.com/LTstripes/hermes-finance/issues/773#issuecomment-6132341689), [Integrator bounded acceptance](https://github.com/LTstripes/hermes-finance/issues/773#issuecomment-6132409052), [stage-3 API](https://github.com/LTstripes/hermes-finance/issues/773#issuecomment-6132678182) and [final desktop PASS](https://github.com/LTstripes/hermes-finance/issues/773#issuecomment-6132814727) separate actual Owner-private evidence from Integrator's GitHub/code verification. The earlier URL-resolution failure was a **tooling blocker that was subsequently resolved**, not an application defect.

**Retained real-source warnings**: `4_Transfers_unsupported`, `5_UFSR_unsupported`, `commission_basis_unresolved`, `money_semantics_unsupported`, `settlement_principal_unresolved`, `unparsed_source_rows`. `coverage_state=unknown`; `bookkeeping_ready=false`, `can_close=false`; XIRR/TWRR null. **No Close/Reopen or separate financial Money/NKD/tax/fee attestations**. Source-native EOD bond valuations retain `bond_nkd_basis=unknown`: source amount known does not equal exact economic value.

**Historical product distinction at this UAT checkpoint**: DRAFT source panel worked and monthly summary could include the account when explicitly opted into capital. The standard `/v2/capital` surface read the latest **CLOSED**; the DRAFT Capital view and warning presentation were then follow-ups. Delivered #807/#808 now provide the read-only DRAFT Capital view and revised warning presentation. This pointer does not extend the dated UAT evidence. Desktop/laptop only.

**[#774](https://github.com/LTstripes/hermes-finance/issues/774) was future work at this checkpoint**; its delivered read-only **separate indicative period MWR** is described in [BROKER_STATEMENT_RETURN.md](BROKER_STATEMENT_RETURN.md), not exact XIRR/TWRR. Numeric September rate is **not** asserted until both broker-native EOD valuations, all dated account-boundary flows, coverage and material REPO/UFSR/custody exposure pass their *own* guards. No inferred `E=0`, no double coupon/cash. All private values/ISINs/paths/hashes/screenshots remain out of tracked docs. [#773](https://github.com/LTstripes/hermes-finance/issues/773) and [#768](https://github.com/LTstripes/hermes-finance/issues/768) stay **OPEN** for complete financial Close.

## Historical Owner-local Gate 0 — 2026-10-11 (pre-#804; superseded for incomplete DRAFT UAT)

This is a dated source-compatibility result, not another parser family or a
production UAT. [#787](https://github.com/LTstripes/hermes-finance/issues/787#issuecomment-6112959100)
reported a complete unmodified private MyBroker source with individually
compatible stock/bond identities, independently matching source/native cash and
quantity controls, and no scratch database or financial Apply. Original file
identifiers, source monetary amounts/hashes and machine targets are Owner-private.

Live `main@e512338b` still requires three distinct acceptance paths:

1. [#788](https://github.com/LTstripes/hermes-finance/issues/788):
   original native settlement/commission Money has the exact primary-ID text in
   `oper_type`, while accepted legacy S1 linkage reads `comment`.
   A safe versioned extension must preserve existing accepted S1 normalized
   rows, fingerprints and receipts. No guessing the second native trade ID.
   Draft PR #791 is **not accepted or merged** at this checkpoint.
2. [#789](https://github.com/LTstripes/hermes-finance/issues/789#issuecomment-6113268340)
   metadata contract: exact empty Transfers and UFSR connected-status-only trees
   may be classified as *no economic movement* only with strict complete
   namespace/attribute/child validation, preserving raw inventory. The
   corresponding bounded implementation is [#792](https://github.com/LTstripes/hermes-finance/issues/792)
   after #788. Populated daily Money `all_volume` and `debet_volume` have no
   proven independent per-date account/basis equation:
   [#793](https://github.com/LTstripes/hermes-finance/issues/793) is a separate
   read-only investigation. Control-only fields do not mint payments or daily
   valuations; even exact total cash arithmetic cannot clear this blocker.
3. [#790](https://github.com/LTstripes/hermes-finance/issues/790#issuecomment-6113269181):
   strictly proven two-leg settled RUB stock BUY separate fee is a future
   compatible **financial proof variant**, not a relaxation of #783 bond
   three-leg proof. A documented, independently reviewed fee-excluded native
   amount basis is required; equal numerical sums alone cannot provide it.
   New fee proof may reuse existing ExecutedTradeRevision and Money ownership,
   but never create an artificial `paid_nkd=0`, another cash ledger or
   a general exemption from commission blockers.

[#787](https://github.com/LTstripes/hermes-finance/issues/787) remains
**Gate 0 BLOCKED** even though private raw controls reconcile to zero residual.
Recheck the unchanged Owner original **read-only** only after integrated
compatible code and exact post-main CI. Creating an isolated scratch DB, DRAFT
Apply and eventual scratch Close each require separately explicit Owner GO.
Protected Test/Stable/CLOSED and actual historical data must remain untouched.
Bond reported EOD value can be retained as a **source-marked value** with
unknown accrued NKD; this does not authorize exact economic XIRR/TWRR.

## Historical technical checkpoint — 2026-10-12 (pre-#804/real UAT)

The preceding 2026-10-11 original Gate 0 account is a **historical dated result**.
Since then [#788 / PR #791](https://github.com/LTstripes/hermes-finance/pull/791)
corrected exact `oper_type` native Money linkage without upgrading prior S1 receipts;
[#792 / PR #795](https://github.com/LTstripes/hermes-finance/pull/795)
introduced original-byte-bound **diagnostic-only** safe Transfers/UFSR metadata
without removing S1 or Close blockers; and
[#790 / PR #796](https://github.com/LTstripes/hermes-finance/pull/796)
added the reviewed two-leg stock commission proof/desktop route, preserving
legacy request hashes and financial ownership. The #790 code merge is
`fee94e4fd4c77db3e50500a6fc3b6d103af2b498`; verify its exact
[post-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/38212066232)
— verified SUCCESS (attempt 1, all applicable jobs). The financial
implementation is CODE COMPLETE, not real September UAT.

The actual private September Gate 0 remains **BLOCKED** even though
[#787](https://github.com/LTstripes/hermes-finance/issues/787) is CLOSED as a
GitHub issue. Broker-authored daily `all_volume`/`debet_volume` definitions
[#793](https://github.com/LTstripes/hermes-finance/issues/793), independent
real-stock fee-excluded source basis (#790), and separately accepted
section-control/Close dispositions remain unproved. No actual Owner scratch,
DRAFT financial Apply or Close is authorized here. No Test/Stable/CLOSED
mutation or exact XIRR/TWRR claim follows from these code merges.

## Original-bound section disposition (#799 / #800)

The accepted [#799 Integrator amendments](https://github.com/LTstripes/hermes-finance/issues/799#issuecomment-6120415679)
add the separately versioned `mybroker-section-disposition-v1` variant in the
existing append-only BrokerMonthApply journal. It accepts metadata only, for one
existing source-owned DRAFT receipt and exact import/account/month. No schema,
source, mapping, financial row or frozen S1/receipt JSON is changed.

Use the existing multipart `/api/broker-months/preview` and `/apply` with one exact
original XML. Intent names `contract_version`, `base_request_id`, `import_id`,
`account_id`, `reporting_month_id` and `sections`, each containing `section`
(`4_Transfers` or `5_UFSR`) and `expected_predecessor` (null for first acceptance).
Apply also requires `request_id` and the server's `confirmation_digest`.
Supporting files, client source hashes and safety assertions are not accepted.

Both stages reread the original with the recorded S1/native-Money grammar,
compare parser facts allowing established service enrichment, validate filename,
range, account aliases and mapping identities, and independently rerun the strict
#792 classifier. The receipt binds the original SHA, filename digest, source and
base-receipt digests, exact section locator/shape, inventory 1/3, zero derived
movements and unknown period scope. Connection dates are never retained as events.
Apply rereads dependencies and heads under the existing reserved writer; failure
rolls back the whole acceptance. Preview writes nothing.

GET `/{request_id}` shows each metadata section as `effective`, `superseded` or
`blocked` without originals. Source-month GET also includes `section_dispositions`;
the month list retains its source-month rows. The shared source resolver removes
only that source's proved named section code before blocker union in Preview,
GET and reserved Close. Unsafe or unproved overlapping sources retain their own
blockers. Frozen exceptions have no understood exclusive section provenance in
the legacy contract, so their contribution remains blocked; no backfill occurs.
All other Money, footer/Positions, REPO, unparsed rows, fee and NKD guards remain.

One chain per import/account/month/section follows explicit predecessor links,
independent of timestamps. Forks, missing predecessors and malformed/unknown
journal variants fail closed. The existing monotonic source/mapping journal and
dependency receipts retain ABA invalidation, including snapshot geometry edits.
An invalid head grants nothing; it never revives an older proof. Explicit fresh
acceptance referencing that head can restore newly validated authority; stale
history does not permanently poison account readiness. Exact replay is read-only
and returns current state, even on CLOSED. Fresh acceptance on CLOSED is refused;
normal Close status changes do not invalidate structural proof.

This code authority does not accept real September Gate 0, Positions/footer
grammar (#798), daily Money definitions (#793), actual stock fee basis or actual
Money ownership. Owner/private Apply/Close, Test/Stable/CLOSED mutations and exact
return authority remain outside this synthetic implementation.
