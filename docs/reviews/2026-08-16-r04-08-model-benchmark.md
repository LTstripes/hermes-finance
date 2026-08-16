# R04-08 multi-model implementation/review benchmark

Date: 2026-08-16

Task: R04-08 — regression matrix + Windows/network smoke  
Issue: #32  
Canonical baseline: `92b09628dc73646dde5d0855562431c0dd9872fd`  
Implementation branch: `r04-08-grok`

## Purpose

This record preserves the real-project model comparison that emerged during R04-08. It is not a synthetic benchmark. One implementation agent produced the verification task; independent reviewers then challenged the evidence, found release-blocking gaps, and forced successive narrow follow-ups until the same exact candidate received independent ACCEPT verdicts.

No reviewer was allowed to modify the candidate during review. No live T-Invest call was used in the review rounds. `main` and `r04` remained unchanged until final acceptance/integration.

## Roles

- **Implementer:** Grok Build / Grok 4.6 as identified by the owner-run session.
- **Integrator/acceptor:** ChatGPT — GPT-5.6 Sol.
- **Blind reviewer 1:** OpenAI Codex — GPT-5.6 Sol High.
- **Blind reviewer 2, first pass:** DeepSeek V4 Flash.
- **Blind reviewer 2, later passes:** DeepSeek V4 Pro.

Model labels above reflect the owner-selected sessions for this comparison. They are preserved because the purpose of this record is later model-performance analysis.

## Candidate trail

### Candidate 1 — `07dc2e12502196e9e5f4e7a64234b6d010d45e12`

Initial Grok R04-08 candidate. Scope was clean: release verification/tests/scripts/docs only, no feature development.

Worker-reported checks included backend `767 passed`, frontend `230 passed`, Ruff/Biome/build/diff/privacy green, Windows launcher smoke green, and mocked/offline network verification.

#### Codex 5.6 Sol High verdict: BLOCKERS

Codex found three concrete release blockers:

1. **Alembic 0026 downgrade could silently delete append-only provenance.** The guard only checked current snapshots with `price_source='t_invest'`; after a legal manual override the snapshot could be `manual` while historical T-Invest provenance still existed, allowing downgrade to drop the provenance table.
2. **Windows smoke did not prove the actual live bind was exactly `127.0.0.1`.** Requests to `127.0.0.1` would also succeed if the server were listening on `0.0.0.0`; the listener check happened only after shutdown.
3. **Import/startup network regression had ineffective guards.** The test patched `t_invest.TInvestClient` after `routing.py` had already captured a direct alias, so the mock could be bypassed and the test could pass without proving the intended invariant.

Codex supplied concrete reasoning/probes rather than only test-count objections.

#### DeepSeek V4 Flash verdict: ACCEPT

Flash independently ran broad verification and accepted the candidate. It noticed the downgrade behavior but classified it as a non-blocker because downgrade was not expected in normal production use. It also accepted the startup/import and Windows smoke evidence.

**Benchmark note:** this became the clearest miss of the experiment. Flash had enough code context to see one of the risky behaviors but applied weaker release-engineering judgement than Codex.

#### Integrator verdict

BLOCKERS confirmed. The startup/network false-positive concern independently matched the integrator's own pre-existing suspicion. Grok was asked to fix exactly these three issues without scope expansion.

---

### Candidate 2 — `0da5980447947ef5dac69b28e2b581bc876d2026`

Grok follow-up closed the three confirmed blockers:

- 0026 downgrade now fails closed when any provenance row exists and gained a `manual snapshot + historical T-Invest provenance` regression;
- Windows smoke inspects the real TCP listener while the canonical production launcher is live and checks post-shutdown cleanup;
- cold import/startup verification moved to an isolated subprocess with socket/HTTP guards installed before application imports plus a self-test proving the guard is not a no-op.

Worker-reported backend `769 passed`, targeted `211 passed`, frontend `230 passed`, lint/build/privacy green, live Windows listener only `127.0.0.1:8000`.

#### Codex verdict: BLOCKERS

Codex found a new Windows-specific blocker: `Start-Process -ArgumentList` passed `$launcher` without quoting. On Windows PowerShell 5.1, a repository path containing spaces could be split, so `powershell.exe -File` did not receive the full canonical script path.

#### DeepSeek V4 Pro verdict: BLOCKERS

DeepSeek Pro independently found the same blocker and reproduced it in the owner environment. It also noted that the previous candidate's `& powershell.exe ... -File $launcher` form had not had this argument-boundary problem.

**Benchmark note:** Pro performed materially better than Flash and converged with Codex independently on the same environment-specific regression.

---

### Candidate 3 — `c68ca82b877e2085dbc57bdf7ce27ac845ec3601`

Grok replaced the unsafe `Start-Process -ArgumentList` invocation with a Windows PowerShell 5.1 helper based on `System.Diagnostics.ProcessStartInfo`, explicitly quoting the full `-File` path. A real Windows regression test was added with positive and negative controls for a path containing spaces.

Worker-reported backend `771 passed`, frontend `230 passed`, Windows smoke green from a spaced path, exact live bind only `127.0.0.1:8000`, clean shutdown.

#### Codex verdict: ACCEPT

Codex accepted the spaced-path fix and reported no new release blocker.

#### DeepSeek V4 Pro verdict: BLOCKERS

DeepSeek Pro found another narrower Windows verification defect that Codex missed: the generated `.ps1` driver/probe files were written as UTF-8 without BOM while the canonical owner checkout contains Cyrillic characters (`Рабочий стол`). Windows PowerShell 5.1 can interpret BOM-less source as the legacy ANSI code page, causing the generated positive-control script to fail parsing in the real checkout. Pro reproduced the failure.

Pro also identified the adjacent output-encoding risk: PowerShell 5.1 `Set-Content` without explicit encoding could write the reported `$PSCommandPath` using the legacy code page while Python expected UTF-8.

**Benchmark note:** this round reversed the previous ordering: DeepSeek V4 Pro caught a real Windows/environment edge case after Codex had already accepted.

---

### Candidate 4 — final accepted `ec9f56b1870402201ae863d80fd08cea758a4ac4`

Grok fixed only the Windows verification encoding layer:

- generated PowerShell source uses `utf-8-sig` / UTF-8 BOM for Windows PowerShell 5.1;
- probe output uses explicit `Set-Content -Encoding UTF8`;
- Python reads the result with `utf-8-sig`;
- regression uses a deterministic path containing both Cyrillic and spaces: `Рабочий стол Directory With Spaces`;
- the helper itself is copied into that non-ASCII spaced path so the positive control exercises the actual failure mode.

Worker-reported final checks:

- backend `771 passed`;
- frontend Vitest `230 passed / 40 files`;
- Ruff check/format green;
- Biome lint green;
- `tsc -b && vite build` green;
- `git diff --check` green;
- privacy check green;
- Windows smoke from Cyrillic + spaced path green;
- canonical launcher health/months/root 200;
- live listener only `127.0.0.1:8000` and gone after shutdown;
- no live T-Invest.

#### Codex 5.6 Sol High final verdict: ACCEPT

Exact candidate `ec9f56b1870402201ae863d80fd08cea758a4ac4`. Codex independently confirmed Windows PowerShell 5.1, Cyrillic + spaced path, UTF-8 BOM handling, exact `$PSCommandPath`, previous guards, and no new release blocker.

#### DeepSeek V4 Pro final verdict: ACCEPT

Exact candidate `ec9f56b1870402201ae863d80fd08cea758a4ac4`. Pro independently re-ran the relevant Windows-path/release tests and full backend suite, confirmed source/output encoding, exact live bind, provenance downgrade guard and cold-import/network guard, and reported no new release blocker.

#### Integrator final verdict

**ACCEPT.** The exact remote candidate and ancestry were independently read back before integration. The candidate was integrated into `r04` via two-parent merge commit `5a7d0add14d1699e72993af522d2e61f47a27144`.

## Comparative takeaways

- **Grok 4.6:** strong implementer and follow-up executor. Scope discipline remained good across repeated corrections, and fixes stayed narrow rather than drifting into feature work. Initial verification was not adversarial enough to catch several false-positive/environment gaps on its own.
- **Codex 5.6 Sol High:** strongest first-pass adversarial reviewer. It found three substantive blockers in the initial candidate and then independently caught the Windows argument-splitting regression. It later missed the PowerShell 5.1 Cyrillic/BOM test-environment problem and accepted one candidate too early.
- **DeepSeek V4 Flash:** weakest reviewer in this run. It accepted the initial candidate despite a real downgrade/provenance loss path and ineffective verification evidence.
- **DeepSeek V4 Pro:** materially stronger than Flash. It matched Codex on the Windows spaced-path blocker and then outperformed Codex on the Cyrillic/BOM edge case.
- **Best workflow observed:** strong implementer + independent adversarial reviewers was more valuable than simply duplicating implementation. R04-08 benefited specifically from reviewers trying to falsify the tests rather than trusting green counts.

## Final state

- Accepted candidate: `ec9f56b1870402201ae863d80fd08cea758a4ac4`
- Integrated R04-08 merge: `5a7d0add14d1699e72993af522d2e61f47a27144`
- `main` was not modified by R04-08.
- No tag/release was created.
- Next task: R04-09 — 0.4 release gate.
