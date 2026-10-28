# Current state, limitations and next actions

Updated **2026-10-28**. This is the sole changing project status book. Current source
behavior is specified by [P](MASTER_SPEC.md), numeric/data authority by
[C](ARCHITECTURE_AND_CONTRACTS.md), integration by [D](DEVELOPMENT.md), and
runtime/recovery by [O](OWNER_RUNTIME_OPERATIONS.md). Historical PR comments
are evidence for their dated stage, not a newer installation status.

## Current checkpoint

**Canonical GitHub `main@20ada2079114a3a7fded71283f2ae38776dbefb5` — code merged, final push CI pending at this checkpoint.**
Accepted work: [#976](https://github.com/LTstripes/hermes-finance/pull/976)
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
**Canonical final-main [CI40629971268](https://github.com/LTstripes/hermes-finance/actions/runs/40629971268)
is QUEUED, not a verified success** at this document checkpoint.
Do not release or repin Test solely on PR CI.

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

**Published and installed Stable remains [v1.6.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.6.0)**,
peeled SHA `d53a67409be4283f08f622218743ff5ef8e66ff0`,
SQLite `0065_source_return_proofs`.
[Owner-local Stable receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6408493088)
and later [Operator #711 return receipt](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6446621985)
attest its physical DB, old source/proof rows, CLOSED history and service readback.
These are attributed Operator-local proofs, not new cloud observation.

**Isolated Test:** prior pinned code `87624e12ef9d9d63c5df5b5f13703a4e3a7e3541`
was technically verified by [#711 0066 migration/read-only
receipt](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6446728835);
the existing Test DB is on `0066_actual_payout_links` but Test stopped,
and same published Stable returned on its 0065 DB.
35 Owner-history GETs PASS; no newer `main@20ada207` Test preparation,
native desktop Owner UAT, actual financial DRAFT/Apply/Close or physical restore
has been accepted.

**Product/release boundary:** [#711 revised Owner decision](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6450994944)
is **XML → source review → accepted financial DRAFT/GET → one-click T-Invest
batch lookup, safe forecast save/refresh and calendar GET** using existing
PositionSnapshot/provider payout revision writers. The one-click bulk
forecast writer **is NOT delivered by #977/#980**. The former source-only
persisted-forecast design STOP no longer governs the chosen DRAFT-first path.
Owner approved [one separately scoped local read-only T-Invest Test
request](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6450551962),
but no successful real provider auth/result has yet been attested.
No additional release, Test/Stable operation or financial write is authorized
by code acceptance.

**Financial limits:** source-only RUB account-month amounts and accepted deposit
interest are separate read models, not summed into a total personal portfolio
return. Gold period returns and the full four-category RUB/rate remain NULL;
historical brokerage-versus-IIS subtype, missing EOD, NKD/REPO and
money ownership are not guessed or filled with zero.

<a id="s1"></a>
## 1. Code, release, installed runtime and UAT are distinct

| Layer | Current verified status |
| --- | --- |
| GitHub `main` | `20ada2079114a3a7fded71283f2ae38776dbefb5`, #976/#977/#979/#980 merged; independent #980 GO, [PR CI40584079496](https://github.com/LTstripes/hermes-finance/actions/runs/40584079496) + [UI40584079506](https://github.com/LTstripes/hermes-finance/actions/runs/40584079506) SUCCESS. **Exact main [push CI40629971268](https://github.com/LTstripes/hermes-finance/actions/runs/40629971268) QUEUED**, not yet PASS. |
| Published release | [v1.6.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.6.0), peeled `d53a6740…`, installed schema 0065. No newer published release or Stable installation. |
| HONOR Stable | Owner-local evidence: same v1.6.0/0065 and original protected DB, immutable receipts and 9 CLOSED unchanged after Test rehearsal. |
| Isolated Test | Old code `87624e12…` with migrated isolated DB 0066, then stopped. No new `20ada207` runtime/Owner UAT. |
| Owner UI UAT | Earlier v1.6.0 UI GO/Stable smoke is NOT new Month/Returns owner browser UAT, financial DRAFT→T-Invest real forecast Apply or full exact XIRR/TWRR. |
| Protected actions | Explicit physical Test/Stable binding, backup/recovery and stage-specific Owner GO before local repin, provider or real financial writes, release-control #124 and Stable OPS02/Start. One read-only T-Invest diagnostic is authorized, with no returned proof. |

Existing accepted custody-source proof remains a scoped source-only observation,
not an independent economic payout. Source money journal does not override
manual financial rows, historical CLOSED facts or unknown NKD valuation.

<a id="s2"></a>
## 2. What the user can do and what is already calculated

**Installed v1.6.0 (source-only semantics unchanged):** original files have source-only journal entries,
recognized positions/dated trades/Money/payouts, native account scope and
strict separate source-month DRAFT Preview/Apply route. Stored source observations
do **not** replace old manually entered financial rows automatically. The
source-proof-backed ordinary Month/Monthly Returns read-only preview shows
**two provisional monthly results on one native account (June/July 2026)**,
and **five monthly results on the other account (May–September 2026)**.
August's principal/custody event remains unaccepted; full calendar 2024–26
investment returns do not appear from long originals alone. Source-only
Modified Dietz is not accepted portfolio TWRR/XIRR or financial Close.

**Month and Returns available in installed v1.6.0:**
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

**Merged but not installed in v1.6.0:** [#971](https://github.com/LTstripes/hermes-finance/pull/971)
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

1. **Exact canonical-main gate:** read terminal [CI40629971268](https://github.com/LTstripes/hermes-finance/actions/runs/40629971268) on `20ada2079114a3a7fded71283f2ae38776dbefb5`. Only terminal SUCCESS of required jobs, including G04/native and `ci-ok`, accepts this combined main; any failure needs a concrete remedy, exact new CI, and updated status. No assertion weakening or unchanged blind rerun.
2. **Complete the agreed #711 DRAFT-first provider feature:** after exact-main GO, one Worker implements [the accepted minimal plan](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6450994944). Strict supported MyBroker Preview/Apply/GET financial DRAFT precedes the existing T-Invest PositionSnapshot batch preview and safe forecast Apply. One explicit action discovers exact ISIN/UID, stores or revises only unambiguous future forecasts, leaves duplicate/uncertain events for review, returns clear GET/readback; repeat click cannot duplicate/retire proved actuals. No source-only new forecast ledger/schema, no autofill of UNKNOWN tax/amount. Require independent financial/source review and exact code CI. This functionality is **not yet merged**.
3. **One bounded aggregate Test/Owner UI pass:** after the accepted complete code candidate and successful exact-main CI, OPS03 prepares the existing isolated Test for the precise SHA, with physical process/profile/DB identity and 0066 compatibility guards. Previous 0065→0066 Test technical PASS can be reused; it does not certify the newer code or a live UI. Owner visually checks Month desktop fields/route, source-financial DRAFT availability, payout forecast persistence/Back/Reload, Returns categories and partial/NULL coverage. Provider tests require explicit current authorized scope; real Source/Apply/Close actions on protected data remain individually gated. Restore the unchanged Stable after bounded Test.
4. **One guarded release then Stable:** after Owner test verdict and eligible exact release candidate, canonical version+notes, guarded #124 publication, separate Owner release GO, and backup-first stable OPS02/Start under separate approval with independent recovery/readback. Stable is still 0065; new main includes 0066. Never copy Test DB to Stable or treat an in-place 0066→0065 downgrade as a recovery method.
5. **Source evidence not blocking honest UI:** unresolved 2024–26 monthly EOD, four position discrepancies, three identity-date ambiguities, August principal, REPO [#888](https://github.com/LTstripes/hermes-finance/issues/888), NKD [#814](https://github.com/LTstripes/hermes-finance/issues/814), old #767 dirty EOD and #769 history acceptance stay their owning financial tasks. Do not fill NULLs, fake gold P&L, duplicate income or re-open closed bugs; standalone month editor remains KEEP pending real consumer retirement.

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
the corresponding PR receipts and published [release notes](release-notes-1.6.0.md).
