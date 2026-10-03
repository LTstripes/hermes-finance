# Owner machine layout — current contract

This page owns the portable role/path contract. Absolute machine mappings, registry, reports and recovery material remain Owner-local outside Git and task workspaces. [Runtime operations](OWNER_RUNTIME_OPERATIONS.md), [ADR 0012](adr/0012-runtime-and-agent-workspace-isolation.md) and [ADR 0014](adr/0014-launcher-runtime-profile-safety.md) retain the data/isolation contracts.

## Completed state — #679 / #666

Both issues are CLOSED COMPLETE. [Final operational evidence](https://github.com/LTstripes/hermes-finance/issues/679#issuecomment-5973182455) supersedes the earlier inventory/design, BLOCKED and rollback checkpoints. No further migration, legacy deletion or client-root testing is assigned by this page.

The Owner-authorized migration preserved Stable v1.1.0 and its DB identity/content/schema, moved Main and isolated Test, removed all recorded legacy remnants and the local Launcher/config/shortcuts, and deployed the workspace janitor. No release/version promotion occurred. Detailed dated restart context: [session closeout](SESSION_CLOSEOUT_2026-10-03.md).

## Owner-authorized final boundaries (#679)

```text
<FINANCE_CONTAINER>/
  Hermes/                         <HERMES_ROOT>
    stable/                       KEEP — published production runtime
      backend/, frontend/         whole release checkout, pinned SHA
      data/                       Owner production DB/sidecars
    main/                         KEEP — clean canonical code; Control role
    test/                         KEEP — persistent exact-SHA UAT; Preview role
      backend/, frontend/         selected Test checkout
      data/                       separate Owner-only data, kind=preview
    owner/                        KEEP — registry/manifests/recovery/journals
    workspaces/
      codex/<issue-task>/
      opencode/<issue-task>/
      grok/<issue-task>/
      hermes/<issue-task>/
  ops/                            KEEP — ACTIVE deployed operations
    workspace-cleanup/            installed janitor script + native helper
    workspace-cleanup-latest.json bounded structural report
```

The Ops sibling is part of the actual deployed setup, not old disposable clutter. The janitor derives its fixed roots relative to that install location. Do not relocate/remove Ops or the installed pair without a separately accepted deployment update. External supported recovery destinations may also be outside this diagram and remain protected.

Stable is not development main. Main is not a Worker workspace. Test is one persistent reusable location with separate data, not a new top-level stand per UAT. Future refresh uses supported exact-SHA preparation and existing-path guards; never attach Test to Stable DB. Only one owned runtime uses `127.0.0.1:8000` at a time.

## Shared client workspace contract

Codex, OpenCode, Grok and Hermes each use the Owner-configured local root under `workspaces/<client>`. One active writing/local-verification task owns one physical `<issue>-<slug>` clone/worktree. Concrete absolute roots are client-local, not duplicated in Git. New roots were already configured and accepted; no routine re-test is required.

Write only the assigned task tree. Do not switch/reset/clean siblings. Inspect delivered sibling work through GitHub/remote refs or a separately assigned review clone, not active physical directories. Stable/Main/Test/Owner/Ops are never Worker roots. Ordinary development and tests use synthetic data; an explicit local operational assignment is not general access to private payloads.

## What may be deleted

| Boundary | Rule |
| --- | --- |
| Stable/Main/Test/Owner, active Ops, supported backups | Preserve. Relocation/deletion requires its own exact operational authorization. |
| New task workspaces | Prefer the deployed janitor's current eligibility; active/unknown/private/unpreserved work stays. |
| Identified old Hermes forests covered by #679 | The one-time Owner authorization allowed discarding their local-only history; that cleanup is complete. |
| Newly discovered or ambiguous outside-root directory | Outside-root location/name alone proves neither role nor disposability. Preserve other projects, active references and private/recovery data. |

Do not follow junction/symlink/reparse targets during cleanup. Do not generalize the old forest authorization into blanket deletion of everything outside `<HERMES_ROOT>`. Unknown files or a shared parent are not automatically Hermes garbage.

## Daily scheduled cleanup

[WORKSPACE_JANITOR](WORKSPACE_JANITOR.md) owns the recurring contract. Task `Hermes Finance workspace cleanup` is deployed daily at 12:00 local, Apply, retention 7 days, IgnoreNew and StartWhenAvailable. It can evaluate only immediate tasks in the four fixed client roots. Publication/preservation, clean state, inactivity, privacy and filesystem checks all apply; age alone is insufficient.

Deployment dry-run was complete with 8 PRESERVE and no deletion. That is not a first scheduled Apply result. The installed Ops copy/report, not Python inventory or a historical frozen plan, identifies the scheduled behavior. Do not rerun migration just to verify housekeeping.

## Owner inventory command

The original `scripts/owner_workspace_inventory.py` remains permanently read-only. It is a bounded diagnostic, not a prerequisite for ordinary work or a command the Owner must repeatedly run after this completed migration. For an explicitly assigned future Owner-local operation, its local Worker can prepare structural batches under that assignment's narrow privacy boundary; ordinary development agents cannot inspect private runtime trees.

Use an explicit local registry following [the schema](schemas/owner-workspace-registry.schema.json), at most 64 entries per batch. Workspace roots are boundaries, not recursive whole-disk discovery requests. Declare uncertain paths unknown; do not infer `active=false` or resolved artifacts from folder age/names. Expected SHA and release tag are independently chosen pins, not proof of publication.

```powershell
& $Python -B "$CONTROL_CHECKOUT/scripts/owner_workspace_inventory.py" `
  --registry $OWNER_LAYOUT_REGISTRY
```

Here Control means current canonical Main. Default stdout is a sanitized numbered summary; `--local-paths` is Owner-only and must not be uploaded. The registry, raw paths, private filenames/payloads and reports remain local. No DB/.env/backup contents are read by this tool; no fetch, profile execution, application import, copy, move or delete occurs.

Runtime dirty state is unknown, not inferred by hashing private files. Content-based workspace status is allowed only after a complete code-only scan without private markers/indirection. Linked pointers, unsafe config, external object stores, incomplete scans and errors fail closed. Name heuristics can flag public templates; that does not prove secret leakage or authorize ignoring a real private file.

Disk bytes are logical/lower-bound observations, not guaranteed reclaim. Nested data counts must not be added twice. Cached remote refs do not prove fresh preservation; local ref coverage does not prove reflog/dangling work is disposable. Treat results as snapshots, not locks or deletion proof.

## Classification and cleanup proposal

Inventory emits KEEP for declared protected roles, ACTIVE WORKSPACE for active/unresolved ownership, and UNKNOWN for the rest of unresolved evidence. It never emits deletion authorization. The separate [frozen-plan cleanup command](OWNER_WORKSPACE_CLEANUP.md) retains its conservative generic contract; it is not the daily janitor and does not inherit the one-time legacy discard decision.

## Migration/backup/rollback manifest for separate approval

The #679 move is already done. For a genuinely new relocation, establish exact source/target roles, current pins/data continuity, supported references, quiescence, recovery and rollback appropriate to that assignment. Do not recreate the old multi-stage Owner manual JSON workflow. The local Worker owns accepted operational execution; the Owner decides retention and actual destructive authority.

A Windows Python environment may retain absolute interpreter bindings. Recreate/reprepare generated environment and console entry points at the destination using the exact release's supported locked preparation. Preserve production DB/config/secrets; never restore Test over Stable, silently promote main or downgrade schema. On a failed Stable readiness check, restore the proven prior operating state before legacy cleanup.

`scripts/owner_machine_relocation.py` is only an identity-bound same-volume rename primitive. It grants no implicit copy/delete/reference or future relocation authority. Caller-specific authorization, quiescence, reference snapshots, readiness and rollback remain required.

## Explicit operational continuation (#679)

Historical authorization: [Owner clarification 5972086820](https://github.com/LTstripes/hermes-finance/issues/679#issuecomment-5972086820). It changed retention of named old technical forests and removed the extra approval loop for those exact actions; it did not authorize other-project deletion or future unrestricted cleanup. Later execution and residual closeout completed it.

One verified supported backup was reused for the move when applicable; already valid restore/rollback evidence was not repeated. The initial path-bound Python startup failure was rolled back, then resolved by destination preparation. Local Launcher removal is complete; repository source retirement remains #629, with shared runtime/recovery consumers protected.

The detailed earlier preparation narrative remains in [the pre-closeout document](https://github.com/LTstripes/hermes-finance/blob/8eb991fc81ebbe63917a9ca1ea204762129c9019/docs/OWNER_MACHINE_LAYOUT.md) and issue history. It is historical evidence, not a standing request to redo #679.
