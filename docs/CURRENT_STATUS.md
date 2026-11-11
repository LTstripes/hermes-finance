# Current state, limitations and next actions

Updated **2026-11-11**. This is the current status; product and numerical rules
remain in [P](MASTER_SPEC.md) and [C](ARCHITECTURE_AND_CONTRACTS.md), development
rules in [D](DEVELOPMENT.md), and operating procedures in [O](OWNER_RUNTIME_OPERATIONS.md).
The [previous complete status](archive/current-status-through-2026-11-05.md)
retains its original dated history and sources; it is not current installation evidence.

<a id="s1"></a>
## 1. Code, release, installation and UAT

- [v1.15.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.15.0)
  is published at `62f0a50eef0eb04c9ce031c39fbbf9fa49efacfc` with
  [exact-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/42904115400)
  and [guarded publication](https://github.com/LTstripes/hermes-finance/actions/runs/42958411450)
  successful, with [release notes](release-notes-1.15.0.md).
- 1.15.0 is installed on the Owner computer on 2026-11-11 by backup-first OPS02,
  then Prepare and Start; the running health version reads back 1.15.0 and a
  pre-update SQLite backup exists in the update backup directory. Detailed numeric
  Owner UAT of 1.15.0 has not been performed.
- [v1.14.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.14.0)
  (`c4e91bd496c602a6496ec018caff473ac83fa1b4`, exact-main CI
  [42571502233](https://github.com/LTstripes/hermes-finance/actions/runs/42571502233),
  guarded publication
  [42572541752](https://github.com/LTstripes/hermes-finance/actions/runs/42572541752))
  was installed on 2026-11-09 and keeps its pre-update backup. Detailed
  numeric Owner UAT of 1.13.0 and 1.14.0 has not been performed and is not inferred
  from CI or copy checks.

<a id="s2"></a>
## 2. Shipped code and limitations

Changes since 1.14.0, shipped in 1.15.0:

- [#1156](https://github.com/LTstripes/hermes-finance/pull/1156) takes the market
  line of the capital bridge from statements and shows the capital-vs-statement
  valuation difference as its own line.
- [#1157](https://github.com/LTstripes/hermes-finance/pull/1157) removes forced
  refetches (data refresh after writes and on «Обновить»), speeds up the close check
  and deduplicates close messages.
- [#1160](https://github.com/LTstripes/hermes-finance/pull/1160) keeps unattributed
  bond amortization from producing a fake loss (UNKNOWN instead; a resolved
  registration number limits it to that issue) and limits IIS month flows to the
  month end (semantics v20).
- [#1162](https://github.com/LTstripes/hermes-finance/pull/1162) reads the account
  and period returns in seconds instead of minutes with byte-identical responses.
- UI from the 10.11.2026 audit:
  [#1158](https://github.com/LTstripes/hermes-finance/pull/1158),
  [#1159](https://github.com/LTstripes/hermes-finance/pull/1159),
  [#1161](https://github.com/LTstripes/hermes-finance/pull/1161),
  [#1163](https://github.com/LTstripes/hermes-finance/pull/1163) and
  [#1164](https://github.com/LTstripes/hermes-finance/pull/1164) (month positions,
  close screen, month step pages, shared formats, returns overview, instrument page,
  loading skeletons).

There are no new database migrations since 1.14.0. Green CI and copy checks do not
establish Owner UAT. Returns summaries and one instrument card still take about
16 s on the installed data.

<a id="s3"></a>
## 3. Next actions

1. Owner UAT of installed 1.15.0 of the returns screens, the month pages and the close screen,
   together with the pending UAT of 1.13.0 and 1.14.0.
2. Remaining UI audit tasks (navigation, payouts forecast, capital table, settings,
   mobile) through Codex; returns summaries speed.
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
