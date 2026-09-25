# Hermes Finance — Owner durability closeout — 2026-09-25

## Result

Owner durability parent #417 is **complete**.

Canonical runtime/durability checkpoint:

`744c613884d074e6f9d35d61523603f257371713`

Verification:
- #527 / PR #542 accepted exact candidate: `720074dcc94954f7485b2e71762fff9cad5d9917`;
- independent security/recovery re-review: **ACCEPT**;
- exact-head CI #946 / `36127808612`: **SUCCESS**;
- exact-main CI #947 / `36139627216`: **SUCCESS**;
- parent #417: **closed / completed**.

Published Stable remains immutable **v1.0.0** at `caf4fdad99cc02f5bc171ec3b1d726b8516ad45e`. This closeout records accepted post-release durability work on development `main`; it does not change the Stable release identity.

## Accepted Owner policy

The Owner explicitly accepted ordinary synced-folder plaintext-at-rest storage for the current Finance off-device recovery workflow.

Canonical plaintext pair:

```text
protection_state=owner_accepted_plaintext
protection_mode=synced_filesystem_destination_v1
destination_alias=synced-filesystem-destination
```

This mode is **not encrypted** and is **not protected-at-rest**. Hermes proves local publication and destination read-back only; it does not claim Google or other provider delivery.

The existing encrypted pair remains available only for a genuinely encrypted destination:

```text
protection_state=protected
protection_mode=external_encrypted_destination_v1
```

Existing protected artifacts are not retroactively reclassified.

## Canonical behavior

The accepted recovery chain now provides:

- consistent SQLite online snapshot creation;
- integrity, foreign-key, schema/migration and deterministic manifest/hash verification;
- destination-local incomplete staging followed by atomic final exposure;
- final destination read-back before `published=true`;
- exact state/mode pair binding across publication, verification, retention and DR;
- bounded retention of the newest 12 verified managed points **per accepted protection pair**;
- object-bound destructive retention checks and fail-closed TOCTOU handling;
- immutable source verification throughout DR;
- fresh isolated target/profile/data/database requirements;
- exact recovery checkout identity and schema-compatibility gating;
- Prepare/Validate/Start/readiness verification over restored data;
- privacy-safe output only;
- no Google API/OAuth/cloud account/background upload architecture.

## Owner-live evidence

### 1. Fresh recovery publication — PASS

A fresh recovery point was published into the Owner-selected ordinary synced filesystem destination with:

- `status=published`;
- `created=true`;
- `verified=true`;
- `published=true`;
- `read_back=verified`;
- `retention=completed`;
- `action_required=null`;
- `protection_state=owner_accepted_plaintext`;
- `protection_mode=synced_filesystem_destination_v1`.

Exactly one new managed recovery point appeared in the destination.

### 2. Off-device visibility — PASS

The Owner independently confirmed that the exact newly published artifact was visible through Google Drive from another device.

This is Owner evidence of off-device visibility. Hermes itself does not make a cloud-delivery claim.

### 3. Clean isolated disaster-recovery rehearsal — PASS

The final rehearsal used the fresh plaintext artifact, canonical recovery code `744c613884d074e6f9d35d61523603f257371713`, an independent clean checkout and a completely fresh isolated target.

Privacy-safe result:

- `status=rehearsed`;
- `source_verified=true`;
- `source_unchanged=true`;
- `restored=true`;
- `prepared=true`;
- `validated=true`;
- `readiness=verified`;
- `action_required=null`;
- producer SHA = selected recovery SHA = `744c613884d074e6f9d35d61523603f257371713`;
- `schema_relationship=same_revision`;
- source/resulting Alembic revision = `0041_debt_linked_account`.

Broad non-private restored structure:
- reporting months: 8;
- user tables: 43;
- populated user tables: 25;
- user indexes: 25;
- user views: 0.

No financial values, account identifiers, private filesystem paths, credentials or recovery payloads are recorded here.

## Real defects found by Owner rehearsal

The live rehearsal was useful because it found defects that synthetic acceptance had not exposed.

### #511 / PR #518

Windows PowerShell 5.1 singleton JSON handling could wrap a one-month response such that the readiness flow failed before the dashboard request. The fix normalized the month handoff and added focused regression coverage.

Canonical fix checkpoint before the next rehearsal: `e24c7ce07ef110741d6730fa06642c5e43bd84c7`, exact-main CI #927 / `36000791353` SUCCESS.

### #524 / PR #525

Recovery readiness checked ownership and then took a second listener/process snapshot for classification. During startup the state could transition between those observations, producing a null classification and `readiness_probe_defect`. The fix uses one bounded classification path, handles the absent-listener startup case, and adds real Windows Job/recovery-boundary coverage.

Canonical fix checkpoint: `f328c82b6c7c3af0f6cd436c7e1d408bb54a8885`, exact-main CI #939 / `36099486848` SUCCESS.

## Final #527 hardening

Independent review of the plaintext-mode change found and drove fixes for:

- truthful mode-specific retention failure output;
- neutral crossed-pair CLI failure identity;
- retention isolation between protected and plaintext artifacts in the same directory;
- mandatory mode-specific retention action.

Final mixed-mode contract: each accepted pair keeps its own newest 12 verified points; one mode never deletes the other mode's verified artifacts.

## Follow-up

#543 remains open as **non-blocking post-closeout hardening**:

- neutral identity for argparse-level failures before a valid pair is parsed;
- an explicit repository regression for the full 12 protected + 12 plaintext + 13th same-pair deletion scenario;
- continued documentation of pair-scoped verified listing if that helper becomes production-facing.

#543 does not reopen #417 and is not required to trust the proven recovery workflow.

## Operational conclusion

The recovery workflow is no longer only synthetic evidence. The Owner has proven the actual chain:

```text
production SQLite
→ verified managed recovery point
→ ordinary synced Google Drive folder
→ independent off-device visibility
→ fresh isolated restore
→ exact supported runtime
→ readiness verified
```

Future rehearsals must continue to use a fresh recovery point and a completely fresh isolated target. Failed mutated rehearsal targets must never be reused as acceptance evidence.

## References

- #417 — Owner durability parent — completed
- #459 / PR #466 — publisher
- #460 / PR #473 — retention
- #461 / PR #483 and PR #499 — isolated DR + Windows cleanup
- #462 / PR #502 — post-restore read-state
- #475 / PR #477 — restore outcome truthfulness
- #511 / PR #518 — singleton-month readiness fix
- #524 / PR #525 — Windows readiness ownership TOCTOU fix
- #527 / PR #542 — Owner-accepted plaintext synced mode
- #543 — post-closeout hardening
- `docs/adr/0017-protected-offsite-backup-and-recovery.md`
- `docs/OWNER_RUNTIME_OPERATIONS.md`
