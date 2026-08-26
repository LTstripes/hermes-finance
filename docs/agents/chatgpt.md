# ChatGPT adapter

This file is the ChatGPT client adapter for Hermes Finance. It does not replace [`AGENTS.md`](../../AGENTS.md); the universal project constitution remains authoritative.

## Default route: chat-first, GitHub-native

When the connected ChatGPT session has direct GitHub repository access and can inspect GitHub Actions, use that capability as the default repository execution surface.

The owner should normally be able to say what to do in chat and receive the completed repository result without being asked to:

- open GitHub to create/edit branches, files, PRs, issues or comments;
- copy commands into PowerShell;
- relay a prompt to Codex or another coding agent merely so it can perform GitHub plumbing;
- press an Actions button when an equivalent guarded repository-owned trigger is available to ChatGPT.

A normal repository write task should follow:

1. read canonical `main` and capture the exact baseline SHA;
2. read `AGENTS.md` and the task-relevant source-of-truth docs;
3. create an isolated task branch from the exact baseline;
4. make only the scoped repository changes on that branch;
5. open a PR and inspect the actual changed files/diff;
6. inspect applicable CI/checks and do not infer green state from partial runs;
7. merge only when authorized and all required acceptance conditions are satisfied;
8. read back canonical `main` after merge;
9. verify canonical `push` CI on that exact merged SHA before calling the integration complete.

GitHub Actions is the normal remote verification surface for repository changes that do not intrinsically require owner-local runtime access.

## When not to hand off

Do not hand off to Codex, Work, another agent or the owner merely because the task changes code. The relevant question is whether the current ChatGPT/GitHub surface has the capabilities needed to perform and verify the task safely.

Keep the work in ChatGPT when direct GitHub operations plus repository CI are sufficient.

A hand-off is justified when a materially required capability is missing, such as:

- local command execution that cannot be represented by repository CI;
- required browser/computer-use inspection;
- owner-local live provider or runtime work;
- binary/artifact manipulation unavailable through the repository connector;
- complex local repository operations not exposed by the connector;
- an explicitly requested independent implementation or independent review.

If the owner has explicitly rejected a hand-off surface, do not keep proposing it as the default. Use the direct route as far as safety and available capability allow, and report a genuine residual limitation only when it actually blocks completion.

## Owner is not a courier

Do not ask the owner to perform routine repository mechanics that ChatGPT can perform directly. This includes creating the task branch, editing tracked text files, opening or merging a PR, updating issues, reading Actions, and triggering the guarded release flow through the control issue when those operations are available.

If an optional cleanup operation is not available through the connector, leave a truthful residual note instead of pushing low-value busywork onto the owner.

## Runtime/privacy boundary

Direct GitHub work is not permission to access production runtime data.

Never use or request the production `.env`, finance database, SQLite sidecars, backups, `private/`, owner exports, provider credentials or other private runtime payloads for ordinary repository work. GitHub Actions must use synthetic/test data only unless a separate owner-controlled contract explicitly says otherwise.

## Releases

HYG-04 established the normal chat-triggerable release route. Follow [`docs/RELEASE_AUTOMATION.md`](../RELEASE_AUTOMATION.md) and permanent control issue **#124**.

For a prepared release, ChatGPT should itself:

1. read exact current `main`;
2. verify successful canonical exact-main `push` CI;
3. verify repository version identity and canonical release notes;
4. post the exact guarded `/release` request to #124;
5. inspect the Guarded Release run;
6. independently read back the annotated tag, peeled commit and published GitHub Release before reporting success.

Do not ask the owner to open GitHub or Codex merely to relay this release trigger.

## Evidence

Prefer connector read-back and GitHub Actions evidence over conversational assumptions. Be explicit about what actually ran, which SHA it ran against, and what was not executable through the current surface.
