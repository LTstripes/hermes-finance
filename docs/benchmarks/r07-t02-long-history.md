# R07-T02 — Long-history performance envelope

## Scope and method

This report measures the existing read paths before any production
optimization or materialization. Every value is synthetic. Each case creates
a fresh temporary SQLite database with `Base.metadata.create_all`, seeds the
same deterministic shape, performs one warm-up request, and records five
measured requests. Timings are local wall-clock observations on the Windows
development host; they are not CI performance guarantees.

The generator and harness are [r07_t02_long_history.py](../../backend/benchmarks/r07_t02_long_history.py).
Run it from `backend`:

```powershell
$env:UV_CACHE_DIR = (Resolve-Path '.uv-cache').Path
uv run python benchmarks/r07_t02_long_history.py --years 1 5 10 20 --repeats 5
```

The harness measures median and p95 wall time, maximum SQL statement count
from SQLAlchemy's `before_cursor_execute` hook, and maximum response size.
Seed/setup, warm-up, and synthetic backup creation are excluded from the
timings. Dashboard and export calls target the latest closed month. The
backup read is `GET /api/backups` after creating one synthetic backup. The
lifecycle operation is one `clone -> close -> reopen` sequence.

The 20-year case contains 240 closed reporting months and the following
deterministic row shape:

| Table | Rows | Scaling |
| --- | ---: | ---: |
| reporting_months | 240 | 12/month |
| accounts | 5 | fixed |
| instruments | 8 | fixed |
| position_snapshots | 3,840 | 16/month |
| deposit_snapshots | 480 | 2/month |
| cash_balances | 240 | 1/month |
| income_entries | 240 | 1/month |
| investment_cash_flows | 960 | 4/month |
| expected_cash_flows | 960 | 4/month |
| expense_entries | 240 | 1/month |
| debts | 240 | 1/month |
| property_snapshots | 240 | 1/month |

## Budgets

These are pragmatic local-development budgets for the representative
operations, not user-facing SLAs.

| Operation | 20-year p95 budget |
| --- | ---: |
| dashboard load | <= 2,500 ms |
| capital-composition analytics | <= 1,000 ms |
| Markdown export | <= 3,000 ms |
| JSON export | <= 3,000 ms |
| clone -> close -> reopen | <= 250 ms |
| backup listing | <= 100 ms |

## Measured results

All values below are from one run of the command above. `queries` is the
maximum SQL statement count across the five samples; export response sizes
are included to show that the result itself also grows for JSON/history
payloads.

### 1 year — 12 months

| Operation | Median | p95 | SQL queries | Response bytes |
| --- | ---: | ---: | ---: | ---: |
| dashboard load | 155.381 ms | 168.656 ms | 320 | 12,633 |
| capital-composition analytics | 45.294 ms | 53.145 ms | 85 | 7,740 |
| Markdown export | 197.629 ms | 284.538 ms | 329 | 5,163 |
| JSON export | 184.709 ms | 190.587 ms | 352 | 55,115 |
| clone -> close -> reopen | 41.340 ms | 51.806 ms | 41 | 95 |
| backup listing | 3.325 ms | 4.245 ms | 0 | 233 |

### 5 years — 60 months

| Operation | Median | p95 | SQL queries | Response bytes |
| --- | ---: | ---: | ---: | ---: |
| dashboard load | 694.692 ms | 743.755 ms | 1,328 | 20,819 |
| capital-composition analytics | 235.830 ms | 246.189 ms | 421 | 38,424 |
| Markdown export | 641.694 ms | 679.005 ms | 1,337 | 5,172 |
| JSON export | 661.843 ms | 683.330 ms | 1,360 | 70,811 |
| clone -> close -> reopen | 46.204 ms | 50.239 ms | 41 | 95 |
| backup listing | 2.791 ms | 3.664 ms | 0 | 233 |

### 10 years — 120 months

| Operation | Median | p95 | SQL queries | Response bytes |
| --- | ---: | ---: | ---: | ---: |
| dashboard load | 1,258.277 ms | 1,271.717 ms | 2,588 | 31,110 |
| capital-composition analytics | 450.033 ms | 452.274 ms | 841 | 76,800 |
| Markdown export | 1,162.983 ms | 1,179.817 ms | 2,597 | 5,182 |
| JSON export | 1,178.079 ms | 1,201.139 ms | 2,620 | 90,515 |
| clone -> close -> reopen | 38.742 ms | 49.483 ms | 41 | 96 |
| backup listing | 2.329 ms | 2.875 ms | 0 | 233 |

### 20 years — 240 months

| Operation | Median | p95 | SQL queries | Response bytes |
| --- | ---: | ---: | ---: | ---: |
| dashboard load | 2,323.467 ms | 2,336.628 ms | 5,108 | 51,788 |
| capital-composition analytics | 856.586 ms | 868.801 ms | 1,681 | 153,670 |
| Markdown export | 2,299.123 ms | 2,360.467 ms | 5,117 | 5,188 |
| JSON export | 2,429.285 ms | 2,489.225 ms | 5,140 | 129,913 |
| clone -> close -> reopen | 38.621 ms | 49.532 ms | 41 | 96 |
| backup listing | 3.107 ms | 3.937 ms | 0 | 233 |

## R07-T02A after batched historical reads

The same command, deterministic seed, warm-up and five measured requests were
rerun after the R07-T02A implementation. Each cell is `median / p95 / SQL`
and uses milliseconds for the first two values. Response sizes stayed exactly
equal to the baseline at every horizon.

### Before → after: 1 year — 12 months

| Operation | Before | After |
| --- | --- | --- |
| dashboard load | 155.381 / 168.656 / 320 | 80.001 / 84.153 / 87 |
| capital-composition analytics | 45.294 / 53.145 / 85 | 13.614 / 16.151 / 6 |
| Markdown export | 197.629 / 284.538 / 329 | 85.457 / 196.825 / 96 |
| JSON export | 184.709 / 190.587 / 352 | 100.134 / 112.127 / 119 |
| clone → close → reopen | 41.340 / 51.806 / 41 | 50.702 / 56.393 / 41 |
| backup listing | 3.325 / 4.245 / 0 | 4.743 / 5.089 / 0 |

### Before → after: 5 years — 60 months

| Operation | Before | After |
| --- | --- | --- |
| dashboard load | 694.692 / 743.755 / 1,328 | 102.441 / 115.076 / 87 |
| capital-composition analytics | 235.830 / 246.189 / 421 | 27.429 / 31.065 / 6 |
| Markdown export | 641.694 / 679.005 / 1,337 | 104.226 / 118.468 / 96 |
| JSON export | 661.843 / 683.330 / 1,360 | 132.780 / 134.961 / 119 |
| clone → close → reopen | 46.204 / 50.239 / 41 | 56.563 / 68.350 / 41 |
| backup listing | 2.791 / 3.664 / 0 | 3.659 / 4.502 / 0 |

### Before → after: 10 years — 120 months

| Operation | Before | After |
| --- | --- | --- |
| dashboard load | 1,258.277 / 1,271.717 / 2,588 | 132.810 / 180.537 / 87 |
| capital-composition analytics | 450.033 / 452.274 / 841 | 45.747 / 53.212 / 6 |
| Markdown export | 1,162.983 / 1,179.817 / 2,597 | 159.660 / 171.625 / 96 |
| JSON export | 1,178.079 / 1,201.139 / 2,620 | 192.459 / 196.938 / 119 |
| clone → close → reopen | 38.742 / 49.483 / 41 | 58.195 / 80.196 / 41 |
| backup listing | 2.329 / 2.875 / 0 | 4.175 / 4.298 / 0 |

### Before → after: 20 years — 240 months

| Operation | Before | After |
| --- | --- | --- |
| dashboard load | 2,323.467 / 2,336.628 / 5,108 | 222.050 / 238.949 / 87 |
| capital-composition analytics | 856.586 / 868.801 / 1,681 | 83.200 / 232.810 / 6 |
| Markdown export | 2,299.123 / 2,360.467 / 5,117 | 246.721 / 424.442 / 96 |
| JSON export | 2,429.285 / 2,489.225 / 5,140 | 281.942 / 415.168 / 119 |
| clone → close → reopen | 38.621 / 49.532 / 41 | 51.282 / 63.136 / 41 |
| backup listing | 3.107 / 3.937 / 0 | 3.596 / 4.214 / 0 |

The implementation batches the month-scoped liquid-capital, passive-income
and asset-allocation reads with `IN (...)` plus grouped SQL. It keeps the
existing pure financial calculators, CLOSED-month filtering and persisted
snapshot semantics. No materialized table/view, cache or formula change was
introduced. The remaining dashboard/export cost is the bounded current-month
assembly and response serialization rather than linear historical SQL fan-out.

## Interpretation and verdict

The 20-year p95 results remain within the stated local budgets. Lifecycle
operations and backup listing are effectively history-independent. There is,
however, a clear linear history-read shape: dashboard work grows from 320 to
5,108 SQL statements and analytics from 85 to 1,681 as closed months grow from
12 to 240. The dashboard and both exports are therefore already in the
multi-second range at the upper requested history size.

**Verdict: `TARGETED_OPTIMIZATION`.**

The evidence justifies a follow-up focused on batching the per-month history
queries and/or adding narrowly validated indexes, with no financial-semantic
change. It does not yet justify materialized aggregates: the requested
20-year envelope passes the budgets, and this task did not measure a broader
workload or a user-visible failure. No production optimization or
materialization was made in R07-T02.

If materialization is considered later, its invalidation contract must cover
every closed-history mutation: initial `close`, explicit `reopen`, edits while
reopened, and the subsequent re-close. A cached closed-history result must
never include a reopened/draft month, and a reopened month must not leave a
stale contribution in rolling passive-income or capital-composition results.

The future AI bundle assembly was not available on the pinned baseline, so it
was not benchmarked. No production `.env`, `finance.db`, backup, private seed,
or owner data was read.
