# Historical membership — bounded lifecycle proposal (#532)

Status: **ACCEPTED as the bounded lifecycle contract gate in the independent #604 review.**
This document still does not authorize a writer, migration, HTTP endpoint or backfill. #608 implementation remains blocked by the membership-aware observed-valuation identity decision in #610.
The membership slice of #532 stops here. The accepted #529/#530 readers and their
fail-closed diagnostics remain authoritative.

## Existing capability

`AccountPerformanceScopeMembership` already persists account, effective_from,
nullable effective_to and include_in_returns. `valuation_points._selected_accounts`
and `performance_availability` read this history. Accounts API updates only the
current account flag. There is no accepted public historical writer on the assigned
#532 baseline `ccee3902335e82b01215c455a9a64746f1b3c00a`.
Neither current flags, account creation dates, flows, imports nor balances prove
past participation. Flow-level scope_membership is separate evidence.

## Proposed bounded writer contract (requires acceptance)

1. **Explicit evidence and interval.** Owner chooses an existing account, inclusive
   calendar dates `[effective_from, effective_to]` and explicitly attests included
   or excluded. Exclusion is known history, not an unknown gap. The first editor
   accepts finite intervals only; existing open-ended rows remain visible and
   block conflicting edits until an explicitly reviewed correction is possible.
   Current include_in_returns is neither a default attestation nor a write target.
2. **Gaps and overlaps.** Gaps remain unknown; no inferred extension, interpolation,
   merge or fill. Reject every overlapping interval for the same account, even
   when flags agree. Inclusive adjacent intervals must start the day after the
   preceding end. A correction must name all replaced rows and show the complete
   resulting interval set; hidden splitting/truncation is forbidden. Existing
   ambiguous overlaps stay fail-closed until explicitly corrected as one set.
3. **Corrections and withdrawal.** Replace/withdraw explicit row identities with
   optimistic comparison against the entire account history read at form opening.
   Changing either boundary or flag affects the union of old and new intervals;
   withdrawal leaves unknown history. Owner reviews that union and the before/after
   set, and re-attests. Metadata is not yet present in this model: any provenance
   persistence requirement needs a separate accepted schema decision. Do not
   invent an audit table or claim a durable audit trail from the existing columns.
4. **Invalidation.** Never rewrite external flows or their scope flags. In the same
   transaction, invalidate dependent cash/in-kind attestations and observed
   valuation evidence whose scope depended on the changed historical set. The
   implementation proposal must enumerate exact canonical consumers and affected
   account/portfolio boundary/group identities before acceptance; conservative
   invalidation must itself be approved, not implemented ad hoc. Re-attesting
   membership alone cannot attest cash/in-kind history or restore PRE/POST.
   Existing solver rules for in-interval membership transitions remain unchanged.
5. **CLOSED guard.** Reserve the writer before reading history/status/dependencies.
   Reject if the affected union intersects a CLOSED reporting period or a CLOSED
   snapshot/observed boundary relying on it, including an old interval removed by
   correction. For open-ended existing history, the affected future extent is not
   silently bounded by the UI selection. Reopen is a separate Owner operation;
   never reopen/reclose in the writer. Explain all reports requiring reopen, then
   explicit reclose and recalculation.
6. **Atomicity and races.** A single transaction covers stale-state comparison,
   overlap checks, CLOSED checks, replacement and invalidation. Any failure rolls
   back all changes. Concurrent close, correction, deletion, restore or competing
   history edits cannot yield a partial set or stale successful attestation.
   No transaction may commit through a nested service mid-operation. Duplicate
   submits must not create duplicate intervals. Unknown network outcome requires
   authoritative read-back before another write; never automatic POST retry.
7. **Read-back.** Return/read the resulting exact row set and affected identities,
   compare with the submitted correction, then reread canonical readiness and both
   final metrics for the original account/scope/interval. Read error or mismatching
   identity is not success. Saving history does not imply computable returns.

## Required review vectors before implementation

Missing history/current flag toggles; historical exclusion; same-day boundaries;
adjacency versus overlap; gaps; finite edits intersecting open-ended history;
withdrawal; correction moving dates across CLOSED periods; snapshot date outside
its reporting period; transition inside the return interval; portfolio dependencies;
rollback after invalidation; two concurrent edits; close winning/losing the writer
reservation; stale form after restore; duplicate submit; ambiguous response/read-back.

Review must settle the exact invalidation consumer map, open-ended correction UX,
provenance requirements and narrow read/write DTO before any membership code lands.
No #533 capture implementation is authorized by this proposal.
