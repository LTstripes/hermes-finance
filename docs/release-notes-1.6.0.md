# Hermes Finance 1.6.0

Hermes Finance **1.6.0** packages the Owner-accepted Month and Returns screens
from #962/#964/#965. It improves presentation and source-only review while
preserving existing financial readers, writers, calculations and schema
**0065_source_return_proofs**. There is no database transition from v1.5.0.

The accepted baseline is `f07b20ddc8bdad074fb0993792cf3f06e5cc30f8`, with
[exact post-main CI40216203428](https://github.com/LTstripes/hermes-finance/actions/runs/40216203428)
SUCCESS. This release-only change synchronizes package, lock and health identity
and documentation. Current review, publication and installation evidence belongs
in [CURRENT_STATUS](CURRENT_STATUS.md) and
[#967](https://github.com/LTstripes/hermes-finance/issues/967).

## Changes since v1.5.0

- [#962](https://github.com/LTstripes/hermes-finance/pull/962): the ordinary Month
  hub combines a compact reporting-month list, manual-entry tiles and one inline
  work area. Unsaved/pending navigation stays guarded. **Брокерские выписки**
  provides the ordinary XML entry, source exceptions, recognized stock/bond
  quantities with dates and read-only T-Invest preview. Final review uses server
  Close readiness, explicit confirmation and independent GET/recovery. Incomplete
  source history no longer displays a false all-clear message.
- [#964](https://github.com/LTstripes/hermes-finance/pull/964): **Доходность**
  provides account/period selection, compact amount/rate/coupon/dividend cards,
  monthly history chart/table, instrument detail and profit/loss top five.
  Existing readers supply the values. Legacy full-history links, including links
  without `bond_period`, and long-period Back/Reload selection remain supported.
- [#965](https://github.com/LTstripes/hermes-finance/pull/965): accessible ⓘ
  explanations retain applicable source boundary/payout advisories, including
  `seam_mismatch`. Account-reconciliation growth is labelled as an account result.
  Financial amounts and methods are unchanged.

## Acceptance and remaining limits

[Owner UI UAT: GO](https://github.com/LTstripes/hermes-finance/issues/963#issuecomment-6401873080)
on the accepted baseline, with the native desktop evidence gap explicitly
accepted. The [Operator technical verdict](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6401652215)
is **PARTIAL**: tested routes passed; nine desktop size/zoom scenarios used
CSS/viewport emulation. Native Windows browser zoom/DPI combinations remain
**NOT TESTED**. This acceptance does not turn emulation into a native PASS.

Real financial Apply/Close/Reopen, real manual Save and live T-Invest remain
**NOT TESTED**. Synthetic Save/Close and mock-provider checks do not certify
those operations. Source-only journal Save, proof confirmation, financial Apply
and Close retain their separate authority and currentness requirements.

Source observations and dated quantities do not establish canonical financial
PositionSnapshots, durable forecast/actual-paid reconciliation or complete
historical returns. #711/#889 remain open for that work. Missing opening values,
monthly EOD, supported flows, custody/principal ownership or bond clean/dirty/NKD
evidence continue to withhold dependent results as NULL. Overlapping observations
are not additional payments; provisional Modified Dietz remains distinct from
accepted financial results and exact TWRR/XIRR. This release does not complete
end-to-end financial reconciliation.

## Publication, update and recovery

Follow [O3](OWNER_RUNTIME_OPERATIONS.md#o3) and
[O4](OWNER_RUNTIME_OPERATIONS.md#o4). Publication requires independent release
review, exact accepted PR and canonical main push CI, a separate specific Owner
release GO and the guarded #124 request. Verify the annotated tag, peeled commit
and published GitHub Release before any separately authorized installation.

For an approved v1.5.0/0065 Stable update, preserve the matching code/database
pair, obtain a fresh independently verified backup, and use stock OPS02 pinned
to the published SHA with the explicit existing physical `DatabasePath` and
disjoint `BackupDirectory`. Target Prepare/Validate and Start remain separate
authorized stages. Verify health/version, process/DB binding, source journals,
CLOSED states, financial continuity and Month/Returns after Reload. No Test DB,
source rows or proofs are promoted. Released migration bytes and their README
remain unchanged; existing 0065 proof-history/recovery restrictions still apply.
