# Hermes Finance 1.5.0

Hermes Finance **1.5.0** packages the accepted #957/#958/#959 source-return
improvements and schema **0065**. It preserves the existing financial history,
source-intake journal and explicit financial acceptance boundaries.

The application baseline is `f9290d7df218c3a46097a674b4d9492826980eff`, with
[exact post-main push CI40170329244](https://github.com/LTstripes/hermes-finance/actions/runs/40170329244)
SUCCESS. This release-only change synchronizes package/lock/health identity and
documentation; it changes no financial reader, writer or migration source.
Current review, publication, installation and attributed local UAT evidence
belong in [CURRENT_STATUS](CURRENT_STATUS.md) and
[#940](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6394683187).

## Changes since v1.4.0

- #957 verifies the complete selected original set to localize strictly recognized
  source-booked custody cancellations. It can unblock supported months whose
  own boundaries and flows are available, while the unresolved cancellation
  month retains NULL. Long statements do not supply intermediate monthly EOD.
- #959 adds one-time, explicit source-proof Preview and attested confirmation.
  Ordinary monthly GET, Month and Monthly Returns can reuse current source-only
  evidence after Back, Reload and service restart, without selecting XML again.
  Confirmation stores provenance, not XML, calculated money/rates or financial
  acceptance. Exact source membership, revisions, manifests, retirement nonces
  and physical database birth identity determine currentness. Stale/ABA/restored
  evidence fails closed until a fresh explicit confirmation.
- Month and Monthly Returns share exact Decimal ROUND_HALF_UP rate display.
  Provisional amounts, approximate period Modified Dietz and assumed flows stay
  visibly separate from accepted financial results, exact XIRR and exact TWRR.
- #958 recognizes bounded dividend year/delimiter narrative variants. GET does
  not relink saved rows. An optional approved relink updates only derived metadata;
  recognized registration/issuer text does not prove an instrument match. Overlap
  observations remain one economic event, never additional payments.

## Database transition: 0064 → 0065

Published v1.4.0 at `b027bcd90c56c500d271a9ee963485bdfa67ea79` uses
`0064_month_template_provenance`. The new head is `0065_source_return_proofs`.
Its accepted migration adds two initially empty tables and thirteen triggers:
four append-only guards and nine monotonic dependency-retirement guards.

All existing tables, columns, source journals, classifications, mappings, CLOSED
months and manual/financial facts must remain unchanged; only the old
`alembic_version` row advances. No original import, private seed, proof creation,
relink or financial promotion occurs during migration. Released migrations and
`backend/migrations/README` remain byte-stable. The migration refuses downgrade
before DDL once any proof history exists, including stale history.

## Update, UAT and recovery

Follow [O2](OWNER_RUNTIME_OPERATIONS.md#o2),
[the 0065 operating boundary](OWNER_RUNTIME_OPERATIONS.md#o3-source-proof-recovery)
and [O4](OWNER_RUNTIME_OPERATIONS.md#o4). Preserve the current database and verified
backup. Prepare Test at an exact accepted SHA through stock OPS03; separate Start
performs the approved migration. Verify all historical table fingerprints,
schema/trigger identity, CLOSED states, source universe and process/physical DB
binding. Synthetic checks do not substitute for Owner-local UAT.

Each environment requires its own current zero-write Preview, backup/readback and
separate Owner consent for proof confirmation and optional relink. A 0064 relink
Preview that claims no trigger writes is invalid under 0065. The new Preview must
account for every generated dependency nonce. If both writes are approved, relink
first and refresh/confirm proof last. Never transplant Test rows, proofs or DB into
Stable, reimport sources for this update, Apply, Close or Reopen implicitly.

Publication requires independently accepted release-only main, exact main push CI,
Owner release GO and the exact #124 trigger; verify annotated tag, peeled SHA and
GitHub Release. Keep this compatible canonical path
`docs/release-notes-1.5.0.md`; leave published v1.4.0 and its assets unchanged.

Before Stable rollout, rehearse **0064→0065 on an isolated production-compatible
copy at the published SHA**, with authentic snapshot/backup and complete
preservation/readback. Record the recovery code/backup pair, cutoff/RPO and
outage/forward-fix limits for separate Owner acceptance. Then use owned Stop,
fresh verified backup, stock OPS02 with the explicit existing physical
`-DatabasePath` and a disjoint `-BackupDirectory`, target Prepare/Validate, and a
separately authorized Start. Check health/version/SHA/schema, API/UI, Reload and
data continuity. Stable source proof/relink remain separate decisions afterward.

Stock restore requires an exact live schema signature; OPS02 refuses an older
target, and O4 recovery creates an isolated target. None supplies an in-place
0065→0064 production rollback. A 0064 backup with its producing code is retained
evidence, not permission to restore it over migrated Stable. Never open 0065 with
an old binary, copy a raw DB over Stable, remove guards or perform unapproved
restore/downgrade. A restored physical DB invalidates saved proof even if its
contents match; preserve old proof history and obtain fresh confirmation.

## Remaining financial limits

Supported original-bound months and native dated intervals remain provisional.
Unsupported calendar months in 2024–2026 stay NULL where intermediate EOD, opening
values, membership or owner-flow coverage is missing. The unresolved August
custody/principal/cash/settlement identity remains NULL after source proof.
Unsupported bond clean/dirty valuation, boundary NKD and settlement/ownership
economics also remain NULL. Conditional estimates and known components are
separate; no market prices, unknown flows or NKD are silently substituted.
