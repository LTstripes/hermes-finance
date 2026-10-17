# Known instrument cash income — #858

Accepted boundary: [#858](https://github.com/LTstripes/hermes-finance/issues/858)
and [#855 acceptance](https://github.com/LTstripes/hermes-finance/issues/855#issuecomment-6231173234).

`GET /api/instruments/{instrument_id}/cash-income?account_id=…&t0=YYYY-MM-DD&t1=YYYY-MM-DD`
reads one exact brokerage/IIS account, one historically supported RUB stock/bond,
and posted dates `(t0,t1]`. Invalid dates return 422, missing references 404.
The desktop entry is an on-demand block on Capital → Performance. It lists the
catalogue including inactive instruments; current holdings do not filter payouts.

The canonical service owns composition; ICF owns economic identity. Each ICF ID
appears once. Equal dates and amounts are not a deduplication key. Money source
occurrences and typed PDF links qualify the ICF rather than adding cash events.
Source-net coupons require effective `source_cash_coupons.authority`; an active
linked PDF cannot revive a retired Money proof. Legacy typed payouts require
active, scope-compatible latest `AppliedStatementEventRevision` readback.
Manual rows retain `manual_booked` even when independently corroborated.

Historical denomination/type needs frozen native SOURCE-receipt identity with
matching original source digest, current accepted bindings and dispositions,
or Money's explicit effective exact-RUB-bond acceptance. Today's instrument
catalogue and RUB payment currency alone cannot supply historical denomination.
Prior valid identity supports exited holdings; source revocation/remapping loses
that authority. Unsupported rows remain visible with reasons and are excluded.
Unlinked PDFs and XML dividend summaries are not semantic event sources.

Amounts are exact two-decimal RUB strings backed by integer kopecks. `booked_net`
is the observed ICF fact; `included_in_known_net` identifies rows admitted to the
provable coupon/dividend subtotals. Missing qualifying observations yield NULL,
not zero. An evidenced zero row can yield `0.00`. Net is never reduced by tax or
fees a second time. PDF `tax_available=false` yields tax NULL despite legacy
technical storage zero. Non-RUB rows have all RUB amount fields NULL.

`coverage` and `completeness` are always `unknown`: there is no whole-interval
proof in this slice. No observed rows does not mean no actual income. Redemption
principal, paid NKD, funding, prices and forecasts are excluded. No total-return
RUB/%, valuation inference or AI export is produced.

One existing `coherent_read_operation` pins the query-only committed SQLite
snapshot for facts, proofs, absence sets, mappings and retained revision journals.
No DML, provider, acceptance, Apply, Close or reopen is performed. The deterministic
dependency fingerprint binds retained journals, including retirement/correction/
disposition history, so supported source A→B→A cannot restore an old token.

The existing canonical ledger has a bounded limitation: generic gross-component
ICFs have no standalone revision journal. Only source-owned same-month scopes
have the existing monotonic Money dependency journal. Without such a journal or
effective Money ownership, a manual/custom row or typed payout remains an honest
unavailable proof: the booked fact is visible, the subtotal excludes it, and the
full-response `dependency_fingerprint` is NULL. The API never invents a reusable
ABA token from unchanged legacy values. This adds no writer or persistence schema.
The UI clears results on selector/context changes and each explicit read has a
new request generation; it hides values during refresh/errors and rejects a
different response scope. NULL fingerprint is explained in provenance details.

Focused verification lives in `test_instrument_cash_income_service.py`,
`InstrumentCashIncome.test.tsx`, and the disposable real-backend desktop journey:
`npm run build` then
`npm run test:e2e -- --config=playwright.instrument-income.config.ts`.
All test source documents, accounts and screenshots are synthetic. This evidence
does not replace separately authorized Owner UAT.
