"""Owner-only, offline inventory. Never changes or deletes an inspected path."""

from __future__ import annotations

import argparse
import configparser
import ctypes
import json
import os
import re
import stat
import subprocess
from pathlib import Path

CANONICAL_ORIGIN = "https://github.com/LTstripes/hermes-finance.git"
MAX_ENTRIES = 64
MAX_FILES = 100_000
MAX_TEXT = 256 * 1024
ROLES = {"stable", "control", "preview", "workspace", "unknown"}
PROTECTED_DIRS = {"data", "private", "backups", "exports", "owner-probes"}


class InventoryError(Exception):
    """Only fixed codes may cross the CLI boundary."""


def within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def plain(path: Path, *, directory: bool = False) -> os.stat_result:
    """lstat every ancestor before access; never resolve/follow indirection."""
    for part in [*reversed(path.parents), path]:
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise InventoryError("indirection")
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise InventoryError("invalid_parent")
    if directory and not stat.S_ISDIR(info.st_mode):
        raise InventoryError("not_directory")
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise InventoryError("hardlink")
    return info


def read_metadata(path: Path) -> str:
    before = plain(path)
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_TEXT:
        raise InventoryError("invalid_metadata")
    # O_NOFOLLOW where available; Windows reparse/ancestor check above is mandatory.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise InventoryError("changed_during_read")
        raw = stream.read(MAX_TEXT + 1)
    after = plain(path)
    identity = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
    )
    if identity(before) != identity(after) or len(raw) > MAX_TEXT:
        raise InventoryError("changed_during_read")
    return raw.decode("utf-8-sig")


def protected(path: Path) -> bool:
    name = path.name.lower()
    return (
        name.startswith((".env", ".hermes-"))
        or name in PROTECTED_DIRS
        or bool(re.search(r"\.(db|sqlite3?|backup|bak|pdf|xlsx?|csv)(-|$)", name))
        or any(
            word in name for word in ("credential", "secret", "token", "finance_data_")
        )
    )


def scan(path: Path) -> dict:
    """Names/stat only, including ignored files. No file contents are opened."""
    result = {
        "bytes_lower_bound": 0,
        "complete": True,
        "private_markers": False,
        "indirection": False,
    }
    pending = [path]
    count = 0
    try:
        plain(path, directory=True)
        while pending:
            folder = pending.pop()
            plain(folder, directory=True)
            with os.scandir(folder) as entries:
                for item in entries:
                    count += 1
                    if count > MAX_FILES:
                        raise InventoryError("scan_limit")
                    child = Path(item.path)
                    # Windows DirEntry.stat caches zero st_nlink; lstat gives the
                    # actual hardlink count and identity without following links.
                    info = child.lstat()
                    if (
                        stat.S_ISLNK(info.st_mode)
                        or getattr(info, "st_file_attributes", 0) & 0x400
                    ):
                        result["indirection"] = True
                        result["complete"] = False
                        continue
                    if stat.S_ISREG(info.st_mode):
                        if info.st_nlink != 1:
                            result["indirection"] = True
                            result["complete"] = False
                        result["bytes_lower_bound"] += info.st_size
                    elif not stat.S_ISDIR(info.st_mode):
                        raise InventoryError("unsupported_entry")
                    if protected(child):
                        result["private_markers"] = True
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(child)
    except InventoryError as exc:
        result["complete"] = False
        if str(exc) in {"indirection", "hardlink"}:
            result["indirection"] = True
    except OSError:
        result["complete"] = False
    return result


def absolute(value: object) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise InventoryError("invalid_registry")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise InventoryError("invalid_registry")
    if os.name == "nt":
        if value.startswith(("\\\\", "//")) or not re.fullmatch(
            r"[A-Za-z]:", path.drive
        ):
            raise InventoryError("invalid_registry")
        if any(part.endswith((".", " ")) or ":" in part for part in path.parts[1:]):
            raise InventoryError("invalid_registry")
        if (
            ctypes.windll.kernel32.GetDriveTypeW(path.anchor) != 3
        ):  # local fixed disk only
            raise InventoryError("invalid_registry")
    # Do not resolve links or expand environment variables from untrusted input.
    return path


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InventoryError("invalid_registry")
        result[key] = value
    return result


def load_registry(path: Path) -> dict:
    if protected(path):
        raise InventoryError("invalid_registry")
    registry = json.loads(read_metadata(path), object_pairs_hook=no_duplicates)
    if not isinstance(registry, dict) or set(registry) != {
        "version",
        "workspace_roots",
        "entries",
    }:
        raise InventoryError("invalid_registry")
    if type(registry["version"]) is not int or registry["version"] != 1:
        raise InventoryError("invalid_registry")
    roots = registry["workspace_roots"]
    entries = registry["entries"]
    if not isinstance(roots, list) or not 1 <= len(roots) <= MAX_ENTRIES:
        raise InventoryError("invalid_registry")
    registry["workspace_roots"] = [absolute(root) for root in roots]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
        raise InventoryError("invalid_registry")
    paths = []
    for entry in entries:
        if not isinstance(entry, dict) or not {"role", "path"} <= set(entry):
            raise InventoryError("invalid_registry")
        if set(entry) - {
            "role",
            "path",
            "data_path",
            "expected_sha",
            "release_tag",
            "active",
            "artifacts_resolved",
        }:
            raise InventoryError("invalid_registry")
        if entry["role"] not in ROLES:
            raise InventoryError("invalid_registry")
        entry["path"] = absolute(entry["path"])
        if "data_path" in entry:
            if entry["role"] not in {"stable", "preview", "unknown"}:
                raise InventoryError("invalid_registry")
            entry["data_path"] = absolute(entry["data_path"])
        for flag in ("active", "artifacts_resolved"):
            if flag in entry and type(entry[flag]) is not bool:
                raise InventoryError("invalid_registry")
        if "expected_sha" in entry and not re.fullmatch(
            r"[0-9a-f]{40}", entry["expected_sha"]
        ):
            raise InventoryError("invalid_registry")
        if "release_tag" in entry and not re.fullmatch(
            r"v[0-9]+\.[0-9]+\.[0-9]+", entry["release_tag"]
        ):
            raise InventoryError("invalid_registry")
        paths.append(entry["path"])
    if len(paths) != len(set(paths)):
        raise InventoryError("overlapping_registry")
    # Every declared code/data boundary must be disjoint, except a runtime's own data child.
    for i, entry in enumerate(entries):
        if entry["role"] == "workspace" and not any(
            within(entry["path"], root) and entry["path"] != root
            for root in registry["workspace_roots"]
        ):
            raise InventoryError("workspace_outside_root")
        for other in entries[i + 1 :]:
            for left in (entry["path"], entry.get("data_path")):
                for right in (other["path"], other.get("data_path")):
                    if left and right and (within(left, right) or within(right, left)):
                        raise InventoryError("overlapping_registry")
        if entry["role"] in {"stable", "control", "preview"}:
            for boundary in (entry["path"], entry.get("data_path")):
                if boundary and any(
                    within(boundary, root) or within(root, boundary)
                    for root in registry["workspace_roots"]
                ):
                    raise InventoryError("overlapping_registry")
        if entry.get("data_path") and within(entry["path"], entry["data_path"]):
            raise InventoryError("overlapping_registry")
    return registry


def git_identity(path: Path, tree: dict, role: str) -> dict:
    result = {
        "kind": "unknown",
        "head": None,
        "branch": "unknown",
        "origin": "unknown",
        "dirty": "unknown",
        "unique_commits_to_cached_remotes": "unknown",
    }
    gitdir = path / ".git"
    try:
        plain(path, directory=True)
        info = plain(gitdir)
        if stat.S_ISREG(info.st_mode):
            # Do not read/follow a worktree pointer into another checkout/runtime.
            result["kind"] = "linked_worktree_or_pointer"
            return result
        plain(gitdir, directory=True)
        metadata = scan(gitdir)
        if (
            not metadata["complete"]
            or metadata["indirection"]
            or metadata["private_markers"]
        ):
            return result
        # Reject alternate object stores and submodule/shared Git directories.
        if any(
            (gitdir / name).exists()
            for name in ("objects/info/alternates", "commondir", "modules")
        ):
            return result
        config = configparser.RawConfigParser(strict=True)
        config.read_string(read_metadata(gitdir / "config"))
        for section in config.sections():
            if section != "core" and not re.fullmatch(
                r"(remote|branch|user) .*|user", section
            ):
                raise InventoryError("unsafe_git_config")
        if set(config.options("core")) - {
            "repositoryformatversion",
            "filemode",
            "bare",
            "logallrefupdates",
            "ignorecase",
            "precomposeunicode",
            "longpaths",
            "symlinks",
        }:
            raise InventoryError("unsafe_git_config")
        if config.get("core", "bare", fallback="true").lower() != "false":
            return result
        for section in config.sections():
            if section.startswith("remote ") and set(config.options(section)) - {
                "url",
                "fetch",
                "pushurl",
            }:
                raise InventoryError("unsafe_git_config")
        # Git may read only regular, unaliased metadata/code inside this checked boundary.
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_OPTIONAL_LOCKS="0",
            GIT_TERMINAL_PROMPT="0",
        )
        args = [
            "git",
            "--no-optional-locks",
            "-c",
            f"safe.directory={path}",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            f"core.attributesFile={os.devnull}",
            "-c",
            f"core.excludesFile={os.devnull}",
            "-c",
            "gc.auto=0",
            "-C",
            str(path),
        ]

        def git(*command: str) -> str:
            proc = subprocess.run(
                args + list(command),
                env=env,
                capture_output=True,
                timeout=30,
                check=False,
            )
            if proc.returncode or len(proc.stdout) > 8 * 1024 * 1024:
                raise InventoryError("git_unavailable")
            return proc.stdout.decode("utf-8", errors="strict").strip()

        head = git("rev-parse", "--verify", "HEAD^{commit}")
        if not re.fullmatch(r"[0-9a-f]{40}", head):
            raise InventoryError("git_unavailable")
        result["kind"] = "independent_clone"
        result["head"] = head
        # Return no arbitrary branch names, remote URLs, Git errors or filenames.
        branch = git("rev-parse", "--abbrev-ref", "HEAD")
        result["branch"] = (
            "main" if branch == "main" else "detached" if branch == "HEAD" else "other"
        )
        origin = config.get('remote "origin"', "url", fallback="")
        result["origin"] = (
            "canonical" if origin == CANONICAL_ORIGIN else "other_or_missing"
        )
        if (
            role == "workspace"
            and tree["complete"]
            and not tree["private_markers"]
            and not tree["indirection"]
        ):
            result["dirty"] = bool(
                git("status", "--porcelain=v1", "-z", "--untracked-files=all")
            )
            remotes = git("for-each-ref", "--format=%(objectname)", "refs/remotes/")
            if remotes:
                # Includes all local branches/tags/stash, not just the checked-out HEAD.
                result["unique_commits_to_cached_remotes"] = bool(
                    git("rev-list", "--max-count=1", "--all", "--not", "--remotes")
                )
        if head != git("rev-parse", "--verify", "HEAD^{commit}"):
            raise InventoryError("changed_during_read")
    except (
        OSError,
        InventoryError,
        ValueError,
        configparser.Error,
        subprocess.SubprocessError,
    ):
        result["dirty"] = "unknown"
        result["unique_commits_to_cached_remotes"] = "unknown"
    return result


def inventory(registry: dict, *, local_paths: bool = False) -> dict:
    rows = []
    for index, entry in enumerate(registry["entries"], 1):
        path = entry["path"]
        tree = scan(path)
        identity = git_identity(path, tree, entry["role"])
        classification = (
            "KEEP" if entry["role"] in {"stable", "control", "preview"} else "UNKNOWN"
        )
        if entry["role"] == "workspace" and entry.get("active", True):
            classification = "ACTIVE WORKSPACE"
        row = {
            "entry": index,
            "declared_role": entry["role"],
            "classification": classification,
            "git": identity,
            "disk": tree,
            "data_boundary": "declared" if "data_path" in entry else "unknown",
            "identity_matches_pin": identity["head"] == entry.get("expected_sha")
            if entry.get("expected_sha")
            else "unknown",
            "artifacts_resolved": entry.get("artifacts_resolved", "unknown"),
        }
        if "data_path" in entry:
            row["data_disk"] = scan(entry["data_path"])
        if local_paths:
            row["path"] = str(path)
            row["data_path"] = str(entry["data_path"]) if "data_path" in entry else None
        rows.append(row)
    return {
        "version": 1,
        "mode": "read_only_offline",
        "remote_freshness": "unknown",
        "cleanup_authorized": False,
        "entries": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument(
        "--local-paths",
        action="store_true",
        help="Owner-local output ONLY; never share this mode",
    )
    args = parser.parse_args()
    try:
        registry = load_registry(absolute(str(args.registry)))
        print(json.dumps(inventory(registry, local_paths=args.local_paths), indent=2))
        return 0
    except (OSError, ValueError, TypeError, RecursionError, InventoryError):
        print(
            json.dumps(
                {
                    "error": "registry_unavailable_or_invalid",
                    "cleanup_authorized": False,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
