#!/usr/bin/env python3
"""Fail closed when private data or generated financial artifacts are tracked."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

FORBIDDEN_DIRS = {
    "backup",
    "backups",
    "coverage",
    "export",
    "exports",
    "private",
    "playwright-report",
    "snapshots",
    "test-results",
}
FORBIDDEN_SUFFIXES = (
    ".backup",
    ".bak",
    ".db",
    ".db-shm",
    ".db-wal",
    ".pdf",
    ".pfx",
    ".p12",
    ".pem",
    ".sqlite",
    ".sqlite3",
    ".xls",
    ".xlsm",
    ".xlsx",
)
EMAIL_PATTERN = re.compile(r"(?P<local>[A-Za-z0-9._%+-]+)@(?P<domain>[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+7|8)[\s(.-]+\d{3}[\s).-]+\d{3}[\s.-]+\d{2}[\s.-]+\d{2}(?!\d)"
)
MACHINE_PATH_PATTERNS = (
    re.compile(r"(?i)\b[A-Z]:[\\/]Users[\\/]+([^\\/\s\"'`<>]+)"),
    re.compile(
        r"(?i)(?:" + "/" + "Users/" + "|" + "/" + "home/" + r")([^/\s\"'`<>]+)"
    ),
)
SECRET_PATTERNS = (
    ("access token prefix", re.compile(r"\b(?:ghp|github_pat|xox[baprs])_[A-Za-z0-9_-]{12,}\b")),
    ("cloud key prefix", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("API key prefix", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("secret key prefix", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)
PLACEHOLDER_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "localhost"}


def repository_root(requested: Path | None) -> Path:
    if requested is not None:
        return requested.expanduser().resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip()).resolve()


def tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def forbidden_path(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    name = Path(normalized).name.lower()
    parts = {part.lower() for part in Path(normalized).parts}

    if normalized == "data/.gitkeep":
        return None
    if "data" in parts:
        return "local data path"
    if parts & FORBIDDEN_DIRS:
        return "private or generated directory"
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "environment file"
    if name.endswith(FORBIDDEN_SUFFIXES) or re.search(r"\.(?:db|sqlite3?)-(?:shm|wal)$", name):
        return "private document or database artifact"
    if name.endswith(".snap"):
        return "snapshot artifact"
    return None


def content_findings(path: str, raw: bytes) -> set[str]:
    if b"\0" in raw:
        return set()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return set()

    findings: set[str] = set()
    for match in EMAIL_PATTERN.finditer(text):
        if match.group("domain").lower() not in PLACEHOLDER_EMAIL_DOMAINS:
            findings.add("email address")
            break
    if PHONE_PATTERN.search(text):
        findings.add("phone number")
    for pattern in MACHINE_PATH_PATTERNS:
        if pattern.search(text):
            findings.add("machine-specific user path")
            break
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            findings.add(label)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, help="repository root; defaults to the current Git root"
    )
    args = parser.parse_args()
    root = repository_root(args.root)

    findings: list[tuple[str, str]] = []
    paths = tracked_paths(root)
    for relative_path in paths:
        path_reason = forbidden_path(relative_path)
        if path_reason is not None:
            findings.append((path_reason, relative_path))
            continue

        absolute_path = root / relative_path
        if absolute_path.is_file():
            for reason in content_findings(relative_path, absolute_path.read_bytes()):
                findings.append((reason, relative_path))

    if findings:
        print("privacy-check: FAIL")
        for reason, path in sorted(set(findings)):
            print(f"privacy-check: {reason}: {path}")
        return 1

    print(f"privacy-check: PASS ({len(paths)} tracked files checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
