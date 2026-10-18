# Recoverable workspace relocation — unapplied Finance proposal

This Finance candidate reuses the narrow container-relocation contract accepted in
Health-Check #447. It includes the previously prepared lifecycle/worker prerequisites
that were absent from Finance canonical main, rather than enabling the legacy Apply
janitor. Finance requires its own independent review, exact PR/main CI, matched
installation, synthetic restore and fresh Scan before task activation.

Retirement moves the same verified root container with actual contents to a fixed
same-volume recovery folder. It is not a snapshot, backup or free-space reclamation.
No Shell, permanent deletion, purge, automatic restore or copy/delete fallback.

Existing clean/publication/private/process/standalone-clone guards, explicit
completion and seven days since both completion and activity remain. Active,
paused, unknown, legacy, dirty, unpublished and shared worktrees preserve. Runtime,
Stable/Test/UAT/Owner/Ops/staging/backups/recovery remain outside the fixed allowlist.

The existing FinanceDirectory installation derivation, four client roots, origin
and Global\HermesFinance.WorkspaceCleanup mutex are retained. The fixed recovery
root is FinanceDirectory/recovery/workspaces; no arbitrary CLI destination exists.
Root/ancestor handles and project mutex remain held. Descendant handles release
only after durable intent and v2 retiring state. Rename uses the checked root
handle on the same fixed local NTFS volume and never replaces a destination.

Bounded no-follow observation retains root DELETE binding before enumeration.
Manifests say NonSnapshot=true and contain metadata, not content hashes or an
atomic snapshot. Detected changes, reparse/private material, bounds, unexpected
old-path occupants and uncertain outcomes become durable NEEDS_REVIEW. Preserve
both objects; no automatic retry, restore, Resume, cleanup or purge follows.

Claims remain format1 for workers. Retirement format2 adds Transaction and blocked
retiring/retired/restoring/needs_review states, rejected by old readers. The journal
is strict ordered format2 with root/Git/enrollment/claim/generation, fixed destination,
before/after metadata digests and observation references. Prepared intent survives
crash; explicit Recover reconciles fixed locations without repeating moves.
Closed journal alone cannot admit an old completed record: the new paused claim
must be committed, or a later legitimate generation must exist.

Explicit Restore verifies the root and current observation, writes intent, performs
no-replace reverse rename to a vacant original path, inspects again and returns a
fresh paused claim. Changed/uncertain outcomes preserve NEEDS_REVIEW. Work requires
the separate Resume and CheckActive transitions. There is no adoption/override.

The consumer keeps bounds of 200 tasks, 25000 entries per task, depth128, 4MiB per
observation and 8KiB per journal/claim. Scan remains default and may fetch eligible
completed candidates, writing local Git metadata. Apply is refused; Retire moves.

Before Finance acceptance, run scripts/tests/test-cleanup-workspaces.ps1 in WinPS5.1
using only synthetic roots. This existing Finance CI entrypoint now invokes
test-workspace-retirement.ps1 in a separate child after the full guards; FixtureOnly
setup does not recurse. Validate that chain in Finance exact CI and retain evidence.
The Health workflow is not copied over Finance CI. An apply-check is not acceptance.

Do not install this patch, create recovery folders, change runtime, merge or register
schedules until Finance Integrator acceptance. Thereafter deploy matching readers
together with schedules disabled, verify synthetic restore and review a fresh Scan
before independently approved hidden Interactive/Limited daily Retire scheduling.
Stop future invocations for rollback, retain all records and containers, and never
restore an old automatic janitor that ignores retirement claims.

## New managed worker checkouts

The installed matched helper exposes Invoke-WorkerLifecycle. A task assignment
supplies the configured client root, one new sanitized child, a unique owner and
the current local Claim. Dot-source the installed helper, then use Create before
clone, Bind after clone, and CheckActive before writes/tests/delivery. Pause retains
ownership. Resume returns a new Claim/generation: persist it locally and CheckActive
before continuing. Complete only after actual task delivery; completion is never
inferred from timestamps, directory age, Git cleanliness or a closed PR.

Create/Bind is for new checkouts only. No enrollment, adoption, backdating, state
reset or override exists for legacy or ambiguous folders. Claims are local authority:
never commit or publish them. Existing unregistered workspaces remain PRESERVE.
Without an accepted configured helper, follow the existing fresh uniquely named
checkout fallback from OWNER_DATA_WORKFLOW; that fallback does not enroll it.

## Deployment and scheduler

Install both files together under the existing container-relative ops/workspace-cleanup
location with verified rollback and future invocations stopped. Preserve normal user
rights, current execution policy, ACLs and credentials. Do not start/restart Finance.
Validate one installed-pair synthetic roundtrip, then run Scan without Retire and
review every record. The independent daily task uses the current logged-in user,
InteractiveToken/Limited, hidden WinPS5.1, IgnoreNew and StartWhenAvailable with
`-Operation Scan -Retire -RetentionDays 7`. No ExecutionPolicy override is required.

Recovery is a separate fixed same-volume directory; it is never a scan root.
Relocation does not free space. Stop future invocations to roll back and preserve
all containers/claims/journals. After a v2 transaction, retain a compatible accepted
reader; never restore an old automatic deletion job. Explicit Recover/Restore is a
separate operational decision and never a scheduled retry or purge.
