# Hermes Finance - current status

Repository checkpoint **2026-10-10**, baseline `7957367b014e9ae3ab1a9645571901db0f0113a2`.
This is the single maintained project-status snapshot. Live GitHub refs/checks establish repository identity;
each issue and its latest accepted Integrator note own that task's assignment.
[#554](https://github.com/LTstripes/hermes-finance/issues/554) is the coordination entrypoint.
[PROJECT_WIKI](PROJECT_WIKI.md) holds durable concepts; dated closeouts preserve the evidence observed then.
Update this checkpoint when an outcome, boundary, selected assignment or remaining gate changes, not for every handoff or poll.

## Repository, release and runtime evidence

| Surface | Verified checkpoint / remaining limit |
| --- | --- |
| Canonical main | `7957367b014e9ae3ab1a9645571901db0f0113a2`; [CI 38001547489](https://github.com/LTstripes/hermes-finance/actions/runs/38001547489) SUCCESS. Includes [#750](https://github.com/LTstripes/hermes-finance/pull/750), [#751](https://github.com/LTstripes/hermes-finance/pull/751), [#754](https://github.com/LTstripes/hermes-finance/pull/754) and [#755](https://github.com/LTstripes/hermes-finance/pull/755). |
| Published release | v1.2.0, source `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`; [release record](releases/1.2.0.md). Development merges do not publish or install a release. |
| Stable | Earlier Owner-local preflight reported checkout at the v1.2.0 source. Separate production Start/data-continuity proof remains unrecorded. Owner declined a redundant standalone version check. |
| Test | Earlier OPS03 PASS on #744 head `20c2c4d45832b3c94a15de8720240815fcba705b`, DB_unchanged=true, schema 0054; desktop screens were observed. #754 code/CI does not prove the intended preserved Test DB/.env has been verified or repaired in the actual runtime. Running/stopped state requires observation at operation time. |

No runtime operation, release, merge or financial write is performed by this status update.
Do not repin Test for a prose change or copy Test SQLite into Stable.

## Active work and remaining gates

| Task | Current result / next gate |
| --- | --- |
| [#747](https://github.com/LTstripes/hermes-finance/issues/747) / [#751](https://github.com/LTstripes/hermes-finance/pull/751) | Code merged: phone-only test variants retired with desktop safety retained. The still-open issue's final acceptance/closeout belongs to Integrator; do not repeat implementation from its older ordering. |
| [#752](https://github.com/LTstripes/hermes-finance/issues/752) | Append-only Skip→Map [contract v2](https://github.com/LTstripes/hermes-finance/issues/752#issuecomment-6090540978) independently [READY](https://github.com/LTstripes/hermes-finance/issues/752#issuecomment-6090672906). Owner has now assigned a code-only Worker for synthetic implementation from live main. Code, exact-candidate CI and independent review are pending; protected execution is separate. |
| [#749](https://github.com/LTstripes/hermes-finance/issues/749) / [#709](https://github.com/LTstripes/hermes-finance/issues/709) | First real brokerage-account XIRR remains unproven. Reuse the bounded private dossier; resolve relevant source/catalogue/Skip dependencies, then an exact source-backed acceptance package. A private reference alone is not the same numeric Hermes API/UI result. |
| [#748](https://github.com/LTstripes/hermes-finance/issues/748) | Its #747 code-merge dependency is satisfied. No implementation PR observed at this checkpoint. Use its accepted issue contract for assignment; readable readiness rows do not grant financial completeness. |
| [#743](https://github.com/LTstripes/hermes-finance/issues/743) / [#744](https://github.com/LTstripes/hermes-finance/pull/744) | DRAFT/unmerged at `20c2c4d45832b3c94a15de8720240815fcba705b`. [Product CI](https://github.com/LTstripes/hermes-finance/actions/runs/37946758389), [UI evidence](https://github.com/LTstripes/hermes-finance/actions/runs/37946758362) SUCCESS; [independent review](https://github.com/LTstripes/hermes-finance/pull/744#pullrequestreview-5471760064) ACCEPT for Test UAT. Expanded preparation form and both v2 month-link/Back checks remain unconfirmed. Integrator owns reconciliation against merged desktop tests and any changed-candidate gates. |

Contract READY, Worker delivery, independent review, Integrator acceptance, Owner UAT and integration are distinct results.
Link concise candidate/check/review/acceptance receipts under the [existing integration procedure](AGENT_ORCHESTRATION.md#linked-handoff-receipts).
Reuse valid evidence with its original candidate and scope; do not relabel partial screenshots or skipped suites as PASS.

## Financial acceptance and preserved context

Source import/Skip journey and H0 read-only performance UAT passed for #740/#741.
The prior audit found no discrepancy in its checked source/ledger facts, while all sampled returns were unavailable:
source fidelity and arithmetic are not proof of accepted financial completeness.
[The dated 9 October checkpoint](SESSION_CLOSEOUT_2026-10-09.md) retains those measurements and original work order.

For account XIRR, try the accepted monthly path before historical H1/H2 fallback. Exact full-account endpoint
values, external flows, applicable noncash evidence, historical scope and reconciliation must be supported.
TWRR PRE/POST and class no-crossing are independent requirements, not automatic account-XIRR gates.
Catalogue preparation or retiring a Skip does not by itself restore source eligibility. #752's accepted contract
requires fresh whole-batch Preview after preparation; original source/Skip evidence stays immutable.
No real financial Apply, attestation, reimport or CLOSED Reopen follows from code or contract acceptance.

[#711](https://github.com/LTstripes/hermes-finance/issues/711), [#714](https://github.com/LTstripes/hermes-finance/issues/714),
[#646](https://github.com/LTstripes/hermes-finance/issues/646) and [#389](https://github.com/LTstripes/hermes-finance/issues/389)
remain separate backlog; [#124](https://github.com/LTstripes/hermes-finance/issues/124) is release control.
Runtime relocation/cleanup, Launcher retirement and prior CI work are historical deliveries, not new instructions.

[AGENTS](../AGENTS.md), [Owner-data workflow](OWNER_DATA_WORKFLOW.md), [verification](VERIFICATION_POLICY.md),
[risk/review](MODEL_ROUTING.md) and [runtime operations](OWNER_RUNTIME_OPERATIONS.md) retain their authority.
This task uses synthetic code checks only; no Owner data or installed-app changes are assigned.
