# Current state, limitations and next actions

**Accepted code (post-#958 live readback):** `main@0ddd0b357325a286c26ed2d564b226bd7214785e`
and [exact post-main CI 40167455400](https://github.com/LTstripes/hermes-finance/actions/runs/40167455400)
**SUCCESS**. [#958](https://github.com/LTstripes/hermes-finance/pull/958) accepts bounded
dividend-narrative variants through existing source authority; normal GET never
relinks saved rows. Its earlier private schema0064 relink Preview is stale after
any future 0065 rollout: regenerate the exact Preview including retirement nonce
effects before separate Owner GO and fresh validated backup/readback. No real
relink is performed by this code integration. The backend [#953](https://github.com/LTstripes/hermes-finance/pull/953)
and Month UI [#954](https://github.com/LTstripes/hermes-finance/pull/954)
implement shared `empty_manual_month` Close/readiness, 0063 immutable receipt audit,
0064 saved-actual versus cloned-template provenance, and explicit reasoned period
confirmation with GET-only lost-ACK/Back/Reload recovery. No real Close was done.

**Installed Test and managed O4 (Owner-local attributed evidence):** Test runs
the accepted application baseline `e487d570...` at schema **0064**, with preserved ten broker originals,
mappings/manual/history and one stock O2/OPS03 upgrade plus Month UAT **PASS**.
The Owner-selected plaintext synced managed backup was independently downloaded
from cloud with matching full SHA256; fresh isolated **0064→0064** restore,
Prepare/Validate/readiness and all **76 table fingerprints** PASS. See the
[single sanitized #954 receipt](https://github.com/LTstripes/hermes-finance/pull/954#issuecomment-6385205231).
The Integrator verified GitHub records, not private DB bytes. Financial source-only
authority and unsupported bond/NKD/coverage returns remain honest PARTIAL/NULL.
No actual October Apply/Close, history reimport, live T-Invest or Stable write.

**Published / Stable (2026-10-24 Operator-attributed readback):** installed clean
**v1.4.0 / 0064**, HEAD/prepared marker at `b027bcd9...`, production binding and
physical DB continuity verified. The accepted release/update evidence is retained
in [#940](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6388752474).
The later missing HTTP listener was confirmed; existing logs/limited crash and
shutdown events did not establish its termination cause or an intentional stop.
After separate explicit Owner GO, stock Start of the same installed SHA passed
health, owned process/cwd/DB-selector checks and UI/Reload. All 76 table
fingerprints remain unchanged. No candidate deployment or Test transfer occurred.

**Accepted #957 bounded #891/#769/#889 slice:** exact-original-bound monthly read
localizes only strictly recognized source-booked custody cancellations; GET
without bytes remains fail-closed. Two priority calendar months become available
through the candidate reader with all selected originals; the cancellation month
and unresolved principal remain NULL. Real amounts, native identities and the
separate five absent historical opening-value operands stay private. This is
provisional source evidence, not financial acceptance; [#957](https://github.com/LTstripes/hermes-finance/pull/957)
is merged with independent review and terminal exact-main CI. Earlier
numerical controls and the private 78/1,539 matrices are reused.

**Pending one-time proof → ordinary GET → desktop slice:** additive schema 0065
stores server-derived source custody-month provenance only, without XML/rates or
V1 reinterpretation. Explicit Preview/attested confirmation supports Month and
Monthly Returns without repeated file selection. Currentness includes complete
membership, parser/manifest/head, monotonic source/classification/correction/
mapping revisions and physical DB birth identity; stale/restore/ABA returns NULL
until fresh confirmation. The cancellation/principal month stays NULL. No real
proof has been saved and no Test/Stable code/schema operation is part of this task.
Independent review and exact candidate CI belong to the implementation PR before
Integrator guarded merge and exact-main CI. Installed Stable remains immutable
published v1.4.0 `b027bcd9...` / 0064. The next rollout requires explicit Test UAT,
a new release (target v1.5.0), published-SHA recovery rehearsal and separate Owner
runtime/write approvals; never a hotpatch or a Test-data transfer. Private Owner
UAT/release gates and the single unsent principal/custody broker question are
retained locally. Prior numerical/operational evidence is reused.
PR [#959](https://github.com/LTstripes/hermes-finance/pull/959) remains Draft pending
repeat Integrator GO. Its successor incorporates post-#958 main, shares exact
Decimal ROUND_HALF_UP percentage display between Month/Monthly Returns (no value
conversion through Number), and retains #958's relink regression with exactly one
nonce append and unchanged proof/financial tables. Fresh combined-tree PR CI/UI
and independent pinned-SHA rereview are required; earlier standalone GO is superseded.
Earlier evidence cut: 2026-10-24 for the bounded bond presentation; earlier dated evidence retains its original scope. This is the only maintained status book. Live GitHub evidence, the #891 Worker's isolated synthetic Windows checks, attributed Owner/Test observations and the #940 Worker's read-only binding/database inspection below retain their distinct scope. This Integrator review inspected source, diff and CI; it did not inspect private originals, mapping seeds or runtime databases. Dated receipts retain their original scope.

<a id="s1"></a>
## 1. Code, published release, installed runtime and UAT are separate

| Object | Confirmed evidence and limit |
| --- | --- |
| #891 original implementation base | Main `418b88a8c9a1b9b8e5f2d72e6112426282f3d285`, after [#935 acceptance/integration](https://github.com/LTstripes/hermes-finance/pull/935#issuecomment-6369982626); exact [main push CI 39988134177](https://github.com/LTstripes/hermes-finance/actions/runs/39988134177) SUCCESS. The current acceptance and integration evidence is linked below; the baseline does not identify an installed runtime. |
| Finance-code checkpoint before #935 | `31e7b41d444945ed5ae5c4e4a813997329c3a354`, [PR #939](https://github.com/LTstripes/hermes-finance/pull/939). Exact [main push CI 39956697053](https://github.com/LTstripes/hermes-finance/actions/runs/39956697053) SUCCESS. This is the earlier code checkpoint reconciled by #941. The subsequent #935 behavior and its exact verification/integration evidence are linked below. |
| Main schema | Through `0064_month_template_provenance`, after `0063_intentional_empty_close` and `0062_security_reg_isin_mappings`; these are merged code. This does not identify the schema of every installed database. |
| Published release | [v1.4.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.4.0), release commit `b027bcd90c56c500d271a9ee963485bdfa67ea79`, schema `0064_month_template_provenance`. Publication and installed acceptance are recorded separately in #940; candidate merges do not authorize rollout. |
| Installed HONOR Stable | Operator-attributed current readback: clean published `b027bcd9...` / v1.4.0 / 0064, original physical DB and binding preserved. Separate Owner-authorized stock Start restored HTTP; health/UI/Reload PASS, 76-table equality PASS. Prior #836/0058 evidence below remains historical. |
| Owner's 1.4.0 Test | [Final one-task Test/O4 receipt](https://github.com/LTstripes/hermes-finance/pull/954#issuecomment-6385205231): accepted `e487d570...` / 0064, 10 originals/mappings/manual data retained, O2/OPS03/Validate/Start, bounded Month UAT PASS; managed plaintext cloud SHA256 readback and isolated 0064 recovery with 76-table equality PASS. Private-data evidence is attributed to the local Operator; not proof of Stable 0058→0064 or complete financial returns. |
| Workspace operations | Accepted code implements recoverable retirement (#864), not legacy permanent Apply. [#892 checkpoint](https://github.com/LTstripes/hermes-finance/issues/554#issuecomment-6255463423) preserved its PAUSED Worker workspace. No scheduler/installation change or future outcome is inferred from that record. |

The earlier [#836 freeze removal](https://github.com/LTstripes/hermes-finance/issues/836#issuecomment-6225429633) allowed main development after v1.3.0. The 2026-10-22 UI freeze is now bounded by the Owner's [2026-10-24 Month authorization](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6375180628) and [useful-bond decision](https://github.com/LTstripes/hermes-finance/issues/891#issuecomment-6375176825). The assigned first read-only bond presentation reuses instrument v2 on the existing monthly-returns route, including conditional statement estimates without inventing NKD or complete economic return. Acceptance/desktop/CI evidence belongs to its Draft PR; this is not general route retirement, financial UAT, or permission for protected runtime changes. Published release, Stable and Test gates remain distinct.

Historical #940 checkpoint on 2026-10-23 (its Test baseline is superseded by the 2026-10-24 UAT above) inspected Stable read-only: clean published
v1.3.0 HEAD/prepared marker, actual DB at 0058 matching canonical production binding,
integrity/FK PASS. Effective DB differs from OPS02's default; explicit `-DatabasePath`
remains mandatory. Test is clean at `31e7b41d444945ed5ae5c4e4a813997329c3a354` / 0062,
integrity/FK PASS, but its prepared marker does not match HEAD. The loopback 8000 listener
belongs to Test, health reports 1.3.0 and the process's effective DB selector matches Test's
binding. Existing Owner account/upload
checks retain their attributed scope; this is not exact-release preparation evidence.
No Stable/Test mutation or production Start was performed. Cross-schema production rollback
is absent: exact-schema API restore, OPS02 older-version refusal and isolated-only O4 recovery
do not compose into a Stable rollback. Integrator must settle recovery/risk before production Start.

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

[#914](https://github.com/LTstripes/hermes-finance/issues/914) / [#915](https://github.com/LTstripes/hermes-finance/pull/915) delivered the existing instrument API. Its legacy monthly denominator remains `V0 + buys`, and all-time percentage remains NULL. The independently reviewed #891 backend implementation adds dated events, current payout attribution, quantity/cash reconciliation and monthly/selected-interval RUB P/Modified Dietz under [C7 v2](ARCHITECTURE_AND_CONTRACTS.md#c7-instrument-return-v2), with a complete typed consumer. `price_effect` remains a cash-cost-inclusive compatibility field. Full economic result, known subtotal and conditional statement-value estimate are separate; unknown bond valuation basis still prevents full economic P/MD. Separate-context financial review and Integrator source review gave GO for the backend scope in [#945](https://github.com/LTstripes/hermes-finance/pull/945). Canonical integration and exact-main CI are recorded in its live receipt; no real-history numerical UAT or instrument UI acceptance is implied.

[#936](https://github.com/LTstripes/hermes-finance/pull/936) and [#939](https://github.com/LTstripes/hermes-finance/pull/939) persist payout attribution. The #891 implementation consumes and revalidates those links read-only; it leaves stale/unresolved links visible and never relinks during GET. Current `reg-isin relink` still returns processed/changed/skipped counts rather than a console unresolved-row list; that existing CLI limitation is unchanged.

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
## 3. Earlier roadmap and open financial work (not the current 1.4.0 release gate)

These earlier roadmap priorities are retained as backlog provenance, not an active instruction to repeat accepted Test work. The current release gate is at the top of this file and in [#940](https://github.com/LTstripes/hermes-finance/issues/940). [P2](MASTER_SPEC.md#p2-statement-led-target) owns the target experience: manual personal facts → statement and exceptions → future payouts → recalculation → dashboards.

1. **Period handling in [#935](https://github.com/LTstripes/hermes-finance/pull/935).** Renamed files remain ingestible. Inferred activity periods cannot establish financial balance dates: applied S3, WHAT-IF, historical endpoints and provisional contexts retain hard `source_period_inferred`; the monthly consumer keeps explained per-intake/month diagnostics without reattachment duplicates. Filename mismatch remains advisory. The [independent corrected-code review](https://github.com/LTstripes/hermes-finance/pull/935#pullrequestreview-5631319200) and final PR receipt own exact-candidate CI/integration status; no local Owner UAT is inferred from this code change.
2. **[#891](https://github.com/LTstripes/hermes-finance/issues/891): backend accepted; private numerical UAT/history/UI remain separate.** [#945](https://github.com/LTstripes/hermes-finance/pull/945) implements the [accepted contract](https://github.com/LTstripes/hermes-finance/issues/891#issuecomment-6369624791). Independent separate-context financial review and Integrator review gave GO on `942b6767b27dac931b334a3635d53d7adce97c06`; exact PR CI [39995418972](https://github.com/LTstripes/hermes-finance/actions/runs/39995418972) and UI evidence [39995419005](https://github.com/LTstripes/hermes-finance/actions/runs/39995419005) completed SUCCESS. Reconciliation with #944 changes documentation only beyond the two accepted trees; successor/exact-main CI and guarded integration are tracked in the PR receipt. Reuse the scoped synthetic arithmetic/service/API, typed consumer and two isolated Windows desktop scenarios; these are not private instrument-history/MD acceptance. UI, acquisition-cost accounting, XIRR, migrations, historical loading and protected runtime changes remain outside this delivery.
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

The Owner authorized updating Stable on 2026-10-23, with timing assigned to Integrator.
The [#944 preparation](https://github.com/LTstripes/hermes-finance/pull/944) was accepted
and merged as `531fd6e98a764a0e7a33c8d6d70366f61c5cf5f3`; its receipt remains dated
preparation evidence. The later [#954 Test/O4 receipt](https://github.com/LTstripes/hermes-finance/pull/954#issuecomment-6385205231)
completes the bounded Test/0064 gate. The current release sequence at the top of this
file and in the [recovery disposition](releases/1.4.0-rollback.md) supersedes the old
blanket publication/Test hold. The exact Owner-approved publication follows the
verified managed Stable 0058 checkpoint and precedes its published-code isolated
0058→0064 rehearsal. **Stable OPS02/Start remain HOLD** until that rehearsal and any
actual residual RPO/outage/forward-fix decision pass. Production uses the original
physical DB with backup-first OPS02 and separate Start; Test data is not promoted.
No release publication or Stable installation is claimed by this checkpoint.

Financial history promotion, versioned in-place reparse, broad FX/in-kind/scope transitions and unsupported provider semantics retain their own authority and acceptance. [#856](https://github.com/LTstripes/hermes-finance/issues/856) AI numeric export waits for a supported numeric model/UAT; [#897](https://github.com/LTstripes/hermes-finance/issues/897) is deferred and does not block offline calculations. Do not revive old release queues or model journals.

Broker inquiry status remains Owner-reported per the [#814 clarification](https://github.com/LTstripes/hermes-finance/issues/814#issuecomment-6254056375): September NKD/settlement/commission inquiry sent; separate [#888](https://github.com/LTstripes/hermes-finance/issues/888) REPO/custody question not sent. This is not independent dispatch verification or a broker response; no new communication occurred here.

[#838](https://github.com/LTstripes/hermes-finance/issues/838) retains its off-device/recovery/ACL limitations. The #891 candidate changes no saved source data, seed, credential, released migration, protected runtime, scheduler or provider connection. Real originals/private financial data remain local; Test DB mutation needs a backup and assigned local authority. T-Invest schedules and MyBroker quantities remain the target source split; MOEX remains retired under ADR 0010.
