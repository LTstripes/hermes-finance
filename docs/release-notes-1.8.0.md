# Hermes Finance 1.8.0

This release combines the dated instrument detail, native bond cash and issue
attribution fixes from #987-#991 with the persistent XML and Alfa investment-PDF
source-return workflow from [#992](https://github.com/LTstripes/hermes-finance/pull/992).
Current publication, installation and acceptance evidence belongs to
[CURRENT_STATUS](CURRENT_STATUS.md).

## Source history and payout evidence

Broker statements accepts the existing XML originals and one optional Alfa
investment-report PDF covering the selected accounts. Preview shows the actual
declared historical interval, existing-source comparison and conflicts; it does
not masquerade as the selected month. After immutable XML Save, explicit Save
stores typed PDF identity/control evidence on the existing append-only proof host.
PDF rows corroborate XML Money and never create another payout or second ledger.
Exact account, payment kind, date, currency and registration groups must match
completely. Ambiguous groups remain unresolved; arbitrary subset-sum matching is
not used. T-Invest forecasts remain separate from actual income.

The ordinary account, instrument and Returns readers recompute source-only RUB
results after Reload. Modified Dietz describes the supported period result;
period and annual XIRR are labelled separately and require valid dated flows.
Unknown operands withhold affected complete metrics while retaining labelled
known components. Account-wide taxes, fees, compensation and REPO financing are
shown separately rather than allocated to instruments by guesswork. Long
originals do not invent intermediate monthly valuations or require old months
to be closed. CLOSED financial facts are preserved.

Native bond BUY cash retains included accrued interest once and fees once.
Source event attribution uses exact original issue/reference evidence, including
trade-only matured issues; the presence of a trade alone does not link Money.
Conflicts, anonymous accrued interest and missing linkage remain explicit.
Temporal endpoint equivalence is allowed only within the separately accepted
exact-original contract in [C7](ARCHITECTURE_AND_CONTRACTS.md#c7).

## Persistence and update safety

Schema **0067_investment_report_proofs** extends the existing proof host and
preserves historical rows, sequences and unrelated schema. Source-only evidence
binds originals, revisions, classifications, physical database and backend code.
Exact retry/readback does not append another proof. Replacement requires explicit
acknowledgement; stale evidence supplies no numeric fallback. Raw PDF/XML payloads
are not stored in the new proof profile.

Use [O3](OWNER_RUNTIME_OPERATIONS.md#o3): verify exact-main CI and guarded annotated
publication, retain a fresh verified backup with producing code, rehearse the
0066-to-0067 transition on a physically separate copy, then use stock backup-first
OPS02 with the exact existing DatabasePath. Prepare/Validate and Start are
separate operations. After Start verify health/version, physical binding,
integrity and historical financial-data continuity.

Code deployment does not automatically import history, confirm source evidence,
activate valuation packets, call providers, Apply financial data or Close a month.
Any authorized history operation requires fresh original-bound Preview and
conflict/deduplication checks. Backend code changes retire old investment proofs
and require fresh explicit confirmation. On failed or uncertain Start, stop only
the owned runtime, retain the database and backup, and do not automatically
downgrade or overwrite across schemas.
