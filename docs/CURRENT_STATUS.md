# Hermes Finance — current status

Updated **2026-10-09** from live GitHub and explicitly attributed Owner-local reports. Latest coordination: [#554](https://github.com/LTstripes/hermes-finance/issues/554). Restart brief: [2026-10-09 checkpoint](SESSION_CLOSEOUT_2026-10-09.md). Older closeouts retain dated evidence, not current assignments.

## Current priority and product boundary

**First implementation: remove obsolete mobile checks (#747). Main financial outcome: first verified real brokerage-account XIRR (#749 / #709), initially 2026-08-31 through 2026-09-30.** Do not substitute cosmetic completion, a successful import or another broad audit for that outcome. Correct zero/loss is valid; the goal is a trustworthy number, not a positive one.

Hermes is **Windows laptop / desktop-browser only**. #746 integrated the Owner decision in MASTER_SPEC and VERIFICATION_POLICY. No phone/390px design or Owner UAT requirement. #747 now explicitly removes obsolete mobile-only test variants, data/expected images and redundant checks while retaining unique financial behavior on desktop. Existing responsive production CSS is not removed merely because it also handles narrow windows.

## Release, main and Test are different

| Surface | Verified checkpoint and limits |
| --- | --- |
| Published release | v1.2.0, source `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`; [release record](releases/1.2.0.md). No newer release authorized by this checkpoint. |
| Canonical main before this docs refresh | `65f1e811971019e2eadda6b20657eb2b86edaf7b`; [exact-main CI 37956819377](https://github.com/LTstripes/hermes-finance/actions/runs/37956819377) SUCCESS. Includes #740/#741, #742 status, #745 real-screenshot policy and #746 desktop-only policy. Read live main after any later merge. |
| Open implementation PR | [#744](https://github.com/LTstripes/hermes-finance/pull/744), DRAFT/unmerged, exact head `20c2c4d45832b3c94a15de8720240815fcba705b`; #743 stays OPEN. |
| Local Stable | Prior Owner-local preflight reported checkout at the published v1.2.0 SHA. Separate production Start/health/data-continuity proof remains unrecorded. Do not say the code is still v1.1.0; do not turn this narrower evidence gap into a repeated Owner chore. Owner declined an unnecessary standalone Stable check. |
| Persistent Test | Owner's OPS03 returned PASS at the exact #744 head above, DB_unchanged=true; schema 0054 retained. Owner then started Test and supplied real desktop screenshots. This is not a deployment to Stable; current running/stopped state must be checked locally before any operation. |

A documentation merge changes neither Owner runtime. Do not repin or rebuild Test just to follow docs. Never copy Test SQLite into Stable. Future release, Stable backup-first update, Start and production imports need their own approval and evidence.

## CI / independent review — not Owner UAT

| Slice | GitHub evidence |
| --- | --- |
| #740 combined REPO + explicit archived Skip | Merged `5144b71b05537a540b2ac11ae9e66ea751bb1446`; post-main [37827387788](https://github.com/LTstripes/hermes-finance/actions/runs/37827387788) SUCCESS; #736/#738 CLOSED. #737/#739 closed as superseded, not separately merged. |
| #741 H0 performance | Merged `e2864668a7357365656ace4ac681288313d0ee9f`; post-main [37835529213](https://github.com/LTstripes/hermes-finance/actions/runs/37835529213) SUCCESS. |
| #744 current UI candidate | [Product 37946758389](https://github.com/LTstripes/hermes-finance/actions/runs/37946758389) SUCCESS; [UI 37946758362](https://github.com/LTstripes/hermes-finance/actions/runs/37946758362) SUCCESS; [independent review 5471760064](https://github.com/LTstripes/hermes-finance/pull/744#pullrequestreview-5471760064) ACCEPT for Test UAT. Initial-head review/runs are historical, not current-head checks. |

Failed helper/controller setup attempts did not inspect source and remain UNVERIFIED. A separate GitHub-native independent review need not rerun all tests or repair that runtime. Any changed executable candidate requires its own applicable checks and accurately attributed review.

## Owner-local acceptance — bounded findings

- **Source journey PASS:** original XML 1/2/4 Preview, explicit Skip, Apply, independent GET, fresh-visit replay/dedup and preservation of previous reports. Combined #740's source/diagnostic UAT is not positive historical return acceptance.
- **H0 read-only UAT PASS:** original Test API returned complete HTTP 200 in 0.538s and 0.524s with equal bodies/digests, unchanged schema/database and existing report/source reads. Old timed-out H0 produced no complete response for old-vs-new comparison. Separate ordinary shutdown smoke was not established by that read-only probe.
- **Data-fidelity audit PASS, financial completeness unproven:** local operator reported 10 accounts, 803 read-only API checks, 2,637 source numeric fields and 124 S2 core facts without detected discrepancies; 18 earlier report responses preserved. All 770 inspected account/portfolio/class return contexts were not_computable/null. This is source-number/ledger-arithmetic evidence, not total portfolio completeness.
- **#744 desktop UAT PARTIAL:** final-head OPS03 and screen loading observed; account/class diagnostic screenshots and Files reviewed. Final expanded preparation form, both native v2 month links and Back are not yet confirmed. Do not merge/close #743 from a table-only screenshot. No real financial attestations or CLOSED Reopen were accepted.

Real screenshots of ordinary financial values may be inspected in the authorized private assistant/UAT session under current AGENTS; no special viewer or per-image monetary redaction gate. Do not automatically publish screenshots, secrets, full databases or raw broker exports to public Git/CI.

## First XIRR — actual remaining work

Existing account/portfolio solvers and monthly Performance are implemented. **The monthly evidence path is tried first; historical H1/H2/H3 is a fallback**, as implemented in `services/portfolio_xirr.py`. Missing historical H1/H2 tables alone do not prove that every account/month requires new historical acceptance. Check the chosen path rather than demanding all layers indiscriminately.

For one exact account/interval, establish complete boundary valuations including cash, all external flows and applicable noncash evidence, historical scope, and reconciliation. Distinguish already present facts needing acceptance from genuinely missing source/implementation. Trades inside an account are not Owner deposits; source settlement/fee details need their accepted meaning, not heuristics. #715 already defines S2-B fee/event-C1 work; use it only if necessary for the selected interval.

Relevant Skip and unsupported REPO remain independent blockers. Merely shortening dates, adding old instruments, or revoking a Skip does not erase its accepted lifecycle impact. Skip-to-map correction or same-account non-impact proof needs its own accepted source-backed contract. Previously confirmed exact account aliases remain Owner decisions; do not strip suffixes generically or ask for the same mapping again. The Owner-designated empty source stays excluded only while actually empty.

**#749 produces one exact private input schedule, verified reference XIRR if possible, and a consolidated supported acceptance/repair package.** It does not perform financial writes. Subsequent Owner-approved Apply/GET must make the same account's Hermes API/UI genuinely numeric before declaring first-XIRR delivery. TWRR PRE/POST, class no-crossing and full two-year reconstruction are not automatic prerequisites for account XIRR.

## Assigned order and parallelism

| Task | When / boundary |
| --- | --- |
| [#747 mobile-test retirement](https://github.com/LTstripes/hermes-finance/issues/747) | FIRST code task, from live main after docs refresh. Does not wait for #744. Only tests/associated mobile fixtures/check references and necessary active test documentation. |
| [#749 first-XIRR input/acceptance package](https://github.com/LTstripes/hermes-finance/issues/749) | Can run alongside #747: Owner-local read-only, reuses prior audit, no repository edits or second heavy suite. |
| [#748 account-readiness rows](https://github.com/LTstripes/hermes-finance/issues/748) | Start implementation AFTER #747 merge; independent of financial acceptance. Makes accounts inspectable, not their return computable. |
| #743 / #744 existing UX | Frozen candidate awaiting remaining desktop UAT. Integrator reconciles its shared visual-test file after #747, preserving new desktop assertions without reintroducing phone cases. |

No parallel writers to the same physical checkout. One heavy local verification at a time. No second broad financial audit. Short launch prompts (normally 5–10 lines), difficulty and model/effort for routing only; no Model evidence or model benchmarks. Simple local actions go directly to Owner as one or two PowerShell commands rather than starting Codex for a trivial action.

## Other retained backlog and completed work

#711 source-first roadmap, #714 bank/deposit source research, #646 documented Alfa PRO token compatibility, #389 future composer; none is an immediate prerequisite of the selected account pilot. #124 is permanent release control, #554 coordination. Alfa remains externally unresolved, not a guessed protocol fix. No new provider investigation/monitoring is authorized here.

Class no-crossing Phase 1 (#696/#698/#535/#540) and #705/#706 evidence-entry UI are integrated after v1.2.0. Exact class returns still need their historical class/whole-universe inventory/no-crossing evidence. Deposits, FX and general flow-bearing class TWRR remain outside that delivered subset. See [class contract](performance/ASSET_CLASS_RETURNS_CONTRACT.md), [C1](performance/POSITION_CLASS_IDENTITY.md), [C2/C3](performance/CLASS_NO_CROSSING_ENDPOINTS.md), [API](performance/CLASS_RETURNS_API.md).

#572's older common UI/monthly-close Owner PASS retains documented limitations; do not repeat the whole route. #679/#666 relocation/legacy cleanup, #629 Launcher retirement and earlier CI optimization are complete. Active Ops, Stable/Main/Test/Owner, backups and other projects remain protected; this checkpoint authorizes no cleanup there. [Layout](OWNER_MACHINE_LAYOUT.md), [runtime operations](OWNER_RUNTIME_OPERATIONS.md), [janitor](WORKSPACE_JANITOR.md) and dated [CI history](history/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-10-04.md) retain details. Old runtime-release pins inside dated sections are historical, not a substitute for this checkpoint.

[AGENTS](../AGENTS.md), [verification](VERIFICATION_POLICY.md) and [integration](AGENT_ORCHESTRATION.md) govern execution. No Stable update, new release, financial/data mutation or #744 merge is performed by this documentation refresh.
