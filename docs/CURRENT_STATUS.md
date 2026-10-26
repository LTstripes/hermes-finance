# Current state, limitations and next actions

Updated **2026-10-26**. This is the sole changing project status book. Current source
behavior is specified by [P](MASTER_SPEC.md), numeric/data authority by
[C](ARCHITECTURE_AND_CONTRACTS.md), integration by [D](DEVELOPMENT.md), and
runtime/recovery by [O](OWNER_RUNTIME_OPERATIONS.md). Historical PR comments
are evidence for their dated stage, not a newer installation status.

## Current checkpoint

**Worker candidate, not integrated:** #711 source-owned payout settlement,
strict dividend Money v2 and scoped Close on branch `worker/711-financial-0066`,
based on `b03681b9bec1474a6bb6c8cf37ca30093df7447f` (test-only #969).
During remediation, live main advanced to `51e204015b6ccbe6c62d92fc1ee3bf0124bcc72b`
(#971 exact-ISIN display names and #972 Month redirect query/hash preservation);
those changes were inspected without integrating them into this Worker branch.
The retirement amendment is implemented for separate R2 and atomic LIVE replacement;
the candidate adds `0066_actual_payout_links`. Its draft PR must carry exact-HEAD
CI and synthetic migration/API/UI evidence for independent financial/migration
review. No acceptance, release, installation, real migration or runtime operation
is implied. Integration remains with ChatGPT Integrator.
[Integrator HOLD on #970](https://github.com/LTstripes/hermes-finance/pull/970#issuecomment-6423924559)
identified Reopen/reclose paid resurrection, an APP-only Month warning and an
incomplete historical guard preflight. This same-PR remediation addresses those
three findings; independent financial/source/migration re-review of the new
exact HEAD remains required. Prior candidate CI does not clear the HOLD.

**Accepted pre-release Month/Returns UI baseline:** `f07b20ddc8bdad074fb0993792cf3f06e5cc30f8`.
New [#964 Returns](https://github.com/LTstripes/hermes-finance/pull/964),
[#965 Returns source explanations](https://github.com/LTstripes/hermes-finance/pull/965)
and [#962 Month tiles and guarded Close](https://github.com/LTstripes/hermes-finance/pull/962)
are guarded-merged in that order, with exact candidate CI/UI GO and a final
reviewed-tree-equal merge at `3ca4780f017e5949aad61e5c888f8bb27af784f6`.
#966 reconciled documentation afterward. Exact baseline
[post-main CI40216203428](https://github.com/LTstripes/hermes-finance/actions/runs/40216203428):
**COMPLETED SUCCESS (28 successful jobs, 3 expected skips, terminal ci-ok SUCCESS)**.
Code integration is not an installed release.

**v1.6.0 release-only candidate:** [PR #968](https://github.com/LTstripes/hermes-finance/pull/968)
under [#967](https://github.com/LTstripes/hermes-finance/issues/967) packages only
version/lock/health test expectations, CHANGELOG and
[canonical release notes](release-notes-1.6.0.md) from that accepted baseline.
The PR's exact reviewed HEAD, candidate CI, guarded integration and canonical
post-main push CI are verified through its latest GitHub receipts; none is inferred
from a prepared document. Worker self-acceptance is not sufficient. v1.6.0 is
**not yet published or installed**. A separate specific Owner release GO, guarded
#124 publication, tagged-release readback and another Owner-approved Stable
transition remain distinct gates. No Stable/Test/Owner DB operation is authorized.

**Published and installed Stable:** [v1.5.0](https://github.com/LTstripes/hermes-finance/releases/tag/v1.5.0)
at `f963374ac0b6b6b5c156f013785c78b900004b7c`, schema
`0065_source_return_proofs`. Release tag/peeled commit and GitHub Release were
independently checked. Owner-local Operator [#940 rollout receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6396538180)
reports stock-installed loopback health/UI/Reload/restart PASS, original physical
DB binding preserved, **76 existing tables plus 2 new**, ten saved source-only
originals across two native broker accounts and nine CLOSED months unchanged.
This is Operator-attributed local proof; the cloud Integrator has not independently
opened the physical Windows database or UI. **The new Month and Returns screens are
not yet installed in Stable.**

<a id="s1"></a>
## 1. Code, release, installed runtime and UAT are distinct

| Layer | Current verified status |
| --- | --- |
| GitHub source | Accepted pre-release UI baseline `f07b20dd...`, #962/#964/#965 merged, #966 docs reconciled; #968 tracks exact release merge SHA and CI. #962 [exact PR CI40213852780](https://github.com/LTstripes/hermes-finance/actions/runs/40213852780) 30/30 SUCCESS, [UI40213852100](https://github.com/LTstripes/hermes-finance/actions/runs/40213852100) SUCCESS. #965 [CI40210791959](https://github.com/LTstripes/hermes-finance/actions/runs/40210791959) SUCCESS; #964 [CI40198729519](https://github.com/LTstripes/hermes-finance/actions/runs/40198729519) SUCCESS. Exact baseline push CI is linked above; #967 release-only candidate is separate. |
| Published | v1.5.0, code `f963374a...`, schema 0065. v1.6.0 preparation is authorized; publication/tag/#124 trigger is not. |
| HONOR Stable | Owner Operator reports v1.5.0/0065 installed, old business facts and source journals preserved. The code-only latest main is not a hotpatch to Stable. |
| Test and actual new UI UAT | [Owner UI UAT GO](https://github.com/LTstripes/hermes-finance/issues/963#issuecomment-6401873080) for Month/Returns on Test `f07b20dd...`, with accepted native desktop evidence gap. [Operator technical PARTIAL](https://github.com/LTstripes/hermes-finance/issues/711#issuecomment-6401652215): tested routes PASS, nine size/zoom scenarios CSS/viewport emulation only; native Windows browser DPI/zoom NOT TESTED. Real financial Apply/Close/Reopen, real manual Save and live T-Invest remain NOT TESTED and unapproved here. |
| Protected actions | Financial Apply/Close/Reopen, real October statement import, Test/Stable rollout and provider calls require the applicable explicit Owner scope/approval; none is granted by a GitHub merge. |

The bounded original-bound custody-month source proof is persisted on installed
Stable under separate Owner approvals: one source-only proof, a scoped payout
narrative relink of **two source observations of one economic event**. This did
not create two financial payments or canonical financial PositionSnapshots.
Proof remains revision/manifest/physical-DB-currentness checked, not raw XML
storage. Owner's protected financial data, ten journals and nine CLOSED are
unchanged by today's code-only #964/#965/#962 integration.

<a id="s2"></a>
## 2. What the user can do and what is already calculated

**Existing installed v1.5.0:** original files have source-only journal entries,
recognized positions/dated trades/Money/payouts, native account scope and
strict separate source-month DRAFT Preview/Apply route. Stored source observations
do **not** replace old manually entered financial rows automatically. The
source-proof-backed ordinary Month/Monthly Returns read-only preview shows
**two provisional monthly results on one native account (June/July 2026)**,
and **five monthly results on the other account (May–September 2026)**.
August's principal/custody event remains unaccepted; full calendar 2024–26
investment returns do not appear from long originals alone. Source-only
Modified Dietz is not accepted portfolio TWRR/XIRR or financial Close.

**Merged code with Owner UI UAT GO, awaiting release/Stable installation:**
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

1. **Baseline exact push CI and Owner UI UAT complete:** CI40216203428 SUCCESS
   on `f07b20dd...`; Owner Month/Returns GO accepts the native DPI/zoom gap.
   Operator technical PARTIAL and real financial/live-provider NOT TESTED limits
   remain explicit. No repeat native-browser capture is required for this
   release-preparation decision; no real financial operation is authorized.
2. **#968 v1.6.0 release-only candidate:** before publication, verify the final
   independent release/security/product review, exact candidate PR CI,
   guarded integration and exact canonical post-main push CI in #968. No additional
   #711/#889 functionality or existing Draft PR enters this release branch/cut;
   separate feature work must not merge to main before candidate publication.
3. **Separate Owner publication and rollout decisions:** specific release GO
   after checks → guarded #124 request → annotated tag/peeled SHA/Release readback.
   Then a separately Owner-approved **backup-first published-SHA Stable update**
   with retained 0065 schema/data, rehearsal as applicable, OPS02
   Prepare/Validate and separate Start; verify source journals, nine CLOSED,
   month/returns UI, actual health and readback. Do not touch published v1.5.0
   tag or copy Test DB into Stable.
4. **Finance work after usability:** address only the 4 quantity disagreements
   and 3 date ambiguities on isolated read-only history first; gather specific
   missing monthly EOD/early 2024 opening valuations, August principal proof,
   REPO/NKD/settlement semantics and verified payout identities. Reuse #769,
   #891, #709, #940. Reconstruct strictly eligible old account periods and
   supported instrument economics, then XIRR/TWRR where complete. Never fabricate
   a 2024 calendar month from one outer-span XML.
5. **Product follow-ups:** the accepted source-native quantity date drives only
   an ephemeral T-Invest preview; source-only Save does not persist canonical
   `PositionSnapshot`, accepted actual-vs-future payout identity or financial
   ledger. Complete the **statement → financial position → forecast quantity →
   actual/paid-state → Close** link under #711/#889 with existing writer/contracts
   and separate financial UAT. Add only unique numerical account/overlap
   regressions from [#960](https://github.com/LTstripes/hermes-finance/issues/960);
   Kimi synthetic Fraction/Decimal audit found no new core formula defect.
   Retire redundant Alfa PRO terminal/legacy upload routes only after actual
   consumer/route audit and accepted replacement; preserve their historic data
   and migration dependencies. [#856 AI export](https://github.com/LTstripes/hermes-finance/issues/856)
   stays deferred until supported accepted metrics are ready.

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
the corresponding PR receipts and published [release notes](release-notes-1.5.0.md).
