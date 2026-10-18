# Owner-local workspace cleanup — plan/apply (#666)

## Current status and tool selection

#679/#666 migration and the named legacy cleanup are **CLOSED COMPLETE**. The [final report](https://github.com/LTstripes/hermes-finance/issues/679#issuecomment-5973182455) records all 54 Access Denied remnants removed and no remaining failures. Do not rerun the historical inventory/config/plan batches. The one-time Owner permission to discard those named technical histories is not future blanket deletion authority.

The deployed daily task uses **`scripts/cleanup-workspaces.ps1` plus its native helper**, documented in [WORKSPACE_JANITOR](WORKSPACE_JANITOR.md). Its active Ops installation is protected even though it is outside the main Hermes folder. This page describes the separate conservative Python frozen-plan tool, not the scheduler.

Only the Owner or the one local Worker under an explicitly accepted operational assignment runs this on real paths. Ordinary agents use synthetic fixtures. Keep populated configuration, plans and journals outside Git, runtime trees and task workspaces. They contain local paths and must not be uploaded. The [inventory tool](OWNER_MACHINE_LAYOUT.md#owner-inventory-command) remains read-only. This Python command implements no scheduler or automatic runtime migration.

## Configuration

All paths are absolute local fixed-disk paths selected by the Owner, not template literals.

| Field | Meaning |
| --- | --- |
| `version` | Integer `1` |
| `owner_root` | Protected Owner container; never a target |
| `stable`, `control`, `preview` | Mandatory protected runtime/code/data boundaries; current roles are Stable/Main/Test |
| `workspace_roots` | Configured roots pairwise disjoint from each other and protected boundaries |
| `entries` | Up to 64 explicit `path` + `role` entries (`workspace`, `unknown`, `stable`, `control`, `preview`) |
| `active`, `artifacts_resolved` | Explicit false / true required for evaluation; not inferred from historical registry or closed PR alone |
| `git_dir`, `git_common_dir` | For linked worktrees only: own registration and trusted Control's `.git` |

Targets must be immediate task children of configured roots. Active/unknown/out-of-boundary/unresolved entries are HOLD without payload inspection. Protected roots and client roots are not targets. Legacy linked worktrees outside trusted Control and independent clones with retained child worktrees remain HOLD under this generic tool. Do not generalize #679's exceptional discard decision into a changed generic classifier.

Use existing Python 3.12+, Git and authenticated gh from trusted Main/Control. It must be an independent clean main with HEAD and origin/main equal to freshly queried canonical GitHub main. Network/auth failures, unsafe config or incomplete scans refuse the run; the command does not fetch/reset/change credentials.

## Plan

```powershell
& $Python -B "$CONTROL_CHECKOUT/scripts/owner_workspace_cleanup.py" `
  --config $OWNER_CLEANUP_CONFIG --plan $OWNER_FROZEN_PLAN
```

Plan-only is default. Its destination must be new. It freezes exact configuration, main, object/file identities, fingerprints, HEAD, shared refs and logical size; stdout is only canonical JSON SHA-256 and candidate/HOLD counts. Enumerated failure `reason` is privacy-safe; unknown exceptions become `unsafe_or_unresolved`. A Control-level refusal is not evidence that entries were evaluated. Logical size is not measured reclaimed disk space.

Eligibility requires a complete code-only plain scan, safe Git config, no runtime/private material, and clean index/bytes with no untracked/ignored files. Exact public repository exceptions remain narrowly defined by current source (#677/#678); ordinary project lockfiles are not Git administrative locks. The read-only inventory intentionally retains broader name heuristics. Do not extend public exceptions to arbitrary `.env*`, `data/*` or token-named content.

Unsupported index flags, alias/reparse/junction/symlink/hardlink, nested Git/submodules, locks, unsafe filters/includes, alternate/shallow/grafted graphs and incomplete evidence fail closed. Actual bytes are checked against index objects; status must also prove index=HEAD. Name checks cannot detect arbitrary renamed private payloads: only declared code-only workspaces may be evaluated.

HEAD must be in trusted Control and an ancestor of current main. Independent clones require all local refs/reflog history preserved, no stash/replacement refs or unreachable objects. Linked pointers require exact reciprocal registration/common-dir evidence; only ordinary own metadata and preserved ORIG_HEAD are removed, never shared refs/object store or unrelated history.

## Apply

Review an unexpired exact local plan and authorize its canonical digest. Generic plans expire after 15 minutes; changed main/path/bytes/Git/config require a new plan and approval. An earlier issue discussion is not approval of an arbitrary future plan.

```powershell
& $Python -B "$CONTROL_CHECKOUT/scripts/owner_workspace_cleanup.py" apply `
  --config $OWNER_CLEANUP_CONFIG --plan $OWNER_FROZEN_PLAN `
  --approve-sha256 $OWNER_APPROVED_PLAN_SHA256
```

Windows-only Apply pins input/configuration/ancestors/objects, obtains fresh canonical evidence before each deletion and revalidates frozen identity/state. It deletes the checked objects via handles, not recursive link traversal, Git force, branch deletion or general worktree prune. Only the exact task and its own trusted registration are removed for linked worktrees.

An exclusive `.apply.jsonl` journal records digest/entry/time/revalidation/deletion outcome. Keep it Owner-local. Failure may leave a partially removed candidate; stop and reinventory with the journal retained. `deleting` or `refused_or_incomplete_reinventory_required` is not success. CLI replay is refused after any Apply attempt. No ACL/ownership repair, quarantine or automatic rollback is supplied. Missing platform support refuses deletion; Linux tests do not replace Windows probes.

The separate recurring janitor has its own accepted 7-day eligibility and deployment. Do not schedule this Python command or weaken its guards merely to make an old frozen plan work. Current operating boundaries are in [OWNER_MACHINE_LAYOUT](OWNER_MACHINE_LAYOUT.md).
