# AGENTS.md — Hermes Finance

## Scope

These rules apply to the entire `hermes-finance` repository. More specific `AGENTS.md` files may tighten rules for a subdirectory but must not weaken privacy or financial-correctness requirements.

## Read before changing anything

Use this precedence when documents disagree:

1. `docs/MASTER_SPEC.md` — business rules, scope and architecture.
2. Active `docs/releases/<version>.md` — current release task order, scope and acceptance criteria.
3. Accepted ADRs in `docs/adr/` — normative contracts and accepted architectural decisions.
4. `docs/MODEL_ROUTING.md` — launch gate, model risk class and delegation rules.
5. `docs/PROJECT_WIKI.md` — accepted clarifications and project history.
6. `docs/HERMES_TASKS.md` — historical MVP backlog/reference only; not a source of new post-MVP work.
7. `docs/HERMES_START_PROMPT.md` — historical/operational iteration reference where still applicable.
8. `docs/IDEA.md` — original concept only.

For remaining `0.3.0` Hermes work, also read `docs/releases/0.3.0-execution-cards.md`. It is the canonical detailed **execution extension** for the named task IDs. It may add implementation/verification/delivery detail but cannot override business semantics from `MASTER_SPEC` or an accepted ADR.

Read `private/PRIVATE_SEED_NOT_FOR_GIT.md` only when the assigned task genuinely requires local owner data. Never quote, summarize or copy its personal values into tracked files, prompts, logs, tests or reports.

## Iteration contract

- Work on only the task ID explicitly named by the owner.
- When the owner writes `начинаем <ID>`, `запускай <ID>` or an equivalent explicit start command, that message assigns the named task and approves its canonical route from the active `docs/releases/<version>.md` plus `docs/MODEL_ROUTING.md`; do not ask for a second model-selection confirmation unless the owner overrides the route or no canonical route exists.
- A named owner start command is intended to be **self-contained**. Do not ask the owner to copy a second long prompt when the active release/task execution card already defines scope, acceptance, verification and delivery. Resolve those requirements from repository docs yourself.
- For `0.3.0`, read the matching ID in both `docs/releases/0.3.0.md` and `docs/releases/0.3.0-execution-cards.md`; if owner-review follow-ups are referenced, read `docs/releases/0.3.0-owner-review-2026-08-12.md` as well.
- If a task is already in progress when docs-only execution guidance is updated, do not restart or discard correct work merely because the documentation commit is newer. Compare the in-progress work against the updated card and continue in the existing task branch/worktree unless a real contract conflict is found.
- Unless a task-card pins an exact baseline, start from current `origin/main` only after verifying all named dependencies are already integrated. If a required dependency exists only in another task branch, stop and report that dependency instead of silently cherry-picking it.
- Before changes, provide a plan of 3–7 short steps.
- Do not start the next backlog item automatically.
- Do not implement future features “while here”.
- If a requirement conflicts with the master specification, stop and ask one concrete question.
- After an explicitly assigned task passes its required local verification, Hermes may create a normal commit, push the current branch to `origin` and verify CI without separate confirmation.
- A task implementation worker owns publishing its accepted local commits to its **own task/candidate branch**. Do not ask the owner to act as a routine `git push` courier between the worker and reviewer. Never push `main`, `r04` or another integration branch from a task worker unless the task explicitly assigns integration authority.
- If a normal task-branch push fails, report the exact attempted command, exit status and stderr/output after safe diagnostic/retry steps. Do not reduce this to “push failed”, and do not ask the owner to push manually until the concrete credential/network/runtime barrier is identified.
- Separate owner permission is still required for force-push, reset, rebase, amending published commits, merge, branch or tag deletion, opening a PR, creating a release, or changing repository settings.
- Keep each change small enough for complete independent review.

## Architecture

- Backend: Python, FastAPI, Pydantic, SQLAlchemy 2, Alembic and SQLite for MVP.
- Frontend: React, TypeScript and Vite; use the libraries fixed by the master specification.
- Financial domain logic must not depend on FastAPI, SQLAlchemy or React.
- API calls domain services; frontend displays backend results and must not duplicate financial formulas.
- Phase C calculations use pure framework-independent inputs/results. SQLAlchemy application services load and map persisted rows, call pure calculators, and return domain result DTOs; Pydantic mapping remains at the API boundary. Do not introduce repository/DI abstractions without a concrete need.
- Composite commands own their transaction. Existing CRUD services may remain as accepted B-layer code, but before transactional month cloning or bulk import, nested mutations must support `flush` without committing so the top-level operation can commit or roll back once.
- Excel is a one-time migration source and reference, never the live database.
- MVP is local, single-user and no-auth; backend binds to `127.0.0.1` by default.
- VPS, PostgreSQL and authentication are later decisions, not premature MVP infrastructure.

See `docs/adr/0001-architecture.md` for rationale.

## Financial invariants

- Never use binary `float` for money or rates.
- Store money as integer minor units in the database; use `Decimal` in domain calculations.
- API money is an object containing ISO currency plus decimal-string major units.
- Store rates as integer basis points; API rates are decimal strings in percentage points.
- Cashback is not passive income.
- Real estate is not liquid capital.
- Bond principal repayment is not income.
- Portfolio value change is not investment return when external cash flows exist.
- Planned IIS deductions are not actual results.
- Frontend-supplied calculated values are untrusted and must be recomputed by backend.
- Deposit actual interest comes only from `deposit_snapshots.actual_interest_received`; do not duplicate it in `investment_cash_flows`.
- Closed reporting months are immutable until explicit `reopen`.
- Cloning a month copies monthly states and snapshots, not global account or instrument dictionaries.

The complete accepted contract is in `docs/PROJECT_WIKI.md` section 7.

## Privacy and fixtures

Never commit:

- real account numbers, instrument positions or financial amounts;
- SQLite databases or sidecar files;
- `.env` files or credentials;
- private seed files;
- personal PDF/XLS/XLSX documents;
- exports, backups or locally generated reports.

Use only synthetic names and values in examples and tests. Verify ignore behavior with `git check-ignore` plus `git status --porcelain`; seeing a pattern in `.gitignore` is not enough.

## Model routing

Read `docs/MODEL_ROUTING.md` before choosing a model, delegating, or beginning a backlog task. It is the authoritative launch gate and records the owner-approved economy route.

- Before every task, resolve `primary / worker / reviewer` with the actual reasoning level. A named start command from the owner approves the canonical route already recorded in the active release task-card; ask only when the owner overrides it, the route is missing, or an escalation condition is reached.
- Default standard implementation to Luna High; use Terra High for complex financial semantics and Sol High only for new/conflicting architecture or explicit checkpoints.
- DeepSeek V4 Flash Free may perform bounded standard implementation in an isolated worktree/session as well as read-only review; it never receives private data, commits, pushes or grants final acceptance.
- After `B19`, run one Sol High blocker-level architecture review; do not rewrite accepted code merely because Sol would design it differently.
- `delegate_task` has no per-call model selector. Never claim a child ran on a named model or level unless runtime metadata confirms it.
- For an exact per-task route, launch a bounded Hermes session with per-run `--provider`, `--model` and `--reasoning` flags; use `--worktree` for a writing worker. Do not change shared Hermes defaults or `config.yaml` merely to route one task.
- If exact routing cannot be confirmed because the provider/model is unavailable or authentication fails, stop before implementation and report the launch blocker.
- Worker summaries are not proof. The accepting primary inspects actual files/diff and reruns relevant checks. Never let multiple agents modify the same migration, schema or working tree concurrently.

Load the user-local `hermes-finance-orchestration` skill when coordinating delegated work.

## Verification

For every task:

1. map each acceptance criterion to a check;
2. run the smallest relevant canonical test first;
3. run broader lint/typecheck/build only when proportional to the change;
4. when no project test exists, use a temporary deterministic ad-hoc probe and label it honestly;
5. verify temporary fixtures and probes were removed;
6. inspect `git status --short` and account for every changed file;
7. confirm no private data or unrelated scope entered the change.

Do not call a task “done” or send its completion report immediately after the first green command. Complete all allowed delivery side effects, CI/probes and guard retries, then perform one final read-back of `HEAD`, remote ref, clean status and temporary-file cleanup. Pause for one settling checkpoint after the last tool result; only then send one message explicitly labelled **Canonical completion report**. Progress updates before that point must not say “done”, and no duplicate completion summary follows unless the owner asks.

Do not claim the full suite passed unless the canonical suite actually ran and passed.

## Required completion report

Report:

- task ID and status;
- work completed;
- changed files;
- exact checks and outcomes;
- limitations or questions;
- next backlog task, explicitly marked as not started.

## Execution history and attribution

`docs/EXECUTION_HISTORY.md` is the durable human-readable attribution journal for the project.

- After a task is **accepted and integrated**, the accepting reviewer/integrator owns appending its execution record; the implementation worker does not self-accept or write the final historical verdict.
- Record the factual implementation agent/tool and exact model only when runtime-confirmed, reviewer/acceptor, baseline, candidate branch + accepted HEAD, target branch + integrated HEAD, meaningful verification, material blockers/iterations and important decision notes.
- For A/B or multi-agent implementations, preserve **all candidates**, their exact branches/HEADs, strengths/weaknesses and checks; then record the selected candidate and evidence-based selection reason.
- Rejected candidates remain part of project history. Do not erase them merely because another implementation was integrated.
- Worker reports are supporting context, not evidence. Attribution records must agree with actual Git refs/diff/CI read-back.
- Never put private financial data, credentials, DB/seed/export contents or owner screenshots containing personal values into the execution history.
- Keep deep technical rationale in ADRs/task-cards and product-facing release notes in `CHANGELOG.md`; execution history should capture **who/how/why selected**, not duplicate specifications.
- Do not fabricate historical executor/model details when backfilling older work; mark unknowns explicitly.
