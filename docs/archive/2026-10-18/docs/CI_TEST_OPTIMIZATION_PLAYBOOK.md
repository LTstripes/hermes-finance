# CI / test execution optimization playbook

## Purpose

A reusable method for reducing CI wall time **without weakening regression coverage or domain guarantees**.

This playbook was distilled from the Hermes Finance optimization pass closed on 2026-09-16. Project-specific results are recorded in [`docs/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-09-16.md`](CI_TEST_OPTIMIZATION_CLOSEOUT_2026-09-16.md).

The method is intentionally portable to other repositories, including Health-Check. Copy the process, not the Hermes-specific numbers or test selections.

## Core principle

Optimize **execution topology** before optimizing or deleting tests.

Prefer, in this order:

1. remove accidental duplicate execution;
2. narrow platform-specific lanes to the guarantees unique to that platform;
3. reuse already-produced artifacts safely inside one job;
4. parallelize independent tests/setup;
5. optimize expensive fixtures after measuring them;
6. consolidate genuinely duplicated tests only when semantic coverage is proven equivalent.

Mass test deletion is not a performance strategy.

## Step 1 — establish a real baseline

Use several recent successful CI runs from the same repository state or comparable states.

For every relevant job record:

- job duration;
- expensive step duration;
- test count / passed / skipped / retries;
- setup/install/build time;
- whether it is actually on the critical path;
- runner/platform.

Separate three metrics:

- **test/step time** — how long the relevant command runs;
- **job time** — setup + command + post steps;
- **whole-CI wall time** — time until all required jobs are complete.

Do not attribute whole-pipeline improvement to one change when another job finished last or runner variance dominates.

## Step 2 — audit duplicate execution first

Look for the same verification entering the pipeline through multiple paths:

- workflow invokes a test directly and a packaging script invokes it again;
- a full suite runs in multiple lanes where only a subset is platform-specific;
- install/package scripts rebuild or republish an artifact already created earlier;
- nested scripts silently call the same harness;
- release smoke and normal CI run equivalent checks without a distinct contract.

For every apparent duplicate ask:

- Is the assertion identical?
- Does it run against the same artifact/state?
- Does the second execution protect a different boundary?
- Which path is canonical?

Remove duplicate **execution**, not the canonical guarantee.

## Step 3 — map platform-specific lanes to guarantees

Never narrow a Windows/macOS/Linux lane just because the same test name exists elsewhere.

Classify every node:

- **MUST RUN ON THIS PLATFORM** — it exercises runtime, filesystem, timezone, path, shell, packaging or dependency behavior unique to the platform;
- **OTHER LANE SUFFICIENT** — the test's semantic guarantee is already fully owned elsewhere;
- **UNCERTAIN** — evidence is insufficient; keep it until proven otherwise.

Before removing a node from a platform lane, prove where it still runs.

Document the new ownership so future tests do not silently lose platform coverage.

## Step 4 — inspect expensive setup separately from assertions

Slow tests are often slow because they repeatedly construct realistic state.

Profile separately where practical:

- database/schema creation;
- repository/fixture creation;
- process startup;
- browser/server startup;
- dependency restore/install;
- compilation;
- artifact publishing;
- test assertions themselves;
- cleanup.

Do not optimize the assertion when fixture setup is the real cost.

## Step 5 — try bounded parallelism only after proving independence

Before increasing workers, inspect:

- shared mutable globals;
- database/filesystem writes;
- screenshot/output filenames;
- ports and web-server lifecycle;
- environment variables;
- fixture directories;
- process cleanup;
- test ordering assumptions;
- retries and artifact collection.

Prefer the smallest concurrency change first.

Example pattern:

- increase workers;
- keep within-file/full parallelism disabled if ordering inside a group still matters;
- do not refactor tests in the same experiment unless necessary.

Concurrency acceptance requires repeated runs, not one green CI.

## Step 6 — keep experiments isolated

One meaningful performance hypothesis per PR whenever possible.

Good examples:

- remove one duplicated harness;
- narrow one platform lane;
- change one worker count;
- replace one fixture setup strategy.

Bad example:

- worker changes + fixture rewrite + lane reshuffle + test deletion in one PR.

Isolation makes regressions attributable and lets the Integrator revert one idea without losing the rest.

## Step 7 — verification contract for an optimization PR

At minimum verify:

- expected test/node count before and after;
- no unintended skips;
- all retained tests pass;
- removed executions still have a canonical owner where applicable;
- artifacts/screenshots/outputs remain complete;
- failure still blocks the pipeline where the previous contract required fail-closed behavior;
- diff is limited to the optimization scope;
- privacy/runtime boundaries are unchanged;
- exact-head PR CI succeeds;
- canonical exact-main push CI succeeds after merge.

For concurrency changes, add repeated local/hosted runs and check for retries/flakes/collisions.

## Step 8 — report timing honestly

Use observed ranges rather than a single headline number when possible.

Report:

- baseline runs;
- candidate runs;
- step timing;
- job timing;
- whole-CI timing;
- test counts;
- runner/platform differences;
- whether the target job remained the critical path.

Do not promise a fixed speedup from GitHub-hosted runner samples.

## GO / NO-GO guidance

### Strong GO

Usually worth doing when:

- duplicate execution is proven;
- coverage is unchanged;
- implementation is small;
- gain is material to the critical path;
- failure semantics remain identical.

### Conditional GO

Requires repeated evidence when:

- adding concurrency;
- caching/reusing mutable artifacts;
- changing fixture topology;
- moving tests between platform lanes.

### Usually NO-GO

Avoid when:

- the expected gain is only a few seconds;
- implementation adds shared mutable fixture state;
- toolchain/reproducibility policy must change only for speed;
- publish/install/fail-closed semantics become less direct;
- the target job is no longer near the critical path;
- the optimization makes tests significantly harder to understand or maintain.

## Stop rule

A CI optimization pass should have an explicit stopping point.

Stop when:

- obvious duplicate work is gone;
- platform lanes have clear ownership;
- safe parallelism is already used;
- remaining cost represents real high-value verification;
- the next expected gain is small relative to complexity/risk;
- current CI latency is acceptable for normal development.

A few seconds left on the table is often cheaper than a clever test harness that becomes difficult to trust.

## Suggested audit prompt

A useful read-only audit can be intentionally short:

> Audit the current CI for safe performance improvements. Treat GitHub as source of truth. Identify the actual critical path, duplicate execution, platform-overbroad coverage, expensive setup/fixtures and safe parallelism opportunities. Do not assume an optimization is required. Preserve regression, privacy, runtime and domain contracts. For each opportunity give expected value, risk and GO/NO-GO; recommend only the next highest-value bounded change.

The repository's own `AGENTS.md`, verification policy and test guide should carry durable rules. Do not duplicate the whole project constitution into every task prompt.

## Applying this to another project

For Health-Check or another repository:

1. start from its own current `main` and CI history;
2. inventory that project's lanes and contracts independently;
3. establish its own baseline counts/timings;
4. do not assume Hermes Finance bottlenecks exist there;
5. run the steps above in small PRs;
6. preserve health/data/privacy semantics exactly as defined by that repository;
7. write a project-specific closeout once the marginal-gain stop condition is reached.
