# Hermes Finance — current status

Owner/Integrator session closeout, **2026-10-03**. Live GitHub refs and completed CI are authoritative. Published release, development main and local runtime are different states. Current coordination: [#554](https://github.com/LTstripes/hermes-finance/issues/554); restart brief: [session closeout](SESSION_CLOSEOUT_2026-10-03.md).

## Published Stable and development

Published and locally confirmed Stable remains **v1.1.0**, commit `32c905cfc938fd1aeaeb67643eb6fa77e8644a64`, tree `7f5a3198fa650b71545550301063c9afd887f8f8`, annotated tag object `9b402190bafc5d8415b217580da5e18ed35a6331`. Release push CI `36776904188` and Guarded Release `36777962224` succeeded. #643/#644 and [the release record](releases/1.1.0.md) retain publication evidence.

#572 is CLOSED: **Owner PASS WITH DOCUMENTED LIMITATIONS**, including manual/v1 use. This is not all-native/all-provider success or proof that every XIRR/TWRR is available on personal history. The pre-publication deferral is historical, superseded by [actual acceptance](https://github.com/LTstripes/hermes-finance/issues/572#issuecomment-5937693786).

Development checkpoint before this documentation closeout: `8eb991fc81ebbe63917a9ca1ea204762129c9019`, exact-main push CI `37150791634` SUCCESS. It includes #683 and #685. This is a milestone, not a moving HEAD alias. No new release or Stable version promotion was performed during the filesystem migration or this documentation closeout.

## Owner filesystem and scheduled cleanup — completed

**#679 and #666 are CLOSED / COMPLETE. Do not restart inventory, migration, rollback rehearsals or legacy cleanup.** [Final operational report](https://github.com/LTstripes/hermes-finance/issues/679#issuecomment-5973182455).

- `<HERMES_ROOT>/stable`: whole production runtime moved; exact v1.1.0, DB identity/content/schema preserved, destination Python environment re-prepared, Start/readiness PASS.
- `<HERMES_ROOT>/main`: canonical code-only checkout, the former Control role. A remote documentation merge does not automatically update this local checkout.
- `<HERMES_ROOT>/test`: persistent reusable isolated Preview/UAT folder. Last reported pin remains `d282d09647f129cd83c99e14a10024901a1cf6da`. Data isolation is proven; Test was not started while Stable owned port 8000.
- `<HERMES_ROOT>/owner` and the four `workspaces/<client>` roots are retained. Client roots were already configured; no reconfiguration is pending.
- All 54 residual Access Denied targets were removed; the two old partial roots are gone. Reported free-space increases were 35,197,726,720 bytes and another 1,345,101,824 bytes: approximately **34.03 GiB in total**, a sum of two reported measurements, not a fresh disk audit.
- Local Launcher/config and shortcuts are removed. **Repository Launcher source/tests/workflow retirement remains #629**, not completed by deleting the installed shell.
- PR #684 merged layout documentation; PR #685 merged and deployed the Finance janitor. Scheduled Task `Hermes Finance workspace cleanup`: Enabled/Ready, daily 12:00 local, Apply, retention 7 days, IgnoreNew, StartWhenAvailable. First planned automatic run at closeout: 2026-10-04 12:00 Europe/Moscow.
- Post-deployment dry-run: complete/exit 0, **8 PRESERVE, 0 deletions** (seven private-marker holds, one filesystem/check-unknown). This proves deployment/dry-run, not an already successful scheduled deletion or guaranteed removal on day seven.

Important exception to the simple root diagram: the deployed janitor and report live under the separate **`<FINANCE_CONTAINER>/ops`** boundary. Preserve this active operational directory. Being outside `<HERMES_ROOT>` is not, by itself, deletion authority. See [machine layout](OWNER_MACHINE_LAYOUT.md) and [janitor](WORKSPACE_JANITOR.md).

## Post-release product wave — integrated, not newly released

Owner-tested aggregate `d282d09647f129cd83c99e14a10024901a1cf6da`, tree `cf39e2c933f78691e7ec0db14872f640df903ec5`, passed CI `37108969114` and UI `37108969154`. [#662 Owner acceptance](https://github.com/LTstripes/hermes-finance/pull/662#issuecomment-5967980369) authorized integration with documented UX follow-ups. Merge `a0396e9971be119038b8c28d29398191449b0c0c` passed canonical CI `37114728212`.

| Slice | Delivered result | Retained limit |
| --- | --- | --- |
| #647 | Exact-month navigation, direct final review, local reread, Settings/Diagnostics | Month-list follow-up #667 is implemented via #674; a separate focused Owner retest is not recorded in this session |
| #648 | Collapsed future-payout groups, bulk and individual Apply | Per-group atomicity and no blind retry of ambiguous submissions |
| #649 | Verified contextual quote mapping, exception-first Alfa, origin/saved/freshness | Does not establish a fix/root cause for #646 |
| #650 | Money units, stacked debt/link editors, saved-only totals | Mutation/readback/CLOSED semantics unchanged |
| #651 | Fixed-set linked-account/debt explanation | Copy follow-up #672 merged; no financial formula change |
| #645 | Server-owned current-day LAST Preview evidence | Historical Owner quote PASS is not live same-day LAST evidence |

Native parity #570/#571/#643 and original #572 are complete. Portfolio/account Performance Phase A is delivered. #541 still coordinates its remaining verification/Phase B scope; #535/#540 class returns are not silently implemented. [Dated product closeout](POST_RELEASE_UAT_CLOSEOUT_2026-10-03.md) remains evidence, not a new execution queue.

## Tests/CI — parallel stream, one workflow writer

| Item | Verified state at closeout |
| --- | --- |
| #671 / #681 | Merged: cancel superseded ordinary PR runs, not canonical main/release or protected integration runs |
| #668 / #682 | Merged: remove duplicate fixed-viewport executions, retain unique scenarios and actual viewport coverage |
| #669 / #683 | Merged at `56d6750a6f13d467d497762b77925d07e3ef21ef`: exact-head UI producer retained; CI omits only proved equivalent repeated executions. Issue administration may still be open; do not reimplement |
| #670 | Remaining docs-only PR fast path; verify current assignment in the parallel test session before proposing work |

This documentation closeout does not modify workflows/classifiers/tests or take over that stream. Serialize #629 workflow removals with #670. Main/release coverage remains required. Normal handoffs no longer request model/provider evidence, benchmark grades or telemetry; model selection remains routing only (#669/#605 decision, current AGENTS).

## Grok maintenance and next decisions

#663 version/current-doc sync, #664 Actions SHA pinning, #665 LF/Node guard and #672 Home wording are merged. Recommended frontend Node remains 22.23.1; AI export schema is independently 1.3.0. Do not reopen these as new tasks or replace guarded #124 release triggering.

Next product/technical choice: **#629 repository Launcher retirement** after coordinating CI ownership. In parallel, a read-only dependency/removal map can be prepared without changing shared workflows. Then consider a single refreshed Test for focused #667 retest and the remaining portfolio/account Performance Owner checks; do not repeat the whole accepted #662 route without a new risk.

#646 remains a bounded Alfa transport/vendor question, not an automatic port-hunting exercise. #630 representative synthetic stand, SQLite date-binding warnings, OpenAPI/pyright pilots and branch cleanup remain deferred/optional. #535/#540 class returns and #389 composer are not launched. `/v1` remains available; #573 retirement is not authorized. #124 is permanent infrastructure; #127/#528/#554 are coordination issues.

## Operating boundaries

[AGENTS](../AGENTS.md), [verification](VERIFICATION_POLICY.md), [routing](MODEL_ROUTING.md) and [runtime operations](OWNER_RUNTIME_OPERATIONS.md) remain authoritative. One physical workspace per task; one heavyweight local verification process across projects. Ordinary tasks use synthetic data; private runtime payloads never enter Git/CI/agent artifacts. Explicit Owner-local operations stay bounded to their authorization. No automatic next task, release, runtime promotion or broad deletion follows from this closeout.
