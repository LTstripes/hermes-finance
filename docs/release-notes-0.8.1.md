# Hermes Finance 0.8.1

Hermes Finance 0.8.1 is a maintenance release on top of the published 0.8.0 state. It documents already integrated owner-workflow, launcher, data-quality and verification improvements without adding a new product line or changing financial formulas.

## Included maintenance

- **Launcher owner workflow (#277–#279):** explicit launcher-owned Preview update from canonical `main`, one-click dependency preparation/repair, clearer Stable/Preview identity, and one actionable primary state for the owner. Normal Start remains offline and does not silently download or mutate Git.
- **Launcher presentation (#284):** desktop layout, spacing, readability and responsive behavior improvements without safety-semantic changes.
- **AI/export fact quality (#285):** clearer calculated-versus-actual salary semantics, valuation freshness separated from position completeness, explicit missing-history and active-account/no-snapshot states, warning deduplication, IIS coverage, and additive AI Analysis Bundle schema `1.1.0` while preserving the frozen portfolio-review package `1.0.0`.
- **Safe workspace cleanup (#280):** repository-owned cleanup tooling that fails closed for dirty, unknown, launcher-linked or private-data paths and keeps Stable/Preview/runtime data protected.
- **Verification infrastructure (#282, #292):** canonical backend pytest lanes with slow-test telemetry and a deterministic quote-freshness regression test with a pinned clock. These are verification improvements, not user financial features.

## Safety and boundaries

- Hermes Finance remains a local, single-user, Windows-first application listening only on `127.0.0.1:8000`.
- There is no cloud, authentication, telemetry, trading, provider write operation, automatic upload or background provider refresh.
- Provider, network and file-processing actions remain explicit owner actions.
- Closed months remain immutable until an explicit Reopen.
- Unknown or unavailable financial evidence is not silently converted to zero.
- The canonical Alembic head remains `0036_broker_baseline_provenance`; this maintenance release adds no migration and changes no schema semantics.
- Private Stable/Preview/runtime databases, `.env` files, exports/PDFs, backups and provider credentials are never part of release preparation.
