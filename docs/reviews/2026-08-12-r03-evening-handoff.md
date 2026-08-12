# R03 evening handoff — 2026-08-12

Status: review bundle only. Nothing in this document authorizes merge, PR, force-push, rebase, branch deletion, release, or changes to remote `main`.

## Goal for the evening

Run the repo locally on Windows, visually inspect the current 0.3 UI stack, execute proportional frontend/backend checks, fix only bounded regressions that belong to the reviewed tasks, and report blockers before any merge decision.

The UI review branch is intentionally stacked. For visual review use this handoff branch; its UI code is exactly the R03-06 stack plus this docs-only handoff commit.

UI code baseline under review:

- `main`: `b235d09745c560a9f1bed94a10f665cd5b75b39d`
- `r03-01-shared-ui-primitives`: `3af0a97cc16624ce429f5629c168b94c4d4b9948`
- `r03-02-app-shell-diagnostics`: `ffa07c101017314dc92121412b4b3d433d60d0e5`
- `r03-03-dashboard-hierarchy`: `8229ace64d5a653c6f63b0c4f3ecf43b6ecc8762`
- `r03-04-passive-income-semantics`: `a476bd2cf4a29ae343ad9bb885617214e7087392`
- `r03-09-goals-cards`: current remote head `e605934041063b9ac2bfbf8d3a68650a8d1c4394`
- `r03-06-month-workspace-shell`: `4e7a79c19cb3fb24be87eead1258b8da2ca084f5`

Separate analytics/backend stack:

- `r03-11-capital-composition-contract`: `b438ddceb71c5f380f129085ef5f6002edcd8ec3`
- `r03-12-capital-composition-api`: `7c41cd9a98c8529e9748f7abbbdcb5245e076ea3`

`R03-05` is intentionally not part of this bundle. It remains the Hermes-vs-Codex A/B candidate and must start from one identical baseline in isolated branches/worktrees, with no remote merge/push of the competing result before owner selection.

## 1. Start clean

PowerShell reference:

```powershell
git fetch origin --prune
git status --short
git switch handoff/2026-08-12-r03-evening-review
git pull --ff-only
```

If the branch is not local yet:

```powershell
git switch -c handoff/2026-08-12-r03-evening-review --track origin/handoff/2026-08-12-r03-evening-review
```

Confirm the UI code parent is R03-06. The handoff branch adds documentation only after `4e7a79c19cb3fb24be87eead1258b8da2ca084f5`.

Do not use private seed data for review. Synthetic/local disposable data is enough for interaction checks.

## 2. Frontend checks

From `frontend/` run the normal project commands available in the repo:

```powershell
npm ci
npm test
npm run lint
npm run build
```

Do not report the whole frontend green unless all commands actually pass.

Known review risk: legacy `App.test.tsx` cases may still assume the old long Month editor where all sections were visible at once. If a failure is only that assumption, update the test to navigate to the relevant section; do not undo the workspace behavior to satisfy an obsolete test.

## 3. Local app / visual smoke

Run the normal local Windows application path and confirm it still binds only to `127.0.0.1:8000`.

Review at minimum:

- normal desktop around `1366×768`;
- reduced desktop around `1024px` width;
- one narrower resize pass to catch wrap/collision regressions.

For every reviewed screen, look for overlap, horizontal action piles, clipped text, sticky elements covering content, menus rendering off-screen, broken focus rings, and controls that become visually indistinguishable.

### App shell / R03-02

Check:

- sidebar groups and order: Overview / Accounting / Planning / System equivalents in the Russian UI;
- `Dashboard`, `Аналитика`, `Месяцы`, Accounts/Instruments, `Цели`, Export/backups, Settings are reachable;
- old permanent topbar `MVP · 127.0.0.1` / duplicate local badge is gone;
- healthy backend consumes no permanent status real estate;
- backend failure produces a visible global error path to Diagnostics;
- Settings → Diagnostics shows runtime/version/local binding information;
- keyboard navigation/focus through sidebar remains usable.

### Dashboard / R03-03 + R03-04

Check:

- top level reads as four semantic blocks, not the old KPI-card wall;
- capital and monthly delta read as one idea;
- passive income clearly distinguishes Fact / Forecast / Goal;
- actual monthly passive income is bars; Forecast/Goal are reference markers, not fake actual series;
- incomplete rolling window is compact (`N мес. из 12` + help) rather than a permanent large warning;
- CLOSED-history gaps are visually gaps, not interpolated receipts;
- only overview charts remain; detailed investment/allocation content is not back on Dashboard;
- links to month list/current month/Analytics are obvious.

Blocker: anything that lets a user visually mistake Forecast or Goal for already received income.

### Goals / R03-09

Check:

- no wide goals table on the primary screen;
- main active goal is first and visually prominent;
- current / target / remaining + progress are readable without opening details;
- unavailable achievement date is concise and explanation is behind help;
- one visible `Изменить`; rare actions live in `⋯`;
- main goal cannot expose destructive deactivate/delete actions;
- inactive goals are collapsed in Archive by default;
- overflow menu works by mouse and keyboard and does not clip at viewport edges;
- cards move 2 → 1 columns without control collisions.

### Month workspace / R03-06

This is the most important interaction pass.

Check:

- one first-level working section is visible at a time;
- section navigation can jump directly to any section;
- direct URL such as `?section=assets` opens the correct section;
- section navigation does not silently save;
- edit a salary/input value, navigate away, navigate back: unsaved value remains;
- `beforeunload`/page-leave guard still triggers for dirty core fields;
- sticky header always makes month, status and current section understandable;
- `Сохранить` state is sensible for draft/closed/clean/dirty;
- warning/dirty indicators do not imply optional sections are required;
- `Проверить и закрыть` goes to review first;
- dirty core data cannot be closed;
- clean draft: Review → explicit Close confirmation → CLOSED;
- CLOSED: no giant lock-warning; `Открыть для редактирования` is visible and explicit;
- reopen restores editable state;
- sticky header does not overlap the section nav/content at `1366×768` or ~`1024px`;
- section nav wraps/compacts cleanly and remains usable by keyboard.

Important scope boundary: `MonthCloseoutSection` still contains old IIS / legacy goal fragment / comments / duplicate lifecycle content. Do not treat that as an R03-06 implementation miss. Its decomposition belongs to `R03-08`. Only fix it now if it creates a concrete R03-06 blocker such as two conflicting visible lifecycle actions in the same review flow.

## 4. Backend analytics checks — R03-11 / R03-12

Use a separate worktree or switch only after finishing/recording the UI branch state.

```powershell
git switch r03-12-capital-composition-api
git pull --ff-only
```

Run the project backend lint/test commands, at minimum the targeted capital-composition tests plus the proportional backend suite used by the repo.

Verify specifically:

- endpoint is `GET /api/analytics/capital-composition`;
- only CLOSED months are emitted;
- reopened month disappears until closed again;
- a missing calendar month is absent/unknown, never synthesized as zero;
- every known CLOSED month emits the five classes in the canonical order: `cash`, `deposits`, `stocks`, `bonds`, `gold_other`;
- a missing class inside a known month is explicit zero;
- `liquid_assets_total`, `included_debts`, and `liquid_capital_net` reconcile;
- Dashboard and analytics use the same shared asset-allocation classifier;
- exact-money boundary remains decimal strings / existing MoneyValue handling, no binary float.

Do not rewrite the ADR or financial semantics during runtime fixing. If a test reveals a contract contradiction, stop and report it for review.

## 5. What Hermes may fix during review

Allowed without expanding product scope:

- TypeScript/test/lint/build regressions caused by these branches;
- stale tests that assert the old UI structure;
- CSS overlap, spacing, responsive wrapping, focus, z-index or menu-position problems;
- broken labels/aria/focus behavior introduced by the new primitives/screens;
- obvious wiring bugs where the implementation does not match the already accepted R03 task-card.

Stop and report instead of improvising when a fix would:

- change financial formulas, money/rate semantics or source-of-truth rules;
- redesign the accepted 0.3 product hierarchy materially;
- implement R03-05, R03-07, R03-08, R03-10 or R03-13 while reviewing this bundle;
- add cloud/auth/telemetry/network exposure;
- require migration/schema changes;
- require force-push/rebase/reset/merge/PR/release.

## 6. Report format back to Nikita / Lera

Return one concise report with:

1. exact branch + HEAD tested;
2. commands run and pass/fail counts;
3. screenshots/visual notes for `1366×768` and ~`1024px` if practical, without committing real financial screenshots;
4. blockers first;
5. bounded fixes made, with files changed;
6. remaining non-blocking polish;
7. backend R03-12 targeted test result separately;
8. `git status --short` and confirmation that no private/generated data entered Git;
9. explicit statement that no merge/PR/release was performed.

Do not merge to `main` after review. Owner/Lera will choose the next action after reading the report.
