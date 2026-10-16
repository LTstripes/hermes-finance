# Synthetic desktop evidence for #839

Source candidate: `b2a2cdd20b0aaa88a4c46e4cd32c6267f8e936b1`.
Base: `461c2f3f44a599b87c0429739ea03ae00a78fd83`.

These are actual Chromium Linux captures of the built frontend served by a
real disposable synthetic backend, viewport 1440 × 1000, normal zoom.
No Owner original, database, runtime, values or private path is used.
The source fixtures are fabricated retained test fixtures.

- [Included candidate: 211 RUB / 2.01%](included-1440.png).
- [Excluded candidate: 1,211 RUB / 12.11%](excluded-1440.png).
- [Source/tree, production-dist manifest and PNG hashes](provenance.json).

Worker inspected the pixels; independent visual inspection is recorded in the
Draft PR review. Actual S3 remains unavailable. The browser journey also verifies
missing choices, exact fresh JSON-download parity and refresh invalidation.
These are distinct scenarios, not confidence bounds on actual performance.

Checks on the source candidate: 45 WHAT-IF backend regressions and one real-backend
desktop journey. Retained Close/XIRR/TWRR: 75 passed. Prior source `4191820` passed
84 combined WHAT-IF/S3 tests, 22 component tests and the frontend build; the entire
frontend diff to this source is empty, so that component/build evidence is reused.
The remediation adds real effective H2 withdrawal, malformed source/upload, coupon
staleness and explicit exact XIRR/TWRR/Close response isolation coverage.
A docs/evidence-only successor may reuse this evidence when its executable diff
is empty; the final Draft PR records the exact candidate and CI status.
Windows visual UAT and actual financial acceptance are not claimed by these PNGs.
