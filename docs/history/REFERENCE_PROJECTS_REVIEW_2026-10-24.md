# Reference projects review — 2026-10-24

Dated research record. It is not an active instruction, backlog or task queue.

**Research baseline — 2026-10-24.** This section is the first recorded Finance
reference comparison, not a claim about changes since an unknown earlier review.
Own-code baseline: [main `b027bcd90c56c500d271a9ee963485bdfa67ea79`](https://github.com/LTstripes/hermes-finance/commit/b027bcd90c56c500d271a9ee963485bdfa67ea79).
AGENTS, the relevant P/C/D/S sections, the complete open issue/PR collection and
applicable latest comments were read before mapping recommendations to source/tests.
The scope is one local/home-server user: understandable results, fewer repeated
manual actions and little maintenance. This is research, not feature acceptance,
a new task queue or a report of local/Owner UAT.

**Placement and reuse boundary.** This dated research moved here from
[D3](../DEVELOPMENT.md#reference-projects-and-reuse), which keeps the current reuse
rule; P and C retain all product and financial
contracts, and S remains the changing status book. No sixth book, dependency,
copied code, financial formula change or new authority is introduced. For every
reference here the present disposition is **concepts, interface observations and
independently authored synthetic cases only**. Even MIT code would need a later
exact-file/SHA/license and notice review before copying. Package/root licenses do
not automatically cover documentation, bundled assets or dependencies. Public
issue reports and project marketing are not proof of a Hermes defect or of correct
financial calculation.

#### Observed versions and licenses

Commit dates are UTC; release dates are publication dates unless noted. Release
commits were resolved independently from tags; branch HEAD is not assumed released
or installed. These are observations, not dependency pins.

| Project | Observed head / commit date | Latest release checked / exact release commit | License evidence at observed head; proposed boundary |
|---|---|---|---|
| [Portfolio Performance](https://github.com/portfolio-performance/portfolio) | [`2a0ef52a93882c0845596b2c6b834e54f592b7ec`](https://github.com/portfolio-performance/portfolio/commit/2a0ef52a93882c0845596b2c6b834e54f592b7ec), 2026-10-24 | [0.89.0](https://github.com/portfolio-performance/portfolio/releases/tag/0.89.0), 2026-10-11; `20d7fb690ad532c5f4a8813f6c4f365745e37c7d` | [EPL-1.0](https://github.com/portfolio-performance/portfolio/blob/2a0ef52a93882c0845596b2c6b834e54f592b7ec/LICENSE). Concepts and synthetic cases only. No copying Java code; online manual has its separate CC BY-NC-SA terms. |
| [Wealthfolio](https://github.com/wealthfolio/wealthfolio) | [`8ef1cb7d84fdcfc5ee4cf62e64ceb9b548166598`](https://github.com/wealthfolio/wealthfolio/commit/8ef1cb7d84fdcfc5ee4cf62e64ceb9b548166598), 2026-10-24 | [v3.11.0](https://github.com/wealthfolio/wealthfolio/releases/tag/v3.11.0), 2026-10-23; `d1fda0b65f69d8557b1ef80e555c799215ad28b3` | [AGPL-3.0](https://github.com/wealthfolio/wealthfolio/blob/8ef1cb7d84fdcfc5ee4cf62e64ceb9b548166598/LICENSE). Reference only. Old `afadil/wealthfolio` redirects to the current organization; do not record the old owner as canonical. |
| [Ghostfolio](https://github.com/ghostfolio/ghostfolio) | [`4f17f0ecd4a357b860f835ab11c4d0034c20d2d0`](https://github.com/ghostfolio/ghostfolio/commit/4f17f0ecd4a357b860f835ab11c4d0034c20d2d0), 2026-10-24 | [3.92.0](https://github.com/ghostfolio/ghostfolio/releases/tag/3.92.0), 2026-10-24; `7429176b44d6bde31baf3b02acecef1a9cbaaf06` | [AGPL-3.0](https://github.com/ghostfolio/ghostfolio/blob/4f17f0ecd4a357b860f835ab11c4d0034c20d2d0/LICENSE). Reference only, especially scope/identity failure classes; no service-stack adoption. |
| [Beancount](https://github.com/beancount/beancount) | [`9747213802acb733ce53acc6e963f5961f47d6cd`](https://github.com/beancount/beancount/commit/9747213802acb733ce53acc6e963f5961f47d6cd), 2026-08-23 | [3.2.3, PyPI](https://pypi.org/project/beancount/3.2.3/), 2026-05-05; [`eeda2aa2a3204ffb980dab11220b2abde5e80b38`](https://github.com/beancount/beancount/tree/eeda2aa2a3204ffb980dab11220b2abde5e80b38). GitHub latest-release endpoint has no release object; tag/PyPI checked instead. | [COPYING](https://github.com/beancount/beancount/blob/9747213802acb733ce53acc6e963f5961f47d6cd/COPYING) GPL-2.0; [pyproject](https://github.com/beancount/beancount/blob/9747213802acb733ce53acc6e963f5961f47d6cd/pyproject.toml) explicitly GPL-2.0-only. Reference only; no second ledger or parser adoption. |
| [Fava](https://github.com/beancount/fava) | [`f0161ba300a393006a88d14b3968e5af535ed4a5`](https://github.com/beancount/fava/commit/f0161ba300a393006a88d14b3968e5af535ed4a5), 2026-10-24 | [1.30.16, PyPI](https://pypi.org/project/fava/1.30.16/), 2026-08-18; [`d8d426f9cbf08ace852a4a319adb4b9dda853b69`](https://github.com/beancount/fava/tree/d8d426f9cbf08ace852a4a319adb4b9dda853b69). No GitHub release object; annotated tag/PyPI agree. | [MIT](https://github.com/beancount/fava/blob/f0161ba300a393006a88d14b3968e5af535ed4a5/LICENSE). UX/read-boundary patterns only in this review; a later exact-file review would be needed for any code reuse, and MIT Fava does not relicense Beancount/dependencies. |
| [GnuCash](https://github.com/Gnucash/gnucash) | stable branch [`fec5643cd22cbafc7b16047f35cbe852395da947`](https://github.com/Gnucash/gnucash/commit/fec5643cd22cbafc7b16047f35cbe852395da947), 2026-10-19 | [5.17](https://github.com/Gnucash/gnucash/releases/tag/5.17), 2026-09-27; `0e302675fff4bf6dccf62ba876c7d306b7152d0e` | [LICENSE](https://github.com/Gnucash/gnucash/blob/fec5643cd22cbafc7b16047f35cbe852395da947/LICENSE) describes a mixed compatible set: mostly GPL-2.0-or-later, some GPL-2.0/GPL-3.0-specific files and exceptions. Reference only; inspect individual file if reuse is ever proposed. |
| [investments](https://github.com/KonishchevDmitry/investments) | [`d4e14076f14a838965b99bd7385902b7c5bf3d08`](https://github.com/KonishchevDmitry/investments/commit/d4e14076f14a838965b99bd7385902b7c5bf3d08), 2026-08-11 | [v8.4.0](https://github.com/KonishchevDmitry/investments/releases/tag/v8.4.0), 2026-08-11; same SHA as observed head | [Cargo.toml](https://github.com/KonishchevDmitry/investments/blob/d4e14076f14a838965b99bd7385902b7c5bf3d08/Cargo.toml) declares `GPL-3.0+` (GPL-3.0-or-later). Root tree has no LICENSE/COPYING; do not overstate a complete licensing audit. Reference only; no copying. |

#### Useful lessons and scenario differences

##### 1. Portfolio Performance — returns with inspectable scope

The official [MWR](https://help.portfolio-performance.info/en/concepts/performance/money-weighted/) and [TWR](https://help.portfolio-performance.info/en/concepts/performance/time-weighted/) explanations distinguish portfolio versus security cash-flow boundaries and annual versus period figures. PP's daily valuations and timing assumptions differ from Hermes statement EOD evidence and bounded Modified Dietz/conditional results; do not rename our available result to exact TTWROR by copying a formula.

Release 0.89.0 includes dividend fees in the security fee total and displays an undefined moving-average cost for short trades rather than zero. It also adds optional read/write MCP, which we should not adopt. Open [#5274](https://github.com/portfolio-performance/portfolio/issues/5274) (created 2025-12-31; updated 2026-10-24) reports weekend cash flows disappearing from a return export. Open [#2367](https://github.com/portfolio-performance/portfolio/issues/2367) (2021-08-04; updated 2026-10-24) reports fallback into the wrong account during CSV import. These are reports, not independently reproduced upstream findings.

**Use:** compare read/visible/export scopes and include weekend/boundary flows in a focused regression. **Difference:** do not import PP's quote collection, taxonomy/dashboard customization, global PDF bank catalogue, or write-capable AI.

##### 2. Wealthfolio — compact account activity with reconciliation clues

v3.11.0 introduces per-activity/running or EOD balances (depending on account type) and date-grouped activity lists. It fixes external credits counted as gains, inconsistent historic income FX/month attribution, duplicate assets during trade edits, and precise broker decimal conversion. These are documented shipped fixes; our equivalent contracts must still be checked independently. The release explicitly distinguishes missing comparative income growth from 0%.

Open [#2281](https://github.com/wealthfolio/wealthfolio/issues/2281), 2026-10-24, asks for stable source record IDs/metadata because value-and-comment matching is insufficient for add-on reimports. Open [#2282](https://github.com/wealthfolio/wealthfolio/issues/2282), 2026-10-24, reports that a CSV column named `lineNumber` collapses preview rows, including unresolved mappings. Open [#2268](https://github.com/wealthfolio/wealthfolio/issues/2268), 2026-10-24, reports dropped tax via MCP import. None is proof about Hermes.

**Use:** evidence-preserving exception preview; account-scoped inventory conservation before/after save/reload. **Difference:** Hermes already has source-native original identities and receipts; do not replace them with value hashes or comments. Ignore sync/cloud/add-on ecosystems, AI ingestion and new broker connections.

##### 3. Ghostfolio — particularly useful negative examples for multiple accounts

Release 3.92.0, 2026-10-24, improves import asset matching to include closed positions/excluded accounts (AI path, experimental), and hardens errors from `POST api/v1/import`. Those improvements are not a reason for an LLM importer.

Open [#7728](https://github.com/ghostfolio/ghostfolio/issues/7728), created 2026-08-26 and updated 2026-09-25, specifically reports deduplication across distinct accounts with identical date/type/price/quantity. Open [#7468](https://github.com/ghostfolio/ghostfolio/issues/7468), 2026-07-29, is a request to distinguish price and dividend-inclusive total return; its assertion about current math is not an independently validated defect or financial authority.

**Use:** two-account adversarial import acceptance; preserved source-account identity through closed/excluded views. **Difference:** Hermes is one local Windows user and has explicit source authority/Close; do not take the multiuser/cloud/provider/admin service stack.

##### 4. Beancount — assertions and deterministic evidence, not another ledger

The [official balance-assertion discussion](https://beancount.github.io/docs/balance_assertions_in_beancount/) explains that a single-currency/unit check is not proof of complete inventory, cost basis or complete operations. It is a design discussion dated July 2014, not a 2026 feature announcement. The [inventory documentation](https://beancount.github.io/docs/how_inventories_work/) is a useful account of ambiguity rather than guessing cost lots.

Open [#1056](https://github.com/beancount/beancount/issues/1056), 2026-09-23, reports same-date ordering changing when one file is split into included files. Open [#1043](https://github.com/beancount/beancount/issues/1043), 2026-08-08, reports negative rounding direction inconsistent with its documentation; [#1004](https://github.com/beancount/beancount/issues/1004), 2026-01-13, reports incomplete currency inference using the wrong tolerance.

**Use:** metamorphic tests for equivalent originals split/reordered without losing economically distinct occurrences. **Difference:** keep Hermes explicit Decimal/ROUND_HALF_UP; do not adopt automatic inferred postings, padding, tolerance inference or textual double-entry ledger.

##### 5. Fava — consistent filters and compact drilldown

Fava is a local web UI over Beancount; useful for journal → account → source navigation rather than another financial engine. [CHANGES](https://github.com/beancount/fava/blob/f0161ba300a393006a88d14b3968e5af535ed4a5/CHANGES) states that duplicate detection with v3 importers is not automatic; it requires explicitly configured hooks. Do not assume a mature import UI makes reimport safe.

The observed head is [57 commits beyond stable 1.30.16](https://github.com/beancount/fava/compare/d8d426f9cbf08ace852a4a319adb4b9dda853b69...f0161ba300a393006a88d14b3968e5af535ed4a5). Relevant **unreleased head** work: [real-subaccount filtering](https://github.com/beancount/fava/commit/c15ee2b123c54fe22f2d11f75b354e328a82c844), 2026-09-26; [concurrent query shared-state protection](https://github.com/beancount/fava/commit/fa7be27ffcd4f8b75e07b2af7dcccbe9edd1c298), 2026-10-07; [trusted localhost hosts](https://github.com/beancount/fava/commit/7e3250cf4cc2227aafc74d8e4e6cb61b8eff6fab), 2026-10-22. Open [#1423](https://github.com/beancount/fava/issues/1423) (2022-05-16) was reported against 1.21; the later filtering fix means its open status alone does not prove the issue remains on current head. [#1151](https://github.com/beancount/fava/issues/1151) (2020-08-29; updated 2026-08-22) requests rapid reconciliation toggles; it is a request, not an implemented feature.

**Use:** same selected account/period must drive list, chart, result and export; source drilldown stays small. **Difference:** no editable SQL/Python hook system or Beancount UI embedding.

##### 6. GnuCash — reconciliation is not the same operation as Close

[Reconciliation](https://www.gnucash.org/docs/v5/C/gnucash-manual/acct-reconcile.html) compares statement date/balance with selected transaction evidence and exposes the remaining difference. Release 5.17, 2026-09-27, fixes reconciliation involving transactions after the reconcile date (upstream Bug 799753), quoted CSV parsing (799774), stock-split cost basis handling and date-boundary tests. Bugzilla itself was inaccessible in this research, so fix evidence is the official release note, not a reproduced bug.

The [Close Book documentation](https://www.gnucash.org/docs/v5/C/gnucash-manual/tool-close-book.html) says its Close creates balancing transfers for income/expense accounts and does not freeze history. Hermes Close means immutable reporting month until explicit Reopen: the operations must not be equated.

**Use:** compact read-only opening balance + observed operations + ending balance + unexplained difference at an exact cutoff. **Difference:** never copy GnuCash's optional balancing-entry button, zeroing Close or full general ledger as a shortcut around unresolved evidence.

##### 7. investments — Russian statement-first import with honest limitations

The pinned [README](https://github.com/KonishchevDmitry/investments/blob/d4e14076f14a838965b99bd7385902b7c5bf3d08/README.md) supports Russian brokerage formats and distinguishes analysis reads from position sync writes. Its requirement for complete account history from zero, without overlaps/gaps, is explicit. Its performance model compares the same cash flows to a bank deposit with monthly capitalization; that is not automatically Hermes XIRR/TWRR/Modified Dietz.

v8.4.0 documents non-exchange-traded funds; [tax withholding for the other-broker format](https://github.com/KonishchevDmitry/investments/commit/aca3fbf0b3bbe2d38b6f9e1aa0eb6dd535655216), 2026-08-10, is a release-ancestor change. README still lists bonds as unsupported, linked to [#43](https://github.com/KonishchevDmitry/investments/issues/43) (open, 2021-04-17); [#13](https://github.com/KonishchevDmitry/investments/issues/13) (open, 2020-06-29) reports cross-account transferred securities lacking original purchase basis.

**Use:** explicit supported-format limits and context-rich parser errors. **Difference:** Hermes has material bond/coupon/NKD, overlapping long/monthly originals, partial history and corrections; cannot inherit the donor's completeness assumptions or require an entire lifetime before every bounded calculation. No tax engine, rebalancing instructions, Prometheus or external metrics stack.

#### What Hermes already has; no duplicate feature proposals

At this cut there were **26 open issues and three open PRs** (#927, #829, #744),
read as a complete collection. OPEN umbrellas do not imply missing implementation.
Current source and later accepted receipts take precedence over old issue bodies:

- [#945](https://github.com/LTstripes/hermes-finance/pull/945) / [#891 accepted backend](https://github.com/LTstripes/hermes-finance/issues/891#issuecomment-6371707813)
  already deliver dated source events, payout-link revalidation, quantity/cash
  reconciliation, P&L and period Modified Dietz. Preserve legacy simple percentage,
  complete economic result, known components and conditional statement estimates
  as different meanings; adding those again is not a proposal.
- [#946](https://github.com/LTstripes/hermes-finance/pull/946),
  [#949](https://github.com/LTstripes/hermes-finance/pull/949),
  [#950](https://github.com/LTstripes/hermes-finance/pull/950) and
  [#951](https://github.com/LTstripes/hermes-finance/pull/951) already provide the
  saved-source payout preview, useful bond detail, shared multi-file Month upload,
  stocks/instruments and explicit actual/future separation. [#953](https://github.com/LTstripes/hermes-finance/pull/953)/
  [#954](https://github.com/LTstripes/hermes-finance/pull/954) implement empty-manual
  Close policy and GET-only recovery. Do not restart these features from old #711/#891 text.
- [#769](https://github.com/LTstripes/hermes-finance/issues/769) owns historical source
  work and targeted missing evidence; [#889](https://github.com/LTstripes/hermes-finance/issues/889)
  owns the partial-source versus economic-acceptance boundary. Its
  [accepted rebuild option](https://github.com/LTstripes/hermes-finance/issues/889#issuecomment-6254184201)
  already permits rebuilding a new isolated scratch from retained originals after
  a parser change. No mandatory in-place reparse/versioning platform is proposed.
- [#940's latest October 24 receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6387781110)
  distinguishes an operational Preview's omitted expected trigger effect from a
  product defect. It retains the same assigned Operator. This review neither
  restarts that operation nor turns the existing correction trigger into a bug.
  Dated release/installation prose elsewhere is not fresh runtime evidence; this
  reference section does not become a second status book.

Own paths below are in the [pinned baseline tree](https://github.com/LTstripes/hermes-finance/tree/b027bcd90c56c500d271a9ee963485bdfa67ea79).
Backend `services/` and `domain/` module paths below are relative to
`backend/src/hermes_finance/`; backend test basenames refer to `backend/tests/`.
Frontend component basenames refer to `frontend/src/ui-v2/`, except
`SourceIntakeUpload.tsx` and `SourceIntakeJournal.tsx`, which are in
`frontend/src/components/month-close/`. A missing UI presentation found by static inspection is distinct from an observed
user failure. Upstream behavior has not been independently reproduced here.

#### Prioritized discussion dispositions — at most five

Complexity and risk refer to a later bounded task. Existing issue references
identify ownership; they do not create another task for the same feature.

| Disposition | Proposal / benefit | Current-code mapping and existing work | Complexity / material risk | Minimal later check |
| --- | --- | --- | --- | --- |
| **Take now as an acceptance extension** | One adversarial batch combining identical cross-account native IDs/amounts with source-row collisions, reordered files and replay; protects against silent missing history | `services/source_intake.py:save_intake`, `source_instrument_events.py:read_events`, `SourceIntakeUpload.tsx`; extend the existing #769/#891 corpus, not the importer. Existing concurrent batch, overlap multiplicity and account-isolation tests are retained. | Small–medium; high source identity/money risk if dedup is weakened | Two synthetic account formats, identical trades and same-day repeated payouts, all available Previews before Saves, both Save orders and concurrent Save, GET/reload/replay. Assert exact per-account native occurrences and all exception rows. A materially corrected source must be an explicit conflict/correction, never a silently overwritten original. |
| **Take now as a narrowly different regression** | Calendar/source representation invariance: preserve weekend flows and trade/settlement cutoffs across long versus adjacent originals | `source_monthly_returns.py`, `source_instrument_events.py`, `domain/monthly_return_chain.py`; reuse #769 tests and #891 date authority. PP/Beancount/GnuCash reports are analogies, not proved Hermes bugs. | Small–medium; high financial boundary risk | Compare the same evidenced outer interval and native event set in long/adjacent/overlap input orders; weekend flow and last-day trade with next-month settlement. Preserve `(start, end]`, multiplicity and date roles. Missing intermediate valuations must still leave monthly rates NULL; no invented order or market price. |
| **Later; one optional read-only explanation** | Expose existing account reconciliation as a short expandable result: account growth, known instrument result, account-only effects and unexplained residual | `source_instrument_events.py:reconcile_account` already produces `AccountReconciliation`; `frontend/src/api/sourceReturns.ts` carries it. Inspected Month/monthly-return UI does not render that reconciliation. A small presentation extension belongs with #891/#711, not a new balance ledger. | Small–medium; medium/high interpretation risk | Fully covered residual 0; known nonzero residual remains `partial` with `complete=false`; missing bond basis; filtered ISIN. NULL must stay unavailable and a known partial subtotal must not be labelled fully reconciled. No allocation of residual, correction posting or Close action. |
| **Simplify within existing #711** | Replace primary technical Save/Apply jargon with a short factual explanation and move detailed diagnostics into existing disclosures; fewer confusing choices | `components/month-close/SourceIntakeUpload.tsx` currently exposes `Source Save != financial Apply` wording; `SourceIntakeJournal.tsx`, `UiV2ClosePage.tsx` and `SourceInstrumentDetail.tsx` already own review/details. This narrows the existing simple-month direction, not a new redesign. | Small; medium risk of hiding uncertainty | Known/unknown original; ACK then GET failure; lost ACK; partial sibling failure; account switch and Back/Reload. State that the original is saved while financial acceptance/Close is separate. Keep an actionable next step and exact reason accessible. |

The code map above is inspected source, not proof these hypothetical failures
exist. In particular, existing `test_source_instrument_events.py` already checks
same-ISIN account separation, missing overlap occurrences, settled cash ownership,
fee/tax/NKD attribution, reconciliation and sold-out missing rows.
`test_statement_import_source_intake.py` already has `_history_batch` concurrency,
long/monthly/replay preservation and partial-file failure. Its four-account fixture
uses different trade IDs; the account event test uses different dividend amounts
and no trades. The proposed first scenario deliberately combines fully identical
native trades across accounts with file/row collisions, rather than repeating
those simpler cases. The second compares only truly equivalent evidenced intervals.

#### Regression catalogue and reuse limits

Retain current regression protection; add a case only when an affected change and
an inspected coverage gap make it useful. No regression was executed in this
docs-only review and no new passing-test claim is made.

- **Identity and correction:** original SHA/filename/native account/row occurrence
  and accepted revisions remain separate identities. Same amount/date is not a
  dedup key; repeated identical legitimate events survive. The existing
  `mybroker_corrections.py:install_sql_guards` invalidates dependent confirmations
  when catalogue/mapping facts change. A Preview of a later operation must account
  for the supported trigger effects, not weaken or suppress them.
- **Missing/zero/precision:** preserve absent tax/cost/valuation versus explicit
  zero, signed sub-kopeck correction evidence and canonical Decimal/ROUND_HALF_UP.
  Beancount rounding reports and Wealthfolio missing comparisons are negative
  examples only; our contract wins. Do not add a second generic tolerance engine.
- **Scope and concurrency:** account/ISIN/interval must bind list/detail/result/source
  through delayed responses and rereads. Fava's filtering/shared-state fixes suggest
  a variant only if current #951 stale-selection tests do not already cover it.
  An invalid explicit instrument must not fall back to another instrument.
- **Reconciliation and Close:** numerical equality of a subset is not whole-source
  completeness or approval to Close. Source-only Save is not financial Apply;
  known residuals are not automatically distributed; CLOSED stays immutable until
  explicit Reopen. GnuCash's Close Book is deliberately not transplanted.

**Do not take:** another ledger, importer or month-close engine; automatic balancing
entries, guessed NKD/taxes/denomination, quote-based invented history, a lifetime-history
requirement for every bounded calculation, LLM financial writes, arbitrary SQL/Python
hooks, cloud/device-sync obligations, multiuser/admin platform, new broker fleet,
model benchmarking or telemetry. Portfolio Performance's daily-price TTWROR,
investments' bank-deposit comparison and our statement-based Modified Dietz are
not interchangeable labels.

**What may be reduced, not blindly deleted:** repeated technical labels and primary
links competing with the Month path. Existing diagnostics, correction/history and
legacy compatibility routes require their own reachability/user-path evidence
before retirement. Neither upstream minimalism nor this no-runtime source review
proves a local route or unique test safe to delete. [#389](https://github.com/LTstripes/hermes-finance/issues/389)
report composition remains deferred; no new dashboard builder is warranted here.
