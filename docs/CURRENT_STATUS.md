# Current state, limitations and next actions

Updated **2026-10-27**. This is the sole changing project status book. Current source
behavior is specified by [P](MASTER_SPEC.md), numeric/data authority by
[C](ARCHITECTURE_AND_CONTRACTS.md), integration by [D](DEVELOPMENT.md), and
runtime/recovery by [O](OWNER_RUNTIME_OPERATIONS.md). Historical PR comments
are evidence for their dated stage, not a newer installation status.

## Current checkpoint

**Canonical GitHub code merged:** `main@3d7fac67a630844099c35838a85bfd745e7016ab`.
[PR #970](https://github.com/LTstripes/hermes-finance/pull/970) delivers
**code and synthetic tests** for #711 durable source-owned payout↔forecast
reconciliation, strict dividend Money v2, scoped Close and
`0066_actual_payout_links`. [Independent exact-head financial/source/migration
GO](https://github.com/LTstripes/hermes-finance/pull/970#pullrequestreview-5662750129)
followed several disclosed NO-GO reproductions; the final accepted head is
`da99453db8789fbdfba4f6852e63aac74a9fa8ef`.
The [candidate CI40453651414](https://github.com/LTstripes/hermes-finance/actions/runs/40453651414)
and [UI40453651427](https://github.com/LTstripes/hermes-finance/actions/runs/40453651427)
are both SUCCESS (candidate CI attempt 2; first native Month
`AdmissionError` was not diagnosed). Verified GitHub merge tree
`6a3f3d37b7ad6c3d8f2d96a7a1a6b86433d3ac60` equals the exact tested
synthetic merge with current main. [New exact-main push
CI40457523342](https://github.com/LTstripes/hermes-finance/actions/runs/40457523342)
is **IN PROGRESS** at this checkpoint; code merge does not yet imply terminal
canonical CI PASS.

**Already integrated usability:** [#971](https://github.com/LTstripes/hermes-finance/pull/971)
uses an exact-ISIN name from existing source/catalogue when available; otherwise
shows honest ISIN. [#972](https://github.com/LTstripes/hermes-finance/pull/972)
preserves legacy Month editor search/hash/Back return context. Both were
guarded-merged with independent review and exact push CI SUCCESS. Standalone
manual editor shell remains KEEP after [read-only architecture audit](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6423656157).

**Published and locally running Stable remains v1.6.0**, **NOT this main**:
[immutable Release v1.6.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.6.0)
peels to `d53a67409be4283f08f622218743ff5ef8e66ff0`, schema
`0065_source_return_proofs`. [Final HONOR-local Operator receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6408493088)
reports authorized backup-first Prepare/Validate and separate Start,
health 1.6.0, Month/Returns/Back/Reload smoke PASS, unchanged physical DB
hash, **78 tables, 10 originals and 9 CLOSED**, original finance/source
proofs retained. These are local Operator-attributed observations, not direct
cloud inspection. **Stable continues to run; Test remains stopped.**
**No real 0066 migration, real payout Apply/Close/Reopen, broker XML import,
T-Invest provider call, release or Stable installation is authorized by
this code merge.** Parent [#711](https://github.com/LTstripes/hermes-finance/issues/711)
remains OPEN for isolated migration rehearsal, real financial UAT and any
remaining source→position/forecast quantity evidence gaps.

<a id="s1"></a>
## 1. Code, release, installed runtime and UAT are distinct

| Layer | Current verified status |
| --- | --- |
| Canonical GitHub main | `3d7fac67…`, #971/#972 usability and #970 financial 0066 source code **MERGED**; reviewed tree equals tested GitHub merge tree. [Exact push CI40457523342](https://github.com/LTstripes/hermes-finance/actions/runs/40457523342) **IN PROGRESS** until terminal ci-ok. |
| Independent code acceptance | #970 [exact-head GO](https://github.com/LTstripes/hermes-finance/pull/970#pullrequestreview-5662750129), [PR CI attempt 2](https://github.com/LTstripes/hermes-finance/actions/runs/40453651414) SUCCESS and [UI comparison](https://github.com/LTstripes/hermes-finance/actions/runs/40453651427) SUCCESS. Synthetic 0065→0066 migration, 136 old trigger SQL bodies, index graph, four rollback checkpoints and P1/P2 boundary fixes are tested; **no Owner data migration is implied**. |
| Published release | [v1.6.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.6.0) at `d53a6740…`, schema 0065. New merged main/0066 has **no published release**. |
| Installed HONOR Stable | [Owner-local Operator LIVE receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6408493088): v1.6.0/0065 health and Month/Returns UI PASS, DB unchanged: 78 tables, 10 originals, 9 CLOSED. **Test stopped.** #970/#971/#972 changes are NOT installed. |
| UAT / protected financial actions | [Owner Month/Returns UI GO](https://github.com/LTstripes/hermes-finance/issues/963#issuecomment-6401873080) for previous UI is distinct from **new #970 actual↔forecast financial Owner UAT NOT RUN**. No real 0066 rollout, settlement acceptance, broker import, Close/Reopen or provider call is authorized by source merge. Local synthetic UI/Back/Reload coverage is not native Owner financial UAT. |

Existing source-only custody proof and its payout narrative relink on Stable
remain the Owner-approved historical source facts: two observations of
**one** economic payment and retained immutable proof/nonces, not two new
accepted financial payouts. New #970 code does not retroactively promote
those source-only observations to financial truth.

<a id="s2"></a>
## 2. What the user can do and what is already calculated

**Installed v1.6.0 (source-only economics retained):** original files have source-only journal entries,
recognized positions/dated trades/Money/payouts, native account scope and
strict separate source-month DRAFT Preview/Apply route. Stored source observations
do **not** replace old manually entered financial rows automatically. The
source-proof-backed ordinary Month/Monthly Returns read-only preview shows
**two provisional monthly results on one native account (June/July 2026)**,
and **five monthly results on the other account (May–September 2026)**.
August's principal/custody event remains unaccepted; full calendar 2024–26
investment returns do not appear from long originals alone. Source-only
Modified Dietz is not accepted portfolio TWRR/XIRR or financial Close.

**Month + Returns screens already included in installed Stable v1.6.0:**
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
broker inquiry ([#814](https://github.com/LTstripes/hermes-finance/issues/814),
Owner says SENT/WAITING); June REPO/custody question
([#888](https://github.com/LTstripes/hermes-finance/issues/888), UNSENT).
Stock returns can be supported on exact scoped periods; full bond economic
P&L/MD requires documented valuation clean/dirty/NKD basis and movements.
There remain reported **88 unresolved payout source observations** and **16
trade-only instrument types** requiring scoped evidence. Do not mistake
observations across overlapping statements for distinct payments.

<a id="s3"></a>
## 3. Next actions, in priority order

1. **Finish code integration check:** confirm [exact main push
   CI40457523342](https://github.com/LTstripes/hermes-finance/actions/runs/40457523342)
   on `3d7fac67…` reaches terminal **SUCCESS and ci-ok SUCCESS**. The
   independent #970 source/migration GO already exists; no duplicate audit
   of the unchanged reviewed candidate or full-suite rerun is needed.
2. **Protected 0066 operations remain separate:** prepare **one narrowly scoped
   Owner decision** for an isolated, backup-first **disposable/Test 0065→0066
   migration rehearsal** against verified existing DB selection and explicit
   recovery; first confirm physical DB identity, no pre-existing schema drift,
   old receipt/trigger/index/history preservation and no surprise write path.
   Do not run 0066 on the currently serving Stable or import Owner source
   under this documentation/code integration. Published Stable v1.6.0 stays
   on 0065 until a new reviewed release and separately authorized rollout.
3. **Owner financial user-path UAT after rehearsal:** next DRAFT month →
   scoped MyBroker original(s) and genuine exceptions → established instrument/
   position and provider-quantity basis → accepted actual/forecast link →
   payout calendar (paid/future/UNKNOWN) → read-only supported Returns →
   explicit Close/GET/Back/Reload. Distinguish the merged **capability**
   from current source-only Save and the user's unverified 2024–2026 history;
   do not close #711 or declare full financial import complete before actual
   UAT and independently supported evidence.
4. **Target missing history evidence**, reusing [#769](https://github.com/LTstripes/hermes-finance/issues/769),
   [#891](https://github.com/LTstripes/hermes-finance/issues/891),
   [#709](https://github.com/LTstripes/hermes-finance/issues/709)
   and [#940](https://github.com/LTstripes/hermes-finance/issues/940):
   four source-vs-manual quantity conflicts, three date ambiguities,
   missing 2024/EOD operands, August principal/cash proof, June REPO and
   September bond NKD/settlement. No wholesale backfill, reimport, silent
   corrections to CLOSED or UNKNOWN→zero.
5. **Later UI/maintenance only when valuable:** separate editor stays KEEP
   after #940 audit, exact-ISIN display labels (#971) and old route query/hash
   compatibility (#972) are already code-merged. Legacy Alfa PRO/import
   entrypoints need confirmed consumer-route replacement before retirement.
   [#856 AI export](https://github.com/LTstripes/hermes-finance/issues/856)
   remains deferred pending supported economic results.

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
