# Owner machine layout — inventory/design, phase 1 (#666)

This page owns the portable layout proposal. Real root mappings and local folder
labels live in an **Owner-local registry outside Git and all agent workspaces**.
No relocation, cleanup, launcher installation or profile change is implemented
or authorized by this phase. Existing [runtime operations](OWNER_RUNTIME_OPERATIONS.md),
[ADR 0012](adr/0012-runtime-and-agent-workspace-isolation.md) and
[ADR 0014](adr/0014-launcher-runtime-profile-safety.md) remain authoritative.

## Proposed boundaries

```text
<HERMES_ROOT>/
  stable/                 KEEP — Owner production, published immutable release
    code/                 independent clone, pinned release SHA
    data/                 Owner-only DB, sidecars, backups and secrets
  control/                KEEP — clean trusted canonical main code; no Owner DB
  preview/                KEEP — one dedicated exact-SHA Owner UAT runtime
    code/                 independent clone, pinned candidate SHA
    data/                 Owner-only isolated data, kind=preview
  workspaces/             per-client/per-task code; never Owner runtime/data
    <client>/<task>/       one active task owns one physical clone/worktree
```

These are placeholders, not current machine paths. Prefer sibling code/data
boundaries, but do not change current checkout-relative settings in phase 1.
Any later external-data configuration must use supported runtime operations and
prove its boundary before Start. Never connect data using junctions, symlinks or
hardlinks. Stable stays separate from Control and Preview; development main
does not become Stable. A completed task does not authorize subtree cleanup.

## Owner inventory command

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
