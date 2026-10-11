# Read-only MyBroker Money candidate inventory

Authority: [#778 accepted contract](https://github.com/LTstripes/hermes-finance/issues/778#issuecomment-6109639388)
and the bounded implementation assignment [#780](https://github.com/LTstripes/hermes-finance/issues/780).

`services.mybroker_money_candidates.read_money_candidates(session, import_id=...,
document=original_bytes, filename=original_filename, account_id=...)` is a
standalone backend diagnostic read. It returns the typed
`mybroker-money-candidates-v1` inventory for an accepted S1 import. There is no
HTTP route, persistence model, acceptance endpoint or financial writer.

The read uses a committed coherent snapshot. It reparses the original through
the unchanged S1 family/namespace/schema/filename/cardinality/bounds rules and
requires equality of every parser fact, ordered Money leaf and section inventory
against the immutable import. Established service enrichment is preserved;
occurrence fingerprints use the full saved S1 rows, exactly like existing cash
coverage readers. Changed bytes, parser, declared range, account facts, amounts
or ordinals refuse interpretation with a bounded error code.

Every signed amount leaf remains an observation, including unsupported rows and
the existing settlement/commission roles. Those roles retain precedence and
their saved linkage; they are never second candidate cash rows. Explicit,
currently valid `alfa_mybroker` bindings must resolve both filename and row
account to the selected brokerage/IIS account. Invalid bindings, posted dates
outside the confirmed range, non-RUB amounts, zero, fractional kopecks, signed
64-bit overflow and wrong direction leave the observation unsupported with
typed reasons. There is no rounding or currency/date substitution.

The three observed shapes are exact-operation, full-narrative coupon and
incoming-account-cash candidates, and exact negative `НКД по сделке`. Narrative
recognition is bounded to 4096 characters; the coupon date suffix is checked
using the existing strict source day grammar, solely as a conservative shape
check. Its value never replaces `settlement_date`. Placeholder issuer/bank/token
values never become instrument, owner, trade or economic identities. Unknown
and dividend shapes remain unsupported. All candidate authority is `unproven`;
instrument/event links stay null, incoming cash has unknown owner crossing and
portfolio externality, and paid NKD has unknown execution linkage and embedding
basis. No current accrued valuation is inferred.

`summary_proof_unavailable` is mandatory: the accepted manifest does not prove
the complete source-rooted account/currency/amount summary selector or row join.
No `oper_group` label or matched total is manufactured. All current S1
blockers/conflicts and missing mappings remain in the inventory exceptions,
including opaque, pending, REPO and unparsed-source evidence.

The inventory exposes all relevant overlapping accepted reports and their
Money occurrence references, even after binding withdrawal. Same-report
multiplicity stays visible. Different matching multiplicities in overlapping
reports have an explicit `overlapping_source_multiplicity_mismatch` diagnostic;
the reader does not pair or collapse their rows. Equal date/amount/currency only identifies possible
competing evidence; it never establishes economic equivalence. Missing matches
in a report covering the posting date remain explicit. No report union is
summed or deduplicated. `source_subtotals` counts admissible candidate leaves
only within the selected original, preserving repeated leaves. It is diagnostic
source arithmetic and must not be added to endpoint cash or interpreted as
canonical payments.

DTO source hashes, account aliases and occurrence fingerprints are Owner-local
provenance. Do not log/publish them. Raw narratives, bank/issuer names and tokens
are consumed in memory and are absent from DTOs and errors. Public tests and
evidence use fabricated originals only.

S1 JSON/receipts, financial ledgers, source cash, UNKNOWN coverage and Close
guards are unchanged. The standalone inventory reports
`financial_apply_available=false`; recognition cannot complete source-account
bookkeeping. The separate financial contract/writer and later Owner UAT remain
outside this adapter.
