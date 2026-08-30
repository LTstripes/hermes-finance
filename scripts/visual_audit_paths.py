#!/usr/bin/env python3
"""Classify paths that require the synthetic frontend visual audit."""

from __future__ import annotations

import argparse
from pathlib import Path

VISUAL_AUDIT_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        "frontend/index.html",
        "frontend/package-lock.json",
        "frontend/package.json",
        "frontend/playwright.visual.config.ts",
    }
)
VISUAL_AUDIT_PREFIXES = (
    "frontend/e2e/",
    "frontend/public/",
    "frontend/scripts/",
    "frontend/src/",
)


def normalize_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_visual_audit_path(path: str) -> bool:
    normalized = normalize_path(path)
    if normalized in VISUAL_AUDIT_PATHS:
        return True
    if normalized.startswith(VISUAL_AUDIT_PREFIXES):
        return True
    return normalized.startswith(("frontend/tsconfig", "frontend/vite.config."))


def should_run(paths: list[str]) -> bool:
    return any(is_visual_audit_path(path) for path in paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-file",
        type=Path,
        required=True,
        help="newline-delimited changed paths",
    )
    args = parser.parse_args()
    paths = args.from_file.read_text(encoding="utf-8").splitlines()
    print("true" if should_run(paths) else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
