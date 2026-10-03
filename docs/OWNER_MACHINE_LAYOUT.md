# Owner machine layout — inventory and cleanup planning (#666)

This page owns the portable layout contract. Real root mappings and local folder
labels live in an **Owner-local registry outside Git and all agent workspaces**.
The inventory remains permanently read-only. The separate cleanup command below
requires exact-plan Owner approval; no real-machine deletion or relocation is
authorized by delivering it. Existing [runtime operations](OWNER_RUNTIME_OPERATIONS.md),
[ADR 0012](adr/0012-runtime-and-agent-workspace-isolation.md) and
[ADR 0014](adr/0014-launcher-runtime-profile-safety.md) remain authoritative.

## Owner-authorized final boundaries (#679)

```text
<HERMES_ROOT>/
  stable/                 KEEP — Owner production, published immutable release
    backend/, frontend/   existing whole checkout, pinned release SHA
    data/                 preserved Owner DB, sidecars, backups and secrets
  main/                   clean trusted canonical main checkout; no Owner DB
  test/                   one persistent reusable exact-SHA Owner UAT runtime
    backend/, frontend/   selected UAT checkout; refresh here for future UAT
    data/                 preserved isolated test data, kind=preview
  owner/                  KEEP — local registry, manifests, recovery and journals
  workspaces/             per-client/per-task code; never Owner runtime/data
    codex/<task>/         one active task owns one physical clone/worktree
    opencode/<task>/
    grok/<task>/
    hermes/<task>/
```

## Shared client workspace contract

Codex, OpenCode, Grok and Hermes each use an Owner-configured machine-local root below the logical `workspaces/<client>/` boundary. The concrete root mapping belongs in local client configuration, not Git. Every writing/local-verification task creates one `<issue>-<slug>` directory under its own client root.

A client writes only its assigned task directory. Another client's physical workspace is not a shared source tree: inspect its delivered work through GitHub PRs/remote refs, or use an explicitly assigned independent review clone/path. Stable, Control and Preview are never client workspace roots.

These are portable labels; actual machine paths remain Owner-local. Control
is the role of `main`, and Preview is the role of `test`. Keep existing
checkout-relative runtime data bindings during whole-directory relocation.
Any later external-data configuration must use supported runtime operations and
prove its boundary before Start. Never connect data using junctions, symlinks or
hardlinks. Stable stays separate from Control and Preview; development main
does not become Stable. A completed task does not authorize subtree cleanup.

## Owner inventory command

For an explicitly launched Owner-local operational assignment such as #679,
the assigned Worker runs bounded structural preparation through local helpers
and generates every registry/configuration batch. The manual sequence below
remains available but is not an Owner prerequisite for that assignment.
Historical registries locate boundaries only: refresh identities, pins,
ownership, artifacts and remote preservation before proposing eligibility.
Unresolved ownership remains ACTIVE/UNKNOWN; no historical `active=false`
or `artifacts_resolved=true` is fresh clearance. Keep full path mappings and
helper outputs in protected Owner-local storage; return sanitized evidence only.

Only the Owner runs this on the real machine. Agents develop and test with
synthetic fixtures; they must not run it against Owner paths or receive the
registry, local-path report, filenames, financial values, secrets or exports.

1. Create a local JSON registry following
   [the schema](schemas/owner-workspace-registry.schema.json). List each known
   checkout explicitly; workspace roots are boundaries, not recursive discovery
   requests. Register uncertain paths as `unknown`. Include old layouts in this
   list so they are not lost during the later migration proposal.
2. Use local, physically separate directories. `path` is a checkout;
   `data_path` is its declared Owner data directory. Roots/entries must not overlap
   other roles. A runtime may contain its own data directory. `expected_sha` is an
   independently selected exact SHA. For Stable, also record `release_tag` and
   verify its published immutable release separately. The tool does not query
   releases, read profiles/.env/sidecars or prove database continuity.
3. Set workspace `active` only after checking all clients/processes. Omission
   means active. `artifacts_resolved` records an Owner decision about required
   reports/evidence; it does not override unknown Git or filesystem state.
4. From trusted Control, using an existing Python 3.12+ and Git installation:

   ```powershell
   & $Python -B "$CONTROL_CHECKOUT/scripts/owner_workspace_inventory.py" `
     --registry $OWNER_LAYOUT_REGISTRY
   ```

   Variables contain local paths selected by the Owner; there is no default scan
   root. Default stdout is a shareable summary: numbered entries, declared role,
   sanitized Git identity/flags and approximate logical byte counts. It contains
   no absolute paths, arbitrary branch names, origin URLs, filenames or exception
   text. Entry numbers correspond to registry order. Keep registry order locally.

   For Owner-only path mapping add `--local-paths`. Keep that output in Owner
   storage; never paste/upload it or place it in Git/agent artifacts. The command
   writes only stdout. Any redirection destination is chosen by the Owner.

The command reads registry and plain Git configuration/metadata. Directory
enumeration/stat supplies size and private-marker flags without opening file
contents. Independent Git identities are read offline. Worktree pointers are
reported without following their external Git directory. Includes, filters,
external Git config/object stores, reparse points and hardlinks make Git evidence
unavailable. Git errors are discarded. No fetch, profile execution, data/sidecar
read, DB open, file copy, move or delete occurs. No application modules are imported.

`dirty` uses content-based Git status **only for a workspace whose entire scan
is complete and has no private markers/indirection**. Runtime dirty-state is
`unknown`, so even a tracked private file is not hashed. Common private names
are a guard, not proof that arbitrary renamed content is public: Owner must
register code-only workspaces. Run against quiescent directories; metadata and
Git observations are snapshots, not a lock or deletion proof. A concurrently
changed path must be reinventoried before any future action.

Disk bytes are logical file sizes (including Git/dependencies/data metadata),
not allocated/reclaimable space. Separate data may also appear in checkout
counts when nested; **do not sum those two counts**. A bounded, unreachable or
aliased scan has `complete=false`; its byte count is a lower bound.

`unique_commits_to_cached_remotes` includes all local refs, including branches,
tags and stash, compared with existing remote-tracking refs. No remotes means
unknown. False does not prove remote freshness, pushed evidence or preservation
of reflog/dangling work. Registry `release_tag`/SHA are declarations, not proof
of publication or runtime/profile kind. `identity_matches_pin` compares HEAD
only. The Owner verifies release/profile/data provenance through existing flows.

## Classification and cleanup proposal

| Output | Meaning / next decision |
| --- | --- |
| KEEP | Declared Stable/Control/Preview. Preserve even if missing or mismatched. |
| ACTIVE WORKSPACE | Active, or ownership unresolved. Preserve. |
| UNKNOWN | Unclassified/inactive workspace, unreachable path, ambiguous filesystem/Git or incomplete evidence. Preserve pending Owner decision. |
| SAFE-TO-REMOVE candidate | Reserved for a later separately approved manifest; this offline command never emits it. |

The tool deliberately cannot clear cleanup from stale remote refs or folder
names. For a later individual candidate: resolve active ownership, required
artifacts and dirty/untracked/ignored work; verify every unique local ref and
uncommitted/reflog work is pushed/merged or intentionally preserved; obtain fresh
canonical remote evidence; prove plain disjoint code/data boundaries; record
exact path and HEAD in a proposed manifest. Owner/Integrator approves that exact
group. No blanket authorization for the whole workspaces subtree follows.

## Migration/backup/rollback manifest for separate approval

The bounded cleanup-plan/apply phase is described in
[Owner workspace cleanup](OWNER_WORKSPACE_CLEANUP.md). It uses a separate
command and exact-plan approval; the inventory classifier above is unchanged.

After Owner inventory, fill this **locally**, without sharing paths/data:

| Boundary | Required manifest fields |
| --- | --- |
| Stable code | current/proposed path; published release/tag object and peeled SHA; clean code identity; supported preparation proof; stop/start plan |
| Stable data | current/proposed directory and DB; production identity; verified backup and restore proof; sidecars/secrets retained Owner-locally; DB continuity assertions |
| Control | current/proposed path; origin/main SHA; clean trusted independent Git directory; no Owner data |
| Preview | current/proposed code/data; exact candidate SHA; kind=preview and physical DB isolation; explicit UAT-copy provenance; required retained UAT artifacts |
| Workspace roots | current/proposed per-client roots; active task mappings; preserved unpushed/dirty/artifact work; individually proposed retired paths |
| References | every affected supported runtime/profile/config/shortcut/client reference; before/after local values; no guessed or omitted references |

Execution order proposal: approve exact manifest and backup/restore evidence;
stop Owner runtimes and freeze task ownership; prove source/destination file
identities, free space and no indirection; use approved supported relocation
steps; update only approved local references; Validate/Prepare/Start Stable with
release/production-data continuity; prepare exact Preview and prove isolation;
validate Control and one synthetic task in each client root. Owner approves
path/UAT results before retiring any source. Local labels such as `KEEP STABLE`
or `TASK CODE — CHECK GIT BEFORE CLEANUP` are proposed Owner files, not written
by this tool.

Rollback manifest: preserved original code SHA/data/config mappings, verified
production backup and restoration procedure, stop condition for any mismatch,
and Owner-controlled reversal steps. Preserve sources/backups until the Owner
accepts the new runtime/data continuity. Never copy Preview data back to Stable.
Launcher removal #629, other-client reconfiguration and migration execution
remain separate work. This delivery supplies the template, not real-machine
inventory or an executable migration.

## Explicit operational continuation (#679)

The authoritative [Owner clarification](https://github.com/LTstripes/hermes-finance/issues/679#issuecomment-5972086820)
supersedes the earlier preservation-heavy legacy cleanup assumptions and
additional package approval round for its explicitly named moves/deletions.
The Owner directly authorized the Worker to execute that migration. Old named
Hermes task/recovery/benchmark forests and their local-only commits need no
preservation. This authorization does not widen the generic plan/apply CLI or
allow traversal through reparse targets. Already configured new client roots
are left in place. Busy individual deletion paths are recorded while other
authorized cleanup continues.

Move the existing Stable whole, preserve its exact published source and DB,
then move Control to `main` and fast-forward it to canonical origin/main, and
move Preview to persistent `test` with physically separate data. A moved
Windows Python environment can retain absolute interpreter paths in console
entry points. Recreate it with the release's supported locked runtime Prepare
at its destination before Start; do not blindly reuse those launchers. Keep
the previous environment available for rollback until readiness succeeds.
Verify DB identity/content and schema continuity before/after preparation and
Start. If Stable Start fails, roll Stable back and stop before legacy deletion.

The local Launcher is deprecated for this assignment: remove its old installed
artifacts/shortcuts/references without repairing or testing it. Repository
source retirement remains #629; Stable's exact release source is preserved.
One verified supported Stable backup is sufficient when DB identity is
unchanged. Reuse existing restore/rollback/review evidence rather than repeat
it solely for this migration. Concrete completion, failed paths and reclaimed
space are recorded in #679/#666 and the Owner-local execution report.

The following preparation contract describes the earlier checkpoint. It still
governs generic package operations, but adds no extra approval gate to the
Owner-authorized exact migration above.

The #679 assignment supersedes the earlier manual-Owner execution split only
for its directly launched local Worker. That Worker prepares the source/target
mapping, references, preserved pins, recovery/restore evidence, dependency
order, rollback and cleanup groups as one local package. Use existing runtime
and cleanup primitives; delivering a helper or draft PR is not a completed
migration. New executable tooling needs independent review and Integrator
acceptance before live apply.

ACTIVE tasks stay at their current paths. Start new client roots clean; retain
old Git parents with unresolved dependents. Preserve checkout-relative data
bindings where sibling code/data separation lacks supported operations.
Stable remains at its published release, Preview at its selected exact UAT
pin. Neither migration nor a launcher reference correction promotes a version.

Before any move/delete, runtime stop or existing-client reconfiguration, show
one independently reviewed package with exact local MOVE/REMOVE/KEEP/HOLD
lists, reference changes, recovery/restore and rollback proof, package digest
and validity window. The Owner approves that package once in chat; the Worker
executes it and reports actual results. No manual JSON or PowerShell is required
from the Owner. Preserve expiry/replay/identity guards and stop/refreeze on
changed evidence; never silently refresh an approved digest. A blocked review,
unproved restore or incomplete reference map prevents READY_FOR_APPROVAL.

The small `scripts/owner_machine_relocation.py` primitive performs one
same-volume Windows rename using the cleanup tool's existing ancestor/source
identity guards and a source handle. It refuses replacement and busy or changed
boundaries; it supplies no CLI or implicit relocation authority. The operational
caller still owns the reviewed package digest, expiry/replay check, quiescence,
reference snapshots and readiness checks. Reverse moves use the same directory
identity after restoring reference bytes. Synthetic tests cover a failure after
move/reference update, destination collision and an open SQLite connection;
the Windows production CI lane runs them explicitly.
