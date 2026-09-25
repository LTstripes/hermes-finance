# ADR 0017 — Protected off-site recovery points and isolated recovery

- **Status:** Accepted contract; implementation and Owner-live recovery acceptance complete on 2026-09-25. #543 is non-blocking post-closeout hardening.
- **Date:** 2026-09-18
- **Source task:** #417-A / #458
- **Parent contract:** #417 execution-contract freeze, `issuecomment-5731304512`
- **Related:** [ADR 0004](0004-localhost-request-security.md), [ADR 0012](0012-runtime-and-agent-workspace-isolation.md), [ADR 0014](0014-launcher-runtime-profile-safety.md), [`OWNER_RUNTIME_OPERATIONS.md`](../OWNER_RUNTIME_OPERATIONS.md)

## 1. Decision summary

Hermes supports two explicit provider-neutral filesystem destination modes.

`external_encrypted_destination_v1` remains the protected mode. Its configured
destination must be the writable view of an already existing Owner-managed
encrypted container or volume whose encrypted backing storage is synchronized
off-device. Hermes does not encrypt an archive, derive or store keys, call a
cloud API, or upload in the background. An ordinary synced folder is not
protected.

`synced_filesystem_destination_v1` is the Owner-accepted plaintext synced
filesystem mode, recorded as `protection_state=owner_accepted_plaintext`. It
describes an ordinary synced folder, including the Owner's initial Google
Drive for desktop folder, and must not be labeled or attested as encrypted or
protected-at-rest. Hermes proves only local publication and destination
read-back for either mode. It does not claim Google or any other cloud
delivery. The Owner confirms off-device visibility separately. No Google API,
OAuth, SDK, cloud account, telemetry, or background upload service is added.

The Owner decision on #417, 2026-09-25, accepts this plaintext privacy
tradeoff and supersedes the earlier requirement that the off-device
destination be encrypted. Existing artifacts that already claim
`external_encrypted_destination_v1` are not retroactively reclassified.

This ADR freezes the contract for the managed recovery-point publisher,
retention, isolated disaster-recovery rehearsal, and post-restore read-state
invalidation. #459 publisher, #460 retention, #461 isolated DR, #462 restore
read-state, the real-rehearsal fixes #511/#524, and #527 plaintext synced mode
are accepted and integrated. On 2026-09-25 the Owner-live completion flow also
passed: fresh plaintext publication/read-back, independent off-device visibility,
and a clean isolated DR rehearsal with verified readiness and unchanged source.

## 2. At-rest protection contract

The protection decision is explicit and machine-readable:

```text
protection_state=protected
protection_mode=external_encrypted_destination_v1
format_version=1
```

```text
protection_state=owner_accepted_plaintext
protection_mode=synced_filesystem_destination_v1
format_version=1
```

The protected state is valid only after the Owner has attested outside Git
that the existing encrypted container/volume has already been successfully
opened or mounted and is readable and writable by the supported workflow.
Independent availability of recovery material remains an Owner-controlled UAT
gate for that mode. Hermes does not validate or authenticate that material.

The plaintext state is valid only when the Owner explicitly selects that exact
pair, accepting that the destination is an ordinary readable and writable
synced filesystem folder and is not encrypted. Its privacy-safe destination
alias is `synced-filesystem-destination`. The protected alias remains
`protected-destination`.

Hermes records or returns only the selected protection mode, format version,
and the matching privacy-safe destination alias.

The following are mandatory fail-closed rules:

- missing, unknown, unattested, unreadable, or unwritable protection boundary
  fails before destination staging;
- a normal Google Drive, OneDrive, Dropbox, Syncthing, NAS, or other synced
  folder is not protected merely because it synchronizes;
- plaintext publication succeeds only for the exact pair
  `owner_accepted_plaintext` + `synced_filesystem_destination_v1`;
- unknown states, unknown modes, and crossed pairs fail closed before
  destination staging or restore mutation;
- a published manifest must match the requested pair on later verification,
  retention, and disaster-recovery rehearsal;
- no key, credential, full private path, financial value, or reconstructive
  payload is persisted or logged;
- Hermes does not validate or authenticate a key or recovery material;
- independently available recovery material for the encrypted mode remains an
  Owner-controlled UAT gate and is not stored inside the recovery artifact or
  only on the laptop being backed up;
- plaintext publication does not claim cloud delivery.

Portable Hermes archive encryption would require a separate accepted design
for a vetted format/library, authenticated encryption, key derivation and
storage, rotation, packaging, and recovery. This ADR does not authorize it.

## 3. Managed recovery-point contract

A recovery point is a single versioned managed artifact containing a
consistent SQLite snapshot and a deterministic manifest. The concrete
serialization is an implementation detail of #459, but the logical contract
is fixed:

- the snapshot is produced through the accepted SQLite online-backup path;
  copying a live `finance.db` is not a backup operation;
- the manifest identifies format version, one exact accepted protection
  state/mode pair, creation time, snapshot/schema identity, artifact size,
  deterministic artifact and snapshot hashes, the producing checkout's full
  40-character Git SHA, and the source database Alembic revision set as an
  exactly sorted deterministic set;
- verification accepts only that exact pair; publication, retention, and
  disaster-recovery rehearsal must request the same pair that the manifest
  records;
- a unique destination-local incomplete name is used while the artifact or
  manifest is incomplete;
- only one exact managed final-name pattern is eligible for listing or
  retention; incomplete, stale, corrupt, foreign, and unknown names are not
  recovery points;
- staging, manifest construction, SQLite integrity/foreign-key/schema checks,
  and deterministic hash checks complete before final exposure;
- final exposure uses an atomic same-filesystem rename/move;
- the destination artifact is read back and fully verified before the result
  may report `published` and `verified`;
- a destination-scoped exclusive lock rejects or safely serializes concurrent
  publication; a contended or ambiguous lock fails closed;
- an interrupted run must not leave a name that can be mistaken for a
  completed recovery point;
- a failed run preserves the newest previously verified recovery point.

Destination validation occurs before staging. It rejects production data,
Stable/Preview/development checkouts, the normal local backup directory,
source artifacts, non-regular or reparse-linked paths, and ambiguous roots.
Path aliases are never treated as a substitute for proving the allowed
destination boundary.

The operation result is privacy-safe and distinguishes at least:

| Result fact | Meaning |
|---|---|
| `created` | A consistent snapshot was produced; it is not yet a published recovery point. |
| `verified` | Manifest, hashes, SQLite checks, and protection state passed before/after publication as applicable. |
| `published` | The exact final name was atomically exposed and destination read-back verification passed. |
| `action_required` | The operation did not complete or a follow-up owner action is required. |

The result may include only a destination alias/class, format/protection
versions, creation time, size, read-back state, retention outcome, and action
required. It must not include financial values, account identifiers,
credentials, encryption material, full private paths, or raw payloads.

## 4. Retention boundary

Retention runs only after a replacement has been fully published and read-back
verified. It is deliberately not a catalogue service:

- enumerate only exact managed final names whose artifact and manifest verify
  as the same accepted protection pair as the replacement;
- retain the newest 12 verified managed recovery points of that pair;
- in a directory that contains both accepted pairs, the bound is 12 verified
  managed points per accepted protection pair;
- perform no age-based expiry or deletion in v1;
- preserve the newest verified recovery point of the pair being replaced;
- never delete a verified point whose manifest pair differs from the
  replacement;
- never delete unknown, partial, corrupt, foreign, or unrelated files;
- never delete the newest verified point before its replacement is complete;
- report cleanup failure separately without invalidating a newly verified point.

Any cleanup of incomplete staging artifacts remains limited to the exact
managed incomplete-name contract. It must never become a general folder
cleanup operation.

## 5. Isolated disaster-recovery rehearsal

The supported rehearsal proves recovery into a clean isolated Finance
profile. It is not a production restore and never overwrites Stable.

Before target mutation, the Owner explicitly selects one immutable full
40-character recovery Git SHA and an independent checkout pinned exactly to
that SHA. A branch or other ref without the full SHA, an ambiguous checkout,
or a dirty checkout fails closed. The selected recovery SHA may differ from
the producing SHA when the compatibility rule below accepts a forward
upgrade; recovery is not restricted to the producer SHA.

Before target mutation, the workflow must verify:

1. the source artifact is the expected managed format and its manifest,
   hashes, producer SHA, sorted source Alembic revision set, protection
   state, container readability, SQLite integrity, and foreign keys all pass;
2. the source artifact remains unchanged throughout verification and restore;
3. the selected recovery checkout is independent, clean, pinned exactly to
   the selected SHA, and its Alembic migration graph and supported head set
   are loaded;
4. every source revision is known to that graph, and exactly one of these
   relationships is accepted:
   - `same_revision`: the source revision set equals the selected checkout's
     supported head set;
   - `forward_upgrade`: one unambiguous supported forward-only Alembic path
     exists from the source revision set to the selected checkout's heads;
5. unknown, ahead, divergent, downgrade-required, ambiguous, or multiple
   unsupported paths fail closed before target mutation;
6. the target is a fresh isolated checkout/profile/data/database boundary;
7. Stable, Preview, development workspaces, local backup/source aliases,
   reparse/linked paths, non-empty targets, and conflicting targets are
   rejected;
8. only broad non-private structural counts and readiness facts are emitted.

After compatibility verification, re-read the selected checkout's Git SHA and
clean state immediately before the restore target write. If migration occurs,
perform a new identity/clean-state re-check immediately before migration. If
Start occurs, perform another new re-check immediately before Start. Every
phase must still equal the selected full SHA and remain clean. An identity
change fails closed before target mutation where possible and never proceeds
to migration or Start. Verification, the existing ADR 0014 schema-preflight,
guarded Prepare/Validate, migration, Start/readiness, and final evidence all
use that same selected SHA; this workflow does not create a second runtime
state machine.

The rehearsal restores into the isolated target and confirms that the
application can read restored months and core financial surfaces. Successful
privacy-safe evidence binds the managed artifact identity and hashes, producer
SHA, sorted source revision set, selected recovery SHA, selected checkout
head set, accepted relationship (`same_revision` or `forward_upgrade`), and
resulting readiness/schema/code identity. It does not perform cloud
operations or claim Owner UAT.

## 6. Restore read-state contract

Successful existing in-app restore must invalidate affected owner-facing read
state. The month list is reloaded from the restored database; the selected
month ID is retained only when it exists in that list. Otherwise the client
selects the restored list's allowed fallback or clears selection when the list
is empty. Stale pre-restore month IDs and lists must not remain visible as
current.

The focused implementation and frontend regression are integrated through
#462 / PR #502. This ADR freezes the behavior without adding a new UI state
system or a backup-publisher UI.

## 7. Owner acceptance and boundaries

Owner-live acceptance completed on 2026-09-25 for the explicitly accepted plaintext synced-filesystem workflow:

- fresh `owner_accepted_plaintext / synced_filesystem_destination_v1` recovery point published with destination read-back verified;
- Owner independently confirmed that exact new artifact was visible off-device;
- clean isolated DR rehearsal from that artifact returned `status=rehearsed`, `source_verified=true`, `source_unchanged=true`, `restored=true`, `prepared=true`, `validated=true`, `readiness=verified`, and `schema_relationship=same_revision`.

Hermes does not prove Google cloud delivery; the off-device observation is Owner evidence. The encrypted mode remains available only for a genuinely encrypted destination. No Worker may access Owner data, credentials, backups, or private artifacts.

#417 is closed completed. #543 is non-blocking post-closeout hardening and does not alter this accepted contract.

The following remain outside this ADR:

The following remain outside this ADR:

- Google Drive or any other provider API/OAuth/SDK;
- archive encryption, key handling, or cloud account management;
- background sync, telemetry, resident services, or an unbounded scheduler;
- automatic restore over Stable or Preview;
- plaintext cloud-sync success claims, including any claim that Google or
  another provider has delivered the artifact;
- production code, dependency changes, schema migrations, backup artifacts,
  or Owner runtime mutation in #458.

## 8. Synthetic acceptance matrix

Automated acceptance uses only temporary/synthetic databases and simulated
filesystem destinations for the accepted protection pairs. No row authorizes
Owner data or a real cloud operation.

| ID | Boundary and adversarial case | Required evidence | Owning child |
|---|---|---|---|
| A01 | Consistent SQLite snapshot through accepted backup primitives | Snapshot passes integrity, foreign-key, and schema/migration checks | #459 |
| A02 | Complete-then-publish into simulated protected destination | Atomic final name appears only after complete verification; read-back passes | #459 |
| A03 | Interrupted or partial publication | Incomplete/stale name is never listed or accepted | #459 |
| A04 | Destination read-back corruption | Publication/read-back verification fails closed | #459 |
| A05 | Missing, unknown, unattested, unreadable, or unwritable protection boundary | Fails before staging or restore mutation; Hermes does not validate key/recovery material | #459 / #461 |
| A06 | Concurrent publication to one destination | Exclusive lock rejects or safely serializes; ambiguous/stale contention fails closed | #459 |
| A07 | Retention with unknown, foreign, partial, and corrupt files | Only exact verified managed artifacts are eligible; newest verified point survives | #460 |
| A08 | Failed next run after a good point | Prior newest verified point remains usable; failure is explicit | #459 / #460 |
| A09 | Clean isolated restore and rehearsal | Source unchanged; target boundary, DB/schema/readiness checks pass | #461 |
| A10 | Restore with stale selected month/list | Month list reloads; stale selection cannot remain current | #462 |
| A11 | Existing local backup/restore and OPS02/OPS03 safety | Existing safety regressions remain green; no production/Preview alias | #459 / #461 |
| A12 | Privacy-safe status and logs | No financial values, secrets, keys, full private paths, or raw artifacts | #459 / #460 / #461 / #462 |
| A13 | Manifest identity is incomplete or nondeterministic | Producer full SHA, sorted source Alembic revision set, format identity, and artifact/snapshot hashes are required | #459 / #461 |
| A14 | Prepared but schema-incompatible checkout | Ambiguous or multiple unsupported paths, or any other incompatible relationship, fails before target mutation | #461 |
| A15 | Missing or ambiguous recovery SHA/checkout identity | Ref-only, dirty, or non-independent identity fails closed before target mutation | #461 |
| A16 | Source revision unknown to selected checkout | Compatibility fails before target mutation | #461 |
| A17 | Source revision ahead/divergent or requiring downgrade | Compatibility fails before target mutation | #461 |
| A18 | Checkout HEAD or dirty state changes between compatibility verification and execution | Each occurring phase has its own immediate re-check; failure prevents restore write where possible and never migration/Start | #461 |
| A19 | Successful rehearsal identity binding | Evidence binds artifact/hash, producer SHA, source revisions, recovery SHA, checkout heads, accepted relationship, and readiness/schema/code identity | #461 |
| A20 | Owner-accepted plaintext synced filesystem mode | Exact plaintext pair publishes, verifies, and retains; protected mode stays unchanged; mismatched pairs and DR mode/artifact mismatches fail closed; no cloud-delivery claim | #527 |

## 9. Dependency-ordered implementation map

The child tasks are sequential and each starts from the exact internally
accepted predecessor candidate. #458 is the contract baseline and does not
implement runtime behavior.

1. **#458 / #417-A — contract (this ADR and runbook).** Freeze protection,
   managed artifact, retention, isolated recovery, privacy status, matrix, and
   owner gates.
2. **#459 / #417-B — managed publisher.** Implement the SQLite snapshot,
   destination validation, protected-state attestation, manifest/hashes,
   incomplete staging, atomic finalization, read-back, lock, and privacy-safe
   result. Depends on #458.
3. **#460 / #417-C — retention.** Retain the newest 12 verified managed
   recovery points, with no age-based expiry/deletion in v1, only after #459
   publication/read-back. Depends on #459.
4. **#461 / #417-D — isolated DR rehearsal.** Implement explicit recovery-SHA
   selection, producer/schema identity binding, pre-mutation compatibility and
   TOCTOU checks, isolated restore, structural/readiness checks, and
   privacy-safe rehearsal evidence over the #459 format and #460 retention
   contract. Depends on #459 and #460.
5. **#462 / #417-E — restore read-state regression.** Update the existing
   Export/Backup page to reload restored month state and add its focused
   frontend regression. It is interface-independent of the backend chain but
   is intentionally executed only after the backend chain stops or reaches its
   explicitly allowed gate.
6. **#527 / #417-H — plaintext synced filesystem mode.** Record one explicit
   Owner-accepted plaintext synced-filesystem pair. Keep the encrypted mode
   unchanged and fail closed on mismatched state/mode pairs. Retention keeps
   12 verified points per accepted pair.

Implementation and Owner-live acceptance are complete. #527 / PR #542 exact
candidate `720074dcc94954f7485b2e71762fff9cad5d9917` merged to canonical checkpoint
`744c613884d074e6f9d35d61523603f257371713`; exact-main CI #947 /
`36139627216` is SUCCESS. Publication, read-back and rehearsal checks stay
pair-bound; retention keeps the newest 12 verified points of the replacement's
exact pair even when both pairs share one directory. The fresh plaintext point,
off-device visibility confirmation and clean Owner DR rehearsal all passed on
2026-09-25, and parent #417 is closed completed.

## References

- #417 — Owner durability: protected off-site backup and disaster-recovery rehearsal
- #458 — freeze protected off-site backup and DR contract
- #459, #460, #461, #462 — dependency-ordered implementation children
- #527 — Owner-accepted plaintext synced-filesystem destination mode
- #543 — non-blocking post-closeout recovery hardening
- [`OWNER_DURABILITY_CLOSEOUT_2026-09-25.md`](../OWNER_DURABILITY_CLOSEOUT_2026-09-25.md)
- [`MASTER_SPEC.md`](../MASTER_SPEC.md)
- [`OWNER_RUNTIME_OPERATIONS.md`](../OWNER_RUNTIME_OPERATIONS.md)
- [ADR 0004](0004-localhost-request-security.md)
- [ADR 0012](0012-runtime-and-agent-workspace-isolation.md)
- [ADR 0014](0014-launcher-runtime-profile-safety.md)
