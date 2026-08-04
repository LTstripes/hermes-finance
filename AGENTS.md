# AGENTS.md — Hermes Finance

## Scope

These rules apply to the entire `hermes-finance` repository. More specific `AGENTS.md` files may tighten rules for a subdirectory but must not weaken privacy or financial-correctness requirements.

## Read before changing anything

Use this precedence when documents disagree:

1. `docs/MASTER_SPEC.md` — business rules, scope and architecture.
2. `docs/HERMES_TASKS.md` — task order, scope and acceptance criteria.
3. `docs/HERMES_START_PROMPT.md` — iteration protocol.
4. Accepted ADRs in `docs/adr/`.
5. `docs/PROJECT_WIKI.md` — accepted clarifications and project history.
6. `docs/IDEA.md` — original concept only.

Read `private/PRIVATE_SEED_NOT_FOR_GIT.md` only when the assigned task genuinely requires local owner data. Never quote, summarize or copy its personal values into tracked files, prompts, logs, tests or reports.

## Iteration contract

- Work on only the task ID explicitly named by the owner.
- Before changes, provide a plan of 3–7 short steps.
- Do not start the next backlog item automatically.
- Do not implement future features “while here”.
- If a requirement conflicts with the master specification, stop and ask one concrete question.
- Do not commit, push, open a PR or change repository settings unless the owner explicitly asks.
- Keep each change small enough for complete independent review.

## Architecture

- Backend: Python, FastAPI, Pydantic, SQLAlchemy 2, Alembic and SQLite for MVP.
- Frontend: React, TypeScript and Vite; use the libraries fixed by the master specification.
- Financial domain logic must not depend on FastAPI, SQLAlchemy or React.
- API calls domain services; frontend displays backend results and must not duplicate financial formulas.
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

The primary Sol session owns architecture, financial semantics, privacy-sensitive changes and final acceptance. Delegated work is bounded:

- **Terra:** medium-complexity implementation with a fixed contract and narrow file scope.
- **Luna:** scaffolding, repetitive CRUD/UI, documentation cleanup, boilerplate tests and mechanical edits.
- **DeepSeek V4 Flash Free:** read-only review, research, test-case drafts and isolated low-risk work via `custom:open.cherryin.ai` model `deepseek/deepseek-v4-flash(free)`.

Delegated summaries are not proof. The primary agent must inspect the actual files/diff and run relevant checks. Never let multiple agents modify the same schema or working tree concurrently. Use separate worktrees for independent write tasks.

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

Do not claim the full suite passed unless the canonical suite actually ran and passed.

## Required completion report

Report:

- task ID and status;
- work completed;
- changed files;
- exact checks and outcomes;
- limitations or questions;
- next backlog task, explicitly marked as not started.
