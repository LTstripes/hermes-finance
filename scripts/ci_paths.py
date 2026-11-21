#!/usr/bin/env python3
"""Conservative PR area selection and a narrow post-installation main push path.

Only regular text additions/edits in known product trees can narrow coverage.
Both the current base/head diff and the PR-owned diff are inspected, so a
base advance cannot hide a changed input. Missing/ambiguous evidence is full.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from docs_only_ci import (
    ABSENT_MODE,
    REGULAR_FILE,
    DiffRecord,
    _git,
    _load_records,
    _plain_relative_path,
    ordinary_doc_path,
    whitespace_ok,
)

AREAS = ("backend", "frontend", "browser", "visual", "release", "windows")
# Real-backend journeys consume backend source/migrations and the frontend.
# Standalone backend tests do not change those journeys. Mocked visual tests use
# frontend inputs; unknown/shared inputs still select every area.
# Runtime and shared test consumers keep their existing ownership.
BACKEND_AREAS = frozenset({"backend", "browser", "release", "windows"})
BACKEND_TEST_AREAS = frozenset({"backend", "release", "windows"})
AUTONOMOUS_BACKEND_TESTS = frozenset(
    f"test_{name}.py"
    for name in (
        "accounts",
        "cash",
        "comments",
        "debts",
        "deposits",
        "expenses",
        "goals",
        "incomes",
    )
)
AUTONOMOUS_SCRIPT_TESTS = frozenset(
    f"scripts/tests/test-{name}.py"
    for name in (
        "ci-paths",
        "docs-only-ci",
        "pr-concurrency",
        "ui-evidence-identity",
        "visual-audit-paths",
    )
)
FRONTEND_AREAS = frozenset({"frontend", "browser", "visual", "windows"})
# Dependency/build/toolchain changes are shared, even under a product tree.
PRODUCT_PREFIXES = {
    "backend/src/": BACKEND_AREAS,
    "backend/tests/": BACKEND_AREAS,
    "backend/migrations/": BACKEND_AREAS,
    "frontend/src/": FRONTEND_AREAS,
    "frontend/public/": FRONTEND_AREAS,
    "frontend/e2e/": FRONTEND_AREAS,
}

# Some browser seeds import backend test modules as reusable fixtures. Keep
# these audited families (and every non-test/helper/resource path) on browser.
# The import-closure regression detects new dependencies outside these families.
BROWSER_TEST_PREFIXES = (
    "test_close_readiness",
    "test_historical_",
    "test_instrument_",
    "test_payout_",
    "test_r08_",
    "test_scratch_",
    "test_source_",
    "test_statement_import_",
)


def backend_test_areas(path: str) -> frozenset[str]:
    """Only standalone top-level test modules may omit browser journeys."""
    relative = path.removeprefix("backend/tests/")
    # Audited direct consumers: backend matrix only. Unknown/new tests retain
    # the old conservative selection until their shared consumers are checked.
    if relative in AUTONOMOUS_BACKEND_TESTS:
        return frozenset({"backend"})
    if (
        "/" not in relative
        and relative.startswith("test_")
        and relative.endswith(".py")
        and not relative.startswith(BROWSER_TEST_PREFIXES)
    ):
        return BACKEND_TEST_AREAS
    return BACKEND_AREAS


def selected_areas(records: list[DiffRecord] | None) -> frozenset[str]:
    """Return all areas unless every changed record has a known safe owner."""
    full = frozenset(AREAS)
    if not records:
        return full
    selected: set[str] = set()
    for record in records:
        if (
            record.binary
            or record.status not in {"A", "M"}
            or record.new_mode != REGULAR_FILE
            or record.old_mode
            != (ABSENT_MODE if record.status == "A" else REGULAR_FILE)
            or record.old_path not in {None, record.new_path}
            or not _plain_relative_path(record.new_path)
            or any(ord(char) < 32 or ord(char) == 127 for char in record.new_path)
        ):
            return full
        # Executable and packaging inputs are shared even inside a product tree.
        # Keep this before prose/product matching so safety jobs cannot be omitted.
        parts = record.new_path.lower().split("/")
        if record.new_path in AUTONOMOUS_SCRIPT_TESTS:
            selected.add("checks")  # Privacy runs these; this is not docs-only.
            continue
        if parts[-1].endswith(".ps1") or {
            "scripts",
            "packaging",
            "release",
            "installer",
        }.intersection(parts[:-1]):
            return full
        if record.new_path.startswith("frontend/src/") and record.new_path.endswith(
            (".test.ts", ".test.tsx")
        ):
            selected.add("frontend")
            continue
        if ordinary_doc_path(record.new_path):
            continue
        for prefix, areas in PRODUCT_PREFIXES.items():
            if record.new_path.startswith(prefix):
                if prefix == "backend/tests/":
                    areas = backend_test_areas(record.new_path)
                selected.update(areas)
                break
        else:
            # Workflows, scripts, schemas, release notes, locks, config and all
            # unknown inputs retain every job. No blanket docs/** exemption.
            return full
    return frozenset(selected)


def classify_repo(repo: Path, base: str, head: str) -> frozenset[str]:
    """Inspect actual Git records, including PR-owned changes after base moves."""
    full = frozenset(AREAS)
    try:
        current = _load_records(repo, base, head)
        if not current:
            return full
        code, raw_base, _stderr = _git(repo, "merge-base", "--all", base, head)
        bases = raw_base.decode("ascii").splitlines()
        if code != 0 or len(bases) != 1:
            return full
        owned = _load_records(repo, bases[0], head)
        if not owned:
            return full
        records = current + owned
        # docs_only_ci inspects prose blobs; product blobs also need binary
        # detection before they can narrow this gate.
        for record in records:
            if not ordinary_doc_path(record.new_path):
                code, blob, _stderr = _git(
                    repo, "cat-file", "blob", f"{head}:{record.new_path}"
                )
                if code != 0 or b"\0" in blob:
                    return full
        return selected_areas(records)
    except (OSError, UnicodeError):
        return full


def status_section_boundary(content: bytes) -> tuple[str, str] | None:
    """Compare everything outside the existing release/installation section."""
    text = content.decode("utf-8")
    start = '<a id="s1"></a>\n## 1. Code, release, installation and UAT\n'
    end = '\n<a id="s2"></a>\n## 2. Integrated code and limitations\n'
    if "\0" in text or text.count(start) != 1 or text.count(end) != 1:
        return None
    prefix, _, section = text.partition(start)
    _body, marker, suffix = section.partition(end)
    return (prefix, suffix) if marker else None


def main_push_mode(repo: Path, base: str, head: str) -> str:
    path = "docs/CURRENT_STATUS.md"
    try:
        records = _load_records(repo, base, head)
        if records != [DiffRecord(REGULAR_FILE, REGULAR_FILE, "M", path, path, False)]:
            return "full"
        code, parent, _ = _git(repo, "rev-parse", f"{head}^1")
        if code or parent.decode("ascii").strip() != base or not whitespace_ok(repo, base, head):
            return "full"
        boundaries = []
        for sha in (base, head):
            code, blob, _ = _git(repo, "cat-file", "blob", f"{sha}:{path}")
            outside = status_section_boundary(blob)
            if code or outside is None:
                return "full"
            boundaries.append(outside)
        if boundaries[0] == boundaries[1]:
            return "status-only"
    except (OSError, UnicodeError):
        pass
    return "full"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path())
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--main-push", action="store_true")
    args = parser.parse_args()
    if args.main_push:
        print(f"mode={main_push_mode(args.repo, args.base, args.head)}")
        return 0
    selected = classify_repo(args.repo, args.base, args.head)
    print("mode=full" if selected else "mode=docs-only")
    for area in AREAS:
        print(f"{area}={str(area in selected).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
