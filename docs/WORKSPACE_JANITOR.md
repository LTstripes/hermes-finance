# Finance workspace janitor

The disposable-workspace janitor reuses the accepted Health-Check #256 contract and implementation (PR #259, `39223e6fff80b5f12c4b4c9d6d973e665362ff82`). Finance changes only repository identity, namespace, installation-relative paths and removal of the Health-specific photo-source allowance.

## Current deployment — completed 2026-10-03

PR #685 candidate `88f0564f9244ae23ba86b281cacbba75074b03c6` was merged at `8eb991fc81ebbe63917a9ca1ea204762129c9019`. Exact PR CI `37149756455` and canonical main CI `37150791634` succeeded. The [Owner-local closeout](https://github.com/LTstripes/hermes-finance/issues/679#issuecomment-5973182455) reports the installed task **Hermes Finance workspace cleanup** Enabled/Ready, daily 12:00 local, Apply with 7-day retention, Owner Interactive/Limited, IgnoreNew and StartWhenAvailable. The next run recorded at deployment was 2026-10-04 12:00 Europe/Moscow; this is a historical scheduled time, not a live task read-back.

One post-deployment dry-run completed with exit 0: **8 PRESERVE / 0 deletions**, seven private-marker reasons and one filesystem/check-unknown. It did not demonstrate a first automatic deletion. Future scheduled results belong in the bounded local report. Do not report PRESERVE as a failed run or promise every completed workspace disappears after exactly seven days.

## Installation boundary — KEEP

Install the two `scripts/cleanup-workspaces.*` files together under `<Finance container>/ops/workspace-cleanup/`. The script derives the four fixed roots under `Hermes/workspaces/{codex,opencode,grok,hermes}` from that installation location. It cannot accept arbitrary roots. Stable, Main, Test and Owner are outside the allowlist. The bounded structural report is `ops/workspace-cleanup-latest.json`; it never includes private contents or raw process/Git diagnostics.

**The deployed Ops directory is active and protected even though it is outside the Hermes role root. Do not delete or relocate it during ad-hoc tidying.** Do not move the installed scripts under `Hermes/owner` without a separately reviewed adjustment of installation-relative scope and task action. [Machine layout](OWNER_MACHINE_LAYOUT.md) owns the role map; local absolute values remain in Owner configuration.

Schedule Windows PowerShell daily at 12:00 in the Owner interactive, limited context, using `-NoLogo -NoProfile -ExecutionPolicy Bypass -File <installed script> -Apply -RetentionDays 7`. Set `MultipleInstances=IgnoreNew` and `StartWhenAvailable=true`. No service, daemon, remote branch deletion or runtime operations are involved. After a future deployment/change run once without `-Apply` and read back the registered task and structural report. The already accepted deployment does not need repeating for a documentation update.

## Eligibility and failure handling

Dry-run is the default. Both modes require fresh local-origin tracking evidence when a candidate reaches the remote check. Preserve active, young, dirty/untracked, wrong-origin, private, reparse/aliased, external Git metadata, unknown ignored material or unpublished/unique local history. Successful bounded process enumeration checks all visible workspace-path matches; unrelated unavailable command lines are a bounded diagnostic count. Failed enumeration preserves candidates. Deletion failure stops the run.

Recognized ignored, untracked generated caches follow the unchanged accepted cache proof. Unknown Finance dependency/build folders remain preserved; no broad cache exception is introduced. Standalone clones use handle-bound deletion; registered worktrees use non-force Git removal. Synthetic Windows coverage is `scripts/tests/test-cleanup-workspaces.ps1` and runs in the existing Windows Release safety CI job.

The one-time #679 permission to discard identified old technical forests/local-only history does not weaken this recurring janitor's conservative eligibility. The Python offline inventory and frozen-plan cleanup CLI are separate tools, not the scheduled task. Do not substitute their historic output or approval for a current janitor decision.
