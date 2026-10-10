# Hermes Finance - current status

Repository checkpoint **2026-10-10**, baseline `59e699bb49f25e6a2b1bf5a233370174b226b848`.
Session closeout: [2026-10-10](SESSION_CLOSEOUT_2026-10-10.md); new sessions must recheck live GitHub and Owner-local Test evidence.
This is the single maintained project-status snapshot. Live GitHub refs/checks establish repository identity;
each issue and its latest accepted Integrator note own that task's assignment.
[#554](https://github.com/LTstripes/hermes-finance/issues/554) is the coordination entrypoint.
[PROJECT_WIKI](PROJECT_WIKI.md) holds durable concepts; dated closeouts preserve the evidence observed then.
Update this checkpoint when an outcome, boundary, selected assignment or remaining gate changes, not for every handoff or poll.

## Repository, release and runtime evidence

| Surface | Verified checkpoint / remaining limit |
| --- | --- |
| Canonical main | `59e699bb49f25e6a2b1bf5a233370174b226b848`; exact-main [CI 38034464413](https://github.com/LTstripes/hermes-finance/actions/runs/38034464413) SUCCESS. Includes #751 (#747 desktop-only test cleanup), #754 (#753 BOM/wrong-DB protection), #755 (Owner-data/verification rules), and #761 (#752 append-only Skip-to-Map correction). Documentation-only #750 and other non-overlapping docs/CI commits are also integrated. |
| Published release | v1.2.0, source `8a0cb257da6ca6a661eb5044d0dd72dac28d90fc`; [release record](releases/1.2.0.md). Development merges do not publish or install a release. |
| Stable | Earlier Owner-local preflight reported checkout at the v1.2.0 source. Separate production Start/data-continuity proof remains unrecorded. Owner declined a redundant standalone version check. |
| Test | Earlier OPS03 PASS at #744 head `20c2c4d45832b3c94a15de8720240815fcba705b`, schema 0054, with previously observed desktop screens. A later Test process opened the WRONG default DB: a UTF-8 BOM hid the explicit .env database setting. Owner-local #752 operator independently confirmed the original protected Test DB identity/hash and retained 3 nonempty MyBroker imports / 19 Skip decisions; those facts are operator-reported, not a current live runtime proof. #754 has fixed the code, NOT yet the Owner-local .env/DB. A Test-only read-only preflight/config-repair task was issued and the Owner reported starting it; result remains PENDING. Migration 0054→0055/financial Apply is not authorized by that read-only task. |

No runtime operation, release, merge or financial write is performed by this status update.
Do not repin Test for a prose change or copy Test SQLite into Stable.

## Active work and remaining gates

| Task | Current result / next gate |
| --- | --- |
| [#747](https://github.com/LTstripes/hermes-finance/issues/747) / [#751](https://github.com/LTstripes/hermes-finance/pull/751) | **CLOSED COMPLETE.** Review ACCEPT, candidate [CI 37968511581](https://github.com/LTstripes/hermes-finance/actions/runs/37968511581), [UI evidence 37968511486](https://github.com/LTstripes/hermes-finance/actions/runs/37968511486), exact-main [CI 37971086613](https://github.com/LTstripes/hermes-finance/actions/runs/37971086613) all SUCCESS. Obsolete phone/390px scenarios retired without deleting desktop financial/real-backend assertions. Discovered visual 297→255 and default 128→102 slots; do not claim an unmeasured runtime speedup. No Owner UAT required for tests/docs-only scope. |
| [#752](https://github.com/LTstripes/hermes-finance/issues/752) / [#761](https://github.com/LTstripes/hermes-finance/pull/761) | **CODE ACCEPT / MERGED**, issue remains OPEN for Owner-local financial acceptance. Independent contract READY; exact candidate `601e38e...`, [Integrator review 5478129447](https://github.com/LTstripes/hermes-finance/pull/761#pullrequestreview-5478129447), [PR CI 38033227817](https://github.com/LTstripes/hermes-finance/actions/runs/38033227817) SUCCESS; exact-main [CI 38034464413](https://github.com/LTstripes/hermes-finance/actions/runs/38034464413) SUCCESS. Migration 0055 adds empty append-only Skip→Map correction receipt/revisions, batch Preview→atomic Apply→GET, shared S1/S2/H0/H1/H2/Performance resolver. No actual Owner DB migration, correction, source reimport or numeric XIRR yet. |
| [#753](https://github.com/LTstripes/hermes-finance/issues/753) / [#754](https://github.com/LTstripes/hermes-finance/pull/754) | **CLOSED for CODE.** UTF-8 BOM .env handling and pinned Test DB boundary passed [PR CI 37999255603](https://github.com/LTstripes/hermes-finance/actions/runs/37999255603) and [main CI 38000839316](https://github.com/LTstripes/hermes-finance/actions/runs/38000839316). A merge does not correct Owner's existing unpinned Test config; protected Test DB identity/Start readback is pending its dedicated local task. |
| [#749](https://github.com/LTstripes/hermes-finance/issues/749) / [#709](https://github.com/LTstripes/hermes-finance/issues/709) | First real brokerage-account XIRR (initially 2026-08-31→2026-09-30 on a least-blocked brokerage account) remains unproven. Reuse the bounded private #749 source dossier, and try the accepted monthly Performance path before historical H1/H2 fallback. Verify exact two full-account endpoints and dated external/noncash flows; no positive rate merely because Skip→Map code merged. |
| [#748](https://github.com/LTstripes/hermes-finance/issues/748) | Its #747 code-merge dependency is satisfied. No implementation PR observed at this checkpoint. Use its accepted issue contract for assignment; readable readiness rows do not grant financial completeness. |
| [#743](https://github.com/LTstripes/hermes-finance/issues/743) / [#744](https://github.com/LTstripes/hermes-finance/pull/744) | DRAFT/unmerged at `20c2c4d45832b3c94a15de8720240815fcba705b`. [Product CI](https://github.com/LTstripes/hermes-finance/actions/runs/37946758389), [UI evidence](https://github.com/LTstripes/hermes-finance/actions/runs/37946758362) SUCCESS; [independent review](https://github.com/LTstripes/hermes-finance/pull/744#pullrequestreview-5471760064) ACCEPT for Test UAT. Expanded preparation form and both v2 month-link/Back checks remain unconfirmed. Integrator owns reconciliation against merged desktop tests and any changed-candidate gates. |

Contract READY, code delivery, independent review, Integrator acceptance, Owner UAT and integration are distinct results. For #752, code is integrated but protected Test data and numeric performance remain unaccepted.
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
**Source population is NOT correction population:** 40 source ISINs = 18 existing exact-ISIN reuses + 4 existing-card metadata enrichments + 17 missing historical instruments + 1 existing restricted fund needing identity/type review. The actual correction is **19 source-specific Skip decisions / 18 distinct ISINs** (18 decisions for the 17 missing historical identities, one for the restricted fund). Existing three inactive likely duplicate catalogue cards are not deleted.

Catalogue/registry preparation is separate from correction. Existing SQL mapping triggers retire prior accepted Skip revisions; the new mechanism requires a **fresh whole-batch post-preparation Preview**, then an independently approved real Apply/GET. A full 19-decision batch refuses if restricted-fund identity/type is unresolved; an 18/17 tranche requires independent accepted scope/overlap proof and may not erase the fund's retained blocker. Original source/Skip history is immutable. No real financial Apply, attestation, reimport, schema migration or CLOSED Reopen follows from GitHub code integration.

The current **next Owner-local step** is the already-launched read-only Test DB/.env preflight. Wait for its actual PASS/BLOCKED and protected file/backup identity proof; do not assume the local laptop was repaired, reissue another preflight or write schema/source data blindly. Afterwards stage reviewed 0054→0055 migration/catalogue preparation only under an exact scoped approval, preserve Stable and CLOSED, and eventually verify source/receipt/deposit continuity and real #749 XIRR.

[#711](https://github.com/LTstripes/hermes-finance/issues/711), [#714](https://github.com/LTstripes/hermes-finance/issues/714),
[#646](https://github.com/LTstripes/hermes-finance/issues/646) and [#389](https://github.com/LTstripes/hermes-finance/issues/389)
remain separate backlog; [#124](https://github.com/LTstripes/hermes-finance/issues/124) is release control.
Runtime relocation/cleanup, Launcher retirement and prior CI work are historical deliveries, not new instructions.

[AGENTS](../AGENTS.md), [Owner-data workflow](OWNER_DATA_WORKFLOW.md), [verification](VERIFICATION_POLICY.md),
[risk/review](MODEL_ROUTING.md) and [runtime operations](OWNER_RUNTIME_OPERATIONS.md) retain their authority.
This task uses synthetic code checks only; no Owner data or installed-app changes are assigned.
