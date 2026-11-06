# Current state, limitations and next actions

Updated **2026-11-07**. This is the current status; product and numerical rules
remain in [P](MASTER_SPEC.md) and [C](ARCHITECTURE_AND_CONTRACTS.md), development
rules in [D](DEVELOPMENT.md), and operating procedures in [O](OWNER_RUNTIME_OPERATIONS.md).
The [previous complete status](archive/current-status-through-2026-11-05.md)
retains its original dated history and sources; it is not current installation evidence.

<a id="s1"></a>
## 1. Code, release, installation and UAT

- [v1.10.7](https://github.com/LTstripes/hermes-finance/releases/tag/v1.10.7)
  is published at `d15b848292905adf96c0b19bdf317a337294baa3` with
  [exact-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/42299407474)
  and [guarded publication](https://github.com/LTstripes/hermes-finance/actions/runs/42301024582)
  successful. [#1105](https://github.com/LTstripes/hermes-finance/pull/1105)
  completed historical clean stock and bond returns;
  [#1106](https://github.com/LTstripes/hermes-finance/pull/1106) prepared the release.
- 1.10.7 is installed on the Owner computer: the Owner reported the update, and
  the running Stable health response, checkout tag and prepared runtime identity
  all match the release. This readback does not verify data continuity or a
  pre-update backup; neither is recorded here.
- The five-real-security private UAT was **NOT PERFORMED**: the Owner waived it
  as a gate for this version in [#1016](https://github.com/LTstripes/hermes-finance/issues/1016).
  No five-security validation or Owner UX PASS is claimed.
- An isolated instrument-UAT snapshot was refused by preflight; the cause remains
  unknown. UAT was not completed. Do not bypass or blindly retry the refusal.
  [#1094](https://github.com/LTstripes/hermes-finance/pull/1094) proposes
  bounded diagnostics; it is not a released capability.

<a id="s2"></a>
## 2. Shipped code and limitations

The 1.10.7 source includes available clean instrument returns, display of known
parts, a cost/movements and received-income breakdown, and FIFO purchase
analytics. Fees, taxes and accrued interest do not enter the clean return;
missing facts remain unknown. Dividend/coupon income is shown at instrument
level and is not allocated to individual purchases. The ordinary overview,
card and AI projections share the relevant source basis and coverage. These are
release-code capabilities, not proof of installed behavior or Owner acceptance.

A read-only comparison of five instruments including X5 and Sber was reported
on one working account and period; it checked calculation code, not the interface
or longer history. Synthetic tests and independent financial/UI review cover the
candidate, not every real account, period or private-data UAT.

<a id="s3"></a>
## 3. Next actions

1. Finish the returns follow-ups in [#963](https://github.com/LTstripes/hermes-finance/issues/963)
   and [#1089](https://github.com/LTstripes/hermes-finance/issues/1089), then begin the
   staged interface work in [#1079](https://github.com/LTstripes/hermes-finance/issues/1079).
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
