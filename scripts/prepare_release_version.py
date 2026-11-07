#!/usr/bin/env python3
"""Prepare local version metadata; never publish or create a release."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")


def assert_plain_path(path: Path, *, directory: bool = False) -> None:
    """Refuse linked components and multiply-linked files in a task checkout."""
    absolute = path.absolute()
    for part in (*reversed(absolute.parents), absolute):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked paths are not allowed")
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Target must be a directory")
        return
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Target must be an unlinked regular file")


def runtime_version(text: str) -> str:
    nodes = ast.parse(text).body
    if (
        len(nodes) == 2
        and isinstance(nodes[0], ast.Expr)
        and isinstance(nodes[0].value, ast.Constant)
        and isinstance(nodes[0].value.value, str)
    ):
        nodes = nodes[1:]
    if (
        len(nodes) != 1
        or not isinstance(nodes[0], ast.Assign)
        or len(nodes[0].targets) != 1
        or not isinstance(nodes[0].targets[0], ast.Name)
        or nodes[0].targets[0].id != "__version__"
        or not isinstance(nodes[0].value, ast.Constant)
        or not isinstance(nodes[0].value.value, str)
    ):
        raise ValueError("Existing runtime version disagrees")
    return nodes[0].value.value


def assert_clean_tree(root: Path) -> None:
    result = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "-C",
            str(root),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode or result.stderr:
        raise ValueError("Unable to verify clean Git tree")
    if result.stdout.strip():
        raise ValueError("Refusing a dirty tree; commit or preserve changes first")


def prepare(root: Path, new: str) -> list[str]:
    if not VERSION.fullmatch(new):
        raise ValueError("Version must be stable X.Y.Z")
    assert_clean_tree(root)
    paths = [
        "backend/pyproject.toml",
        "backend/uv.lock",
        "backend/src/hermes_finance/__init__.py",
        "frontend/package.json",
        "frontend/package-lock.json",
    ]
    for name in paths:
        assert_plain_path(root / name)
    original = {name: (root / name).read_bytes() for name in paths}
    contents = {name: content.decode("utf-8") for name, content in original.items()}
    project = tomllib.loads(contents[paths[0]])["project"]
    old = project["version"]
    if not VERSION.fullmatch(old) or tuple(map(int, new.split("."))) <= tuple(
        map(int, old.split("."))
    ):
        raise ValueError(
            "Target version must be greater than the current stable version"
        )
    if runtime_version(contents[paths[2]]) != old:
        raise ValueError("Existing runtime version disagrees")
    lock = tomllib.loads(contents[paths[1]])
    packages = [p for p in lock["package"] if p["name"] == project["name"]]
    frontend = json.loads(contents[paths[3]])
    npm_lock = json.loads(contents[paths[4]])
    if (
        len(packages) != 1
        or packages[0]["version"] != old
        or any(
            v != old
            for v in (
                frontend["version"],
                npm_lock["version"],
                npm_lock["packages"][""]["version"],
            )
        )
    ):
        raise ValueError("Existing release identities disagree")
    notes = root / "docs" / f"release-notes-{new}.md"
    notes_name = f"docs/release-notes-{new}.md"
    if notes.exists() or notes.is_symlink():
        assert_plain_path(notes)
        if not notes.read_text(encoding="utf-8").strip():
            raise ValueError("Existing release notes are empty")
    else:
        assert_plain_path(root / "docs", directory=True)
    replacements = {}
    for name, text in contents.items():
        needle = f'"{old}"'
        expected = 2 if name.endswith("package-lock.json") else 1
        if text.count(needle) != expected:
            raise ValueError(f"Unexpected version occurrences in {name}")
        replacements[name] = text.replace(needle, f'"{new}"')
    new_project = tomllib.loads(replacements[paths[0]])["project"]
    new_lock = tomllib.loads(replacements[paths[1]])
    new_packages = [p for p in new_lock["package"] if p["name"] == new_project["name"]]
    new_front = json.loads(replacements[paths[3]])
    new_npm = json.loads(replacements[paths[4]])
    if len(new_packages) != 1 or any(
        value != new
        for value in (
            new_project["version"],
            new_packages[0]["version"],
            runtime_version(replacements[paths[2]]),
            new_front["version"],
            new_npm["version"],
            new_npm["packages"][""]["version"],
        )
    ):
        raise ValueError("Prepared release identities disagree")
    if not notes.exists():
        replacements[notes_name] = (
            f"# Hermes Finance {new}\n\n"
            "UAT-PENDING - candidate notes; complete before publication.\n\n"
            "## Changes\n\nTODO\n\n## Verification\n\nTODO\n"
        )
        paths.append(notes_name)
    staged = {}
    changed = []
    try:
        for name, text in replacements.items():
            target = root / name
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                staged[name] = Path(output.name)
                output.write(text.encode("utf-8"))
            if target.exists():
                os.chmod(staged[name], target.stat().st_mode)
        for name in paths:
            changed.append(name)
            os.replace(staged[name], root / name)
    except (OSError, KeyboardInterrupt) as error:
        restore_failed = False
        for name in reversed(changed):
            try:
                if name in original:
                    (root / name).write_bytes(original[name])
                else:
                    (root / name).unlink(missing_ok=True)
            except OSError:
                restore_failed = True
        if restore_failed:
            raise OSError(
                "Preparation failed and rollback was incomplete; inspect the checkout"
            ) from error
        raise OSError(
            "Preparation failed; restored modified files; inspect the checkout"
        ) from error
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "version", help="stable X.Y.Z greater than current; requires a clean tree"
    )
    args = parser.parse_args()
    try:
        changed = prepare(ROOT, args.version)
    except SyntaxError:
        parser.exit(
            1, "Version preparation failed: a version file has invalid Python syntax\n"
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Version preparation failed: {error}\n")
    print(
        "Prepared local metadata; review the diff and run independent identity checks:"
    )
    for path in changed:
        print(path)


if __name__ == "__main__":
    main()
