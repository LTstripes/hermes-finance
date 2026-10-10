# MyBroker archived-instrument disposition — accepted bounded v1 contract

Assignment: [#738](https://github.com/LTstripes/hermes-finance/issues/738).
Baseline: `main@7de6031fe8a24dad60cd1647e5768bb7f9ec255a`.
Status: ACCEPT AS AMENDED by [Integrator comment 6058010476](https://github.com/LTstripes/hermes-finance/issues/738#issuecomment-6058010476).
This freezes the implementation contract, not implementation acceptance, CI, UAT
or merge. It grants no financial authority and changes no existing accepted record.

Governing source contract: [S1](MYBROKER_S1.md), especially the accepted
[#708 contract](https://github.com/LTstripes/hermes-finance/issues/708#issuecomment-5999540552)
and [#716 endpoint extension](https://github.com/LTstripes/hermes-finance/issues/716#issuecomment-6021176561).
Consumers retain [S2-A](MYBROKER_S2_A.md), [H0](HISTORICAL_RECONSTRUCTION_H0.md),
[H1-A](HISTORICAL_ENDPOINTS_H1_A.md), and [H2-B1](HISTORICAL_PORTFOLIO_FLOWS_H2_B1.md)
authority boundaries. H2-A1 owner-flow and H2-A2 cash-coverage evidence remain
independent; H3 consumes only effective H1/H2 authority.

## 1. Source preservation decision

The upload is reparsed in full. No XML filtering, synthetic report generation,
ISIN replacement, normalized-row deletion, or suppression of unsupported
observations is permitted. The original whole-file SHA-256, parser identity,
normalized document, source occurrence ordinals, native trade identities,
monetary observations and provenance remain unchanged by a skip.

Keep accepted S1 retention: persist only the whole-file hash, parser identity,
full normalized source facts/ordinals and disposition provenance. Never add
raw XML storage, an archive, source names/paths/private comments or XML backups.
The original bytes remain intact for Preview and authoritative Apply reparse;
source preservation means evidence fidelity, not bytes stored in the database.
Previously accepted S1 v2 records remain unchanged.

## 2. Smallest identity and acceptance scope

- The durable disposition key is provider + immutable source import/document hash
  + exact source ISIN. It covers every occurrence of that ISIN in that document,
  including all explicitly bound source accounts. Preview discloses those accounts,
  every affected position/trade reference and linked Money evidence.
- The Owner chooses `map` or `skip` for each exact ISIN. `map` uses the existing
  compatible effective registry binding. `skip` creates neither an Instrument nor
  a BrokerIdentityMapping and supplies no Hermes instrument ID or historical class.
- Accounts always require their existing explicit mappings. Undecided instruments,
  contradictory/ambiguous mappings and source integrity/reconciliation conflicts
  still block source Apply. Skip cannot override any source-level conflict.
- A skip is never inferred from catalogue absence, current holdings, zero values,
  instrument names, tickers, account suffixes or another report. Each new document
  requires explicit review, including an overlapping report of the same ISIN.
- An already accepted S1 document with no disposition extension keeps exactly its
  accepted v2 semantics. Adding a skip retrospectively is refused. Original
  `mappings_json`, `normalized_json`, parser constants and hashes are not rewritten.

## 3. Append-only lifecycle and atomicity

An additive, empty migration supplies a disposition revision ledger and Apply
receipts, separate from `mybroker_imports`. A revision freezes the key, reviewed
source-set fingerprint, exact account bindings, affected occurrence fingerprints,
contract version, typed Owner confirmation, expected predecessor revision,
confirmation digest and acceptance time. Append-only SQL guards and populated
downgrade refusal protect the ledger. Supported whole-file backup/recovery must
preserve it without special private artifacts.

Initial source acceptance and all initial skips commit together under the existing
SQLite writer reservation. Preview and Apply bind the entire unfiltered source,
mapped bindings, explicit decisions, relevant registry/lifecycle/financial state
and revision set. Stale, changed, contradictory or partially invalid decisions
roll back the entire Apply. No financial writes occur.

Same bytes, range, account bindings and accepted decision set replay as a source
no-op. A request receipt preserves the original committed revision identity;
independent GET also reports current disposition state. A reused request key with
different intent/digest conflicts. A changed skip choice on source reimport is
not a correction API and is refused.

Explicit revision-bound `revoke` withdraws the reviewed skip, retaining its
permanent affected occurrences as unresolved excluded evidence. It does not map
the ISIN, permit S2 promotion, remove blockers or restore completeness.
`reaffirm` can restore the same exclusion after review of fresh dependencies; it
cannot rewrite the source, accepted mappings or financial facts. Dependency loss
retires authority and must not silently revive after an A→B→A change.

Changing a skipped source instrument into mapped economic authority, changing an
accepted mapped instrument into skipped evidence, or replacing source economics
requires a separately reviewed correction/reconciliation contract. Those requests
fail closed in this slice, preserving existing C5 and CLOSED/Reopen guards.
Integrator accepts this bounded deferral. Every attempted skip↔map correction,
including retrospective plain-S1 skips and mixed cross-report economic support,
is explicitly refused as reconciliation required; revoke/reaffirm cannot bypass it.

## 4. Projection and evidence rules

All readers use one authoritative disposition resolver. Missing/invalid extension
state on a document accepted with skips fails closed. Resolver output separates
the immutable accepted disposition from current effective state and includes
permanent occurrence references and revision dependencies.

Skipped, retired and revoked occurrences cannot create canonical executions,
cash flows, snapshots, prices, valuations, cost basis or return-class assignments.
Their source trades remain in the evidence union for identity conflicts, pending
lifecycle, cash linkage and cutoff exposure. A mapped occurrence of the same
economic identity in another report must not silently promote an excluded trade;
mixed disposition/support requires reconciliation. No duplicate economic event
or cash leg can arise from repetition or overlap.

Source Apply success is separate from financial eligibility. An affected account
cannot become complete by totaling only mapped rows. Attestations cannot override
excluded inventory, linked money or possible cash/in-kind crossings. Historical
class remains unknown; all potentially affected classes in the historically
included account remain guarded.

| Reader/gate | Required treatment |
| --- | --- |
| S1 Preview, GET, lineage | Full unchanged document, mapped/skipped/unsupported counts, exact ISIN choices and revision state; coverage remains unknown. |
| S2 canonical trade acceptance | Disclose excluded occurrences; refuse promotion and mixed mapped/skipped support; keep economic identity and money ambiguity checks. |
| H0 inventory | Structural exclusion impact and revision fingerprints; preserve endpoint/event observations and no private values in reduced output. |
| H1 endpoint accept/reaffirm/GET | Excluded positions do not become endpoint components; potentially affected excluded inventory/trades remain blockers. No smaller complete account total. |
| H2-A1 / H2-B1 | Preserve money and full counterparty evidence; exclusion cannot supply outside-boundary, transfer or non-owner-flow semantics. |
| H2-A2 cash coverage | Excluded trade cash cannot automatically become accepted non-owner trade cash; possible crossing/opaque source evidence blocks completeness. |
| Class no-crossing / cash / in-kind coverage | Relevant exclusions block new claims and invalidate relevant existing reads; source Apply preserves pre-existing reconciliation guards. |
| H3 account/portfolio XIRR, class XIRR/TWRR, monthly materialization | Consult current exclusion impact in every availability path, including legacy fallback. Relevant exclusion gives explicit partial/NOT_COMPUTABLE; no solver input from skipped rows. |

Every affected acceptance fingerprint and lifecycle dependency must include the
disposition revision set. Both sanctioned ORM writers and supported SQL change
tracking must prevent disappearance, A→B→A restoration or an old receipt from
reviving authority. Reads may invalidate authority without changing CLOSED facts;
protected dependency correction still requires the existing explicit Reopen.

## 5. Frozen scope-only irrelevance proof

The only positive irrelevant case in v1 is disjoint historical account scope:
using effective immutable source account bindings and exact dated membership/
universe evidence, no affected mapped source account belongs to the requested
account/class/portfolio scope. Current account flags do not supply dated proof.
Portfolio/cross-account queries also require their independent tracked-transfer,
in-kind and roster gates. Unrelated independently evidenced scopes stay unchanged.

For a scope containing an affected account, there is no positive same-account
date-window irrelevance claim. Skipped settled position/value/unknown carry-forward
can affect any cutoff. Report non-overlap, earliest observation, later quiet
reports, absent/zero rows, equal actual/forward, old completed trades, catalogue
state and Owner skip do not establish lifetime, disposal or complete absence.
Relevant historical source-dependent endpoint, cash/in-kind/class completeness,
XIRR/TWRR and legacy/fallback eligibility remain partial/UNKNOWN/NOT_COMPUTABLE
with a specific excluded-source-impact reason. No guessed exposure expiry.

Full trades/Money/unsupported observations continue participating in identity,
link ambiguity, pending lifecycle and settlement/custody checks. Skip-linked
settled Money stays unresolved in H2-A2 even with valid native identity or mapped
support in another report. Preserve source Apply reconciliation refusal for
pre-existing COMPLETE claims; never silently downgrade or overwrite CLOSED facts.
A future independently accepted proof contract may relax same-account windows;
it is not a prerequisite for reviewed source Apply.

## 6. UI and synthetic acceptance

Preview uses **Сопоставить** / **Пропустить (не учитывать)** and explains:
**Источник сохранён; для затронутой исторической доходности требуется полное подтверждение**.
Changing any choice retires confirmation; Apply requires a new reviewed Preview.
Success requires independent GET equality for the full normalized document,
accepted bindings, disposition revisions and counts. Accounts remain explicit.

Synthetic acceptance must cover:

- Mixed mapped/skipped/undecided instruments, independent filename/row account
  identities, REPO and unsupported observations; undecided/account/conflict
  refusal, mapped survival and no skipped catalogue or financial events.
- Byte/hash/parser/normalized-occurrence preservation through Preview→Apply→GET;
  existing fully mapped v2 and accepted legacy records behave unchanged.
- Exact same-hash replay, changed range/choice, stale remapping/revision, duplicate
  request keys, rollback/concurrent Apply and correction refusal.
- Overlapping repeated identities with consistent and mixed decisions; excluded
  Money remains identifiable and cannot establish complete coverage.
- Relevant H0/H1/H2/H3, legacy/class XIRR/TWRR and monthly eligibility refusal,
  plus a positively proven disjoint historical account scope; unresolved future pending,
  custody/settlement/commission and opaque transfer exposure remain guarded.
- Revoke/reaffirm, dependency retirement and SQL A→B→A protection; CLOSED/Reopen
  behavior; empty migration, append-only guards, populated downgrade refusal and
  supported backup/recovery.
- Russian choice interaction, stale confirmation and independent readback mismatch.

All fixtures are fabricated. No Owner data or runtime access, Stable/Test changes,
release or merge is authorized. Implementation requires the accepted contract,
synthetic evidence, full relevant exact-candidate CI, independent financial/data
candidate review and Integrator acceptance. Owner-local UAT is a separate gate.

## 7. Accepted bounded Skip-to-Map correction extension

[#752 amended contract](https://github.com/LTstripes/hermes-finance/issues/752#issuecomment-6090540978)
and its [READY recheck](https://github.com/LTstripes/hermes-finance/issues/752#issuecomment-6090672906)
define the separate correction route deferred above. This does not change original
source acceptance, reimport or revoke/reaffirm semantics.

The API is `POST /api/mybroker-import/corrections/preview`, then
`POST /api/mybroker-import/corrections/apply`, followed independently by
`GET /api/mybroker-import/corrections/{request_id}`. Submit the complete declared
`decisions` array and strict `owner_reviewed: true`. Each decision binds `import_id`,
`document_sha256`, `isin`, `original_revision_id`, `expected_revision`,
`expected_correction_revision` (zero initially), exact effective `mapping_id` and
`hermes_id`, and the positively reviewed `reviewed_instrument_type`. Apply adds a
request ID and the fresh Preview's `confirmation_digest`.

Catalogue/account/registry preparation is separate. Existing mapping-trigger
retirement must finish before constructing these pins. Only an intact original
accepted Skip with a current, traceable retired predecessor is eligible. Revoked,
accepted, invalid or missing/unhistoried predecessors refuse. Exact target ISIN,
observed mapping ISIN, instrument type and observed trade currency must agree;
funds receive no equity fallback. A batch has no fixed size. Every declared
decision must pass, and all account/ISIN exclusion support across overlapping
imports must be included. The API never drops a failed fund or silently selects
an 18/17 tranche: a smaller scope needs its own accepted scope/overlap review.

Migration 0055 creates only empty, append-only correction receipts, revisions and
a monotonic change journal. Original Skip/source sets, revisions, receipts and
JSON remain untouched. Writer reservation, complete dependency reread and digest
comparison precede all inserts. Any mismatch or insert failure rolls back the
whole batch. Populated receipt downgrade refuses. Source/registry/catalogue
changes conservatively retire correction authority for the entire reviewed source
union; SQL A-to-B-to-A cannot restore it. Returning to the old target needs fresh
Preview and a new correction revision. Existing SQL guards remain installed.

GET separates the immutable committed receipt/revision IDs from current effective
corrections and unresolved exclusions. Exact request/digest replay returns these
same committed IDs with fresh current state; it never reaccepts retired authority.
A changed request payload/digest conflicts. An identical newly reviewed batch is
a correction-revision no-op only while every current effect is valid.

S1 reads retain original mappings and Skip history while exposing effective
mappings separately. S2, H0/H1/H2 and Performance use the same effective resolver.
S2 separately accepts canonical trade support and deduplicates economic identities
and Money across files. Within-file duplicate Money refuses correction; ambiguous
primary linkage and reducer conflicts remain blockers. Corrected Money stays
bound to its exact originally accepted account mapping, revalidated against the
effective registry and trade account even for Money-only support documents. It stays
unresolved in H2 until current independent S2 acceptance exists. H1/H2 and S2
fingerprints retain correction generation IDs, so fresh correction cannot revive
an older financial acceptance. Correction removes only resolved exclusion impact;
endpoint, membership, C1, fee, funding, REPO, pending, XIRR and TWRR gates remain.
Affected CLOSED facts refuse until explicit Reopen; Apply never changes facts,
months, deposits, catalogue or mappings. Owner-local preparation/UAT and numeric
return acceptance remain separate from synthetic code verification.
