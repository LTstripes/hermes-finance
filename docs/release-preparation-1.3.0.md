# v1.3.0 code-only release preparation — #836

Authority: [issue #836](https://github.com/LTstripes/hermes-finance/issues/836) and
[Integrator 6200484920](https://github.com/LTstripes/hermes-finance/issues/836#issuecomment-6200484920).
This record describes the candidate and future gates, not completed production UAT.

## Source inventory (2026-10-15)

| Identity | Verified repository fact |
| --- | --- |
| Published v1.2.0 | Published 2026-10-04; annotated tag `f9311d26c1aae7295361937096844f4dde615b55`, peeled commit `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc` |
| v1.1.0 | Peeled commit `32c905cfc938fd1aeaeb67643eb6fa77e8644a64`; schema 0044 |
| Pinned live main | `46a9e6db01fcbf868362028957678b0d856d804c`; 122 commits / 273 changed files from v1.2.0; 14 new migrations |
| Excluded PRs | #744 and #829 are open/unmerged at inventory time; their branches are not integrated here |
| Owner installation | Not inspected by this CODE-ONLY task; last attested v1.1.0 is historical, not current measurement |

The published release supplies the previous monthly workflow, portfolio/account
Performance, direct runtime and backup-first immutable update. It does **not**
contain the later source-first broker-month workflow, Money/H2 additions, S3,
DRAFT source valuation, class-return Phase 1 or multi-original preflight. Those
are accepted-main capabilities being packaged, subject to the explicit limits
in [candidate notes](release-notes-1.3.0.md). No feature branch is bundled.

## Supported synthetic schema path

`v1.1.0 / v1.2.0 (0044) -> v1.3.0 (0058)` is one code/schema route; an intermediate
v1.2 installation adds no schema step. This does not authorize a direct production
jump from an unmeasured installation. A different, damaged or unknown schema is
BLOCKED pending diagnosis; never stamp it to a convenient version.

Both released tags and pinned main contain byte-identical migration sources
0001–0044 and the migration runner/template/README (47 files). SHA256 over sorted
`repository-path + NUL + git-blob-bytes` is
`154be96b42969e9eb56397476f4a38ca88a585b1f2f9f2e089c4e67a0fdc00c2` for each.
`test_r13_00_release_verification.py` pins that digest (normalizing checkout CRLF)
and creates the common released schema from those actual unchanged migrations;
it does not merely stamp a current schema or require tags/network in CI.

| Revisions | Purpose / preserved limit |
| --- | --- |
| 0045–0047 | Historical class identity and explicit no-crossing/inventory evidence; legacy identity remains NULL, no inferred claims |
| 0048–0049 | Immutable MyBroker imports and canonical executions; no financial backfill |
| 0050–0053 | Historical endpoints, Owner flows, source cash and portfolio evidence; new authority tables start empty |
| 0054–0055 | Reviewed instrument dispositions and append-only corrections; no automatic historical mapping |
| 0056 | Nullable source-native finance; legacy rows keep required components; exact totals preserved through SQLite table rebuild |
| 0057–0058 | BrokerMonth receipts and permanent Money occurrence ownership; no duplicate ledger or cash backfill |

New compatibility regressions seed CLOSED/DRAFT positions with deliberately
non-derived integer totals, NULL NKD, manual payouts, existing statement-event
provenance and baseline receipts. Every original column/row in every old table
is compared after direct and each-revision upgrade. They verify integrity/FKs,
empty new authority tables, natural-key duplicate rejection, idempotent rerun and
recovered-copy re-upgrade. Injected DDL collision and late invalid-FK failure prove
the direct migration transaction restores the old schema/version/data; a separate
verified SQLite backup remains recoverable. This is bounded fault evidence,
not proof against every disk/power-loss failure or all possible Owner histories.

Migrations are additive in meaning; 0056 rebuilds tables. They are not a promise
of unrestricted downgrade. Existing regressions in `test_migrations.py` reject
lossy class/source/native/Money downgrades with evidence present. Recovery means
retaining the old immutable code and a verified pre-upgrade database, separately
recovered and checked before any runtime use. Never open a 0058 DB with old code.

## Verification and acceptance gates

- New release compatibility tests plus existing migration/receipt/downgrade tests
  cover schema/data preservation; backend CI must execute their owning lanes.
- Existing broker-month HTTP regressions and real-backend browser journey cover
  Preview -> reviewed Apply -> GET/reload, replay, incomplete DRAFT and blocked
  Close. Money tests retain original-bound proof, atomic rollback and ownership.
- S3/source-XIRR tests cover null reasons, exact-vs-indicative separation and
  unavailable coverage. No real numeric September acceptance is implied.
- Exact candidate PR CI must complete all applicable backend quality/test lanes,
  frontend lint/tests/build, real-backend journeys, privacy, Windows Release
  safety and Windows production smoke. A filtered visual job is not a visual
  PASS; no UI is changed in this packaging slice. Canonical exact-main push CI,
  including synthetic visual audit, is required later after authorized integration.
- Independent code/financial/release review is required on the final candidate.
  CI and review results belong to the draft PR with exact SHA/run identities;
  this plan is not a pre-written PASS. There is no merge/publication authority here.
- Before publication: complete applicable Owner UAT, accept remaining limitations,
  replace candidate lifecycle wording in the publication notes with accepted
  facts, obtain CI/review for any resulting change, then recheck exact main and
  release identity under [RELEASE_AUTOMATION](RELEASE_AUTOMATION.md). Only a
  separately authorized #124 decision may publish the immutable release.

## Post-move UAT and rollout plan (future authorization required)

1. Transfer first: bounded local executor establishes actual old code pin/schema,
   stops only its owned runtime, preserves originals and consistent SQLite copies
   including WAL-aware recovery, and proves recoverability on HONOR. Keep Tecno
   intact. Do not copy a live SQLite file blindly, reuse the old Windows venv,
   substitute symlinks or use same-volume relocation tooling across machines.
2. Revalidate destination paths, source identity, Python and fresh Prepare/Validate.
   Record actual Stable role/pin/schema and backup/restore proof. A historical
   v1.1.0 attestation is insufficient. Select the proven 0044 route only after
   matching actual metadata; otherwise stop and diagnose.
3. Under separate bounded Test/Preview authorization, use a consistently recovered
   isolated copy with exact candidate code. Desktop UAT: original -> zero-write
   Preview -> explicitly authorized incomplete DRAFT -> GET/reload; truthful
   account readiness and source valuation; blocked Close with retained reasons;
   actual S3 `rate_fraction=null` for unproved September. Verify old totals,
   provenance, duplicate protection, CLOSED immutability and no invented tax/NKD.
   Financial Money/H2 acceptance requires its own original-specific evidence.
4. After transfer and UAT PASS, Owner/Integrator decides on release publication.
   Complete exact-main CI/review and #124 safeguards; independently read back the
   published annotated tag, peeled commit and GitHub Release. Until then there
   is no published v1.3.0 Stable target.
5. Only with new explicit rollout authority: backup-first OPS02 to that immutable
   target, separate guarded Start/migration, then integrity/FK, code/schema/process
   binding, health, finance/provenance and CLOSED readbacks. Updater preparation
   alone does not migrate or prove readiness. On failure stop, retain old Stable
   and recover old data/code through the supported recovery procedure; never
   relabel partial work as release completion.

CODE-ONLY preparation, production UAT readiness and production rollout readiness
are separate verdicts. This task performs none of the future local operations.
