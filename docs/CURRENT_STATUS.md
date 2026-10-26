# Current state, limitations and next actions

Updated **2026-10-26**. This is the sole changing project status book. Current source
behavior is specified by [P](MASTER_SPEC.md), numeric/data authority by
[C](ARCHITECTURE_AND_CONTRACTS.md), integration by [D](DEVELOPMENT.md), and
runtime/recovery by [O](OWNER_RUNTIME_OPERATIONS.md). Historical PR comments
are evidence for their dated stage, not a newer installation status.

## Current checkpoint

**Current canonical source:** `main@b03681b9bec1474a6bb6c8cf37ca30093df7447f`.
[#969 eight synthetic multi-account / overlap regressions](https://github.com/LTstripes/hermes-finance/pull/969)
was independently reviewed, guarded-merged test-only and verified by
[exact main CI40272845779](https://github.com/LTstripes/hermes-finance/actions/runs/40272845779):
**COMPLETED SUCCESS, 28 successful + 3 expected skipped, ci-ok SUCCESS**.
The new tests do not change the published application or finance semantics;
[#960](https://github.com/LTstripes/hermes-finance/issues/960) is complete.

**Published AND running Stable:** [v1.6.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.6.0)
at immutable release SHA `d53a67409be4283f08f622218743ff5ef8e66ff0`,
schema `0065_source_return_proofs`. [PR #968](https://github.com/LTstripes/hermes-finance/pull/968)
and [exact release main CI40227746782](https://github.com/LTstripes/hermes-finance/actions/runs/40227746782)
passed; [guarded #124 publication](https://github.com/LTstripes/hermes-finance/issues/124#issuecomment-6408380101)
and annotated tag/Release were independently read back.
[HONOR-local Operator's final rollout receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6408493088)
reports one backup-first OPS02, separate authorized Start, correct loopback process /
physical DB binding, `health=ok/version=1.6.0`, Month/Returns/Back/Reload smoke
**PASS**. All **78 tables, 10 source originals, 9 CLOSED**, source-proof history
and financial rows/physical DB hash were preserved. These installed proofs
are **Operator-attributed local readbacks**, not cloud access to the Owner DB.
**Test is stopped; Stable is running.** Do not redeploy v1.6.0 to re-prove this.

**Next functional work:** [#711/#889](https://github.com/LTstripes/hermes-finance/issues/711)
actual payout↔forecast, strict broker dividend Money and scoped Close. An
independent contract [§2.1/§3 correction](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6409530686)
now distinguishes atomic LIVE supersession from `R1→R2(retire)→R3(reaffirm)`
without rewriting R1. Owner-approved **code-only/synthetic 0066** Worker
reported **STOP** with 18 uncommitted local files, 9 synthetic migration + 4
Money-v1 serialization tests PASS (Worker-attributed), no PR/candidate CI and
no protected operations. **Resume that same protected checkout** after the
narrow correction; no financial implementation acceptance, owner-data/schema
migration or real Apply/Close/provider GO is implied by the spec.

<a id="s1"></a>
## 1. Code, release, installed runtime and UAT are distinct

| Layer | Current verified status |
| --- | --- |
| Canonical GitHub main | `b03681b9…`, #969 test-only guarded-merged; [exact main CI40272845779](https://github.com/LTstripes/hermes-finance/actions/runs/40272845779) SUCCESS. This source HEAD is later than the *published* release commit solely because of eight new synthetic regressions. |
| Published v1.6.0 | [Immutable GitHub Release](https://github.com/LTstripes/hermes-finance/releases/tag/v1.6.0), annotated tag peels to `d53a6740…`; [release CI40270100941](https://github.com/LTstripes/hermes-finance/actions/runs/40270100941) SUCCESS. The published tag does not follow newer main. |
| HONOR Stable | [Operator v1.6.0 LIVE receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6408493088): published SHA installed and started, schema 0065, same physical DB, 78 tables / 10 originals / 9 CLOSED and source proofs/financial history preserved. Test stopped. |
| UI Test/UAT | [Owner Month/Returns GO](https://github.com/LTstripes/hermes-finance/issues/963#issuecomment-6401873080); operator's actual post-Start Month/Returns and Back/Reload smoke PASS. Original native Windows DPI/zoom matrix remains NOT TESTED; nine scenarios were CSS/viewport emulation only. Real finance Apply/Close, real personal Save, live T-Invest remain NOT TESTED. |
| Financial #711 Worker | Contract amendment [R1/R2/R3](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6409530686) published; local uncommitted/synthetic Worker's STOP awaits same-checkout remediation and full candidate CI/independent review. No actual 0066 migration, financial write or provider action is authorized. |

Existing source-only custody proof and its payout narrative relink on Stable
remain exactly those prior Owner-approved operations: one source-only proof,
two linked source observations of **one** economic payment and their permanent
retirement nonce history, not two financial receipts. New #711 work does
not retroactively upgrade the authority of those source facts.

<a id="s2"></a>
## 2. What the user can do and what is already calculated

**Installed v1.6.0 (underlying source/read semantics retained):** original files have source-only journal entries,
recognized positions/dated trades/Money/payouts, native account scope and
strict separate source-month DRAFT Preview/Apply route. Stored source observations
do **not** replace old manually entered financial rows automatically. The
source-proof-backed ordinary Month/Monthly Returns read-only preview shows
**two provisional monthly results on one native account (June/July 2026)**,
and **five monthly results on the other account (May–September 2026)**.
August's principal/custody event remains unaccepted; full calendar 2024–26
investment returns do not appear from long originals alone. Source-only
Modified Dietz is not accepted portfolio TWRR/XIRR or financial Close.

**Month + Returns screens included in installed v1.6.0:**
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

1. **No repeat deployment:** Stable v1.6.0 is published and locally running on
   the exact immutable tagged code/0065. Preserve its verified backups, physical
   DB binding, source proof history, 10 originals and 9 CLOSED. Neither the
   latest test-only `main` nor any #711 WIP is an installed Stable hotpatch.
2. **Synthetic regression coverage complete:** [#960](https://github.com/LTstripes/hermes-finance/issues/960)
   closed after [PR #969](https://github.com/LTstripes/hermes-finance/pull/969)
   and [exact main CI40272845779](https://github.com/LTstripes/hermes-finance/actions/runs/40272845779)
   SUCCESS. No full historic XML reimport or second financial ledger is needed.
3. **#711 actual payout contract next:** apply the precise
   [Integrator R1/R2/R3 amendment](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6409530686)
   in the **same existing Worker's protected local checkout**, preserving the
   18 uncommitted files and existing 9 migration + 4 v1 serialization checks
   (Worker-attributed). First prove both LIVE atomic succession and
   already-retired reaffirmation without a `retired_request_id` rewrite.
   Finish bounded migration/actual-link/dividend/scoped-Close synthetic tests,
   API→desktop Back/Reload, independent financial/source/migration review,
   exact candidate CI and Integrator acceptance before guarded merge.
   **No PR or code integration exists yet for this implementation.**
   Real Owner 0066/financial Apply/Close/provider/Stable operations remain
   separately gated; v1.6.0/0065 remains untouched.
4. **History gaps, targeted only:** reuse #769/#891/#709/#940 existing
   read-only 2024–2026 coverage; investigate the four quantity disagreements,
   three date ambiguities, exact missing EOD/opening observations, August
   principal/cash ownership, June REPO and September NKD/settlement broker
   evidence. Never fabricate a month from a long original, replace CLOSED/manual
   rows wholesale, or convert missing facts to zero.
5. **Later product cleanup:** after #711 end-to-end finance acceptance, audit
   actual consumers of obsolete Alfa PRO terminal and legacy import screens.
   Retire only proven redundant entry routes, retaining history/schema/readers
   needed by current workflows. [#856 AI export](https://github.com/LTstripes/hermes-finance/issues/856)
   stays deferred until accepted monetary results exist.

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
