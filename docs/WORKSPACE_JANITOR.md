# Finance workspace janitor

## Current contract

The automatic consumer uses [recoverable workspace relocation](WORKSPACE_RETIREMENT.md).
It includes explicit managed lifecycle/worker enrollment for new standalone clones.
Scan is the default; Apply is refused. Retire relocates the same verified physical
root container with its actual contents to fixed recovery storage, without deletion,
Shell, copy/delete fallback, automatic restore or purge. It is not a snapshot or
backup and does not free disk space.

Only explicit completed managed checkouts can become eligible, after at least seven
days since both completion and relevant activity and all clean/publication/private/
process/root/cache guards. Active, paused, unknown, legacy, dirty, unpublished and
shared worktrees remain PRESERVE. Do not adopt or backdate old folders.

Install the two scripts/cleanup-workspaces.* files together under the existing
container-relative ops/workspace-cleanup location. The script derives only the four
fixed Hermes/workspaces/{codex,opencode,grok,hermes} roots, Ops and recovery/workspaces
from that installation. Main, Stable, Test/UAT, Owner, staging, backups, runtime,
Ops and recovery are excluded. Do not relocate Ops or change its ACLs/security.

After exact project acceptance and matched installation/rollback, validate synthetic
restore and review a fresh Scan. A separately authorized daily task uses the logged-in
Owner Interactive/Limited context, hidden WinPS5.1, IgnoreNew, StartWhenAvailable,
Operation Scan, Retire and RetentionDays 7. Keep existing execution policy and
credentials; do not add an ExecutionPolicy override. No Finance runtime operations
or automatic classification of old tasks are involved.

The bounded structural latest report remains ops/workspace-cleanup-latest.json.
It never includes private contents or raw process/Git diagnostics. Scan may fetch
local-origin metadata for completed candidates; it is not strictly read-only.
Changed or uncertain relocation outcomes become NEEDS_REVIEW and preserve their
containers and journals, without automatic retry/restore/Resume/purge.

The existing Windows Release safety CI entrypoint scripts/tests/test-cleanup-workspaces.ps1
now runs the focused retirement regressions in a separate child after the full guards;
FixtureOnly initialization does not recurse. Retain the exact source/evidence scope
and do not replace missing Finance CI with Health evidence.

## Historical deployment

The 2026-10-03 #685 deployment at 8eb991fc81ebbe63917a9ca1ea204762129c9019,
its old Apply task and next-run time belong to the historical
[Owner-local closeout](https://github.com/LTstripes/hermes-finance/issues/679#issuecomment-5973182455).
They are not current task readback or authority to enable permanent deletion.
The historical post-deployment dry-run reported eight preserved objects; no first
automatic deletion was demonstrated. Do not rerun closed #679/#666 cleanup batches.
The separate [Python frozen-plan tool](OWNER_WORKSPACE_CLEANUP.md) is not this task.
