# Current state, limitations and next actions

Evidence cut: 2026-10-23. This is the only maintained status book. Live GitHub evidence, the #891 Worker's isolated synthetic Windows checks and the Owner/handoff-reported Test observations below are distinct. No private originals, mapping seeds or Owner/Test/Stable databases were inspected by the #891 implementation. Dated receipts remain evidence for their original scope, not a current work queue.

<a id="s1"></a>
## 1. Code, published release, installed runtime and UAT are separate

| Object | Confirmed evidence and limit |
| --- | --- |
| #891 pinned implementation base | Main `418b88a8c9a1b9b8e5f2d72e6112426282f3d285`, after [#935 acceptance/integration](https://github.com/LTstripes/hermes-finance/pull/935#issuecomment-6369982626); exact [main push CI 39988134177](https://github.com/LTstripes/hermes-finance/actions/runs/39988134177) SUCCESS. The Worker candidate below is not an integrated/released or installed change. |
| Finance-code checkpoint before #935 | `31e7b41d444945ed5ae5c4e4a813997329c3a354`, [PR #939](https://github.com/LTstripes/hermes-finance/pull/939). Exact [main push CI 39956697053](https://github.com/LTstripes/hermes-finance/actions/runs/39956697053) SUCCESS. This is the earlier code checkpoint reconciled by #941. The subsequent #935 behavior and its exact verification/integration evidence are linked below. |
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

[#914](https://github.com/LTstripes/hermes-finance/issues/914) / [#915](https://github.com/LTstripes/hermes-finance/pull/915) delivered the existing instrument API. Its legacy monthly denominator remains `V0 + buys`, and all-time percentage remains NULL. The #891 Worker candidate adds dated events, current payout attribution, quantity/cash reconciliation and monthly/selected-interval RUB P/Modified Dietz under [C7 v2](ARCHITECTURE_AND_CONTRACTS.md#c7-instrument-return-v2), with a complete typed consumer. `price_effect` remains a cash-cost-inclusive compatibility field. Full economic result, known subtotal and conditional statement-value estimate are separate; unknown bond valuation basis still prevents full economic P/MD. This is candidate implementation, not Integrator acceptance or real-history UAT.

[#936](https://github.com/LTstripes/hermes-finance/pull/936) and [#939](https://github.com/LTstripes/hermes-finance/pull/939) persist payout attribution. The #891 candidate consumes and revalidates those links read-only; it leaves stale/unresolved links visible and never relinks during GET. Current `reg-isin relink` still returns processed/changed/skipped counts rather than a console unresolved-row list; that existing CLI limitation is unchanged.

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

1. **Period handling in [#935](https://github.com/LTstripes/hermes-finance/pull/935).** Renamed files remain ingestible. Inferred activity periods cannot establish financial balance dates: applied S3, WHAT-IF, historical endpoints and provisional contexts retain hard `source_period_inferred`; the monthly consumer keeps explained per-intake/month diagnostics without reattachment duplicates. Filename mismatch remains advisory. The [independent corrected-code review](https://github.com/LTstripes/hermes-finance/pull/935#pullrequestreview-5631319200) and final PR receipt own exact-candidate CI/integration status; no local Owner UAT is inferred from this code change.
2. **[#891](https://github.com/LTstripes/hermes-finance/issues/891): candidate implemented, review/integration remain.** The [accepted contract](https://github.com/LTstripes/hermes-finance/issues/891#issuecomment-6369624791) is implemented on the pinned base in `worker/891-dated-returns-20261023`. Focused synthetic arithmetic/service/API regressions, TypeScript build/consumer test and the existing Windows `provisional` Playwright path were exercised on a disposable synthetic DB (two desktop scenarios passed, including the additive instrument API read). Exact final candidate/check evidence belongs to its Draft PR receipt. Full relevant CI, independent financial review, guarded Integrator merge and exact-main push CI remain separate gates; the Worker does not self-accept. UI, acquisition-cost accounting, XIRR, migrations, historical loading and protected runtimes remain outside this candidate.
3. **[#769](https://github.com/LTstripes/hermes-finance/issues/769): targeted historical loading.** Start at the first evidenced statement, currently estimated by the Owner as around May 2024. Prefer long originals where sufficient, add only necessary missing valuation boundaries, reuse accepted corpus/history tests, and produce an actionable unresolved-link list. Actual local loading/DB changes remain a separately assigned operation with backup.
4. **[#711](https://github.com/LTstripes/hermes-finance/issues/711) / [#889](https://github.com/LTstripes/hermes-finance/issues/889): connect the ordinary monthly path.** Match/create recognized instruments, establish the source-backed quantity used by existing forecasts and reconcile paid versus future events. Do not build another catalogue, payout provider or parallel money ledger.
5. **UI after backend/history readiness and removal of the UI freeze.** One month screen and useful instrument detail, with corrections and secondary diagnostics. Alfa PRO and old preparation screens are optional capabilities, not compulsory monthly steps. This checkpoint does not launch redesign or remove routes.

The local Worker reconciled the relevant existing audit reports, primarily report 7 and report 6's consumer dependencies, into the linked sanitized #891 contract. The original reports/private examples remain local. The earlier “11 UI PRs / 4 backend PRs” are not a fixed partition; the accepted next backend scope is the coherent PR above. Do not upload original statements, private numerical cases or mapping seeds.

Reported audit follow-ups in #940 still need exact reproductions/current-source disposition: forecast/quantity/paid-event issues; missing issuer forecasts; tax-label wording; deposit edit race/duplicates; broad promo pattern and positive dividend-NDFL classification; reg-ISIN console/path/downgrade behavior. They are not claimed fixed here, nor all independently reproduced. Existing contracts already distinguish forecast from actual and provider net terminology from personal after-tax income.

### Execution route

Nikita selects and dispatches short Worker prompts, returns the result, and Integrator performs live review and authorized repository mechanics under D5. No implicit queue or automatic external Astra invocation; a concrete Astra task requires the Owner's explicit OK. The #891 candidate's automated Windows desktop path uses a disposable synthetic environment. It is not private Owner Test UAT or acceptance of a future instrument-history/MD screen.

The latest integration state of #935 belongs in its live PR receipt and #940. Other open candidates at this evidence cut are [#927](https://github.com/LTstripes/hermes-finance/pull/927), [#829](https://github.com/LTstripes/hermes-finance/pull/829) and [#744](https://github.com/LTstripes/hermes-finance/pull/744); their old descriptions do not authorize resuming them or importing unpushed local changes.

<a id="s4"></a>
## 4. Deferred directions and operational limits

The Owner authorized updating Stable on 2026-10-23, with timing assigned to Integrator. Preparation is coordinated in #940 after accepted #935; stock O3 requires a published release, explicit existing DB binding and backup-first OPS02 followed by separate Start. No release publication, Stable installation or Test-to-Stable data transfer is claimed. The dated 1.4.0 notes/recovery limits must be reconciled before the production schema transition.

Financial history promotion, versioned in-place reparse, broad FX/in-kind/scope transitions and unsupported provider semantics retain their own authority and acceptance. [#856](https://github.com/LTstripes/hermes-finance/issues/856) AI numeric export waits for a supported numeric model/UAT; [#897](https://github.com/LTstripes/hermes-finance/issues/897) is deferred and does not block offline calculations. Do not revive old release queues or model journals.

Broker inquiry status remains Owner-reported per the [#814 clarification](https://github.com/LTstripes/hermes-finance/issues/814#issuecomment-6254056375): September NKD/settlement/commission inquiry sent; separate [#888](https://github.com/LTstripes/hermes-finance/issues/888) REPO/custody question not sent. This is not independent dispatch verification or a broker response; no new communication occurred here.

[#838](https://github.com/LTstripes/hermes-finance/issues/838) retains its off-device/recovery/ACL limitations. The #891 candidate changes no saved source data, seed, credential, released migration, protected runtime, scheduler or provider connection. Real originals/private financial data remain local; Test DB mutation needs a backup and assigned local authority. T-Invest schedules and MyBroker quantities remain the target source split; MOEX remains retired under ADR 0010.
