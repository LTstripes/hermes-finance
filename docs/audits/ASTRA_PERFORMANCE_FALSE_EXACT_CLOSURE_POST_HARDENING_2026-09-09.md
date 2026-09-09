# ASTRA post-hardening false-exact closure audit — 2026-09-09

> Reviewer-only audit. Production code was not changed. Verdict: **BLOCK**.

## Итог

На проверенном post-hardening candidate подтверждены два независимых HIGH-пути,
где exact availability сохраняется без достаточного persisted evidence:

1. reverse-date transfer legs обходят transit gate на required closing valuation;
2. после material correction `ExternalFlow` повторная cash-attestation не
   пересматривает уже сохранённые observed TWRR boundary points.

Оба пути воспроизведены на synthetic isolated databases. По требованию аудит
остановлен после двух подтверждённых HIGH findings. Остальные OPEN hypotheses
ниже не объявляются закрытыми и не поднимались до третьего reproducer.

## Scope and exact candidate

- Repository: `LTstripes/hermes-finance`
- Workstream: `integration/performance-v1`
- Audit branch: `audit/astra-performance-false-exact-post-hardening-20260909`
- Candidate under review: `d89830b11af32c2d10a1673e36a6a85d608ed7f2`
  (`fix(performance): invalidate cash attestation on flow mutation`)
- Candidate ancestry: base `ee35db2b58875914107d304d3537fdfb3661c67f`,
  F1 `2ef4ce1`, F1 regression test `cb78f03`, F2 `cc76824`, F3 `d89830b`.
- Baseline contract:
  `docs/PERFORMANCE_V1_RECONCILIATION_2026-09-06.md`
- Prior OPEN-hypothesis register:
  `docs/audits/ASTRA_PERFORMANCE_FALSE_EXACT_CLOSURE_2026-09-08.md`

Read-only ref check showed `origin/integration/performance-v1` at
`ee35db2b58875914107d304d3537fdfb3661c67f`; F3 is still the separate candidate
under review. This audit did not merge or rewrite the integration ref.

## Review method and boundary

Static reasoning was primary. The reviewed path was the availability assembly
through `portfolio_xirr`/`portfolio_twrr`, not solver re-implementation. Synthetic
tests were used only for the two suspicious paths and reused existing isolated
R08 fixtures. They contain no owner/runtime data, credentials, provider calls,
or production database access.

The normative contract treats exact TWRR as dependent on observed boundary
evidence and requires fail-closed handling for unvalued transfer transit and
ambiguous historical identity (`PERFORMANCE_V1_RECONCILIATION_2026-09-06.md:46-49,
76-135`).

## Confirmed finding C1 — HIGH: reverse-date transfer bypasses required transit

### Concrete path

`services/performance_availability.py:1149-1270` constructs `transit_dates` only
when `source.event_date < destination.event_date` (`:1194`). A linked pair with
destination on 2030-02-10 and source on 2030-02-15 therefore gets no transit
dates. It remains an `INTERNAL_TRANSFER`, and no
`not_computable_transfer_in_transit_unvalued` reason is added.

The candidate nevertheless supplies the closing date 2030-02-12 to both metric
required-date sets (`:1388-1394`). That date lies between the two persisted leg
dates, but the reverse ordering has removed the only transit check. The
membership and cash/in-kind prerequisites are complete; no transit valuation or
ordering/continuity provenance is persisted.

### Minimal reproducer

`docs/audits/evidence/test_post_hardening_false_exact_closure.py:39-79`

- two stable in-scope brokerage accounts with complete cash and in-kind history;
- source withdrawal 1000 RUB on 15 Feb and destination contribution 1000 RUB on
  10 Feb;
- requested interval ends on 12 Feb, between the reverse-date legs;
- both reporting months are closed before availability is read.

### Expected vs actual

Expected: `NOT_COMPUTABLE` for the portfolio metrics because the required closing
valuation falls inside a transfer interval whose aggregate inclusion cannot be
proven. The system must not infer an order from date inversion.

Actual: both `availability.xirr` and `availability.twrr` are `AVAILABLE`, and
the TWRR service is exact with a non-null return. The reproducer also asserts
the absence of the transit blocker. This is a false-exact availability path,
not a solver arithmetic claim.

The accepted contract deliberately permits an unrelated intermediate TWRR
boundary to leave XIRR available while blocking TWRR; this reproducer is
stronger because the required XIRR closing valuation itself is inside the
reverse-date interval.

### Fix direction (not implemented)

Make transfer chronology an explicit valid/invalid state. Any non-strict or
reverse leg ordering that can contain a required valuation must fail closed
unless an accepted ordering/continuity evidence model proves the aggregate
boundary. Do not silently treat the reverse interval as empty.

## Confirmed finding C2 — HIGH: flow correction leaves stale exact TWRR boundary evidence

### Concrete path

F3 invalidates intersecting COMPLETE cash coverage on a material canonical-flow
mutation (`services/external_flows.py:476-604` and
`services/cash_boundary_coverage.py:282-313`). After the owner explicitly
reopens the months and re-attests the corrected cash history, the old observed
valuation points remain linked to the same `external_flow_id`.

`ObservedValuationPoint` persists the flow link, date, value, quality, and
coverage, but no flow amount/event revision or immutable economic-event
signature (`persistence.py:1203-1295`).
`services/performance_availability.py:983-1059` checks the point’s date,
currency, coverage, and quality, but not the current flow signature. Then
`services/portfolio_twrr.py:86-123` uses the **current** signed flow amount with
the **old** persisted pre/post values.

### Minimal reproducer

`docs/audits/evidence/test_post_hardening_false_exact_closure.py:83-169`

- initial canonical contribution: 100 RUB;
- exact observed portfolio boundary: pre 100 RUB, post 200 RUB;
- initial TWRR is available with zero return;
- reopen, correct the flow to 125 RUB, explicitly re-attest cash coverage, and
  close again;
- the two old observed points remain unchanged.

### Expected vs actual

Expected: the corrected event must invalidate or version the related observed
TWRR boundary evidence. Until replacement evidence is captured and accepted,
TWRR must be `NOT_COMPUTABLE`; cash re-attestation alone is insufficient.

Actual: availability and `portfolio_twrr_for_interval` remain exact, while the
calculation combines 125 RUB with the old 100/200 RUB boundary. The reproducer
observes a non-zero negative exact return and proves that the persisted points
were not revised.

### Fix direction (not implemented)

Bind observed boundary evidence to an immutable flow/economic-event revision or
invalidate it on every material flow mutation, including amount, date, currency,
scope, and replacement. Require fresh pre/post evidence before exact TWRR is
restored.

## Static disposition of the requested OPEN hypotheses

| Area | Evidence checked | Disposition after the two-finding stop |
|---|---|---|
| Reverse-date transfers | `performance_availability.py:1149-1270`; C1 reproducer | **Confirmed HIGH** |
| Transfer mutation / reconciliation evidence identity | `external_flows.py:496-604`; `transfer_reconciliation.py:118-200`; evidence stores only `transfer_link_id` plus free-form reference (`persistence.py:1086-1140`) | **OPEN suspicion, not promoted**. Amount/date/currency/scope edits do not require deleting link evidence; no third synthetic finding was run after the stop. |
| Async transfer + membership transition | `_scope_membership_coverage` and `_has_membership_transition_inside` (`performance_availability.py:144-246`); forward-transit cross-check in `:1194-1225` | Forward transit and inclusive membership transition gates remained present in static review. Reverse-date C1 is the confirmed interaction bypass; no separate transition cross-product was run. |
| Direct payout / legacy withdrawal economic-event identity | `_legacy_flow_ids` (`performance_availability.py:466-503`) and `_direct_payout_reason_codes` (`:515-565`) use account/date/currency keys; income is not separately fed to return math | **OPEN**. Missing transaction/holding identity and legacy cash-flow mutation invalidation are suspicious, but were not promoted after the stop. |
| Correction/replacement observed TWRR boundary evidence | `ObservedValuationPoint`, `_observed_boundary_for_target`, and `_boundaries_from_availability` | **Confirmed HIGH** as C2. |
| Coverage overlap/endpoints | Inclusive overlap predicates and gap/overlap rejection in cash (`cash_boundary_coverage.py:316-388`) and in-kind (`in_kind_boundary_coverage.py:491-550`) coverage | No additional bypass found statically; endpoint/overlap matrix was not exhaustively regenerated. |
| F1/F2/F3 interaction | F1 snapshot-clock population (`in_kind_boundary_coverage.py:428-446`); F2 same-day reason propagation (`performance_availability.py:1253-1270`); F3 cash invalidation (`external_flows.py:587-604`) | F1/F2 targeted regressions remain green. F3 closes cash-attestation mutation but leaves the C2 valuation-evidence gap. |

The table intentionally distinguishes “no additional bypass found in the
checked static path” from proof that every hypothesis is closed.

## Checkpoints and changed scope

| Checkpoint | Commit | Contents |
|---|---|---|
| Scope captured | `c9eeeb3` | Exact candidate/baseline and reviewer-only scope |
| Evidence captured | `9dce4ad` | Synthetic audit reproducer file |
| Final report | pending | Findings, matrix, checks, and BLOCK verdict |

Only these audit artifacts are in scope:

- this report;
- `docs/audits/evidence/test_post_hardening_false_exact_closure.py`.

No production source, migration, existing production test, PR, merge, tag,
release, or owner/runtime state was changed.

## Checks actually run

- Audit evidence, from `backend` with an external unique pytest basetemp:
  `uv run --locked pytest ../docs/audits/evidence/test_post_hardening_false_exact_closure.py -q --basetemp D:\Finance\pytest-post-hardening-20260909-reverse`
  — **2 passed**.
- Existing regression lanes on the candidate:
  `test_r08_h2a_scope_membership_changed.py`,
  `test_r08_h2b_cash_boundary.py`,
  `test_r08_h2c_transfer_transit.py`,
  `test_r08_h2d_in_kind_coverage.py`,
  `test_r08_h3_tax_direct_payout.py`, and
  `test_r08_01c_performance_availability.py` — **71 passed**.
- Audit evidence lint:
  `uv run --locked ruff check ../docs/audits/evidence/test_post_hardening_false_exact_closure.py`
  — **PASS**.
- `git diff --check` — **PASS**.
- `uv run --locked python ../scripts/privacy_check.py` — **PASS (814 tracked files)**.

No full backend suite, CI, owner UAT, provider call, or private runtime probe is
claimed; none was needed for this reviewer-only static/synthetic closure audit.

## Verdict

**BLOCK** for candidate
`d89830b11af32c2d10a1673e36a6a85d608ed7f2`.

Two concrete HIGH false-exact paths remain. The branch is not acceptable for an
exactness-closure verdict until reverse-date transfer transit and observed TWRR
boundary revision identity are fixed and independently re-audited. No PR or
merge was created.
