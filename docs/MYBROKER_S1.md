# MyBroker S1 normalization and import lineage

Authority: [#708 accepted contract](https://github.com/LTstripes/hermes-finance/issues/708#issuecomment-5999540552),
the accepted [#713 endpoint disposition](https://github.com/LTstripes/hermes-finance/issues/713#issuecomment-6020928890)
and the [#716 implementation plan](https://github.com/LTstripes/hermes-finance/issues/716#issuecomment-6021176561)
with its Owner-local [gate confirmation](https://github.com/LTstripes/hermes-finance/issues/716#issuecomment-6021302431).
Parser constants and hand-built synthetic fixtures record the sanitized Integrator
manifests; they do not claim public format stability. No Owner XML or report value
is used in implementation or tests.

Upload is available under **Data → Files**, independently of a reporting month.
The multipart API is `/api/mybroker-import/preview` and `/apply`; `/{import_id}`
provides committed readback and `/lineage` provides the reduced source history.

Preview returns the hash, strict filename interval, parser/provider identity,
section inventory, normalized rows, explicit mapping bindings, conflicts and
unresolved evidence. Filename account and row `acc_code` are distinct identities:
both require explicit `alfa_mybroker` registry mappings, with no suffix/name/Alfa
PRO heuristic. Instrument mappings use the manifest's ISIN identity. No current
instrument class becomes event-C1.

Apply confirms the complete document set. Its confirmation digest binds every
normalized row and both native trade IDs, range, mapping revisions and current
reconciliation facts. Apply reparses the upload and reserves the SQLite writer
before rechecking the entire set. A stale or conflicting set writes nothing.
The UI retires confirmation on any Apply attempt and shows success only after
an independent GET agrees with the reviewed document and mapping bindings.

`mybroker_imports` is an append-only source ledger. It stores hashes, confirmed
dates, normalized facts, mapping IDs and acceptance provenance, never XML,
filenames, security names, arbitrary comments or paths. Migration 0048 adds only
this empty table; downgrade refuses to discard populated lineage. No economic
facts or historical months are created, overwritten or backfilled.

Economic identity is provider + source `acc_code` + both native trade IDs;
document/section/ordinal identifies an occurrence. Identical settled material
adds occurrences without another trade. Pending advances to settled only with
unchanged economic core and a later source endpoint, independent of upload order.
Equal endpoints with different lifecycle states conflict even when range starts
differ. Pending absence is checked against every account-scoped confirmed report
covering the trade timestamp, in both chronology and upload directions.
The immutable economic core must always agree. Present settlement/depo dates,
settlement time, commission and accrued-interest evidence must agree within each
state; absence may be enriched and pending plans never replace settled evidence.
Occurrence cash visibility alone is not material disagreement, but contradictory
present settlement/commission legs still conflict. Projection enrichment does
not rewrite persisted occurrences. Material changes, settled-to-pending, pending
disappearance in an overlapping confirmed report, and ambiguous primary-only
money linkage require reconciliation. A new trade also cannot make a previously
accepted money linkage ambiguous. Incomplete IDs retain observations without
authoritative trade identity.
Money rows linked to incomplete IDs retain their visible blocker and attach to
no identity-less trade.

## Read-only section metadata (#789/#792)

Source Preview adds a separate `metadata_evidence` envelope identified by
`mybroker-section-metadata-v1` and bound to SHA256 of the exact uploaded bytes.
It is not part of normalized S1 JSON, confirmation material or saved receipts.
GET returns the immutable accepted S1 receipt; it cannot reconstruct metadata
without original bytes. Existing accepted Money grammar selection is unchanged.

Only these exact MyBroker-namespace trees report `READY_SAFE_STRUCTURE`:

- `Trades3/Report[@Name='4_Transfers']/Tablix1`: no wrapper/table attributes,
  no table children; raw report inventory remains 1.
- `Trades4/Report[@Name='5_UFSR']/Tablix1[@Textbox4='Подключен']/Details_Collection/Details`:
  exactly one childless Details, with only `sys_start_time` (ASCII
  `DD.MM.YYYY HH:MM`, valid calendar/time) and `sys_end_time='-'`;
  raw report inventory remains 3. The collection/wrapper have no attributes.

Every fixed node occurs once, Report has only its exact Name, and all text/tails
are whitespace-only. Extra attributes/nodes, comments, processing instructions,
foreign namespaces, alternate states/end tokens or malformed times block the
classification. Invalid S1 family/cardinality/bounds still reject the upload.
The previously supported childless Report is a separate family and is not
classified as either new safe pattern.

Both classifications derive zero movements. Connection times are validated but
not returned, constrained to the reporting month or used as transaction dates;
period scope and coverage remain unknown. The envelope retains S1 source warnings
and does not disposition any source/account/Close blockers. Money daily controls,
unknown economics, REPO and unexpected UFSR/Transfers remain unresolved. Any
consumer authority to relax a specific section blocker needs a separate decision
and review; this classifier grants none.

## Native Money linkage compatibility (#788)

The exact full strings `Расчеты по сделке <numeric-primary-id>` and
`Комиссия по сделке <numeric-primary-id>` are accepted from the `oper_type`
attribute of the Money `oper_type` node. The accepted `comment` attribute
variant remains supported. IDs contain 1–128 ASCII digits. Neither field is
trimmed, searched for substrings, translated or used to invent a secondary ID.
When both fields match, they must agree on role and ID; otherwise the complete
document refuses parsing with `money_linkage_conflict`, including legacy rereads.
Matching both fields still yields one observation per original amount leaf.
Other Money operations keep their existing classification and blockers.

New documents with native linkage record the bounded optional
`money_linkage_version=mybroker-money-linkage-v1` extension under the unchanged
`mybroker-s1-v2` identity. Comment-only documents retain their frozen normalized
shape. The extension participates in confirmation material; row ordinals,
source account, posted date, currency, exact signed amount and both trade-native
IDs retain their original authority. Native cash requires a unique settled
trade; pending-only linkage stays unlinked with `money_link_not_settled`.
Existing account/ID ambiguity, direction, date/currency and commission-basis
checks still apply. Link recognition is not financial fee/NKD acceptance.

For exact bytes already accepted as S1 v2, source Preview/replay, broker-month
planning and original-bound Money reads select the grammar recorded in that
immutable receipt. An absent extension means the old comment-only grammar.
Thus old oper_type-only rows remain unsupported; saved JSON, fingerprints,
confirmation digests and receipts are never upgraded or rewritten. Unknown
extension versions refuse parsing with `money_linkage_version_unsupported`.
Fresh reports can provide new native evidence through normal overlap guards;
they never erase an older unsupported occurrence or grant complete coverage.
There is no migration, reimport or financial write in this parser repair.

This bounded fix does not waive unparsed Money/control nodes, Transfers/UFSR,
separate stock-fee proof or any remaining #787 Gate 0 blocker. Original Owner-local
read-only recheck and any subsequently authorized scratch work remain separate.

The [#736 compatibility repair](https://github.com/LTstripes/hermes-finance/issues/736)
also accepts the sanitized completed REPO observation shape at
`Trades/Report/Tablix2/Details_Collection/Details`: exactly one `trade_no`
matching `B[0-9]+`, a distinct single `repo_no` matching `B[0-9]+`, and
`comment` exactly `репо ч.1` or `репо ч.2`. IDs remain bounded to 128 characters.
The partner and marker validate syntax only; no pairing or financial semantics
are derived. The original one-part `ids` remains an observation with
`identity=null`, `repo_observed=true`, `trade_ids_incomplete` and
`repo_semantics_unsupported`. Reciprocal rows and duplicate occurrences never
manufacture a second native ID or an S2 execution.

The parser identity and normalized shape remain `mybroker-s1-v2`; previously
accepted numeric-ID documents normalize identically. Malformed B IDs, ambiguous
partners, absent/inconsistent markers and pending B rows refuse parsing.
B-linked money comments remain unsupported and unlinked. Because S1 does not
retain arbitrary money comments, H2 owner-cash claims cannot override an
identity-less REPO observation in the account's scoped source set. H0/H1,
source-cash coverage and XIRR continue to refuse unresolved affected evidence.

Source settlement/commission legs remain source evidence. No buy/sell principal
is relabeled as payout or realized profit; missing tax stays unknown, accrued
interest stays evidence, and unknown commission embedding never yields an
available all-in cash event. Pending is never actual cash. Transfers/UFSR,
generic money moves and unknown rows remain visible unresolved evidence.

Confirmed per-account source ranges are returned separately from financial
completeness; the latter stays `unknown`, including quiet/empty reports.
Import cannot revise accepted endpoint quantities or silently contradict a
complete no-crossing assertion. Subsequent no-crossing reads/writes also check
accepted source evidence against the historical account universe, preventing a
later assertion from ignoring unresolved event-C1. Existing source-free Phase 1
material signatures and solver behavior are unchanged. Reconciliation/C5 and
Reopen remain prerequisites where already required; S1 cannot perform them.
An unresolved pending trade survives the filename range until an explicit
settled occurrence resolves it. Actual settlement/depo dates crossing later
cutoffs are checked too; a new import surfaces impact on already accepted later
intervals before writing. Planned dates never clear an unsettled cutoff.
Both source guards use the membership-derived account universe at the interval
endpoints and the explicit source-account bindings; an unrelated, excluded or
historically uncovered account contributes no MyBroker blocker. Existing missing
membership guards remain independent. Within an included account S1 still has
no event-C1 proof, so it cannot safely restrict a source event to stock/bond/gold
from today's catalogue or a position's class. All potentially affected classes
remain guarded there; this does not assign or backfill a trade class.

## Endpoint evidence (parser `mybroker-s1-v2`)

`mybroker-s1-v2` adds the accepted #716 Positions evidence without financial
writes. Security rows carry beginning/ending actual quantity, beginning value and
ending value beside the unchanged ending actual/forward quantity keys. Values
keep the source-native basis labels (beginning `previous_day_eod`, ending
`covered_to_eod`) as document `endpoint_basis`; no price is derived, and no bond
nominal/NKD/clean-dirty semantics are introduced.

The RUB currency row is recognized only by the accepted conjunction
`active_type=Валюта`, `active_name=RUB`, empty `ISIN1`, and is normalized
separately as `rub_money` beginning/ending money amounts. Its absence is never
zero RUB. Multiple matching rows are a blocking conflict (`rub_money_ambiguous`);
unclassified Positions rows stay visible blockers and are not stored.

Evidence gaps are document-level `endpoint_blockers`
(`endpoint_beginning_quantity_unavailable`, `endpoint_value_unavailable`,
`rub_money_unavailable`, `rub_money_incomplete`, `position_row_unclassified`).
They remain visible in Preview and committed readback but do not refuse a source
import; conflicts still refuse the whole Apply. Same-date accepted quantity
conflicts are unchanged, and this slice does not compare source values with
accepted snapshots.

A document already accepted under `mybroker-s1-v1` with the same bytes is an
explicit `accepted_parser_version_conflict`, never a silent re-interpretation or
rewrite; endpoint evidence for those bytes needs a distinct report. Coverage stays
`unknown`, and quotes, C1, historical backfill and #715 trade-ledger semantics
remain outside this slice.

Historical reconstruction (#709), trade-to-manual-fact reconciliation, historical
valuation/class evidence, bond returns, transfer semantics and payout-kind
interpretation remain outside S1. Full backend/frontend CI, independent review
and applicable Owner UAT remain separate from focused synthetic checks.
