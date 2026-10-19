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

AREAS = ("backend", "frontend", "browser", "release", "windows")
# The browser journeys and production startup consume both product trees.
# Windows release/recovery tests consume backend code, but not frontend leaves.
BACKEND_AREAS = frozenset({"backend", "browser", "release", "windows"})
FRONTEND_AREAS = frozenset({"frontend", "browser", "windows"})
# Dependency/build/toolchain changes are shared, even under a product tree.
PRODUCT_PREFIXES = {
    "backend/src/": BACKEND_AREAS,
    "backend/tests/": BACKEND_AREAS,
    "backend/migrations/": BACKEND_AREAS,
    "frontend/src/": FRONTEND_AREAS,
    "frontend/public/": FRONTEND_AREAS,
    "frontend/e2e/": FRONTEND_AREAS,
}


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
        if ordinary_doc_path(record.new_path):
            continue
        for prefix, areas in PRODUCT_PREFIXES.items():
            if record.new_path.startswith(prefix):
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
