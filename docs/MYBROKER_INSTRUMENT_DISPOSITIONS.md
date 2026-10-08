# MyBroker archived-instrument disposition — contract proposal

Assignment: [#738](https://github.com/LTstripes/hermes-finance/issues/738).
Baseline: `main@7de6031fe8a24dad60cd1647e5768bb7f9ec255a`.
Status: proposed; independent financial/data review and authoritative contract
acceptance are required before implementation. This document grants no financial
authority and changes no existing accepted record.

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

The accepted S1 contract deliberately does not store raw XML, names, arbitrary
comments, filenames or private paths. Whether #738 requires new byte-for-byte
durable XML storage is an unresolved Owner decision. Such retention would amend
S1 and requires a separately accepted storage/privacy/recovery contract; it must
not be introduced implicitly by this proposal. Legacy records cannot acquire
missing bytes retrospectively.

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
The decision to defer these corrections requires Integrator acceptance; the
Worker cannot claim that a refused correction implements an accepted correction.

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

## 5. Date/scope proof boundary

First restrict by immutable accepted account aliases and the caller's explicit
historical account universe. Demonstrably unrelated accounts do not acquire new
blockers. Unknown/ambiguous membership remains blocked by its existing guard.

For an included account, report overlap alone is insufficient to prove exclusion
irrelevant. Inspect both exact position boundaries, actual/forward quantities,
every execution occurrence, unresolved lifecycle, actual settlement/depo/commission
dates and linked Money across the whole source union. Pending and unresolved
position exposure persist beyond filename ranges. Opaque transfer/unsupported
evidence cannot be assigned an invented ISIN, timestamp, class or expiry.

A window may be called unrelated only when existing exact source evidence
independently proves that excluded evidence affects neither boundary nor any
flow in the interval. No catalogue absence, later clean report, zero default,
range non-overlap or Owner skip attestation supplies that proof. Otherwise keep
the explicit exclusion-impact blocker. The sufficient exact proof predicate and
its account/interval boundaries remain to be frozen by financial contract review.

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
  plus a positively proven unrelated account/window; unresolved future pending,
  custody/settlement/commission and opaque transfer exposure remain guarded.
- Revoke/reaffirm, dependency retirement and SQL A→B→A protection; CLOSED/Reopen
  behavior; empty migration, append-only guards, populated downgrade refusal and
  supported backup/recovery.
- Russian choice interaction, stale confirmation and independent readback mismatch.

All fixtures are fabricated. No Owner data or runtime access, Stable/Test changes,
release or merge is authorized. Implementation requires the accepted contract,
synthetic evidence, full relevant exact-candidate CI, independent financial/data
candidate review and Integrator acceptance. Owner-local UAT is a separate gate.
