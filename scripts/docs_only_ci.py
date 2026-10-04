#!/usr/bin/env python3
"""Fail-closed docs-only classification for ordinary pull requests.

A docs-only result means the current base/head diff is only explicit
non-executable prose, and the retained privacy/diff checks succeeded.
It does not mean backend, frontend, browser or Windows suites passed.

Canonical main pushes and release gates do not use this shortcut.
The separate UI evidence workflow is unchanged: its path filter is
frontend files and that workflow file, so a docs-only pull request
does not run it and this gate does not fabricate UI evidence.

The decision is recomputed from the commits named by the caller.
Nothing in this module stores a previous mode.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_MODE = re.compile(r"^[0-7]{6}$")
_OBJECT = re.compile(r"^[0-9a-fA-F]{4,64}$")
_STATUS = re.compile(r"^[A-Z][0-9]{0,3}$")
_PROSE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*\.md$")
_RELEASE_NOTES = re.compile(r"^docs/release-notes-.+\.md$")

# Ordinary prose at a known path. This is not "any markdown" and not docs/**.
# backend/README.md stays full: Hatchling reads it as the package readme.
EXACT_DOCS = frozenset(
    {
        "AGENTS.md",
        "CHANGELOG.md",
        "README.md",
        "docs/336-financial-context-contract.md",
        "docs/AGENT_ORCHESTRATION.md",
        "docs/AI_ANALYSIS_BUNDLE.md",
        "docs/AI_FINANCIAL_REVIEW.md",
        "docs/CI_TEST_OPTIMIZATION_CLOSEOUT_2026-09-16.md",
        "docs/CI_TEST_OPTIMIZATION_PLAYBOOK.md",
        "docs/CONSOLIDATION_2026-09-06.md",
        "docs/CURRENT_STATUS.md",
        "docs/DATA_INTEGRITY_HARDENING_CLOSEOUT_2026-09-27.md",
        "docs/DECISION_SUPPORT_V1_CLOSEOUT_2026-09-09.md",
        "docs/DETERMINISTIC_INSIGHTS.md",
        "docs/EXECUTION_HISTORY.md",
        "docs/FRESHNESS_PROVENANCE.md",
        "docs/IDEA.md",
        "docs/MASTER_SPEC.md",
        "docs/MODEL_ROUTING.md",
        "docs/OWNER_DURABILITY_CLOSEOUT_2026-09-25.md",
        "docs/OWNER_MACHINE_LAYOUT.md",
        "docs/OWNER_RUNTIME_OPERATIONS.md",
        "docs/OWNER_WORKSPACE_CLEANUP.md",
        "docs/PERFORMANCE_H1_ASTRA_BLOCKERS_2026-09-06.md",
        "docs/PERFORMANCE_V1_CLOSEOUT_2026-09-12.md",
        "docs/PERFORMANCE_V1_RECONCILIATION_2026-09-06.md",
        "docs/PORTFOLIO_REVIEW_PACKAGE.md",
        "docs/POST_RELEASE_UAT_CLOSEOUT_2026-10-03.md",
        "docs/PROJECT_WIKI.md",
        "docs/R09_RUNTIME_RELEASE_CLOSEOUT_2026-09-17.md",
        "docs/R10_RELEASE_CLOSEOUT_2026-09-21.md",
        "docs/README.md",
        "docs/RELEASE_AUTOMATION.md",
        "docs/TEST_SUITE_GUIDE.md",
        "docs/UI_V2_AGGREGATE_VERIFICATION.md",
        "docs/UI_V2_ANALYTICS_RECONCILIATION.md",
        "docs/UI_V2_COMPLETION_CLOSEOUT_2026-09-20.md",
        "docs/UI_V2_DEFAULT_SWITCH_CLOSEOUT_2026-09-21.md",
        "docs/UI_V2_OWNER_UAT.md",
        "docs/UI_V2_PARITY_CHECKPOINT_2026-09-28.md",
        "docs/VERIFICATION_POLICY.md",
        "docs/WORKSPACE_JANITOR.md",
        "docs/financial-completeness-contract.md",
        "docs/r07-06a-risk-allocation-contract.md",
        "docs/r07-09-scenario-lab-contract.md",
        "docs/r08-01b-valuation-coverage.md",
        "docs/r08-01c-performance-availability.md",
        "docs/r08-02-portfolio-xirr.md",
        "docs/r08-03-twrr-contract-recon.md",
        "docs/r08-03a-valuation-boundaries.md",
        "docs/reconciliation-normalized-contract.md",
        "docs/t-invest-market-data.md",
        "frontend/README.md",
        "sketches/README.md",
        "sketches/e01-airy-editorial/README.md",
        "sketches/e01-balanced-fintech/README.md",
        "sketches/e01-dense-tool/README.md",
    }
)

# A new file is docs-only only inside one of these prose directories.
PROSE_PREFIXES = (
    "docs/adr/",
    "docs/agents/",
    "docs/benchmarks/",
    "docs/design/",
    "docs/experiments/",
    "docs/history/",
    "docs/performance/",
    "docs/releases/",
    "docs/reviews/",
)

REGULAR_FILE = "100644"
ABSENT_MODE = "000000"

# Product jobs that must not run for a proven docs-only pull request.
# The visual audit keeps its existing path gate.
OMITTED_JOBS = (
    "backend-quality",
    "backend-tests",
    "backend-timezone-windows",
    "frontend",
    "g04-browser",
    "visual-audit",
    "release-safety",
    "windows-production-smoke",
)

# Cheap checks that must actually succeed. A skip is not success.
RETAINED_JOBS = (
    "privacy",
    "visual-audit-paths",
)

SUCCESS_TEXT = (
    "This candidate was classified as safe docs-only and the retained "
    "documentation/privacy/diff checks succeeded."
)


@dataclass(frozen=True)
class DiffRecord:
    old_mode: str
    new_mode: str
    status: str
    old_path: str | None
    new_path: str
    binary: bool = False


def ordinary_doc_path(path: str) -> bool:
    """Return true only for an explicit prose path, never from the suffix alone."""
    if not _plain_relative_path(path) or _RELEASE_NOTES.fullmatch(path):
        return False
    if path in EXACT_DOCS:
        return True
    for prefix in PROSE_PREFIXES:
        if not path.startswith(prefix):
            continue
        name = path[len(prefix) :]
        if "/" in name or _PROSE_FILE.fullmatch(name) is None:
            return False
        if name.startswith("release-notes-"):
            return False
        return True
    return False


def classify_records(records: list[DiffRecord] | None) -> str:
    """Return docs-only only when every record is a safe prose add or edit."""
    if not records:
        return "full"
    for record in records:
        if not _ordinary_doc_record(record):
            return "full"
    return "docs-only"


def product_suites_required(
    *,
    event_name: str,
    classify_result: str,
    mode: str,
    cancelled: bool,
) -> bool:
    """Mirror the product-job condition. Pushes and uncertainty stay full."""
    if cancelled:
        return False
    if event_name != "pull_request":
        return True
    if classify_result != "success":
        return True
    return mode != "docs-only"


def documentation_fast_path_ok(
    *,
    classification: str,
    retained_results: dict[str, str],
    omitted_results: dict[str, str],
    whitespace_ok: bool,
) -> bool:
    """Docs-only success is the retained checks, not a skipped product suite."""
    if classification != "docs-only" or not whitespace_ok:
        return False
    if any(retained_results.get(name) != "success" for name in RETAINED_JOBS):
        return False
    if any(omitted_results.get(name) != "skipped" for name in OMITTED_JOBS):
        return False
    return True


def parse_raw_diff_z(raw: bytes) -> list[DiffRecord] | None:
    """Parse `git diff --raw -z` output. Unreadable output is None."""
    if raw == b"":
        return []
    parts = raw.split(b"\0")
    if parts[-1] == b"":
        parts.pop()
    records: list[DiffRecord] = []
    index = 0
    while index < len(parts):
        meta = parts[index]
        index += 1
        parsed = _parse_meta(meta)
        if parsed is None:
            return None
        old_mode, new_mode, status = parsed
        two_paths = status[:1] in {"R", "C"}
        if two_paths:
            if index + 1 >= len(parts):
                return None
            old_path = _decode_path(parts[index])
            new_path = _decode_path(parts[index + 1])
            index += 2
            if old_path is None or new_path is None:
                return None
        else:
            if index >= len(parts):
                return None
            new_path = _decode_path(parts[index])
            index += 1
            if new_path is None:
                return None
            old_path = None if status == "A" else new_path
        records.append(
            DiffRecord(
                old_mode=old_mode,
                new_mode=new_mode,
                status=status,
                old_path=old_path,
                new_path=new_path,
            )
        )
    return records


def classify_repo(repo: Path, base: str, head: str) -> str:
    """Classify the diff of two commits. Missing or odd evidence is full."""
    records = _load_records(repo, base, head)
    if records is None:
        return "full"
    return classify_records(records)


def whitespace_ok(repo: Path, base: str, head: str) -> bool:
    """Use git's own diff check. A command failure is not a pass."""
    if _commit_sha(base) is None or _commit_sha(head) is None:
        return False
    code, _stdout, _stderr = _git(repo, "diff", "--check", base, head)
    return code == 0


def _ordinary_doc_record(record: DiffRecord) -> bool:
    if record.binary or record.status not in {"A", "M"}:
        return False
    if record.new_mode != REGULAR_FILE:
        return False
    if record.status == "A" and record.old_mode != ABSENT_MODE:
        return False
    if record.status == "M" and record.old_mode != REGULAR_FILE:
        return False
    if record.old_path not in {None, record.new_path}:
        return False
    return ordinary_doc_path(record.new_path)


def _plain_relative_path(path: str) -> bool:
    if path != path.strip() or path == "" or "\\" in path or ":" in path:
        return False
    if path.startswith("/") or "\0" in path:
        return False
    return all(part not in {"", ".", ".."} for part in path.split("/"))


def _parse_meta(meta: bytes) -> tuple[str, str, str] | None:
    if not meta.startswith(b":"):
        return None
    try:
        text = meta.decode("ascii")
    except UnicodeDecodeError:
        return None
    fields = text.split(" ")
    if len(fields) != 5:
        return None
    old_mode = fields[0][1:]
    new_mode = fields[1]
    old_object = fields[2]
    new_object = fields[3]
    status = fields[4]
    if _MODE.fullmatch(old_mode) is None or _MODE.fullmatch(new_mode) is None:
        return None
    if _OBJECT.fullmatch(old_object) is None or _OBJECT.fullmatch(new_object) is None:
        return None
    if _STATUS.fullmatch(status) is None:
        return None
    return old_mode, new_mode, status


def _decode_path(raw: bytes) -> str | None:
    try:
        path = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if path == "" or "\0" in path:
        return None
    return path


def _commit_sha(value: str) -> str | None:
    if _SHA.fullmatch(value) is None:
        return None
    if value.lower() == "0" * 40:
        return None
    return value.lower()


def _load_records(repo: Path, base: str, head: str) -> list[DiffRecord] | None:
    if _commit_sha(base) is None or _commit_sha(head) is None:
        return None
    for sha in (base, head):
        code, _stdout, _stderr = _git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
        if code != 0:
            return None
    code, raw, _stderr = _git(
        repo,
        "diff",
        "--raw",
        "-z",
        "--find-renames",
        base,
        head,
    )
    if code != 0:
        return None
    records = parse_raw_diff_z(raw)
    if not records:
        return records
    loaded: list[DiffRecord] = []
    for record in records:
        binary = record.binary
        if (
            record.status in {"A", "M"}
            and record.new_mode == REGULAR_FILE
            and ordinary_doc_path(record.new_path)
        ):
            cat_code, content, _stderr = _git(
                repo,
                "cat-file",
                "blob",
                f"{head}:{record.new_path}",
            )
            binary = cat_code != 0 or b"\0" in content
        loaded.append(
            DiffRecord(
                old_mode=record.old_mode,
                new_mode=record.new_mode,
                status=record.status,
                old_path=record.old_path,
                new_path=record.new_path,
                binary=binary,
            )
        )
    return loaded


def _git(repo: Path, *args: str) -> tuple[int, bytes, bytes]:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _parse_job(value: str) -> tuple[str, str] | None:
    name, separator, result = value.partition("=")
    if separator != "=" or name == "" or result == "":
        return None
    return name, result


def _verdict(repo: Path, base: str, head: str, jobs: list[str]) -> int:
    parsed = [_parse_job(job) for job in jobs]
    if any(item is None for item in parsed):
        print("unreadable job result", file=sys.stderr)
        return 1
    results = {name: result for name, result in parsed if name}
    classification = classify_repo(repo, base, head)
    accepted = documentation_fast_path_ok(
        classification=classification,
        retained_results=results,
        omitted_results=results,
        whitespace_ok=whitespace_ok(repo, base, head),
    )
    if not accepted:
        print(f"documentation fast path rejected classification={classification}", file=sys.stderr)
        return 1
    print(SUCCESS_TEXT)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    classify = commands.add_parser("classify")
    classify.add_argument("--repo", type=Path, default=Path())
    classify.add_argument("--base", required=True)
    classify.add_argument("--head", required=True)

    verdict = commands.add_parser("verdict")
    verdict.add_argument("--repo", type=Path, default=Path())
    verdict.add_argument("--base", required=True)
    verdict.add_argument("--head", required=True)
    verdict.add_argument("--job", action="append", default=[])

    args = parser.parse_args(argv)
    if args.command == "classify":
        mode = classify_repo(args.repo, args.base, args.head)
        if mode != "docs-only":
            mode = "full"
        print(mode)
        return 0
    return _verdict(args.repo, args.base, args.head, list(args.job))


if __name__ == "__main__":
    raise SystemExit(main())
