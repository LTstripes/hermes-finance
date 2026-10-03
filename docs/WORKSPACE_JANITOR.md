# Finance workspace janitor

The disposable-workspace janitor reuses the accepted Health-Check #256 contract and implementation (PR #259, `39223e6fff80b5f12c4b4c9d6d973e665362ff82`). Finance changes only repository identity, namespace, installation-relative paths and removal of the Health-specific photo-source allowance.

Install the two `scripts/cleanup-workspaces.*` files together under `<Finance container>/ops/workspace-cleanup/`. The script derives the four fixed roots under `Hermes/workspaces/{codex,opencode,grok,hermes}` from that installation location. It cannot accept arbitrary roots. Stable, Main, Test and Owner are outside the allowlist. The bounded structural report is `ops/workspace-cleanup-latest.json`; it never includes private contents or raw process/Git diagnostics.

Schedule Windows PowerShell daily at 12:00 in the Owner interactive, limited context, using `-NoLogo -NoProfile -ExecutionPolicy Bypass -File <installed script> -Apply -RetentionDays 7`. Set `MultipleInstances=IgnoreNew` and `StartWhenAvailable=true`. No service, daemon, remote branch deletion or runtime operations are involved. After deployment run once without `-Apply` and read back the registered task and structural report.

Dry-run is the default. Both modes require fresh local-origin tracking evidence when a candidate reaches the remote check. Preserve active, young, dirty/untracked, wrong-origin, private, reparse/aliased, external Git metadata, unknown ignored material or unpublished/unique local history. Successful bounded process enumeration checks all visible workspace-path matches; unrelated unavailable command lines are a bounded diagnostic count. Failed enumeration preserves candidates. Deletion failure stops the run.

Recognized ignored, untracked generated caches follow the unchanged accepted cache proof. Unknown Finance dependency/build folders remain preserved; no broad cache exception is introduced. Standalone clones use handle-bound deletion; registered worktrees use non-force Git removal. Synthetic Windows coverage is `scripts/tests/test-cleanup-workspaces.ps1` and runs in the existing Windows Release safety CI job.
