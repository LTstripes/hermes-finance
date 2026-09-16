# CI test optimization — 2026-09-16

Historical pointer for the bounded Hermes Finance CI/test-execution optimization pass.

Canonical project-specific closeout:

- [`docs/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-09-16.md`](../CI_TEST_OPTIMIZATION_CLOSEOUT_2026-09-16.md)

Reusable cross-project method:

- [`docs/CI_TEST_OPTIMIZATION_PLAYBOOK.md`](../CI_TEST_OPTIMIZATION_PLAYBOOK.md)

Accepted implementation PRs:

- #397 — Windows launcher safety harness deduplication;
- #399 — Windows timezone lane narrowed to Windows-specific coverage;
- #401 — Synthetic visual audit moved to two Playwright workers with coverage unchanged.

Historical outcome:

- 0 regression tests intentionally deleted;
- 116 redundant test/scenario executions removed from a normal full CI run relative to the pre-pass configuration;
- whole-CI observations moved from roughly 7–9 minutes before the pass to roughly 3.5 minutes at closeout, with normal hosted-runner variance;
- further launcher optimization was intentionally stopped because the next identified safe opportunity was only an estimated 5–20 seconds and would add fixture complexity.

This file is a compact history index. Detailed evidence and caveats live in the closeout document above.
