# Hermes Finance 1.4.0 — DRAFT

> **Status:** DRAFT, unpublished candidate preparation. Owner-real numerical UAT PENDING.
> No tag, GitHub Release, publication request, Stable update or financial acceptance exists
> for 1.4.0. This file is not a release announcement, UAT acceptance or financial result.

The draft uses `1.4.0`, the next minor after published `1.3.0`; no current documentation
assigns a different next number. It was prepared 2026-10-21 from main
`f9969c426d497e53600bd24f6c1ac4fa6896975c`. The eventual release commit is not selected, and
the application version remains `1.3.0` in
`backend/pyproject.toml` and `hermes_finance.__version__`. Publication requires the separate
version bump, Owner-real UAT, exact-main CI and guarded release route; see
[publication and update](OWNER_RUNTIME_OPERATIONS.md#o3) and the
[Test-run checklist](releases/1.4.0-test-run.md). The DRAFT status must be replaced before a
release-control request; the release-note lifecycle is defined in
[O3](OWNER_RUNTIME_OPERATIONS.md#o3-release_automation-7-release-note-lifecycle).

## What this draft covers

This candidate is the provisional monthly source-return slice merged after v1.3.0:

| Change | Merged evidence | User-facing result |
|---|---|---|
| Monthly return chain (#911, issue #910) | `7ab9566c` | Contributions, withdrawals and growth are separated; approximate Modified Dietz monthly/chained returns and XIRR are available to the source-return services. |
| Source monthly returns API and migration (#913, issue #912) | `4efbd433` | Read-only `GET /api/source-returns/monthly` over saved source intakes, persisted provisional money classification, flags and contiguous segments. |
| Per-instrument source returns (#915, issue #914) | `a9a239d8` | Read-only `GET /api/source-returns/instruments` with monthly/all-time price, coupon, dividend, NKD-aware estimates and explicit gaps. |
| v2 «Доходность по месяцам» page (#917) | `e31848d0` | Multi-file statement upload plus monthly and per-instrument tables over the read-only source returns. |
| Docs, classifier and CI (#916, #918, #919, #920) | `5b3888b5`, `d931f5b6`, `889eb60a`, `f9969c42` | Status/changelog updates, `docs/archive/**` prose classification, clearer Playwright project errors, CI lane speed-up and docs index tidy. |

## Monthly source return chain

- The domain kernel in `domain/monthly_return_chain.py` treats each adjacent native EOD
  boundary pair as one interval. External flows are counted in `(opening_date, closing_date]`;
  a closing-day flow has zero Modified Dietz weight.
- Contributions and withdrawals are separate from growth:
  `growth = closing - opening - contributions + withdrawals`. Growth can be negative, zero is
  a real observed zero only when both endpoints and flows are known, and unavailable values
  stay `null`.
- The monthly rate is an approximate Modified Dietz fraction. The chained return is the product
  of the monthly estimates and is displayed as approximate, not exact TWRR. Period XIRR uses
  the outer endpoints and one dated external-flow schedule.
- A missing interior endpoint withholds the affected adjacent months' growth and rate and the
  chained return; known contributions and withdrawals remain available. Independent period
  growth or XIRR may remain available when the outer endpoints and flows are known. A missing
  value is never replaced by zero.
- Money stays in integer kopecks and rates are Decimal fractions with `ROUND_HALF_UP`; binary
  float is not used for financial arithmetic.

## Source monthly returns API and migration 0060

- `GET /api/source-returns/monthly?source_account=...` is read-only and `no-store`. It returns
  `authority=provisional`, `financial_authority=none`, `currency=RUB`, `approximate=true`, plus
  months, period totals, contiguous segments, flows, default assumptions and gaps.
- Each month retains its own opening and closing native EOD position-plus-separate-RUB-cash
  total. Differing consecutive totals are disclosed as `seam_mismatch`; neither operand is
  replaced. Missing endpoints remain `null` with `missing_endpoint`. An invalid month does not
  suppress independent valid months.
- Migration `0060_source_money_classifications` adds the empty
  `source_intake_money_classifications` table. It is additive: existing journal, financial and
  receipt tables are unchanged. The migration is `0060_source_money_classifications` on top of
  `0059_source_intake`.
- Save captures Money occurrences in the same reserved transaction as their observations.
  Deterministic defaults classify client/bank deposits and withdrawals as external, coupons and
  dividends as income, commissions/tariffs as fees, НДФЛ as tax, and settlements/НКД по сделке
  as trade settlement. Everything else stays `unknown`; defaults are `origin=default_rule`,
  `status=assumed`.
- `PUT /api/source-intakes/{id}/money-classifications/{ref}` accepts a persisted user choice
  from the documented classification set. Repeated identical PUT is idempotent. The choice
  changes provisional interpretation only; it never creates a financial receipt or Close
  authority. Bound CLOSED months require explicit Reopen for the existing workflow.
- Re-upload does not duplicate occurrences or replace an existing classification. An exact
  original re-save with a new request ID can capture missing legacy rows; an acknowledged
  same-request replay stays read-only. A changed Money extraction count refuses with
  `source_intake_parser_revision_changed`.
- Pre-0060 intakes have no backfilled classifications; their used Money rows produce
  `classification_missing_legacy_intake`. Reads never interpret missing rows as zero.
  Non-RUB Money makes the affected month's flows unknown with `currency_unsupported`
  (`unknown_flow`); independent RUB-only months remain available.
- Missing monthly boundaries split the result into contiguous segments. A long report that
  supplies only its outer EOD boundaries, with no complete monthly group, retains one
  `partial_segment`; its monthly chain stays unavailable.

## Per-instrument source returns

- `GET /api/source-returns/instruments?source_account=...` is read-only, `no-store`, and returns
  `authority=provisional`, `financial_authority=none`, `currency=RUB`.
- Each monthly row retains native opening/closing quantity and EOD valuation. An absent position
  is not an affirmative zero. Missing and partial months are listed separately; neither is
  silently converted into a zero return.
- `price_effect_kopecks = V1 - V0 - buys_cost_kopecks + sells_proceeds_kopecks`.
  `income_kopecks` is classified coupons plus dividends. `total_kopecks` is price effect plus
  income. `capital_base_kopecks = V0 + buys_cost_kopecks`; `return_percent` is a simple
  percentage, `null` for a nonpositive base or unavailable operands. This is not XIRR or TWRR.
- All-time monetary fields sum available monthly components. All-time percentage stays `null`
  by design: this scope defines monetary sums, not a holding-period or chained instrument rate.
  An all-time total need not equal its independently available price-effect plus income
  subtotals when months are partial.
- NKD is counted once. A current accepted cash proof, or a unique per-row MyBroker bond
  inference from parsed price and quantity, resolves the native-total basis. An inconclusive
  inference preserves a valid accepted proof. Without either a proof or a unique inference,
  the basis is unknown and affected buys/sells/price effect/total/rate are withheld with
  `trade_nkd_basis_unknown`; a decidable inference that conflicts with the accepted proof
  makes the basis unknown and adds `trade_nkd_basis_conflict`. Missing commission or bond NKD
  is unknown; omitted stock NKD is inapplicable zero. When there is neither an accepted proof
  nor a trade nominal, a unique arithmetic reading may assume face 1000; the affected cost
  then carries `face_value_assumed` and is approximate, not verified. If the true face differs,
  that assumption can select the wrong NKD basis. Bond valuation does not resolve
  clean/dirty or accrued-interest basis, so bonds carry `approximate=true` and
  `bond_valuation_basis_unknown` without blocking the numbers.
- One-part or absent trade identity produces `trade_identity_unresolved` and withholds the
  affected costs, including across overlapping reports. Pending or missing settlement produces
  `trade_missing_settlement`. Contradictory trades, REPO and non-RUB trades withhold affected
  costs. `RUR` is treated as `RUB`; native source facts are not rewritten.
- Income is attributed by whole ISIN or an explicit saved registration alias before whole saved
  names. A missing or ambiguous match stays in the income list with `isin=null` and an
  `unattributed_income` gap. Every income field is nullable: an incomplete covered month keeps
  only genuinely observed matching amounts, or `null` if none; a complete covered month with no
  income is affirmative zero. `income_complete=false` discloses the gap. Assumed income makes
  the row approximate; confirmed income alone does not.
- Unsupported section structure, scope ambiguity and unreadable overlaps are month-local source
  gaps with explicit codes such as `source_reader_unavailable`,
  `native_source_scope_ambiguous`, `unparsed_source_rows`, `unknown_section`,
  `4_Transfers_unsupported`, `5_UFSR_unsupported` and `position_row_unclassified`. They withhold
  affected costs and total while retaining independent instruments and months where evidence
  permits.
- `seam_mismatch` also discloses differing consecutive native opening/closing quantities or
  within-month movements unexplained by observed trades. It never replaces native operands.

## v2 «Доходность по месяцам» page and multi-file upload

- New route `/v2/capital/monthly-returns`, linked from the v2 «Доходность» page. The page is
  explicitly labelled provisional: «Предварительная оценка по сохранённым выпискам. Не
  финансовый результат.»
- The «Добавить несколько файлов» panel accepts multiple XML statements. Each file has its own
  save and authoritative readback state; one file's save failure does not reject the batch.
  A readback failure shows «Сохранен · не удалось прочитать» and offers a read-only retry that
  does not re-upload the file. Re-uploading the same original must not create duplicate journal
  occurrences or classifications.
- The page shows the source-account selector, the all-time summary («Взносы», «Выводы»,
  «Рост отдельно», XIRR annualized and period, and the approximate chained Modified Dietz
  labelled «≈TWRR»), the monthly «Взносы и рост» table, and the per-instrument
  «Цена и выплаты по инструментам» table. Coupons and dividends are shown separately from
  contributions and from price effect.
- Flags are visible rather than hidden: «приблизительно», «частичные данные»,
  «доходы неполные», assumption badges, gap codes such as «нет границы месяца» and
  «неизвестный поток», and the «Пробелы и перекрытия источников» list. A clean-looking row is
  not proof of financial completeness.
- UI tests for this page and the upload flow are synthetic. There is no Owner-real numerical UAT
  for the page, the source account, the uploaded statements or any displayed value.

## Docs and CI changes

- #916 recorded the 2026-10-20 status and changelog entries for this slice.
- #918 lets the docs-only classifier accept Markdown prose anywhere under `docs/archive/**`
  while keeping release notes, scripts, JSON and other non-prose archive content on the full
  path. It also makes an unknown Playwright project fail with the requested name and the list of
  valid project names instead of an opaque error.
- #919 speeds the PR pipeline by splitting release runtime safety from release safety,
  rebalancing backend persistence/integration lanes and caching the uv setup without dropping
  the retained coverage. The docs-only omitted-job list and aggregate `ci-ok` contract were
  updated with it.
- #920 tidied the documentation index, condensed stale sections and fixed links. The release
  note path itself remains outside the docs-only fast path because release identity checks read
  `docs/release-notes-X.Y.Z.md`; a change to that path is deliberately classified as full CI.

## Limits and non-claims

- **Synthetic-tested only.** #911/#913/#915 basis and API tests and #917 UI tests use synthetic
  data. CI success is not Owner-real numerical UAT, not a real-statement reconciliation and not
  financial authority.
- **No Owner-real numerical UAT yet.** No real account, statement, month or instrument result in
  this slice has been accepted by the Owner. Numbers must not be used for decisions, tax,
  reporting or Close.
- **Approximate by construction.** Monthly Modified Dietz, the chained ≈TWRR and XIRR are
  estimates over provisional source endpoints and classified flows. This is not exact TWRR,
  not exact portfolio/account XIRR, and not a proof of returns.
- **Classification is provisional.** Default external/income classifications are assumptions
  captured at upload. Unknown, invalid, unclassified, legacy, non-RUB or structurally ambiguous
  rows withhold affected metrics. The page does not expose a classification editor; persisted
  overrides are API-level and do not create financial authority.
- **No tax claim.** Fees and taxes are classified for source interpretation, but this view is
  not a tax-adjusted result and makes no tax, НДФЛ or cost-basis conclusion.
- **Bond and NKD limits.** Bonds use reported values without resolving clean/dirty or
  accrued-interest basis. NKD is counted once where an accepted proof or a unique per-row
  inference resolves the basis; rows with neither, or with a decidable inference that
  conflicts with the proof, are withheld. Sells rely on per-row inference or remain withheld;
  the buy cash checks do not validate sells.
- **Null is not zero.** Missing endpoints, unknown flows, incomplete instrument income, missing
  months, partial months and unsupported structure stay `null` with reason codes. For
  per-instrument income, a covered complete empty month is affirmative zero; an uncovered or
  incomplete one is not. Monthly income subtotals remain observed sums and are read with their
  gaps.
- **Known defect.** Non-dict proof claims raise `AttributeError` in the per-instrument reader.
  This is a documented limitation of the candidate, not a financial result.
- **No legacy backfill.** Migration 0060 does not reconstruct classifications for pre-0060
  intakes. An exact original re-save with a new request ID can capture missing rows; a replay
  does not.
- **No financial or runtime action.** Return reads are read-only. The upload path writes only
  source-intake journal rows (original/observations/revisions) and provisional classifications;
  it performs no Apply, Close, Reopen, financial receipt, metadata promotion, Stable update,
  publication or broker communication. The slice adds read-only return endpoints, provisional UI
  and the additive 0060 table.

## Compatibility, migration and rollback

- Published v1.3.0 is schema `0058_broker_money_ownership`. This candidate adds
  `0059_source_intake` and `0060_source_money_classifications`. Both are additive to the
  existing schema.
- Synthetic migration coverage includes upgrade through `0059`/`0060` to head and the
  populated `0060` downgrade/re-upgrade. The `0060` downgrade drops
  `source_intake_money_classifications` only; the `0059` journal and financial tables are
  preserved. Re-upgrade recreates an empty table, and classification choices are not
  reconstructed. A populated `0059` journal refuses downgrade to `0058`.
- A production rollback from the `0060` schema to `0058` is **BLOCKED** with the current
  accepted procedures. The in-app restore requires an exact same-schema database, the isolated
  recovery wrapper only restores into a fresh non-Stable target, and `update-stable.ps1` pins
  and validates code only; none can replace the Stable database with a `0058` backup. An
  Alembic downgrade is not a production rollback. Old v1.3.0 code must never open a
  `0059`/`0060` database.
- After `0060` has been created, the only executable production path is a forward fix on
  `0060`. Returning to the `0058` pair requires a separately accepted production cross-schema
  restore procedure.
- See the [1.4.0 rollback plan](releases/1.4.0-rollback.md) for the blocked production-restore
  status, the isolated rehearsal checks, the Test-only downgrade note and the forward-fix path.

## Not included

This draft does not include #839 external-flow reconciliation or a combined-period accepted
result, #891 full economic result, #856 AI numerical export, exact TWRR, financial Apply/Close,
tax reporting, owner-real numerical acceptance, publication, installation or a Stable update.
It also does not resolve Alfa PRO protocol compatibility (#646) or any historical source
inventory gap. Dated runtime and UAT status remains in [CURRENT_STATUS](CURRENT_STATUS.md), not
in this draft.

## Publication prerequisites

Before this file can be used as a release note:

1. complete the [Test-run checklist](releases/1.4.0-test-run.md) on a separate Test/scratch
   runtime with real statements and record the Owner/Integrator disposition;
2. replace the DRAFT/UAT-PENDING wording with publication-ready facts and remove the candidate
   disclaimer;
3. set the application version to the approved release version in both version files;
4. pass exact-main CI and the guarded release guard chain in
   [O3](OWNER_RUNTIME_OPERATIONS.md#o3);
5. keep publication, backup-first Stable update and Start as separate Owner actions.

The presence of this file does not authorize any of those steps.
