# R04 pre-apply independent architecture/correctness checkpoint

**Date:** 2026-08-14  
**Reviewed baseline:** `r04` @ `b8f50075cc1b91f2fae85003ab2b9a977984a5b6`  
**Audit mode:** read-only tracked-tree review; no code changes; no live provider calls; no `.env`, private DB, exports, backups or owner financial data inspected.  
**Independent reviewer:** Grok Build (exact model/effort not independently runtime-confirmed in the submitted report)  
**Finding verification:** ChatGPT — GPT-5.6 Sol

## Verdict

**READY WITH PRECONDITIONS** for R04-06.

No blocker exists in the current runtime because quote apply does not yet exist. Before external data can mutate `PositionSnapshot`, the mapping/apply boundary needs additional integrity and provenance guarantees.

## Confirmed findings

### R04-specific

1. **T-Invest accepted mapping verification gap.** A `t_invest` mapping can currently persist `provider + instrument_uid` without mandatory provider verification and without carrying candidate ISIN. This is acceptable for read-only preview but unsafe before apply. Moved into `R04-05C` and made a precondition for R04-06.
2. **Discovery partial-result hardening.** One malformed T-Invest discovery candidate should not discard already valid candidates when partial success is safe. Folded into R04-05C.
3. **Live contract confidence gap.** Deterministic tests use synthetic/mock payloads; a bounded owner-side read-only live probe against public market-data endpoints is required before R04-06 acceptance. Added as R04-05D.

### Stable-line findings already present in `main`

1. **M03-01 / loopback invariant.** Runtime host configuration can be overridden to a non-loopback address even though the no-auth security model assumes loopback-only operation.
2. **M03-02 / signed realized loss.** `realized_loss` can be persisted with positive signed net and then summed by IIS/dashboard as profit.
3. **M03-03 / multiple salary rows.** Frontend salary editing/display uses the first SALARY row while backend tax/cash calculations sum all SALARY rows.

These are not R04-only defects and must be fixed from `main`, then forward-ported `main → r04` after acceptance.

## R04-06 preconditions added by the checkpoint

- add a real `t_invest` `PriceSource` and migrate the DB constraint;
- persist immutable snapshot-scoped provider-neutral quote provenance;
- never reconstruct applied history from mutable current mapping;
- keep the existing editable-month guard authoritative;
- stale quote apply requires explicit per-row owner selection;
- production 0.4 apply is T-Invest only; no MOEX production fallback;
- frontend money is never authoritative; backend re-fetches/normalizes and recomputes metrics;
- add a preview/apply consistency guard: if the refreshed server quote differs from the approved preview, return deterministic conflict/`preview_changed` and require a new preview;
- apply the selected set atomically in one top-level transaction; do not loop through the existing per-row `update_position_snapshot()` commits;
- preserve NKD unchanged;
- complete R04-05D live read-only probe before R04-06 acceptance.

## Documentation impact

The checkpoint also confirmed that the old `docs/releases/0.4.0.md` had drifted behind the actual `r04` implementation and still described earlier MOEX-primary statuses. The canonical backlog was synchronized immediately after the audit.

## Resulting sequence

```text
R04-05C mapping integrity hardening
  → R04-05D owner read-only T-Invest live probe
  → R04-06 selective apply + immutable provenance
  → R04-07 polish
  → R04-08 regression/Windows/network smoke
  → R04-09 release gate
```

Stable maintenance can proceed separately on `main` (`M03-01`, `M03-02`, then `M03-03`) and be forward-merged into `r04` after acceptance.

## References

- `docs/releases/0.4.0.md`
- `docs/adr/0009-moex-market-identity-and-quote-semantics.md`
- `docs/adr/0010-market-and-broker-provider-strategy.md`
- `docs/t-invest-market-data.md`
- `docs/EXECUTION_HISTORY.md`
