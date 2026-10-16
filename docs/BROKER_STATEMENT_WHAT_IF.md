# Account-period WHAT-IF

Contract: [#839 architecture and C1–C4](https://github.com/LTstripes/hermes-finance/issues/839#issuecomment-6211969149),
[Integrator CODE GO](https://github.com/LTstripes/hermes-finance/issues/839#issuecomment-6212289246).
This separate read-only feature is outside frozen v1.3.0. Integration remains held
until an explicit release-unfreeze in #836; a draft PR or green CI does not release it.

## Scope and provenance

One accepted unchanged XML, one RUB brokerage account, its exact native `(t0,t1]`.
The new service composes unchanged S3, Money-candidate, H2-A2 inventory (current
contract), permanent ownership and metadata readers inside one committed read
snapshot. It does not call Preview/Apply, accept or reaffirm evidence, repair
receipts, persist scenarios, request providers, or calculate actual S3 with altered
evidence. Existing S3/H2/Close/exact XIRR/TWRR contracts remain unchanged.

`StatementWhatIfContext` separates verified observed endpoints/capital delta,
untouched `actual_result`, full diagnostic inventory, fixed effective H2 schedule,
zero or one optional native incoming-bank candidate, exact required assumptions,
hard blockers and context fingerprint. Bad provenance does not relabel cached
endpoints as observations. All effective H2 crossings are mandatory and counted
once. Compatible H2/Money ownership of the same target is one event; incompatible,
conflicting or ineffective ownership cannot become an optional candidate.
Coupon and trade dispositions come from the existing H2 inventory.

There is no generic outgoing classifier, manual amount/date/endpoint entry, IIS
extension, arbitrary interval, portfolio aggregation, saved scenario or batch mode.
More than one eligible optional incoming candidate or 128 fixed crossings is a
capacity blocker; inventories and schedules are never truncated.

## Finite assumptions

The server derives each requirement and its complete reference membership:

1. Model the native account continuously with both native EOD totals, without
   valuation/cost adjustments or a historical portfolio-inclusion assertion.
2. Use all fixed crossings and explicitly include/exclude the optional candidate.
   Excluding a candidate does not delete observed cash. Posting date is the native
   modeled date. `schedule_mode=explicit_empty` is required for an empty selected
   schedule and differs from missing/null; a nonempty schedule requires `dated`.
3. When actual crossing completeness is absent, assume no additional boundary
   crossings in this selected account beyond the displayed schedule.
4. Enumerated recognized unresolved coupon/NKD or S1-linked settlement/commission
   occurrences contribute no extra investor flow or endpoint adjustment in this
   native-total model. Unknown tax/NKD/fee authority is never zeroed or counted again.
5. Each named Transfers/UFSR channel separately has no additional modeled effect
   outside native totals/schedule. Only existing parsed safe patterns or a genuinely
   empty observed tree qualify. A zero row count with opaque attributes/text/comments
   does not qualify. Accepted section authority and economic period coverage remain
   separate; `period_scope=unknown` stays unknown.

No choice is selected automatically. Missing valid choices produce
`needs_assumptions` with both numeric fields null. Duplicate, extra, wrong-reference,
wrong-choice or contradictory schedule selections block. The literal
`SCOPED_REASONS` map is conditional on the complete inspected inventory; every
unknown/new reason defaults to a hard blocker. Source membership, integrity,
mapping/currentness, legacy/transfer overlap, unsupported Money, unmodeled nonempty
REPO/pending/in-kind/custody/opaque exposure and authority conflicts cannot be
bypassed by assumptions. Mathematical failure also returns null for both fields.

## Units and mathematics

Independent strict frozen WHAT-IF types do not inherit actual S3 DTOs.
Result: `kind=broker_statement_what_if_result_v1`,
`method=broker_statement_what_if_mwr_period_v1`, `scope=account`,
`authority=hypothetical`, `currency=RUB`, `annualized=false`,
`status=hypothetical|needs_assumptions|blocked`. There is no scenario `quality`
or actual `rate_fraction` override. Monetary operands and results are canonical
integer-kopeck strings; unknown is null. Diagnostic native monetary lexemes are
converted exactly into named kopeck fields, never rounded; the raw dependency
fingerprint also binds the unmodified reader material. Nonmonetary source fields
(such as native price/quantity) retain their original source units.

The unchanged Decimal XIRR kernel consumes investor flows
`-V0@t0, -Ei@ti, +V1@t1`, `t0 < ti <= t1`; positive `Ei` enters the account.
At precision 60 its internal ACT/365 root is converted to the actual-period
fraction `R=(1+r)^((t1-t0).days/365)-1`. Only that finite fixed-point Decimal
fraction is returned. No root, conservative ambiguity, nonconvergence and
nonfinite guards remain effective. No annualized number or confidence interval
is published.

`scenario_result_kopecks = V1 - V0 - sum(Ei)`, labelled
**«Условный результат после учёта выбранных внешних движений»**.
It is not actual P&L, realized/unrealized profit, taxable income or `V0 * R`.
Display uses retained string/BigInt helpers with HALF_UP and negative-zero handling.

Synthetic 30-day reference: 10,000 RUB + 1,000 RUB on day 15 → 11,211 RUB.
Independent equation: `10,000 × 1.0201 + 1,000 × 1.01 = 11,211`.
Including that candidate gives 211 RUB / 2.01%; excluding it gives 1,211 RUB /
12.11%. These are different scenarios, not bounds on actual performance.

## HTTP and desktop lifecycle

All routes are POST multipart under `/api/broker-statement-what-if`:

| Route | Required fields beyond unchanged `file`, `account_id`, accepted `request_id`, `expected_actual_fingerprint` |
| --- | --- |
| `/context` | None |
| `/evaluate` | JSON `assumptions`, `expected_context_fingerprint` |
| `/export` | Same plus `expected_result_fingerprint` |

All responses, including handled validation errors, use `Cache-Control: no-store`.
Query parameters, unexpected/duplicate form fields, endpoint overrides and invalid
strict assumptions are 422. Missing source identity is 404. Context/actual/result
staleness is a typed 409 without a number or attachment. Export re-reads and
recomputes the same full result DTO; it is never a rate-only or persisted token.
Body/XML/financial values are not included in error logs or exception diagnostics.

Context binds source/parser/scope/version, actual fingerprint, complete Money and
H2 dependency inventory including absences, permanent ownership, metadata and
relevant coupon/Money/section/flow material. Assumptions are separately canonicalized
and hashed; result binds both plus full provenance and schedule.

The panel lives below the existing S3 result on `/v2/capital/statement-return`.
Actual availability/reasons stay visible with the scenario. Native facts, accepted
H2, optional candidate, per-channel choices, selected assumptions and actual
limitations remain distinct. Full member references and diagnostic inventory expand.
Original bytes and selections exist only in page memory. Changing original,
account/source, assumptions, refreshing, errors or response mismatch hides the
old result and disables export. Generation/abort guards reject late responses,
including A→B→A source changes. Download requires fresh bound server validation.

## Reproducible synthetic verification

- Backend: `uv run --project backend pytest backend/tests/test_statement_import_broker_statement_what_if.py`.
  C1 independently compounds references and checks fraction error ≤1e-8 and RUB
  residual <0.01; includes signs, loss, internal cash, empty/missing schedule,
  endpoint dates, large integers and solver guards. C2 composes real readers and
  source fixtures; C3 checks exact reference sets and stale absence/ownership/section
  changes; C4 compares all tables, actual responses and observes zero DML.
- Desktop component tests: `npm test --prefix frontend -- BrokerStatementWhatIfPanel.test.tsx BrokerStatementReturnPage.test.tsx`.
- Production desktop/browser and freshly downloaded JSON:
  `npm run build --prefix frontend`, then from frontend
  `npx playwright test --config=playwright.what-if.config.ts`.
  This starts only a disposable synthetic runtime on loopback port 18789.
  The optional `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` selects an installed local browser.
  Screenshots are test artifacts, not Owner evidence or real financial acceptance.

Exact candidate checks, independent review and PR CI are recorded in the Draft PR.
Synthetic correctness does not guarantee numerical availability for Owner data;
later authorized real-data UAT remains separate.
