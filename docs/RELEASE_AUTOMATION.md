# Guarded release automation

HYG-04 adds a repository-owned GitHub Actions path for publishing an already prepared Hermes Finance release without requiring a local development/Codex session only to run `scripts/release.ps1`.

The release remains explicit and owner-controlled. There is no release-on-merge, release-on-tag, scheduled release, or background publication.

## Control endpoint

Permanent control issue: **#124 — Release Control — guarded owner trigger**.

Keep that issue open and unlocked. A release is requested only by a newly created owner-authored comment on #124 with exactly three lines:

```text
/release
version=X.Y.Z
expected_main_sha=<full 40-character main SHA>
```

The version has no `v` prefix. The SHA must be the complete 40-character commit ID.

Edited comments, extra fields, short SHAs, other issues, another actor, or another comment author are rejected. A normal comment that does not begin with `/release` does not enter the release job.

The issue-comment trigger is intentional: the ChatGPT GitHub integration can create an auditable issue comment directly, while it does not require the owner to open GitHub Actions and press a manual workflow-dispatch button.

## Chat-first integrator flow

For the normal chat-driven path the owner can ask the integrator to release a prepared version. The integrator should:

1. read current GitHub `main` and capture its exact 40-character SHA;
2. confirm canonical `ci.yml` has a completed successful `push` run for that exact `main` SHA;
3. verify repository release identity and `docs/release-notes-X.Y.Z.md` are present;
4. create the exact `/release` request comment on control issue #124;
5. read the Guarded Release run and its job summary;
6. independently read back the tag object, peeled commit and published GitHub Release before reporting success.

The workflow repeats the critical checks itself. Pre-checking in chat is convenience and defense in depth, not authorization to skip workflow guards.

## Guard chain

`.github/workflows/release.yml` invokes `scripts/release-automation.ps1`, which performs the narrow trigger/identity preflight and then delegates publication to the existing `Invoke-HermesRelease` implementation in `scripts/release-lib.ps1`.

The combined path requires all of the following before publication:

- repository is exactly `LTstripes/hermes-finance`;
- event is a newly created issue comment;
- issue is exactly #124;
- GitHub actor and comment author are both the repository owner;
- request body follows the exact three-line grammar;
- requested version is a stable `X.Y.Z` identity;
- expected main is a full commit SHA;
- `backend/pyproject.toml` `[project].version` equals the requested version;
- `backend/src/hermes_finance/__init__.py` `__version__` equals the requested version;
- canonical `docs/release-notes-X.Y.Z.md` exists and is non-empty;
- fetched `origin/main` still equals the expected SHA;
- canonical `ci.yml` has a completed successful exact-main `push` run for that SHA;
- existing local/remote tag state is compatible with the same annotated tag at the same commit;
- existing GitHub Release state is compatible with a published stable release.

Unexpected tag/release state fails closed. The helper never force-updates or deletes a release tag to make a request succeed.

## Publication boundary

The publication path is deliberately narrow:

- create an annotated `vX.Y.Z` tag at the guarded exact main SHA when it does not already exist;
- push only `refs/tags/vX.Y.Z:refs/tags/vX.Y.Z` with no follow-tags behavior;
- create a published, non-prerelease GitHub Release from that existing tag and canonical release notes;
- never push, reset, update, delete or force-update a branch ref;
- never use `--tags`, `--all`, `--mirror`, force push or tag deletion.

If tag publication succeeds but GitHub Release creation fails, the tag is intentionally retained. Repeating the exact same guarded request may safely reuse the same compatible annotated tag; it is not moved or recreated.

## Permissions and credentials

The workflow uses only the repository-provided `GITHUB_TOKEN`; there is no PAT or custom release token.

Workflow-level default permission:

- `contents: read`.

The single release job narrows its elevated permissions to:

- `actions: read` — read canonical exact-main Actions runs;
- `contents: write` — push the one release tag and create/read the GitHub Release.

No `issues: write`, `pull-requests: write`, `packages: write`, deployment permission, id-token, or repository-administration permission is granted to the release job.

## Privacy and runtime isolation

The workflow checks out only the public repository on a GitHub-hosted Windows runner. It has no path or connector to the production runtime and must not read or receive:

- a real `.env`;
- the real finance database or SQLite sidecars;
- backups;
- `private/` owner data;
- provider credentials or owner exports.

No production smoke or live provider operation is part of release publication.

## Verification and job summary

After the shared release helper returns, the automation performs a final remote read-back and fails if any invariant changed. The job summary exposes:

- requested version and tag;
- annotated tag object SHA;
- peeled commit SHA;
- final `main` SHA;
- GitHub Release title;
- published state;
- GitHub Release URL;
- control issue and request actor.

A valid successful result requires the peeled tag commit and final `main` to equal the original expected SHA, and the tag object SHA to differ from the peeled commit SHA (annotated tag evidence).

An integrator can independently verify the same state through GitHub by reading `main`, `refs/tags/vX.Y.Z`, the peeled tag target, the canonical exact-main CI run and the GitHub Release. The job summary is evidence, not a substitute for independent read-back when release correctness matters.

## Synthetic safety verification

Canonical PR/main CI includes a Windows `Release safety` job. It runs:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\tests\test-release.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\tests\test-release-request.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\tests\test-release-workflow.ps1
```

`test-release.ps1` exercises the publication contract through an injected fake command runner, including successful publication semantics and fail-closed cases such as missing/failed/wrong-kind CI and conflicting tags/releases. It does not create a real tag or GitHub Release.

`test-release-request.ps1` exercises the owner-control request grammar, provenance checks, version identity and release-note requirements using temporary synthetic files only.

`test-release-workflow.ps1` parses the real automation entrypoint with the Windows PowerShell parser and verifies the tracked workflow contract: narrow trigger, control issue binding, owner gates, built-in token use and minimal permissions. It performs no network or publication calls.

No HYG-04 acceptance test publishes a throwaway real Hermes Finance tag or release.

## Manual fallback

`scripts/release.ps1` remains the supported manual fallback. It uses the same guarded `scripts/release-lib.ps1` publication implementation:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release.ps1 `
  -Version X.Y.Z `
  -ExpectedMainSha <full-40-character-main-sha> `
  -ReleaseNotes .\docs\release-notes-X.Y.Z.md
```

The automated path does not weaken or replace those release guards; it adds a repository-owned, chat-triggerable entrypoint around them.
