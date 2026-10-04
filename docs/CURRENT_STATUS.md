# Hermes Finance — current status

Owner/Integrator session closeout, **2026-10-04**. Live GitHub refs and completed CI are authoritative. Published release, development main and local runtime are different states. Current coordination: [#554](https://github.com/LTstripes/hermes-finance/issues/554); restart brief: [session closeout](SESSION_CLOSEOUT_2026-10-03.md).

## Published Stable and development

Published release is **v1.2.0**, commit `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`, annotated tag object `f9311d26c1aae7295361937096844f4dde615b55`. Canonical exact-main CI `37206069556` completed SUCCESS on rerun attempt 2 after one transient `ECONNRESET` in the G04/Performance job; only that failed job was rerun and passed. Guarded Release `37206660242` succeeded. The last locally confirmed Stable remains **v1.1.0** until the Owner runs backup-first OPS02 for 1.2.0; publication and installation are separate. [Release record](releases/1.2.0.md) retains publication evidence.

#572 is CLOSED: **Owner PASS WITH DOCUMENTED LIMITATIONS**, including manual/v1 use. This is not all-native/all-provider success or proof that every XIRR/TWRR is available on personal history. The pre-publication deferral is historical, superseded by [actual acceptance](https://github.com/LTstripes/hermes-finance/issues/572#issuecomment-5937693786).

Published release checkpoint: `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc` / v1.2.0. Release-preparation PR #693 exact-head CI `37205737199` and UI comparison `37205737191` succeeded; canonical CI and guarded publication are recorded above. Any later docs-only closeout merge may advance `main` without changing the immutable release tag.

## Owner filesystem and scheduled cleanup — completed

**#679 and #666 are CLOSED / COMPLETE. Do not restart inventory, migration, rollback rehearsals or legacy cleanup.** [Final operational report](https://github.com/LTstripes/hermes-finance/issues/679#issuecomment-5973182455).

- `<HERMES_ROOT>/stable`: whole production runtime was moved and last confirmed on exact v1.1.0 with DB identity/content/schema preserved and Start/readiness PASS. Owner-selected v1.2.0 is now published; the local Stable transition is the next explicit backup-first OPS02 operation.
- `<HERMES_ROOT>/main`: canonical code-only checkout, the former Control role. A remote documentation merge does not automatically update this local checkout.
- `<HERMES_ROOT>/test`: persistent reusable isolated Preview/UAT folder. Last reported pin remains `d282d09647f129cd83c99e14a10024901a1cf6da`. Data isolation is proven; Test was not started while Stable owned port 8000.
- `<HERMES_ROOT>/owner` and the four `workspaces/<client>` roots are retained. Client roots were already configured; no reconfiguration is pending.
- All 54 residual Access Denied targets were removed; the two old partial roots are gone. Reported free-space increases were 35,197,726,720 bytes and another 1,345,101,824 bytes: approximately **34.03 GiB in total**, a sum of two reported measurements, not a fresh disk audit.
- Local Launcher/config and shortcuts are removed. Repository Launcher source/package/tests/workflows were retired by #629/#689 at merge `29b2ecf6c61a86fb5da03c48585b92358f38e890`; direct Prepare/Validate/Start, Windows production smoke, backup-first Stable update, recovery protections and the Finance Ops janitor remain supported.
- PR #684 merged layout documentation; PR #685 merged and deployed the Finance janitor. Scheduled Task `Hermes Finance workspace cleanup`: Enabled/Ready, daily 12:00 local, Apply, retention 7 days, IgnoreNew, StartWhenAvailable. First planned automatic run at closeout: 2026-10-04 12:00 Europe/Moscow.
- Post-deployment dry-run: complete/exit 0, **8 PRESERVE, 0 deletions** (seven private-marker holds, one filesystem/check-unknown). This proves deployment/dry-run, not an already successful scheduled deletion or guaranteed removal on day seven.

Important exception to the simple root diagram: the deployed janitor and report live under the separate **`<FINANCE_CONTAINER>/ops`** boundary. Preserve this active operational directory. Being outside `<HERMES_ROOT>` is not, by itself, deletion authority. See [machine layout](OWNER_MACHINE_LAYOUT.md) and [janitor](WORKSPACE_JANITOR.md).

## Post-v1.1.0 product wave — integrated and published in v1.2.0

Owner-tested aggregate `d282d09647f129cd83c99e14a10024901a1cf6da`, tree `cf39e2c933f78691e7ec0db14872f640df903ec5`, passed CI `37108969114` and UI `37108969154`. [#662 Owner acceptance](https://github.com/LTstripes/hermes-finance/pull/662#issuecomment-5967980369) authorized integration with documented UX follow-ups. The accepted wave plus later #667, CI/runtime maintenance and Launcher retirement are now packaged in published v1.2.0.

| Slice | Delivered result | Retained limit |
| --- | --- | --- |
| #647 | Exact-month navigation, direct final review, local reread, Settings/Diagnostics | Month-list follow-up #667 is implemented via #674; a separate focused Owner retest is not recorded in this session |
| #648 | Collapsed future-payout groups, bulk and individual Apply | Per-group atomicity and no blind retry of ambiguous submissions |
| #649 | Verified contextual quote mapping, exception-first Alfa, origin/saved/freshness | Does not establish a fix/root cause for #646; later live evidence shows the 3366 Trading core can be switched Online and a read-only API token can be issued, but current Hermes still rejects the resulting protocol as unrecognized |
| #650 | Money units, stacked debt/link editors, saved-only totals | Mutation/readback/CLOSED semantics unchanged |
| #651 | Fixed-set linked-account/debt explanation | Copy follow-up #672 merged; no financial formula change |
| #645 | Server-owned current-day LAST Preview evidence | Historical Owner quote PASS is not live same-day LAST evidence |

Native parity #570/#571/#643 and original #572 are complete. Portfolio/account Performance Phase A is delivered. #541 and the parent #528 are CLOSED after Phase A coordination; any later focused real-history portfolio/account check is coordinated only through #554. Exact asset-class XIRR/TWRR remains a separate deferred Phase B in #535/#540, blocked on the accepted #534 evidence prerequisites C1–C5 rather than on missing UI work. [Dated product closeout](POST_RELEASE_UAT_CLOSEOUT_2026-10-03.md) remains evidence, not a new execution queue.

## Tests/CI — optimization wave complete

The 2026-10-03/04 CI/test stream is complete. No separate test/CI implementation issue remains queued after this closeout.

| Item | Final state |
| --- | --- |
| #671 / #681 | Merged: a newer ordinary PR run cancels only the older run of the same repository/workflow/PR; canonical main, release and protected integration work are isolated |
| #668 / #682 | Merged: fixed-viewport-owned visual cases execute once while unique project-viewport coverage remains |
| #669 / #683 | Merged at 56d6750a6f13d467d497762b77925d07e3ef21ef; exact-head UI evidence remains separate and CI omits the overlapping 1440 set only on proved tree equivalence |
| #670 / #686 | Merged at d8c7ec95024e7cb3ff906901512681c48e6dc83a; fail-closed docs-only PR classification skips product suites only for explicit non-executable prose |
| #629 / #689 | Merged at 29b2ecf6c61a86fb5da03c48585b92358f38e890; Launcher GUI/package/tests/jobs retired, shared direct runtime/recovery boundaries preserved through the direct-operations runtime inventory |

Measured evidence from the accepted candidates:
- #668 reduced scheduled visual executions **345 → 287** (−58 / 16.8%) while preserving **115** unique scenario titles, the **97-test** evidence selection and the **58-file** 1440 screenshot set.
- #669 reduces normal visual CI **287 → 190** when head/merge/checkout trees are proven equivalent, while the separate **97-test** exact-head evidence run remains. A mismatch or incomplete identity proof falls back to full coverage.
- #670 controlled proof PR #687 (4c96fb74a1cf4b7f32b0f44bfc8a8d2bb2fb5a8b, CI 37183515223) completed docs-only CI in about **21 seconds** with product jobs terminal-skipped; the implementation PR itself stayed full and canonical main remains full.
- #629 PR #689 removed the retired Launcher maintenance surface: **41 files, +112/−7000** in the final PR while preserving direct Windows/runtime/recovery checks.

The earlier September optimization closeout remains historical evidence; this later wave is summarized in [the 2026-10-04 closeout](history/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-10-04.md). Normal handoffs no longer request model/provider evidence, benchmark grades or telemetry; model selection remains routing only (#669/#605 decision, current AGENTS).
## Grok maintenance and next decisions

#663 version/current-doc sync, #664 Actions SHA pinning, #665 LF/Node guard and #672 Home wording are merged. Recommended frontend Node remains 22.23.1; AI export schema is independently 1.3.0. Do not reopen these as new tasks or replace guarded #124 release triggering.

No dedicated test/CI task is queued after this closeout. Remaining product/Owner choices are #535/#540 exact asset-class returns, #646 Alfa PRO compatibility follow-up and #389 composer. The previously prepared focused #667 + portfolio/account Performance Test route remains available in #554, but Owner has deferred that combined UAT for now to avoid repeating it before the Alfa situation settles.

#630 representative synthetic stand, #573 v1-retirement gate and historical umbrella #127 are CLOSED / NOT_PLANNED; #528 is CLOSED / COMPLETED for Phase A coordination. SQLite date-binding warnings, OpenAPI/pyright pilots and branch cleanup remain optional ideas rather than active backlog. `/v1` remains intentionally available. #124 is permanent release infrastructure; #554 is the current coordination issue.

## Operating boundaries

[AGENTS](../AGENTS.md), [verification](VERIFICATION_POLICY.md), [routing](MODEL_ROUTING.md) and [runtime operations](OWNER_RUNTIME_OPERATIONS.md) remain authoritative. One physical workspace per task; one heavyweight local verification process across projects. Ordinary tasks use synthetic data; private runtime payloads never enter Git/CI/agent artifacts. Explicit Owner-local operations stay bounded to their authorization. No automatic next task, release, runtime promotion or broad deletion follows from this closeout.
