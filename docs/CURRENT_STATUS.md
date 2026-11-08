# Current state, limitations and next actions

Updated **2026-11-08**. This is the current status; product and numerical rules
remain in [P](MASTER_SPEC.md) and [C](ARCHITECTURE_AND_CONTRACTS.md), development
rules in [D](DEVELOPMENT.md), and operating procedures in [O](OWNER_RUNTIME_OPERATIONS.md).
The [previous complete status](archive/current-status-through-2026-11-05.md)
retains its original dated history and sources; it is not current installation evidence.

<a id="s1"></a>
## 1. Code, release, installation and UAT

- 1.13.0 is prepared on main for guarded publication with
  [release notes](release-notes-1.13.0.md). Publication, the tag and the Stable
  installation are recorded here only after their read-back.
- [v1.12.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.12.0)
  (`067b6be1a5d5957643d50e996ffda647ba9ac891`) is the installed Stable version since
  2026-11-08 (backup-first OPS02, Prepare and Start; health read back 1.12.0). Its
  pre-update backup is retained. Detailed numeric Owner UAT of 1.12.0 has not been
  performed and is not inferred from CI or snapshot checks.

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

1. Publish 1.13.0 through the guarded route, install it on Stable backup-first,
   then Owner UAT of the Returns rates, the instrument card and the 3.2.0 export,
   together with the pending 1.12.0 redesign UAT (#963, #1014, #711).
2. Owner data actions that unlock remaining results: re-confirm the current source
   reports where a stored cancellation proof is stale, add the missing registration
   bridge, and fix catalogue types and duplicates.
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
