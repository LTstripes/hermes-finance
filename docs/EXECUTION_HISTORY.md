# Hermes Finance — execution history

> **Purpose:** durable human-readable history of how Hermes Finance was built: which agent/model/tool implemented each accepted task, who reviewed it, which candidate was selected, what blockers/iterations mattered, and which exact commit entered the integration line.
>
> This file is **not** a specification or release backlog. Business semantics remain in `MASTER_SPEC.md` and accepted ADRs; task scope/status remains in active release docs; product-facing changes remain in `CHANGELOG.md`.

## Recording policy

After a task is **accepted and integrated** into its target branch, the accepting reviewer/integrator appends one execution record here.

The implementation worker must provide enough factual data in its canonical completion report, but it does **not** decide its own acceptance record.

For every accepted task record, preserve when applicable:

- release and task ID;
- calendar date of acceptance/integration;
- implementation agent/tool and exact model when runtime-confirmed;
- reviewer / accepting agent;
- baseline ref/SHA;
- candidate branch and exact accepted HEAD;
- target branch and exact integrated HEAD;
- meaningful verification performed (tests, CI, Windows smoke, migration/runtime checks, etc.);
- blocker/follow-up iterations that materially changed the result;
- short rationale for important implementation/architecture choices;
- deviations or known limitations that matter historically.

### A/B or multi-agent comparison

When two or more agents implement the same task from the same baseline, keep **all candidates** in the record, even though only one is integrated.

Record for each candidate:

- agent/model/tool;
- branch + exact HEAD;
- checks/result summary;
- strongest points;
- material weaknesses/blockers.

Then record:

- **Selected candidate**;
- **Selection reason** based on actual diff/verification, not preference or model reputation;
- whether useful ideas/fixes from a rejected candidate were later adopted separately.

Do not allow candidates to inspect or copy each other's task branches before the comparison is settled unless the owner explicitly ends the blind comparison.

## Evidence rules

- Prefer exact Git refs/SHAs and verified CI/run results over prose claims.
- Worker completion reports are context, not proof; the reviewer reads the actual diff/state.
- Never fabricate a model identity. Write the model only when runtime metadata or the execution environment confirms it.
- If exact model is unknown, record the agent/tool only and mark the model `unknown/not recorded`.
- Do not put private financial values, DB content, private seed data, credentials, owner screenshots containing personal values, or private payloads here.
- Keep this file concise enough to read chronologically. Deep technical rationale belongs in ADRs and release task-cards; link/reference them rather than duplicating them.

## Record template

```md
### <RELEASE> / <TASK-ID> — <short title>

- **Accepted:** YYYY-MM-DD
- **Implemented by:** <agent/tool> — <model if confirmed>
- **Reviewer/acceptor:** <agent/person>
- **Baseline:** `<ref>` @ `<sha>`
- **Candidate:** `<branch>` @ `<sha>`
- **Integrated into:** `<target>` @ `<sha>`
- **Verification:** <short factual list>
- **Iterations/blockers:** <none or material review loop>
- **Decision notes:** <why this implementation/contract was accepted>
- **References:** <ADR/release card/CI run if useful>
```

For an A/B task insert a `Candidates` subsection before `Selected candidate` and preserve both results.

---

# 0.4.x development

### 0.4.0 / R04-00 — parallel release line + active backlog setup

- **Accepted:** 2026-08-13
- **Implemented by:** ChatGPT — GPT-5.6 Sol
- **Reviewer/acceptor:** owner scope approval + ChatGPT repository read-back
- **Baseline:** `main` @ `b385e8cddfaa8e057dc34dc73a11d0bc839978d1`
- **Candidate/integration line:** `r04`, initially created from the exact green 0.3 RC baseline
- **Resulting R04 setup commit:** `fa3a470668f8f2c3e8d0f321d520d0d86aeba955`
- **Verification:** remote `r04` and `main` refs read back through GitHub; `main` remained unchanged
- **Iterations/blockers:** none
- **Decision notes:** established separate `main` maintenance (`0.3.x`) and long-lived `r04` development lines, with forward-port of accepted stable fixes `main -> r04` and owner-feedback triage independent of large-release work.
- **References:** `docs/releases/0.4.0.md`

### 0.4.0 / R04-01 — MOEX market identity + quote semantics contract

- **Accepted:** 2026-08-13
- **Implemented by:** ChatGPT — GPT-5.6 Sol
- **Reviewer/acceptor:** owner-authorized contract work + ChatGPT repository/source verification
- **Baseline:** `r04` after R04-00
- **Contract commit:** `d8fcf10231590dedd4fc4f484612ecf20dbb1f9c`
- **Backlog/unblock commit:** `1c2e2f5b1d757e9697126ce9206a2768a570be2a`
- **Integrated into:** `r04` @ `1c2e2f5b1d757e9697126ce9206a2768a570be2a`
- **Verification:** repository read-back of ADR/backlog and exact `r04`; stable `main` stayed at `b385e8cddfaa8e057dc34dc73a11d0bc839978d1`
- **Iterations/blockers:** MOEX data-usage terms were identified as a release/apply gate rather than silently assumed; technical adapter work remains unblocked.
- **Decision notes:** fixed board-aware MOEX identity, target-date quote semantics, stale/unavailable rules, exact bond percent-of-face conversion, manual fallback and no-background-refresh contract before implementation.
- **References:** `docs/adr/0009-moex-market-identity-and-quote-semantics.md`, `docs/releases/0.4.0.md`

### 0.4.0 / R04-02 — read-only MOEX ISS provider client (A/B)

- **Accepted:** 2026-08-13
- **Reviewer/acceptor:** ChatGPT — GPT-5.6 Sol
- **Baseline:** `r04` @ `1c2e2f5b1d757e9697126ce9206a2768a570be2a`

#### Candidates

- **Hermes/Grok — Grok 4.6:** `r04-02-grok` @ `073e343ab6ffd5e9d4e24bd6c77dd3c808fe4ce3` (initial implementation `0a566e39e76517f01401289663b14e8ba1cbc0d8`, reviewer follow-ups `ff44f62dcb83e6d60ba83b0320b8210b9a4f268a` and `073e343ab6ffd5e9d4e24bd6c77dd3c808fe4ce3`). Worker-reported final verification: targeted market-data tests `25 passed`, full backend `605 passed`, Ruff check/format passed, `git diff --check` clean. Strongest points: provider-neutral boundary, reuse of project domain/money types, correct ISS query discovery, Decimal-preserving parse, board-aware RUB filtering, documented current-day LAST handling. Review iterations fixed current-session `price_date`, SUR/RUR compatibility, false ambiguity from non-RUB boards and independent bond `F` currency/FACEUNIT checks.
- **OpenAI Codex — model unknown/not recorded:** `r04-02-codex` @ `acc42add6f6b035d3ca0fd75bf15df801c5ff787`. Worker-reported verification: targeted `13 passed`, full backend `593 passed`, Ruff/diff/privacy checks clean. Strongest points: genuine bounded parallel batch and no added runtime HTTP dependency. Material weaknesses from reviewer diff/source inspection: free-text discovery routed as exact security lookup, overloaded provider-specific identity metadata, possible false ambiguity, literal `RUB` handling rejected MOEX legacy RUB units, and current marketdata date assumptions mismatched documented shares payloads.

- **Selected candidate:** Hermes/Grok — Grok 4.6, final accepted HEAD `073e343ab6ffd5e9d4e24bd6c77dd3c808fe4ce3`.
- **Integrated into:** `r04` @ `073e343ab6ffd5e9d4e24bd6c77dd3c808fe4ce3` by fast-forward; later documentation-only commits advanced `r04` without changing the R04-02 implementation.
- **Selection reason:** actual branch comparison favored the Grok implementation for ADR alignment, provider-boundary architecture, project-domain reuse and lower follow-on integration risk. Codex's parallel batch implementation was better in isolation but did not outweigh correctness/contract issues.
- **Verification:** reviewer inspected both remote candidate diffs and the two Grok correction diffs against ADR 0009 and documented MOEX ISS payload semantics; exact remote candidate/integration refs were read back. Test counts above are worker-reported, not independently rerun by the reviewer.
- **Known limitation/gate:** MOEX data-usage authorization/terms remain a separate gate before live apply/release; R04-02 itself is read-only and does not claim authorization.
- **References:** `docs/adr/0009-moex-market-identity-and-quote-semantics.md`, `docs/releases/0.4.0.md`

### 0.4.0 / R04-03 — instrument market mapping storage/API

- **Accepted:** 2026-08-13
- **Implemented by:** Hermes/Grok — Grok 4.6
- **Reviewer/acceptor:** ChatGPT — GPT-5.6 Sol
- **Baseline:** `r04` @ `86d2033de5cb0572a2f9086464ab0145a51950f0`
- **Candidate:** `r04-03-grok` @ `4e35e7328d670466ac7f94fdbef7b928dcdffe9f`
- **Integrated into:** `r04` @ `4e35e7328d670466ac7f94fdbef7b928dcdffe9f` by fast-forward; this execution-history commit advances the branch afterward without changing R04-03 implementation.
- **Verification:** reviewer inspected the remote candidate diff, Alembic table/constraints, mapping state machine, API/provider-verification path, historical-snapshot safety tests and exact baseline relationship. Worker-reported verification: targeted mapping/API/migration/startup `35 passed`, full backend `633 passed`, Ruff check/format passed, `git diff --check` clean, migration smoke passed, privacy check passed. GitHub exposed no commit status checks for the candidate, so local test counts remain worker-reported rather than independently rerun.
- **Iterations/blockers:** none after implementation review.
- **Decision notes:** accepted a separate 1:1 mapping table with atomic board-aware identity; legacy `Instrument.moex_secid` remains only a discovery hint and is never migrated into accepted truth. `unmapped / mapped / excluded` transitions are explicit and reversible. Default mapping save is local-only explicit owner choice; optional `verify=true` confirms the already chosen identity through R04-02 without performing quote fetch, startup/background network, or automatic candidate selection.
- **Historical safety:** mapping operations touch only reference mapping storage; tests assert closed-month `PositionSnapshot` price/date/source/value/accrued-interest/update timestamp remain unchanged.
- **References:** `docs/adr/0009-moex-market-identity-and-quote-semantics.md`, `docs/releases/0.4.0.md`

---

## Historical backfill

Pre-R04 attribution remains available across Git history, `docs/HERMES_TASKS.md`, release backlogs, owner-review/follow-up docs, ADRs and `CHANGELOG.md`.

Do not invent missing executor/model attribution during backfill. A later documentation-only pass may reconstruct older releases from verifiable records if the owner wants a complete project-history article dataset.