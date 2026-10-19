# Hermes Finance — Integrator session closeout, 2026-10-12

**Dated sanitized handoff, not a substitute for live GitHub.** First verify canonical `main`, open PRs/issues, latest Integrator comments and exact CI. Current maintained state is [CURRENT_STATUS](CURRENT_STATUS.md); relevant source-month contract is [BROKER_MONTHS](BROKER_MONTHS.md). Real Owner original documents, account/mapping identities, RUB amounts, source hashes, local SQLite path, screenshots and other private evidence stay in the authorized local report, **not** in Git/CI.

## Canonical code and acceptance

- Last verified finance-code `main@d4ff5ea1d1500117d4b57ba348c09fa5452330bc`. [#804 / PR #805](https://github.com/LTstripes/hermes-finance/pull/805) **Integrator CODE ACCEPT / guarded squash merged**, [exact post-main CI 38301062183](https://github.com/LTstripes/hermes-finance/actions/runs/38301062183) **COMPLETED SUCCESS** (14 applicable jobs, 3 path/fast-path skips). [#804 technical issue](https://github.com/LTstripes/hermes-finance/issues/804#issuecomment-6131771499) CLOSED.
- **#804 invariant**: original-bound, strict namespace/grammar+identity+Money/quantity/cash control validations allow only proved **nonidentity** XML side branches to become explicit exceptions on *incomplete DRAFT*. Every Transfers/UFSR descendant uses XML-whitespace-only guards; S1 warnings, frozen receipts, distinct native events, Close blockers and exact performance quality remain unchanged. No default-ignore of unsupported financial events.
- Release last confirmed **v1.2.0**, not automatically updated with post-release code. Protected Owner canonical DB, Test, Stable and historical CLOSED September **untouched** by this session's broker UAT.

## Real September source-first pilot — bounded Owner-local PASS

The former [#787 source-original Gate 0](https://github.com/LTstripes/hermes-finance/issues/787) STOP was resolved **for incomplete-DRAFT UAT** after #804. Owner authorized new isolated scratch and later the bounded current source-month Apply/GET/desktop stages. Actual evidence is operator-attested in private reports, **not directly inspected on the laptop by Integrator**:

1. Original unmodified September MyBroker XML → actual zero-write API Preview; `can_apply=true`, `conflicts=[]`, six financial/source warnings retained.
2. One true atomic **incomplete DRAFT** Apply → independent GET matching original and Preview; 11 confirmed source securities (6 equities/5 bonds), 13 effective metadata/mappings, separate RUB cash and source-native values; all 11 quantity residuals and signed cash residual zero. Eight canonical trades; one source-month import/receipt; no duplicative payout, external flows or cash.
3. Same-intent replay `duplicate=true` with unchanged DB/sidecars, integrity OK, no FK failures or protected-data modifications.
4. Scratch-only ordinary account PATCH: `include_in_capital=true`, `include_in_returns=false`. Monthly-summary GET now matches the source-owned total. **Returns membership/exact/indicative readiness not implied**.
5. Windows desktop UAT: read-only local runtime, actual page reload and visual confirmation of source positions/cash, September **DRAFT**, six visible source exceptions in expanded details and disabled **Close**. Temporary URL navigation/tool blocker was recovered. Integrator **did not personally open screenshot pixels**.

References: [real Apply/GET operator checkpoint](https://github.com/LTstripes/hermes-finance/issues/773#issuecomment-6132341689), [Integrator bounded ACCEPT](https://github.com/LTstripes/hermes-finance/issues/773#issuecomment-6132409052), [stage-3 account API](https://github.com/LTstripes/hermes-finance/issues/773#issuecomment-6132678182), [final desktop PASS](https://github.com/LTstripes/hermes-finance/issues/773#issuecomment-6132814727), [parent #768 product milestone](https://github.com/LTstripes/hermes-finance/issues/768#issuecomment-6132820336).

**Boundaries STILL BLOCKED:** `4_Transfers_unsupported`, `5_UFSR_unsupported`, `commission_basis_unresolved`, `money_semantics_unsupported`, `settlement_principal_unresolved`, `unparsed_source_rows`; `bookkeeping_ready=false`, `coverage_state=unknown`, `can_close=false`. No Close/Reopen, source Money/H2/fee/NKD/tax attestation, protected deployment, exact XIRR/TWRR or portfolio-complete claim. #773 and product #768 remain **OPEN** because full selected-account Close is not source-proven.

## Next lane #774 — Worker outcome to be brought in next session

- [#774 separate indicative broker return](https://github.com/LTstripes/hermes-finance/issues/774) has [Integrator **PARALLEL CODE GO**](https://github.com/LTstripes/hermes-finance/issues/774#issuecomment-6132724218), **no PR/code acceptance yet at this checkpoint**. #773 fresh desktop has passed, so no shared runtime/UI ownership is necessary. First new-session action: independently inspect live #774 delivery (branch/PR, exact candidate SHA/diff, CI, independent financial/source review); do not assume accepted just because Worker reports green.
- Frozen direction: **read-only `BrokerStatementReturn`** with two broker-native whole-account EOD values and separate RUB cash; exact dated **account-boundary** external crossings, source identity/membership and financial coverage; Decimal/ACT365 *nonannualized period MWR*, separate API/desktop UI/export and `status=indicative|unavailable`, `rate_fraction: Decimal-string|null`. Explicit bond **NKD UNKNOWN** warning may permit provisional rating **only if all other evidence gates pass**.
- Synthetic acceptance covers 2.01% midpoint inflow, 0%, 2.8% internal coupon/fee, loss/negative, nonunique/no root, stale sources/overlaps, incomplete flow coverage, material REPO/UFSR and unit/annualization parity. If real September boundary/member/custody evidence remains incomplete, output actual known endpoint values plus **null rate and specific blockers**: no invented external flow=0 or false positive return.
- **Never relax existing exact XIRR/TWRR/historical fallback, add another ledger, reimport private originals or modify source DRAFT to calculate a rate.** Separate task [#767](https://github.com/LTstripes/hermes-finance/issues/767) still tracks clean/dirty/EOD bond NKD basis for exact economic performance.

## Other next steps / product backlog

- Desktop-only small UX improvement: explicitly labelled **read-only DRAFT account portfolio/capital preview**, without converting into latest-CLOSED Capital; clearer labels for six blockers (currently details reveal exact cause). It is not a blocker for the already accepted import/desktop workflow. Avoid UI edits racing #774.
- [#793](https://github.com/LTstripes/hermes-finance/issues/793) daily Money source formula, [#790](https://github.com/LTstripes/hermes-finance/issues/790) independent real stock fee basis, opaque UFSR/REPO, full Money ownership and eventual source-backed Close remain open **source-evidence** work; do not insist on broker field perfection simply to keep DRAFT useful.
- [#769](https://github.com/LTstripes/hermes-finance/issues/769) historical backfill, [#749](https://github.com/LTstripes/hermes-finance/issues/749) exact returns and protected release/UAT are separate. Open [PR #744](https://github.com/LTstripes/hermes-finance/pull/744) remains unrelated.
- Worker prompts short, scope+guardrails+AC, task complexity and suggested model/effort. No mobile work, no benchmark/model telemetry.

**Next Integrator session must trust live GitHub over this snapshot, then process the Owner's #774 handoff.**
