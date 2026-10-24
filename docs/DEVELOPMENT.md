# Development, verification and integration

Current normative handbook. Historical evidence and section-by-section provenance are in the [migration map](archive/2026-10-18/MIGRATION_MAP.md); it is not required reading for ordinary work. Current delivery/installation/task state is owned by [CURRENT_STATUS](CURRENT_STATUS.md).

[1. Roles, scope, authority and risk](#d1) | [2. Bootstrap, isolated workspace and lifecycle](#d2) | [3. API/UI implementation discipline](#d3) | [4. Verification, independent review and evidence](#d4) | [5. Delivery, integration and documentation maintenance](#d5) | [6. Optional orchestration and client mechanics](#d6)

<a id="d1"></a>
## 1. Roles, scope, authority and risk

Owner owns product direction and private/live UAT decisions. Integrator owns routing, project acceptance and authorized guarded integration. Worker is the one accountable writer for one candidate and cannot self-accept or merge. Reviewer independently assesses the candidate in a separate context without implementation ownership. Optional helpers/coordinators do not gain project authority.

Resolve current assignment/accepted Integrator decisions under the five-book contracts. A launch locates that assignment; changed requirements belong in the issue/note. Stop only at a concrete conflicting/undefined contract, new financial meaning, architecture/invariant expansion, unapproved runtime/data operation or materially larger scope. Routine reversible engineering within the assignment proceeds. No normal handoff collects model/provider identity, comparative grades or usage telemetry.

<a id="d1-agents-18"></a>
### Assignment, precedence and authority

A launch prompt locates that assignment; it is not a second specification. Record changed requirements in the authoritative issue/note.
Verification, risk/review and integration procedures have the respective owners linked above; task-specific stricter gates still apply.
the owning P/C/D/O subsection is durable context. Historical task catalogs, experiments and old release notes are not standing orders.


<a id="d1-agents-18-roles"></a>
#### Roles

- **Owner**: product direction and private/live UAT decisions.
- **Integrator**: task routing, authoritative notes, project acceptance, authorized integration and affected durable docs/history.
- **Worker**: one accountable writer for one candidate; no self-acceptance or automatic next task.
- **Reviewer**: independent candidate assessment without implementation ownership; does not silently edit the candidate.
A role is not a GitHub account. Worker self-review is not independent review; optional coordinator/helper roles are defined only in the orchestration procedure.

<a id="default-execution-mode"></a><a id="task-prompt-authority"></a>

<a id="d1-agents-18-scope-discipline"></a>
#### Scope discipline

Default: one Worker takes the assigned result through investigation, implementation, verification and authorized delivery.
Choose implementation details, add necessary regressions and fix task-caused defects without repeated approval for routine reversible steps.
Do not add unrelated cleanup or invent backlog work. Queues/orchestration require explicit opt-in.
Stop for a conflicting/undefined contract, new financial meaning, architecture/invariant expansion, data/runtime operations outside the Owner-authorized scope or materially larger scope.
Ordinary engineering choices inside the accepted contract are not scope expansion; do not turn them into approval gates.


<a id="d1-agents-18-product-and-privacy-invariants"></a>
#### Product and privacy invariants

- Local single-user Windows app, normal endpoint `127.0.0.1:8000`; loopback by default. No cloud, auth, telemetry or trading without an explicit scope decision.
- Money and rates are exact: no binary `float` in financial logic; `Decimal` calculations, integer minor-unit money storage, `ROUND_HALF_UP`.
- CLOSED reporting months are immutable until explicit reopen. The frontend is not the financial source of truth.


<a id="d1-agents-18-owner-data-and-runtime-isolation"></a>
#### Owner data and runtime isolation

Follow [Owner data authority and distinct operations](#d1-owner_data_workflow-5). Owner-requested analysis, diagnosis and UAT permit relevant real-data reads and presentation to the Owner in the authorized conversation; they do not authorize data writes, runtime changes or publication. Credentials and real `.env` contents remain excluded from output.

<a id="d1-model_routing-8"></a>
### Risk, independent review and concise launch

Select capability per task, not a permanent vendor/model/effort roster.
Independent review uses a separate context without implementation ownership; Worker self-review is not independent evidence.


<a id="d1-model_routing-8-risk-classes"></a>
#### Risk classes

| Risk | Surface | Review |
| --- | --- | --- |
| Low | Docs, bounded tests, cosmetic UI, mechanical changes | Integrator diff review is normally enough; separate review only when requested or a concrete risk warrants it. |
| Medium | Backend/frontend behavior or APIs under established contracts | Capable Worker; independent review when cross-cutting/material behavior, an explicit request or execution findings warrant it. |
| High | Financial meaning, migration/data reinterpretation, privacy/security, runtime/network, destructive Git operations, new architecture | Strong Integrator and independent Reviewer; resolve contract ambiguity before implementation. |

A faster/newer model never lowers the required review/UAT bar. Newly discovered risk may raise review requirements, not silently expand scope.
Do not add a Reviewer or coordinator merely because the task uses more than one file or includes tests.
Reviewers use the candidate's actual diff and verified check evidence; verification locality/repeats are owned by D4.


<a id="d1-model_routing-8-escalation"></a>
#### Escalation

Escalate undefined money/rate units, rounding or financial source of truth; potentially lossy migrations;
private-data requirements; changed tax/return/income/capital/goal semantics; new scope/architecture or an out-of-scope contract failure.
Ordinary implementation choices under a defined contract remain the Worker's responsibility.


<a id="d1-model_routing-8-owner-task-proposal"></a>
#### Owner task proposal

Propose in plain Russian:
1. Name and concrete result/value in one or two sentences.
2. Complexity (небольшая / средняя / сложная) with reason; state risk separately.
3. A concrete Codex model/available effort and an external model/provider/client alternative, with brief preference/confidence. Do not invent availability.
4. Only the required independent review and Owner/private actions, with their reason.
5. One short copyable launch: repo/issue/note, role, exact baseline/target, task branch/workspace policy, intended result and authorized delivery.

The issue/accepted contract holds acceptance criteria; do not duplicate it in the prompt.
**Owner preference: normally 5–10 lines for a Worker launch or remediation prompt.** Link the exact issue/review note instead of copying its requirements, test matrix or invariants. New-session prompts point to the latest closeout and pending decisions, not a second project manual. Longer prompts require a specific request or genuinely missing authoritative scope.
Use standing workspace self-create where applicable; do not invent a root, SHA or missing safety-critical authorization.
Choose one execution route at launch. An alternative may be unavailable/not recommended; say so rather than manufacture a choice.

Model choice is routing only. Normal task handoffs do not request or persist runtime model/provider identity, benchmark grades or usage telemetry.

<a id="codex-local-orchestration"></a><a id="manual-execution-remains-supported"></a>

<a id="d1-model_routing-8-execution-modes"></a>
#### Execution modes

Ordinary execution is one Worker; special queue/delegation mechanics live only in D6.
Local configuration selects models; routing policy neither activates orchestration nor grants canonical integration authority.


<a id="d1-model_routing-8-what-this-file-is-not"></a>
#### What this file is not

Not a vendor ranking, client skill/config manual or permission for an execution coordinator to self-integrate.

<a id="d1-owner_data_workflow-5"></a>
### Owner data authority and distinct operations

<a id="d1-owner_data_workflow-5-data-access-and-presentation"></a>
#### Data access and presentation

An Owner request to analyze, diagnose or visually verify their data authorizes the
assigned assistant to read the relevant real records, reports, documents, screenshots
and UI in the assigned context. Use ordinary local viewers, browser tools and model
vision/text in the authorized assistant conversation. Do not ask again for each
record, image or query. Values, dates, names, identifiers and local paths are not
credentials merely because they are personal. Show the facts needed to answer the
Owner without compulsory masking or opaque surrogate labels.

Keep real datasets and working reports in the assigned Owner-data location outside
the tracked code checkout. A code task that needs Owner evidence can perform an
authorized read-only diagnostic there; it need not pretend that all useful evidence
is synthetic. Automated tests/CI and committed examples still use synthetic data.
Do not copy or link runtime databases into code fixtures. Read-only database work
uses an appropriate read-only connection and must not run migration-capable startup.

Access credentials, tokens, recovery keys and real `.env` contents are not report
material. Do not print them. Public GitHub/CI publication and sharing to another
recipient are separate from showing relevant data to the Owner in the authorized
AI conversation. Ordinary task authorization is not permission to publish a whole
dataset; follow a specific Owner publication request when one is given.


<a id="d1-owner_data_workflow-5-reads-runtime-changes-and-data-writes"></a>
#### Reads, runtime changes and data writes

Reading/analyzing assigned data does not authorize database writes, migrations,
reimports, semantic attestations, production changes or destructive operations.
Those require the applicable task authority. Once the Owner has authorized a bounded
operation, carry out its necessary reversible steps without repeated consent.
Normal code checks do not call account-backed providers. Live provider operations,
runtime preparation/start/stop and external connections use their assigned scope.

<a id="d2"></a>
## 2. Bootstrap, isolated workspace and lifecycle

Fetch canonical refs and pin the authorized baseline (current main unless assigned otherwise). Use one fresh physical clone/worktree per active writing/local verification task below the configured client root; a different branch alone is not isolation. Never switch/reset/pull another task's tree or write Stable/Main/Test/Owner/Ops.

Use the accepted installed matched `cleanup-workspaces.ps1`/`.fs.cs` helper: dot-source it; `Invoke-WorkerLifecycle -Action Create -Workspace <new-child> -Owner <unique-task>` before clone, then Bind, persist the returned local Claim, and CheckActive before writes/tests and delivery. Pause retains ownership. Resume returns a new Claim/generation; persist and recheck. Complete follows actual final delivery with verified Git state, not age or a closed PR. Do not print, commit or publish claims.

If the launch's helper path is absent, investigate the accepted installed Ops pair read-only; do not alter scheduler/cleanup or silently stall. If no accepted configured helper is available, create one fresh unique authorized checkout and record its owner once under the standing fallback; do not enroll/adopt legacy trees. Preserve ambiguous/sibling work. O5 owns retirement/deletion procedures.

Development uses synthetic data. From the isolated checkout: `uv sync --project backend --locked --group dev`; frontend `npm ci --prefix frontend`. Use the committed locks and checkout-local environments. Copy no production DB, `.env` or backup into fixtures. Alembic migration changes require the accepted compatibility/recovery contract; never rewrite released migration bytes or expected digests to make CI pass. `backend/migrations/README` is part of the released migration digest.

<a id="d2-agents-67"></a>
### Physical workspace isolation and self-create authority

With a known configured root and pinned task/branch/baseline/target, create one fresh `workspaces/<agent>/<task>/` worktree/clone yourself.
Do not ask for an absolute path just because the launch omitted it. Ask only for a genuine unknown/inaccessible root, path collision or boundary crossing.
An explicitly assigned independent clone/path takes precedence. Out-of-root work needs authorization; high-risk isolation may require an independent clone.
Use assigned scratch roots for temporary checks/caches. Workspace deletion remains Owner/Integrator-controlled after final Git-state verification.

<a id="canonical-main-and-integration-workstreams"></a><a id="preferred-ownerintegrator-execution-route"></a>

<a id="d2-agents-67-delivery"></a>
#### Delivery

A Worker may commit/push its own assigned task branch; no direct writes to `main`/integration branches or merging sibling/main changes independently.
`main` alone is canonical and releasable; `integration/*` is staging. Merge, force-push, destructive reset/rebase, branch/tag deletion, release and repo settings
remain Owner/Integrator-controlled unless explicitly delegated. A Worker cannot adopt Integrator authority from tool access.
An authorized Integrator performs permitted repository mechanics directly; existing standing integration authorization is not revoked by this document.
<a id="staged-integration-for-parallel-slices"></a><a id="documentation-synchronization"></a>
<a id="accepted-and-integrated-task"></a><a id="published-release"></a>
Staged integration and affected-document closeout belong to the integration procedure; release-specific closeout belongs to O4.


<a id="d2-agents-67-verification"></a>
#### Verification

Claim the physical checkout before writing/testing and check ownership before delivery, as described in the Owner-data workflow. Every STOP cites a concrete boundary or failure; do not invent privacy gates for authorized Owner reads.

Use the matching policy section, focused evidence and the existing CI; do not automatically repeat full suites for every handoff or role change.
Review final scope/diff/privacy and report actual checks, not inferred passes. Required independent review and Owner UAT are not replaced by green tests.
Integration requires successful exact-candidate PR CI and canonical exact-main push CI; never describe pending checks as completed.

<a id="d2-owner_data_workflow-38"></a>
### Atomic checkout ownership

<a id="d2-owner_data_workflow-38-one-writer-per-physical-checkout"></a>
#### One writer per physical checkout

Before editing or local verification, claim the canonical physical checkout with
the current chat/task identity using the available local ownership helper. Check
the claim before commit/push and release it at handoff or cancellation. Concurrent
claim acquisition must be atomic. Never steal a claim because a timer elapsed or
adopt another chat's identity. A paused task retains ownership until handed off.
If occupied, use a fresh authorized checkout; read-only remote review can continue.
The helper is cooperative coordination, not an OS lock against arbitrary editors.
If the helper is unavailable, use a freshly created uniquely named checkout and record its owner once; do not turn missing tooling into repeated approval requests. See the [workspace fallback](#d2) and [recoverable retirement](OWNER_RUNTIME_OPERATIONS.md#o5).

<a id="d2-0012-runtime-and-agent-workspace-isolation-21"></a>
### Separate runtime and agent trees

<a id="d2-0012-runtime-and-agent-workspace-isolation-21-decision"></a>
#### Decision

Separate the production runtime from all agent development environments.

Conceptually maintain:

- one production runtime clone;
- one independent clone per development agent.

All agent clones have independent Git directories. They are not worktrees of the runtime clone.

Runtime secrets and data live only in runtime storage.

Owner clarification (2026-10-10): [Owner data workflow](#d1-owner_data_workflow-5)
permits assigned read-only analysis/UAT of real data and presentation to the Owner
in the authorized assistant conversation. This supersedes blanket bans on the
assistant seeing personal values; it preserves separate runtime storage, synthetic
code fixtures, credential protection and authorization for mutations/publication.

Development agents must not turn runtime data into code fixtures through copies or filesystem links, including:

- copies;
- symlinks;
- junctions;
- hardlinks;
- other filesystem indirection.

Machine-specific absolute paths are local configuration, not repository architecture. Tracked docs must not turn a local disk layout into a portable requirement.

The canonical shared source is the GitHub repository. Agent clones sync from canonical `main` as described in `AGENTS.md`.


<a id="d2-0012-runtime-and-agent-workspace-isolation-21-consequences"></a>
#### Consequences

- Production use happens from a runtime checkout that may contain ignored local runtime data.
- Implementation, review and benchmark work happen in clean agent clones.
- A write task uses a dedicated branch in the writer's clone.
- Reviewers do not silently edit the candidate they are independently reviewing.
- Runtime isolation is a hard invariant, not a convenience.

<a id="d3"></a>
## 3. API/UI implementation discipline

Keep fonts and mandatory UI assets local: production rendering makes no required Google Fonts request. Financial sums/derived public indicators come from backend; necessary frontend aggregation uses exact integer minor units/BigInt. JS Number is allowed only at the final chart-geometry boundary after exact values have been computed, never as monetary source of truth.

Financial/domain logic lives in backend services/domain; React renders authoritative DTOs. Keep Decimal/minor-unit precision and stable reason codes, isolate provider adapters and validate explicit DTO allowlists. No native editor route accepts invalid month identity or arbitrary section names; C1 owns its exact protocol.

Use explicit loading/empty/error/partial/saving/acknowledged/readback-failed states. Bind every request to entity, month, account, source, scope and dependency identity. Late responses cannot populate a new selection. Preserve newer dirty input during outstanding requests; warn on dirty navigation and treat CLOSED as read-only until explicit Reopen. Following ACK, recover failed readback by GET, and independently verify exact create/update/delete before success.

After restore, discard pre-restore read models/confirmations, reread restored months and retain selection only if still valid. An ambiguous destructive result blocks unsafe repetition; confirmed-negative validation may retain input. Keep runtime/DB binding and native API source of truth. Performance preparation, mapping and provider previews use their contract-specific currentness rather than a UI-only success flag. Desktop keyboard/focus/Back and zoom are acceptance surfaces; preserve unique financial/lifecycle/browser coverage when retiring phone-only duplicates.

<a id="reference-projects-and-reuse"></a>
### Reference projects and reuse

**Research baseline — 2026-10-24.** This section is the first recorded Finance
reference comparison, not a claim about changes since an unknown earlier review.
Own-code baseline: [main `b027bcd90c56c500d271a9ee963485bdfa67ea79`](https://github.com/LTstripes/hermes-finance/commit/b027bcd90c56c500d271a9ee963485bdfa67ea79).
AGENTS, the relevant P/C/D/S sections, the complete open issue/PR collection and
applicable latest comments were read before mapping recommendations to source/tests.
The scope is one local/home-server user: understandable results, fewer repeated
manual actions and little maintenance. This is research, not feature acceptance,
a new task queue or a report of local/Owner UAT.

**Placement and reuse boundary.** D owns contributor research/reuse provenance
under [D5's single-home rule](#d5); P and C retain all product and financial
contracts, and S remains the changing status book. No sixth book, dependency,
copied code, financial formula change or new authority is introduced. For every
reference here the present disposition is **concepts, interface observations and
independently authored synthetic cases only**. Even MIT code would need a later
exact-file/SHA/license and notice review before copying. Package/root licenses do
not automatically cover documentation, bundled assets or dependencies. Public
issue reports and project marketing are not proof of a Hermes defect or of correct
financial calculation.

#### Observed versions and licenses

Commit dates are UTC; release dates are publication dates unless noted. Release
commits were resolved independently from tags; branch HEAD is not assumed released
or installed. These are observations, not dependency pins.

| Project | Observed head / commit date | Latest release checked / exact release commit | License evidence at observed head; proposed boundary |
|---|---|---|---|
| [Portfolio Performance](https://github.com/portfolio-performance/portfolio) | [`2a0ef52a93882c0845596b2c6b834e54f592b7ec`](https://github.com/portfolio-performance/portfolio/commit/2a0ef52a93882c0845596b2c6b834e54f592b7ec), 2026-10-24 | [0.89.0](https://github.com/portfolio-performance/portfolio/releases/tag/0.89.0), 2026-10-11; `20d7fb690ad532c5f4a8813f6c4f365745e37c7d` | [EPL-1.0](https://github.com/portfolio-performance/portfolio/blob/2a0ef52a93882c0845596b2c6b834e54f592b7ec/LICENSE). Concepts and synthetic cases only. No copying Java code; online manual has its separate CC BY-NC-SA terms. |
| [Wealthfolio](https://github.com/wealthfolio/wealthfolio) | [`8ef1cb7d84fdcfc5ee4cf62e64ceb9b548166598`](https://github.com/wealthfolio/wealthfolio/commit/8ef1cb7d84fdcfc5ee4cf62e64ceb9b548166598), 2026-10-24 | [v3.11.0](https://github.com/wealthfolio/wealthfolio/releases/tag/v3.11.0), 2026-10-23; `d1fda0b65f69d8557b1ef80e555c799215ad28b3` | [AGPL-3.0](https://github.com/wealthfolio/wealthfolio/blob/8ef1cb7d84fdcfc5ee4cf62e64ceb9b548166598/LICENSE). Reference only. Old `afadil/wealthfolio` redirects to the current organization; do not record the old owner as canonical. |
| [Ghostfolio](https://github.com/ghostfolio/ghostfolio) | [`4f17f0ecd4a357b860f835ab11c4d0034c20d2d0`](https://github.com/ghostfolio/ghostfolio/commit/4f17f0ecd4a357b860f835ab11c4d0034c20d2d0), 2026-10-24 | [3.92.0](https://github.com/ghostfolio/ghostfolio/releases/tag/3.92.0), 2026-10-24; `7429176b44d6bde31baf3b02acecef1a9cbaaf06` | [AGPL-3.0](https://github.com/ghostfolio/ghostfolio/blob/4f17f0ecd4a357b860f835ab11c4d0034c20d2d0/LICENSE). Reference only, especially scope/identity failure classes; no service-stack adoption. |
| [Beancount](https://github.com/beancount/beancount) | [`9747213802acb733ce53acc6e963f5961f47d6cd`](https://github.com/beancount/beancount/commit/9747213802acb733ce53acc6e963f5961f47d6cd), 2026-08-23 | [3.2.3, PyPI](https://pypi.org/project/beancount/3.2.3/), 2026-05-05; [`eeda2aa2a3204ffb980dab11220b2abde5e80b38`](https://github.com/beancount/beancount/tree/eeda2aa2a3204ffb980dab11220b2abde5e80b38). GitHub latest-release endpoint has no release object; tag/PyPI checked instead. | [COPYING](https://github.com/beancount/beancount/blob/9747213802acb733ce53acc6e963f5961f47d6cd/COPYING) GPL-2.0; [pyproject](https://github.com/beancount/beancount/blob/9747213802acb733ce53acc6e963f5961f47d6cd/pyproject.toml) explicitly GPL-2.0-only. Reference only; no second ledger or parser adoption. |
| [Fava](https://github.com/beancount/fava) | [`f0161ba300a393006a88d14b3968e5af535ed4a5`](https://github.com/beancount/fava/commit/f0161ba300a393006a88d14b3968e5af535ed4a5), 2026-10-24 | [1.30.16, PyPI](https://pypi.org/project/fava/1.30.16/), 2026-08-18; [`d8d426f9cbf08ace852a4a319adb4b9dda853b69`](https://github.com/beancount/fava/tree/d8d426f9cbf08ace852a4a319adb4b9dda853b69). No GitHub release object; annotated tag/PyPI agree. | [MIT](https://github.com/beancount/fava/blob/f0161ba300a393006a88d14b3968e5af535ed4a5/LICENSE). UX/read-boundary patterns only in this review; a later exact-file review would be needed for any code reuse, and MIT Fava does not relicense Beancount/dependencies. |
| [GnuCash](https://github.com/Gnucash/gnucash) | stable branch [`fec5643cd22cbafc7b16047f35cbe852395da947`](https://github.com/Gnucash/gnucash/commit/fec5643cd22cbafc7b16047f35cbe852395da947), 2026-10-19 | [5.17](https://github.com/Gnucash/gnucash/releases/tag/5.17), 2026-09-27; `0e302675fff4bf6dccf62ba876c7d306b7152d0e` | [LICENSE](https://github.com/Gnucash/gnucash/blob/fec5643cd22cbafc7b16047f35cbe852395da947/LICENSE) describes a mixed compatible set: mostly GPL-2.0-or-later, some GPL-2.0/GPL-3.0-specific files and exceptions. Reference only; inspect individual file if reuse is ever proposed. |
| [investments](https://github.com/KonishchevDmitry/investments) | [`d4e14076f14a838965b99bd7385902b7c5bf3d08`](https://github.com/KonishchevDmitry/investments/commit/d4e14076f14a838965b99bd7385902b7c5bf3d08), 2026-08-11 | [v8.4.0](https://github.com/KonishchevDmitry/investments/releases/tag/v8.4.0), 2026-08-11; same SHA as observed head | [Cargo.toml](https://github.com/KonishchevDmitry/investments/blob/d4e14076f14a838965b99bd7385902b7c5bf3d08/Cargo.toml) declares `GPL-3.0+` (GPL-3.0-or-later). Root tree has no LICENSE/COPYING; do not overstate a complete licensing audit. Reference only; no copying. |

#### Useful lessons and scenario differences

##### 1. Portfolio Performance — returns with inspectable scope

The official [MWR](https://help.portfolio-performance.info/en/concepts/performance/money-weighted/) and [TWR](https://help.portfolio-performance.info/en/concepts/performance/time-weighted/) explanations distinguish portfolio versus security cash-flow boundaries and annual versus period figures. PP's daily valuations and timing assumptions differ from Hermes statement EOD evidence and bounded Modified Dietz/conditional results; do not rename our available result to exact TTWROR by copying a formula.

Release 0.89.0 includes dividend fees in the security fee total and displays an undefined moving-average cost for short trades rather than zero. It also adds optional read/write MCP, which we should not adopt. Open [#5274](https://github.com/portfolio-performance/portfolio/issues/5274) (created 2025-12-31; updated 2026-10-24) reports weekend cash flows disappearing from a return export. Open [#2367](https://github.com/portfolio-performance/portfolio/issues/2367) (2021-08-04; updated 2026-10-24) reports fallback into the wrong account during CSV import. These are reports, not independently reproduced upstream findings.

**Use:** compare read/visible/export scopes and include weekend/boundary flows in a focused regression. **Difference:** do not import PP's quote collection, taxonomy/dashboard customization, global PDF bank catalogue, or write-capable AI.

##### 2. Wealthfolio — compact account activity with reconciliation clues

v3.11.0 introduces per-activity/running or EOD balances (depending on account type) and date-grouped activity lists. It fixes external credits counted as gains, inconsistent historic income FX/month attribution, duplicate assets during trade edits, and precise broker decimal conversion. These are documented shipped fixes; our equivalent contracts must still be checked independently. The release explicitly distinguishes missing comparative income growth from 0%.

Open [#2281](https://github.com/wealthfolio/wealthfolio/issues/2281), 2026-10-24, asks for stable source record IDs/metadata because value-and-comment matching is insufficient for add-on reimports. Open [#2282](https://github.com/wealthfolio/wealthfolio/issues/2282), 2026-10-24, reports that a CSV column named `lineNumber` collapses preview rows, including unresolved mappings. Open [#2268](https://github.com/wealthfolio/wealthfolio/issues/2268), 2026-10-24, reports dropped tax via MCP import. None is proof about Hermes.

**Use:** evidence-preserving exception preview; account-scoped inventory conservation before/after save/reload. **Difference:** Hermes already has source-native original identities and receipts; do not replace them with value hashes or comments. Ignore sync/cloud/add-on ecosystems, AI ingestion and new broker connections.

##### 3. Ghostfolio — particularly useful negative examples for multiple accounts

Release 3.92.0, 2026-10-24, improves import asset matching to include closed positions/excluded accounts (AI path, experimental), and hardens errors from `POST api/v1/import`. Those improvements are not a reason for an LLM importer.

Open [#7728](https://github.com/ghostfolio/ghostfolio/issues/7728), created 2026-08-26 and updated 2026-09-25, specifically reports deduplication across distinct accounts with identical date/type/price/quantity. Open [#7468](https://github.com/ghostfolio/ghostfolio/issues/7468), 2026-07-29, is a request to distinguish price and dividend-inclusive total return; its assertion about current math is not an independently validated defect or financial authority.

**Use:** two-account adversarial import acceptance; preserved source-account identity through closed/excluded views. **Difference:** Hermes is one local Windows user and has explicit source authority/Close; do not take the multiuser/cloud/provider/admin service stack.

##### 4. Beancount — assertions and deterministic evidence, not another ledger

The [official balance-assertion discussion](https://beancount.github.io/docs/balance_assertions_in_beancount/) explains that a single-currency/unit check is not proof of complete inventory, cost basis or complete operations. It is a design discussion dated July 2014, not a 2026 feature announcement. The [inventory documentation](https://beancount.github.io/docs/how_inventories_work/) is a useful account of ambiguity rather than guessing cost lots.

Open [#1056](https://github.com/beancount/beancount/issues/1056), 2026-09-23, reports same-date ordering changing when one file is split into included files. Open [#1043](https://github.com/beancount/beancount/issues/1043), 2026-08-08, reports negative rounding direction inconsistent with its documentation; [#1004](https://github.com/beancount/beancount/issues/1004), 2026-01-13, reports incomplete currency inference using the wrong tolerance.

**Use:** metamorphic tests for equivalent originals split/reordered without losing economically distinct occurrences. **Difference:** keep Hermes explicit Decimal/ROUND_HALF_UP; do not adopt automatic inferred postings, padding, tolerance inference or textual double-entry ledger.

##### 5. Fava — consistent filters and compact drilldown

Fava is a local web UI over Beancount; useful for journal → account → source navigation rather than another financial engine. [CHANGES](https://github.com/beancount/fava/blob/f0161ba300a393006a88d14b3968e5af535ed4a5/CHANGES) states that duplicate detection with v3 importers is not automatic; it requires explicitly configured hooks. Do not assume a mature import UI makes reimport safe.

The observed head is [57 commits beyond stable 1.30.16](https://github.com/beancount/fava/compare/d8d426f9cbf08ace852a4a319adb4b9dda853b69...f0161ba300a393006a88d14b3968e5af535ed4a5). Relevant **unreleased head** work: [real-subaccount filtering](https://github.com/beancount/fava/commit/c15ee2b123c54fe22f2d11f75b354e328a82c844), 2026-09-26; [concurrent query shared-state protection](https://github.com/beancount/fava/commit/fa7be27ffcd4f8b75e07b2af7dcccbe9edd1c298), 2026-10-07; [trusted localhost hosts](https://github.com/beancount/fava/commit/7e3250cf4cc2227aafc74d8e4e6cb61b8eff6fab), 2026-10-22. Open [#1423](https://github.com/beancount/fava/issues/1423) (2022-05-16) was reported against 1.21; the later filtering fix means its open status alone does not prove the issue remains on current head. [#1151](https://github.com/beancount/fava/issues/1151) (2020-08-29; updated 2026-08-22) requests rapid reconciliation toggles; it is a request, not an implemented feature.

**Use:** same selected account/period must drive list, chart, result and export; source drilldown stays small. **Difference:** no editable SQL/Python hook system or Beancount UI embedding.

##### 6. GnuCash — reconciliation is not the same operation as Close

[Reconciliation](https://www.gnucash.org/docs/v5/C/gnucash-manual/acct-reconcile.html) compares statement date/balance with selected transaction evidence and exposes the remaining difference. Release 5.17, 2026-09-27, fixes reconciliation involving transactions after the reconcile date (upstream Bug 799753), quoted CSV parsing (799774), stock-split cost basis handling and date-boundary tests. Bugzilla itself was inaccessible in this research, so fix evidence is the official release note, not a reproduced bug.

The [Close Book documentation](https://www.gnucash.org/docs/v5/C/gnucash-manual/tool-close-book.html) says its Close creates balancing transfers for income/expense accounts and does not freeze history. Hermes Close means immutable reporting month until explicit Reopen: the operations must not be equated.

**Use:** compact read-only opening balance + observed operations + ending balance + unexplained difference at an exact cutoff. **Difference:** never copy GnuCash's optional balancing-entry button, zeroing Close or full general ledger as a shortcut around unresolved evidence.

##### 7. investments — Russian statement-first import with honest limitations

The pinned [README](https://github.com/KonishchevDmitry/investments/blob/d4e14076f14a838965b99bd7385902b7c5bf3d08/README.md) supports Russian brokerage formats and distinguishes analysis reads from position sync writes. Its requirement for complete account history from zero, without overlaps/gaps, is explicit. Its performance model compares the same cash flows to a bank deposit with monthly capitalization; that is not automatically Hermes XIRR/TWRR/Modified Dietz.

v8.4.0 documents non-exchange-traded funds; [tax withholding for the other-broker format](https://github.com/KonishchevDmitry/investments/commit/aca3fbf0b3bbe2d38b6f9e1aa0eb6dd535655216), 2026-08-10, is a release-ancestor change. README still lists bonds as unsupported, linked to [#43](https://github.com/KonishchevDmitry/investments/issues/43) (open, 2021-04-17); [#13](https://github.com/KonishchevDmitry/investments/issues/13) (open, 2020-06-29) reports cross-account transferred securities lacking original purchase basis.

**Use:** explicit supported-format limits and context-rich parser errors. **Difference:** Hermes has material bond/coupon/NKD, overlapping long/monthly originals, partial history and corrections; cannot inherit the donor's completeness assumptions or require an entire lifetime before every bounded calculation. No tax engine, rebalancing instructions, Prometheus or external metrics stack.

#### What Hermes already has; no duplicate feature proposals

At this cut there were **26 open issues and three open PRs** (#927, #829, #744),
read as a complete collection. OPEN umbrellas do not imply missing implementation.
Current source and later accepted receipts take precedence over old issue bodies:

- [#945](https://github.com/LTstripes/hermes-finance/pull/945) / [#891 accepted backend](https://github.com/LTstripes/hermes-finance/issues/891#issuecomment-6371707813)
  already deliver dated source events, payout-link revalidation, quantity/cash
  reconciliation, P&L and period Modified Dietz. Preserve legacy simple percentage,
  complete economic result, known components and conditional statement estimates
  as different meanings; adding those again is not a proposal.
- [#946](https://github.com/LTstripes/hermes-finance/pull/946),
  [#949](https://github.com/LTstripes/hermes-finance/pull/949),
  [#950](https://github.com/LTstripes/hermes-finance/pull/950) and
  [#951](https://github.com/LTstripes/hermes-finance/pull/951) already provide the
  saved-source payout preview, useful bond detail, shared multi-file Month upload,
  stocks/instruments and explicit actual/future separation. [#953](https://github.com/LTstripes/hermes-finance/pull/953)/
  [#954](https://github.com/LTstripes/hermes-finance/pull/954) implement empty-manual
  Close policy and GET-only recovery. Do not restart these features from old #711/#891 text.
- [#769](https://github.com/LTstripes/hermes-finance/issues/769) owns historical source
  work and targeted missing evidence; [#889](https://github.com/LTstripes/hermes-finance/issues/889)
  owns the partial-source versus economic-acceptance boundary. Its
  [accepted rebuild option](https://github.com/LTstripes/hermes-finance/issues/889#issuecomment-6254184201)
  already permits rebuilding a new isolated scratch from retained originals after
  a parser change. No mandatory in-place reparse/versioning platform is proposed.
- [#940's latest October 24 receipt](https://github.com/LTstripes/hermes-finance/issues/940#issuecomment-6387781110)
  distinguishes an operational Preview's omitted expected trigger effect from a
  product defect. It retains the same assigned Operator. This review neither
  restarts that operation nor turns the existing correction trigger into a bug.
  Dated release/installation prose elsewhere is not fresh runtime evidence; this
  reference section does not become a second status book.

Own paths below are in the [pinned baseline tree](https://github.com/LTstripes/hermes-finance/tree/b027bcd90c56c500d271a9ee963485bdfa67ea79).
Backend `services/` and `domain/` module paths below are relative to
`backend/src/hermes_finance/`; backend test basenames refer to `backend/tests/`.
Frontend component basenames refer to `frontend/src/ui-v2/`, except
`SourceIntakeUpload.tsx` and `SourceIntakeJournal.tsx`, which are in
`frontend/src/components/month-close/`. A missing UI presentation found by static inspection is distinct from an observed
user failure. Upstream behavior has not been independently reproduced here.

#### Prioritized discussion dispositions — at most five

Complexity and risk refer to a later bounded task. Existing issue references
identify ownership; they do not create another task for the same feature.

| Disposition | Proposal / benefit | Current-code mapping and existing work | Complexity / material risk | Minimal later check |
| --- | --- | --- | --- | --- |
| **Take now as an acceptance extension** | One adversarial batch combining identical cross-account native IDs/amounts with source-row collisions, reordered files and replay; protects against silent missing history | `services/source_intake.py:save_intake`, `source_instrument_events.py:read_events`, `SourceIntakeUpload.tsx`; extend the existing #769/#891 corpus, not the importer. Existing concurrent batch, overlap multiplicity and account-isolation tests are retained. | Small–medium; high source identity/money risk if dedup is weakened | Two synthetic account formats, identical trades and same-day repeated payouts, all available Previews before Saves, both Save orders and concurrent Save, GET/reload/replay. Assert exact per-account native occurrences and all exception rows. A materially corrected source must be an explicit conflict/correction, never a silently overwritten original. |
| **Take now as a narrowly different regression** | Calendar/source representation invariance: preserve weekend flows and trade/settlement cutoffs across long versus adjacent originals | `source_monthly_returns.py`, `source_instrument_events.py`, `domain/monthly_return_chain.py`; reuse #769 tests and #891 date authority. PP/Beancount/GnuCash reports are analogies, not proved Hermes bugs. | Small–medium; high financial boundary risk | Compare the same evidenced outer interval and native event set in long/adjacent/overlap input orders; weekend flow and last-day trade with next-month settlement. Preserve `(start, end]`, multiplicity and date roles. Missing intermediate valuations must still leave monthly rates NULL; no invented order or market price. |
| **Later; one optional read-only explanation** | Expose existing account reconciliation as a short expandable result: account growth, known instrument result, account-only effects and unexplained residual | `source_instrument_events.py:reconcile_account` already produces `AccountReconciliation`; `frontend/src/api/sourceReturns.ts` carries it. Inspected Month/monthly-return UI does not render that reconciliation. A small presentation extension belongs with #891/#711, not a new balance ledger. | Small–medium; medium/high interpretation risk | Fully covered residual 0; known nonzero residual remains `partial` with `complete=false`; missing bond basis; filtered ISIN. NULL must stay unavailable and a known partial subtotal must not be labelled fully reconciled. No allocation of residual, correction posting or Close action. |
| **Simplify within existing #711** | Replace primary technical Save/Apply jargon with a short factual explanation and move detailed diagnostics into existing disclosures; fewer confusing choices | `components/month-close/SourceIntakeUpload.tsx` currently exposes `Source Save != financial Apply` wording; `SourceIntakeJournal.tsx`, `UiV2ClosePage.tsx` and `SourceInstrumentDetail.tsx` already own review/details. This narrows the existing simple-month direction, not a new redesign. | Small; medium risk of hiding uncertainty | Known/unknown original; ACK then GET failure; lost ACK; partial sibling failure; account switch and Back/Reload. State that the original is saved while financial acceptance/Close is separate. Keep an actionable next step and exact reason accessible. |

The code map above is inspected source, not proof these hypothetical failures
exist. In particular, existing `test_source_instrument_events.py` already checks
same-ISIN account separation, missing overlap occurrences, settled cash ownership,
fee/tax/NKD attribution, reconciliation and sold-out missing rows.
`test_statement_import_source_intake.py` already has `_history_batch` concurrency,
long/monthly/replay preservation and partial-file failure. Its four-account fixture
uses different trade IDs; the account event test uses different dividend amounts
and no trades. The proposed first scenario deliberately combines fully identical
native trades across accounts with file/row collisions, rather than repeating
those simpler cases. The second compares only truly equivalent evidenced intervals.

#### Regression catalogue and reuse limits

Retain current regression protection; add a case only when an affected change and
an inspected coverage gap make it useful. No regression was executed in this
docs-only review and no new passing-test claim is made.

- **Identity and correction:** original SHA/filename/native account/row occurrence
  and accepted revisions remain separate identities. Same amount/date is not a
  dedup key; repeated identical legitimate events survive. The existing
  `mybroker_corrections.py:install_sql_guards` invalidates dependent confirmations
  when catalogue/mapping facts change. A Preview of a later operation must account
  for the supported trigger effects, not weaken or suppress them.
- **Missing/zero/precision:** preserve absent tax/cost/valuation versus explicit
  zero, signed sub-kopeck correction evidence and canonical Decimal/ROUND_HALF_UP.
  Beancount rounding reports and Wealthfolio missing comparisons are negative
  examples only; our contract wins. Do not add a second generic tolerance engine.
- **Scope and concurrency:** account/ISIN/interval must bind list/detail/result/source
  through delayed responses and rereads. Fava's filtering/shared-state fixes suggest
  a variant only if current #951 stale-selection tests do not already cover it.
  An invalid explicit instrument must not fall back to another instrument.
- **Reconciliation and Close:** numerical equality of a subset is not whole-source
  completeness or approval to Close. Source-only Save is not financial Apply;
  known residuals are not automatically distributed; CLOSED stays immutable until
  explicit Reopen. GnuCash's Close Book is deliberately not transplanted.

**Do not take:** another ledger, importer or month-close engine; automatic balancing
entries, guessed NKD/taxes/denomination, quote-based invented history, a lifetime-history
requirement for every bounded calculation, LLM financial writes, arbitrary SQL/Python
hooks, cloud/device-sync obligations, multiuser/admin platform, new broker fleet,
model benchmarking or telemetry. Portfolio Performance's daily-price TTWROR,
investments' bank-deposit comparison and our statement-based Modified Dietz are
not interchangeable labels.

**What may be reduced, not blindly deleted:** repeated technical labels and primary
links competing with the Month path. Existing diagnostics, correction/history and
legacy compatibility routes require their own reachability/user-path evidence
before retirement. Neither upstream minimalism nor this no-runtime source review
proves a local route or unique test safe to delete. [#389](https://github.com/LTstripes/hermes-finance/issues/389)
report composition remains deferred; no new dashboard builder is warranted here.

<a id="d4"></a>
## 4. Verification, independent review and evidence

Choose affected semantic lanes and concrete regression/failure boundaries. Use existing exact-candidate CI for its actual covered jobs; do not run full local suites again just because roles change. Explicit task requirements still apply. Independent review follows D1 risk and explicit task requirements; a role change does not require repeating valid checks. No Apply/Close/Start/update or private-data UAT is authorized by a documentation change.

A read-only review preflight verifies actual source access and exact candidate identity. Setup failure is UNVERIFIED; repair its cause before another preflight. Reviewer self-message is not a PASS. Synthetic tests, Windows probes, local private UAT, published release and installed runtime each retain their own provenance and limits.

<a id="d4-verification_policy-1"></a>
### Complete proportional verification policy

Обязательный протокол. Проверяем изменённое поведение и реальные риски, а не повторяем одни и те же действия при каждой передаче задачи.


<a id="d4-verification_policy-1-1-общий-принцип"></a>
#### 1. Общий принцип

Для обычной задачи нет обязательного локального full-suite перед каждым handoff.
Targeted evidence проверяет изменение; полный релевантный охват может обеспечить успешный CI точного кандидата.
Не дублируй этот охват локально только ради отчёта Worker, Reviewer или Integrator.
Явные task/ADR/release/Owner gates сохраняются. Противоречащее им сокращение сначала согласуется в авторитетной issue/note, а не скрывается в отчёте.


<a id="d4-verification_policy-1-11-semantic-lanes-и-ownership"></a>
#### 1.1. Semantic lanes и ownership

Добавляй регрессию существующему semantic owner; выбирай marker или конкретный test path.
Карта и команды находятся в [TEST_SUITE_GUIDE.md](#d4-test_suite_guide-1); читай нужный участок, а не весь каталог.
Новый `test_rXX_*` файл нужен для отдельного release/version/compatibility или task-acceptance контракта, не просто для номера issue.
Markers не исключают тесты из полного suite; существующее покрытие и CI lanes эта политика не меняет.


<a id="d4-verification_policy-1-12-ui-платформа-и-визуальная-приёмка"></a>
#### 1.2. UI-платформа и визуальная приёмка

**Owner decision 2026-10-09: desktop/laptop only.** Новый UI и Owner UAT проверяются в браузере на Windows-ноутбуке: стандартные рабочие ширины порядка 1280–1440 px, читаемость при обычном масштабе и поддерживаемом desktop zoom, отсутствие обрезания важных действий, клавиатура/focus/Back и надёжность текущих данных. Точная ширина теста выбирается по изменению/существующему acceptance contract, а не ритуально для каждого PR.

Мобильные раскладки, phone-only UX, 390 px, эмуляторы телефона, touch/mobile UAT **больше не являются продуктовым критерием или обязательным новым gate**. Не назначать Worker/Owner дополнительный мобильный прогон и не делать телефонный дизайн. Активное Playwright-покрытие использует desktop-размеры: дубли 390 px удалены в #747, уникальные финансовые, real-backend, lifecycle и keyboard-сценарии сохранены на desktop. Не возвращать телефонные варианты при интеграции старых веток. Mobile-only CSS можно убирать только отдельной узкой проверенной правкой, без ухудшения desktop-доступности или изменения финансовых контрактов.


<a id="d4-verification_policy-1-2-implementation-loop"></a>
#### 2. Implementation loop

1. Для bugfix найди/добавь regression test; подтверди RED на старом поведении, когда это даёт полезное воспроизводимое доказательство.
2. Во время правок запускай affected tests и lint/format для затронутого кода. Сначала стабилизируй реализацию и форматирование.
3. При сбое сохрани ошибки, установи причину, затем проверь failed nodes и affected contracts. Не используй полный suite как следующую диагностическую команду по привычке.
4. При новом контрактном/integration риске останови расширение задачи и обратись к Integrator; не исправляй чужое поведение молча.

RED-first не обязателен для docs-only, форматирования и других изменений, где failing test не добавляет уверенности.
<a id="stabilize-before-a-full-gate"></a>
Для shared DB/session, serialization, restore и иных cross-cutting primitives сначала проверь direct consumers, failure/lifecycle boundaries и production entrypoints.
Один heavyweight local verification process одновременно, включая параллельные проекты. Не меняй source/config/dependencies во время его работы.
После выявленного инфраструктурного сбоя исправь temp/cache/toolchain условия и проверь малым запуском, прежде чем снова запускать дорогой suite.

<a id="3-финальный-local-verification-gate-по-типу-задачи"></a>
<a id="backenddomain-only"></a><a id="frontend-only"></a><a id="apishared-contract-change"></a>
<a id="migration--startup--backup--restore--filesystem--concurrency--security"></a>
<a id="docsprocess-only"></a><a id="cross-cutting-backend--frontend"></a>

<a id="d4-verification_policy-1-3-достаточный-охват-по-типу-задачи"></a>
#### 3. Достаточный охват по типу задачи

| Изменение | Достаточное локальное evidence и дополнительный охват |
| --- | --- |
| Docs/process-only | Diff, ссылки/anchors, whitespace; privacy/tracked-files check при затрагивании путей/данных. Без backend/frontend full suite. |
| Backend под принятым контрактом | Targeted regressions + backend lint/format. Полный backend охват — CI либо один локальный full, если CI его не обеспечивает. |
| Frontend под принятым API | Targeted component/interaction tests + frontend lint/format; production build локально или в exact-candidate CI. Полный frontend охват — CI либо один локальный full при отсутствии такого CI. |
| API/shared contract или оба слоя | Targeted проверки обеих сторон и реальных consumers; lint/build затронутых слоёв. Полный релевантный охват — соответствующие CI lanes или недостающий локальный gate. |
| Financial semantics, migration, startup, backup/restore, filesystem/concurrency, security/runtime | Targeted boundary/failure regressions, полный релевантный охват и все task-specific probes. Нужны соответствующая среда, независимое ревью и применимый Owner UAT. Linux unit CI не заменяет Windows process/file-handle/path probe. |

Полный локальный запуск нужен, когда CI недоступен/не покрывает релевантный слой, есть воспроизводимый local-only риск, либо его прямо требует task/ADR gate.
Для high-risk задачи CI засчитывается только за реально выполненные проверки в подходящей среде; отсутствующие platform/integration/package probes выполняются отдельно.
Package/install smoke — финальная проверка при изменении упаковки/установки, а не причина повторять все suite перед каждым smoke.
Не запускай frontend full для чистого backend изменения и наоборот без изменённого consumer/shared contract или отдельного требования.
Push и PR можно создать для получения CI evidence; пока обязательные проверки идут, статус — pending, не done/accepted.


<a id="d4-verification_policy-1-4-когда-полный-suite-надо-повторить"></a>
#### 4. Когда полный suite надо повторить

Повторный полный запуск должен закрывать конкретную недостающую гарантию:
- семантическое изменение затронуло слой после предыдущего полного evidence;
- предыдущий нужный gate был прерван, невалиден или завершился ошибкой;
- новый установленный риск/обязательный gate не покрыт имеющимися результатами.

Сначала стабилизируй исправление на focused tests; затем получи полный нужный охват обновлённого кандидата, в том числе через CI.
Это не требование одновременно повторить и локальный full, и CI, и всё то же у Reviewer.
Смена роли/сессии, передача кандидата, потеря polling-сессии, новый SHA после docs/format-only правки и «для уверенности» сами по себе не основания для локального full.
После доказуемо non-semantic diff допускается переиспользовать применимое локальное evidence с указанием исходного SHA и проверенного отличия.
Нельзя приписывать старый PASS изменённому поведению, смешивать несовместимые запуски или выдавать failed-node rerun за пройденный полный gate.
Числового лимита, который отменял бы необходимую проверку, нет. Перед дорогим повтором достаточно коротко назвать изменение/ошибку и незакрытый риск; отдельный отчёт не нужен.


<a id="d4-verification_policy-1-5-ci-и-exact-head"></a>
#### 5. CI и exact HEAD

Успешный exact-candidate CI может быть полным verification gate без его локального дубля, только если проверены нужные jobs, охват и среда.
Skipped, pending, failed, чужой SHA или отфильтрованный нужный lane не являются этим доказательством.
Зелёный check `Documentation fast path` у pull request означает только доказанную классификацию обычной неисполняемой документации и успешные сохранённые проверки privacy/diff. Он не доказывает выполнение backend, frontend, browser или Windows product suites. Push в canonical `main` и release gates этот режим не использует: они остаются полными.
Проверки на новом executable/config/dependency состоянии должны соответствовать этому состоянию; отчёт явно связывает каждый результат с кандидатом/run.
Для интеграции обязательны зелёный PR CI принятого кандидата и зелёный canonical main push CI точного merge SHA. Ни одно не заменяет другое.
Не обходи существующие required jobs; изменение coverage, filters, assertions или release guards требует явного scope и проверки сохранённого охвата.
Reviewer/Integrator используют подтверждённое evidence кандидата. Независимость означает отдельную оценку diff/контракта, а не обязательный повтор всех тестов.
Reviewer запускает focused reproduction/probe, когда есть спорный вывод, пробел покрытия или другое конкретное основание; для локального запуска нужна изоляция.


<a id="d4-verification_policy-1-6-что-писать-в-отчёте"></a>
#### 6. Что писать в отчёте

Назови выполненные команды/CI jobs, результат и исходный SHA/run; отдельно обозначь material gaps и ожидаемые проверки.
Не называй targeted subset полным suite и не утверждай, что локально запускалось то, что выполнялось только в CI.
Не добавляй перечень оправданий за каждый несвязанный suite. Неисполненное явное требование задачи, напротив, нельзя умолчать.


<a id="d4-verification_policy-1-61-owner-данные-review-и-продолжение-uat"></a>
#### 6.1. Owner-данные, review и продолжение UAT

[Owner data workflow](#d1-owner_data_workflow-5) разделяет разрешённое чтение реальных
данных, изменение runtime и публичную публикацию. Offline-аудиту сохранённого клона
не нужен запущенный UI. Для runtime проверяй актуальную привязку процесса, кода и
профиля; сохраняй выполненные этапы и продолжай с первого незавершённого.
Preflight reviewer должен прочитать Git/source. Ошибка среды не отменяет полезные
выводы по исходникам, но и не превращает их в завершённое независимое review.


<a id="d4-verification_policy-1-7-примеры"></a>
#### 7. Примеры

- Docs-only: diff/link/whitespace/privacy review → обычный PR CI; локально продуктовые full suite не нужны.
- React leaf: targeted Vitest + frontend lint/format → exact-candidate frontend tests/build в CI; повтор full у Reviewer не нужен.
- Backend service: regression + targeted pytest + lint/format → полный backend CI; frontend добавляется только при реальном consumer/API влиянии.
- Windows restore: synthetic failure/concurrency regressions + нужный Windows probe + полный релевантный охват → independent review/UAT по контракту.
- После failed full: диагностика → failed nodes + affected tests → полный нужный gate на стабилизированном кандидате, не full после каждой правки.

<a id="d4-test_suite_guide-1"></a>
### Semantic lanes, commands and shard coverage

This guide is the Phase 2A ownership and lane map for Hermes Finance. It is
additive: the existing regression tests remain in place, and the full test
commands still collect every existing test. The guide does not authorize
renaming, moving, merging, or deleting test files.


<a id="d4-test_suite_guide-1-current-ci-topology--2026-10-09"></a>
#### CI sources and required guarantees

Use the executable sources for current jobs, filters, selections and timeouts:

- [Product CI](../.github/workflows/ci.yml) owns the matrix, marker expressions, Windows selections, concurrency and terminal `ci-ok` gate.
- [Path classifier](../scripts/ci_paths.py) and its [behavioral checks](../scripts/tests/test-ci-paths.py) own area selection and conservative fallback.
- [UI evidence workflow](../.github/workflows/ui-v2-evidence.yml) and [identity checks](../scripts/tests/test-ui-evidence-identity.py) own candidate provenance and safe duplicate omission.
- [Playwright projects](../frontend/playwright.config.ts) and [visual configuration](../frontend/playwright.visual.config.ts) own browser selections and desktop viewports.

Do not copy matrix counts, shard lists, timeout values or selected Windows node counts into this handbook. Update their executable owner and relevant contract checks together. D4 owns verification policy: required coverage must remain complete, ambiguous classification must fail conservatively, ordinary PR cancellation must not cancel canonical/protected work, and exact-head evidence must identify the code it checked. Desktop coverage follows the [desktop policy](#d4-verification_policy-1-12-ui-платформа-и-визуальная-приёмка).

The [documentation-only classifier](../scripts/docs_only_ci.py) permits only its proven non-executable prose fast path. A green Documentation fast path reports classification/privacy/diff evidence, not omitted product suites. Canonical main pushes and release gates retain full verification.


<a id="d4-test_suite_guide-1-add-a-regression-to-the-semantic-owner"></a>
#### Add a regression to the semantic owner

When a regression belongs to an existing behavior, add it to that behavior's
semantic suite. A release or issue identifier belongs in the test name only
when the test is specifically a release gate, version/compatibility check, or
task acceptance contract. For a historical regression that now protects a
current invariant, retain the scenario and its history in a comment or
docstring while keeping the test with the semantic owner.

Do not create a new `test_rXX_*` file merely to record the issue that exposed a
bug. If no suitable owner exists, document the gap first; a new lane or a
Phase 2B rehome may be appropriate after an explicit coverage comparison.


<a id="d4-test_suite_guide-1-backend-markers"></a>
#### Backend markers

The registered markers live in `backend/pyproject.toml`. The test
`conftest.py` applies them by stable path through
`backend/tests/_test_taxonomy.py`, so a new test added to an already mapped
file inherits that file's lane without boilerplate. Markers are additive: a
test may belong to both `migration` and `release`, for example. No marker
excludes tests from the normal full suite.

| Marker | Current ownership surface | Primary owner/lane | Contract or evidence |
| --- | --- | --- | --- |
| `domain` | `backend/tests/domain/` | Pure financial/domain rules | `docs/MASTER_SPEC.md` and accepted financial ADRs |
| `api` | Backend files ending in `_api.py` | HTTP/DTO/status contracts | API routes and their schemas |
| `service` | Backend files ending in `_service.py` | Application orchestration | Service contracts and domain tests |
| `persistence` | Database, reporting-month, applied-state, broker-state, and SQLite persistence suites | Persisted state | Persistence models and accepted migration contracts |
| `migration` | `test_migrations.py`, R04/R05/R06 release verification, and R08-01A migration coverage | Schema/data preservation | Alembic chain and additive/downgrade safety |
| `integration` | Alfa, broker, T-Invest, quote, payout, market, provider, reconciliation, and forecast/dashboard integration suites | Provider/integration boundaries | Accepted provider and read-only integration ADRs |
| `import_export` | Statement import, Markdown export, AI bundle, private-seed, and legacy interchange suites | Import/export boundary | Export/import contracts and privacy rules |
| `legacy` | `test_legacy_*.py` | Supported legacy compatibility | Legacy CLI and explicit mapping contracts |
| `runtime` | Startup, settings, local security, static app, CLI, and timezone suites | Runtime safety | Loopback/offline startup and direct-operation contracts |
| `release` | Release verification plus F05/G02/G08 acceptance and Windows release-path checks | Release/task gate | Release workflow and task acceptance contracts |
| `benchmark` | `test_long_history_benchmark.py` and `test_historical_batch_reads.py` | Explicit performance lane | Long-history benchmark contract |
| `windows` | Windows direct-runtime path (spaced/Cyrillic via `start-local`), timezone suites | Windows/runtime lane | Windows process/path/timezone behavior |
| `network_free` | Synthetic provider, startup, and release offline-boundary suites | Offline safety | No live provider or external network during the test |

The semantic mapping is intentionally not a mass classification of every flat
legacy test module. Existing modules may remain semantically unmarked and are
still covered by the full suite; the exclusive CI primary map below owns them
without renaming or moving files. This keeps the ownership decision reviewable
instead of hiding it in a bulk rename.


<a id="d4-test_suite_guide-1-backend-ci-primary-lanes"></a>
#### Backend CI primary lanes

Every collected backend node has one exclusive primary CI owner. Additive semantic markers support focused debugging and do not replace that owner.

- [Taxonomy](../backend/tests/_test_taxonomy.py) owns path-to-lane mapping, duration weights and deterministic execution-shard assignment.
- [Collection hooks](../backend/tests/conftest.py) apply markers and reject missing/conflicting ownership.
- [Ownership guard](../backend/tests/test_ci_lane_ownership.py) verifies file/weight coverage, deterministic assignment, exact collected-node union/disjointness, and one execution per node against the actual [workflow matrix](../.github/workflows/ci.yml).
- [Registered markers](../backend/pyproject.toml) provide the supported local selection vocabulary.

A new test module needs an explicit semantic/primary owner and any weight required by its execution shard. Weights remain scheduling inputs; they must be complete and positive where used. Benchmark isolation and fail-closed unknown ownership remain mandatory.

Estimated shard balance and old planning-time budgets are diagnostics, not acceptance gates. Adding a useful regression does not require retuning historical durations to satisfy a ratio. To inspect estimates, run `uv run --locked python -I -m pytest -q -s tests/test_ci_lane_ownership.py` from `backend/`. Actual job failures/timeouts remain blocking; investigate observed bottlenecks before changing scheduling or runtime limits.

The workflow owns platform-specific selections. Linux ownership does not replace unique Windows timezone/export/runtime guarantees; when changing a platform subset, prove where each retained guarantee runs and update its executable contract checks.

The shared support modules have these owners:

| Support module | Owner/lane | Use |
| --- | --- | --- |
| `backend/tests/_migration_helpers.py` | Migration/persistence | Locked synthetic Alembic execution and revision reads |
| `backend/tests/_network_helpers.py` | Integration/network-free | Forbidden transport for offline HTTP assertions |
| `backend/tests/_release_helpers.py` | Release/runtime | Isolated startup guard and persisted fingerprints |
| `backend/tests/t_invest_mapping_fixtures.py` | Integration | Accepted synthetic provider mapping without quote calls |
| `backend/tests/_statement_pdf.py` | Import/export | Synthetic statement document construction |
| `backend/tests/startup_network_guard.py` | Runtime/network-free | Startup probe and external-network guard |


<a id="d4-test_suite_guide-1-frontend-and-external-lanes"></a>
#### Frontend and external lanes

Vitest does not use pytest markers. Its existing directories are the semantic
ownership map:

| Surface | Owner/lane |
| --- | --- |
| `frontend/src/api/` | API client and DTO behavior |
| `frontend/src/lib/` | Pure formatting, period, chart, and display helpers |
| `frontend/src/components/` | Component and month-editor interactions |
| `frontend/src/ui-v2/` and `frontend/src/app/` | Page, workspace and routing flows |
| `frontend/e2e/` | Synthetic smoke and visual behavior |
| `scripts/tests/` | Release, workflow, and changed-path contracts |

Keep frontend tests in the existing API/lib/component/page split; do not add
backend-style directories only to make the trees look symmetrical.


<a id="d4-test_suite_guide-1-useful-targeted-commands"></a>
#### Useful targeted commands

From `backend/`, use a marker for the semantic implementation loop. The full
command below is available when a local full gate is needed under
D4; it is not mandatory in addition to complete relevant CI.

```powershell
uv run --locked python -I -m pytest -q -m domain
uv run --locked python -I -m pytest -q -m "migration or persistence"
uv run --locked python -I -m pytest -q -m "integration and network_free"
uv run --locked python -I -m pytest -q -m benchmark
uv run --locked python -I -m pytest -q tests/test_ci_lane_ownership.py
uv run --locked python -I -m pytest -q
```

For an individual execution shard, use the marker expression from the [current workflow matrix](../.github/workflows/ci.yml); do not maintain a second shard command list here.

`benchmark` is an explicit performance lane; it is preserved and selectable,
not silently removed from the default correctness suite in Phase 2A. A marker
selection is targeted evidence, not a claim that unrelated lanes passed.


<a id="d4-test_suite_guide-1-local-helper-versus-ci"></a>
#### Local helper versus CI

The root [scripts/test.ps1](../scripts/test.ps1) is an optional developer convenience, not a mandatory handoff command. It does not replace the [canonical workflow](../.github/workflows/ci.yml), which owns the full set of product, browser, privacy, release and Windows jobs. Use their actual results and D4's proportional rules instead of duplicating them locally for each role.

Browser acceptance protects the real synthetic monthly journey and unique financial/lifecycle interactions. Its current project selection and execution order live in the workflow and project configuration; a docs-only fast path does not claim those journeys passed. Retired Launcher/phone coverage must not be restored by an old candidate; preserve the supported direct-runtime and desktop guarantees.

Playwright suites share `frontend/playwright.config.ts`. From `frontend`, run
`npm run test:e2e:<name>` or `npx playwright test --project=<name>`.
Select one project per execution: each suite retains its own server command,
port, environment and output directory, and some fixture servers share ports.
An unqualified execution retains the original `chromium` suite.
`npx playwright test --list` lists all projects; add `--project=<name>` to
inspect one suite. The separate `playwright.visual.config.ts` retains the
`1366x768`/`1440x900`/`1920x1080` matrix, viewport ownership and exact-head
UI evidence identity/duplicate omission. Continue using `npm run audit:visual`
for that matrix and its evidence producer.

Use D4 for the proportional implementation and
final-gate rules. When a task changes only docs or test organization, review
the diff and run the policy-relevant checks; do not rerun unrelated full
product suites merely because a release-ID file still exists.


<a id="d4-test_suite_guide-1-optional-future-coverage-work--not-active-backlog"></a>
#### Optional future coverage work — not active backlog

No issue is queued for the items below. Reopen one only when a product/risk need justifies a node-level coverage map and Owner/Integrator decision:

- rehoming or renaming release/task-ID files and payout suffix fragments;
- deciding whether G02/G08 are distinct acceptance evidence or overlap with
  the browser smoke path;
- comparing large frontend interaction suites and any exact duplicate nodes;
- deleting or merging any assertion, including an apparently old release
  regression.

<a id="d4-ci_test_optimization_playbook-1"></a>
### Verification optimization without coverage loss

The 2026-09-16 speed pass is closed. Treat this as guidance for a new, concrete bottleneck, not a standing queue. The full method and measurements remain in the [archived playbook](archive/2026-10-18/docs/CI_TEST_OPTIMIZATION_PLAYBOOK.md) and [closeout](archive/2026-10-18/docs/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-09-16.md); copy the method, not Hermes-specific numbers or selections.

<a id="d4-ci_test_optimization_playbook-1-purpose"></a>
<a id="d4-ci_test_optimization_playbook-1-core-principle"></a>
**Core principle.** Optimize execution topology before changing tests. Prefer, in order: remove duplicate execution; narrow platform-specific lanes to their unique guarantees; reuse artifacts safely inside one job; parallelize independent work; optimize measured expensive fixtures; consolidate tests only when semantic equivalence is proven. Mass deletion is not a performance strategy.

<a id="d4-ci_test_optimization_playbook-1-step-1--establish-a-real-baseline"></a>
- **Baseline.** Use several successful runs from comparable repository states. Record test/step time, job time, whole-CI wall time, counts, setup/build, critical path and runner. Do not attribute a pipeline gain to one change when another job or runner variance dominates.

<a id="d4-ci_test_optimization_playbook-1-step-2--audit-duplicate-execution-first"></a>
- **Duplicate execution.** Look for the same verification invoked by a workflow and a script, a full suite in several lanes, repeated artifact builds, nested harnesses, or release smoke duplicating normal CI. Ask whether assertion, artifact/state, protected boundary and canonical path are identical. Remove duplicate execution, not the canonical guarantee.

<a id="d4-ci_test_optimization_playbook-1-step-3--map-platform-specific-lanes-to-guarantees"></a>
- **Platform lanes.** Classify each node as must-run-on-this-platform, already-owned-elsewhere or uncertain. Never narrow a Windows/macOS/Linux lane merely because a test name exists elsewhere; prove where the guarantee still runs and document ownership.

<a id="d4-ci_test_optimization_playbook-1-step-4--inspect-expensive-setup-separately-from-assertions"></a>
- **Expensive setup.** Profile database/schema creation, fixtures, process and browser startup, dependency restore, compilation, artifact publishing and cleanup separately from assertions. Optimize the real cost, not the assertion by habit.

<a id="d4-ci_test_optimization_playbook-1-step-5--try-bounded-parallelism-only-after-proving-independence"></a>
- **Bounded parallelism.** First inspect shared globals, database/filesystem writes, output filenames, ports, environment, fixture directories, ordering and cleanup. Prefer the smallest concurrency change; keep within-file parallelism disabled where ordering still matters, and require repeated runs rather than one green CI.

<a id="d4-ci_test_optimization_playbook-1-step-6--keep-experiments-isolated"></a>
- **Isolation.** One performance hypothesis per PR: one duplicate harness, lane, worker count or fixture strategy. Do not combine worker changes, fixture rewrites, lane reshuffles and test deletion.

<a id="d4-ci_test_optimization_playbook-1-step-7--verification-contract-for-an-optimization-pr"></a>
- **Verification contract.** Compare node counts before/after; show no unintended skips; retain passing tests and a canonical owner for removed executions; keep artifacts and fail-closed behavior complete; limit the diff; preserve privacy/runtime boundaries; pass exact-head PR CI and canonical exact-main push CI. Concurrency changes need repeated runs.

<a id="d4-ci_test_optimization_playbook-1-step-8--report-timing-honestly"></a>
- **Honest timing.** Report baseline and candidate ranges, step/job/whole-CI time, counts, runner/platform differences and whether the target remained critical. Do not promise a fixed speedup from hosted-runner samples.

<a id="d4-ci_test_optimization_playbook-1-go--no-go-guidance"></a>
<a id="d4-ci_test_optimization_playbook-1-strong-go"></a>
<a id="d4-ci_test_optimization_playbook-1-conditional-go"></a>
<a id="d4-ci_test_optimization_playbook-1-usually-no-go"></a>
| Decision | Use when |
|---|---|
| Strong GO | Duplicate execution is proven, coverage is unchanged, the change is small, gain is material to the critical path and failure semantics stay identical. |
| Conditional GO | Adding concurrency, caching/reusing mutable artifacts, changing fixture topology or moving tests between platform lanes; require repeated evidence. |
| Usually NO-GO | Gain is seconds, shared mutable fixtures appear, toolchain/reproducibility changes only for speed, publish/install/fail-closed semantics weaken, the target is no longer near the critical path, or the optimization makes tests significantly harder to understand or maintain. |

<a id="d4-ci_test_optimization_playbook-1-stop-rule"></a>
**Stop rule.** Stop when obvious duplicate work is gone, platform lanes have clear ownership, safe parallelism is used, remaining cost is real high-value verification, current CI latency is acceptable and the next gain is small relative to complexity or risk.

<a id="d4-ci_test_optimization_playbook-1-suggested-audit-prompt"></a>
> Audit the current CI for safe performance improvements. Treat GitHub as source of truth. Identify the actual critical path, duplicate execution, platform-overbroad coverage, expensive setup and safe parallelism opportunities. Do not assume an optimization is required. Preserve regression, privacy, runtime and domain contracts. For each opportunity give expected value, risk and GO/NO-GO; recommend only the next highest-value bounded change.

Keep durable rules in this book; do not copy the project constitution into every task prompt.

<a id="d4-ci_test_optimization_playbook-1-applying-this-to-another-project"></a>
**Other repositories.** Start from that repository's main and CI history; inventory its lanes and contracts independently; establish its own baseline; do not assume Hermes bottlenecks; change one small thing per PR; preserve its health/data/privacy semantics; write a project-specific closeout when the stop condition is reached.


<a id="d4-ui_v2_aggregate_verification-19"></a>
### Aggregate coverage and shared-spine verification

<a id="d4-ui_v2_aggregate_verification-19-shared-spine-reconciliation"></a>
#### Shared-spine reconciliation

- Mechanical App/entry conflicts were resolved additively: allocation, monthly-result and Performance detail each keep their own route/lazy entry. No sibling was selected wholesale.
- Capital combines accepted allocation and monetary-result links with accepted Performance summary/detail. Monetary result is cash income for a reporting month plus separately labelled unrealized snapshot evidence; Performance uses exact snapshot dates, historical scope and backend-owned interval returns. Neither replaces the other.
- Main/#538 and #621–#624 source/coverage and lifecycle protections remain in ancestry. The union uses canonical readiness, preserves null/unknown/partial, and retains existing query keys. Mutation invalidation and restore invalidation retain Performance and Monthly Close reads; no financial calculation was added in React.
- Empty Home/Capital/Income close actions now go to `/v2/close`; Home's payouts/forecast action goes to `/v2/income`. Native Monthly Close origin/step/month query and editor return mapping are retained. Retired legacy routes redirect to their native `/v2` workspaces.
- Required `g04-browser` CI job runs G04 and Performance, builds the production frontend, then runs the accepted statement and Monthly Close configs serially, with zero retries. Synthetic screenshots/traces are retained as `native-v2-real-backend-evidence`. Full Vitest uses `--maxWorkers=1` locally and in CI.
- Visual discovery adds existing month/editor/import/payout/IIS/allocation/Scenario specs. Allocation uses `/v2/capital/allocation` on the actual App route rather than the standalone leaf fixture. API-mocked visual evidence remains distinct from real-backend evidence.


<a id="d4-ui_v2_aggregate_verification-19-job--spec--scenario-matrix"></a>
#### Job / spec / scenario matrix

Paths below are under `frontend/` unless another root is shown. A listed spec is a mapping, not a claim it ran; exact execution outcomes are recorded below and in final-head CI.

| Capability / boundary | Native route or action | Executable evidence / canonical job |
| --- | --- | --- |
| Default entry, Shell, route union, lazy failure | `/`, `/v2`, three Capital details; retired routes redirect | `src/app/App.test.tsx`, `src/ui-v2/UiV2Shell.test.tsx`, `e2e/ui-v2-default-switch.spec.ts`; frontend / visual / UI evidence |
| Home confirmed picture; empty/first/zero/partial/error | `/v2` latest CLOSED; native close action | `src/ui-v2/UiV2Page.test.tsx`, `e2e/ui-v2.visual.spec.ts`; frontend / visual |
| Capital state/history/holdings/coverage and returns | `/v2/capital`; no capital delta as return | `src/ui-v2/UiV2CapitalPage.test.tsx`, `e2e/ui-v2.visual.spec.ts`; frontend / visual |
| Closed historical monetary result by account/class | `/v2/capital/monthly-result?month=<closed-id>&view=accounts|classes` | `src/ui-v2/UiV2MonthlyResultPage.test.tsx`, `e2e/ui-v2.visual.spec.ts`; latest/older, zero/loss, cash-only nulls, account-only events, stale/reopened/restore identity |
| Allocation/concentration/support | `/v2/capital/allocation?month=<id>` | `src/ui-v2/UiV2CapitalAllocationPage.test.tsx`, `e2e/ui-v2-capital-allocation.spec.ts`; selected draft/closed, unsupported denominator, desktop/keyboard; frontend / visual |
| Income facts/planning/forecast/ladder | `/v2/income`; historical facts remain local | `src/ui-v2/UiV2IncomePage.test.tsx`, `e2e/ui-v2-income.visual.spec.ts`; frontend / visual; principal is not passive income |
| Goals CRUD/main/active/local as-of | `/v2/income/goals?month=<id>` | `src/ui-v2/GoalsWorkspace.test.tsx`, `src/app/App.test.tsx`, `e2e/ui-v2-income.visual.spec.ts`; frontend / visual |
| Tax/IIS planning and account write tools | `/v2/income/tax-iis`, `/v2/data/catalogs?tab=accounts&account=<id>` | `src/ui-v2/UiV2TaxIisPage.test.tsx`, `src/ui-v2/UiV2IisAccountForms.test.tsx`, `e2e/ui-v2-iis-forms.spec.ts`; account/year identity, readback, ambiguous lock, keyboard/desktop |
| Months create/clone/delete/local selection | `/v2/data/months` | `src/ui-v2/UiV2MonthsPage.test.tsx`, `e2e/ui-v2-months.spec.ts`; frontend / visual; clone source lifecycle also in backend full |
| Six editor slices and dirty navigation | `/v2/data/months/:id?section=...` | `src/ui-v2/UiV2MonthEditorPage.test.tsx`, `UiV2MonthPositionsSection.test.tsx`, `UiV2MonthAssetsSection.test.tsx`, `UiV2MonthPayoutsSection.test.tsx`, `UiV2MonthBudgetSection.test.tsx`, `UiV2MonthLiabilities.test.tsx`; `e2e/ui-v2-month-editor.visual.spec.ts` (mocked API) |
| Native import/apply/authoritative persistence | `/v2/data/payouts?month=<id>#statement-import` | `e2e/statement-import.acceptance.ts` via `playwright.config.ts --project=statement`; **real backend**, temp SQLite/synthetic PDF, cancel, foreign-month row disabled, one keyboard write, reread/reload/duplicate, desktop; `g04-browser` |
| Import failed/ambiguous/stale/CLOSED state | Native statement/Alfa tools | `src/ui-v2/UiV2StatementImportSection.test.tsx`, `src/ui-v2/UiV2AlfaBaselinePage.test.tsx`, `e2e/ui-v2-statement-import.spec.ts`; backend import/atomicity tests; frontend / visual / backend lanes |
| Forecast payouts and calendar | `/v2/data/payouts?month=<id>` | `src/ui-v2/UiV2PayoutForecastPage.test.tsx`, `e2e/ui-v2-payout-forecast.spec.ts`; frontend / visual; dated principal and passive income remain distinct |
| Monthly Close native edit/return/fresh final review | `/v2/close?month=<id>&step=final_review_close` | `e2e/monthly-close.acceptance.ts` via `playwright.config.ts --project=monthly-close`; **real backend**, persisted expense, fresh workflow read on return, dirty cancel/discard, failed write and mismatched read guards; `g04-browser` |
| Close/report/reopen; historical archive | Same close context, `/v2/reports/:id` | Same retained **real-backend** scenario: confirmation cancel, persisted CLOSED, hidden mutations, actual older archive after a later closed report, refresh, next-month return, explicit reopen; desktop/keyboard |
| Repeat/stale/concurrent CLOSED/deleted/invalid target | Close and editor exact month | `src/ui-v2/UiV2ClosePage.test.tsx`, editor tests and real-backend deleted/duplicate query checks; backend close/write atomicity in full lanes |
| Reports/archive latest/draft/missing/coverage | `/v2/reports`, `/v2/reports/:id` | `src/ui-v2/UiV2ReportsPage.test.tsx`, `src/ui-v2/UiV2ReportPage.test.tsx`, `e2e/ui-v2.visual.spec.ts` and actual archive above |
| Performance unavailable -> XIRR-only -> observed PRE/POST -> TWRR | `/v2/capital/performance?start=...&end=...&scope=account&account_id=...` | `e2e/performance-real-backend.spec.ts`; **real backend**, public supported writes, temporary SQLite, no provider calls; correction invalidates coverage/captures, stale form gets 409, CLOSED write rejected, Back/refresh/desktop/keyboard; `g04-browser` |
| Performance period/scope/error/null/zero/unsupported | Same detail; preparation hash/context | `src/ui-v2/UiV2CapitalPerformanceDetail.test.tsx`, `capitalPerformanceContext.test.ts`, existing preparation/capture component tests, `e2e/performance-preparation.visual.spec.ts`; frontend / visual; historical membership is explicit |
| Freshness/reconciliation/accounts/catalogs/mappings/settings/diagnostics | `/v2/data`, `/v2/data/reconciliation`, `/v2/data/catalogs`, `/v2/data/app` | `src/ui-v2/UiV2DataSourcesPage.test.tsx`, `UiV2DataReconciliationPage.test.tsx`, `UiV2DataCatalogsPage.test.tsx`, `UiV2DataAppPage.test.tsx`, `e2e/ui-v2-data.visual.spec.ts`; frontend / visual; provider calls remain mocked/offline |
| Export/download/backup/restore | `/v2/data/files` | `src/ui-v2/UiV2DataFilesPage.test.tsx`: exact restore confirmation/focus, failed/ambiguous results, no repeat, financial reads invalidated; monthly-result stale restore identity tests; real-backend Close scenario deletes/restores synthetic month then reloads |
| Scenario input/result/local month/export | `/v2/income/scenario-lab?month=<id>` | `src/ui-v2/UiV2ScenarioLabPage.test.tsx`, `e2e/ui-v2-scenario.spec.ts`; calculate, backend DTO/download, desktop/keyboard/Back/refresh; frontend / visual; canonical financial service in backend full |
| Retired-route redirects and safety gates | `/v1` and legacy paths redirect to native `/v2` workspaces | `src/app/App.test.tsx`, `e2e/ui-v2-default-switch.spec.ts`; privacy, backend quality/full lanes, Windows timezone/production smoke and release safety in canonical CI |

Full local backend and frontend gates cover all retained tests, including failure cases above. They do not turn an API-mocked component/visual test into real persisted financial evidence. The synthetic Close restore probe explicitly reloads after a confirmed backend restore; UI transport/ambiguous/failed restore behavior has component and backend coverage, not a claim of a real-history Owner restore.


<a id="d4-ui_v2_aggregate_verification-19-ordinary-links-and-deliberate-legacy-fallback"></a>
#### Ordinary links and retired-route redirects

Ordinary close actions from empty Home/Capital/Income stay native; Home's income/forecast action stays native. Native Close action maps and Final Review Edit links preserve exact month/step/section; current CLOSED review hides mutations.

Retired `/v1` and legacy routes redirect to their native `/v2` workspaces; there is no previous-interface link, fallback or second editor. Native-origin Close uses only the accepted native map. D1 KEEP and D2's bounded global-selector reduction are unchanged; local facts/editor/Goals/Tax/Scenario/risk/Performance context remains.

<a id="d4-ui_v2_owner_uat-5"></a>
### Real Owner UAT procedure

<a id="d4-ui_v2_owner_uat-5-assignment-and-backup-first"></a>
#### Assignment and backup first

Integrator/Owner must first identify the exact candidate SHA, trusted control checkout, independent Preview checkout, Preview data directory/database, Stable checkout/data/database and representative-history source. These private local assignments remain Owner-controlled and absent from repository evidence. A missing required assignment is a concrete gate; do not invent paths or use a developer workspace.

Stop the relevant Owner runtime through its supported operation. Create and verify a backup with the existing Owner backup/recovery procedure **before copying or changing any history**. Use a consistent verified physical database copy, with confirmed isolation from Stable and its SQLite sidecars. The copy must contain representative existing history: older and latest closed reports, a draft, meaningful account/class/cash/instrument contexts and relevant return boundaries. An empty/synthetic stand cannot demonstrate real-history UAT. The explicitly assigned Owner-local operator/reviewer may read relevant source/DB/statement/screenshot evidence under D1 authorization. Credentials remain excluded, private payloads stay outside tracked code/CI, and reads do not authorize writes, runtime changes or publication. A normal development assignment supplies no private-data authority by itself.

Use the accepted OPS03 command from a trusted control checkout. Variables below are the explicit Owner assignment, not suggested paths:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-preview.ps1 `
  -CandidateSha $CandidateSha `
  -PreviewCheckout $PreviewCheckout `
  -PreviewDataDirectory $PreviewDataDirectory `
  -PreviewDatabase $PreviewDatabase `
  -StableCheckout $StableCheckout `
  -StableDataDirectory $StableDataDirectory `
  -StableDatabase $StableDatabase `
  -ControlCheckout $ControlCheckout
```

OPS03 validates separation, pins an independent clone, and composes Prepare/Validate. It does not Start or directly migrate. After its boundary is prepared, Owner populates Preview with the verified isolated representative-history copy using the existing supported Owner process, rechecks the selected DB assignment, and starts from that approved Preview checkout:

```powershell
git rev-parse HEAD
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1 `
  -Checkout $PreviewCheckout -Validate
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Confirm the reported HEAD equals the selected final candidate and startup selects only the assigned Preview DB. Start uses existing migration semantics for that isolated DB. A failed identity/boundary/backup check stops UAT. Do not bypass prepared-state or recovery guards. See [Owner runtime operations](OWNER_RUNTIME_OPERATIONS.md#o2-owner_runtime_operations-80-6-exact-previewuat-preparation) and [runtime safety ADR](adr/0014-launcher-runtime-profile-safety.md).

**Preview writes are only Preview writes.** A September close/reopen/import in Preview does not close/reopen/import production. No automatic copying back, database promotion, Stable repointing or deletion follows UAT. Actual production close requires the separately approved exact code/runtime update and Owner operation; retain the original history and verified backup.


<a id="d4-ui_v2_owner_uat-5-short-journey-and-expected-results"></a>
#### Short journey and expected results

Use loopback UI in the approved Preview. Select exact targets locally; do not publish IDs, dates/amounts or screenshots. For each step record only PASS/FAIL/NOT TESTED and a non-reconstructive observation. A failed mandatory step blocks Owner PASS; missing applicable source evidence stays unavailable.

| Step | Actual UI labels / route | Expected result |
| --- | --- | --- |
| 1. Confirm picture/history | `Мои финансы`, `Капитал`, `Все отчёты`; open an older `Исторический отчёт` | Latest CLOSED is the confirmed picture; archive has the selected older closed report, correct context and read-only values; Back/refresh keeps its target. A draft is not an archived fact. |
| 2. Prepare the draft | Open `/v2/close`, inspect the chosen month; use `Бюджет` / `Изменить`, then `Редактор месяца` | Edit only the intended draft, save a harmless known test change in Preview, and verify confirmation/readback. `Вернуться к закрытию` preserves month and step and refreshes readiness. Cancel/discard an unsaved edit explicitly. |
| 3. Native import | Close's statement action, or `Данные` -> payouts for that month; `Проверить отчёт`, `Подготовить к импорту`, `Применить выбранные строки` | Only rows belonging to the selected month can apply. `Отмена` writes nothing. `Подтвердить и применить` writes once, then authoritative reread/reload shows the result; re-import is a duplicate. Owner-authorized local existing local statement/source; no live provider call is needed for this test. |
| 4. Final review and close | Final step, `Закрыть месяц`, confirmation `Закрыть` | Review actual refreshed state and blockers. Escape/cancel leaves a draft. Confirm only in Preview; `Месяц зафиксирован` follows persisted CLOSED and fresh workflow. Mutation/Edit actions disappear. |
| 5. Return/reopen | `Создать следующий месяц`, `Вернуться к закрытию исходного месяца`, `Открыть месяц заново`, `Открыть заново` | Return keeps the original month/step. Reopen requires explicit confirmation; cancel keeps CLOSED, confirmed reopen becomes the same draft after reread. Check desktop, keyboard focus and Back/refresh. |
| 6. Monetary result and allocation | `Капитал` -> `Денежный результат`; `Распределение и концентрация` | Older/latest closed result has separate cash-income and unrealized-snapshot meaning; cash-only rows keep nulls, zero/loss stay truthful. Account and class cuts need not total alike. Allocation preserves local month, canonical denominator/support and future-event exclusions. |
| 7. Performance Phase A | `Капитал` -> `Доходность`, exact period and account/portfolio selection; `Проверить данные` | Snapshot dates/scope/currency remain exact. Unavailable reasons are visible. XIRR-only is valid when TWRR evidence is missing. Save only actual supported evidence already possessed by Owner; never manufacture PRE/POST amounts, infer membership from current flags or mark empty histories complete. TWRR becomes available only when canonical evidence supports it. Back/refresh retains period/scope. The delivered bounded no-crossing class capability follows C7; unsupported evidence stays unavailable, and current real UAT scope belongs in S2. |
| 8. Income / local tools | `Доход и планы`, Goals, Tax/IIS planner/account catalogs; Scenario `Рассчитать сценарий` and local export | Actual income, forecast and principal remain distinct. Local month/as-of/account/year context survives actions. Goals main/active behavior and IIS confirmation/readback remain correct; Scenario export represents the chosen calculation. Global historical/draft Dashboard planning is intentionally de-scoped by D2. |
| 9. Recovery on the isolated copy, if applicable | `Экспорт и копии`; create a local backup and confirm its exact restore target | Test only against the assigned Preview copy. Cancel/failed/ambiguous restore does not claim success or silently retry. Confirmed success retains pre-restore backup evidence and reloads current reads; a removed month must show missing, not silently select another. Afterward verify the same assigned database/identity. |
| 10. Reconcile and report | Latest/older report, monetary result, Performance, settings/diagnostics; native `/v2` route if needed | Report only labelled PASS/FAIL/NOT TESTED and sanitized UI observations. Do not attribute a missing ordinary action to a retired fallback. Keep private values/files/backup IDs locally. No production transition or release is implied. |

Earlier Performance Owner PASS explicitly deferred representative real-history evidence. It does not cover this common candidate. Integrator records the actual Owner disposition on this exact tree, or explicitly proves tree equivalence; after that, main merge, exact-main push CI, release identity and supported runtime update are separate decisions.

<a id="d4-mobile_retirement_coverage-5"></a>
### Preserve unique desktop test coverage

<a id="d4-mobile_retirement_coverage-5-removed-versus-retained-scenarios"></a>
#### Removed versus retained scenarios

Desktop/laptop only (#747): phone/390px duplicates were removed; unique financial, actual-backend, lifecycle and keyboard coverage remains at 1366/1440/1920. No phone UAT or mobile matrix is required, and phone variants must not be restored when integrating old branches. Dated #747 detail remains in Git history; the current specs and D4 matrix are the coverage map.

<a id="d4-mobile_retirement_coverage-44"></a>
### Fixture and expected-image protections

<a id="d4-mobile_retirement_coverage-44-fixtures-expected-images-and-active-checks"></a>
#### Fixtures and expected images

Screenshots remain generated artifacts, not tracked phone baselines. Shared fixtures, desktop configs, visual evidence and safety lanes are unchanged; no blanket exclusion or disabled evidence is introduced.

<a id="d4-r07-t02-long-history-3"></a>
### Repeatable long-history measurements

<a id="d4-r07-t02-long-history-3-scope-and-method"></a>
#### Scope and method

This report measures the existing read paths before any production
optimization or materialization. Every value is synthetic. Each case creates
a fresh temporary SQLite database with `Base.metadata.create_all`, seeds the
same deterministic shape, performs one warm-up request, and records five
measured requests. Timings are local wall-clock observations on the Windows
development host; they are not CI performance guarantees.

The generator and harness are [r07_t02_long_history.py](../backend/benchmarks/r07_t02_long_history.py).
Run it from `backend`:

```powershell
$env:UV_CACHE_DIR = (Resolve-Path '.uv-cache').Path
uv run python benchmarks/r07_t02_long_history.py --years 1 5 10 20 --repeats 5
```

The harness measures median and p95 wall time, maximum SQL statement count
from SQLAlchemy's `before_cursor_execute` hook, and maximum response size.
Seed/setup, warm-up, and synthetic backup creation are excluded from the
timings. Dashboard and export calls target the latest closed month. The
backup read is `GET /api/backups` after creating one synthetic backup. The
lifecycle operation is one `clone -> close -> reopen` sequence.

The 20-year case contains 240 closed reporting months and the following
deterministic row shape:

| Table | Rows | Scaling |
| --- | ---: | ---: |
| reporting_months | 240 | 12/month |
| accounts | 5 | fixed |
| instruments | 8 | fixed |
| position_snapshots | 3,840 | 16/month |
| deposit_snapshots | 480 | 2/month |
| cash_balances | 240 | 1/month |
| income_entries | 240 | 1/month |
| investment_cash_flows | 960 | 4/month |
| expected_cash_flows | 960 | 4/month |
| expense_entries | 240 | 1/month |
| debts | 240 | 1/month |
| property_snapshots | 240 | 1/month |


<a id="d4-r07-t02-long-history-3-budgets"></a>
#### Budgets

These are pragmatic local-development budgets for the representative
operations, not user-facing SLAs.

| Operation | 20-year p95 budget |
| --- | ---: |
| dashboard load | <= 2,500 ms |
| capital-composition analytics | <= 1,000 ms |
| Markdown export | <= 3,000 ms |
| JSON export | <= 3,000 ms |
| clone -> close -> reopen | <= 250 ms |
| backup listing | <= 100 ms |

<a id="d5"></a>
## 5. Delivery, integration and documentation maintenance

Worker may commit/push the assigned branch and open the authorized PR. Return baseline/target, exact candidate SHA, branch/workspace, changed files/stat, actual checks/limits and final HEAD/remote/working-tree readback. Use one linked issue/PR receipt; no new process ledger. Required independent review and Owner UAT remain independent gates.

Integrator inspects exact diff/privacy/contracts and accepted review/UAT, then uses expected-head guarded integration when authorized. PR CI must pass on the accepted exact candidate; after merge canonical push CI must pass on the exact merge SHA. Neither replaces the other. Only main is canonical/releasable; integration/* is staging. Changed semantics return for review; proven nonsemantic edits may reuse applicable evidence with original scope. Worker cannot merge, force-push, delete branches/tags, publish or change repository settings without separate authority.

#### One canonical home per rule

| Book | Owns | Exact update trigger | Accountable owner |
|---|---|---|---|
| P — MASTER_SPEC | Product scope, supported user journeys, screens and UX | An accepted change changes a user-visible scenario, supported capability, interpretation or desktop interaction | Implementing Worker drafts the affected clause; Integrator accepts the product wording, Owner decides new scope |
| C — ARCHITECTURE_AND_CONTRACTS | Architecture and normative financial/data/API/export meaning | An accepted change changes a formula/unit, source authority, state/reason, receipt/version/currentness, schema compatibility, API consumer or supported metric | Implementing Worker updates the owning subsection; independent financial/security/domain Reviewer where risk requires; Integrator accepts |
| D — DEVELOPMENT | Roles, workspace, implementation, verification, delivery and this maintenance contract | An accepted workflow/tool/client/testing/integration change changes what contributors must do | Worker changing that process drafts; Integrator owns acceptance |
| O — OWNER_RUNTIME_OPERATIONS | Stable operating/release/backup/recovery/provider setup and workspace procedures | An accepted operation contract changes commands, prerequisites, boundaries, recovery behavior or lifecycle | Assigned operations Worker drafts the procedure; Integrator accepts, Owner authorizes actual operations |
| S — CURRENT_STATUS | Single current code/release/installed/UAT/limitation/next-action evidence | Acceptance/integration, terminal exact-main CI, publication, verified local installation/UAT, changed blocker or authoritative next-action decision changes the truth of a current claim | Integrator; assigned Worker may propose sourced edits without self-acceptance |

Update the existing owning subsection in the same change when its meaning changes; cross-link it from other books instead of copying its rule. An unchanged handoff, poll, new chat or routine PR creates no documentation task. Do not create a new document/closeout per PR or duplicate status in README, O, release notes or adapters. ADRs record durable decisions only when such a decision exists; machine schemas and version release notes keep their distinct purposes. Keep dated evidence as history, never refresh its old PASS/next-step text into current instructions. The archive migration map is provenance for this consolidation, not a recurring ledger.

AGENTS is a short executable router to current D/C/O anchors, with critical boundaries. Client-specific mechanics live in D6; installed external skills/config are machine-local. Repair a routing link when its target moves; do not establish a second handbook.

#### Concise documentation review checklist

- Is each changed rule in its single owning subsection, with links from dependents and no duplicate status?
- Are formulas/units/NULL/coverage, source authority, receipts/currentness, writer/Close limits and permissions unchanged unless explicitly accepted?
- Do current claims cite exact SHA/run/decision/local receipt and distinguish code, release, installation and UAT?
- Are links/anchors, runtime schema/fixture/release-note paths and released migration bytes preserved?
- Does the exact candidate have the required proportional checks, independent review/UAT and CI, with remaining limits stated?

No model accounting, mandatory new document per PR or additional approval loop is introduced.

<a id="d5-agent_orchestration-20"></a>
### Guarded delivery, acceptance and linked receipts

With direct GitHub capability, the Integrator performs authorized repository mechanics rather than making the Owner relay commands.
Existing standing Owner authorization covers this standard flow without repeated approval:

1. Create/update the task issue, PR and repository metadata under the accepted assignment.
2. Inspect the exact candidate, scope/privacy, contract and required independent-review/UAT evidence.
3. Diagnose CI; make only clearly mechanical in-scope corrections on the task branch, without a concurrent writer.
4. Reuse valid evidence and rerun failed checks for an established mechanical/infrastructure cause; follow D4, not a second full-suite ritual.
5. Merge an accepted candidate after required PR CI/review/UAT, with an exact-head guard where supported.
6. Read back canonical main and verify its exact push CI before reporting integration complete.
7. Update only documentation whose meaning changed: current outcomes/gates in `CURRENT_STATUS.md`, durable concepts in
   the owning P/C/D/O subsection or their owning procedure. Keep dated records intact; add a linked later receipt when needed.
   A handoff, CI poll or unchanged candidate does not require another Wiki/status/closeout edit.

Tool access alone grants no authority; the standing delegation above does. Workers cannot adopt it by changing their role label.
A post-review nonsemantic correction may retain earlier semantic review only after the Integrator proves the exact diff changes no executable/product/financial meaning.
Standard mechanics never authorize new product/financial semantics, architecture/invariants, migration/data reinterpretation,
privacy/runtime/network-boundary expansion, behavior-changing fixes outside accepted scope or missing review/UAT evidence.
Those cases return to the task/decision path; a green rerun does not replace a missing decision.
Force-push, destructive reset/rebase, branch/tag deletion, release publication and repository settings require their separate explicit authority.

<a id="linked-handoff-receipts"></a>

<a id="d5-agent_orchestration-20-linked-handoff-receipts"></a>
#### Linked handoff receipts

Use the existing issue/PR and review/acceptance notes with the AGENTS completion fields, not a new ledger or copied logs. Link the exact candidate, changed files, actual checks/limits and verdict, with earlier evidence tied to its original SHA/scope. Worker delivery, independent review and Integrator acceptance remain separate; a receipt is not merge authority.


<a id="d5-agent_orchestration-20-staged-integration-for-parallel-slices"></a>
#### Staged integration for parallel slices

Use temporary `integration/*` staging early when sibling tasks overlap shared application structure or must be Owner-UATed together; main remains the only release source.
- Each task retains its isolated child branch/workspace; Workers do not merge siblings or independently refresh from main.
- Integrate an exact accepted head promptly and run proportional integration smoke, not a mandatory extra full suite.
- Later candidates should use the current accepted staging context when practical or prove compatibility; baseline reconciliation is Integrator-owned.
- Shared routing/navigation/configuration reconciliation has one owner. Prefer leaf changes and additive/declarative registration where appropriate; no permanent list of UI filenames.
- Preserve each accepted task contract. A semantic conflict returns to an Integrator decision, not a Worker choosing which sibling wins.
- Owner UAT uses one exact aggregate SHA containing accepted slice ancestry, with its own required CI/evidence.
- Required financial/mutation/Monthly Close/restore/migration/runtime/provider review and Owner gates still apply before canonical main.
- After PASS, integrate that tested aggregate tree or a proven exact-equivalent tree, then verify exact-main push CI. Do not reconstruct an unproven aggregate after UAT.


<a id="d5-agent_orchestration-20-mode-b--experimental-codex-delivery-loop-explicit-opt-in"></a>
#### Mode B — optional delivery loop

Only an explicit instruction activates a delivery loop or queue; mention, audit or editing is not activation. Default remains one Worker. Optional queue mechanics and coordination limits are in D6; internal statuses never equal project acceptance or merge authority.


<a id="d5-agent_orchestration-20-overhead-budget"></a>
#### Overhead budget

Start with one Worker and at most one independent Reviewer role. Extra writers/roles/replacement sessions need a concrete coordination benefit and explicit authorization.
Do not add readiness-only model turns, nested delegation, speculative explorers or reviewers-of-reviewers by default.
Use small environment checks and existing valid evidence; required safety/review gates are not waived for a session budget.
Normal completion does not require model/provider identity, usage telemetry or a phase-by-phase ledger.


<a id="d5-agent_orchestration-20-queue-policy"></a>
<a id="d5-agent_orchestration-20-single"></a>
#### Queue policy

Only an explicit instruction activates a delivery loop or queue; default execution remains one Worker. Queue status never equals project acceptance, merge authority or permission to skip required review.

<a id="d6"></a>
## 6. Optional orchestration and client mechanics

Default execution is one accountable Worker and only required independent review. A request for autonomous/careful work does not activate an unattended queue. Optional delivery-loop mode requires explicit opt-in and a concrete coordination reason; it does not grant canonical integration authority.

Honor an explicitly selected execution client; direct GitHub access does not justify replacing it. ChatGPT Integrator reads actual refs/diffs/checks and reports GitHub-native evidence rather than local commands it did not run; authorized repository mechanics are performed directly, with release control only for an explicitly authorized prepared release. Codex defaults to the receiving Worker session unless assigned another role; no coordinator is compulsory. Give an independent Reviewer pinned base/candidate, relevant literal issue/source excerpts, previous findings and existing check evidence. A network-disabled Reviewer needs literal sources, not inaccessible URLs; cheap packet checks are sufficient. A child inheriting writable rights does not prove enforced read-only isolation.

Hermes is a first-class Worker: receiving session owns one final candidate, optional helpers remain bounded and gain no acceptance/merge authority, and no ordinary delegate/fallback ledger is required. Hermes does not require Codex-local skills. OpenCode uses its configured isolated root and inspects sibling delivery via GitHub/remote refs or an assigned independent review path. Gemini/Grok add no project-wide orchestration/provider scheme. Machine-specific launch settings and concrete model choices stay local. Do not modify global/client skills, model defaults or installed config without explicit request.

The root coordinates; after delegating implementation it does not become a second writer. Each Worker owns its frozen candidate and verification.
The root assesses the actual candidate; required independent review uses a separate Reviewer. Remediation returns to the same Worker.
One remediation cycle is the default; a second needs explicit authorization, with the existing absolute cap of two.
Internal outcomes are `INTERNAL_ACCEPT`, `FIXES_REQUIRED`, `BLOCKED` or `BLOCKED_FOR_INTEGRATION`; none equals project ACCEPT or permission to merge.

Codex can use its configured local skills and GitHub tools; OpenCode, Grok, Gemini, Hermes and ChatGPT use the same five-book rules and configured client roots. Launch prompts should normally be 5–10 lines with exact issue/note, role, baseline/target, branch/isolation, result and authorized delivery. Select available capability for risk; local configuration owns concrete model/effort. Do not invent tool availability, force a client switch or resurrect model identity/grades/usage accounting. CBM is optional and never requires a used/skipped report or index maintenance; verify any index result against the assigned checkout. Installed optional skills do not override project authority or enable implicit queue execution.

<a id="d6-agent_orchestration-92"></a>
### Optional explicit orchestration and queues

<a id="d6-agent_orchestration-92-independent-queue"></a>
#### Independent queue

Advance only through explicitly listed eligible tasks, each with its own branch/workspace and exact baseline, after the prior task reaches INTERNAL_ACCEPT.
An earlier candidate is not an implicit baseline for the next task; do not invent extra backlog work.


<a id="d6-agent_orchestration-92-dependency--integration-block"></a>
#### Dependency / integration block

Without an authorized safe baseline/dependency strategy, a dependent task is BLOCKED_FOR_INTEGRATION.
Only that chain is blocked; unrelated listed tasks may continue. Do not invent stacked history or merge canonical/integration branches to bypass the block.


<a id="d6-agent_orchestration-92-review-triggers"></a>
#### Review triggers

Use D1 risk policy; requiring review does not activate a queue or expand scope.


<a id="d6-agent_orchestration-92-reporting"></a>
<a id="d6-agent_orchestration-92-per-task-report"></a>
#### Per-task report

Use the single completion contract in AGENTS.md. An explicit experiment may add measured experiment evidence, not compulsory unknown telemetry.


<a id="d6-agent_orchestration-92-final-queue-report"></a>
#### Final queue report

List every authorized task, internal status, candidate SHA, review path and unresolved Integrator action. This is not batch project acceptance.


<a id="d6-agent_orchestration-92-local-codex-skills"></a>
#### Local Codex skills

Local `$delivery-loop`/helper skills are optional mechanics, not competing policy. Keep implicit loop invocation disabled.
Local paths, concrete model choices and config stay machine-local. Changes here do not silently modify installed skills/config.


<a id="d6-agent_orchestration-92-invariants-that-automation-does-not-weaken"></a>
#### Invariants that automation does not weaken

The shared financial, privacy/runtime, workspace, authority and evidence boundaries apply unchanged to every execution mode.

