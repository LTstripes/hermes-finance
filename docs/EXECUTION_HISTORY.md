# Hermes Finance — execution history

> **Purpose:** durable human-readable history of how Hermes Finance was built: which agent/model/tool implemented each accepted task, who reviewed it, which candidate was selected, what blockers/iterations mattered, and which exact commit entered the integration line.
>
> This file is **not** a specification or release backlog. Business semantics remain in `MASTER_SPEC.md` and accepted ADRs; task scope/status remains in active release docs; product-facing release notes remain in `CHANGELOG.md`.

## Recording policy

After a task is **accepted and integrated** into its target branch, the accepting reviewer/integrator appends one execution record here. The implementation worker supplies completion evidence but does not self-accept its historical verdict.

Preserve when applicable:

- release/task ID and acceptance date;
- implementation agent/tool and exact model only when runtime-confirmed;
- reviewer/acceptor;
- baseline ref/SHA;
- candidate branch and exact accepted HEAD;
- target branch and exact integrated HEAD;
- meaningful verification performed;
- material blockers/follow-ups;
- short decision rationale and historically relevant limitations.

### A/B or multi-agent comparison

Keep **all candidates**, including rejected ones. Record each candidate's agent/model/tool, branch/HEAD, checks, strongest points and material weaknesses, then record the selected candidate and evidence-based selection reason. Do not let blind-comparison candidates inspect/copy each other's work before the comparison is settled unless the owner explicitly ends the blind phase.

## Evidence rules

- Prefer exact Git refs/SHAs and verified CI/read-back over prose claims.
- Worker completion reports are context, not proof.
- Never fabricate model identity. If it is not runtime-confirmed, record the agent/tool and mark the model unknown/not independently confirmed.
- Do not put private financial values, DB/seed/export contents, credentials, private payloads or owner screenshots containing personal values here.
- Deep technical rationale belongs in ADRs/task cards; this file captures **who/how/why selected**.

---

# 0.4.x development

### 0.4.0 / R04-00 — parallel release line + active backlog setup

- **Accepted:** 2026-08-13
- **Implemented by:** ChatGPT — GPT-5.6 Sol
- **Reviewer/acceptor:** owner scope approval + ChatGPT repository read-back
- **Baseline:** `main` @ `b385e8cddfaa8e057dc34dc73a11d0bc839978d1`
- **Resulting setup commit:** `fa3a470668f8f2c3e8d0f321d520d0d86aeba955`
- **Verification:** remote refs read back; `main` remained unchanged.
- **Decision notes:** established stable `main` (`0.3.x`) and long-lived `r04` development lines with accepted stable fixes forward-ported `main → r04`.
- **References:** `docs/releases/0.4.0.md`

### 0.4.0 / R04-01 — MOEX market identity + quote semantics contract

- **Accepted:** 2026-08-13
- **Implemented by:** ChatGPT — GPT-5.6 Sol
- **Reviewer/acceptor:** owner-authorized contract work + ChatGPT repository/source verification
- **Baseline:** `r04` after R04-00
- **Contract commit:** `d8fcf10231590dedd4fc4f484612ecf20dbb1f9c`
- **Backlog/unblock commit / integrated state:** `r04` @ `1c2e2f5b1d757e9697126ce9206a2768a570be2a`
- **Verification:** ADR/backlog and exact refs read back; stable `main` stayed unchanged.
- **Iterations/blockers:** MOEX data-usage terms were identified as an apply/release gate rather than silently assumed.
- **Decision notes:** fixed board-aware MOEX identity, target-date/as-of semantics, freshness, bond percent-of-face conversion, manual fallback and no-background-refresh contract before implementation.
- **References:** ADR 0009, `docs/releases/0.4.0.md`

### 0.4.0 / R04-02 — read-only MOEX ISS provider client (A/B)

- **Accepted:** 2026-08-13
- **Reviewer/acceptor:** ChatGPT — GPT-5.6 Sol
- **Baseline:** `r04` @ `1c2e2f5b1d757e9697126ce9206a2768a570be2a`

#### Candidates

- **Hermes/Grok — Grok 4.6:** `r04-02-grok` @ `073e343ab6ffd5e9d4e24bd6c77dd3c808fe4ce3`; initial `0a566e39e76517f01401289663b14e8ba1cbc0d8`, follow-ups `ff44f62dcb83e6d60ba83b0320b8210b9a4f268a` and `073e343...`. Worker-reported final verification: targeted market-data `25 passed`, full backend `605 passed`, Ruff check/format and `git diff --check` clean. Strong points: provider boundary, project money/domain reuse, discovery, Decimal-preserving parsing, board-aware filtering, current-day/historical semantics. Follow-ups fixed current-session `price_date`, SUR/RUR compatibility, false ambiguity and bond currency/FACEUNIT checks.
- **OpenAI Codex — model unknown/not recorded:** `r04-02-codex` @ `acc42add6f6b035d3ca0fd75bf15df801c5ff787`. Worker-reported targeted `13 passed`, full backend `593 passed`, Ruff/diff/privacy clean. Strong point: bounded parallel batch and no added runtime HTTP dependency. Reviewer found weaker ADR alignment: exact-security lookup for free-text discovery, provider-specific identity overloading, false-ambiguity risk, legacy RUB-unit rejection and documented shares payload/date mismatch risk.

- **Selected candidate:** Hermes/Grok — Grok 4.6 @ `073e343ab6ffd5e9d4e24bd6c77dd3c808fe4ce3`.
- **Integrated into:** `r04` @ the same accepted HEAD by fast-forward; later commits advanced the integration line.
- **Selection reason:** better contract alignment, provider-boundary architecture, domain reuse and lower follow-on integration risk outweighed Codex's stronger isolated batch implementation.
- **Known limitation:** direct MOEX production use remained gated; the adapter stayed valid technical/reference work.
- **References:** ADR 0009, `docs/releases/0.4.0.md`

### 0.4.0 / R04-03 — instrument market mapping storage/API

- **Accepted:** 2026-08-13
- **Implemented by:** Hermes/Grok — Grok 4.6
- **Reviewer/acceptor:** ChatGPT — GPT-5.6 Sol
- **Baseline:** `r04` @ `86d2033de5cb0572a2f9086464ab0145a51950f0`
- **Candidate / integrated implementation:** `r04-03-grok` @ `4e35e7328d670466ac7f94fdbef7b928dcdffe9f`
- **Verification:** reviewer inspected schema/constraints, state machine, API/provider verification, historical-snapshot safety and ancestry. Worker-reported targeted mapping/API/migration/startup `35 passed`, full backend `633 passed`, Ruff/format/diff/migration/privacy checks passed.
- **Iterations/blockers:** none after implementation review.
- **Decision notes:** explicit `unmapped / mapped / excluded`; legacy `moex_secid` stays discovery hint and is never promoted silently. Reference mapping edits do not rewrite historical snapshots.
- **References:** ADR 0009, release backlog.

### 0.4.0 / R04-04 — quote refresh preview API

- **Accepted:** 2026-08-13
- **Implemented by:** Hermes/Grok — Grok 4.6
- **Reviewer/acceptor:** ChatGPT — GPT-5.6 Sol
- **Baseline:** `r04` @ `300e58844ea8f093e5b31a819ac878801e95c899`
- **Candidate:** `r04-04-grok` @ `e29cf5c0009d4be9febbeb865528d04175a162ba`; initial `2aa54bc4c046d8afd15c981ef2af3432dc9b5930`.
- **Integrated into:** `r04` via PR #23, merge commit `de47dedf4514ef28816c56a750d985fb1c38ffa5`.
- **Verification:** reviewer inspected target-date, stale/closed-month semantics, provider-neutral handling, partial success, accepted mappings and zero-write preview. Worker-reported final targeted preview + R04-02/03 `68 passed`, full backend `649 passed`, Ruff/format/diff/privacy passed.
- **Iterations/blockers:** initial code converted unexpected provider/programming exceptions to `network_error`; follow-up removed the generic fallback so unexpected failures surface as server/provider-contract failures.
- **Decision notes:** explicit owner-triggered read-only preview; stale visible but not apply-eligible by default; closed month preview allowed but apply forbidden.
- **References:** ADR 0009, release backlog, PR #23.

### 0.4.0 / R04-05 — mapping + quote refresh preview UI

- **Accepted:** 2026-08-13
- **Implemented by:** Hermes/Grok — Grok 4.6
- **Reviewer/acceptor:** ChatGPT — GPT-5.6 Sol
- **Baseline:** `r04` @ `52ccad0f378bc5350619282404c68531ceea577e`
- **Candidate:** `r04-05-grok` @ `75935451dea4d1b3cd0f295f126591d030e776fe`; initial `ed297ad0026172a3eb1cd54d337765b152bfd3b8`.
- **Integrated into:** `r04` @ accepted HEAD by fast-forward; later history/docs commits advanced the branch.
- **Verification:** reviewer inspected explicit-only preview invocation, mapping states/actions, stale/closed/manual presentation and absence of apply. Worker-reported final AccountsPage tests `10/10`, full frontend `207/207`, lint, touched-file format, `tsc -b && vite build`, diff/privacy checks passed.
- **Iterations/blockers:** mapping GET failure initially rendered false `unmapped`; follow-up made mapping load atomic with instrument load and used visible error/retry instead.
- **Decision notes:** mapping management stays in Instruments workflow; quote preview stays explicit in monthly positions. No auto-map/apply/background refresh.
- **References:** ADR 0009, release backlog.

### 0.4.0 / provider strategy checkpoint — ADR 0010

- **Accepted:** 2026-08-13
- **Authored/researched by:** ChatGPT — GPT-5.6 Sol with owner decision
- **Strategy commit:** `83ae29a6fab40516378251e40b1d6171aac159eb`
- **Decision:** T-Invest becomes production market-data provider for 0.4; MOEX ISS remains reference/technical adapter because current MOEX materials did not establish the intended automated private workflow without applicable agreement. Alfa PRO remains future broker-portfolio candidate.
- **Architecture impact:** market data and broker holdings are separate bounded contexts; T-Invest canonical identity is `instrument_uid`; old MOEX-shaped canonical identity must become provider-neutral before T-Invest implementation.
- **References:** ADR 0010, issue #24.

### 0.4.0 / R04-05A — provider-neutral market identity refactor

- **Accepted:** 2026-08-13
- **Implemented by:** Hermes/Grok — Grok 4.6
- **Reviewer/acceptor:** ChatGPT — GPT-5.6 Sol
- **Baseline:** `r04` @ `83ae29a6fab40516378251e40b1d6171aac159eb`
- **Candidate:** `r04-05a-grok` @ `72d2dd461ae97fb3937de2dca620e7d88b104f96`
- **Integrated into:** `r04` @ the same accepted HEAD by owner-authorized non-force fast-forward after direct integrator mutations were safety-blocked.
- **Verification:** reviewer inspected provider-neutral DTO/storage, strict MOEX codec, mapping/verify path, preview deduplication, frontend conversion and migration safety. Worker-reported full backend `660 passed`, full frontend `209 passed` across 40 files, Ruff check/format, frontend lint, `tsc -b && vite build`, diff/privacy checks passed. Whole-checkout Biome remained noisy from Windows CRLF; touched-file checks were green.
- **Iterations/blockers:** no code blocker after review; integration itself required a narrow follow-up due connector mutation safety.
- **Decision notes:** canonical identity became `provider + provider_instrument_id + optional provider_venue_id`; MOEX engine/market/boardid/secid moved behind codec. Existing MOEX mappings migrate deterministically; excluded state preserved; no fabricated T-Invest mapping.
- **References:** ADR 0009, ADR 0010.

### 0.4.0 / R04-05B — T-Invest read-only production market-data provider

- **Accepted:** 2026-08-13
- **Implemented by:** Hermes/Grok — Grok 4.6
- **Reviewer/acceptor:** ChatGPT — GPT-5.6 Sol
- **Baseline:** `r04` @ `6cb33f92cfa7bb2842b7b639575eea9b9776b8cf`
- **Candidate:** `r04-05b-grok` @ `b8f50075cc1b91f2fae85003ab2b9a977984a5b6`; initial implementation `93095da7a9b99e0e4bccf67b09c4be5f54b71821`, accepted follow-up `b8f50075...`.
- **Integrated into:** `r04` @ `b8f50075cc1b91f2fae85003ab2b9a977984a5b6`.
- **Verification:** accepting review plus the later independent pre-apply audit re-inspected the exact final implementation. Confirmed read-only Instruments/MarketData-only surface, no account/order/cancel/transfer/operations methods, exact Quotation/MoneyValue parsing, target-date/freshness/bond semantics, root `.env` `SecretStr`, no startup/background requests and no silent MOEX production fallback. Exact worker test counts for this record were not independently preserved here and are therefore not invented.
- **Iterations/blockers:** follow-up fixed repository-root `.env` loading independent of cwd, HTTP 408 normalization to `network_error`, and official candle-source field handling.
- **Decision notes:** T-Invest is the selected production market-data provider under ADR 0010; MOEX remains reference adapter. Apply/provenance was intentionally not started.
- **References:** ADR 0010, `docs/t-invest-market-data.md`.

### 0.4.0 / R04-AUDIT-01 — independent pre-apply architecture/correctness checkpoint

- **Reviewed:** 2026-08-14
- **Performed by:** Grok Build — owner described the session as `3.6 / xhigh`; exact model/effort was not independently runtime-confirmed in the submitted audit report
- **Finding verifier:** ChatGPT — GPT-5.6 Sol
- **Baseline:** `r04` @ `b8f50075cc1b91f2fae85003ab2b9a977984a5b6`
- **Mode:** read-only tracked-tree audit; tests inspected but not executed; no live external network; no `.env`, private DB, exports/backups or owner financial data read.
- **Verdict:** `READY WITH PRECONDITIONS` for R04-06; no blocker in current runtime because quote apply does not exist yet.
- **Confirmed findings:**
  - stable `main` + `r04`: `realized_loss` can persist positive signed net and then increase IIS/dashboard result;
  - stable `main` + `r04`: salary UI edits/displays first SALARY row while backend sums all SALARY rows;
  - R04-specific: T-Invest accepted mapping can persist UID without mandatory candidate ISIN/provider verification, unsafe before apply;
  - stable `main` + `r04`: host config can bind non-loopback despite the no-auth loopback trust model;
  - R04 hardening: one malformed T-Invest discovery candidate should not discard already valid candidates when partial success is safe.
- **Verification of findings:** ChatGPT independently reopened the relevant live `main`/`r04` services, frontend helpers, API mapping path, Settings/CLI/security middleware and position price-source schema. M1–M4 were confirmed; the audit itself did not run tests, so no test execution is attributed to this checkpoint.
- **Plan impact:** inserted `R04-05C` mapping-integrity hardening and `R04-05D` live read-only T-Invest probe before R04-06; queued `M03-01..03` on stable `main`; tightened R04-06 with real `t_invest` PriceSource, immutable provider-neutral provenance, preview/apply consistency conflict guard and atomic selected-set transaction.
- **Documentation impact:** stale 0.4 backlog was synchronized to actual T-Invest/provider-neutral state immediately after review.
- **References:** `docs/reviews/2026-08-14-r04-pre-apply-audit.md`, `docs/releases/0.4.0.md`, ADR 0010.

---

## Historical backfill

Pre-R04 attribution remains available across Git history, `docs/HERMES_TASKS.md`, release backlogs, owner-review/follow-up docs, ADRs and `CHANGELOG.md`.

Do not invent missing executor/model attribution during backfill. A later documentation-only pass may reconstruct older releases from verifiable records if the owner wants a complete project-history article dataset.
