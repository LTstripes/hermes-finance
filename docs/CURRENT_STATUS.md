# Current state, limitations and next actions

Updated **2026-11-19**. This is the current status; product and numerical rules
remain in [P](MASTER_SPEC.md) and [C](ARCHITECTURE_AND_CONTRACTS.md), development
rules in [D](DEVELOPMENT.md), and operating procedures in [O](OWNER_RUNTIME_OPERATIONS.md).
The [previous complete status](archive/current-status-through-2026-11-05.md)
retains its original dated history and sources; it is not current installation evidence.

<a id="s1"></a>
## 1. Code, release, installation and UAT

- [v1.21.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.21.0)
  (`3d8d4e1098f27642902e52f76d3e32d841011425`, exact-main CI
  [43807791037](https://github.com/LTstripes/hermes-finance/actions/runs/43807791037),
  guarded publication
  [43808917512](https://github.com/LTstripes/hermes-finance/actions/runs/43808917512),
  [release notes](release-notes-1.21.0.md)) is installed on the Owner computer on
  2026-11-16 by backup-first OPS02, then Prepare and Start; health reads 1.21.0, the
  total income endpoint reads back for the calendar year, rolling 12 months and all
  time, "Весь доход" renders on Income and Home, and salary tax renders in a closed
  month report. Owner UAT has not been performed.
- [v1.20.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.20.0)
  (`91ad33b2d2c2d86f30c8f547d9d29b322327fc4d`, exact-main CI
  [43712083490](https://github.com/LTstripes/hermes-finance/actions/runs/43712083490),
  guarded publication
  [43713075819](https://github.com/LTstripes/hermes-finance/actions/runs/43713075819),
  [release notes](release-notes-1.20.0.md)) was installed on the Owner computer on
  2026-11-15 by backup-first OPS02, then Prepare and Start; health read 1.20.0, the
  page title read "Finance" and an invalid goal plan rate was rejected. It was
  superseded on Stable by 1.21.0.
- [v1.19.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.19.0)
  (`f6e244d50a8f546a87ad0757494989f2fbe644b8`, exact-main CI
  [43645700173](https://github.com/LTstripes/hermes-finance/actions/runs/43645700173),
  guarded publication
  [43646788043](https://github.com/LTstripes/hermes-finance/actions/runs/43646788043),
  [release notes](release-notes-1.19.0.md)) was installed on the Owner computer on
  2026-11-15 by backup-first OPS02, then Prepare and Start; health read 1.19.0 and the
  goal plan read back for the capital goal. It was superseded on Stable by 1.20.0.
- [v1.18.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.18.0)
  (`099e443641d350c822459c77b46f13c91072c358`, exact-main CI
  [43635231842](https://github.com/LTstripes/hermes-finance/actions/runs/43635231842),
  guarded publication
  [43636335678](https://github.com/LTstripes/hermes-finance/actions/runs/43636335678),
  [release notes](release-notes-1.18.0.md)) was installed on the Owner computer on
  2026-11-14 by backup-first OPS02, then Prepare and Start; health read 1.18.0 and
  the overall annual rate read back as provisional for the portfolio and both accounts.
  It was superseded on Stable by 1.19.0.
- [v1.17.1](https://github.com/LTstripes/hermes-finance/releases/tag/v1.17.1)
  (hotfix, `41260fe677518c1233972ae70ebb1abaa49e27c1`, exact-main CI
  [43620042362](https://github.com/LTstripes/hermes-finance/actions/runs/43620042362),
  guarded publication
  [43621817007](https://github.com/LTstripes/hermes-finance/actions/runs/43621817007),
  [release notes](release-notes-1.17.1.md)) was installed on the Owner computer on
  2026-11-14 by backup-first OPS02, then Prepare and Start; health read 1.17.1 and
  the returns overview carried short names again. Owner UAT was not performed.
  It was superseded on Stable by 1.18.0.
- [v1.17.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.17.0)
  is published at `229def1f296ceb70673a9772df9bebbcf14a9eb9` with
  [exact-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/43613070222)
  and [guarded publication](https://github.com/LTstripes/hermes-finance/actions/runs/43614408690)
  successful, with [release notes](release-notes-1.17.0.md).
- 1.17.0 was installed on the Owner computer on 2026-11-14 by backup-first OPS02,
  then Prepare and Start; the running health version read back 1.17.0, the page
  title read "Finance", and a pre-update SQLite backup was created in the update backup
  directory. Detailed numeric Owner UAT of 1.17.0 was not performed;
  it was superseded on Stable by 1.17.1.
- [v1.16.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.16.0)
  is published at `33496ec450f8ce7f8709e89e1e59c22b58cea2ae` with
  [exact-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/43474463116)
  and [guarded publication](https://github.com/LTstripes/hermes-finance/actions/runs/43476478277)
  successful, with [release notes](release-notes-1.16.0.md).
- 1.16.0 was installed on the Owner computer on 2026-11-13 by backup-first OPS02,
  then Prepare and Start; the running health version read back 1.16.0 and a
  pre-update SQLite backup was created in the update backup directory. Detailed numeric
  Owner UAT of 1.16.0 was not performed; it was superseded on Stable by 1.17.0.
- [v1.15.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.15.0)
  (`62f0a50eef0eb04c9ce031c39fbbf9fa49efacfc`, exact-main CI
  [42904115400](https://github.com/LTstripes/hermes-finance/actions/runs/42904115400),
  guarded publication
  [42958411450](https://github.com/LTstripes/hermes-finance/actions/runs/42958411450))
  was installed on 2026-11-11 and keeps its pre-update backup. Detailed
  numeric Owner UAT of 1.13.0–1.15.0 has not been performed and is not inferred
  from CI or copy checks.

<a id="s2"></a>
## 2. Integrated code and limitations

Spending diary [#1227](https://github.com/LTstripes/hermes-finance/issues/1227)
was integrated on 2026-11-18 in
[#1229](https://github.com/LTstripes/hermes-finance/pull/1229) and
[#1230](https://github.com/LTstripes/hermes-finance/pull/1230).
[Exact-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/44267030592)
passed for that feature merge. Finance 1.22.0 includes Alfa CSV and manual Markdown
imports, the spending overview, rules and migrations `0069_spending_diary` and
`0070_spending_screen`. Owner UAT is pending. See the
[release notes](release-notes-1.22.0.md) for preview limitations.

Shipped in 1.21.0 ([release notes](release-notes-1.21.0.md)), total income:
[#1221](https://github.com/LTstripes/hermes-finance/pull/1221) read-only total income
(salary, passive income and smoothed bonus) over CLOSED months for the calendar year,
rolling 12 months and all time, `GET /api/analytics/total-income`;
[#1222](https://github.com/LTstripes/hermes-finance/pull/1222) salary tax in Month
screens, mismatch shown above 1 000 ₽;
[#1223](https://github.com/LTstripes/hermes-finance/pull/1223) AI export income summary,
schema 1.5.0;
[#1224](https://github.com/LTstripes/hermes-finance/pull/1224) "Весь доход" on Income
and Home. No new migrations; the salary estimate before the first known salary is
analytical only and never stored.

Shipped in 1.20.0 ([release notes](release-notes-1.20.0.md)), cleanup after the 15.11.2026 audit:
[#1213](https://github.com/LTstripes/hermes-finance/pull/1213) short names on freshness, source income and statement returns;
[#1214](https://github.com/LTstripes/hermes-finance/pull/1214) goal plan validation and visible required contribution;
[#1215](https://github.com/LTstripes/hermes-finance/pull/1215) field-anchored version bump and "Finance X.Y.Z" release title;
[#1216](https://github.com/LTstripes/hermes-finance/pull/1216) editor focus fix and stable tests;
[#1217](https://github.com/LTstripes/hermes-finance/pull/1217) dead code and wording;
[#1218](https://github.com/LTstripes/hermes-finance/pull/1218) pypdf 6.21.4 and frontend dev tools. No new migrations; no financial calculation changes.

Shipped in 1.19.0 ([release notes](release-notes-1.19.0.md)):
[#1209](https://github.com/LTstripes/hermes-finance/pull/1209) goal plan (`goal_plan_v1`,
closes #1129 MVP) and passive-income capital estimate;
[#1208](https://github.com/LTstripes/hermes-finance/pull/1208) quiet instrument links.
No new migrations.

Shipped in 1.18.0 ([release notes](release-notes-1.18.0.md)):
[#1205](https://github.com/LTstripes/hermes-finance/pull/1205) overall annual portfolio
rate (B9): annual XIRR over brokerage and IIS accounts from the first operation;
provisional between 90 and 365 capital-weighted days, hidden below 90; annual return
and securities realized/unrealized results in the AI export. No new migrations.

Shipped in 1.17.0 ([release notes](release-notes-1.17.0.md)); 1.17.1 ([release notes](release-notes-1.17.1.md)) fixes missing short names in the returns overview ([#1202](https://github.com/LTstripes/hermes-finance/pull/1202)):

- Speed: [#1199](https://github.com/LTstripes/hermes-finance/pull/1199) bounded
  read cache keyed by the whole committed SQLite snapshot (repeat reads of Returns
  and Month in hundredths of a second, byte-identical responses), Home returns
  summary (B3) and idle prefetch; [#1189](https://github.com/LTstripes/hermes-finance/pull/1189);
  lazy month position and securities results in [#1194](https://github.com/LTstripes/hermes-finance/pull/1194).
- Returns: [#1193](https://github.com/LTstripes/hermes-finance/pull/1193) realized and
  unrealized result per instrument (FIFO, semantics v22);
  [#1198](https://github.com/LTstripes/hermes-finance/pull/1198) one server short
  instrument name everywhere (B8) and the gold FIFO split (semantics v23);
  [#1191](https://github.com/LTstripes/hermes-finance/pull/1191) annual XIRR for fully
  redeemed bonds; audit tails B1, B2, B5, B6, B7, B10-B12 in #1193/#1194.
- Month and gold: [#1187](https://github.com/LTstripes/hermes-finance/pull/1187),
  [#1195](https://github.com/LTstripes/hermes-finance/pull/1195).
- Visible product name "Finance" ([#1197](https://github.com/LTstripes/hermes-finance/pull/1197),
  stage 1 of [#1196](https://github.com/LTstripes/hermes-finance/issues/1196); internal
  names, env vars and the AI export application name unchanged).
- Tests, CI and status: [#1188](https://github.com/LTstripes/hermes-finance/pull/1188),
  [#1190](https://github.com/LTstripes/hermes-finance/pull/1190),
  [#1192](https://github.com/LTstripes/hermes-finance/pull/1192).

There were no new database migrations from 1.16.0 through 1.21.0. Green CI and copy checks do not
establish Owner UAT.

Changes since 1.15.0, shipped in 1.16.0 — the full UI audit of 10–11.11.2026 and
faster returns reads:

- Returns: [#1169](https://github.com/LTstripes/hermes-finance/pull/1169) halves the remaining returns read times with byte-identical
  responses; [#1170](https://github.com/LTstripes/hermes-finance/pull/1170) one row per instrument and catalogue account names;
  [#1172](https://github.com/LTstripes/hermes-finance/pull/1172) «По месяцам» in the overview layout.
- Month: [#1167](https://github.com/LTstripes/hermes-finance/pull/1167) honest draft totals before statements; [#1168](https://github.com/LTstripes/hermes-finance/pull/1168) and [#1171](https://github.com/LTstripes/hermes-finance/pull/1171)
  shared money field, inline deposits and one edit pattern; [#1177](https://github.com/LTstripes/hermes-finance/pull/1177) statements panel.
- Home, capital, income and plans: [#1176](https://github.com/LTstripes/hermes-finance/pull/1176), [#1177](https://github.com/LTstripes/hermes-finance/pull/1177), [#1173](https://github.com/LTstripes/hermes-finance/pull/1173), [#1181](https://github.com/LTstripes/hermes-finance/pull/1181).
- Navigation and settings: [#1178](https://github.com/LTstripes/hermes-finance/pull/1178), [#1179](https://github.com/LTstripes/hermes-finance/pull/1179), [#1180](https://github.com/LTstripes/hermes-finance/pull/1180), [#1175](https://github.com/LTstripes/hermes-finance/pull/1175).
- Formats, wide screens, accessibility and mobile: [#1174](https://github.com/LTstripes/hermes-finance/pull/1174), [#1182](https://github.com/LTstripes/hermes-finance/pull/1182), [#1183](https://github.com/LTstripes/hermes-finance/pull/1183).
- Test stability: [#1180](https://github.com/LTstripes/hermes-finance/pull/1180), [#1184](https://github.com/LTstripes/hermes-finance/pull/1184); status record [#1166](https://github.com/LTstripes/hermes-finance/pull/1166).

There are no new database migrations in 1.16.0 since 1.15.0. Green CI and copy
checks do not establish Owner UAT.

<a id="s3"></a>
## 3. Next actions

For the spending diary, the Owner acceptance scenario is one Alfa CSV and one
manual Markdown file for the same month, followed by preview, application and
reconciliation of the resulting monthly total. Historical imports follow that check.

1. The Owner monitors numbers in everyday use and reports problems as new issues
   (formal UAT card #711 closed on 14.11.2026). At month close the Owner compares
   deposit balances with the bank on the snapshot date.
2. Candidate development, Owner to choose: goal plan pauses and one-off expenses
   (#1129 extension), actual monthly saving, payout reconciliation exceptions
   ([#1033](https://github.com/LTstripes/hermes-finance/issues/1033)).
3. Deferred by the Owner: annual tax and IIS reconciliation
   ([#1130](https://github.com/LTstripes/hermes-finance/issues/1130), documents first);
   a market-data supplement for amortizing bonds (until one is held).
4. Never infer UAT from green CI. No financial Apply/Close or data repair is
   implied by release.

<a id="s4"></a>
## 4. Evidence boundaries

Financial records, credentials, database identities and local paths stay private.
Preserve receipt history and confirmed data; unknown values are not zeros.
Historical issue, PR and installation receipts retain their original scope in
[the archived status](archive/current-status-through-2026-11-05.md), including
unresolved source and valuation limitations. Review pending changes separately;
no draft PR is production code.
