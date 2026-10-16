# Hermes Finance 1.3.0

## Owner-accepted limited release scope (2026-10-16)

The Owner explicitly accepted a **limited local release for weekend UX exploration**
after [independent UAT-1B coverage review](https://github.com/LTstripes/hermes-finance/issues/836#issuecomment-6219722047)
and [Integrator/Owner release decision](https://github.com/LTstripes/hermes-finance/issues/836#issuecomment-6219807480).
This is **not full business/financial UAT**, permission for unresolved financial
Apply/Close, proof of actual returns, or a blanket declaration of UI correctness.
User-facing questions may be assessed in a separate post-installation Owner session.

On the moved HONOR, isolated v1.2.0/0044 recovery to sole v1.3.0/0058, code and
database binding, integrity/FK checks, controlled startup/shutdown, genuine
MyBroker original zero-write Preview API/UI parity, retained source blockers and
70-table unchanged database readback were independently reviewed within their
bounded evidence scope. Stable v1.2.0 and the recovery point remained unchanged
during UAT. The inspected recovered copy had **9 CLOSED months, no DRAFT month,
and no matching accepted S3 source**; its Save action correctly remained disabled
on unresolved mappings and source warnings.

**Not exercised on this moved HONOR 0058 copy:** browser reload parity, positive
DRAFT Apply → GET/replay, source-bound S3 unavailable/null-reason output, and full
Owner semantic UX acceptance. Earlier separate [#773 real-original DRAFT/GET/reload
UAT](https://github.com/LTstripes/hermes-finance/issues/773#issuecomment-6132814727)
and [#774 real September S3 unavailable-path
UAT](https://github.com/LTstripes/hermes-finance/issues/774#issuecomment-6139144470)
provide prior bounded evidence at different isolated source/code checkpoints,
**not new PASS results on the moved HONOR copy**. The independent review result
remains **PARTIAL** for total release-UAT coverage; the Owner knowingly accepts
these exclusions for limited local exploration. Financial/source authority stays
fail-closed until its independent evidence and UAT are completed.

Publication is separate from installing and starting Stable. The protected
production 0044 database must be covered by a **fresh, independently verified
pre-upgrade recovery point** before any separately authorized backup-first OPS02;
then a distinct guarded Start and 0044→0058 post-upgrade financial/CLOSED data
continuity review are required. Rollback pairs preserved v1.2.0 code with its
verified 0044 database, never old code with a 0058 database.

## Broker month and source history

- Original MyBroker XML can be reviewed through zero-write Preview and explicitly
  applied atomically to a source-owned, possibly **incomplete DRAFT**, with
  authoritative GET/reload and immutable source receipts. Account, month,
  stock/bond identity, currency and exact original evidence must match.
- Multi-original month preflight is read-only and zero-write. It diagnoses the
  complete supplied source set; it does not batch Apply or Close historical months.
- Source-native position totals, separate account cash and net payouts preserve
  unknown cost, tax and bond NKD. DRAFT source valuation has its own read-only
  display; ordinary latest-CLOSED Capital keeps its existing basis.
- Reviewed canonical executions, historical endpoints, Owner crossings and
  portfolio/source-cash coverage have explicit provenance, versioned acceptance
  and retirement. Current catalogue values never fill missing historical identity.

## Money and Close limits

- Money recognition alone has no financial authority. Bounded reviewed coupon and
  account funding, settled RUB bond BUY paid-NKD/separate-fee and stock BUY
  separate-fee proofs retain their individual source and dependency requirements.
  Equal dates/amounts do not establish event identity or independent fee basis.
- Permanent occurrence ownership, immutable receipts and replay protect against
  duplicate cash/payouts. Dependency loss retires authority; restoring values or
  replaying an old request cannot silently reaffirm it. Unknown tax/NKD stays null.
- Unsupported Money, REPO, Transfers/UFSR exposure, settlement principal,
  commission basis and unparsed rows remain explicit blockers as applicable.
  Structural section metadata never proves economic-period completeness.
- Incomplete DRAFT is not bookkeeping readiness. Existing scoped server Close
  checks remain authoritative; no automatic Close, historical mapping or broad
  financial Apply is introduced. CLOSED financial facts require explicit Reopen.

## Returns

- BrokerStatementReturn (S3) is a separate read-only, nonannualized **indicative
  account period MWR**, with provenance, exposure and coverage reasons. It is not
  exact portfolio/account XIRR or TWRR. Real September remains unavailable:
  `rate_fraction=null` on the previously accepted unavailable path; no numeric
  September return is financially accepted.
- The separate #839 WHAT-IF scenario (Draft PR #841) is excluded from this
  release. Assumptions cannot complete actual coverage or Close.
- Historical account/portfolio exact returns remain evidence-gated. Asset-class
  Phase 1 exposes bounded RUB stock/bond/gold no-crossing endpoint returns and
  evidence preparation; legacy unknown identity, unsupported crossings/classes,
  incomplete inventory and solver ambiguity remain unavailable. This is no claim
  of universal Owner-history XIRR/TWRR or completed class-return Owner UAT.

## Compatibility and runtime

Published v1.1.0 and v1.2.0 share Alembic head 0044. Version 1.3.0 adds 0045–0058.
Synthetic tests cover direct and revision-by-revision upgrade, CLOSED/DRAFT and
legacy provenance preservation, duplicate guards, repeat upgrade, transaction
failure and consistent backup recovery. This supports the **code/schema path**
from either release; the actual destination pin/schema and recovered data still
require fresh post-move validation. Rollback uses the preserved old code and a
verified pre-upgrade recovery copy; source-owned evidence can prohibit downgrade.

Direct Windows Prepare/Validate/Start, backup-first immutable Stable update and
explicit Start remain separate operations. Read-only scratch preflight startup
has additional boundary checks. Publishing the release does not install it to
Owner Stable, migrate any database or authorize OPS02/Start by itself.

PRs #744/#829/#841, #814 broker-proof-dependent finance authority, and #769
financial Apply/Close are excluded. Alfa PRO protocol compatibility #646 remains
unresolved. Hermes
remains local, single-user, Windows-first, loopback by default; no cloud, trading,
telemetry or background provider refresh.

Evidence and post-move gates: [release preparation record](release-preparation-1.3.0.md).
