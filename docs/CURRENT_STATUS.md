# Current state, limitations and next actions

Updated **2026-11-09**. This is the current status; product and numerical rules
remain in [P](MASTER_SPEC.md) and [C](ARCHITECTURE_AND_CONTRACTS.md), development
rules in [D](DEVELOPMENT.md), and operating procedures in [O](OWNER_RUNTIME_OPERATIONS.md).
The [previous complete status](archive/current-status-through-2026-11-05.md)
retains its original dated history and sources; it is not current installation evidence.

<a id="s1"></a>
## 1. Code, release, installation and UAT

- [v1.13.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.13.0)
  is published at `bbf4197e4545be554dc2425b95354a18dff19fb1` with
  [exact-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/42504077344)
  and [guarded publication](https://github.com/LTstripes/hermes-finance/actions/runs/42504946525)
  successful, with [release notes](release-notes-1.13.0.md).
- 1.13.0 is installed on the Owner computer on 2026-11-08 by backup-first OPS02,
  then Prepare and Start; the running health version reads back 1.13.0 and a
  pre-update SQLite backup exists in the update backup directory. Detailed numeric
  Owner UAT of 1.13.0 has not been performed and is not inferred from CI or copy checks.
- Main after 1.13.0, not released (the Owner holds the next release to combine it
  with upcoming work): #1146 and #1147 (IIS forms scroll, edit and delete of
  contributions and deductions), #1148 and #1149 (full bond redemption from
  exchange-code cancellation rows and the resulting closed-position result,
  semantics v17 and v18), #1150 and #1151 (monthly capital bridge through the
  month's flow, with a card-debt hint).
- The previous release [v1.12.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.12.0)
  (`067b6be1a5d5957643d50e996ffda647ba9ac891`) keeps its pre-update backup.

<a id="s2"></a>
## 2. Shipped code and limitations

Changes since 1.12.0, prepared for 1.13.0:

- [#1140](https://github.com/LTstripes/hermes-finance/pull/1140) attributes clean
  coupons by exact issue identity before issuer text, keeps ambiguous payouts
  unattributed, resolves extended dividend narratives by an explicit registration
  bridge and recovers a full bond redemption only from a current custody
  cancellation with exact quantity, nominal and cash (semantics v14).
- [#1141](https://github.com/LTstripes/hermes-finance/pull/1141) reconciles a bond
  sale with its separate NKD money only on an exact kopeck match; otherwise the sale
  stays without a result (semantics v15).
- [#1142](https://github.com/LTstripes/hermes-finance/pull/1142) adds per-position
  simple return on invested and annual XIRR, published only for a capital-weighted
  holding of at least 365 days (Owner decision on
  [#1016](https://github.com/LTstripes/hermes-finance/issues/1016); semantics v16).
  [#1144](https://github.com/LTstripes/hermes-finance/pull/1144) shows both rates on
  Returns and the instrument card instead of the position Modified Dietz.
- [#1143](https://github.com/LTstripes/hermes-finance/pull/1143) moves the AI export
  to 3.2.0 with names, payments, per-ISIN summaries, labeled rates and position
  rates; [#1139](https://github.com/LTstripes/hermes-finance/pull/1139) removed the
  export formats the UI did not use.
- [#1136](https://github.com/LTstripes/hermes-finance/pull/1136),
  [#1137](https://github.com/LTstripes/hermes-finance/pull/1137) and
  [#1138](https://github.com/LTstripes/hermes-finance/pull/1138) remove dead code and
  fix the guided Stable updater on Windows PowerShell 5.1.

Read-only copy checks: full position results 24 to 27 and purchases with a result
236 to 239, with no open position degraded. A full bond redemption without a current
custody cancellation proof and registration bridge remains unknown. There are no new
database migrations since 1.12.0. Green CI and copy checks do not establish Owner UAT.

<a id="s3"></a>
## 3. Next actions

1. Owner UAT of installed 1.13.0: Returns rates, the instrument card and the 3.2.0
   export, together with the pending redesign UAT (#963, #1014, #711). The next
   release waits for the Owner's go-ahead and then ships main since 1.13.0.
2. Owner data actions that unlock remaining results: record one-off card purchases
   as month expenses so the capital bridge reconciles, and classify the remaining
   unclassified account money. The registration bridge and catalogue fixes of
   2026-11-08 are done.
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
