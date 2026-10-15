# Hermes Finance 1.3.0 candidate

UAT-PENDING. Code-only preparation under #836; not published. Publication remains
blocked until independent review, exact CI, post-move acceptance and an explicit
Owner release decision. These candidate lifecycle lines must be replaced with
accepted publication facts before the guarded #124 request; the existing release
helper rejects them. This document grants no local runtime or data operation.

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
  `rate_fraction=null`; accepted incomplete-DRAFT UAT proves no numeric return.
- The optional #774 WHAT-IF scenario remains separate from actual S3 and is not
  added by this candidate. Assumptions cannot complete actual coverage or Close.
- Historical account/portfolio exact returns remain evidence-gated. Asset-class
  Phase 1 exposes bounded RUB stock/bond/gold no-crossing endpoint returns and
  evidence preparation; legacy unknown identity, unsupported crossings/classes,
  incomplete inventory and solver ambiguity remain unavailable. This is no claim
  of universal Owner-history XIRR/TWRR or completed class-return Owner UAT.

## Compatibility and runtime

Published v1.1.0 and v1.2.0 share Alembic head 0044. The candidate adds 0045–0058.
Synthetic tests cover direct and revision-by-revision upgrade, CLOSED/DRAFT and
legacy provenance preservation, duplicate guards, repeat upgrade, transaction
failure and consistent backup recovery. This supports the **code/schema path**
from either release; the actual destination pin/schema and recovered data still
require fresh post-move validation. Rollback uses the preserved old code and a
verified pre-upgrade recovery copy; source-owned evidence can prohibit downgrade.

Direct Windows Prepare/Validate/Start, backup-first immutable Stable update and
explicit Start remain separate operations. Read-only scratch preflight startup
has additional boundary checks. No Stable/Test update, Owner migration, OPS02,
tag, release, merge or runtime deployment is performed by candidate preparation.

PRs #744/#829, suspended #814 finance authority and #769 financial Apply/Close
are excluded. Alfa PRO protocol compatibility #646 remains unresolved. Hermes
remains local, single-user, Windows-first, loopback by default; no cloud, trading,
telemetry or background provider refresh.

Evidence and post-move gates: [release preparation record](release-preparation-1.3.0.md).
