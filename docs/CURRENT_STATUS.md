# Current state, limitations and next actions

Updated **2026-11-08**. This is the current status; product and numerical rules
remain in [P](MASTER_SPEC.md) and [C](ARCHITECTURE_AND_CONTRACTS.md), development
rules in [D](DEVELOPMENT.md), and operating procedures in [O](OWNER_RUNTIME_OPERATIONS.md).
The [previous complete status](archive/current-status-through-2026-11-05.md)
retains its original dated history and sources; it is not current installation evidence.

<a id="s1"></a>
## 1. Code, release, installation and UAT

- [v1.12.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.12.0)
  is published at `067b6be1a5d5957643d50e996ffda647ba9ac891` with
  [exact-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/42464520127)
  and [guarded publication](https://github.com/LTstripes/hermes-finance/actions/runs/42465353065)
  successful, with [release notes](release-notes-1.12.0.md). It ships redesign
  stages 3–5, #1120–#1127 and #1133.
- 1.12.0 is installed on the Owner computer on 2026-11-08 by backup-first OPS02,
  then Prepare and Start: the Stable checkout tag and the running health version
  read back as 1.12.0, and a pre-update SQLite backup exists in the update backup
  directory. The guided wrapper stopped before OPS02 on Windows PowerShell 5.1 git
  stderr ([#1138](https://github.com/LTstripes/hermes-finance/pull/1138) fixes it);
  OPS02 itself was run directly with the same arguments. Detailed numeric Owner UAT
  of 1.12.0 has not been performed and is not inferred from CI or snapshot checks.
- The previous release [v1.11.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.11.0)
  (`afd51ce9ca489d571ec4cc8ed0391eb05d45b43e`) shipped #1110, #1113 and redesign
  stages 1–2; its pre-update backup is retained.

<a id="s2"></a>
## 2. Shipped code and limitations

The 1.11.0 source proves each instrument from its own trades reconciled to
statement quantities, so other issues' rows and unattributed account money no
longer withhold its result; unattributed money adds one note. Bonds use one
NKD-inclusive basis (Owner decision 2026-11-07, see C): trade totals with NKD,
the statement position value and full coupons; fees and taxes stay excluded.
Contradicting linked trade money, differing statement totals and ambiguous
coupon links still withhold the result. A read-only snapshot check showed a full
result for every open position; older closed positions of unknown type without
a closing quantity remain without one. Stage 1 and 2 of the
[#1079](https://github.com/LTstripes/hermes-finance/issues/1079) redesign ship
the new tokens, shell, working-month plate and the Month summary and checklist.
These are release-code capabilities, not proof of installed behavior or Owner
acceptance.

Changes since 1.11.0, shipped in 1.12.0:

- Redesign stages 3–5 of #1079: Home ([#1117](https://github.com/LTstripes/hermes-finance/pull/1117)),
  Income and Capital ([#1116](https://github.com/LTstripes/hermes-finance/pull/1116)),
  Returns and instrument details ([#1118](https://github.com/LTstripes/hermes-finance/pull/1118)).
  Partial results remain marked; the component equality requires complete values.
- [#1120](https://github.com/LTstripes/hermes-finance/pull/1120) resolves same-second
  purchases and historical closed REPO only where execution/settlement evidence
  proves the result. Ambiguous FIFO order remains unavailable.
- [#1121](https://github.com/LTstripes/hermes-finance/pull/1121) adds version preparation
  and exact-main release requests; [#1122](https://github.com/LTstripes/hermes-finance/pull/1122)
  adds guided backup-first Stable updates with separate Start.
- [#1123](https://github.com/LTstripes/hermes-finance/pull/1123) stabilizes browser CI
  without relaxing assertions; [#1127](https://github.com/LTstripes/hermes-finance/pull/1127)
  aligns Month tests with the current workspace and retains unique legacy coverage.
- [#1124](https://github.com/LTstripes/hermes-finance/pull/1124) adds an Owner-local
  read-only returns snapshot check; its private outputs stay outside Git/CI.
- [#1125](https://github.com/LTstripes/hermes-finance/pull/1125) names accounts missing
  capital snapshots; [#1126](https://github.com/LTstripes/hermes-finance/pull/1126)
  reuses reads within a protected request snapshot, preserving proof/currentness rules.
- [#1133](https://github.com/LTstripes/hermes-finance/pull/1133) infers sold-out positions
  only from balanced trades and absence in the final statement; investment semantics
  v13 retains v12 receipt compatibility. Its read-only copy check improved one closed
  position while open positions were unchanged. Remaining incomplete trades, payouts,
  redemptions and valuations still withhold full results.

There are no new database migrations since 1.11.0. Green CI and earlier read-only
copy checks do not establish Owner UAT of 1.12.0.

<a id="s3"></a>
## 3. Next actions

1. Owner UAT of installed 1.12.0, including the redesign (#963, #1014, #711).
   Continue #1079 only with the Owner's next accepted scope. Cleanup from audit
   [#1135](https://github.com/LTstripes/hermes-finance/issues/1135) proceeds as
   separate reviewed PRs.
2. Apply the Owner's proportional verification rule: use an isolated Test or
   manual acceptance when the change or an explicit accepted gate requires it;
   state whether it was performed. Never infer UAT from green CI.
3. Maintain distinct source-only observations, accepted financial facts and
   CLOSED history. No financial Apply/Close or data repair is implied by release.

<a id="s4"></a>
## 4. Evidence boundaries

Financial records, credentials, database identities and local paths stay private.
Preserve receipt history and confirmed data; unknown values are not zeros.
Historical issue, PR and installation receipts retain their original scope in
[the archived status](archive/current-status-through-2026-11-05.md), including
unresolved source and valuation limitations. Review pending changes separately;
no draft PR is production code.
