# CI / test execution optimization closeout — 2026-09-16

## Status

**Closed.** Hermes Finance completed a bounded CI/test-execution optimization pass without deleting regression tests or weakening product, privacy, financial, launcher, timezone or visual verification contracts.

This document records what changed, the measured effect, the stop decision, and the reusable lessons for other repositories.

Reusable method: [`docs/CI_TEST_OPTIMIZATION_PLAYBOOK.md`](CI_TEST_OPTIMIZATION_PLAYBOOK.md).

## Scope and safety boundary

The optimization pass deliberately targeted **duplicate execution, platform-overbroad execution and safe parallelism**, not removal of test coverage.

Permanent rules during the pass:

- do not delete tests merely to make CI faster;
- preserve financial/domain assertions;
- preserve fail-closed launcher/package/install behavior;
- preserve Windows-specific timezone/tzdata evidence;
- preserve visual scenarios, screenshot inventory and existing skips;
- make one narrow optimization at a time;
- require exact-head PR CI and exact-main push CI before closeout;
- distinguish job/step timing from whole-CI timing and runner variance.

## Accepted changes

### PR #397 — run Windows launcher safety harness once

Previous launcher CI executed the same full safety harness twice:

1. directly from the workflow;
2. again through the canonical package/install chain.

PR #397 removed only the standalone duplicate execution. The accepted chain remains:

`CI → test-windows-launcher-package.ps1 → package.ps1 → full safety harness → publish/package → install.ps1 → smoke assertions`

Coverage result:

- launcher safety scenarios before: **88 × 2 = 176 scenario executions**;
- after: **88 × 1 = 88 scenario executions**;
- regression scenarios removed: **0**.

Observed timing evidence showed the launcher job falling from earlier multi-minute runs, including an observed **8:56** pre-change run, to roughly **3:11–3:24** in later canonical runs. GitHub-hosted runner variance means this is not a fixed guaranteed speedup.

### PR #399 — narrow Windows timezone lane to Windows-specific coverage

The Windows timezone job previously ran **35 pytest nodes** across:

- the Moscow timezone suite;
- AI Analysis Bundle contract coverage;
- AI Analysis Bundle export coverage.

Audit showed that only a bounded subset provided additional Windows/tzdata/runtime value. PR #399 changed the Windows selection to:

- all 5 nodes in `test_moscow_tz.py`;
- 2 production-path export integration tests.

Result:

- Windows nodes before: **35**;
- Windows nodes after: **7**;
- redundant Windows executions removed: **28**;
- those 28 tests deleted: **0** — they remain mandatory in Linux CI lanes.

Observed Windows timezone job time moved from about **100 seconds** to roughly **39–50 seconds** in accepted/canonical runs.

### PR #401 — run synthetic visual audit with two Playwright workers

The visual audit was not reduced. Instead the same independent spec/viewport groups were allowed to run with:

- `workers: 2`;
- `fullyParallel: false` unchanged.

Coverage remained:

- **84 collected**;
- **74 passed**;
- **10 existing skips**;
- **0 retries/flakes** in the accepted repeated evidence;
- the same **76 screenshot paths and dimensions**.

Evidence before acceptance included 2 serial baseline runs, 5 local candidate runs, 2 hosted candidate visual runs and exact-candidate UI comparison.

Observed hosted timing:

- visual audit step: about **171–174 s → 96–124 s** across measured candidate/canonical runs;
- visual job: about **210–218 s → 138–162 s** across measured candidate/canonical runs.

No visual scenario, assertion, fixture, viewport or screenshot contract was removed.

## Aggregate result

Compared with the pre-pass configuration, every normal full CI run now avoids approximately:

- **88** duplicate launcher safety scenario executions;
- **28** redundant Windows pytest executions.

That is **116 fewer redundant test/scenario executions per full CI run** while retaining the original regression coverage.

Tests intentionally deleted during this optimization pass: **0**.

The visual suite still runs the same nodes, now with bounded parallelism.

Whole-pipeline observations moved from earlier runs in roughly the **7–9 minute** range to about **3.5 minutes** at closeout. This is directional evidence, not a controlled benchmark: repository state, GitHub-hosted runners, caches and setup times differ between runs.

At the closeout checkpoint after PR #401, an exact-main CI run completed in approximately **3:28**. The Windows launcher safety job was again the last/longest job at about **3:24**, while visual audit had stopped being the critical path.

## Final launcher audit and stop decision

A subsequent read-only audit decomposed the remaining launcher cost.

The important conclusion was that the obvious structural waste had already been removed:

- no second full harness remains;
- installer reuses the produced package rather than republishing it;
- publish/install assertions are cheap relative to the safety scenarios;
- most remaining time is real safety work that creates and verifies Git/filesystem/process states.

One additional low-risk idea was identified: batch several Git pushes used while building Stable-upgrade fixtures. Expected gain was only an estimated **5–20 seconds** and had not been measured on an implementation candidate.

Owner/Integrator decision: **do not pursue that optimization now**.

Reason:

- the remaining gain is small relative to the already-achieved improvement;
- the safety harness protects real Git/filesystem/update invariants;
- increasing fixture complexity for marginal speed is not justified;
- the current CI duration is acceptable.

This is the explicit stop condition for this optimization pass.

Reopen launcher CI optimization only if one of these becomes true:

- launcher safety materially blocks normal development again;
- repeated evidence shows a substantially larger safe opportunity;
- a fixture/runtime redesign is already required for correctness or maintainability;
- meaningful flakiness appears and the fix also improves runtime.

Do **not** reopen merely to chase a few seconds.

## What worked

1. **Remove duplicate executions before touching tests.** The largest gain came from identifying the same 88-scenario harness running twice.
2. **Treat platform lanes as contracts.** Windows coverage was narrowed only after mapping every node to Windows-specific value and proving Linux ownership for the rest.
3. **Parallelize only after proving independence.** Playwright moved to two workers only after checking ports, filesystem outputs, fixtures, screenshot names and repeated runs.
4. **Keep one optimization per PR.** This made timing changes attributable and regressions easy to reason about.
5. **Measure multiple levels.** Step time, job time and whole-pipeline time were reported separately.
6. **Use repeated evidence for concurrency changes.** One green run is not enough to call parallelism stable.
7. **Stop when marginal value falls below contract risk.** A possible 5–20 second launcher gain was intentionally left on the table.

## Reuse in other projects

The numerical choices in Hermes Finance are **not** defaults for another repository. In particular, do not copy `workers: 2`, Windows test selections or launcher-specific decisions mechanically.

For another project such as Health-Check, reuse the **method**:

1. measure current CI and identify the actual critical path;
2. search for duplicate execution;
3. map platform-specific lanes to the guarantees they uniquely provide;
4. inspect expensive fixture/setup work separately from test assertions;
5. try bounded parallelism only where state is independent;
6. validate with repeated runs and exact coverage counts;
7. preserve all correctness/privacy/runtime contracts;
8. stop when the next optimization is only marginal.

See [`docs/CI_TEST_OPTIMIZATION_PLAYBOOK.md`](CI_TEST_OPTIMIZATION_PLAYBOOK.md) for the reusable checklist.

## Canonical references

- PR #397 — launcher safety harness deduplication;
- PR #399 — Windows timezone subset;
- PR #401 — Playwright visual workers=2;
- `docs/TEST_SUITE_GUIDE.md`;
- `docs/VERIFICATION_POLICY.md`;
- `AGENTS.md`.
