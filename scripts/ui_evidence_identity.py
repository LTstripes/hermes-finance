#!/usr/bin/env python3
"""Exact-head UI evidence identity for #669.

Normal pull-request CI checks out the merge ref. The UI evidence workflow
checks out the pull request head and is the producer of the synthetic
screenshot package, the production dist, and the provenance for that head.

Those visual executions are the same only when all of the following hold:

- the event is an ordinary pull_request, not a push or pull_request_target;
- the PR's own file list would run both the CI visual audit and the evidence
  workflow;
- the merge checkout tree, the fetched merge ref tree, and the head tree are
  the same git tree.

A head SHA written into metadata does not prove that equality. Dev-server
screenshots are not browser verification of the production dist. The dist
proves only that the checked-out tree built.

The evidence workflow keeps its exact-head visual command. CI omits only the
matching 1440x900 grep when the conditions above are true.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from visual_audit_paths import is_visual_audit_path

EVIDENCE_GREP = "(dashboard:|monthly-close:|ui-v2)"
EVIDENCE_VISUAL_COMMAND = (
    "npm run audit:visual -- --project=1440x900 "
    f'--grep "{EVIDENCE_GREP}"'
)
OMIT_ENV = "HERMES_VISUAL_AUDIT_OMIT_DUPLICATE_EVIDENCE"
SCREENSHOT_RUNTIME = "vite-dev-server"
SCREENSHOT_MEANING = "dev-server-browser-capture-not-production-build"
BUILD_MEANING = "production-dist-of-checked-out-tree-only"
DATA_MEANING = "synthetic API fixtures only"
RUNTIME_MEANING = "no backend or provider"
WORKFLOW_NAME = "ui-v2-evidence.yml"
REQUIRED_SCREENSHOTS = ("dashboard.png", "monthly-close.png")
PROVENANCE_KEYS = (
    "candidate_sha",
    "base_sha",
    "checked_out_sha",
    "checked_out_tree",
    "head_tree",
    "merge_tree",
    "head_tree_equals_merge_tree",
    "event_sha",
    "run_id",
    "run_attempt",
    "workflow",
    "visual_command",
    "screenshot_runtime",
    "screenshot_meaning",
    "build_meaning",
    "data",
    "runtime",
)
_SHA = re.compile(r"[0-9a-f]{40}")
_ZERO_SHA = "0" * 40
_PRIVATE_NAMES = {".env", ".env.local", ".env.production", "private"}
_PRIVATE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def normalize_path(path: str) -> str:
    parts: list[str] = []
    for part in path.strip().replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def valid_sha(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    if _SHA.fullmatch(lowered) is None or lowered == _ZERO_SHA:
        return None
    return lowered


def evidence_patterns_from_workflow(workflow_text: str) -> tuple[str, ...]:
    match = re.search(
        r'(?m)^on:\n  pull_request:\n    paths:\n((?:      - "[^"]+"\n)+)',
        workflow_text,
    )
    if match is None:
        raise ValueError("UI evidence workflow is missing its pull_request path filter")
    patterns = tuple(re.findall(r'"([^"]+)"', match.group(1)))
    if not patterns:
        raise ValueError("UI evidence path filter is empty")
    return patterns


def path_matches_pattern(path: str, pattern: str) -> bool:
    normalized = normalize_path(path)
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return normalized == prefix or normalized.startswith(prefix + "/")
    return normalized == pattern


def evidence_workflow_applies(paths: list[str], patterns: tuple[str, ...]) -> bool:
    return any(
        path_matches_pattern(path, pattern) for path in paths for pattern in patterns
    )


def duplicate_visual_paths(paths: list[str], patterns: tuple[str, ...]) -> bool:
    """True when this PR would execute the overlap in both workflows."""
    return any(is_visual_audit_path(path) for path in paths) and evidence_workflow_applies(
        paths, patterns
    )


def omit_duplicate_1440(
    *,
    event_name: str,
    duplicate_paths: bool,
    head_sha: object,
    resolved_head_sha: object,
    base_sha: object,
    checkout_sha: object,
    head_tree: object,
    merge_tree: object,
    checkout_tree: object,
) -> bool:
    """Return true only for one proven duplicate of the exact-head 1440 grep.

    The checked-out commit SHA may be the merge commit. Tree equality is the
    proof. A matching head SHA alone is not.
    """
    if event_name != "pull_request" or not duplicate_paths:
        return False
    head = valid_sha(head_sha)
    resolved_head = valid_sha(resolved_head_sha)
    base = valid_sha(base_sha)
    checkout = valid_sha(checkout_sha)
    head_tree_sha = valid_sha(head_tree)
    merge_tree_sha = valid_sha(merge_tree)
    checkout_tree_sha = valid_sha(checkout_tree)
    if None in (
        head,
        resolved_head,
        base,
        checkout,
        head_tree_sha,
        merge_tree_sha,
        checkout_tree_sha,
    ):
        return False
    if head != resolved_head:
        return False
    return head_tree_sha == merge_tree_sha == checkout_tree_sha


def valid_run_id(value: object) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return str(value)
    if (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and not value.startswith("0")
    ):
        return value
    return None


def git_output(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git failed"
        raise ValueError(detail)
    return completed.stdout.strip()


def build_provenance(
    *,
    candidate_sha: str,
    base_sha: str,
    checked_out_sha: str,
    checked_out_tree: str,
    event_sha: str,
    merge_tree: str | None,
    run_id: str,
    run_attempt: str,
) -> dict[str, object]:
    equals = merge_tree is not None and merge_tree == checked_out_tree
    return {
        "candidate_sha": candidate_sha,
        "base_sha": base_sha,
        "checked_out_sha": checked_out_sha,
        "checked_out_tree": checked_out_tree,
        "head_tree": checked_out_tree,
        "merge_tree": merge_tree,
        "head_tree_equals_merge_tree": equals,
        "event_sha": event_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "workflow": WORKFLOW_NAME,
        "visual_command": EVIDENCE_VISUAL_COMMAND,
        "screenshot_runtime": SCREENSHOT_RUNTIME,
        "screenshot_meaning": SCREENSHOT_MEANING,
        "build_meaning": BUILD_MEANING,
        "data": DATA_MEANING,
        "runtime": RUNTIME_MEANING,
    }


def provenance_errors(document: object, expected: dict[str, object]) -> list[str]:
    if not isinstance(document, dict):
        return ["provenance must be a JSON object"]
    errors: list[str] = []
    unknown = sorted(set(document) - set(PROVENANCE_KEYS))
    if unknown:
        errors.append("unexpected provenance keys: " + ", ".join(unknown))
    for key in PROVENANCE_KEYS:
        if key not in document:
            errors.append(f"missing {key}")
    if errors:
        return errors
    for key, value in expected.items():
        if document.get(key) != value:
            errors.append(f"wrong {key}")
    if document.get("screenshot_runtime") != SCREENSHOT_RUNTIME:
        errors.append("screenshot runtime must stay the vite dev server")
    if document.get("screenshot_meaning") != SCREENSHOT_MEANING:
        errors.append("screenshots must not be described as production-build verification")
    if document.get("build_meaning") != BUILD_MEANING:
        errors.append("dist must stay a build proof only")
    if document.get("head_tree") != document.get("checked_out_tree"):
        errors.append("head tree does not match the checked-out tree")
    merge_tree = document.get("merge_tree")
    equals = document.get("head_tree_equals_merge_tree")
    if equals is not (merge_tree is not None and merge_tree == document.get("checked_out_tree")):
        errors.append("tree equality flag does not match the recorded trees")
    return errors


def _private_file(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    if any(part in _PRIVATE_NAMES or part.startswith(".env") for part in relative_parts):
        return True
    return path.suffix.lower() in _PRIVATE_SUFFIXES


def package_errors(package: Path, expected: dict[str, object]) -> list[str]:
    errors: list[str] = []
    allowed = {"screenshots", "frontend-dist", "provenance.json"}
    if not package.is_dir():
        return ["missing evidence package"]
    extra = sorted(item.name for item in package.iterdir() if item.name not in allowed)
    if extra:
        errors.append("unexpected evidence files: " + ", ".join(extra))
    screenshots = package / "screenshots"
    pngs = sorted(screenshots.glob("*.png")) if screenshots.is_dir() else []
    if not screenshots.is_dir():
        errors.append("missing screenshots")
    else:
        stray = sorted(
            item.name for item in screenshots.iterdir() if item.is_file() and item.suffix.lower() != ".png"
        )
        if stray:
            errors.append("unexpected screenshot files: " + ", ".join(stray))
        for name in REQUIRED_SCREENSHOTS:
            if not (screenshots / name).is_file():
                errors.append(f"missing screenshot {name}")
        extras = [path.name for path in pngs if path.name not in REQUIRED_SCREENSHOTS]
        if not extras:
            errors.append("missing ui-v2 screenshots")
    dist_index = package / "frontend-dist" / "index.html"
    if not dist_index.is_file():
        errors.append("missing production build index")
    provenance_path = package / "provenance.json"
    if not provenance_path.is_file():
        errors.append("missing provenance")
    else:
        try:
            document = json.loads(provenance_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            errors.append("provenance is not JSON")
        else:
            errors.extend(provenance_errors(document, expected))
    for path in package.rglob("*"):
        if path.is_file() and _private_file(path, package):
            errors.append(f"private evidence path {path.relative_to(package).as_posix()}")
    return errors


def publication_allowed(*, capture_succeeded: bool, errors: list[str]) -> bool:
    return capture_succeeded and not errors


def publish_package(
    package: Path,
    repo: Path,
    *,
    candidate_sha: object,
    base_sha: object,
    event_sha: object,
    merge_tree: object,
    run_id: object,
    run_attempt: object,
) -> list[str]:
    """Write provenance only after the checked-out head and the package agree."""
    if not package.is_dir():
        return ["missing evidence package"]
    errors: list[str] = []
    try:
        checked_out_sha = valid_sha(git_output(repo, "rev-parse", "--verify", "HEAD"))
        checked_out_tree = valid_sha(git_output(repo, "rev-parse", "--verify", "HEAD:"))
    except (ValueError, OSError) as exc:
        return [f"checked-out identity is unavailable: {exc}"]
    candidate = valid_sha(candidate_sha)
    base = valid_sha(base_sha)
    event = valid_sha(event_sha)
    attempt = valid_run_id(run_attempt)
    run = valid_run_id(run_id)
    if candidate is None:
        errors.append("missing or wrong candidate_sha")
    elif checked_out_sha is None or candidate != checked_out_sha:
        errors.append("candidate_sha is not the checked-out head")
    if base is None:
        errors.append("missing or wrong base_sha")
    if event is None:
        errors.append("missing or wrong event_sha")
    if checked_out_tree is None:
        errors.append("missing or wrong checked_out_tree")
    if run is None:
        errors.append("missing or wrong run_id")
    if attempt is None:
        errors.append("missing or wrong run_attempt")
    merge: str | None
    if merge_tree is None or (isinstance(merge_tree, str) and merge_tree.strip() == ""):
        merge = None
    else:
        merge = valid_sha(merge_tree)
        if merge is None:
            errors.append("missing or wrong merge_tree")
    if errors or candidate is None or base is None or event is None or checked_out_tree is None:
        return errors
    if run is None or attempt is None or checked_out_sha is None:
        return errors
    expected = build_provenance(
        candidate_sha=candidate,
        base_sha=base,
        checked_out_sha=checked_out_sha,
        checked_out_tree=checked_out_tree,
        event_sha=event,
        merge_tree=merge,
        run_id=run,
        run_attempt=attempt,
    )
    provenance_path = package / "provenance.json"
    existing = provenance_path.read_text(encoding="utf-8") if provenance_path.is_file() else None
    provenance_path.write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    errors = package_errors(package, expected)
    if errors:
        if existing is None:
            provenance_path.unlink(missing_ok=True)
        else:
            provenance_path.write_text(existing, encoding="utf-8")
    return errors


def _read_paths(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _print_flag(value: bool) -> int:
    print("true" if value else "false")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    paths_command = commands.add_parser("paths")
    paths_command.add_argument("--from-file", type=Path, required=True)
    paths_command.add_argument("--workflow", type=Path, required=True)

    trees_command = commands.add_parser("trees")
    trees_command.add_argument("--event-name", required=True)
    trees_command.add_argument("--duplicate-paths", required=True)
    trees_command.add_argument("--head-sha", default="")
    trees_command.add_argument("--resolved-head-sha", default="")
    trees_command.add_argument("--base-sha", default="")
    trees_command.add_argument("--checkout-sha", default="")
    trees_command.add_argument("--head-tree", default="")
    trees_command.add_argument("--merge-tree", default="")
    trees_command.add_argument("--checkout-tree", default="")

    publish_command = commands.add_parser("publish")
    publish_command.add_argument("--package", type=Path, required=True)
    publish_command.add_argument("--repo", type=Path, required=True)
    publish_command.add_argument("--candidate-sha", required=True)
    publish_command.add_argument("--base-sha", required=True)
    publish_command.add_argument("--event-sha", required=True)
    publish_command.add_argument("--merge-tree", default="")
    publish_command.add_argument("--run-id", required=True)
    publish_command.add_argument("--run-attempt", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "paths":
            patterns = evidence_patterns_from_workflow(
                args.workflow.read_text(encoding="utf-8")
            )
            return _print_flag(
                duplicate_visual_paths(_read_paths(args.from_file), patterns)
            )
        if args.command == "trees":
            return _print_flag(
                omit_duplicate_1440(
                    event_name=args.event_name,
                    duplicate_paths=args.duplicate_paths == "true",
                    head_sha=args.head_sha,
                    resolved_head_sha=args.resolved_head_sha,
                    base_sha=args.base_sha,
                    checkout_sha=args.checkout_sha,
                    head_tree=args.head_tree,
                    merge_tree=args.merge_tree,
                    checkout_tree=args.checkout_tree,
                )
            )
    except (OSError, ValueError) as exc:
        print(f"fail-closed: {exc}", file=sys.stderr)
        return _print_flag(False)

    errors = publish_package(
        args.package,
        args.repo,
        candidate_sha=args.candidate_sha,
        base_sha=args.base_sha,
        event_sha=args.event_sha,
        merge_tree=args.merge_tree,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
    )
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
