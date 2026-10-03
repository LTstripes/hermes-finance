# Owner-local workspace cleanup — plan/apply (#666)

Only the Owner runs this command on real paths. Agents use synthetic fixtures.
Keep populated configuration, frozen plans and journals outside Git, runtime
trees and all agent workspaces. Do not upload them: they contain local paths.
The [inventory command](OWNER_MACHINE_LAYOUT.md#owner-inventory-command) remains
read-only forever. This command implements no scheduler or runtime migration.

Create an Owner-local JSON configuration with these fields (all paths are
absolute local fixed-disk paths selected by the Owner, never template literals):

| Field | Meaning |
| --- | --- |
| `version` | Integer `1` |
| `owner_root` | Protected Owner container; never a target |
| `stable`, `control`, `preview` | Mandatory protected checkout/runtime boundaries, including their data children |
| `workspace_roots` | Array of configured per-client task roots; pairwise disjoint from each other and protected boundaries |
| `entries` | Up to 64 explicit entries, each with `path` and `role` (`workspace`, `unknown`, `stable`, `control`, `preview`) |
| Entry `active`, `artifacts_resolved` | Only explicit `false` / `true` permit evaluation; refresh ownership across clients/processes before planning and applying |
| Entry `git_dir`, `git_common_dir` | Required only for linked worktrees: exact own registration directory and trusted Control's `.git` |

The configuration is intentionally separate from the phase-1 inventory registry.
Targets must be immediate task children of a configured root. Unknown, active,
out-of-boundary or unresolved entries are HOLD without content inspection.
Protected paths and workspace roots themselves are impossible targets. Legacy
linked worktrees hosted anywhere except trusted Control remain HOLD; migrate
or preserve their metadata through a separate Owner-approved procedure first.
Independent clones with registered child worktrees also remain HOLD.

Use existing Python 3.12+, Git and authenticated GitHub CLI (`gh`), from trusted
Control. First update Control through the approved canonical procedure. Control
must be an independent clean `main` checkout; HEAD and `origin/main` must equal
the freshly queried canonical GitHub main SHA. Network/authentication failures,
unsafe Git configuration or incomplete scans refuse the run. No fetch/reset or
credential changes are performed by the cleanup command.

```powershell
& $Python -B "$CONTROL_CHECKOUT/scripts/owner_workspace_cleanup.py" `
  --config $OWNER_CLEANUP_CONFIG --plan $OWNER_FROZEN_PLAN
```

Default is **plan only**. The destination must not already exist. This writes
one frozen Owner-local JSON plan and prints only its canonical JSON SHA-256,
candidate/HOLD counts. It does not delete or change inspected directories.
The plan includes exact configuration, main SHA, object/file identities,
content fingerprints, HEAD, shared-ref fingerprint and logical size estimate.
Reasons are fixed codes, with no private payloads or arbitrary Git errors.
Logical bytes are not guaranteed reclaimed disk space.

Eligibility requires a complete code-only scan, no symlink/reparse/junction or
hardlink anywhere in the inspected boundary or ancestors, no private markers,
and clean Git status with **no untracked or ignored files**. Only exact tracked
`.env.example` files are allowed; `.env`, other `.env*`, runtime data/sidecars,
backups, exports and private markers remain protected. Untracked templates are
HOLD and never read. Arbitrarily renamed private content cannot be detected by
name: the Owner must attest that these are code-only workspaces.

HEAD must exist in trusted Control and be an ancestor of current main. An
independent clone also needs all local refs peeled to preserved commits, no
stash/replacement refs, no unique reflog history, and no unreachable objects.
For a linked worktree, validate the declared pointer, reciprocal registration,
common directory and its own HEAD reflog. Shared refs, branch/stash/reflogs and
object store remain in Control; unrelated shared history is never deleted.
Unsafe configuration (including hooks/filter/include execution settings),
alternates, nested Git/submodules, locks and scan limits fail closed.

Review the frozen local plan and approve its exact digest. It expires after
15 minutes; a changed main, path, bytes, Git state or configuration requires a
new plan and approval. Real deletion still requires the independent filesystem/
privacy review and Owner approval required by #666.

```powershell
& $Python -B "$CONTROL_CHECKOUT/scripts/owner_workspace_cleanup.py" apply `
  --config $OWNER_CLEANUP_CONFIG --plan $OWNER_FROZEN_PLAN `
  --approve-sha256 $OWNER_APPROVED_PLAN_SHA256
```

Apply is Windows-only. It holds input/configuration handles, obtains fresh
canonical evidence immediately before **each** deletion, and revalidates that
entry's exact frozen identity/state. Windows handles pin checked ancestors and
objects; deletion uses those same objects after a verified handle handover,
never recursive path deletion, link traversal, Git `--force`, branch deletion
or worktree prune. For linked worktrees, only that task tree and its exact own
registration are removed. Shared Git refs are preserved.

An exclusive `<plan filename>.apply.jsonl` journal records entry indices,
digest, timestamps and revalidation/deletion/completion states. Keep it with
the plan for the local path mapping. A failure can leave a partially removed
candidate; stop and reinventory, retaining the journal. A journal ending with
`deleting` or `refused_or_incomplete_reinventory_required` is not success.
The same plan cannot be replayed via the CLI after any apply attempt.
No ACL/ownership changes or rollback/quarantine are implemented. Apply requires
Windows support for handle disposition with read-only-file handling; lack of
support refuses deletion. Linux plan/unit CI does not replace Windows probes.

Grace periods, recurring scheduling and an automatic enable setting belong
to the later auto-cleanup phase. No automatic cleanup is enabled here.
