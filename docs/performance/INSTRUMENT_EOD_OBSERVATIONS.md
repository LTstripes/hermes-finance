# Exact instrument EOD observations — #860

Accepted scope: [#860](https://github.com/LTstripes/hermes-finance/issues/860),
following [#855 acceptance](https://github.com/LTstripes/hermes-finance/issues/855#issuecomment-6231173234).
Implementation started after #858 post-main CI succeeded on `9586f2ba5571cd40c8bcfc2fedd98d676d65c5ad`.

`GET /api/instruments/{instrument_id}/eod-observations?account_id=…&t0=YYYY-MM-DD&t1=YYYY-MM-DD`
reads one exact brokerage/IIS account and two exact persisted `PositionSnapshot`
observations, with `t0 < t1`. Invalid dates return 422; absent references return
404. The existing on-demand Capital → Performance panel reads this composite
endpoint once. Both boundaries and [known net payouts](INSTRUMENT_CASH_INCOME.md)
share one committed, query-only snapshot. Payout dates remain `(t0,t1]`.

Each available boundary exposes Decimal quantity, exact RUB market value,
historical RUB stock/bond identity, native NKD basis, price date, position/import/
row identifiers, accepted receipt IDs, revision generation, currentness and
dependency fingerprint. Amounts remain integer-kopek-backed decimal strings.
Per-unit quote absence does not erase an independently accepted native total.
No nearest-date, live quote or catalogue-only identity fallback is allowed.

Authority reuses native SOURCE receipts, original source integrity, accepted
historical mappings/dispositions, canonical overlap conflicts and native
account/month projection readback. A changed, ambiguous, archived, unsupported
or unproven boundary returns NULL numeric values and explicit reason codes.
Missing positions never imply zero ownership or value. The native writer's
suppressed zero row also cannot establish zero closing value without separate
accepted evidence of no outstanding entitlement. Inactive/exited instruments
remain selectable and their known payouts remain independent of endpoint gaps.

Pair comparability concerns the observed value basis only. Unknown bond NKD
basis leaves comparability NULL; mismatched basis/identity makes it false.
Only comparable observations may expose `observed_position_value_difference`.
Changing quantity does not establish price profit, sale proceeds, cost or a
realized/unrealized split. The UI labels any difference as observed position
values, never adds payouts to it, and prominently states that full instrument
return RUB/% is unavailable. Interval activity and payout completeness remain
unknown. No new accounting engine, writer, schema, provider call or export exists.

The EOD token binds relevant source material, retained mappings/history,
account/instrument/periods, positions, account receipts and current native
account/month projection digests. Unrelated accounts' original source text is
not hashed into it. The existing global correction generation conservatively
invalidates it on source/registry/catalogue SQL changes, including ABA. Native
position/month/cash changes through supported ORM writers use the retained
monotonic dependency receipts. Arbitrary SQL projection ABA bypassing those
writers is outside that existing journal guarantee; this slice adds no triggers.
Changed current projection readback is still detected. No reliable native
boundary journal means that boundary's token is NULL.

`valuation_dependency_fingerprint` describes the EOD dependency set. The full
`dependency_fingerprint` additionally binds #858's payout token and is NULL
whenever either boundary journal or the payout token is unavailable. #858 manual,
retired, UNKNOWN, NULL and tax semantics are unchanged. The UI hides both sections
during refresh/error or selector/context changes and rejects a different outer,
boundary or payout scope. Every explicit read gets a new request generation.

Focused evidence: `test_instrument_eod_observations_service.py`, unchanged #858
regressions and `InstrumentCashIncome.test.tsx`. The disposable real-backend
production-dist desktop journey is:

```text
npm run build
npm run test:e2e -- --config=playwright.instrument-eod.config.ts
```

It covers bond 1000/950/coupon 120, stock 1000/900/dividend 120, exact-date gaps,
provenance, selector invalidation, keyboard submission, 1440px desktop and
1280px at 125% zoom. Its accounts, documents and screenshots are synthetic;
it performs no Owner/Stable operations and does not replace Owner UAT.
