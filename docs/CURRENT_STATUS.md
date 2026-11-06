# Current state, limitations and next actions

Updated **2026-11-06**. This is the current status; product and numerical rules
remain in [P](MASTER_SPEC.md) and [C](ARCHITECTURE_AND_CONTRACTS.md), development
rules in [D](DEVELOPMENT.md), and operating procedures in [O](OWNER_RUNTIME_OPERATIONS.md).
The [previous complete status](archive/current-status-through-2026-11-05.md)
retains its original dated history and sources; it is not current installation evidence.

<a id="s1"></a>
## 1. Code, release, installation and UAT

- [v1.10.6](https://github.com/LTstripes/hermes-finance/releases/tag/v1.10.6)
  is published at `4b7ab0242f706c8cbe40a498ccb8e68c97c98df9` with
  [exact-main CI](https://github.com/LTstripes/hermes-finance/actions/runs/42196856391)
  and [guarded publication](https://github.com/LTstripes/hermes-finance/actions/runs/42198072800)
  successful. [#1092](https://github.com/LTstripes/hermes-finance/pull/1092)
  integrated the returns package; [#1095](https://github.com/LTstripes/hermes-finance/pull/1095)
  updated proportional verification rules.
- Installation of 1.10.6 is **not verified**: the Owner computer was unavailable
  when installation was attempted. Do not infer the installed version from the tag.
  A previously verified backup exists; its applicability must be checked before
  the supported backup-first update and separate Start/readback.
- An isolated instrument-UAT snapshot was refused by preflight; the cause remains
  unknown. UAT was not completed. Do not bypass or blindly retry the refusal.
  [#1094](https://github.com/LTstripes/hermes-finance/pull/1094) proposes
  bounded diagnostics; it is not a released capability.

<a id="s2"></a>
## 2. Shipped code and limitations

The 1.10.6 source includes available clean instrument returns, display of known
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

1. Restore access to the Owner computer, confirm the actual installed state and
   backup, then perform the authorized guarded update and verify startup, version
   and data continuity. Stop on failure and preserve database and backup.
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
