# MyBroker batch preflight

`POST /api/mybroker-preflight/preview` accepts multipart `files` (one to eight
original XML files) and an optional JSON `intent`. This is a pre-import inventory;
it neither executes BrokerMonth Preview nor creates a ReportingMonth, source,
receipt, mapping or financial row. There is no batch Apply endpoint.

Intent permits `account_bindings` with the existing identity-preview shape and
optional `requested_from` / `requested_to` dates supplied together. Omitted dates
select the uploaded filename-declared range. Bounds are 8 MiB per original,
32 MiB per batch, 30,000 parsed rows and 120 calendar months.

The service uses the existing S1 original grammar selector and native reducer,
strict identity planner, and H0 endpoint definitions inside a query-only committed
snapshot. Previously persisted originals retain their recorded Money grammar and
must match their immutable binder. H0 remains the inventory of persisted accepted
sources; this preflight does not replace it. A new original's range is declared
by its filename under the S1 contract, not independently attested by this Preview.

The response separates:

- `documents`: original identity/range/parser, source-native position and separate
  RUB cash observations on each endpoint side, mappings/type/denomination evidence,
  unsupported section inventory, and distinct source/calendar/financial/DRAFT/
  Close statuses. Normalized Money, NKD and fee observations remain intact with
  unknown financial authority. An independently observed whole month may be a
  candidate for the existing separate reviewed incomplete DRAFT Preview.
- `calendar`: whole-month original availability and explicit references to source
  endpoint sides. Missing interior EOD is unknown. A partial or wide report proves
  only its own endpoints and dated events; it cannot lend intervening EOD or
  historical market valuations. A following first-day opening can reference the
  previous day's EOD without establishing a whole-month original.
- `seams`: adjacent ending versus opening quantities, source values and RUB cash,
  compared only for the same native source account. Differences use exact Decimal
  arithmetic; one kopeck is a conflict. Missing/ambiguous rows stay unknown. These
  comparisons do not attest complete settled inventory or financial coverage.
- `native_trade_inventory`: existing reducer projections plus occurrence lineage,
  exact duplicate/enrichment/pending-to-settled, changed core/material, missing
  overlap and multiplicity diagnostics. Repeated identical file uploads are
  counted as uploads, not new trade occurrences. Anonymous Money is never
  economically deduplicated. No second ledger is persisted.
- `report_availability`: explicit missing adjacent and 2025 originals. A known
  range is an observation, not proof of historical financial completeness.

`coverage_state` and `financial_completeness` remain `unknown`;
`financial_apply_available` is false and `close_performance` is blocked. Preflight
grants no source-account/portfolio crossing, H2, Close, XIRR or TWRR authority.
The Owner-original pilot is a separate later read-only UAT. Automated evidence
uses fabricated originals only; originals and private response values belong
outside Git, logs and public issue/PR evidence.
