# Hermes Finance 1.2.0

Hermes Finance 1.2.0 packages the accepted post-1.1.0 owner-workflow improvements, runtime cleanup and CI/test maintenance into one immutable local release. Release preparation changes version/package identity and documentation only; the product changes below were already integrated and verified on canonical main.

## Owner workflow and monthly operations

- Month navigation and close/review actions preserve exact-month identity, with one clearer primary month entry and truthful latest/older report routing.
- Future payouts use collapsed instrument groups with individual and selected bulk Apply while preserving per-group atomicity and no blind retry after ambiguous submissions.
- Provider mapping/reconciliation surfaces show clearer provenance, saved/freshness state and exception-first handling.
- Money/debt/link editing and linked-account/debt explanations are clearer without changing canonical financial formulas.
- Explicit Preview → Apply → authoritative reread remains the write boundary for provider-backed operations.

## Quotes, providers and known Alfa limitation

- Same-day quote Preview uses server-owned evidence rather than trusting browser-supplied money; Apply remains fail-closed on stale or mismatched evidence.
- Alfa mapping/reconciliation UX is improved, but build 5.26.6.594 introduced a new Trading core/token surface whose public token/handshake contract is not yet established.
- Owner live evidence shows the Trading core can be switched Online on port 3366 and a read-only token can be issued, while current Hermes can still reject the resulting traffic as an unrecognized protocol. This remains tracked in #646 and is not claimed fixed by this release.
- Manual input remains an explicit fallback; unavailable provider evidence is never presented as successful reconciliation.

## Performance and financial correctness

- Portfolio/account Performance Phase A remains available with XIRR/TWRR diagnostics, supported preparation actions and honest metric-specific unavailable states.
- Existing data-integrity hardening preserves coherent reads, atomic Close/evidence boundaries, correction invalidation, exact coverage/provenance and the distinction between unknown and zero.
- Asset-class XIRR/TWRR is intentionally outside this release. #534 accepted BLOCK ON EVIDENCE; #535/#540 remain deferred until the required historical class identity and class-boundary evidence exist.

## Runtime, recovery and maintenance

- The Windows Launcher shell/package/tests/jobs are retired. Direct Prepare/Validate/Start is now the supported Owner runtime path.
- Backup-first immutable Stable update, Windows production smoke, protected recovery/rehearsal boundaries and direct-operations runtime inventory protections remain.
- The completed Owner filesystem migration and workspace janitor preserve Stable/Main/Test/Owner and the separate active Ops installation.

## CI/test maintenance

- Superseded ordinary PR CI cancels safely without cancelling canonical main/release/protected integration work.
- Duplicate visual executions are reduced while unique viewport/scenario coverage remains.
- Overlapping visual CI is omitted only when exact tree identity is proven.
- Safe docs-only PRs use a fail-closed fast path; canonical main and release gates remain full.

## Owner decision and operating boundary

The Owner explicitly authorized v1.2.0 publication after the accepted development work and green canonical verification, choosing several days of ordinary Stable use as the next real-history validation path instead of repeating the prepared focused Test route before the Alfa PRO investigation settles. This does not claim Alfa compatibility, universal real-history XIRR/TWRR availability or asset-class returns.

Before updating the working installation, stop the owned Hermes runtime and use the supported backup-first Stable update operation for version 1.2.0. The updater validates the published annotated release, creates a verified SQLite backup before changing code, prepares and validates that exact checkout, and does not start the application. Start remains explicit.

The previous interface remains available at /v1. Hermes remains local-only, single-user, Windows-first and normally bound to 127.0.0.1:8000, without cloud accounts, telemetry, trading or background provider refresh.

Not included: /v1 retirement, asset-class returns #535/#540, representative synthetic stand #630, or dashboard composer #389.

Source/evidence: #554; #662; #667/#674; #668–#671; #629/#689; docs/CURRENT_STATUS.md; docs/history/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-10-04.md; docs/OWNER_RUNTIME_OPERATIONS.md.
