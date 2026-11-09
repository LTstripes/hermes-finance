# Current state, limitations and next actions

Updated **2026-11-09**. This is the current status; product and numerical rules
remain in [P](MASTER_SPEC.md) and [C](ARCHITECTURE_AND_CONTRACTS.md), development
rules in [D](DEVELOPMENT.md), and operating procedures in [O](OWNER_RUNTIME_OPERATIONS.md).
The [previous complete status](archive/current-status-through-2026-11-05.md)
retains its original dated history and sources; it is not current installation evidence.

<a id="s1"></a>
## 1. Code, release, installation and UAT

- [v1.14.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.14.0)
  is published at `c4e91bd496c602a6496ec018caff473ac83fa1b4` with
  [exact-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/42571502233)
  and [guarded publication](https://github.com/LTstripes/hermes-finance/actions/runs/42572541752)
  successful, with [release notes](release-notes-1.14.0.md).
- 1.14.0 is installed on the Owner computer on 2026-11-09 by backup-first OPS02,
  then Prepare and Start; the running health version reads back 1.14.0 and a
  pre-update SQLite backup exists in the update backup directory. A read-only check
  of the installed data shows the redeemed bond with a full result and the capital
  bridge with its card-debt and market-line hints. Detailed numeric Owner UAT of
  1.14.0 has not been performed.
- The previous release [v1.13.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.13.0)
  (`bbf4197e4545be554dc2425b95354a18dff19fb1`) keeps its pre-update backup.

<a id="s2"></a>
## 2. Shipped code and limitations

Changes since 1.13.0, shipped in 1.14.0:

- [#1150](https://github.com/LTstripes/hermes-finance/pull/1150) and
  [#1151](https://github.com/LTstripes/hermes-finance/pull/1151) explain the monthly
  capital change through the month's flow before savings, the market change of
  brokerage and IIS without payouts already in the flow, physical gold revaluation
  and an explicit residual, with a card-debt hint;
  [#1153](https://github.com/LTstripes/hermes-finance/pull/1153) names the next step
  when the market line is unknown. The previous breakdown remains for its consumers.
- [#1148](https://github.com/LTstripes/hermes-finance/pull/1148) recognizes a full
  bond redemption from cancellation rows with an exchange issue code and padded
  quantity (semantics v17); [#1149](https://github.com/LTstripes/hermes-finance/pull/1149)
  closes a position by that redemption for a full result (semantics v18).
- [#1146](https://github.com/LTstripes/hermes-finance/pull/1146) and
  [#1147](https://github.com/LTstripes/hermes-finance/pull/1147) scroll to the IIS forms
  and add edit and delete of IIS contributions and deductions.

The market line stays unknown where capital snapshots and statements disagree at a
month boundary or a monthly statement is missing; the bridge then says what to
reconcile. There are no new database migrations since 1.13.0. Green CI and copy
checks do not establish Owner UAT.

<a id="s3"></a>
## 3. Next actions

1. Owner UAT of installed 1.14.0: the capital bridge and the IIS forms, together
   with the pending UAT of 1.13.0 and the redesign (#963, #1014, #711).
2. Owner data actions for the capital bridge: record one-off card purchases as month
   expenses, reconcile the capital snapshot with the statements at the named month
   boundaries, confirm the remaining assumed account deposit and add the missing
   monthly IIS statement.
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
