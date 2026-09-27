#!/usr/bin/env python3
"""Classify paths that require the Windows launcher safety/package harness."""

from __future__ import annotations

import argparse
from pathlib import Path

# Keep this set bounded. start-local/prepare-runtime stay on Windows production
# smoke; they do not by themselves publish or install the launcher.
LAUNCHER_CI_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        "scripts/launcher-schema-check.py",
        "scripts/launcher_ci_paths.py",
        "scripts/tests/test-windows-launcher-package.ps1",
    }
)
LAUNCHER_CI_PREFIXES = ("launcher/windows/",)


def normalize_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_launcher_ci_path(path: str) -> bool:
    normalized = normalize_path(path)
    if normalized in LAUNCHER_CI_PATHS or normalized == "launcher/windows":
        return True
    return normalized.startswith(LAUNCHER_CI_PREFIXES)


def should_run(paths: list[str]) -> bool:
    return any(is_launcher_ci_path(path) for path in paths)


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
