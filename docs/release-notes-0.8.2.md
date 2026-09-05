# Hermes Finance 0.8.2

Hermes Finance 0.8.2 is a maintenance release-prep candidate after the published Stable `v0.8.1` release. It documents already integrated owner-workflow, launcher and deterministic-analysis improvements without adding a new product line or changing financial formulas.

## Included maintenance

- **Launcher Stable lifecycle (#298, #299):** owner-safe Stable release update discovery and upgrade path, restart-safe launcher process ownership, and reliable Stop recovery while preserving Stable/Preview separation and explicit owner actions.
- **Launcher presentation (#302):** final owner-facing visual and content polish, including canonical Stable/Preview identity presentation.
- **Tax/IIS Planner Lite (#142):** current-state backend and owner UI for existing tax and IIS data; no implicit year-end projection or expanded projection scope.
- **Deterministic Insights and AI Analysis Bundle (#143):** Deterministic Financial Insights Engine v1 is integrated with the additive AI Analysis Bundle schema `1.2.0`, backed by persisted evidence and without LLM/cloud calls or formula duplication; the dedicated Insights UI remains deferred.

## Safety and boundaries

- Hermes Finance remains a local, single-user, Windows-first application listening only on `127.0.0.1:8000`.
- There is no cloud, authentication, telemetry, trading, provider write operation, automatic upload or background provider refresh.
- Provider, network and file-processing actions remain explicit owner actions.
- Closed months remain immutable until an explicit Reopen.
- Unknown or unavailable financial evidence is not silently converted to zero.
- The canonical Alembic head remains `0036_broker_baseline_provenance`; this maintenance release adds no migration and changes no schema semantics.
- Private Stable/Preview/runtime databases, `.env` files, exports/PDFs, backups and provider credentials are never part of release preparation.
- #308 is a known non-blocking cosmetic follow-up and is not required for v0.8.2 release-prep.
