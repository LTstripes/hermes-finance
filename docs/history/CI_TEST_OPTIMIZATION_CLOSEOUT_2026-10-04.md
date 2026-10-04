# CI/test optimization closeout — 2026-10-04

This is the closeout for the later Hermes Finance CI/test simplification wave. The earlier [2026-09-16 optimization closeout](../CI_TEST_OPTIMIZATION_CLOSEOUT_2026-09-16.md) remains historical evidence for the first pass; this document records the later concurrency, visual-evidence, docs-only and Launcher-retirement work.

## Final checkpoint

- Development main checkpoint: 29b2ecf6c61a86fb5da03c48585b92358f38e890 (#629 / PR #689 merge).
- #629 exact candidate: 377290aa2ac303a949755c92ccda003bff50b7c7; exact-head CI 37186535246 SUCCESS.
- Canonical exact-main CI 37187645443 is the final pending gate at this draft checkpoint. #629 is not administratively complete until that run succeeds.
- No release, Stable/Test promotion, financial-semantic change or Owner-private data action is part of this wave.

## What changed

| Work | Result | Preserved guarantee |
| --- | --- | --- |
| #671 / #681 | Cancel only superseded ordinary-PR runs of the same repository/workflow/PR | main, release and protected integration/UAT runs are not cancelled or queued behind ordinary PRs |
| #668 / #682 | Fixed-viewport-owned visual cases run once | unique scenario set and true project-viewport coverage remain |
| #669 / #683 | Exact-head UI evidence remains its own truthful producer; normal CI can omit only proved-equivalent duplicate 1440 executions | head/merge/checkout identity is fail-closed; screenshots remain dev-server evidence and dist remains build evidence |
| #670 / #686 | Narrow fail-closed docs-only PR mode | executable/build/test/release inputs and ambiguity stay full; canonical main is always full |
| #629 / #689 | Retired Launcher GUI/package/install/tests/jobs | direct Prepare/Validate/Start, Windows production smoke, backup-first Stable update, recovery and janitor exclusions remain |

## Measured effect

### Visual audit

#668 changed the scheduled visual matrix from **345 to 287 executions**:
- 1366×768: 115 → 86;
- 1440×900: 115 → 115;
- 1920×1080: 115 → 86.

That removes **58 repeated executions (16.8%)** while keeping **115 unique scenario titles**. The exact-head 1440 evidence selection remains **97 tests**, and independent review confirmed the retained **58 screenshot filename set**.

#669 then removes the overlapping 97-test 1440 selection from normal PR visual CI only when the candidate/head/merge/checkout trees are proven equivalent:
- normal visual CI: **287 → 190** scheduled executions;
- exact-head UI evidence: **97** executions retained separately.

If the trees differ or identity evidence is incomplete, normal CI falls back to the full relevant visual run.

### Docs-only pull requests

#670 keeps the workflow terminal and fail-closed instead of using an on.paths-ignore shortcut. Final controlled proof PR #687 at 4c96fb74a1cf4b7f32b0f44bfc8a8d2bb2fb5a8b completed CI 37183515223 in about **21 seconds**: classification/privacy/path checks and Documentation fast path succeeded while product suites were terminal-skipped.

The implementation PR itself classified full and ran the full product lanes. Independent review caught one real false-positive candidate: backend/README.md is Hatchling package metadata, so it was removed from the docs-only allowlist. This is why the final rule is based on explicit consumers, not “Markdown means safe”.

### Concurrency and retired Launcher surface

#671 prevents superseded ordinary PR attempts from wasting runners without changing main/release behavior.

#629 removes the now-unused Windows Launcher maintenance surface. Final PR #689 changed **41 files, +112/−7000**, deleting the GUI/C# safety harness, package/install assets, launcher-only path/safety jobs and their helpers. Shared runtime/recovery code with launcher-era names was retained when still consumed.

Review also found that recovery still needed a v1 runtime inventory after the Launcher config disappeared. The accepted remediation adds [a non-Launcher example](../runtime-inventory.example.json) and requires an explicit Owner-local inventory path for recovery/cleanup exclusions; missing or invalid inventory remains fail-closed.

## Final supported CI shape

- Ordinary code/config PR: full applicable backend/frontend/browser/Windows/release verification.
- Proven docs-only PR: narrow retained classification/privacy/diff checks plus terminal Documentation fast path; omitted product jobs are skips, not fake passes.
- UI-relevant PR: exact-head UI evidence remains separate under its existing path trigger.
- Canonical main: full CI; docs-only mode is PR-only.
- Guarded release: unchanged and separately controlled.
- Windows: Launcher-only jobs are gone; direct-runtime Windows production smoke, timezone and shared runtime/recovery coverage remain.
- Concurrency: only superseded ordinary runs of the same PR/workflow cancel each other.

## Stop decision

After #629 canonical verification there is **no dedicated test/CI optimization implementation backlog**. #124 is permanent release infrastructure, #554 is coordination, and remaining open work such as #535/#540 or #646 is product/integration work rather than a test-speed queue. #630 is CLOSED / NOT_PLANNED.

Do not reopen CI optimization merely to chase small runner-time gains. Reopen only for a concrete correctness/flakiness problem, material development bottleneck or a new product change whose coverage needs redesign.

## Process simplification

During #669 the project also retired mandatory model-benchmark/model-evidence collection:
- #605 is closed;
- the benchmark journal was removed;
- normal Worker/Reviewer handoffs do not request model/provider identity, grades, token usage or telemetry.

Model selection remains a routing choice, not repository evidence to collect.
