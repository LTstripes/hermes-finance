# Current state, limitations and next actions

Evidence cut: 2026-10-23. This is the only maintained status book. Live GitHub evidence is distinguished from the Owner/handoff-reported local Test observations below. This documentation reconciliation did not inspect private originals, mapping seeds, databases or the Windows desktop. Dated receipts remain evidence for their original scope, not a current work queue.

<a id="s1"></a>
## 1. Code, published release, installed runtime and UAT are separate

| Object | Confirmed evidence and limit |
| --- | --- |
| Canonical code baseline | `31e7b41d444945ed5ae5c4e4a813997329c3a354`, [PR #939](https://github.com/LTstripes/hermes-finance/pull/939). Exact [main push CI 39956697053](https://github.com/LTstripes/hermes-finance/actions/runs/39956697053) SUCCESS. This is the code baseline reconciled by this docs change; the docs PR and its exact integration evidence belong in its own receipt. |
| Main schema | Through `0062_security_reg_isin_mappings`, after `0061_money_instrument_links`; both are merged code. This does not identify the schema of every installed database. |
| Published release | [v1.3.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.3.0), release commit `a9c88266fffe26e83688c52fc8f425b04fa14812`, schema `0058_broker_money_ownership`. The 1.4.0 preparation files remain dated snapshots, not proof of a published 1.4.0 release or current migration instructions. |
| Installed HONOR Stable | Last attributed [#836 local receipt](https://github.com/LTstripes/hermes-finance/issues/836#issuecomment-6222421447): backup-first OPS02, separate Start, physical DB continuity, `0044 → 0058`, limited health/API/UI/reload checks. No fresh Stable inspection or update is claimed here. |
| Owner's 1.4.0 Test | [#940 handoff](https://github.com/LTstripes/hermes-finance/issues/940) reports Test at the code baseline above, database revision 0062, private reg-ISIN seed loaded and coupons linked. Owner reports correct monthly account results and working multi-account upload. This is attributed local acceptance of those paths, not independent remote inspection, per-instrument return UAT or release acceptance. The process was manually started; present reachability/reboot persistence is not verified. |
| Workspace operations | Accepted code implements recoverable retirement (#864), not legacy permanent Apply. [#892 checkpoint](https://github.com/LTstripes/hermes-finance/issues/554#issuecomment-6255463423) preserved its PAUSED Worker workspace. No scheduler/installation change or future outcome is inferred from that record. |

The earlier [#836 freeze removal](https://github.com/LTstripes/hermes-finance/issues/836#issuecomment-6225429633) allowed main development after v1.3.0. The later Owner decision of 2026-10-22 freezes **UI work** while statement ingestion and return calculations are corrected; the current Owner order retains that focus. Published release, Stable, Test and UI-freeze decisions are distinct.

### Recent merged changes

| Work | Verified result |
| --- | --- |
| [#926](https://github.com/LTstripes/hermes-finance/pull/926), [#928](https://github.com/LTstripes/hermes-finance/pull/928), [#929](https://github.com/LTstripes/hermes-finance/pull/929) | Audit/return regressions and security work are merged. #928 merged as `8297a747`; #929 as `6ce9b7c9`. Old “uncommitted/unmerged candidate” prose is no longer their current state. Open #927 is tracked separately below. |
| [#932](https://github.com/LTstripes/hermes-finance/pull/932) | Real MyBroker statement/account-scope support merged as `8e46a65d`; it is no longer a Draft waiting for its first integration. |
| [#934](https://github.com/LTstripes/hermes-finance/pull/934), [#933](https://github.com/LTstripes/hermes-finance/pull/933) | Promo/gifts are external contributions, not investment income; unknown money remains NULL. Dividend matching was narrowed. Merged as `e268d38e` and `bebe5733`. |
| [#936](https://github.com/LTstripes/hermes-finance/pull/936) | Persisted coupon/dividend instrument links and migration 0061; merged as `7a558fbb`. |
| [#939](https://github.com/LTstripes/hermes-finance/pull/939) | Offline registration-number → ISIN crosswalk, migration 0062 and reg-ISIN CLI, re-landed onto main as `31e7b41d`. #937 was merged into the stacked branch; #938 was closed; #939 is the canonical main delivery. |

<a id="s2"></a>
## 2. Delivered capabilities and remaining gaps

### Account and instrument returns

[#911](https://github.com/LTstripes/hermes-finance/pull/911) / [#913](https://github.com/LTstripes/hermes-finance/pull/913) provide the provisional monthly account reader over saved intakes: contributions versus growth, approximate Modified Dietz, chained supported segments and XIRR, with dated-flow and valuation coverage tracked separately. [#917](https://github.com/LTstripes/hermes-finance/pull/917) supplies the v2 monthly-return page and multiple-file upload. The 2026-10-23 Owner Test report in S1 now provides limited real account-level acceptance; it does not turn every unsupported history into an exact result.

[#914](https://github.com/LTstripes/hermes-finance/issues/914) / [#915](https://github.com/LTstripes/hermes-finance/pull/915) already deliver `GET /api/source-returns/instruments`: monthly quantities/values, buy/sell cash, coupons/dividends and monetary result, plus all-time known sums. The current [reader](../backend/src/hermes_finance/services/source_instrument_returns.py) and [C7 contract](ARCHITECTURE_AND_CONTRACTS.md#c7-source_instrument_returns-1) use a simple monthly denominator `V0 + buys`; all-time percentage is intentionally NULL. It is not yet the requested dated purchase history or instrument Modified Dietz. Its `price_effect` uses buy/sell cash that can contain costs/NKD, so it must not be presented as pure market-price movement without an accepted decomposition.

[#936](https://github.com/LTstripes/hermes-finance/pull/936) and [#939](https://github.com/LTstripes/hermes-finance/pull/939) improve payout attribution. Unresolved or ambiguous links still require attention. Current `reg-isin relink` returns processed/changed/skipped counts; it does not print the requested unresolved-row list. The existing classification read model already exposes link status for that future exceptions view.

### History intake is not automatic monthly financial reconstruction

The [source-intake integration tests](../backend/tests/test_statement_import_source_intake.py) already include long history, multiple files, sparse months, overlapping originals and replay. The UI sends independent requests per file; it is not one transaction over the selected batch.

A long original may provide dated transactions/payouts and its own outer valuations. It does not supply unknown intermediate monthly EOD values. [Monthly source returns](../backend/src/hermes_finance/services/source_monthly_returns.py) retain supported outer-period estimates separately from missing monthly endpoints. Strict financial month binding still requires the original period to match the selected month. Accepting a long file into the source journal is not automatic financial DRAFT creation for every month.

The [accepted #769 history receipt](https://github.com/LTstripes/hermes-finance/issues/769#issuecomment-6254449019) and [accepted differential check](https://github.com/LTstripes/hermes-finance/issues/769#issuecomment-6254662531) preserve the already inspected source-only corpus. Repetitive whole-archive inventory remains PAUSED. Continue for new supplied originals or exact missing operands, not another blanket monthly export request. Earlier June/July pilots and the common history journal remain source-only evidence, not accepted financial receipts or a promoted Stable ledger.

The [#889 intake acceptance](https://github.com/LTstripes/hermes-finance/issues/889#issuecomment-6253440076) and [parser-upgrade boundary](https://github.com/LTstripes/hermes-finance/issues/889#issuecomment-6254134701) remain: V1 journal observations are not a raw-XML cache or future reparse. Preserve unchanged originals for the supported re-upload/rebuild route; no in-place manifest/trigger rewrite or row-copy promotion. The broader partial financial writer has no automatic code/authority approval.

### Statement ingestion and the payout calendar still need to be joined

[source_intake](../backend/src/hermes_finance/services/source_intake.py) explicitly creates no catalogue metadata or financial facts. The separate strict [identity staging](../backend/src/hermes_finance/services/mybroker_identity.py) path can create identified instruments as part of its authorized transaction. A new ISIN visible in the source-return journal therefore does not by itself prove a new catalogue instrument or monthly position exists.

[payout_preview](../backend/src/hermes_finance/services/payout_preview.py) uses the selected `PositionSnapshot` quantity. Source-journal Save does not update that quantity basis. Connecting statement identity/positions, existing T-Invest forecasts and actual-payout reconciliation is an explicit functional step under #711/#889, not cosmetic UI cleanup. This code gap does not by itself establish the cause of a particular private quantity or issuer case.

### Retained acceptance boundaries

Earlier instrument readers [#858](https://github.com/LTstripes/hermes-finance/issues/858)/[#860](https://github.com/LTstripes/hermes-finance/issues/860)/[#862](https://github.com/LTstripes/hermes-finance/issues/862)/[#865](https://github.com/LTstripes/hermes-finance/issues/865) and the [#867 consolidated inspection](https://github.com/LTstripes/hermes-finance/issues/891#issuecomment-6275641077) remain bounded evidence. Their PARTIAL UAT is not full changing-quantity stock/bond acceptance. [#839's offline closeout](https://github.com/LTstripes/hermes-finance/issues/839#issuecomment-6277475896) is historical conditional-return evidence, separate from the later Test report.

UNKNOWN/NULL/zero, actual versus forecast, source versus accepted financial authority, bond clean/dirty/NKD basis, completeness, explicit Close/Reopen and exact XIRR/TWRR prerequisites remain owned by C. Useful provisional results do not silently waive these boundaries.

<a id="s3"></a>
## 3. Current priorities, blockers and Owner actions

The current coordination issue is [#940](https://github.com/LTstripes/hermes-finance/issues/940). [P2](MASTER_SPEC.md#p2-statement-led-target) owns the target experience: manual personal facts → statement and exceptions → future payouts → recalculation → dashboards.

1. **First: repair [#935](https://github.com/LTstripes/hermes-finance/pull/935).** It remains Draft/Open at `7734323494d2dc54f082ee5af41f634e03133659`. Exact [PR CI 39970067863](https://github.com/LTstripes/hermes-finance/actions/runs/39970067863) SUCCESS does not close the [B2 review finding](https://github.com/LTstripes/hermes-finance/pull/935#issuecomment-6368265286): applied S3 and WHAT-IF can still use inferred balance dates; historical-endpoint and provisional paths also need closure or a concrete proof of inapplicability. Preserve import usability; expose `source_period_inferred` as a hard financial reason where dates are unproved. Required next gates: corrected candidate, independent re-review, exact PR CI, guarded merge and exact-main push CI. The PR body must also be reconciled with its actual filename/content policy.
2. **Then [#891](https://github.com/LTstripes/hermes-finance/issues/891): instrument returns backend.** Reuse the existing reader and payout links; define dated cash flows and quantity changes, defensible price/payout/cost decomposition, RUB result and Modified Dietz, with XIRR optional. Handle reinvestment, full exit and incomplete history. The immediate local assignment reconciles the existing audit report 7 with current code into one first coherent implementation contract; it does not repeat a broad audit or automatically start code.
3. **[#769](https://github.com/LTstripes/hermes-finance/issues/769): targeted historical loading.** Start at the first evidenced statement, currently estimated by the Owner as around May 2024. Prefer long originals where sufficient, add only necessary missing valuation boundaries, reuse accepted corpus/history tests, and produce an actionable unresolved-link list. Actual local loading/DB changes remain a separately assigned operation with backup.
4. **[#711](https://github.com/LTstripes/hermes-finance/issues/711) / [#889](https://github.com/LTstripes/hermes-finance/issues/889): connect the ordinary monthly path.** Match/create recognized instruments, establish the source-backed quantity used by existing forecasts and reconcile paid versus future events. Do not build another catalogue, payout provider or parallel money ledger.
5. **UI after backend/history readiness and removal of the UI freeze.** One month screen and useful instrument detail, with corrections and secondary diagnostics. Alfa PRO and old preparation screens are optional capabilities, not compulsory monthly steps. This checkpoint does not launch redesign or remove routes.

The Owner-local audit reports 6 and 7 were not available in this cloud session. Their proposed “11 UI PRs / 4 backend PRs” are not an accepted fixed partition. Reuse those existing reports locally and return sanitized source-backed conclusions; do not upload original statements, private numerical cases or mapping seeds.

Reported audit follow-ups in #940 still need exact reproductions/current-source disposition: forecast/quantity/paid-event issues; missing issuer forecasts; tax-label wording; deposit edit race/duplicates; broad promo pattern and positive dividend-NDFL classification; reg-ISIN console/path/downgrade behavior. They are not claimed fixed here, nor all independently reproduced. Existing contracts already distinguish forecast from actual and provider net terminology from personal after-tax income.

### Execution route

Nikita selects and dispatches short Worker prompts, returns the result, and Integrator performs live review and authorized repository mechanics under D5. No implicit queue or automatic external Astra invocation; a concrete Astra task requires the Owner's explicit OK. Relevant user-path execution must be evidenced on the assigned local/synthetic Test environment before delivering a feature for Owner testing. This session's source/CI inspection is not a Windows desktop click-through.

Open PRs at the evidence cut are #935, [#927](https://github.com/LTstripes/hermes-finance/pull/927), [#829](https://github.com/LTstripes/hermes-finance/pull/829) and [#744](https://github.com/LTstripes/hermes-finance/pull/744). Only #935 is the immediate route above. Old candidate descriptions do not authorize resuming the others or importing unpushed local changes.

<a id="s4"></a>
## 4. Deferred directions and operational limits

Stable/release/deployment, financial history promotion, versioned in-place reparse, broad FX/in-kind/scope transitions and unsupported provider semantics retain their own authority and acceptance. [#856](https://github.com/LTstripes/hermes-finance/issues/856) AI numeric export waits for a supported numeric model/UAT; [#897](https://github.com/LTstripes/hermes-finance/issues/897) is deferred and does not block offline calculations. Do not revive old release queues or model journals.

Broker inquiry status remains Owner-reported per the [#814 clarification](https://github.com/LTstripes/hermes-finance/issues/814#issuecomment-6254056375): September NKD/settlement/commission inquiry sent; separate [#888](https://github.com/LTstripes/hermes-finance/issues/888) REPO/custody question not sent. This is not independent dispatch verification or a broker response; no new communication occurred here.

[#838](https://github.com/LTstripes/hermes-finance/issues/838) retains its off-device/recovery/ACL limitations. This documentation reconciliation changes no source, database, seed, credential, released migration, runtime, scheduler or provider connection. Real originals/private financial data remain local; Test DB mutation needs a backup and assigned local authority. T-Invest schedules and MyBroker quantities remain the target source split; MOEX remains retired under ADR 0010.
