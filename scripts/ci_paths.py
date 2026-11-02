#!/usr/bin/env python3
"""Conservative per-area PR job selection; main and release remain full.

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
)

AREAS = ("backend", "frontend", "browser", "visual", "release", "windows")
# Real-backend journeys consume backend source/migrations and the frontend.
# Standalone backend tests do not change those journeys. Mocked visual tests use
# frontend inputs; unknown/shared inputs still select every area.
# Keep the existing release and Windows ownership for all backend changes.
BACKEND_AREAS = frozenset({"backend", "browser", "release", "windows"})
BACKEND_TEST_AREAS = frozenset({"backend", "release", "windows"})
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
            or record.old_mode != (ABSENT_MODE if record.status == "A" else REGULAR_FILE)
            or record.old_path not in {None, record.new_path}
            or not _plain_relative_path(record.new_path)
            or any(ord(char) < 32 or ord(char) == 127 for char in record.new_path)
        ):
            return full
        # Executable and packaging inputs are shared even inside a product tree.
        # Keep this before prose/product matching so safety jobs cannot be omitted.
        parts = record.new_path.lower().split("/")
        if parts[-1].endswith(".ps1") or {"scripts", "packaging", "release", "installer"}.intersection(
            parts[:-1]
        ):
            return full
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
                code, blob, _stderr = _git(repo, "cat-file", "blob", f"{head}:{record.new_path}")
                if code != 0 or b"\0" in blob:
                    return full
        return selected_areas(records)
    except (OSError, UnicodeError):
        return full


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path())
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    selected = classify_repo(args.repo, args.base, args.head)
    print("mode=full" if selected else "mode=docs-only")
    for area in AREAS:
        print(f"{area}={str(area in selected).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
