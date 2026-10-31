# Hermes Finance 1.9.0

This release brings the available-history Returns workspace and the canonical
AI review into one guarded local release. Current publication, installation and
Owner acceptance evidence belongs to [CURRENT_STATUS](CURRENT_STATUS.md).

- Returns opens a compact overview for all selected brokerage accounts and
  sold instruments, with supported results, contribution charts, search and
  leaders. Changing accounts selects that account's own available history.
  Account display labels do not rename financial facts or infer mappings.
- Each instrument has its own page from Returns and Capital, with supported
  results, paid income, exact components, concise native trades and Back context.
  Coupons and dividends load details on demand and are not added twice to P&L.
- Leaders use equal-width groups and explicit rank/name/amount columns; amounts
  stay right-aligned without wrapping, and narrower desktops stack the groups.
- Settings groups the existing data, source, export/copy and application tools;
  the sidebar stays visible with its own scroll. Capital embeds allocation and
  concentration and removes duplicate panels. Home graphs gain RUB axes; Income
  omits the duplicate embedded forecast/goals panels without removing their data.
- The recommended AI download explicitly requests strict format2.0. Repeated
  source metadata, endpoints, result states and event payloads are stored once
  with typed references. Ordered occurrences preserve account/period context,
  multiplicity, NULL/zero, provenance and revision differences. The v1.5 API
  default and legacy schemas remain compatible. No second calculator is added.
- Gold uses the existing dated snapshot and a bounded, preview/confirm manual
  history source inside its instrument. Unknown fees, incomplete declarations
  and unprovided taxes retain their limits. This release does not create Owner
  history entries, reinterpret a valuation as a sale or rewrite CLOSED months.

Schema0068 adds the three bounded manual-gold source tables; existing financial
rows and CLOSED history are preserved. Deposit-statement import remains separate.
Results across different periods do not imply a common portfolio percentage.
Full AI generation remains a complete read-only review; no new latency claim is
made by the representation change.

Use the existing backup-first [O3](OWNER_RUNTIME_OPERATIONS.md#o3) workflow with
an exact published release and its verified code/database recovery pair. After
backend changes, investment proofs require a fresh Preview of the same originals
and explicit replacement confirmation through the existing host. Never rehash an
old proof or reimport financial operations to refresh it. Verify ordinary readers
after Reload. Financial Apply/Close and actual gold Save remain separate actions.
Failed or uncertain operations require readback; no automatic database overwrite
or downgrade is authorized.
