# Current state, limitations and next actions

Updated **2026-10-27**. This is the sole changing project status book. Current source
behavior is specified by [P](MASTER_SPEC.md), numeric/data authority by
[C](ARCHITECTURE_AND_CONTRACTS.md), integration by [D](DEVELOPMENT.md), and
runtime/recovery by [O](OWNER_RUNTIME_OPERATIONS.md). Historical PR comments
are evidence for their dated stage, not a newer installation status.

## Current checkpoint

**GitHub CODE MERGED (2026-10-27):** canonical `main@df1e6884fa7e70cb3559363d5fb1f90b18f11093`
contains the accepted [#976](https://github.com/LTstripes/hermes-finance/pull/976)
source-account alias grouping and honest partial RUB history, [#977](https://github.com/LTstripes/hermes-finance/pull/977)
one Month path/compact desktop forms and verified stale ISIN/date navigation fix, and
[#979](https://github.com/LTstripes/hermes-finance/pull/979) the read-only
four-checkbox «Моя доходность» basket. [#977 exact-main CI40575981857](https://github.com/LTstripes/hermes-finance/actions/runs/40575981857)
**SUCCESS** on `main@6129090c62b9da69ee0ad3521aef77d675a51925`.
[#979 exact candidate CI40567222067](https://github.com/LTstripes/hermes-finance/actions/runs/40567222067)
attempt 2 and [UI40567222060](https://github.com/LTstripes/hermes-finance/actions/runs/40567222060)
**SUCCESS** with one evidence-based G04 transport retry, independently reviewed.
**Final combined-main [CI40580924918](https://github.com/LTstripes/hermes-finance/actions/runs/40580924918): FAILED** on the exact merged SHA: Frontend 1/1356 tests failed on absent CLOSED default selecting a source period without Owner choice. Bounded [Draft #980](https://github.com/LTstripes/hermes-finance/pull/980) corrects this implicit selection and its regression; its exact CI/review are pending.
No new aggregate Test/Owner-real UI UAT is implied by PR or CI evidence.

The earlier [#976 push-main failure40557762042](https://github.com/LTstripes/hermes-finance/actions/runs/40557762042)
was a genuine Month stale ISIN/date control P2 and remains dated failure evidence;
the fixed [#977 HEAD](https://github.com/LTstripes/hermes-finance/pull/977#issuecomment-6452270051)
passed deterministic BrowserRouter cases and G04, independently reviewed and then merged.
No blanket test skip, assertion reduction or unexplained retry is accepted.

**Published/installed Stable remains [v1.6.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.6.0)**,
immutable peeled SHA `d53a67409be4283f08f622218743ff5ef8e66ff0`,
SQLite `0065_source_return_proofs`. [Owner-local Stable receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6408493088)
attests correct service/physical DB and preserved old CLOSED, sources and financial
history; later [Operator #711 addendum](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6446621985)
attests SAME Stable restored. These are attributed Windows-local results, not a fresh cloud DB inspection.

**Isolated Test:** [#711 Operator technical rehearsal](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6446728835)
PASS on the previous pinned Test code `87624e12ef9d9d63c5df5b5f13703a4e3a7e3541`;
its existing physically isolated DB was migrated `0065→0066_actual_payout_links`,
old values/receipts/9 CLOSED preserved and 35 real-history GETs passed.
The Test was then **stopped on 0066**, Stable restored to 0065. This is **NOT**
Test preparation/UAT of the newer `df1e6884` main, not actual source DRAFT,
forecast saving, native Chrome, financial Close or an approved Stable upgrade.

**Remaining product gate:** Owner changed [#711 forecast plan](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6450994944)
to **broker XML → reviewed actual financial DRAFT/GET → one explicit T-Invest batch
lookup/save/refresh of forecasts → GET calendar** through existing PositionSnapshot/
provider-payout revision writers. This **is not implemented by #977/#979**.
A prior source-journal-only forecast-writer HOLD is superseded for this simpler
DRAFT-based route, but strict DRAFT can_apply/source account requirements still apply.
Owner authorized [one separate read-only live T-Invest Test probe](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6450551962);
no actual provider result is verified in GitHub yet.

**Portfolio honesty:** known source-only account-month RUB values, accepted
deposit interest and unavailable gold/composite return keep their distinct
basis. Basket `result_kopecks` and overall rate remain NULL; a
checkbox selection does not manufacture full cross-category returns, a
2024–2026 monthly valuation, accepted dividends or exact XIRR/TWRR.
Unresolved NKD/REPO/EOD evidence is separate from honest UI acceptance.

<a id="s1"></a>
## 1. Code, release, installed runtime and UAT are distinct

| Layer | Current verified status |
| --- | --- |
| GitHub `main` | `df1e6884fa7e70cb3559363d5fb1f90b18f11093`, #976/#977/#979 merged after independent code/financial review. #977 exact [push CI40575981857](https://github.com/LTstripes/hermes-finance/actions/runs/40575981857) SUCCESS; #979 final combined [push CI40580924918](https://github.com/LTstripes/hermes-finance/actions/runs/40580924918) **IN_PROGRESS / not terminal**. PR CI success is not itself this final gate. |
| Published release | [v1.6.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.6.0), peeled `d53a6740…`, released schema 0065. No release yet for #970/0066 or new Month/Returns changes. |
| HONOR Stable | Attributed local receipts: same published v1.6.0/0065 and protected physical DB, originals, proof receipts and 9 CLOSED preserved. New main code not installed. |
| Isolated Test | Operator technical 0065→0066 PASS and 35 scoped GETs on pinned `87624e12…`, then Test stopped; no new `df1e6884` repin/desktop acceptance. |
| Owner UAT | Earlier [v1.6.0 Month/Returns Owner UI GO](https://github.com/LTstripes/hermes-finance/issues/963#issuecomment-6401873080) plus Stable smoke do **not** certify new #977/#979 UI, DRAFT→T-Invest persistence, actual financial Save/Apply/Close/Reopen or exact full-period return. |
| Protected operations | Separate exact scope/physical binding/backup and Owner GO for Test changes, live provider usage, financial writes, release #124 and Stable OPS02/Start. One read-only T-Invest probe was approved, not attested complete. |

Existing accepted custody-source proof remains one scoped source-only observation
identity, not a second economic payout. Stored source income and original journals
do not automatically replace manual financial rows, prove bond clean/dirty/NKD
basis or grant full portfolio returns.

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
data or silently reconcile forecasts with actual payouts.

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

1. **Code/integration gate:** exact [combined-main CI40580924918](https://github.com/LTstripes/hermes-finance/actions/runs/40580924918) FAILED on `df1e6884fa7e70cb3559363d5fb1f90b18f11093`: Frontend no-CLOSED source-period test exposes a real late implicit selection; do not rerun it unchanged. [Draft #980](https://github.com/LTstripes/hermes-finance/pull/980) targets only that fallback and its no-auto-selection regression. Requires independent review, exact PR CI/UI and guarded integration with a new exact-main push SUCCESS before Test/release. Old #976 ISIN race and #979 transport retry remain dated, separately established cases.
2. **Finish the simple #711 source-financial-DRAFT payout workflow:** [accepted Owner decision](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6450994944) requires a successful supported financial DRAFT Preview/Apply/independent GET BEFORE existing T-Invest batch preview and forecast Apply; one explicit button, unique exact ISIN→UID or manual exception, repeated click safely revises only forecasts and GET/Reload never calls provider. Reuse existing snapshot, mapping, applied-provider payout/revision and #970 paid-state contracts, with focused synthetic regressions and independent financial review. If `can_apply=false`, do not fabricate a position or weaken broker source guards. This CODE work is **not delivered**.
3. **Combined Test and Owner UI/UAT:** after final accepted code and exact-main CI, use supported OPS03 on the existing isolated Test, confirm exact code/physical 0066 DB and migration compatibility without repeating accepted old backup/migration unnecessarily; compare Month → statement/exception/financial DRAFT readiness → payouts and T-Invest stored calendar → Returns four checkboxes/period/Back/Reload, NULL/known partial. The prior Test 0066 PASS was at an earlier code SHA and cannot count as this candidate's UI UAT. Only one separately authorized real read-only T-Invest diagnostic exists; real forecast writes, DRAFT Apply, live batch provider or Close in protected data require appropriate additional Owner GO. Return unchanged Stable after bounded Test.
4. **One new release then safeguarded Stable:** after exact combined Main/Owner Test acceptance, prepare canonical version/notes, release-control #124 and an independent release review. **Publication and backup-first OPS02 Stable 0065→0066 plus separate owned Start require their own specific Owner approvals** and fresh physically verified backup/recovery cutoff. Test DB/rows never copied onto Stable; an in-place populated 0066→0065 downgrade is not a recovery promise. No automatic release just from CI green.
5. **Other financial/source follow-ups are separate:** [#769](https://github.com/LTstripes/hermes-finance/issues/769)/[#891](https://github.com/LTstripes/hermes-finance/issues/891)/[#709](https://github.com/LTstripes/hermes-finance/issues/709)/[#940](https://github.com/LTstripes/hermes-finance/issues/940) own missing 2024–26 intermediate EODs, four quantity discrepancies, three date/identity ambiguities, August principal, June REPO [#888](https://github.com/LTstripes/hermes-finance/issues/888), September NKD links [#814](https://github.com/LTstripes/hermes-finance/issues/814) and full bond economic authority. These are not a reason to hide already supported partial numbers or invent exact composite rates. Legacy standalone month editor remains KEEP; old draft #744 and other unrelated work are not part of this release.

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
