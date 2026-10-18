# Finite historical membership API (#608)

Implements the accepted lifecycle and #610 valuation identity contracts. This is
not a source of new financial semantics or a durable audit trail.

`GET /api/performance/membership` takes `account_id`, `start_date`, `end_date`
and `scope` (`account` or `portfolio`). The account identifies the history being
edited; dates/scope preserve the original returns request. The response contains
the entire account history, a state identity, a transient form token and canonical
readiness with final XIRR/TWRR from the same committed snapshot.

`POST` takes the same context, `form_token`, `replaced_ids`, `replacements`
(`effective_from`, finite `effective_to`, explicit `include_in_returns`) and
`attested: true`. Empty replacements withdraw the named rows. Unselected rows are
preserved. The UI displays the complete before/after set and old/new interval
union before re-attestation. Open-ended existing rows cannot be selected.

After acquiring the SQLite writer reservation, the API consumes the form and
compares the complete membership/evidence/target state. Replacement, CLOSED
checks and invalidation share that transaction. The mutation returns affected
intervals, retired observation IDs, revoked coverage IDs, boundary target
identities and the resulting identity. After commit, an independent coherent read
must match that identity and read readiness/XIRR/TWRR; otherwise the response is
not a confirmed success. The browser rereads and compares the resulting row set
and identity, invalidating other query consumers. It never retries POST.

The state hash covers the preparation evidence catalogue plus observations,
boundary groups and group members, including targets without captured sides.
This conservative conflict detector is separate from the boundary-date v2
financial material hash. It does not broaden the invalidation map.

Form tokens are process-local, single-use, expire after 30 minutes, and are bounded
to 1024 outstanding entries. A submission retires other outstanding membership
forms; stale/failed/ambiguous submissions require rereading and re-attestation.
Restart loses forms. The existing database-maintenance restore guard changes a
transient form epoch after draining active operations, on success or failure, so
restoring identical contents cannot revive a form. These values are not persisted
financial generations and do not alter the accepted S2 A-to-B-to-A policy.

No migrations, provenance schema, provider calls, inferred historical intervals,
flow-scope rewrites, PRE/POST capture UI or automatic reopen/reclose are added.
