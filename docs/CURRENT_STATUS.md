# Current state, limitations and next actions

Updated **2026-11-09**. This is the current status; product and numerical rules
remain in [P](MASTER_SPEC.md) and [C](ARCHITECTURE_AND_CONTRACTS.md), development
rules in [D](DEVELOPMENT.md), and operating procedures in [O](OWNER_RUNTIME_OPERATIONS.md).
The [previous complete status](archive/current-status-through-2026-11-05.md)
retains its original dated history and sources; it is not current installation evidence.

<a id="s1"></a>
## 1. Code, release, installation and UAT

- 1.14.0 is prepared on main for guarded publication with
  [release notes](release-notes-1.14.0.md). Publication, the tag and the Stable
  installation are recorded here only after their read-back.
- [v1.13.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.13.0)
  (`bbf4197e4545be554dc2425b95354a18dff19fb1`) is the installed Stable version since
  2026-11-08 (backup-first OPS02, Prepare and Start; health read back 1.13.0). Its
  pre-update backup is retained. Detailed numeric Owner UAT of 1.13.0 has not been
  performed and is not inferred from CI or copy checks.

<a id="s2"></a>
## 2. Shipped code and limitations

Changes since 1.13.0, prepared for 1.14.0:

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

1. Publish 1.14.0 through the guarded route and install it on Stable backup-first,
   then Owner UAT of the capital bridge and the IIS forms, together with the pending
   UAT of 1.13.0 and the redesign (#963, #1014, #711).
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
