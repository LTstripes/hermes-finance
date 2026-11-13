# Current state, limitations and next actions

Updated **2026-11-13**. This is the current status; product and numerical rules
remain in [P](MASTER_SPEC.md) and [C](ARCHITECTURE_AND_CONTRACTS.md), development
rules in [D](DEVELOPMENT.md), and operating procedures in [O](OWNER_RUNTIME_OPERATIONS.md).
The [previous complete status](archive/current-status-through-2026-11-05.md)
retains its original dated history and sources; it is not current installation evidence.

<a id="s1"></a>
## 1. Code, release, installation and UAT

- [v1.16.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.16.0)
  is published at `33496ec450f8ce7f8709e89e1e59c22b58cea2ae` with
  [exact-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/43474463116)
  and [guarded publication](https://github.com/LTstripes/hermes-finance/actions/runs/43476478277)
  successful, with [release notes](release-notes-1.16.0.md).
- 1.16.0 is installed on the Owner computer on 2026-11-13 by backup-first OPS02,
  then Prepare and Start; the running health version reads back 1.16.0 and a
  pre-update SQLite backup exists in the update backup directory. Detailed numeric
  Owner UAT of 1.16.0 has not been performed.
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

There are no new database migrations since 1.15.0. The legacy month editor
(`/v2/data/months/:id`) stays reachable: the month panels have no equivalent of its
confirmed re-read with form reload. Green CI and copy checks do not establish Owner UAT.

<a id="s3"></a>
## 3. Next actions

1. Owner UAT of installed 1.16.0 of the redesigned screens together with the pending UAT of
   1.13.0–1.15.0.
2. Remaining leftovers: a confirmed re-read action in the month panels before the
   legacy editor can redirect; backend item B11 for task 26.D; the cloned draft month
   marks income and expenses «Не заполнено» while rows exist.
3. Apply the Owner's proportional verification rule and never infer UAT from green
   CI. No financial Apply/Close or data repair is implied by release.

<a id="s4"></a>
## 4. Evidence boundaries

Financial records, credentials, database identities and local paths stay private.
Preserve receipt history and confirmed data; unknown values are not zeros.
Historical issue, PR and installation receipts retain their original scope in
[the archived status](archive/current-status-through-2026-11-05.md), including
unresolved source and valuation limitations. Review pending changes separately;
no draft PR is production code.
