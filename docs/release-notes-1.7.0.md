# Hermes Finance 1.7.0

Hermes Finance **1.7.0** packages the integrated Month, DRAFT payout and Returns
work through [#981](https://github.com/LTstripes/hermes-finance/pull/981).
The accepted code baseline is `a1027347b253ed2e53647143726c11f76d09c0da`;
[exact-main CI40653035431](https://github.com/LTstripes/hermes-finance/actions/runs/40653035431)
attempt 2 completed successfully. This packaging change synchronizes version
identity and documentation without changing dependency resolutions, application
behavior or migration sources. Review, publication, installation and UAT state
are recorded separately in [CURRENT_STATUS](CURRENT_STATUS.md).

## Changes since v1.6.0

- [#970](https://github.com/LTstripes/hermes-finance/pull/970) adds durable actual
  payout settlement, dividend handling and scoped Close dependencies. Actual net
  income remains the financial fact; forecasts remain separate. Exact receipts,
  revisions and currentness guard settlement, retirement and reaffirmation.
  Equal amounts or nearby dates alone do not prove a payment.
- [#981](https://github.com/LTstripes/hermes-finance/pull/981) adds the explicit
  **Get and save T-Invest forecasts** action for eligible financial DRAFT
  positions. A current strict broker-month SOURCE receipt, native positive
  PositionSnapshot and supported active RUB stock/bond scope are required.
  Source-only, manual/copied and CLOSED positions are ineligible. Unambiguous
  future events reuse existing forecast writers and the saved calendar;
  unchanged events create no revision, and provider omissions/errors do not
  erase saved forecasts. Actual payout lineage is not revived by refresh.
- [#977](https://github.com/LTstripes/hermes-finance/pull/977) clarifies Month
  forms, position/payout tables and source-observed versus actual versus forecast
  values, and guards fast ISIN/date navigation. [#980](https://github.com/LTstripes/hermes-finance/pull/980)
  preserves explicit source-period selection when no CLOSED reporting month
  supplies a default, including historical links and dated quantity selection.
- [#976](https://github.com/LTstripes/hermes-finance/pull/976) retains one native
  source account per proven alias group and presents signed available-history
  RUB subtotals with coverage. [#979](https://github.com/LTstripes/hermes-finance/pull/979)
  adds the four-category investment basket: brokerage, IIS, deposits/savings and
  physical gold, with one explicit period and URL/Back/Reload selection.
  Source-only account amounts and accepted deposit interest remain separate;
  incomplete composite amounts/rates and gold period results remain unavailable.
- [#971](https://github.com/LTstripes/hermes-finance/pull/971) shows trusted
  exact-ISIN instrument names; [#972](https://github.com/LTstripes/hermes-finance/pull/972)
  preserves query/hash in the legacy Month redirect;
  [#975](https://github.com/LTstripes/hermes-finance/pull/975) corrects documented
  MyBroker reader treatment of included NKD without counting it twice.

## Evidence and remaining limits

The accepted isolated Test migration to **0066_actual_payout_links** and its
preservation evidence remain applicable to the unchanged migration sources.
They are not a new native UI, provider-authentication or financial-write verdict.
CI attempt 1 exposed an intermittent Windows recovery-readiness failure; one
bounded Windows diagnostic did not reproduce it and attempt 2 passed. The cause
has not been established as fixed or harmless.

On 28 October the Owner removed the separate aggregate Test walkthrough and
authorized a guarded Stable update. Visual acceptance was deferred to the
evening/Thursday review; the main monthly UAT is planned for 1 November. No new
Owner visual PASS, successful live provider diagnostic, real DRAFT Apply,
forecast save or Close is claimed. Those financial actions retain their separate
specific authorization and currentness requirements.

Source observations are not accepted financial balances or independent payouts.
Unknown historical account subtype, EOD, NKD/REPO, cash ownership, tax or net
amounts remain unknown. Provisional source Modified Dietz and partial RUB
coverage are not full portfolio TWRR/XIRR. CLOSED history remains protected.

## Publication, update and recovery

Follow [O3](OWNER_RUNTIME_OPERATIONS.md#o3) and
[O4](OWNER_RUNTIME_OPERATIONS.md#o4). The new release identity commit requires
its own exact-candidate review/CI and canonical exact-main push CI. Publish
through guarded #124 and independently verify the annotated tag, peeled commit
and published release before OPS02. The v1.6.0 tag remains immutable.

Updating Stable v1.6.0 moves its schema from **0065_source_return_proofs** to
**0066_actual_payout_links** at the separately authorized Start. First prove the
owned process and physical production DB, stop only that runtime, obtain a fresh
verified stock backup and retain the producing code/schema pair. Use stock
backup-first OPS02 with the explicit existing DatabasePath and a disjoint backup
directory, then target Prepare/Validate and separate Start. Keep the supported
schema, integrity, FK, exact graph and preservation guards. Reuse accepted Test
evidence without replaying its migration or promoting its data to Stable.

The Owner-approved recovery disposition is fail-stop. Failed or uncertain
schema-changing Start requires stopping only the owned runtime, preserving the
resulting database, verified original backup and evidence, and notifying the
Owner. Do not retry blindly, downgrade automatically or overwrite the live
database with a cross-schema backup. An accepted recovery/forward-fix action is
separate from preserving this evidence. Finish a successful update with short
health/version, physical binding and required data-continuity readback.
