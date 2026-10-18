# R05-00 architecture benchmark — automatic payout calendar

- **Date:** 2026-08-16
- **Task:** issue #35 — R05-00 automatic investment payout calendar contract
- **Canonical starting baseline:** `main = r05 = 17a02b25801f329721caa8b554de0320ef52cf7c`
- **Mode:** blind architecture/specification comparison; no implementation task
- **Canonical outcome:** ADR 0011, `docs/adr/0011-automatic-investment-payout-calendar.md`

## Why this benchmark existed

R05-00 was deliberately used as a real-project architecture benchmark instead of a synthetic puzzle. All candidates were asked to design an implementation-ready contract for future coupon/dividend/redemption events while preserving Hermes Finance invariants: local-only, owner-triggered read-only T-Invest, exact money, closed-month immutability, manual expected-flow safety, no broker portfolio import and no background refresh.

The candidates did not inspect each other's responses during the blind phase.

## Candidates

### Grok 4.6 — owner-supplied model label

**Overall:** strongest single proposal and closest to the accepted canonical architecture.

Strong points:

- best alignment with the existing Hermes codebase and 0.4 preview/apply philosophy;
- separate provider-event/applied-event persistence instead of overloading manual `expected_cash_flows`;
- selected-reporting-month quantity with quantity frozen at apply;
- strong `preview_changed` and atomic apply semantics;
- good preservation of current C04 dividend formula instead of silently changing financial meaning;
- detailed T-Invest surface analysis and useful live-probe question list;
- explicit manual/provider reconciliation and append-only revision history.

Material corrections made by the canonical synthesis:

1. Grok proposed dividend identity including normalized `dividend_type`. This was rejected because `Cancelled` is provider lifecycle/state for a payout and must not make the same event become a new identity merely by changing type/status.
2. Grok allowed `coupon_end_date` as fallback calendar date when `coupon_date` was absent. This was rejected: official T-Invest docs define `coupon_date` as coupon payout date and `coupon_end_date` as coupon-period end. Missing payout date is tentative/unapplyable, not synthesized.
3. Synthetic redemption from `BondBy.maturity_date + nominal` was made stricter. The canonical ADR keeps it disabled until live probe proves safe constraints, especially for amortizing/perpetual bonds.
4. `missing_from_provider` was strengthened with explicit provider-coverage semantics rather than simple response omission.

**Benchmark assessment:** best architecture candidate; selected as the main structural basis of ADR 0011, but not accepted verbatim.

### DeepSeek V4 Pro — owner-supplied model label

**Overall:** strong conservative reviewer/architect, especially around backward compatibility and existing C04 semantics.

Strong points:

- correctly preserved expected-dividend exclusion from C04 v1 and kept provider dividends calendar-only;
- strong refetch + `preview_changed` concept;
- good explicit separation of expected vs actual cash flows;
- good focus on migration/backward compatibility and additive schema evolution;
- correctly treated provider omission as warning rather than delete;
- useful live-probe questions and honest uncertainty around provider fields.

Material disagreements with the canonical outcome:

1. DeepSeek's preferred design extended existing `expected_cash_flows` with provider-origin rows. The canonical synthesis rejected a shared write model because the current table's unique key, forecast-version and owner/manual semantics create avoidable collision/overwrite risk. Manual and provider events now merge at read time instead.
2. Coupon natural identity based on payment/coupon date is less stable under provider date revision than coupon number / coupon-period fallback.
3. Dividend identity fallback through mutable payment date was considered too weak for automatic apply if no stable record-date/provider identifier exists.

**Benchmark assessment:** second-best proposal for contract discipline; several ideas were adopted, especially C04 conservatism, refetch consistency and migration safety.

### Gemini 3.7 Flash — owner-supplied model label

**Overall:** very fast and useful as a broad architecture/red-team generator, but weaker evidence discipline and more invented provider/product semantics.

Strong points:

- clear two-track distinction between future cash flow and forecast passive income;
- strong anti-vanishing principle: provider omission must not delete stored data;
- good enumeration of lifecycle states and failure modes;
- useful broad task decomposition and risk list.

Material issues:

1. The proposal asserted provider/API semantics beyond the evidence supplied, including a separate `dividend_gross` field. Current official T-Invest `Dividend` documentation lists `dividend_net` as amount per security; it does not document a separate `dividend_gross` in this message.
2. It proposed synthesizing a dividend cash date as `record_date + 18 business days`. The canonical design explicitly rejects invented payout dates.
3. It proposed dynamic quantity recomputation from the current/open position. Canonical semantics freeze quantity on owner apply and require refresh/apply after quantity changes.
4. It proposed persisting full raw provider payload JSON for audit. Canonical privacy/minimality rules store normalized provenance only, not full raw payloads.
5. It offered destructive-sounding manual `LINK / REPLACE` behavior; canonical reconciliation never auto-replaces/archives/deletes a manual owner row.

**Benchmark assessment:** valuable low-cost hypothesis generator and checklist author; not reliable enough to be the sole source of a normative contract without factual verification.

### ChatGPT — GPT-5.6 Sol (runtime-confirmed for this synthesis)

**Mode:** independent repository/API analysis first, then synthesis after the three blind responses were available.

Independent findings that materially changed the accepted contract:

1. **Coverage-aware missing.** A response omission alone is insufficient for `missing_from_provider`. Missing may be inferred only after successful structurally valid fetch whose documented provider filter window actually covered the event's comparison key. This matters especially because T-Invest `GetDividends` filters by `record_date` while Hermes calendars by `payment_date`.
2. **Dividend identity excludes mutable lifecycle/type.** `dividend_type=Cancelled` is status-like evidence for the same stable identity, not a safe natural-key component.
3. **No payout-date invention.** Missing `coupon_date`/`payment_date` stays tentative rather than falling back to coupon-period end or computed business-day estimates.
4. **Separate write models, merged read model.** Provider applied payouts/revisions stay separate from owner manual expected flows, avoiding the existing manual unique/version contract.
5. **Manual reconciliation defaults fail-safe.** An unresolved duplicate does not silently double-count. Manual remains the default counting survivor until the owner explicitly chooses keep-both or provider-survivor reconciliation.
6. **Synthetic redemption remains probe-gated.** Bond reference flags/dates are useful evidence but do not prove a safe amortization schedule.

## Comparison summary

| Dimension | Grok 4.6 | DeepSeek V4 Pro | Gemini 3.7 Flash | GPT-5.6 Sol synthesis |
|---|---|---|---|---|
| Existing Hermes alignment | strongest | strong | medium | strong |
| Provider/API caution | strong but some overreach | strong | weakest | strongest after official-doc verification |
| Manual-data safety | strong | strong | medium | strongest/fail-safe |
| Identity design | strong coupon/redemption, dividend correction needed | medium | medium | accepted canonical |
| Quantity/audit semantics | strongest | strong | weaker dynamic approach | accepted frozen-apply model |
| C04 backward compatibility | strong | strongest | weaker product drift | accepted conservative model |
| Missing/cancellation semantics | strong | strong | strong conceptually | accepted with coverage-aware rule |
| Evidence discipline | strong | strong | weakest | official repo/API read-back |

## Canonical synthesis

The accepted ADR is not a majority vote and not a verbatim winner copy.

Approximate contribution to the final design:

- **Grok 4.6:** primary structural basis — separate provider tables, selected-month quantity freeze, preview/apply, T-Invest-specific practical detail.
- **DeepSeek V4 Pro:** C04 conservatism, refetch consistency, additive migration/backward-compatibility discipline.
- **Gemini 3.7 Flash:** broad cash-flow/passive-income framing, anti-vanishing emphasis and risk enumeration.
- **GPT-5.6 Sol synthesis:** coverage-aware missing, stricter identity rules, no invented payout dates, separate write/merged read model, stricter manual reconciliation and probe-gated synthetic redemption.

The normative result is ADR 0011. If this benchmark document and ADR disagree, ADR 0011 is authoritative.

## Important decisions selected for ADR 0011

- separate persisted provider payout/revision model; manual `expected_cash_flows` stays owner-managed;
- event identity: provider + `instrument_uid` + event kind + stable event-specific key;
- coupon number preferred identity; coupon-period pair is fallback; amount/payment date not identity;
- dividend `record_date` preferred identity when no validated stable provider event ID; mutable dividend type excluded;
- redemption uses validated `GetBondEvents` MTY identity; synthetic maturity fallback remains live-probe gated;
- payment date is canonical calendar date; no invented date from record date/coupon-period end;
- selected reporting-month position quantity drives preview and is frozen in each applied revision;
- provider omissions never auto-delete/cancel; `missing_from_provider` requires proven fetch coverage;
- preview is zero-write; selected apply refetches provider + local state and uses `preview_changed`;
- selected set applies atomically;
- manual duplicates require explicit owner resolution and default to manual-only counting while unresolved;
- provider coupons can feed existing C04 expected-coupon component; provider dividends remain calendar-only in formula v1; redemptions never count as passive income;
- full raw provider payloads are not persisted;
- all uncertain payout-method behavior is resolved by a dedicated read-only live probe before adapter/apply implementation.

## Provider documentation checked during synthesis

Current official T-Invest documentation was checked on 2026-08-16 for:

- `InstrumentsService/GetBondCoupons`: request range filters by `coupon_date`; Coupon includes payout date/number/fix date/per-unit payout/period fields.
- `InstrumentsService/GetDividends`: request range filters by `record_date`; Dividend includes per-security `dividend_net`, payment/declared/last-buy/record dates and dividend type including Cancelled/Return of Capital.
- `InstrumentsService/GetBondEvents`: event kinds include CPN/CALL/MTY/CONV and BondEvent exposes event number, dates and per-bond payout fields.
- bond reference fields include maturity/floating/perpetual/amortization flags.

These are documentation facts, not owner live-API observations. ADR 0011 deliberately keeps practical payload/reliability questions in R05-01.

## Next task

R05-01 is the first implementation-adjacent task: a **read-only T-Invest payout probe with sanitized public fixtures**, explicitly designed to close the provider unknowns before domain/persistence/apply code is allowed to harden assumptions.
