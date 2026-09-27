# Membership-aware observed valuation identity — #610

Status: **PROPOSED; pending independent performance/data-integrity review.**
Baseline: `31f9fd5386f0b9b25b804f01a7de9c0243f14dc2`.

This contract closes the historical-membership identity gap discovered while gating #608.
It extends #494 / PR #526 without broad event sourcing, a new audit trail, a provider call,
or #533 capture UI.

## Decision

Bind observed PRE/POST valuation evidence to **boundary-date historical membership material**
as well as the existing flow/group material. Use a v2 material hash. Do not grandfather
legacy v1 signatures. No database schema change is required for this policy.

Define the observation target identity:

```text
K = (
  reporting_month_id,
  scope,
  account_id,
  target_kind,
  target_id,
  boundary_date,
)

S2 = SHA256(canonical_json([
  "observed-valuation-material-v2",
  scope,
  account_id,
  boundary_date,
  existing_v1_flow_or_group_material,
  membership_material,
]))
```

Retain all existing #494 flow/group material, including explicit boundary-group membership.
Standalone-flow signatures now receive explicit observation scope/account context. PRE and POST
for one target intentionally share S2; relation and observed amount are not target material.

## Boundary-date membership material

For **account scope**, include only the selected account and every historical membership row
covering the boundary date, represented deterministically as:

```text
(id, account_id, effective_from, effective_to, include_in_returns)
```

For **portfolio scope**, include every account ID in the canonical account catalogue and every
covering membership row for each account, including explicitly excluded accounts. Do not reduce
the identity to accounts that own the target flow/group.

Dates are inclusive; use ISO dates, literal null for open-ended ends and deterministic
account/row ordering. Account names, notes, visibility/status and current `include_in_returns`
are not historical membership evidence.

An authoritative binding requires exactly one covering membership row per relevant account.
Missing/overlapping history is non-authoritative. Explicit exclusion remains known history.

Conservatively, changing a covering row ID, either endpoint or the inclusion flag changes S2,
even when the resulting inclusion boolean on that date is unchanged. Editing an interval that
covers neither the old nor new boundary date does not invalidate that observation.

Whole-return-interval membership coverage and transition rules remain separate. This contract
does not invent intraday membership ordering or synthetic flows.

## Capture, reservation and read-time validation

Capture start obtains K and S2 in one coherent read associated with the actual observed values.
It must not fetch a fresh signature at submit time and attach it to older observations.

At publication:

1. acquire the SQLite writer reservation before authoritative rereads;
2. expire stale ORM state;
3. reread and validate membership, flow/group target identity and CLOSED state;
4. recompute current S2 and compare with the capture-start signature;
5. reject missing/invalid/mismatching identity with no automatic retry or re-signing;
6. hold the reservation through persistence and commit/rollback.

Concurrent outcomes are deterministic:

- membership correction commits first -> older capture fails S2 validation;
- capture commits first -> membership correction retires the persisted observation atomically;
- close wins first -> capture/membership write fails the CLOSED guard.

At read time, recompute S2 in the same coherent snapshot as the observed evidence.
Unbound/stale/mismatching signatures, invalid targets, duplicate PRE/POST sides or inconsistent
identities make the boundary unavailable. PRE and POST must match the same current K and S2.
Retain the existing currency, coverage, quality, provenance and ordering checks. Do not repair
or choose a convenient pair at read time.

The canonical authority path remains
`performance_availability._observed_boundary_for_target()`.

## Legacy v1 compatibility

Choose **fail-closed recapture**, not grandfathering.

Existing v1 hashes and null signatures cannot prove capture-time membership. Keep stored rows
without blanket migration/rewrite, but do not accept them as authoritative v2 observations.
Do not automatically rehash them, assume history was unchanged or manufacture provenance.
Normal authorized invalidation or fresh source-backed recapture may retire them.

Compatibility cost: exact TWRR that depends on v1 observations becomes unavailable until valid
PRE/POST evidence is supplied. CLOSED rows are not silently changed or reopened. This rule must
not independently disable XIRR.

A logical signature-version change is required, but a new schema/version column is not.
The existing nullable 64-character signature column can store the SHA-256 digest; v2 domain
separation plus strict recomputation is enough to reject legacy signatures safely.

## #608 invalidation and validation map

For account `a`, let `U` be the exact union of the complete old and new intervals of all
changed/replaced/withdrawn membership rows. It is not the UI selection and not an enclosing
gap-filled interval. Existing open-ended rows remain read-only/blocking in the first writer.

### Observed valuation identity

`material_signature_for_boundary()` and `stage_create_observed_valuation_point()` must use
v2 membership-aware identity, including targets that have no observation rows yet.

### ObservedValuationPoint

Atomically retire all PRE/POST rows affected by the changed membership:

- account-scope observations for account `a` whose boundary date lies in U;
- every portfolio-scoped boundary whose boundary date lies in U, regardless of target-flow
  ownership, including standalone flows of other accounts and groups with no member flow from a.

Preserve account-scoped observations for unrelated accounts.

### CashBoundaryCoverage / InKindBoundaryCoverage

For account `a`, any overlapping COMPLETE attestation becomes UNKNOWN as a whole row.
Preserve row identity, dates and provenance fields. Do not split, delete or automatically
re-attest it. Do not invalidate unrelated accounts merely because they share a portfolio.

### Read-time availability and immutable facts

`_observed_boundary_for_target()` / `_twrr_boundary_reasons()` independently reject stale or
unbound evidence even if eager invalidation missed a row.

Canonical valuation/membership/flow/transfer/cash/in-kind readers recompute from canonical
history. Do not rewrite external flows or their separately asserted scope flags, transfer
evidence, boundary-group definitions, in-kind movement facts or monthly snapshot values.

### #608 form identity / read-back

The #608 stale-state identity must cover the complete account membership history and affected
evidence/targets, including ObservedValuationPoint, ExternalFlowBoundaryGroup and
ExternalFlowBoundaryGroupMember. The existing preparation token is insufficient unchanged.

After commit, read back the exact resulting membership set and affected identities, then
coherently reread readiness and final XIRR/TWRR for the original request. A read error or
identity mismatch is not success.

## CLOSED and atomicity

Before membership mutation, reject if U intersects:

- any CLOSED reporting period;
- any CLOSED snapshot date within U;
- the CLOSED parent reporting month of any affected observed valuation evidence.

Resolve both stored observation identities and canonical targets. An unresolvable dependency
fails closed; it is not skipped.

Stale comparison, overlap/CLOSED checks, membership replacement, evidence invalidation and
resulting read identity are one transaction with no nested commits.

## Required reference outcomes

| Vector | Required outcome |
|---|---|
| Capture -> relevant include/exclude change -> publish | Reject old capture. |
| Capture -> covering interval endpoint moves -> publish | Reject old capture, even when inclusion at the boundary remains the same. |
| Capture -> covering row withdrawn -> publish | Reject; missing history remains unknown. |
| Account observation -> unrelated account membership changes | Preserve binding. |
| Portfolio observation -> another account enters/leaves at boundary | Reject old capture and retire affected portfolio PRE/POST. |
| Existing signed observation -> accepted membership correction | Retire both sides atomically; read-time validation rejects stale survivors. |
| Fresh observation after correction | Accept when corrected membership and all existing evidence requirements pass; no promise of computable returns. |
| Contractually metadata-only account/flow changes | Preserve binding where existing contracts already say material identity is unchanged. |
| Legacy v1 observation | Non-authoritative under v2; no automatic upgrade. |

## Deliberate boundary

This is **current-material identity**, not a monotonic revision/audit generation.

If material state changes A -> B -> A and is exactly restored, the resulting S2 may again equal
the original hash. Rejecting solely because an intervening edit occurred would require a
separately accepted generation/version mechanism. #608 must not silently introduce one, and
must keep its separate stale-form/restore/duplicate-protection identity.

## Non-goals

- no historical-membership writer in this contract task;
- no #533 capture UI;
- no new financial formula;
- no provider/import inference;
- no audit/provenance schema;
- no broad event sourcing.
