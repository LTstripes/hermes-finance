# Hermes Finance v1.0.0 release closeout — 2026-09-21

## Status

**PUBLISHED / OWNER OPS03 PASS / REAL STABLE PASS**

## Canonical release identity

- release: `v1.0.0`;
- exact Owner-OPS03-tested/released SHA: `caf4fdad99cc02f5bc171ec3b1d726b8516ad45e`;
- annotated tag object: `f99ee8ecac1acde7f559d92ee8f45ddcfcdfaa47`;
- tag peels exactly to the released SHA;
- exact-main candidate CI #880 / `35579583692`: SUCCESS;
- Guarded Release run `35580890145`: SUCCESS;
- GitHub Release: `Hermes Finance 1.0.0`, published, non-draft, non-prerelease.

## Owner acceptance chain

### OPS03 isolated Preview/UAT — PASS

Owner tested exact `caf4fdad99cc02f5bc171ec3b1d726b8516ad45e` against isolated copied owner data before publication.

### Guarded publication — PASS

The repository-owned #124 flow published the annotated `v1.0.0` tag and GitHub Release from the same exact Owner-tested SHA.

### OPS02 real Stable transition — PASS

Owner then completed the backup-first Stable transition:

`v0.9.0 -> v1.0.0`

### Production Start / data continuity — PASS

Owner explicitly reported **PASS Stable** after starting real Stable on the production database.

This is the acceptance boundary that matters operationally: the cohesive UI v2 release is not only canonical in GitHub; it is now running against the owner's real working data.

## Included product milestone

- UI v2 primary at `/`;
- previous UI rollback at `/v1`;
- complete Home / Capital / Income & Plans / Reports / Monthly Close / Data-App experience;
- truthful ambiguous restore-result semantics;
- protected recovery-point publisher;
- bounded verified retention;
- proven exact-SHA UAT / guarded publication / backup-first Stable update lifecycle.

## Separate remaining work

- #461 isolated DR rehearsal;
- #462 legacy Export/Backup restored-month state reload;
- #476 real-backend G04 browser CI gate;
- future configurable dashboards #389;
- any later v1-retirement decision.

## Privacy boundary

No production database bytes, backup identifiers, credentials, paths with private payloads or financial values are recorded in this closeout.

## Metadata note

The GitHub Release body was produced from the pre-publication notes and retains future-tense candidate/OPS03 wording in its final section. The immutable tag/released commit are correct; canonical repository docs now record the final lifecycle state.
