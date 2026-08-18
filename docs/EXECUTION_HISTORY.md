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

### 0.4.0 / R04-05C — T-Invest mapping integrity hardening

- **Accepted:** 2026-08-14
- **Implemented by:** Grok Build — Grok 4.6 per submitted session report; model identity not independently runtime-confirmed by the accepting reviewer
- **Reviewer/acceptor:** ChatGPT — GPT-5.6 Sol
- **Issue:** #28
- **Baseline:** `r04` @ `182e7000c077cb760cadbf6c3bc3272f07851ac0`
- **Candidate:** `r04-05c-grok` @ `9c8b4bba2f58e79d6b5f012e5cade99393dbacae`
- **Integrated into:** `r04` via true two-parent merge commit `169079b7c1bebe95bf8cee3f12a2a58d36d3c1a4`; later documentation commits advance the branch.
- **Verification:** accepting reviewer verified exact one-commit ancestry from the expected baseline and inspected the complete candidate diff plus final backend/API/frontend paths. Confirmed candidate ISIN preservation, hard ISIN mismatch rejection, required provider verification for manual T-Invest UID with known local ISIN, UI `verify=true` T-Invest saves, clearing candidate ISIN after owner UID edits, and valid-candidate preservation when a neighboring discovery payload is malformed. Worker-reported checks: targeted backend `68 passed`, full backend `706 passed`, targeted frontend mapping tests `50 passed`, full frontend `218 passed`, `tsc -b && vite build`, Ruff check/format, touched-file Biome, `git diff --check`, and privacy check (`444 tracked files`) all passed. GitHub Actions did not run on the task branch because CI triggers on `main` push / pull request.
- **Scope discipline:** no apply/provenance/live probe, no background/startup network, no MOEX production fallback and no trading/account APIs were added.
- **Decision notes:** closes the R04-AUDIT-01 pre-apply mapping-integrity finding. T-Invest candidate saves are deliberately stricter in the UI: all T-Invest saves request provider verification, while backend also prevents a manual UID from bypassing verification when local ISIN is known and candidate ISIN is absent.
- **Known limitation:** an API caller that supplies a candidate ISIN matching the local instrument can persist without `verify_provider`; the canonical owner UI still sends `verify=true`, and R04-05D live probe remains required before R04-06 acceptance.
- **References:** issue #28, ADR 0009, ADR 0010, `docs/releases/0.4.0.md`.

### 0.4.0 / R04-05D — owner live read-only T-Invest probe

- **Accepted:** 2026-08-14
- **Implemented by:** Grok Build — Grok 4.6 per submitted session report; exact model identity not independently runtime-confirmed by the accepting reviewer
- **Reviewer/acceptor:** ChatGPT — GPT-5.6 Sol
- **Issue:** #29
- **Baseline:** `r04` @ `76d02f10f891102c3f10964a2d7c814e89e06a8a`
- **Candidate:** `r04-05d-grok` @ `08214f91994ddf3dfe7f91143d0d7fa343a2d711`; initial implementation `4c7ebedb37d9fc2df4724162054b2fd5226d9467`.
- **Integrated into:** `r04` via true two-parent merge `e2a30e4d696de21e0b30bed46e9ffff78d042af5`; troubleshooting docs followed at `d275b2ee413fa5c6e945de0ab05230b00ed42d97`.
- **Live verification:** owner-side authenticated read-only probe succeeded against official T-Invest API shape using public/non-personal instruments. Only `FindInstrument`, `GetInstrumentBy`, `BondBy`, `GetLastPrices`, and `GetCandles` were called; no Accounts/Operations/Orders/Sandbox/Transfer methods. Official Quotation `units+nano`, `lastPriceType`, `candleSourceType`, historical `price_date <= target_date`, and bond MoneyValue semantics matched the adapter. No mapping/snapshot mutation occurred.
- **Deterministic verification:** worker reported probe/provider targeted tests `31 passed`, full backend `715 passed`, Ruff check/format, `git diff --check`, and privacy check (`447 tracked files`) all passed.
- **Iterations/blockers:** accepting review first caught a fixture-writer schema mismatch; follow-up made `--write-fixture` emit the canonical `{meta, stock, bond}` schema and added write→reload regression coverage. The final live run intentionally did not retain an auto-refreshed fixture because the capture generated repeated sanitized public rows while the existing deterministic fixture already represented the confirmed official fields.
- **Owner environment note:** on the owner's Windows environment the live API connection succeeded with VPN disabled after failing while VPN was active; a rejected read-only token also required owner-side reissue. These are troubleshooting observations, not application networking/auth contracts. No token value or raw private/account payload is recorded here.
- **Decision notes:** closes the final external-provider pre-apply gate from R04-AUDIT-01. Issue #29 closed completed.
- **References:** issue #29, ADR 0010, `docs/t-invest-market-data.md`.

### 0.3.x maintenance wave / M03-01..03 — audit findings closed and forward-ported

- **Accepted/integrated:** 2026-08-14
- **Reviewer/acceptor/integrator:** ChatGPT — GPT-5.6 Sol, with independent Grok verification/follow-up on all three candidates.
- **Original stable baseline:** `main` @ `b385e8cddfaa8e057dc34dc73a11d0bc839978d1`.
- **M03-01 / issue #25:** exact canonical bind invariant `host == 127.0.0.1`; final candidate `m03-01-loopback-bind` @ `55861b588dd7302cc3efc41d96db76dec5a19b95`; integrated main merge `5a42426c224cc77c1204356ecfcec029cfa328b6`. Grok final verification: targeted `24 passed`, full backend `586 passed`, Ruff/diff/privacy clean.
- **M03-02 / issue #26:** `realized_loss` write invariant requires strictly negative signed net (`net < 0`), without double-negation; final candidate `m03-02-realized-loss-sign` @ `e5a30c0b65db790fcea7fe46ffc59cf9a7f3431b`; integrated main merge `8c52664080a50dd794816712c293351ecc75bf3c`. Grok final verification: targeted `32 passed`, full backend `582 passed`, Ruff/diff/privacy clean.
- **M03-03 / issue #27:** one canonical SALARY row for valid writes while legacy duplicates remain readable/aggregated; atomic owner salary replace heals duplicates; clone collapses recurring legacy duplicates deterministically; frontend aggregation stays exact integer/bigint. Final candidate `m03-03-salary-cardinality` @ `0813cd63edacb231e0eda20b3fa3452758667c08`; integrated main merge `23f14aca74c5fa05c434cf15b89ec6bc2d687a12`. Grok final candidate verification: backend `589 passed`, frontend `171 passed`, targeted/frontend build/Ruff/Biome lint/diff/privacy clean.
- **Exact-main gate:** CI #224 exposed only a Biome formatting regression in two M03-03 import lines; format-only commit `1bf28bfdbec2c9c6d495a1de449bce2f541be13e` fixed it. Exact-main CI #225 completed successfully.
- **Forward-port into 0.4:** current stable main `1bf28bfdbec2c9c6d495a1de449bce2f541be13e` was merged into `r04` via true two-parent merge `4b2d249a6a175bf4009ec1785dbded961a2b2fa9`. The only semantic overlap was Settings: the merge preserves both the R04 repository-root `.env` / T-Invest `SecretStr` contract and M03-01's exact `127.0.0.1` bind invariant. Relative to the preceding `r04`, exactly the 17 maintenance paths changed; market-data implementation remained intact.
- **Decision notes:** all three stable audit findings are closed on `main` and present in `r04`. R04-06 remains gated only on an exact integrated-`r04` post-merge verification pass before implementation begins.
- **References:** issues #25, #26, #27, `docs/releases/0.4.0.md`.

### 0.4.0 / R04-06 — explicit selective quote apply + immutable provenance

- **Accepted:** 2026-08-14
- **Implemented by:** Grok Build — exact model identity not independently runtime-confirmed in the accepted evidence
- **Reviewer/acceptor:** ChatGPT — GPT-5.6 Sol
- **Issue:** #30
- **Baseline:** `r04` @ `e48183b04387452879f6e21e0f281df3da9460b8`
- **Candidate:** `r04-06-grok` @ `540537385eb05d5793d807c2cb19b05428dfe3b8`; initial reviewed candidate `be692918ad55e294b96b9580d99d508d1c648e82`.
- **Integrated into:** `r04` via true two-parent merge `40c1e9406f09d541df4281e51fc4473e22a4f997`, using the exact accepted candidate tree and preserving candidate history.
- **Verification:** accepting reviewer inspected the exact remote branch/ancestry and re-checked the four blocking invariants after follow-up. Confirmed append-only 1:N apply-event provenance per snapshot; generic position CRUD cannot fabricate or silently corrupt `t_invest`; stale selection is T-Invest-only; clone carries valuation state without fabricating target-month apply provenance. Selected-set apply remains atomic, closed-month guard authoritative, backend refetch/normalization authoritative, `preview_changed` writes nothing, NKD is unchanged, and historical provenance survives mapping/manual edits. Worker-reported final checks: backend full `752 passed`, frontend full `224 passed`, Ruff/Biome lint/build/diff/privacy green; no live probe or `.env` access.
- **Iterations/blockers:** first review returned four blockers: provenance overwrote prior apply history; generic CRUD could fabricate/corrupt `t_invest`; stale MOEX rows were selectable in UI; clone fabricated provenance on the target snapshot. All four were fixed narrowly on the task branch before ACCEPT.
- **Decision notes:** R04-06 established the mutation boundary for production T-Invest quotes: explicit selected rows only, server-side refetch, optimistic preview consistency guard, one transaction for the selected set, and immutable historical provenance.
- **References:** issue #30, `docs/releases/0.4.0.md`.

### 0.4.0 / R04-07 — market-data failure/manual fallback UX

- **Accepted:** 2026-08-14
- **Implemented by:** Grok Build — exact model identity not independently runtime-confirmed in the accepted evidence
- **Reviewer/acceptor:** ChatGPT — GPT-5.6 Sol
- **Issue:** #31
- **Baseline:** `r04` @ `d397c4092e2e01911475726cc3e1246544441632`
- **Candidate:** `r04-07-grok` @ `7f967be829be5e88283907a02461c4dbee0f7c84`
- **Integrated into:** `r04` via true two-parent merge `61e6a1503b8b173920b6976ee5f04d4a2aef2f08`.
- **Verification:** independent inspection of the exact candidate confirmed sanitized provider failure reasons/messages, clear local-Hermes versus external-provider network distinction, mixed-success preview usability, stale T-Invest explicit-only selection, stale MOEX non-applicability, and `preview_changed` invalidation of the old preview/apply state. Worker-reported final checks: backend full `763 passed`, frontend full `230 passed`, Ruff pass, Biome lint pass, build pass, privacy PASS.
- **Scope discipline:** no live T-Invest probe, no background/retry polling, no auto-apply, no weakening of closed-month or R04-06 provenance/source rules. Missing token/provider failure preserves stored prices and editable-month manual fallback without exposing raw provider diagnostics.
- **Decision notes:** failure recovery is now owner-safe and explicit: failed rows remain non-applicable, good rows in mixed previews remain usable, and a changed quote requires a fresh preview before a second explicit apply.
- **References:** issue #31, `docs/releases/0.4.0.md`.

### 0.4.0 / R04-08 — regression matrix + Windows/network smoke (multi-model review benchmark)

- **Accepted:** 2026-08-16
- **Implemented by:** Grok Build / Grok 4.6 as selected by the owner-run implementation session
- **Reviewer/acceptor:** ChatGPT — GPT-5.6 Sol
- **Independent reviewers:** OpenAI Codex — GPT-5.6 Sol High; DeepSeek V4 Flash (initial blind pass); DeepSeek V4 Pro (later blind re-review passes)
- **Issue:** #32
- **Baseline:** `r04` @ `92b09628dc73646dde5d0855562431c0dd9872fd`
- **Candidate trail:** initial `07dc2e12502196e9e5f4e7a64234b6d010d45e12` → follow-up `0da5980447947ef5dac69b28e2b581bc876d2026` → follow-up `c68ca82b877e2085dbc57bdf7ce27ac845ec3601` → final accepted `ec9f56b1870402201ae863d80fd08cea758a4ac4`.
- **Integrated into:** `r04` via true two-parent merge `5a7d0add14d1699e72993af522d2e61f47a27144`; later documentation commits advance the branch.
- **Final verification:** Grok reported backend `771 passed`, frontend `230 passed / 40 files`, Ruff/Biome/build/diff/privacy green and Windows smoke green from a Cyrillic + spaced path. Final exact candidate then received independent ACCEPT from both Codex GPT-5.6 Sol High and DeepSeek V4 Pro; ChatGPT independently read back the live candidate/ref/ancestry and inspected the final fixes before integration.
- **Material review iterations:** Codex's first blind review found three real blockers: 0026 downgrade could delete append-only provenance after a manual override; Windows smoke did not prove the actual live listener was exactly `127.0.0.1`; and the cold-import/startup network test used an ineffective constructor patch. DeepSeek V4 Flash accepted that initial candidate and therefore missed the release-engineering significance of those gaps. After Grok fixed them, Codex and DeepSeek V4 Pro independently found the same Windows PowerShell 5.1 spaced-path `Start-Process -ArgumentList` regression. After the next fix Codex accepted, but DeepSeek V4 Pro found a further Cyrillic/UTF-8-BOM regression in the generated PowerShell verification script. Grok fixed source/output encoding narrowly; the final candidate then received dual ACCEPT.
- **Decision notes:** this task became a useful real-project model benchmark. Grok remained a strong scope-disciplined implementer/follow-up executor; Codex was the strongest initial adversarial reviewer; DeepSeek V4 Pro materially outperformed Flash and later caught a Windows/environment edge case after Codex had already accepted. The most effective workflow was one implementer plus independent reviewers trying to falsify the verification evidence rather than trusting green test counts.
- **References:** issue #32, `docs/releases/0.4.0.md`, `docs/reviews/2026-08-16-r04-08-model-benchmark.md`.

---

# 0.5.0 publication

### 0.5.0 — published stable release

- **Published:** 2026-08-18
- **Status:** RELEASED; R05 closed
- **Exact released SHA:** `7a032eb8c61c675f3a779f9afda59d47e9c8dc81`
- **Lineage:** `main` = `r05` = `v0.5.0`
- **GitHub Release:** `0.5.0` published as Latest
- **Final exact-main CI:** `32140936658` green
- **Owner verification:** live smoke including T-Invest passed
- **Implemented/reviewed by:** not independently reconstructed in this record; do not invent executor or model attribution
- **Decision notes:** 0.5.0 is the current stable product line. It adds the owner-controlled T-Invest payout calendar on top of locally stored positions. No new R05 development.
- **References:** `docs/releases/0.5.0.md`, `CHANGELOG.md`, `docs/release-notes-0.5.0.md`

# Workspace hygiene migration

### HYG — runtime / agent workspace isolation

- **Recorded:** 2026-08-18
- **Kind:** architectural / process migration after 0.5.0 publication
- **Reason:** the original checkout had become both production runtime and a shared Git directory for 33 linked worktrees. Real `.env`, the live finance database, backups and private assets sat in the same tree that agents used. Development and owner runtime were insufficiently isolated.
- **Outcome:** production runtime and agent development environments were separated. Independent agent clones were created with their own Git directories. All 33 linked worktrees of the old shared checkout were retired. A clean runtime clone received the verified migration of ignored runtime data. The legacy shared checkout was retired.
- **Migration sequence:** inventory-only audit → preservation triage → Preservation Seal → preservation of unique dirty Codex work, a special Grok/T-Invest research artifact and the R04-02 benchmark source/tests → classification of dangling commits → independent agent clones → retirement of 33 linked worktrees → clean runtime clone → verified runtime-data migration → local loopback runtime smoke → retirement of the old shared checkout.
- **Normative follow-up:** ADR 0012; `AGENTS.md` runtime-isolation invariant.
- **Not recorded here:** secret values, database contents, private filenames, or machine-specific paths as repository requirements.
- **Attribution:** owner-driven workspace migration; executor/model details not independently reconstructed.

---

## Historical backfill

Pre-R04 attribution remains available across Git history, `docs/HERMES_TASKS.md`, release backlogs, owner-review/follow-up docs, ADRs and `CHANGELOG.md`.

Do not invent missing executor/model attribution during backfill. A later documentation-only pass may reconstruct older releases from verifiable records if the owner wants a complete project-history article dataset.