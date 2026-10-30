# Hermes Finance 1.8.1

This bounded return-calculation correction retains the existing XML/PDF import,
source-proof host, ledger and schema `0067_investment_report_proofs`.
Current publication and installation evidence belongs to
[CURRENT_STATUS](CURRENT_STATUS.md).

- XIRR certifies the number of distinct positive roots instead of refusing every
  history with repeated contribution/receipt sign changes. Exact integer
  subdivision and a rational validation bracket retain multiple-root and
  numerical-limit refusals. A fully certified rational tangent is supported;
  an unresolved root is never selected or replaced with zero. Period return and
  annualized XIRR keep their existing ACT/365 meaning.
- An explicitly observed zero position quantity supports a missing zero value at
  the same boundary independently of account inception. Missing quantity and
  contradictory nonzero values still withhold the complete result.
- Malformed PDF rows retain a uniquely recognized ISIN. Unknown-scope faults
  remain account-wide; the typed RUB cash row is recognized separately from a
  security row. A malformed amount cannot prove an XML payout identity.
- Known XML coupons/dividends remain visible in Returns independently of missing
  valuation. Coverage follows metric dependencies; genuinely incomplete values
  remain partial or NULL. Source-proved events expose effective ISIN and actual
  net payout without fabricating a legacy link, gross amount or tax allocation.

Update through the existing backup-first [O3](OWNER_RUNTIME_OPERATIONS.md#o3)
workflow with exact-main CI and guarded publication. No schema migration is added.
Retain a verified backup and its producing code before updating Stable.
Backend changes retire existing investment proofs: create a fresh Preview of the
same originals, review its comparison and explicitly confirm replacement proofs.
Never update an old proof hash in place. This confirmation does not reimport
financial operations, Apply/Close a month or rewrite CLOSED history. After Save,
check the ordinary readers in a new process and the UI after Reload. Failed or
uncertain operations require readback before retry; no automatic downgrade or
database overwrite is authorized.
