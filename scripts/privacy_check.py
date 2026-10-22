#!/usr/bin/env python3
"""Fail closed when private data or generated financial artifacts are tracked."""

from __future__ import annotations

import argparse
import hashlib
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
    re.compile(r"(?i)(?:" + "/" + "Users/" + "|" + "/" + "home/" + r")([^/\s\"'`<>]+)"),
)
SECRET_PATTERNS = (
    (
        "access token prefix",
        re.compile(r"\b(?:ghp|github_pat|xox[baprs])_[A-Za-z0-9_-]{12,}\b"),
    ),
    ("cloud key prefix", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("API key prefix", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    ("secret key prefix", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)
# Match literal credentials, rather than variable names or environment lookups.
CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?im)\b[a-z0-9_]*(?:password|secret|token)\b[\"']?\s*[:=]\s*"
    r"(?P<quote>[\"'])(?P<value>[^\"'\r\n]+)(?P=quote)"
)
BARE_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?im)^\s*[a-z0-9_]*(?:password|secret|token)\s*[:=]\s*(?P<value>[^\s\"'#;]+)\s*(?:[#;].*)?$"
)
CREDENTIALED_URL = re.compile(
    r"(?i)\b(?:https?|wss?|ftp)://(?P<userinfo>[^\s/\"'<>@]+)@[^\s/\"'<>]+"
)


def _synthetic_credential(value: str) -> bool:
    """Explicit placeholder values only; a test/document path is never exempt."""
    lowered = value.lower()
    return (
        lowered.startswith(
            ("synthetic", "dummy", "fake", "example", "test-", "test_", "placeholder")
        )
        or lowered in {"secret", "token", "password", "change-me", "changeme", "redacted"}
        or value.startswith(("$", "<", "{", "%"))
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
    if name == ".git-credentials":
        return "credential store"
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "environment file"
    if name.endswith(FORBIDDEN_SUFFIXES) or re.search(r"\.(?:db|sqlite3?)-(?:shm|wal)$", name):
        return "private document or database artifact"
    if name.endswith(".snap"):
        return "snapshot artifact"
    return None


# Exact existing synthetic fixtures and the recovery header name.
# A new value or a different file still fails; no directory-wide exemption.
_SYNTHETIC_LITERALS = {
    (
        "backend/src/hermes_finance/main.py",
        "b69a9dae257065a21b570674ae4504f52a7080af2034a995a3c616c1b7d877fb",
    ),
    (
        "backend/tests/security/test_security_review.py",
        "97286efb3adeadd4cca3e7ae78872f4b82bc5a36a902dd8fbc2ffcd2f1bddb45",
    ),
    (
        "backend/tests/test_alfa_pro_probe.py",
        "ef56588f62f4c4a02a7d8327d88add1c7eb2a62a8557cc0b742b1bbf005f3ff2",
    ),
    (
        "backend/tests/test_alfa_pro_snapshot.py",
        "c9976babfd5a7bcb1425ebbda365f2a8d27a4e67fe91a9690a991c3ac70cc1bd",
    ),
    (
        "backend/tests/test_recovery_process.py",
        "61feeb9f9191c3553230914118aee8f9a34af496013e438a0dbf956a2bb36f25",
    ),
    (
        "backend/tests/test_recovery_process.py",
        "a6ab9859e4793ec36f3f5565337385ebb1648452d8a5531b8e9f5dd2f18283f2",
    ),
    (
        "backend/tests/test_recovery_process.py",
        "d13d08821167f9cdb51d9f56746414a8b0325b6cb096d69447280e84786c35f0",
    ),
    (
        "backend/tests/test_recovery_process.py",
        "d755d6f0e5fa3de60ce8ff82367623521dc9d0e56e041351cce218a6a4ca5825",
    ),
    (
        "backend/tests/test_recovery_process.py",
        "dda0dc5f48fe9692d39ff312eb5fdf2e5c05cbf7a9b2128b6f76fd83db76dbec",
    ),
    (
        "backend/tests/test_recovery_rehearsal.py",
        "c1bda738725af761ae2bf4cc97b57c21ddb74f2bcc41abeb0189e2c7257e091b",
    ),
    (
        "backend/tests/test_recovery_rehearsal.py",
        "ff042ab4ccbc1e4bccf5e4e208b22fd33917069b270f1ecb6fe67a95221a17cf",
    ),
    (
        "backend/tests/test_scratch_preflight_runtime.py",
        "75ccd368764dcf6fd73820ef5646f9250bea9421ac18ba1005f12b4531b338b0",
    ),
    (
        "backend/tests/test_t_invest_payout_probe.py",
        "cde2fea7894e9fd9e4e7d2c9fa9e9134e892304c4c56ec7804af6a258edf6201",
    ),
    (
        "backend/tests/test_t_invest_probe.py",
        "cde2fea7894e9fd9e4e7d2c9fa9e9134e892304c4c56ec7804af6a258edf6201",
    ),
    (
        "frontend/src/ui-v2/ObservedValuationCapture.test.tsx",
        "4562d7527c94e007183a719c4da05c13b11f151a66d3980c22265a5b7ee97272",
    ),
    (
        "frontend/src/ui-v2/PerformancePreparation.test.tsx",
        "275a2eddc78a50b823eafc940ed5c5a2aa9c5aa156f297d34c82829afd8797f5",
    ),
    (
        "frontend/src/ui-v2/PerformancePreparation.test.tsx",
        "80411bda52e4ad799b212ecf7e93c0bc17264a8cdae9d3a0309cd10dda0cdd25",
    ),
    (
        "frontend/src/ui-v2/PerformancePreparation.test.tsx",
        "eb8d18d1a8afd17e5a1ab8cd581b22dc8df602d7961e68ff72116112001de709",
    ),
}


def _known_synthetic_literal(path: str, literal: str) -> bool:
    return (
        path.replace(chr(92), "/"),
        hashlib.sha256(literal.encode()).hexdigest(),
    ) in _SYNTHETIC_LITERALS


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
    for match in CREDENTIAL_ASSIGNMENT.finditer(text):
        if not _synthetic_credential(match.group("value")) and not _known_synthetic_literal(
            path, match.group()
        ):
            findings.add("generic credential assignment")
    if Path(path).suffix.lower() in {
        ".conf",
        ".cfg",
        ".ini",
        ".toml",
        ".yaml",
        ".yml",
        ".properties",
    }:
        for match in BARE_CREDENTIAL_ASSIGNMENT.finditer(text):
            if not _synthetic_credential(match.group("value")):
                findings.add("generic credential assignment")
    for match in CREDENTIALED_URL.finditer(text):
        if not _known_synthetic_literal(path, match.group()):
            findings.add("credentialed URL")
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
