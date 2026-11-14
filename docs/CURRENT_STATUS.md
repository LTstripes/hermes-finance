# Current state, limitations and next actions

Updated **2026-11-14**. This is the current status; product and numerical rules
remain in [P](MASTER_SPEC.md) and [C](ARCHITECTURE_AND_CONTRACTS.md), development
rules in [D](DEVELOPMENT.md), and operating procedures in [O](OWNER_RUNTIME_OPERATIONS.md).
The [previous complete status](archive/current-status-through-2026-11-05.md)
retains its original dated history and sources; it is not current installation evidence.

<a id="s1"></a>
## 1. Code, release, installation and UAT

- [v1.17.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.17.0)
  is published at `229def1f296ceb70673a9772df9bebbcf14a9eb9` with
  [exact-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/43613070222)
  and [guarded publication](https://github.com/LTstripes/hermes-finance/actions/runs/43614408690)
  successful, with [release notes](release-notes-1.17.0.md).
- 1.17.0 is installed on the Owner computer on 2026-11-14 by backup-first OPS02,
  then Prepare and Start; the running health version reads back 1.17.0, the page
  title reads "Finance", and a pre-update SQLite backup exists in the update backup
  directory. Detailed numeric Owner UAT of 1.17.0 has not been performed.
- [v1.16.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.16.0)
  is published at `33496ec450f8ce7f8709e89e1e59c22b58cea2ae` with
  [exact-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/43474463116)
  and [guarded publication](https://github.com/LTstripes/hermes-finance/actions/runs/43476478277)
  successful, with [release notes](release-notes-1.16.0.md).
- 1.16.0 is installed on the Owner computer on 2026-11-13 by backup-first OPS02,
  then Prepare and Start; the running health version reads back 1.16.0 and a
  pre-update SQLite backup exists in the update backup directory. Detailed numeric
  Owner UAT of 1.16.0 has not been performed; it was superseded on Stable by 1.17.0.
- [v1.15.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.15.0)
  (`62f0a50eef0eb04c9ce031c39fbbf9fa49efacfc`, exact-main CI
  [42904115400](https://github.com/LTstripes/hermes-finance/actions/runs/42904115400),
  guarded publication
  [42958411450](https://github.com/LTstripes/hermes-finance/actions/runs/42958411450))
  was installed on 2026-11-11 and keeps its pre-update backup. Detailed
  numeric Owner UAT of 1.13.0–1.15.0 has not been performed and is not inferred
  from CI or copy checks.

<a id="s2"></a>
## 2. Shipped code and limitations

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

Shipped in 1.17.0 ([release notes](release-notes-1.17.0.md)):

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

No new database migrations since 1.16.0. Green CI and copy checks do not
establish Owner UAT.

<a id="s3"></a>
## 3. Next actions

1. Owner UAT of installed 1.17.0 together with the pending UAT of 1.13.0-1.16.0,
   tracked in [#711](https://github.com/LTstripes/hermes-finance/issues/711).
2. Development: overall portfolio annual rate (B9) by the Owner rule of 14.11.2026:
   annual XIRR over brokerage and IIS accounts from the first operation; own
   transfers are not income.
3. Deferred by the Owner: annual tax and IIS reconciliation
   ([#1130](https://github.com/LTstripes/hermes-finance/issues/1130), documents first);
   a market-data supplement for amortizing bonds (until one is held).
4. Apply the proportional verification rule of the Owner and never infer UAT from
   green CI. No financial Apply/Close or data repair is implied by release.

<a id="s4"></a>
## 4. Evidence boundaries

Financial records, credentials, database identities and local paths stay private.
Preserve receipt history and confirmed data; unknown values are not zeros.
Historical issue, PR and installation receipts retain their original scope in
[the archived status](archive/current-status-through-2026-11-05.md), including
unresolved source and valuation limitations. Review pending changes separately;
no draft PR is production code.
