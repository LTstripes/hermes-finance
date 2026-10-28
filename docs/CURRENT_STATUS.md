# Current state, limitations and next actions

Updated **2026-10-28**. This is the sole changing project status book. Current source
behavior is specified by [P](MASTER_SPEC.md), numeric/data authority by
[C](ARCHITECTURE_AND_CONTRACTS.md), integration by [D](DEVELOPMENT.md), and
runtime/recovery by [O](OWNER_RUNTIME_OPERATIONS.md). Historical PR comments
are evidence for their dated stage, not a newer installation status.

## Current checkpoint

**Accepted application baseline: [#981](https://github.com/LTstripes/hermes-finance/pull/981)
merged as `main@a1027347b253ed2e53647143726c11f76d09c0da` - CODE MERGED and accepted.**
The explicit financial-DRAFT T-Invest forecast save/refresh action is implemented
and accepted in code, and is now included in installed Stable v1.7.0. Earlier exact-main
[CI40653035431](https://github.com/LTstripes/hermes-finance/actions/runs/40653035431)
**attempt 2 COMPLETED SUCCESS**. Attempt 1 failed one Windows recovery-readiness
regression; the bounded Windows diagnostic did not reproduce it. The retry PASS
does not establish that the intermittent cause was fixed or harmless.
**Current released and installed target: `536bb2336284b75cc6901570a7c196235326cf68`.**
[#982](https://github.com/LTstripes/hermes-finance/pull/982) packaging and
[#983](https://github.com/LTstripes/hermes-finance/pull/983) retirement-test
readback synchronization are merged. Exact-main
[CI40682375464](https://github.com/LTstripes/hermes-finance/actions/runs/40682375464)
and guarded [release40684513085](https://github.com/LTstripes/hermes-finance/actions/runs/40684513085)
**COMPLETED SUCCESS**. [v1.7.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.7.0)
is published; annotated tag `d8aaf8599bbbb05c105a6c1cb3c39b54a8d2ae6b`
peels to that exact target. GitHub reports `immutable=false`; no platform
immutability guarantee is claimed. Operator-local OPS02/Prepare/Validate/Start
and startup/continuity readback PASS establish installation, not Owner UAT.

Earlier accepted work: [#976](https://github.com/LTstripes/hermes-finance/pull/976)
(native source-account aliases and partial RUB history),
[#977](https://github.com/LTstripes/hermes-finance/pull/977)
(Month forms/order/source-vs-actual-vs-forecast and stale ISIN/date guard),
[#979](https://github.com/LTstripes/hermes-finance/pull/979)
(four-checkbox investment basket with honest partial/NULL outcomes), and
[#980](https://github.com/LTstripes/hermes-finance/pull/980)
(no implicit source-period selection without CLOSED and G04 bound to new ISIN panel).
[#980 exact candidate CI40584079496](https://github.com/LTstripes/hermes-finance/actions/runs/40584079496)
and [UI40584079506](https://github.com/LTstripes/hermes-finance/actions/runs/40584079506)
**COMPLETED SUCCESS** at `693131707157999d42ea8912241551e7ecbc391d`,
with [independent UI/contract GO](https://github.com/LTstripes/hermes-finance/pull/980#issuecomment-6460306343)
(Reviewer did not independently open prior native trace archive). Exact-head
guarded squash merge is `20ada2079114a3a7fded71283f2ae38776dbefb5`.
**Earlier #980 canonical-main [CI40629971268](https://github.com/LTstripes/hermes-finance/actions/runs/40629971268)
COMPLETED SUCCESS**, including native/G04, synthetic visual audit, finance/runtime
lanes and terminal `ci-ok` on the exact merged SHA. This is code integration
acceptance, not new Test/UAT, published release or Stable installation.

Earlier exact-main [CI40557762042](https://github.com/LTstripes/hermes-finance/actions/runs/40557762042)
FAILED on an actual stale ISIN/date navigation P2, subsequently fixed in #977.
[CI40580924918](https://github.com/LTstripes/hermes-finance/actions/runs/40580924918)
FAILED 1/1356 frontend tests (implicit source interval without CLOSED);
the first #980 candidate also exposed an old-panel G04 test interaction.
The [trace-backed correction](https://github.com/LTstripes/hermes-finance/pull/980#issuecomment-6453594768)
waits for the selected bond's new ISIN panel before changing quantity date;
the production stale-control guard, exact quantity assertions and read-only
provider boundaries remain unchanged. These failures are historical evidence,
not current code acceptance or permission for an unchanged rerun.

**Earlier Stable was [v1.6.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.6.0)**,
peeled SHA `d53a67409be4283f08f622218743ff5ef8e66ff0`,
SQLite `0065_source_return_proofs`.
[Owner-local Stable receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6408493088)
and later [Operator #711 return receipt](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6446621985)
attest its physical DB, old source/proof rows, CLOSED history and service readback.
These are attributed Operator-local proofs, not new cloud observation.
The earlier 28 October readback confirmed v1.6.0 and unchanged database bytes.
The subsequent authorized update installed v1.7.0 with health HTTP 200/ok/1.7.0
and schema `0066_actual_payout_links`. Operator-local evidence confirms the
original physical DB/file identity and preservation of prior values, triggers,
sequences and sidecar. A fresh verified 0065 backup and its producing v1.6.0
code bundle are retained. Test is unchanged; no financial or provider actions
were performed. These installation proofs do not establish Owner visual UAT.
[Final installation receipt](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6468966093)
records the attributed Operator-local outcome.
At the Owner's explicit request the Finance workspace-retirement schedule is
disabled; backup schedules are unaffected.

**Isolated Test:** prior pinned code `87624e12ef9d9d63c5df5b5f13703a4e3a7e3541`
was technically verified by [#711 0066 migration/read-only
receipt](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6446728835);
the existing Test DB is on `0066_actual_payout_links` but Test stopped,
and the then-published v1.6.0 Stable was returned on its 0065 DB.
35 Owner-history GETs PASS on that earlier scope. The new OPS03 did not start:
the scheduled lifecycle `Scan -Retire` held its global mutex, then completed
normally. No new Test pin/Start or provider request occurred. On 28 October the
Owner cancelled the separate aggregate Test walkthrough and authorized the
guarded Stable update instead. Visual acceptance is deferred to evening/Thursday
review, with the main monthly UAT planned for 1 November; neither is a PASS.
Real financial DRAFT Apply/forecast save/Close and physical restore remain
unaccepted and require their separate specific authority.

**Product/release boundary:** [#711 revised Owner decision](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6450994944)
is **XML → source review → accepted financial DRAFT/GET → one-click T-Invest
batch lookup, safe forecast save/refresh and calendar GET** using existing
PositionSnapshot/provider payout revision writers. The one-click bulk
forecast writer **is delivered by #981 and included in installed Stable v1.7.0**.
It requires the strict current financial-DRAFT receipt and native positive
PositionSnapshot; source-only/manual/copied/CLOSED positions are not eligible.
The former source-only
persisted-forecast design STOP no longer governs the chosen DRAFT-first path.
Owner approved [one separately scoped local read-only T-Invest Test
request](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6450551962),
but no successful real provider auth/result has yet been attested.
Code acceptance itself authorizes no runtime or financial action. The separate
28 October Owner authorization covered the now-completed guarded #124
publication and backup-first Stable update with binding and migration/recovery
safeguards; financial Apply/save/Close was excluded and was not performed.
The approved fail-stop disposition remains: on failed or uncertain
schema-changing Start, stop only the owned runtime, preserve the resulting DB
and verified original backup, perform no automatic downgrade/overwrite, and
report to the Owner. Successful installation grants no new financial authority.

**Financial limits:** source-only RUB account-month amounts and accepted deposit
interest are separate read models, not summed into a total personal portfolio
return. Gold period returns and the full four-category RUB/rate remain NULL;
historical brokerage-versus-IIS subtype, missing EOD, NKD/REPO and
money ownership are not guessed or filled with zero.

<a id="s1"></a>
## 1. Code, release, installed runtime and UAT are distinct

| Layer | Current verified status |
| --- | --- |
| Accepted code | #981/#982/#983 integrated; released target `536bb2336284b75cc6901570a7c196235326cf68`, exact-main [CI40682375464](https://github.com/LTstripes/hermes-finance/actions/runs/40682375464) SUCCESS. Earlier evidence retains its original scope; CI40653035431 attempt 1 recovery intermittency remains unexplained. |
| Published release | [v1.7.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.7.0), annotated tag `d8aaf8599bbbb05c105a6c1cb3c39b54a8d2ae6b`, peeled `536bb2336284b75cc6901570a7c196235326cf68`; guarded [release40684513085](https://github.com/LTstripes/hermes-finance/actions/runs/40684513085) SUCCESS. API `immutable=false`. |
| HONOR Stable | Operator-local 28 October OPS02/Prepare/Validate/Start PASS: v1.7.0 / 0066, health HTTP 200/ok, original physical DB/file identity and prior values/triggers/sequences/sidecar preserved; verified 0065 backup and producing v1.6.0 code bundle retained. Earlier source/proof and CLOSED-history evidence retains its scope. |
| Isolated Test | Old code `87624e12ef9d9d63c5df5b5f13703a4e3a7e3541` / isolated DB0066, stopped. New OPS03 was blocked before execution by the now-completed lifecycle Scan -Retire. Owner cancelled the separate aggregate Test on 28 October. |
| Owner UI UAT | New visual review deferred to evening/Thursday; main monthly UAT planned for 1 November. No new visual PASS, real financial DRAFT/forecast save or complete XIRR/TWRR acceptance. Earlier v1.6.0 UI GO retains its original scope. |
| Protected actions | Authorized release/Stable update completed with backup, binding and migration/recovery guards; no financial/provider actions performed. Financial Apply/save/Close remains separately gated; the earlier read-only provider diagnostic has no execution/result proof. Finance workspace-retirement schedule disabled by explicit Owner request; backups unaffected. |

Existing accepted custody-source proof remains a scoped source-only observation,
not an independent economic payout. Source money journal does not override
manual financial rows, historical CLOSED facts or unknown NKD valuation.

<a id="s2"></a>
## 2. What the user can do and what is already calculated

**Installed v1.7.0 (source-only semantics unchanged):** original files have source-only journal entries,
recognized positions/dated trades/Money/payouts, native account scope and
strict separate source-month DRAFT Preview/Apply route. Stored source observations
do **not** replace old manually entered financial rows automatically. The
source-proof-backed ordinary Month/Monthly Returns read-only preview shows
**two provisional monthly results on one native account (June/July 2026)**,
and **five monthly results on the other account (May–September 2026)**.
August's principal/custody event remains unaccepted; full calendar 2024–26
investment returns do not appear from long originals alone. Source-only
Modified Dietz is not accepted portfolio TWRR/XIRR or financial Close.

**Month and Returns retained in installed v1.7.0:**
- `/v2/close?month=id` is the normal **Month** hub. Compact report-month list,
  reusable manual form tiles, one inline work area, guarded unsaved/pending
  navigation, **Брокерские выписки** with one XML entry/source exceptions,
  recognized stock/bond quantity dates and read-only T-Invest preview,
  **Закрыть месяц** with server readiness and explicit Close→GET/recovery.
  Historical overlapping originals do not become missing October month-end
  valuations. [#962 accepted](https://github.com/LTstripes/hermes-finance/pull/962).
- `/v2/returns` is the new ordinary **Доходность** navigation: period/account,
  compact ₽/%/coupons/dividends cards, monthly history chart and table,
  instrument detail, profit/loss top five, keyboard-accessible ⓘ. Legacy
  full-history URLs (even without `bond_period`) and historical >12-month
  Back/Reload selection are preserved. Financial values reuse existing
  readers, not a new frontend calculation. [#964 accepted](https://github.com/LTstripes/hermes-finance/pull/964).
- [#965](https://github.com/LTstripes/hermes-finance/pull/965)
  retains applicable source advisory codes including `seam_mismatch` in the
  Returns presentation DTO/ⓘ and labels account-reconciliation growth as an
  **account** result. #962 separately fixes Month's false all-clear message.
  Neither changes P&L, Modified Dietz, or accounting authority.

**Now installed in v1.7.0 (previously absent from v1.6.0):** [#971](https://github.com/LTstripes/hermes-finance/pull/971)
exact-ISIN trusted instrument name fallback; [#972](https://github.com/LTstripes/hermes-finance/pull/972)
legacy month editor query/hash preserving redirect; [#975](https://github.com/LTstripes/hermes-finance/pull/975)
MyBroker documented source/parser fixes; [#976](https://github.com/LTstripes/hermes-finance/pull/976)
one native source-account per proven alias group, original account compatibility
and **«За доступные месяцы»** signed RUB subtotal/coverage with full historical
result kept separate; [#977](https://github.com/LTstripes/hermes-finance/pull/977)
compact properties and position/payout tables, Month flow order and source
observed/actual/forecast distinction plus fixed fast ISIN/date navigation;
[#979](https://github.com/LTstripes/hermes-finance/pull/979)
**«Моя доходность»** with four default-on categories (brokerage, IIS,
deposits/savings, physical gold), one period and URL/Back/Reload. Its honest
first slice returns **source-only available account-month RUB subtotal**
and **accepted deposit received interest separately**; composite RUB/%
and gold period result are explicitly unavailable, not computed by averaging
rates or present-day class inference. An external-flow/transfer/unknown coverage
cell is unavailable rather than 0. The basket GET does not change financial
data or silently reconcile forecasts with actual payouts. [#980](https://github.com/LTstripes/hermes-finance/pull/980)
preserves the selected source interval as an explicit Owner choice when no
CLOSED reporting month exists, while retaining explicit historical links and
correct dated quantity on the switched source instrument.

**Historical reconciliation completed, read-only:**
[private Owner analysis receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6397041341)
covered **72 native-account×calendar-month combinations** for 2024–2026.
At that readback, **7 ordinary provisional source month results** were
available; **17 exact position-number coincidences**, **4 quantity conflicts**
and **3 date/identity ambiguities** were identified. **Zero** old manual row
replacements were eligible: intersecting facts belong to CLOSED. Five earliest
opening-value operands and various intervening EOD/monthly price boundaries
are genuinely absent. No full-archive source reimport or blanket manual DELETE
is needed or approved.

**Remaining finance evidence:** one account's August 2026 cancellation/principal/
cash ownership and double-payment question; September settlement/NKD/commission
broker reply ([#814 field-definition receipt](https://github.com/LTstripes/hermes-finance/issues/814#issuecomment-6442328623),
REPLY RECEIVED / PARTIAL: trade field meanings supplied, five Money NKD→trade
links still BLOCKED; signed final letter unverified). The authorized R1 reader
correction is separate from original-bound #767/R2 dirty-EOD acceptance and real
financial authority. June REPO/custody question
([#888](https://github.com/LTstripes/hermes-finance/issues/888), UNSENT).
Stock returns can be supported on exact scoped periods; full bond economic
P&L/MD requires documented valuation clean/dirty/NKD basis and movements.
There remain reported **88 unresolved payout source observations** and **16
trade-only instrument types** requiring scoped evidence. Do not mistake
observations across overlapping statements for distinct payments.

<a id="s3"></a>
## 3. Next actions, in priority order

1. **Deferred Owner acceptance:** visual review is planned for evening/Thursday and the main monthly UAT for 1 November. v1.7.0 publication and guarded Stable installation are complete; do not repeat release, migration or aggregate Test solely for handoff. Installation/readback is not a visual or monthly UAT PASS.
2. **Separately scoped finance:** real DRAFT Apply, forecast save/refresh, Close and any provider action retain their exact scope, currentness and separate authority. The deployment performed none of those actions. Preserve the verified original backup and producing code/schema pair; no automatic downgrade, cross-schema overwrite or Test-to-Stable data promotion.
3. **Source evidence not blocking honest UI:** unresolved 2024–26 monthly EOD, four position discrepancies, three identity-date ambiguities, August principal, REPO [#888](https://github.com/LTstripes/hermes-finance/issues/888), NKD [#814](https://github.com/LTstripes/hermes-finance/issues/814), old #767 dirty EOD and #769 history acceptance stay their owning financial tasks. Do not fill NULLs, fake gold P&L, duplicate income or re-open closed bugs; standalone month editor remains KEEP pending real consumer retirement.

<a id="s4"></a>
## 4. Operating and evidence boundaries

Single accountable Owner/Operator for physical Windows Stable and its personal
files; reviewers/Integrators can independently verify GitHub but do not
implicitly access the user's local original XML or database. Financial facts
stay private. All real changes need exact supported Preview, independent
currentness/readback, backup and stage-specific Owner GO. Source-only Save,
proof Confirm, derived metadata relink, financial DRAFT Apply and Close are
different operations, not aliases. CLOSED requires explicit Reopen.
Do not use a pending PR as production code or treat a clean source journal as
portfolio financial acceptance. An agent checkout paused after `unsafe-entry`
must not be force-reset/cleaned; this is separate from the installed runtime.

Historical delivery evidence is retained in [#940](https://github.com/LTstripes/hermes-finance/issues/940),
[#711](https://github.com/LTstripes/hermes-finance/issues/711),
[#891](https://github.com/LTstripes/hermes-finance/issues/891),
the corresponding PR receipts and published [v1.6.0 release notes](release-notes-1.6.0.md).
Current release scope is described in [v1.7.0 release notes](release-notes-1.7.0.md).

