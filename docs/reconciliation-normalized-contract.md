# R07-08A normalized reconciliation contract

The normalized reconciliation endpoint is an explicit, read-only owner action
over one transient broker snapshot. It compares the selected reporting-month
Hermes position snapshots with the provider observation and never writes the
database.

## Endpoint

`POST /api/months/{reporting_month_id}/broker-reconciliation-preview`

`POST /api/months/{reporting_month_id}/reconciliation-preview` is an equivalent
short alias. The request has the existing broker snapshot preview mapping
shape:

```json
{
  "accounts": [
    {"hermes_account_id": 1, "provider_account_id": "SYN-ACCOUNT-001"}
  ],
  "instruments": [
    {"hermes_instrument_id": 10, "provider_instrument_id": "SYN-INSTRUMENT-001"}
  ],
  "expected_rows": [
    {"hermes_account_id": 1, "instrument_id": 10, "fingerprint": "..."}
  ],
  "expected_snapshot_fingerprint": "..."
}
```

`expected_rows` and `expected_snapshot_fingerprint` are optional. When present,
they reuse the accepted preview/apply fingerprint semantics and a mismatch
returns a stale, non-actionable result. The provider is called only during
this explicit request.

## Normalized position states

Each response `rows[]` item has exactly one canonical `state`:

| State | Meaning |
|---|---|
| `matched` | Account/instrument identity is resolved and Decimal quantities are equal. |
| `differs` | Identity is resolved and the provider/local quantities differ. |
| `missing_local` | A resolved provider position has no local Hermes position. |
| `missing_provider` | A local Hermes position has no resolved provider row. |
| `unresolved` | Mapping, duplicate identity, quantity, compatibility or freshness prevents a safe comparison. |

An unresolved provider position is retained as a row with an explicit
`reason`; it is never silently relabelled as `missing_local`. Safe display
identifiers are limited to the existing mapping contract and normalized
account/instrument label, ticker and ISIN fields where available.

## Values and gates

- `provider_broker_unit_price`, `provider_accounting_price`,
  `provider_market_value`, `provider_accrued_interest_nkd` and
  `provider_unrealized_result` are comparison-only observations. Their names
  are listed in `comparison_only_fields`; none can overwrite Hermes values.
- Identity reuses explicit account mapping, explicit instrument mapping and
  exact unique ISIN matching from the accepted reconciliation preview.
- An incomplete, stale, non-eligible or compatibility-unknown snapshot is
  fail-closed. The response keeps the diagnostic state/reason and exposes no
  actionable position rows.
- `diagnostics` and `diagnostic_report` reuse the sanitized Alfa compatibility
  and fingerprint contract. They contain no raw provider payload, credential,
  private value or runtime path.
- `read_only` is always `true` and `eligible_for_apply` is always `false` for
  this slice. There is no new apply endpoint, transaction import or background
  refresh.

## Follow-up

The UI/selective-action slice may consume `rows[]` and the per-row fingerprints,
but must retain explicit owner selection, stale-preview revalidation and the
existing CLOSED-month/apply safeguards. It must not infer mappings or promote
comparison-only provider values into Hermes state.

Persistent broker-identity mappings are specified by
[`docs/adr/0016-owner-approved-alfa-baseline-and-broker-mappings.md`](adr/0016-owner-approved-alfa-baseline-and-broker-mappings.md)
Slice A. This endpoint remains read-only: it composes `effective` registry
rows with the request mapping, labels reused/new/conflict identities, and
still never writes quantity or comparison-only fields. Unique ISIN matching
does not persist a mapping. The matcher and comparison-only field list in
this document remain authoritative.
