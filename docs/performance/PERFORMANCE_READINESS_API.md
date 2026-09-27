# Performance readiness projection v1

Implementation of #530 under the accepted #529 contract. This read endpoint does
not implement the #531 UI or the #532/#533 write adapters.

`GET /api/performance/readiness` requires `start_date` and `end_date`, with the
existing `scope=portfolio|account` and `account_id` contract. Repeated context
parameters are rejected. Unknown accounts and invalid intervals are context
errors, never a fallback to portfolio or another date range.

The response contains `schema_version=1`, request identity, final `xirr` and
`twrr` using the existing metric DTOs, the existing `evidence` blocks and
`diagnostics`. All three services execute inside one existing coherent read
snapshot. No new calculator, completeness semantics or persisted revision is
introduced. Old endpoints are unchanged.

`evidence.availability` is the prerequisite union, **not** a hide-switch for
either final metric. Final values retain percentage-point units and their
existing annualization flags; exact zero is a value. A prerequisite success
does not promise that the final solver succeeded.

Account sets retain their original names and meanings:

- `evidence.scope_membership.account_ids`: membership-checked catalog;
- `evidence.cash_boundary_coverage.account_ids`: accounts requiring cash evidence;
- `evidence.in_kind_boundary_coverage.account_ids`: accounts requiring in-kind evidence.

There is no reconstructed included-account set.

Diagnostics group exact final reason codes by affected metric. The external-flow
code also yields separate cash-history and legacy diagnostics where those
evidence fields prove them. Unknown codes receive `unknown_reason` with an
unsupported inspection action; they never acquire mutation advice from their
spelling. Refs identify only evidence-backed local records/dates. The whole
response identity supplies the selected scope and interval; refs do not assert
that an entire interval has been confirmed when coverage is missing.

Action kinds are a closed enum with typed local params, never a URL. `available`
means a supported inspection/selection or existing coverage API path;
`requires_reopen` uses the existing coverage edit guard for the requested
interval. Coverage review still requires actual Owner verification and explicit
attestation. `not_implemented` identifies absent historical-membership,
legacy/transfer UI reconciliation or observation adapters. `source_required`
does not claim a historical source is absent. `unsupported` does not promise
that editing or confirming coverage can fix valuation/FX/solver limitations.
Every action requires rereading readiness to verify the final outcome.

Free-form provenance references and non-allowlisted provenance/source labels
are omitted from this projection. Evidence IDs, financial status and values
remain authoritative; old evidence endpoints are unchanged.

Unexpected read/serialization failures and mismatched result identity or value
contracts return HTTP 503 with `performance_readiness_technical_error` and a
retry-read message, without exception text or financial missing-data reasons.
Do not merge a failed response with cached metrics from a different generation.
