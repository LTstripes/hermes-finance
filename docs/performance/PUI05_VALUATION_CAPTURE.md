# PUI-05 observed PRE/POST valuation capture — #533

Supported read/capture adapter over the accepted
[`r08-03a` valuation-boundary service](../r08-03a-valuation-boundaries.md) and
the accepted [#610 membership-aware material identity](MEMBERSHIP_AWARE_VALUATION_IDENTITY_CONTRACT.md).
No new valuation engine, importer, event versioning, provider call or derived
financial meaning is introduced.

## Delivered boundary

`GET /api/performance/valuation-captures?start_date=&end_date=&scope=&account_id=`
returns one committed snapshot with:

- the canonical explicit targets that need observed evidence, resolved from
  `performance_availability_for_interval` (never a second target detector);
- target identity: boundary group ID or flow IDs, scope/account, event date,
  reporting month and its status, performance currency;
- `pre_state`/`post_state` per relation (`captured`, `missing`, `stale` or
  `ambiguous`) plus every persisted side with exact amount/currency, coverage,
  quality, provenance kind and the material binding state;
- the current `material_signature` and, only for a truly capturable target, a
  single-use capture token;
- canonical readiness with both final metrics from the same snapshot.

`POST /api/performance/valuation-captures` takes the target identity, the
capture-start `expected_material_signature`, the single-use `form_token` and
one actually observed side (relation, exact amount, provenance
kind/reference, notes, explicit attestation). The server resolves the
reporting month, observed date, target performance currency and authoritative
coverage/quality from the target itself, so a client cannot submit a
mismatched month, boundary date, currency or non-authoritative value.

## Authoritative-only capture

The supported adapter persists only evidence that could ever make the pair
authoritative:

- `coverage=complete` and `quality=exact` (the API accepts nothing else);
- `performance_currency` exactly equal to the target performance currency.

This is intentional: the canonical valuation-boundary service has no
observation update/delete correction path, so an incomplete, inexact or
foreign-currency side would permanently consume the target without ever
making TWRR usable. Owners see only source-backed complete/exact input; the
write form has no unknown/unavailable choices and shows the currency fixed
and read-only. When no confirmed historical source exists, the form says so
and performs no write — the readiness limitation stays displayed.

Persisted legacy/non-authoritative sides remain visible in their stored form
and continue to fail closed. The adapter offers no edit, delete or repair
path for them.

## Fail-closed rules

- The writer reservation is acquired before the authoritative reread; the
  stored signature must equal the capture-start signature or the write is
  rejected (`409`) without mutation.
- Flow correction/delete, group date or member change, and membership change
  therefore change the signature and reject a stale form. The accepted #610
  A→B→A policy is unchanged.
- One side per target and material state: an existing bound side, duplicate
  same-relation rows or an already ambiguous target are rejected. The adapter
  never picks a convenient pair and never retires corrupt rows implicitly.
- Non-authoritative input (incomplete coverage, inexact quality) is rejected
  at the DTO boundary (`422`) and again in the adapter service; a currency
  different from the target performance currency is rejected (`409`). No row
  is created by any rejected submission, so a later valid source-backed
  capture remains possible.
- CLOSED months fail closed (`409`); the read marks the target
  `requires_reopen`. There is no automatic reopen, reclose or retry.
- The capture token is process-local, single-use, expires after 30 minutes and
  is retired by a restore epoch. A rejected or ambiguous submission can only be
  followed by an explicit reread, never a blind replay.
- Amount, currency, coverage, quality, provenance and attestation are validated
  before persistence; only the canonical service stores the observation.

## Read-back

After commit the response is produced from an independent coherent reread: the
saved side must appear bound to the same current signature in the capture
projection, and the canonical readiness (diagnostics plus final XIRR/TWRR) is
read in the same snapshot. A commit acknowledgement alone is never presented as
a confirmed capture. Remaining blockers are not hidden; saving evidence does
not guarantee TWRR, and XIRR stays independently available when its
prerequisites are met.

The readiness diagnostic keeps exact capability semantics: the observation
adapter reports `available` only when a concrete target can accept fresh
evidence now, `requires_reopen` when only the explicit month reopen blocks it,
and `not_implemented`/`unsupported` when identity, grouping or duplicate sides
make input impossible.

## Deliberate limitations

- Observation deletion or in-place correction is not supported by the accepted
  contracts. A wrong observed value can only be replaced through a material
  target change (which retires stale sides) followed by fresh capture.
- Persisted non-authoritative legacy sides are displayed and fail closed; the
  adapter deliberately does not repair, replace or delete them.
- Explicit boundary-group creation/deletion remains a separate lifecycle and
  is not part of this adapter; same-day grouping is never inferred.
- Free-form provenance references are stored but never echoed by the read
  projection.

## Evidence

- Backend API/service tests: target read, exact amount/currency/provenance
  validation, PRE then POST capture to exact TWRR, stale signature rejection,
  token replay and duplicate-side rejection, closed-month rejection,
  non-authoritative and mismatched-currency rejection without mutation
  followed by a successful source-backed capture, legacy non-authoritative
  sides staying visible and fail-closed, group/portfolio targets, private
  reference omission and invalid/unknown context.
- Component tests: only source-backed complete/exact input in the fixed target
  currency, missing-side rendering, single submission under a double click,
  ambiguous outcome without retry and explicit reread unlocking, closed
  month, legacy non-authoritative sides without a repair write, ambiguous
  sides and order-unknown limitations.
- Synthetic browser/responsive checks and exact-head CI are recorded in the
  candidate handoff.
