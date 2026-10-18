# Post-move / returns checkpoint — 2026-10-16

This dated receipt records the Owner's changed situation and the Integrator's live GitHub recheck. It supersedes stale *current-status* scheduling, not historical evidence or financial/runtime contracts. Earlier [12 October](../archive/2026-10-18/docs/SESSION_CLOSEOUT_2026-10-12.md), [11 October](../archive/2026-10-18/docs/SESSION_CLOSEOUT_2026-10-11.md), [10 October](../archive/2026-10-18/docs/SESSION_CLOSEOUT_2026-10-10.md) and [4 October](../archive/2026-10-18/docs/SESSION_CLOSEOUT_2026-10-04.md) records remain intact.

## Code and release evidence

| Item | Exact identity / disposition |
| --- | --- |
| Canonical main inspected | `2051862bd2bdef0441580ec700e1844e5b6b9f6a` |
| Accepted preparation | [PR #837](https://github.com/LTstripes/hermes-finance/pull/837), head `25e20bd19b9965a03dfd39190e526c3ab10ba727`, guarded squash to the main SHA above |
| Candidate CI / review | [CI #38795738008](https://github.com/LTstripes/hermes-finance/actions/runs/38795738008) SUCCESS in accepted candidate evidence; [Integrator review #5539252243](https://github.com/LTstripes/hermes-finance/pull/837#pullrequestreview-5539252243) |
| Directly reread post-main CI | [#38799966374](https://github.com/LTstripes/hermes-finance/actions/runs/38799966374), `push`, exact main SHA, `completed/success`, attempt 1 |
| Code closeout | [#836 final Integrator checkpoint](https://github.com/LTstripes/hermes-finance/issues/836#issuecomment-6201636965) |
| Last published release | [v1.2.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.2.0), published 2026-10-04; tag object `f9311d26c1aae7295361937096844f4dde615b55` → commit `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc` |
| v1.3.0 | Code complete, **unpublished**; candidate notes deliberately `UAT-PENDING` |
| Excluded open candidates | #744 and #829 remain outside this release |

The pre-packaging inventory at `46a9e6db01fcbf868362028957678b0d856d804c` counted 122 commits / 273 changed files since v1.2.0 and 14 new migrations. [Release preparation](../archive/2026-10-18/docs/release-preparation-1.3.0.md) records synthetic 0044→0058 compatibility, preservation, duplicates and migration failure/recovery; it does not prove a real production upgrade. This docs-only refresh does not change that product candidate, its package version or its publication guard.

## Owner update and local evidence boundary

Owner reports that Finance data have **already been transferred from Tecno to HONOR**, with Stable update still pending. The previous “no move signal / empty HONOR” scheduling is therefore obsolete. [#838](https://github.com/LTstripes/hermes-finance/issues/838) was updated to verify the completed move, not repeat it.

The [pre-move Stage A receipt](https://github.com/LTstripes/hermes-finance/issues/838#issuecomment-6202472514) measured OLD Tecno Stable **v1.2.0 / schema 0044**. That supersedes historical v1.1.0 on the old machine only. The receipt's PASS_WITH_FIXES concerned a read-only pre-move assessment; it is not post-move preservation/recovery PASS. Its unresolved backup, off-device visibility, restore-route, target-binding and scheduler findings must be reconciled against existing move evidence, not assumed either fixed or still broken.

The chat Integrator has not inspected HONOR private files, SQLite or live processes. Current HONOR Stable pin/schema, continuity and supported recovery must be established by the bounded local operator/readback and required independent review. Preserve old code/data and Tecno rollback; keep Health-Check in its own repository and acceptance path. No repeated transport, protected Start/restore/migration, financial Apply/Close or deletion occurred in this GitHub session.

## Task status corrections and next goal

- [#838](https://github.com/LTstripes/hermes-finance/issues/838): **Owner-reported transfer complete / technical acceptance pending**. Immediate assignment is read-only reconciliation of existing move receipts and actual HONOR identity/recovery. Remains OPEN until acceptance.
- [#836](https://github.com/LTstripes/hermes-finance/issues/836): **code complete / recovered-copy UAT, publication and Stable rollout pending**. Existing #837 work is not reassigned. Retain UAT-PENDING until actual accepted UAT and release decision.
- [#774](https://github.com/LTstripes/hermes-finance/issues/774): obsolete “implementation not started” corrected to **code complete / unavailable-path UAT PASS / numeric blocked**. [September acceptance](https://github.com/LTstripes/hermes-finance/issues/774#issuecomment-6139144470) remains operator-attested API/desktop/export no-write evidence, not a real numeric return.
- [#839](https://github.com/LTstripes/hermes-finance/issues/839): new bounded **independent WHAT-IF contract** task, not implementation or publication. It follows [Owner's conditional-analysis direction](https://github.com/LTstripes/hermes-finance/issues/774#issuecomment-6200192284): useful single-account period calculation under explicit assumptions, separate from actual S3, exact XIRR/TWRR and whole-portfolio performance.

The user-facing goal is a useful conditional RUB result and period percentage with observed facts and assumptions visibly separated. Unknown source/economic inputs remain unknown in the ledger and actual APIs. A scenario number must not grant source authority, cash coverage, financial Apply, Close or an exact-return claim. New product code is outside frozen v1.3.0 and needs its own accepted contract, independent financial review, synthetic tests and exact CI.

## Preserved source and operational work

[#831](https://github.com/LTstripes/hermes-finance/issues/831) is CLOSED / technical runtime handoff complete. [#769 latest checkpoint](https://github.com/LTstripes/hermes-finance/issues/769#issuecomment-6199824580) is **OPEN / FINANCIAL NOT_READY** after one accepted read-only four-original July/August source pilot. Both seams remain UNKNOWN; no July zero follows from an August zero. Retain the scratch/originals/private response/manifests; do not rerun the same batch without new evidence. #752 catalogue reuse and #777 denomination remain separate proof gates; old mapping IDs are not transportable authority.

[#814 consolidated broker request](https://github.com/LTstripes/hermes-finance/issues/814#issuecomment-6200022502) is prepared, **not sent**. It covers July omission/full-inventory semantics and September NKD/fee/settlement/Money/Transfers/UFSR/footer/EOD basis. Await new broker-authored evidence before another financial-authority pass; a reply is still not blanket Apply/Close permission. No broker message was sent in this session.

The October original can later use the existing one-month source-first path when available, with its own mappings/Preview/warnings. No automatic Close or promised exact return follows from a new file or the Stable update.

## Next-session entry

Start with live #838/#836, main, open PRs, latest accepted comments, release and exact CI. Reuse completed work. The next safe local operation is #838 read-only handoff verification; then authorized isolated-copy UAT → Owner acceptance → final notes/exact CI/guarded #124 → published-target backup-first OPS02 → explicit Start/migration and continuity acceptance. #839 contract review can proceed independently without Owner data or changes to protected runtimes.

README and CURRENT_STATUS are the current entrypoints; this is a dated history receipt. Issue/PR review and CI outcomes after this snapshot must be read live. Nothing here asserts that a later docs PR is merged, a new release exists, or Stable is upgraded.
