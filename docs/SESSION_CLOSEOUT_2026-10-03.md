# Session closeout — 2026-10-03

This is the restart brief for the completed post-release UAT/filesystem session. Read current GitHub main/release/CI and #554 before acting; do not treat this dated SHA as today's moving main. Existing dated release/UAT reports are retained unchanged.

## Verified repository checkpoint

- Baseline for this documentation closeout: `8eb991fc81ebbe63917a9ca1ea204762129c9019`, main push CI [37150791634](https://github.com/LTstripes/hermes-finance/actions/runs/37150791634) SUCCESS.
- Published/local Stable remains v1.1.0 at `32c905cfc938fd1aeaeb67643eb6fa77e8644a64`. No release or version promotion in this session closeout.
- #662 six-slice wave (#645/#647/#648/#649/#650/#651), #663/#664/#665 maintenance, #672 copy and #674 month-list follow-up are integrated. Do not repeat their implementation.
- #679/#666 filesystem migration and cleanup are closed COMPLETE. #684 documentation and #685 janitor are integrated. The final operational report, not earlier STOPPED/BLOCKED checkpoints, is authoritative: [#679 comment 5973182455](https://github.com/LTstripes/hermes-finance/issues/679#issuecomment-5973182455).

## What was actually achieved

Stable, canonical Main and persistent Test were moved into the agreed role layout. Stable preserved v1.1.0 and its production DB identity/content/schema; its path-bound Python environment was re-prepared and supported Start/readiness passed. Test kept its independent data and original UAT pin. New per-client workspace roots were already working and were left unchanged.

The initial cleanup increased D: free space by 35,197,726,720 bytes; the residual pass added 1,345,101,824 bytes. Their sum is 36,542,828,544 bytes, approximately 34.03 GiB. These are recorded operational measurements, not a new scan. All 54 Access Denied remnants were removed; zero remaining failures were reported. Local Launcher/config and shortcuts are removed, but #629 repository source/test/workflow retirement remains open.

The Finance janitor is deployed: daily 12:00 local, Apply, 7-day retention, IgnoreNew, StartWhenAvailable. The observed dry-run preserved all eight inspected entries and deleted none. No first scheduled deletion has been observed in this closeout. An old workspace is not guaranteed to disappear after seven days; all eligibility checks still apply.

## Filesystem rules that must survive the handoff

Portable layout and role ownership: [OWNER_MACHINE_LAYOUT](OWNER_MACHINE_LAYOUT.md). The actual machine mapping is in the Owner-local registry and the authorized #679 report; do not duplicate absolute machine paths in tracked files.

`stable`, `main`, `test`, `owner` and active deployed Ops are protected. New task/review copies belong only in the configured client root below `workspaces`. Review other agents' delivered work through GitHub/remote refs, not their active physical trees.

**The deployed janitor uses a separate `<FINANCE_CONTAINER>/ops/workspace-cleanup` installation and Ops report. Do not delete that directory just because it is outside `<HERMES_ROOT>`.** Likewise, external supported recovery destinations and other projects are not old disposable workspaces. The one-time authorization to discard identified legacy Hermes code/history was not blanket future deletion authority.

No new inventory/migration/cleanup or client-root testing is pending. Remaining operational follow-up is only a later read-back of the scheduled janitor's actual result, not another deployment or mandatory immediate Apply.

## Parallel test optimization

- #671 / PR #681 merged: ordinary PR concurrency cancellation with main/release/integration protection.
- #668 / PR #682 merged: 58 duplicate fixed-viewport executions removed at its measured candidate; unique titles and required viewport combinations retained.
- #669 / PR #683 merged, head `4016b49c60f249a7722d94f20a31d96578b0ea3e`, merge `56d6750a6f13d467d497762b77925d07e3ef21ef`. Exact-head producer is retained. Duplicate omission is conditional on verified checked-out/head/merge tree identity; no head/merge evidence substitution.
- #670 remains the next docs-only PR fast-path item at this checkpoint. The test-optimization session owns its execution; check live issue/PR state before assigning anyone.
- Do not reimplement #669 merely because its issue state still needs administrative closeout. Do not modify workflows in parallel with their current writer. #629 CI removals are serialized with this stream.
- Model evidence/benchmark collection was retired by Owner decision in #669; historical records remain history. Recommend a Codex model/effort and an external alternative when routing, but do not require runtime identity reporting.

## Owner checks still distinct

#572 and #662 are accepted within their documented limitations. Historical quote Preview/Apply PASS does not prove live same-day LAST #645. Alfa UI PASS does not establish #646 incident root cause or terminal recovery. #667 code is merged but this session does not invent a later focused Owner retest. Portfolio/account Phase A exists; universal real-history XIRR/TWRR availability and class-return Phase B do not follow from that.

After the CI work, consider one Test refresh and a short combined route for #667 and remaining portfolio/account Performance checks. Use the persistent Test folder; no new top-level stand for every task. #630 synthetic representative dataset is optional/deferred, not a reason to block accepted work.

## Next-session order

1. Independently read live main, published release, exact-main CI, open PRs and latest #554/test-session notes.
2. Finish/coordinate the existing test stream; do not start a second workflow writer.
3. Propose #629 as the next technical implementation: delete only Launcher-owned source/tests/jobs; preserve shared direct startup, backup/recovery helpers and runtime safety. It has product approval but not arbitrary shared-helper deletion authority.
4. Prepare focused Owner retests only when the intended Test SHA is frozen. Leave /v1, class returns, composer and unrelated audits alone unless explicitly selected.

A normal proposal includes result, complexity/risk, concrete Codex model/effort and external alternative, and one short prompt. No automatic Worker launch or release. For #629, Sol 6.1 High is a reasonable runtime/dependency route; Grok 4.7 / xAI / Grok Build CLI is an available alternative for read-only dependency review. This is routing preference, not measured performance or execution attribution.

## Lessons retained without adding another rulebook

The initial Owner-only inventory/framework assignment did not match the request for a completed local move and cleanup. Later clarification explicitly distinguished protected current data from disposable legacy history. Future operational tasks should establish that retention choice and give the local Worker the accepted bounded execution authority upfront. Do not make the Owner relay a sequence of exploratory PowerShell/JSON diagnostics when an authorized local Worker can execute the workflow. Reuse valid evidence; do not promise an unverified fix is the last one.
