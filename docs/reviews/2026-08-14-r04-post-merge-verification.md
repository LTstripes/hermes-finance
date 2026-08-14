# R04 post-merge verification — 2026-08-14

## Verdict

**ACCEPT. Exact integrated `r04` is verified and R04-06 may be unblocked.**

This review verifies the combined integration state after R04-05D acceptance, stable maintenance M03-01..03, the `main → r04` forward merge, and documentation synchronization.

## Exact refs verified

- `origin/main = 1bf28bfdbec2c9c6d495a1de449bce2f541be13e`
- `origin/r04 = aa1368e56790c28fde49e70b577dffe814ea0226`
- `origin/main` is an ancestor of `origin/r04`.
- Verification used an isolated detached review worktree at exact `aa1368e...`.
- Persistent owner/Grok worktree and repository-root `.env` were not accessed.
- No live T-Invest probe or live network call was run during this verification.

## Integration invariants

Verified together:

- canonical host remains exactly `127.0.0.1`; `0.0.0.0`, `localhost`, and `::1` are rejected while port override remains valid;
- T-Invest repository-root absolute `.env` configuration remains cwd-independent;
- `HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN` remains `SecretStr`; blank value means missing and token values are absent from repr/str;
- T-Invest/provider-neutral market-data implementation and deterministic probe/fixture code remained present after the maintenance forward merge;
- MOEX remains disabled as a production fallback.

## Stable maintenance verification

### M03-01

PASS — Settings/CLI/startup/local-security enforce the exact loopback trust boundary.

### M03-02

PASS — `REALIZED_LOSS` requires strictly negative signed net value; zero/positive writes are rejected and IIS/passive-income regressions remain green.

### M03-03

PASS — canonical SALARY writes enforce one row while legacy duplicates remain readable/aggregated; atomic replace heals duplicates; rollback and closed-month guards hold; clone collapses recurring legacy duplicates deterministically; frontend aggregation remains exact and does not use float financial arithmetic.

## R04 market-data verification

PASS:

- provider-neutral identity and T-Invest `instrument_uid` semantics;
- mapping integrity / ISIN mismatch protections;
- UI provider-verification save path;
- malformed neighboring discovery candidate does not discard valid candidates;
- quote preview remains read-only and owner-triggered;
- deterministic T-Invest provider/probe tests without `--live`;
- historical as-of remains `price_date <= target_date`;
- exact Quotation `units+nano` and MoneyValue parsing;
- probe allowlist remains only `FindInstrument`, `GetInstrumentBy`, `BondBy`, `GetLastPrices`, `GetCandles`;
- Accounts/Operations/Orders/Sandbox/Transfer remain forbidden;
- no background/startup provider network.

## Verification results

- backend targeted integration matrix: **226 passed**;
- full backend: **732 passed**;
- Ruff check: pass;
- Ruff format check: pass;
- frontend targeted: **79 passed**; additional `instrumentMappings` and `quotePreview` tests also green in the full suite;
- full frontend: **220 passed / 40 files**;
- Biome lint: pass across 149 files;
- `tsc -b && vite build`: pass;
- `git diff --check`: pass;
- review worktree clean after checks.

### Known non-blocking tooling noise

Tree-wide Biome format check reports the established Windows CRLF normalization noise (`\r\n → \n`) across 148 files, including untouched configuration files. No AST/import-wrap format defect remained in the M03-03 touched frontend files.

`privacy_check.py` could not execute its internal `git -C` call because the isolated Windows worktree path contained Unicode characters. Equivalent repository checks verified 448 tracked files, only `.env.example` among tracked env-like files, `.env` ignored and absent from the review worktree, and clean porcelain state. This is a tooling/path limitation, not a privacy finding.

## Secret / remote safety

- `.env` accessed: **no**;
- token exposed: **no**;
- live network called: **no**;
- `main` unchanged during verification;
- `r04` unchanged during verification;
- no commit/push/merge was performed by the verifier.

## Gate decision

There are no correctness, security, financial, provider-contract, integration, or deterministic-test blockers remaining from the pre-R04-06 gates.

**R04-06 may start from the current canonical `r04` after the documentation-only unblock commit.**
