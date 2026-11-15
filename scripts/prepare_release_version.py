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
import tomllib
from pathlib import Path

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


def runtime_version_node(text: str) -> ast.Constant:
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
    return nodes[0].value


def runtime_version(text: str) -> str:
    return runtime_version_node(text).value


def replace_runtime_version(text: str, new: str) -> str:
    node = runtime_version_node(text)
    # AST columns are UTF-8 byte offsets, including when a docstring precedes
    # the assignment on the same line. Leave that docstring and comments alone.
    lines = text.encode("utf-8").splitlines(keepends=True)
    start = sum(map(len, lines[: node.lineno - 1])) + node.col_offset
    end = sum(map(len, lines[: node.end_lineno - 1])) + node.end_col_offset
    raw = text.encode("utf-8")
    literal = raw[start:end]
    quote = chr(literal[0])
    if quote not in ("'", '"') or literal != f"{quote}{node.value}{quote}".encode():
        raise ValueError("Unexpected runtime version literal")
    return (raw[: start + 1] + new.encode() + raw[end - 1 :]).decode("utf-8")


def replace_project_version(text: str, old: str, new: str) -> str:
    section = re.search(r"(?m)^[ \t]*\[[ \t]*project[ \t]*\][ \t]*(?:#[^\r\n]*)?\r?\n", text)
    if section is None:
        raise ValueError("Missing [project] version section")
    next_section = re.search(r"(?m)^[ \t]*\[", text[section.end() :])
    end = section.end() + next_section.start() if next_section else len(text)
    field = re.compile(
        rf"""(?m)^([ \t]*version[ \t]*=[ \t]*)(["']){re.escape(old)}\2([ \t]*(?:\#[^\r\n]*)?\r?$)"""
    )
    body = text[section.end() : end]
    if len(field.findall(body)) != 1:
        raise ValueError("Unexpected [project].version field")
    body = field.sub(lambda m: f"{m[1]}{m[2]}{new}{m[2]}{m[3]}", body)
    return text[: section.end()] + body + text[end:]


def replace_json_version(text: str, keys: tuple[str, ...], new: str) -> str:
    """Locate an object member with JSON decoding; splice only its value token."""
    decoder = json.JSONDecoder()

    def skip_space(position: int) -> int:
        while position < len(text) and text[position] in " \t\r\n":
            position += 1
        return position

    def locate(position: int, path: tuple[str, ...]) -> tuple[int, int]:
        position = skip_space(position)
        if text[position] != "{":
            raise ValueError("Expected JSON version object")
        position = skip_space(position + 1)
        matches = []
        while text[position] != "}":
            key, position = decoder.raw_decode(text, position)
            position = skip_space(position)
            if text[position] != ":":
                raise ValueError("Expected JSON member separator")
            start = skip_space(position + 1)
            _, end = decoder.raw_decode(text, start)
            if key == path[0]:
                matches.append(locate(start, path[1:]) if len(path) > 1 else (start, end))
            position = skip_space(end)
            if text[position] == ",":
                position = skip_space(position + 1)
        if len(matches) != 1:
            raise ValueError(f"Expected one JSON field at {keys!r}")
        return matches[0]

    start, end = locate(0, keys)
    return text[:start] + json.dumps(new) + text[end:]


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
        raise ValueError("Target version must be greater than the current stable version")
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
        if name == paths[1]:
            # A dependency may share the version string (alembic 1.19.0 did), so
            # anchor the lock replacement to this project's own package entry.
            anchor = re.compile(
                rf'(name = "{re.escape(project["name"])}"\r?\nversion = )"{re.escape(old)}"'
            )
            if len(anchor.findall(text)) != 1:
                raise ValueError(f"Unexpected version occurrences in {name}")
            replacements[name] = anchor.sub(lambda m: f'{m.group(1)}"{new}"', text)
            continue
        if name == paths[0]:
            replacements[name] = replace_project_version(text, old, new)
        elif name == paths[2]:
            replacements[name] = replace_runtime_version(text, new)
        else:
            replacements[name] = replace_json_version(text, ("version",), new)
            if name == paths[4]:
                replacements[name] = replace_json_version(
                    replacements[name], ("packages", "", "version"), new
                )
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
            f"# Finance {new}\n\n"
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
    parser.add_argument("version", help="stable X.Y.Z greater than current; requires a clean tree")
    args = parser.parse_args()
    try:
        changed = prepare(ROOT, args.version)
    except SyntaxError:
        parser.exit(1, "Version preparation failed: a version file has invalid Python syntax\n")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Version preparation failed: {error}\n")
    print("Prepared local metadata; review the diff and run independent identity checks:")
    for path in changed:
        print(path)


if __name__ == "__main__":
    main()
