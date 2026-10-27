# Current state, limitations and next actions

Updated **2026-10-27**. This is the sole changing project status book. Current source
behavior is specified by [P](MASTER_SPEC.md), numeric/data authority by
[C](ARCHITECTURE_AND_CONTRACTS.md), integration by [D](DEVELOPMENT.md), and
runtime/recovery by [O](OWNER_RUNTIME_OPERATIONS.md). Historical PR comments
are evidence for their dated stage, not a newer installation status.

## Current checkpoint

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
not direct cloud observation. **Test remains stopped.** No #970 schema 0066
migration or #971/#972 main-only code was installed by this merge.

**Finance/UAT boundary:** #970 is accepted source code and synthetic finance
coverage, **not real financial Apply/Close or end-to-end Owner UAT**. Real
Owner data/schema 0065→0066 transition, isolated Test, full history reconstruction,
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
| GitHub `main` | `3d7fac67...`, #970 merged; exact tested tree is identical to reviewed synthetic merged tree. Exact [main CI40457523342](https://github.com/LTstripes/hermes-finance/actions/runs/40457523342) is **COMPLETED SUCCESS (28 successful, 3 expected skipped, terminal ci-ok SUCCESS)**. #971 Returns names and #972 legacy query/hash fix are merged and have earlier exact-main CI SUCCESS. |
| Published release | [v1.6.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.6.0), unchanged tagged SHA `d53a6740...`; `0065`. No release exists for #970/`0066` or later main-only changes. |
| HONOR Stable | Owner-local [Operator LIVE/health/UI receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6408493088): published v1.6.0 installed/running; same physical DB, 78 tables, 10 originals, 9 CLOSED, financial/source proof records unchanged; Test stopped. |
| Owner UI UAT | [Month/Returns Owner GO](https://github.com/LTstripes/hermes-finance/issues/963#issuecomment-6401873080), then installed v1.6.0 local UI smoke PASS including Back/Reload; native Windows DPI/zoom matrix not independently certified. New #970 financial flows are synthetic/API/browser code acceptance **only**, no Owner-real financial action UAT. |
| Protected operations | Actual financial Apply/Close/Reopen, real import/source edits, `0066` installation, Test/Stable migration, provider calls and release require separate applicable authority; guarded code merge is not such approval. |

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

**Newer source-only main UI improvements (not yet installed in v1.6.0):**
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

1. **Plan one protected 0066 Test slice, not an automatic rollout:** use the
   accepted synthetic #970 contract and C9/O procedures. Before any real Test/
   Owner DB action, require authorized physical selector, backup-first
   isolated rehearsal, 0065 guard/index drift preflight, rollback/readback
   and explicit financial user-path UAT. Historical CLOSED and existing originals
   must remain untouched. Same-schema snapshot restore is distinct from
   an unsafe cross-schema downgrade; no production `0066` or Stable GO yet.
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
