# Current state, limitations and next actions

Updated **2026-10-27**. This is the sole changing project status book. Current source
behavior is specified by [P](MASTER_SPEC.md), numeric/data authority by
[C](ARCHITECTURE_AND_CONTRACTS.md), integration by [D](DEVELOPMENT.md), and
runtime/recovery by [O](OWNER_RUNTIME_OPERATIONS.md). Historical PR comments
are evidence for their dated stage, not a newer installation status.

## Current checkpoint

**Integration HOLD (2026-10-27):** Returns A–C [#976](https://github.com/LTstripes/hermes-finance/pull/976)
was guarded squash-merged at `a79d4b4d343638afbbab0c5c1638996e8562ec23`.
Its tree `50a296a5b3f643cae2f06fb3fbd0509678b57566` equals reviewed candidate
`516c5a51846ff55dfacf99ecca35e1d809216f05`. Independent financial/source review,
[exact PR CI](https://github.com/LTstripes/hermes-finance/actions/runs/40547819410)
and [UI evidence](https://github.com/LTstripes/hermes-finance/actions/runs/40547819452)
passed. However [exact main push CI40557762042](https://github.com/LTstripes/hermes-finance/actions/runs/40557762042)
**FAILED** in the G04/native broker-month journey. Integration is not complete;
no release/runtime approval or successful main gate is implied. See the
[Integrator failure receipt](https://github.com/LTstripes/hermes-finance/pull/976#issuecomment-6450400655).

**P2:** after switching stock→bond, an outgoing historical-quantity date control
can write captured URL parameters and remove the newer `instrument_isin`,
silently restoring the stock selection/quantity. The retained CI trace proves
bond URL→old date-control event→stock URL; `broker-month.acceptance.ts:171`
failed, 23 other broker-month cases passed and later required journeys were
skipped. One fresh local exact-main scenario passed; timing dependence does not
invalidate the concrete failing trace. This is an existing Month race, not
introduced by the Returns-only #976 diff. Do not resolve it with weakened
assertions, test waits or blind reruns.

Month UX [#977](https://github.com/LTstripes/hermes-finance/pull/977) remains
**Draft/unmerged** at `7f236101c6018e38e1bec6e842314612f01e6a5d`.
Its [exact CI](https://github.com/LTstripes/hermes-finance/actions/runs/40553681805)
and [UI evidence](https://github.com/LTstripes/hermes-finance/actions/runs/40553681819)
passed, but the same handlers remain. The [new P2 review/HOLD](https://github.com/LTstripes/hermes-finance/pull/977#pullrequestreview-5672373011)
supersedes the earlier Integrator GO. No #977 merge or rollback of #976 occurred.
The clean combined candidate tree `cd40c9fcf20b14f55eed5f916546abdb84ec9e96`
had 94 affected frontend tests, 74 backend tests, production build and one
synthetic desktop browser test PASS; those checks do not replace the failed
canonical-main gate. The unchanged global 422 error renderer also still drops
exception headers; successful Returns reads retain `no-store`.

**Earlier accepted code checkpoint:**
**Code integrated into canonical main:** [PR #970](https://github.com/LTstripes/hermes-finance/pull/970)
durable actual payout settlement/strict dividend Money v2/scoped financial Close
and the additive SQLite `0066_actual_payout_links` contract were independently
reviewed [GO on the exact head](https://github.com/LTstripes/hermes-finance/pull/970#pullrequestreview-5662750129)
and guarded squash-merged to `main@3d7fac67a630844099c35838a85bfd745e7016ab`.
The actual merged tree `6a3f3d37b7ad6c3d8f2d96a7a1a6b86433d3ac60`
equals the reviewed/tested synthetic-merge tree. [Exact candidate CI40453651414](https://github.com/LTstripes/hermes-finance/actions/runs/40453651414)
and [UI comparison40453651427](https://github.com/LTstripes/hermes-finance/actions/runs/40453651427)
are SUCCESS. [Exact **main** push CI40457523342](https://github.com/LTstripes/hermes-finance/actions/runs/40457523342)
is **COMPLETED SUCCESS (28 successful, 3 expected skipped, terminal ci-ok SUCCESS)**.
Source-only regressions [#969](https://github.com/LTstripes/hermes-finance/pull/969),
Returns exact-ISIN names [#971](https://github.com/LTstripes/hermes-finance/pull/971)
and legacy month redirect [#972](https://github.com/LTstripes/hermes-finance/pull/972)
are already merged; their prior respective exact push CIs succeeded.

**Published and running Stable is independently pinned to [v1.6.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.6.0)**,
immutable peeled SHA `d53a67409be4283f08f622218743ff5ef8e66ff0`,
schema `0065_source_return_proofs`. [Owner-local Operator's rollout receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6408493088)
reports health `ok/version=1.6.0`, Month/Returns + Back/Reload smoke PASS,
physical DB identity/hash and all **78 tables, 10 originals, 9 CLOSED** and
source-proof/financial history preserved. These are attributed local proofs,
not direct cloud observation. These dated Stable rollout facts remain separate
from the later Test technical rehearsal below.

**Latest accepted Test stage:** [Operator addendum](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6446621985)
and [Integrator acceptance](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6446728835)
attest technical PASS at pinned Test `87624e12ef9d9d63c5df5b5f13703a4e3a7e3541`:
stock OPS03/Validate, existing physical Test DB migration 0065→0066, preservation
and 35 read-only history GETs. Same Stable v1.6.0/0065 was returned; Test was
stopped at 0066. Native desktop/Owner UAT and physical restore remain unaccepted.
This is attributed Operator evidence, not a fresh runtime inspection. Reusing
this accepted stage does not require another migration. Newer main code was not
silently installed. This review made no Test/Stable/provider/financial changes.

**Finance/UAT boundary:** #970 is accepted source code and synthetic finance
coverage, **not real financial Apply/Close or end-to-end Owner UAT**.
Remaining Owner UI/financial UAT, new Test operations, full history reconstruction,
provider operations, release and Stable transition are separate gates with backup,
currentness, exact supported readback and explicit stage-specific Owner GO.
The one-user desktop Month route remains primary; standalone editor is intentionally
[KEEP](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6423656157).
Neither source-only journal entries nor indicative period results become accepted
portfolio XIRR/TWRR merely because financial link code was merged.

<a id="s1"></a>
## 1. Code, release, installed runtime and UAT are distinct

| Layer | Current verified status |
| --- | --- |
| GitHub `main` | `a79d4b4d...`, #976 merged on #975 baseline `2da61058...`; exact-main CI40557762042 FAILED, integration HOLD on the Month selection P2. #977 stays Draft/unmerged. Earlier accepted #970/#971/#972 remain included. |
| Published release | [v1.6.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.6.0), unchanged tagged SHA `d53a6740...`; `0065`. No release exists for #970/`0066` or later main-only changes. |
| HONOR Stable | Owner-local [Operator LIVE/health/UI receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6408493088): published v1.6.0 installed/running; same physical DB, 78 tables, 10 originals, 9 CLOSED, financial/source proof records unchanged; Test stopped. |
| Isolated Test | Accepted Operator receipt: pinned `87624e12...`, existing DB migrated to 0066 with preservation/35 GETs PASS, then stopped. Native desktop UAT remains pending; this is not newer main code. |
| Owner UI UAT | [Month/Returns Owner GO](https://github.com/LTstripes/hermes-finance/issues/963#issuecomment-6401873080), then installed v1.6.0 local UI smoke PASS including Back/Reload; native Windows DPI/zoom matrix not independently certified. New #970 financial flows are synthetic/API/browser code acceptance **only**, no Owner-real financial action UAT. |
| Protected operations | Actual financial Apply/Close/Reopen, real import/source edits, further Test/Stable changes, provider calls and release require separate applicable authority. Test technical migration does not approve Stable 0066 or real financial UAT. |

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

**Newer source-only main UI improvements (not installed by this integration):**
[#976](https://github.com/LTstripes/hermes-finance/pull/976) adds source-account
selection and separate signed partial RUB totals with coverage; its canonical
main gate is blocked as described above. Month UX #977 is still a candidate.

[#971](https://github.com/LTstripes/hermes-finance/pull/971) resolves trusted
instrument names by exact ISIN; [#972](https://github.com/LTstripes/hermes-finance/pull/972)
preserves old month editor URL query/hash without removing its independent
GET/recovery. Neither changes the published Stable binary.

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

1. **Clear the integration HOLD:** preserve the newest account/ISIN/month
   identity when changing the quantity date, retire outgoing controls as needed,
   and add deterministic stale-control plus API→browser regressions. Require
   independent review, exact candidate CI and full exact-main push CI before
   declaring integration complete or merging #977. No blind retry or assertion
   weakening. The bulk source T-Invest action and mixed-category Returns basket
   remain [separate #711](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6448461231)
   / [#963 D](https://github.com/LTstripes/hermes-finance/issues/963#issuecomment-6448489993)
   follow-ups. Any later authorized Test UI stage reuses the accepted technical
   0066 migration, first confirms physical profile/code/DB binding and verifies
   native Chrome Month→Money/reconciliation→Returns with Back/Reload. New code
   preparation/repin is a distinct operation. T-Invest token validity remains
   unverified; Settings uses the selected checkout's configuration and the
   default adapter calls public T-Bank API, not a local-Test-selected sandbox.
   A live diagnostic request needs separate explicit Owner authorization.
2. **Owner data completeness remains separate:** reuse #769/#891/#709/#940 to
   resolve four account/instrument quantity disagreements, three date
   ambiguities, genuinely absent opening/intervening monthly EOD, August
   principal/cash ownership, June REPO and September NKD/settlement proofs.
   Only supported periods receive supported returns; source-only or partial
   figures remain qualified. Never infer 2024 monthly valuations from long XML.
3. **Later release/Stable:** once #970's real user route and recovery have
   been accepted on a separately authorized isolated Test and exact release
   candidate passes review/CI, request Owner publication and a distinct
   backup-first Stable decision; keep the published v1.6.0 tag/runtime unchanged
   until then. No one-step direct main→Stable installation.
4. **Nonblocking cleanup:** [#940 Astra audit](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6423656157)
   says standalone month editor **KEEP**, with #972 already addressing the
   legacy redirect. [#963](https://github.com/LTstripes/hermes-finance/issues/963)
   name fallback still honestly shows ISIN without a trusted name. Review older
   [draft #927](https://github.com/LTstripes/hermes-finance/pull/927) synthetic
   parser findings against modern main before adopting them; do not reopen
   closed #960/#969 regressions or duplicate #711. Defer retired route cleanup
   until actual consumer/route evidence and accepted replacement, and
   [#856 AI export](https://github.com/LTstripes/hermes-finance/issues/856)
   until supported investment results exist.

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
