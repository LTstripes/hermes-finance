# ADR 0016 — Owner-approved Alfa current-state baseline and reusable broker mappings

- **Status:** Proposed (contract-first for issue #201; not implemented)
- **Date:** 2026-08-29
- **Release line:** `r07` / Reconciliation Center track
- **Source task:** R07-D05 / issue #201
- **Parent roadmap:** issue #127
- **Implementation follow-up:** two bounded slices after integrator acceptance (see §12). No implementation issue is opened by this ADR.
- **Related:** [ADR 0009](0009-moex-market-identity-and-quote-semantics.md), [ADR 0010](0010-market-and-broker-provider-strategy.md), [ADR 0013](0013-broker-snapshot-and-alfa-pro-security.md), [ADR 0015](0015-alfa-pro-compatibility-diagnostics.md), [R06-03 field mapping](../reviews/2026-08-20-r06-03-alfa-pro-field-mapping.md), [R07-08A normalized reconciliation](../reconciliation-normalized-contract.md), [R07-07 freshness/provenance](../FRESHNESS_PROVENANCE.md)

## Problem

Current Alfa / broker reconciliation is `transient mapping only`. Every preview and every R06-05 quantity apply must resend account and instrument mappings in the request. The matcher already allows explicit owner mapping plus exact unique ISIN; it does not persist either.

The owner’s intended monthly workflow is the opposite: on an explicit baseline date (planned owner use: `2026-08-31`), one reviewed Alfa PRO current snapshot should establish trusted **current holdings identity and quantity**. Later runs should reuse confirmed mappings and ask only about new, changed, or ambiguous identities.

This ADR is the contract for that change. It does not ship schema, API, UI, or provider writes.

## Non-negotiable invariants

These remain authoritative and are not weakened:

- local single-user product; loopback-only; no cloud/auth/telemetry/trading/background refresh;
- exact money: `Decimal` / integer minor units, `ROUND_HALF_UP`, no binary `float` in financial logic;
- a CLOSED reporting month is immutable until explicit reopen;
- Hermes identity stays canonical; provider IDs are projections (ADR 0013 §6);
- frontend is not the financial source of truth;
- no raw Alfa payloads, credentials, runtime paths, or private diagnostic artifacts in Git, logs, API, or persistence;
- existing historical imports (manual, Excel, T-Invest quotes/payouts, Alfa depository PDF statements) remain historical truth and are not re-imported or rewritten by a current-state baseline.

## Current accepted surface (baseline of this contract)

This ADR is written against current `r07` `67fa84653be23c05852f2e05bd0c4bcd39c879f9`.

| Surface | What it already does | What it must not be mistaken for |
|---|---|---|
| `BrokerSnapshotProvider` / Alfa PRO adapter (ADR 0013, R06-03) | Owner-triggered read-only current snapshot | Historical ledger, cash-flow import, trading |
| R06-04 matching / preview | Explicit account mapping; explicit instrument mapping; exact unique ISIN; fail-closed conflicts | Persistent mapping store |
| R07-08A normalized reconciliation | Read-only row states; comparison-only provider valuation fields; `eligible_for_apply=false` | Apply path |
| R06-05 `broker_snapshot_apply` | Selective quantity apply into one editable month; dependent average cost / market price / NKD are owner-local decisions; closed-month refusal; fingerprint stale-preview protection; identical quantity + `keep_existing` dependents is `unchanged` | Persistent mappings; cash apply; provider price/UchPrice/NKD/P&L as Hermes values |
| `instrument_market_mappings` | Market-data quote identity (T-Invest `instrument_uid` / historical MOEX board identity) | Broker account/position identity |
| Alfa depository PDF import | Per-import transient statement mapping | Broker snapshot mapping |
| R07-07 `alfa_pro_positions` freshness family | Always `unknown` because Alfa observation timestamps are **not** persisted after quantity apply | A freshness clock invented from `updated_at` or apply time |

R06-05 already implements the quantity write the owner needs. The missing contract is: **when** a current snapshot may become the trusted current-state boundary, **which** Alfa fields may persist, and **how** owner-confirmed mappings are reused without silent remap.

## Decision

### 1. Introduce a persistent broker-identity mapping registry

Add a local, owner-controlled **broker identity mapping registry**, separate from market-data mappings and from statement-import mappings.

The registry stores provider-scoped **account** and **instrument** identity links that the owner has explicitly confirmed. Subsequent broker snapshot preview/reconciliation **pre-populates** those links into the existing `OwnerMappingInput` shape and labels them as reused. The existing matcher remains the resolver. This ADR does not invent a second matching engine.

Logical record (storage shape is an implementation decision; these fields are normative):

```text
BrokerIdentityMapping
    mapping_id
    provider                  # e.g. alfa_pro; later t_invest broker snapshot
    subject_kind              # account | instrument
    provider_identity         # opaque provider key; see §3
    hermes_target_id          # accounts.id or instruments.id
    status                    # effective | revoked | superseded
    observed_isin             # instruments only; optional evidence at confirmation
    confirmed_at
    source_as_of              # snapshot observation time used at confirmation
    captured_at
    predecessor_mapping_id    # set on remap
    successor_mapping_id      # set when this row is superseded
    revoked_at / revoke_reason
```

Append-only lifecycle: confirm, revoke, and remap insert or status-transition history. They must not rewrite the original confirmation tuple `(provider, subject_kind, provider_identity, hermes_target_id, confirmed_at)`. Historical `PositionSnapshot` rows are never rewritten because a mapping later changes.

### 2. Registry is not the other mapping tables

| Store | Bounded context | Canonical key | This ADR |
|---|---|---|---|
| `instrument_market_mappings` | Market quotes (ADR 0009 / 0010) | provider + `provider_instrument_id` (+ venue) | Unchanged. T-Invest quote `instrument_uid` stays here. |
| Statement import mappings | Alfa depository PDF inspect/prepare/apply | Per-import ISIN/account mapping | Unchanged. Transient per import. |
| **Broker identity mapping registry** | Broker current holdings identity | `(provider, subject_kind, provider_identity)` | **New.** First implemented provider: `alfa_pro`. |

Copying or inferring broker mappings from market mappings, statement mappings, account names, `external_code`, tickers, section codes, or `IIAType` is forbidden. No automatic backfill from legacy data.

The registry is provider-neutral so a future T-Invest **broker** snapshot adapter (ADR 0010) can store `t_invest` account/instrument holdings identity without sharing the quote-mapping table. This ADR does not implement T-Invest broker import.

### 3. Provider identity keys

Hermes local `account_id` / `instrument_id` remain canonical.

For `provider = alfa_pro` the registry keys are the keys the accepted matcher already uses:

| Kind | Provider identity | Alfa field | Not a registry key |
|---|---|---|---|
| `account` | `provider_account_id` | `ClientAccountEntity.IdAccount` | `IdSubAccount`, `IdRazdel`, `RCode`, names, `IIAType` |
| `instrument` | `provider_instrument_id` | `ClientPositionEntity.IdObject` / `AssetInfoEntity.IdObject` | ticker, name, section, subaccount |

Subaccount/section IDs remain snapshot observations. They are not mapping keys in this contract. Mapping at section granularity, or aggregating duplicate provider rows that resolve to the same Hermes `(account, instrument)`, remains the existing fail-closed rule (“no aggregation rule”). This ADR does not add that rule.

ISIN is **not** the registry key. Exact unique ISIN matching remains a deterministic **resolution path** under the existing matcher (see §5).

Provider identity is opaque text as already accepted. A changed provider id is a new identity, never a silent remap of the old one (ADR 0013 §6).

### 4. Effective / revoked / remapped / uniqueness

Statuses:

| Status | Resolver behaviour | Owner effect |
|---|---|---|
| `effective` | Loaded into `OwnerMappingInput` for the next preview | Shown as reused; owner may keep, revoke, or remap |
| `revoked` | Ignored | Owner must map again if the provider identity reappears |
| `superseded` | Ignored; successor is the effective row | Previous confirmation remains auditable |

**Remap** is revoke-by-supersession plus a new `effective` row in one explicit owner action. It is not an in-place overwrite of `hermes_target_id`.

While `effective`, uniqueness is fail-closed as follows, per provider:

1. **Forward (accounts and instruments):** at most one `effective` Hermes target for `(provider, subject_kind, provider_identity)`. A second distinct target for the same provider identity requires explicit remap.
2. **Reverse (instruments):** at most one `effective` `provider_instrument_id` for `(provider, hermes_instrument_id)`. A second provider instrument id for the same Hermes instrument requires explicit remap.
3. **Reverse (accounts):** multiple provider accounts may point at one Hermes account only when the owner confirms each pair explicitly. That is not aggregation: if those accounts then contribute duplicate resolved positions for the same Hermes instrument, the existing position-level conflict still wins.

Identical repeated confirmation of an already effective pair is idempotent (no new successor). Confirming a **different** Hermes target for an effective provider identity without an explicit remap/revoke is a **conflict** and must not write. The same applies to a second `effective` provider instrument id for one Hermes instrument.

Request-body mappings (today’s `OwnerMappingInput`) remain valid for one preview/apply:

- equal to an effective registry pair → reused, not a conflict;
- new provider identity with no effective row → candidate `new` mapping, persisted only after explicit confirmation (§6);
- disagrees with an effective registry pair and the request does not carry an explicit revoke/remap → `conflict`, fail-closed.

One Hermes instrument may appear under many mapped **accounts**; instrument uniqueness is per provider instrument id, not per account. Duplicate provider **position** rows that collapse to one Hermes `(account_id, instrument_id)` stay a position-level conflict (existing R06-04 rule). That conflict is not resolved by this registry.

### 5. Resolution order (preview)

Each owner-triggered snapshot preview keeps the accepted gates: incomplete / stale / non-eligible / compatibility `unknown|unsupported` snapshots are fail-closed and not apply candidates (ADR 0013, ADR 0015, R07-08A).

Then:

1. Load `effective` registry rows for the snapshot’s `provider`.
2. Compose them with any explicit request mappings under §4.
3. Run the **existing** matcher:
   - accounts: explicit mapping only;
   - instruments: explicit mapping, else exact unique normalized ISIN (`strip` + `upper`; empty ISIN is absent);
   - ticker / name / `IIAType` / section code / numeric similarity never create identity;
   - explicit mapping that contradicts present ISIN evidence on both sides is `conflict` (existing B5).
4. Classify each identity row for owner display (presentation on top of matcher status, not a second matcher):

| Classification | Meaning |
|---|---|
| `reused` | Resolved from an `effective` registry row |
| `deterministic_isin` | Instrument resolved only by exact unique ISIN; no effective registry row yet |
| `new` | Unmatched; owner must map or skip |
| `ambiguous` | Existing matcher `ambiguous` (multiple Hermes ISINs) |
| `conflict` | Existing matcher `conflict`, uniqueness violation, or request/registry disagreement |
| `provider_identity_absent` | An `effective` registry row whose provider identity is not in this snapshot (orphaned; not auto-revoked) |

Owner-readable labels (title, type, short id) remain a presentation concern. They must not become registry keys. UUIDs/internal ids stay secondary.

Unique ISIN matching **may** resolve an instrument without a registry row. It must **not** silently insert a registry row. Persistence happens only under §6.

### 6. When the registry may be written

Registry writes are explicit owner confirmations. Allowed writes:

- confirm a `new` account mapping;
- confirm an instrument mapping that the matcher already resolved (`explicit` or `deterministic_isin`) or that the owner picked from a non-ambiguous candidate set;
- revoke an `effective` mapping;
- remap as defined in §4.

Forbidden writes:

- silent persist because unique ISIN matched;
- silent persist because preview ran;
- silent persist because quantity apply ran **without** those identities being in the confirmed set;
- backfill from closed months, statement imports, market mappings, or guessed names.

A successful **baseline apply** (§7) of a selected position row **must** include, in the same transaction, confirmation of the account and instrument identities used for that row (already `effective`, or newly confirmed in this action). Quantity must not land without a durable identity explanation.

Revoke/remap never mutates already applied `PositionSnapshot` quantity, cost, or quotes.

### 7. Owner-approved current-state baseline

A **baseline** is an explicit owner action that uses one complete, compatibility-confirmed Alfa (or later broker) current snapshot to establish trusted **current position quantity** in **one editable reporting month**, after identity confirmation.

Normative flow (issue #201 UX, now contract):

1. Owner fetches a current read-only snapshot (existing adapter; no background refresh).
2. Preview shows reused / deterministic / new / ambiguous / conflict identities.
3. Owner confirms only unresolved/new mappings; may revoke or remap reused ones.
4. Preview shows current quantity differences for resolved identities (existing R06-04 / R07-08A states).
5. Owner explicitly applies **selected** quantity rows to the editable month through the accepted R06-05 apply path (fingerprint, selective, transactional).
6. Re-running the same baseline against unchanged identities and quantities is idempotent: selected rows come back `unchanged` and no financial fields move.

Baseline parameters:

| Field | Rule |
|---|---|
| `provider` | Snapshot provider; first implementation `alfa_pro` |
| `reporting_month_id` | Must exist and be editable (`draft`). CLOSED → refuse, existing `CLOSED_MONTH` semantics. |
| `baseline_date` | Owner-declared current-state date. **Must equal** that month’s `snapshot_date`. Planned owner use is `2026-08-31` on the August 2026 month whose `snapshot_date` is that day. A mismatch is fail-closed. |
| `source_as_of` / `captured_at` | Provenance of the snapshot actually confirmed. Local observation time may differ from `baseline_date`; do not substitute one for the other (R07-07 four clocks). |

What a baseline **may** establish, after explicit owner confirmation:

- registry account mappings;
- registry instrument mappings (deterministic or owner-picked);
- `PositionSnapshot.quantity` for selected resolved rows with provider quantity `> 0`, via R06-05 `update` / `create`;
- baseline provenance (§8).

What a baseline **must not** silently establish or overwrite:

- any other reporting month, including earlier closed months and other drafts;
- deposits, withdrawals, transfers, statement payouts, T-Invest payouts, or performance history (`external_flows`, valuation points, XIRR/TWRR inputs);
- Hermes `average_cost_per_unit` from Alfa `UchPrice` / accounting price;
- Hermes `market_price_per_unit`, `price_date`, `price_source` from Alfa `Price`;
- Hermes `accrued_interest` from Alfa `NKD` / `PSTNKD`;
- Hermes unrealized result from Alfa `NPLtoMarketCurPrice` / `DailyPL`;
- Hermes cash balances from Alfa `ClientBalanceEntity.Money` (still non-comparable at this `r07` schema);
- new Hermes accounts or instruments invented from the snapshot;
- credentials, raw frames, or private diagnostics.

R06-05 dependent-field rules stay: `create` requires explicit **local** average cost and market price/date/source; `update` requires explicit `keep_existing` or explicit **local** replace. Provider valuation fields are never a legal replace source.

Zero or missing provider quantity cannot be applied (existing R06-05). A missing provider row must not delete a Hermes position. Hermes-only rows are visible in preview; clearing them is outside this baseline contract.

`ClientPositionEntity.IsMoney = true` is a cash-like observation. Those rows are **not** quantity-baseline eligible and must not create or update `PositionSnapshot` instrument rows. They stay with the cash/comparison family.

Provider-only rows whose identity is unresolved stay `unresolved` / `new`. They are never silently created.

### 8. Baseline provenance (minimum persist)

When a baseline apply commits, persist a month-scoped **baseline provenance** record (name is an implementation decision) containing only:

- `provider`;
- `reporting_month_id`;
- `baseline_date`;
- `source_as_of`;
- `captured_at`;
- owner `confirmed_at`;
- sanitized `compatibility_fingerprint` / apply fingerprint already used by R06-05 / ADR 0015;
- per selected row: `position_snapshot_id`, action `created|updated|unchanged`, applied `quantity`.

Do not persist provider prices, NKD, P&L, cash amounts, tickers, names, or raw snapshots in this record.

This **narrowly supersedes** ADR 0013 §11 for the enumerated minimum in §10 only. Issue #201 is the owner’s explicit persistence confirmation for those fields. The legal/terms gate remains closed for raw payloads, undocumented extras, and any broader Alfa-derived ledger.

R07-07 currently states that Alfa PRO observations are transient and the `alfa_pro_positions` family is always `unknown` (`alfa_pro_observation_not_persisted`). After the implementation slice that writes §8, that family must be updated to read this provenance: `source_as_of` is the observation clock; `confirmed_at` is import/apply time and is **not** freshness. Until that slice lands, R07-07 stays as written.

### 9. Existing historical data and coexistence

A current Alfa baseline **coexists** with earlier imported history as a new trusted **current-state** boundary:

- closed months keep their snapshots;
- statement/T-Invest/manual history is not re-derived from Alfa current state;
- the selected draft month becomes the owner-approved current holdings quantity for that `snapshot_date`;
- later months are not auto-cloned or backfilled by this contract (existing month clone/reopen rules unchanged);
- performance/history contracts that already treat closed snapshots as truth continue to do so.

No migration rewrites owner data. No backfill of the registry.

### 10. Alfa fields: persist vs comparison-only vs ignored

Authoritative raw-field meanings remain R06-03 / `FIELD_MAPPINGS`. A field name is still not evidence. This table is the **persistence/apply** gate on top of that mapping.

#### 10.1 May persist (minimum)

| Alfa entity.field | Snapshot field | Persist as | Condition |
|---|---|---|---|
| `ClientAccountEntity.IdAccount` | `provider_account_id` | registry account identity | Explicit owner confirm / baseline confirm |
| `ClientPositionEntity.IdObject` / `AssetInfoEntity.IdObject` | `provider_instrument_id` | registry instrument identity | Explicit owner confirm / baseline confirm |
| `AssetInfoEntity.ISIN` | `isin` | optional `observed_isin` evidence on the instrument mapping; also deterministic match input | Never the registry key; never overwrites a conflicting Hermes `Instrument.isin` |
| `ClientPositionEntity.TorgPos` | `quantity` | `PositionSnapshot.quantity` | Explicit selected R06-05 apply; quantity `> 0`; identity resolved and confirmed; not `IsMoney` |
| (Hermes clocks) | `source_as_of`, `captured_at` | baseline provenance | Written only with a committed baseline apply |
| (sanitized ADR 0015) | compatibility fingerprint | baseline provenance | Value-independent structural fingerprint only |

#### 10.2 Comparison-only — preview may show; never write as Hermes financial truth

Listed names match `COMPARISON_ONLY_PROVIDER_FIELDS` plus cash and classification observations.

| Alfa entity.field | Snapshot field | Why comparison-only |
|---|---|---|
| `ClientPositionEntity.Price` | `broker_unit_price` | No accepted unit/currency/scale conversion into Hermes `market_price_per_unit` |
| `ClientPositionEntity.UchPrice` | `accounting_price` | Must not become `average_cost_per_unit` merely because it exists |
| `ClientPositionEntity.NKD` | `accrued_interest_nkd` | Non-comparable vs Hermes kopecks; not auto NKD apply |
| `ClientPositionEntity.NPLtoMarketCurPrice` | `unrealized_result` | Hermes unrealized is derived from local valuation; not broker НПУ |
| `ClientBalanceEntity.Money` | cash `amount` | Hermes cash is month-scoped and (on this `r07`) not account-linked; existing cash rows stay `non_comparable` |
| `ClientPositionEntity.IsMoney` | `is_money` | Classification only; money rows are not instrument quantity baseline |
| synthesized `market_value` | `market_value` | R06-03 forbids `TorgPos * Price` stand-in; no official position market-value field |
| `SubAccountRazdelEntity.RCode` / `IdRazdel` / `IdSubAccount` / `IdRazdelGroup` | section/subaccount observations | Display/correlation only; not registry keys |
| `AssetInfoEntity.Ticker` / `Name` | `ticker` / `display_name` | Discovery/display hints; never identity; not stored as mapping keys |

R07-08A `comparison_only_fields` remains the API list for valuation observations. Implementation must not promote those fields into write instructions.

#### 10.3 Unresolved / ignored — do not map, persist, or infer

| Alfa field | Reason |
|---|---|
| `ClientAccountEntity` extras / live `IIAType` | Undocumented; IIS stays owner-controlled (ADR 0013 §7) |
| `ClientPositionEntity.PSTNKD` | Insufficient to distinguish from `NKD` |
| `ClientPositionEntity.DailyPL` | Daily P/L is not unrealized-result |
| `ClientBalanceEntity.PortfolioCost` | Portfolio-level; not position market value |
| `ClientOperationEntity` and type codes `3` / `14` | Not in the production snapshot; not a ledger (ADR 0013 §9) |
| `#Order.*`, limits, archive, order book, trade tape | Trading/out of adapter |
| Raw router frames, credentials, exception text | Privacy / ADR 0013 §10–11, ADR 0015 |

### 11. Synthetic acceptance examples

All identities below are synthetic (`SYN-*`). No owner/runtime values.

Shared fixture unless a row overrides it:

- provider `alfa_pro`;
- Hermes account `H-ACC-1`, instrument `H-INS-1` with ISIN `SYN000000001`;
- draft month `2026-08` with `snapshot_date = 2026-08-31`;
- complete compatible snapshot, `eligible_for_apply = true`.

#### E1 — First-time mapping

**Given** empty registry; snapshot account `SYN-ACCOUNT-001`, instrument `SYN-INSTRUMENT-001` with unique ISIN `SYN000000001`, `TorgPos = 10`; Hermes has `H-ACC-1` / `H-INS-1` and no August position.

**When** owner maps `SYN-ACCOUNT-001 → H-ACC-1`, accepts the unique-ISIN instrument resolution, and applies create with explicit local average cost and market price.

**Then** registry gains two `effective` rows; August `PositionSnapshot.quantity = 10`; baseline provenance written; comparison-only `Price`/`UchPrice`/`NKD` are not copied.

#### E2 — Reused mapping next run

**Given** E1 registry rows still `effective`; next snapshot same identities, `TorgPos = 12`; August still draft with quantity `10`.

**When** owner opens preview with no request mappings.

**Then** account and instrument classify `reused`; owner is not asked to re-enter them; quantity preview is `differs` / `12 vs 10`; apply update with `keep_existing` dependents writes quantity `12` only.

#### E3 — New instrument

**Given** E1 registry; snapshot adds `SYN-INSTRUMENT-002` with ISIN `SYN000000002` and no Hermes instrument with that ISIN.

**When** preview runs.

**Then** `SYN-INSTRUMENT-001` stays `reused`; `SYN-INSTRUMENT-002` is `new` / unmatched; no row is auto-created; quantity apply of the new id is refused until the owner maps it to an existing Hermes instrument (or creates that instrument **outside** this flow, then maps). This flow does not invent instruments.

#### E4 — Changed provider account identity

**Given** effective `SYN-ACCOUNT-001 → H-ACC-1`; new snapshot has only `SYN-ACCOUNT-002` (old id absent).

**When** preview runs.

**Then** `SYN-ACCOUNT-001` is `provider_identity_absent` (not auto-revoked, not silently rebound); `SYN-ACCOUNT-002` is `new`; positions under `002` stay unresolved until explicit remap `001` superseded and `002 → H-ACC-1` confirmed. No quantity apply through the orphaned mapping.

#### E5 — Conflicting ISIN

**Given** effective `SYN-INSTRUMENT-001 → H-INS-1` and Hermes ISIN `SYN000000001`; snapshot `SYN-INSTRUMENT-001` now carries ISIN `SYN000000099`.

**When** preview runs.

**Then** instrument status is `conflict` (“explicit mapping contradicts provider ISIN evidence”); classification `conflict`; row is not applyable; registry remains `effective` until owner remaps or fixes local ISIN by the ordinary instrument editor. No silent retarget.

#### E6 — Revoked then remapped

**Given** E1 effective instrument mapping.

**When** owner revokes `SYN-INSTRUMENT-001`, then remaps it to `H-INS-2` (existing Hermes instrument, ISIN compatible or absent).

**Then** original row becomes `superseded` (or `revoked` then a new confirm — remap must leave history); new `effective` row points at `H-INS-2`; previously applied August quantity on `(H-ACC-1, H-INS-1)` is **unchanged**; later preview uses `H-INS-2`.

#### E7 — Identical baseline rerun

**Given** E1 after apply (quantity already `10`, dependents kept); same snapshot, same mappings, same `baseline_date`.

**When** owner applies the same selected row with the same fingerprint-valid keep-existing decisions.

**Then** result item action is `unchanged`; `PositionSnapshot` financial fields and `updated_at` semantics follow existing R06-05 no-op (no rewrite); provenance may record the rerun as unchanged evidence but must not invent a second quantity history. Mapping confirm is idempotent.

#### E8 — Closed-month refusal

**Given** August month `closed`; registry may already be populated.

**When** owner requests baseline apply (or R06-05 apply) for that month.

**Then** refusal with existing closed-month semantics; no quantity write; no registry write as a side-effect of the refused apply. Reopen remains the only path to edit that month. Preview may still be read-only.

Additional synthetic guards the implementation slices must keep (already accepted elsewhere, restated so they are not dropped):

- request maps one provider account to two Hermes accounts → `conflict`;
- two provider position rows resolve to the same Hermes pair → position `conflict`, no aggregation;
- stale/incomplete/compatibility-unknown snapshot → no actionable rows, `eligible_for_apply` false;
- `UchPrice` present and owner omitted local average cost on **create** → validation error, not a silent copy.

### 12. Implementation split (next phase, not this task)

This ADR is contract-only. After integrator acceptance, implement in **two** slices. Do not start them from this commit.

#### Slice A — Persistent registry + preview reuse

**Intent:** stop asking the owner to retype confirmed Alfa identities.

**May:**

- additive Alembic tables for the registry (append-only status model);
- service to load `effective` rows into `OwnerMappingInput`;
- explicit confirm / revoke / remap API;
- preview DTO classification in §5 (`reused`, `deterministic_isin`, `new`, …);
- synthetic tests for E1 mapping persist, E2 reuse, E3 new, E4 changed id, E5 ISIN conflict, E6 revoke/remap, plus uniqueness conflicts;
- keep R06-04 matcher behaviour unchanged aside from feeding it persisted+request mappings.

**Must not:**

- apply quantity;
- persist comparison-only fields or raw payloads;
- backfill from legacy data;
- change `instrument_market_mappings` or statement import;
- call live Alfa or touch owner runtime.

#### Slice B — Current-state baseline apply + provenance

**Depends on:** Slice A accepted.

**Intent:** one explicit baseline onto an editable month using R06-05.

**May:**

- wrap existing `apply_broker_snapshot_preview` with `baseline_date` equality check, identity-confirm-in-transaction, and §8 provenance;
- exclude `IsMoney` rows from quantity apply;
- update R07-07 `alfa_pro_positions` to read persisted baseline provenance without mixing clocks;
- owner UX for the six-step flow; visible reused vs new mappings;
- synthetic tests for E7 idempotent rerun, E8 closed-month, comparison-only non-apply, `IsMoney` exclusion.

**Must not:**

- write cash, deposits, transfers, payouts, or provider prices/NKD/P&L into Hermes financial columns;
- mutate closed months;
- implement T-Invest broker import;
- broaden the Alfa channel allowlist;
- treat this ADR as license to auto-sync.

UI for Slice A may wait for Slice B if the API is testable without it. Do not hide registry writes behind an implicit preview.

### 13. Relationship to earlier ADRs

- **ADR 0010** remains the market-vs-broker split. This registry is the broker-portfolio mapping that ADR 0010 sketched. It does not merge with quote mappings.
- **ADR 0013** remains the snapshot/security boundary. §8/§10 of this ADR resolve §11 **only** for the listed minimum fields, because issue #201 is explicit owner confirmation. Raw payloads stay forbidden. `ClientOperationEntity` stays out.
- **ADR 0015** remains the compatibility fingerprint. Baseline apply still requires `compatible` + complete + eligible snapshot.
- **R06-05** remains the only quantity write path. This ADR does not add a second apply engine.
- **R07-08A** remains the read-only normalized row contract until Slice A/B change composition (pre-populated mappings, not a new matcher).

## Consequences

- The owner can confirm Alfa identities once and reuse them.
- Current quantity can become trusted current-state without rebuilding the portfolio by hand and without touching closed history.
- Provider valuation/cash/P&L cannot leak into Hermes books through “the numbers were on the snapshot”.
- Implementation is split so mapping reuse can land even if baseline provenance needs a second review.
- Until Slice A/B land, production behaviour stays transient mapping + existing R06-05.

## Non-goals (this ADR / this task)

This document does not:

- add Alembic migrations, ORM tables, API/UI, or provider writes;
- persist mappings or baseline provenance in this commit;
- implement T-Invest broker holdings import;
- map subaccount/section as identity;
- aggregate duplicate section rows;
- apply cash or zero-out Hermes-only positions;
- infer IIS from Alfa;
- reopen or rewrite closed months;
- access owner runtime, Preview, `.env`, real DB, or live Alfa.

## References

- Issue #201 — R07-D05 owner-approved Alfa baseline and reusable broker mappings
- Issue #127 — 0.7+ roadmap (Reconciliation Center)
- ADR 0013 — broker snapshot boundary and Alfa PRO security
- ADR 0015 — Alfa PRO compatibility diagnostics
- `docs/reviews/2026-08-20-r06-03-alfa-pro-field-mapping.md`
- `docs/reconciliation-normalized-contract.md`
- `hermes_finance.broker_data.reconciliation.matching`
- `hermes_finance.services.broker_snapshot_apply`
- `COMPARISON_ONLY_PROVIDER_FIELDS`
