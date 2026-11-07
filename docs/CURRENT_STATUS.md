# Current state, limitations and next actions

Updated **2026-11-07**. This is the current status; product and numerical rules
remain in [P](MASTER_SPEC.md) and [C](ARCHITECTURE_AND_CONTRACTS.md), development
rules in [D](DEVELOPMENT.md), and operating procedures in [O](OWNER_RUNTIME_OPERATIONS.md).
The [previous complete status](archive/current-status-through-2026-11-05.md)
retains its original dated history and sources; it is not current installation evidence.

<a id="s1"></a>
## 1. Code, release, installation and UAT

- [v1.11.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.11.0)
  is published at `afd51ce9ca489d571ec4cc8ed0391eb05d45b43e` with
  [exact-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/42372946792)
  and [guarded publication](https://github.com/LTstripes/hermes-finance/actions/runs/42373803152)
  successful. It ships [#1110](https://github.com/LTstripes/hermes-finance/pull/1110),
  [#1113](https://github.com/LTstripes/hermes-finance/pull/1113) and redesign stages 1–2;
  [#1115](https://github.com/LTstripes/hermes-finance/pull/1115) prepared the release.
- 1.11.0 is installed on the Owner computer by backup-first OPS02 on 2026-11-07: the
  Stable checkout tag and the running health version read back as 1.11.0, and a
  pre-update SQLite backup exists in the update backup directory. The Owner reports
  that the app works and the interface looks right after a first use; a detailed
  numeric UAT of returns is not recorded and is not claimed.
- Redesign stages 3 and 4 ([#1117](https://github.com/LTstripes/hermes-finance/pull/1117),
  [#1116](https://github.com/LTstripes/hermes-finance/pull/1116)) are on main after
  1.11.0 and are not released; stage 5 is in review.

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

<a id="s3"></a>
## 3. Next actions

1. Verify 1.11.0 on Stable after a backup-first update, then continue the
   [#1079](https://github.com/LTstripes/hermes-finance/issues/1079) redesign with stage 3.
   Deferred returns findings: same-second purchases in FIFO and a historical closed
   REPO barrier.
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
