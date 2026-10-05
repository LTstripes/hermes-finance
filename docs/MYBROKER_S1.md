# MyBroker S1 normalization and import lineage

Authority: [#708 accepted contract](https://github.com/LTstripes/hermes-finance/issues/708#issuecomment-5999540552)
and the Owner-supplied sanitized Integrator syntax manifest. Parser constants and
hand-built synthetic fixtures record that manifest; they do not claim public
format stability. No Owner XML is used in implementation or tests.

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

Historical reconstruction (#709), trade-to-manual-fact reconciliation, historical
valuation/class evidence, bond returns, transfer semantics and payout-kind
interpretation remain outside S1. Full backend/frontend CI, independent review
and applicable Owner UAT remain separate from focused synthetic checks.
