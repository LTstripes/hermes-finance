"""Owner-local frozen cleanup plans. Inventory remains permanently read-only."""

from __future__ import annotations

import argparse
import configparser
import ctypes
import hashlib
import json
import os
import re
import stat
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path

import owner_workspace_inventory as inv

TTL = 900
MAX_OUTPUT = 8 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{40}")


class Hold(Exception):
    """Fixed, privacy-safe reason only."""


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def identity(info):
    return [
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
    ]


class Pins:
    """Windows handles deny writes/deletion; never open a reparse target.

    Ancestors deny rename/deletion. Selected tree objects also deny writes.
    Apply uses these SAME handles for disposition, never a recursive path API.
    """

    def __init__(self):
        self.handles = {}
        self.records = {}
        if os.name == "nt":
            from ctypes import wintypes

            self.api = ctypes.WinDLL("kernel32", use_last_error=True)
            self.api.CreateFileW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            self.api.CreateFileW.restype = wintypes.HANDLE
            self.api.CloseHandle.argtypes = [wintypes.HANDLE]
            self.api.SetFileInformationByHandle.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            self.api.SetFileInformationByHandle.restype = wintypes.BOOL
            self.api.GetFinalPathNameByHandleW.argtypes = [
                wintypes.HANDLE,
                wintypes.LPWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
            ]
            self.api.GetFinalPathNameByHandleW.restype = wintypes.DWORD
            self.api.GetFileInformationByHandleEx.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            self.api.GetFileInformationByHandleEx.restype = wintypes.BOOL

    def pin(self, path, *, delete=False, ancestor=False):
        if path in self.handles:
            return
        before = inv.plain(path)
        if os.name != "nt":
            return
        access = 0x80 | (0x10000 if delete else 0)  # attributes, DELETE
        if not ancestor:
            access |= 0x80000000  # data/list access enforces share-deny-write
        sharing = 3 if ancestor else 1  # never FILE_SHARE_DELETE
        handle = self.api.CreateFileW(
            str(path), access, sharing, None, 3, 0x02000000 | 0x00200000, None
        )  # backup semantics, OPEN_REPARSE_POINT
        if handle == ctypes.c_void_p(-1).value:
            raise Hold("busy_or_inaccessible")
        self.handles[path] = handle
        attributes = (ctypes.c_uint32 * 2)()
        if (
            not self.api.GetFileInformationByHandleEx(handle, 9, attributes, 8)
            or attributes[0] & 0x400
        ):
            raise Hold("indirection")
        canonical = ctypes.create_unicode_buffer(32768)
        length = self.api.GetFinalPathNameByHandleW(
            handle, canonical, len(canonical), 0
        )
        if (
            not length
            or length >= len(canonical)
            or Path(canonical.value.removeprefix("\\\\?\\")) != path
        ):
            raise Hold("aliased_path")
        if identity(before) != identity(inv.plain(path)):
            raise Hold("path_changed")

    def upgrade(self, paths):
        """Acquire DELETE only after Git has finished; prove each opened file.

        Git/CRT readers do not consistently share DELETE on Windows. Keep all
        parent pins while upgrading leaves first, verifying identities and bytes
        after each handover. No Git/path traversal occurs after this point.
        """
        import msvcrt

        for path in sorted(paths, key=lambda p: len(p.parts), reverse=True):
            expected, content = self.records[path]
            self.api.CloseHandle(self.handles.pop(path))
            self.pin(path, delete=True)
            if identity(inv.plain(path)) != expected:
                raise Hold("path_changed")
            if stat.S_ISREG(expected[2]):
                # CRT owns the handle after conversion. Remove it from the native
                # map and retain the fd until disposition/close.
                fd = msvcrt.open_osfhandle(
                    self.handles[path], os.O_RDONLY | os.O_BINARY
                )
                self.handles[path] = (fd, msvcrt.get_osfhandle(fd))
                if identity(os.fstat(fd)) != expected:
                    raise Hold("path_changed")
                h = hashlib.sha256()
                while chunk := os.read(fd, 1024 * 1024):
                    h.update(chunk)
                if content is not None and h.hexdigest() != content:
                    raise Hold("path_changed")

    def ancestors(self, path):
        for part in reversed(path.parents):
            self.pin(part, ancestor=True)

    def erase(self, paths):
        if os.name != "nt":
            raise Hold("windows_apply_required")
        # Bottom-up, exact opened objects. A newly created child causes directory
        # disposition to fail; it is never discovered and recursively removed.
        for path in sorted(paths, key=lambda p: len(p.parts), reverse=True):
            flags = ctypes.c_uint32(1 | 0x10)  # DELETE | IGNORE_READONLY_ATTRIBUTE
            opened = self.handles[path]
            handle = opened[1] if isinstance(opened, tuple) else opened
            if not self.api.SetFileInformationByHandle(
                handle, 21, ctypes.byref(flags), 4
            ):
                raise Hold("deletion_incomplete")
            if isinstance(opened, tuple):
                os.close(opened[0])
            else:
                self.api.CloseHandle(handle)
            del self.handles[path]

    def close(self):
        if os.name == "nt":
            for handle in reversed(list(self.handles.values())):
                if isinstance(handle, tuple):
                    os.close(handle[0])
                else:
                    self.api.CloseHandle(handle)
        self.handles.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def scan(path, pins, *, shared=False):
    """Bounded names/stat scan, then hash public code/metadata under held pins."""
    pins.ancestors(path)
    pending, found = [path], {}
    while pending:
        child = pending.pop()
        if len(found) >= inv.MAX_FILES:
            raise Hold("scan_limit")
        pins.pin(child)
        info = inv.plain(child)
        if child.name == ".env.example" and not stat.S_ISREG(info.st_mode):
            raise Hold("private_marker")
        if child.name == ".gitmodules" or (
            child.name == ".git" and child.parent != path
        ):
            raise Hold("nested_git")
        # Exact template names only; tracked status is checked after safe Git setup.
        if child != path and inv.protected(child) and child.name != ".env.example":
            raise Hold("private_marker")
        # Legitimate tracked project lockfiles (for example backend/uv.lock)
        # are ordinary code. Only Git administrative *.lock files indicate an
        # active repository operation and must block cleanup.
        if child.name.endswith(".lock") and any(
            part.lower() == ".git" for part in child.parts
        ):
            raise Hold("active_lock")
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise Hold("unsupported_entry")
        found[child] = identity(info)
        if stat.S_ISDIR(info.st_mode):
            if shared and child == path / ".git" / "worktrees":
                continue  # only explicitly declared registration may be opened
            with os.scandir(child) as entries:
                pending.extend(Path(item.path) for item in entries)
    # No content access before the COMPLETE privacy/alias scan succeeds.
    rows = []
    for child, ident in sorted(found.items()):
        content = None
        if stat.S_ISREG(ident[2]) and child.name != ".env.example":
            h = hashlib.sha256()
            with child.open("rb") as stream:
                if identity(os.fstat(stream.fileno())) != ident:
                    raise Hold("path_changed")
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
            content = h.hexdigest()
        if identity(inv.plain(child)) != ident:
            raise Hold("path_changed")
        rows.append([str(child.relative_to(path)), ident, content])
        pins.records[child] = (ident, content)
    return {
        "fingerprint": digest(rows),
        "bytes": sum(i[4] for i in found.values() if stat.S_ISREG(i[2])),
        "paths": list(found),
    }


def read_json(path):
    try:
        if inv.protected(path):
            raise Hold("invalid_document")
        return json.loads(
            inv.read_metadata(inv.absolute(str(path))),
            object_pairs_hook=inv.no_duplicates,
        )
    except (OSError, ValueError, TypeError, RecursionError, inv.InventoryError):
        raise Hold("invalid_document") from None


def load_config(path):
    raw = read_json(path)
    required = {
        "version",
        "owner_root",
        "stable",
        "control",
        "preview",
        "workspace_roots",
        "entries",
    }
    if (
        not isinstance(raw, dict)
        or set(raw) != required
        or type(raw["version"]) is not int
        or raw["version"] != 1
    ):
        raise Hold("invalid_configuration")
    for name in ("owner_root", "stable", "control", "preview"):
        raw[name] = inv.absolute(raw[name])
    if (
        not isinstance(raw["workspace_roots"], list)
        or not 1 <= len(raw["workspace_roots"]) <= 64
    ):
        raise Hold("invalid_configuration")
    roots = raw["workspace_roots"] = [inv.absolute(p) for p in raw["workspace_roots"]]
    protected = [raw[n] for n in ("stable", "control", "preview")]
    boundaries = roots + protected
    if any(
        inv.within(a, b) or inv.within(b, a)
        for i, a in enumerate(boundaries)
        for b in boundaries[i + 1 :]
    ):
        raise Hold("overlapping_boundaries")
    if any(inv.within(raw["owner_root"], b) for b in boundaries):
        raise Hold("overlapping_boundaries")
    entries = raw["entries"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
        raise Hold("invalid_configuration")
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not {"path", "role"} <= set(entry)
            or set(entry)
            - {
                "path",
                "role",
                "active",
                "artifacts_resolved",
                "git_dir",
                "git_common_dir",
            }
            or entry["role"] not in inv.ROLES
        ):
            raise Hold("invalid_configuration")
        for key in ("path", "git_dir", "git_common_dir"):
            if key in entry:
                entry[key] = inv.absolute(entry[key])
        for key in ("active", "artifacts_resolved"):
            if key in entry and type(entry[key]) is not bool:
                raise Hold("invalid_configuration")
    if any(
        inv.within(a["path"], b["path"]) or inv.within(b["path"], a["path"])
        for i, a in enumerate(entries)
        for b in entries[i + 1 :]
    ):
        raise Hold("overlapping_entries")
    return raw


def portable(config):
    return {
        k: (
            [{a: str(b) if isinstance(b, Path) else b for a, b in e.items()} for e in v]
            if k == "entries"
            else [str(p) for p in v]
            if isinstance(v, list)
            else str(v)
            if isinstance(v, Path)
            else v
        )
        for k, v in config.items()
    }


def safe_config(common):
    config = configparser.RawConfigParser(strict=True)
    config.read_string(inv.read_metadata(common / "config"))
    for section in config.sections():
        allowed = (
            {
                "repositoryformatversion",
                "filemode",
                "bare",
                "logallrefupdates",
                "ignorecase",
                "precomposeunicode",
                "longpaths",
                "symlinks",
            }
            if section == "core"
            else {"url", "fetch", "pushurl"}
            if section == 'remote "origin"'
            else {"remote", "merge"}
            if section.startswith('branch "')
            else {"name", "email"}
            if section == "user"
            else set()
        )
        if not allowed or set(config.options(section)) - allowed:
            raise Hold("unsafe_git_config")
    if (
        config.get("core", "bare", fallback="true") != "false"
        or config.get('remote "origin"', "url", fallback="") != inv.CANONICAL_ORIGIN
    ):
        raise Hold("untrusted_git_origin")
    if any(
        (common / p).exists()
        for p in (
            "objects/info/alternates",
            "objects/info/http-alternates",
            "modules",
            "shallow",
            "info/grafts",
            "commondir",
        )
    ):
        raise Hold("external_or_incomplete_git")


def git(path, *command, input_bytes=None):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
        GIT_NO_REPLACE_OBJECTS="1",
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
        *command,
    ]
    try:
        result = subprocess.run(
            args,
            env=env,
            capture_output=True,
            timeout=30,
            check=False,
            input=input_bytes,
        )
        if result.returncode or len(result.stdout) > MAX_OUTPUT:
            raise Hold("git_evidence_unavailable")
        return result.stdout.decode("utf-8", errors="strict").strip()
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise Hold("git_evidence_unavailable") from None


def remote_main(control):
    # Fixed canonical endpoint; Owner's existing gh authentication only. Local
    # Git configuration cannot select a credential helper or network command.
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                "--hostname",
                "github.com",
                "repos/LTstripes/hermes-finance/git/ref/heads/main",
                "--jq",
                ".object.sha",
            ],
            cwd=control,
            capture_output=True,
            timeout=30,
            check=False,
        )
        main = result.stdout.decode("ascii").strip()
        if result.returncode or not SHA.fullmatch(main):
            raise Hold("remote_evidence_unavailable")
        return main
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise Hold("remote_evidence_unavailable") from None


def preserved(commit, ancestors):
    # This set comes exclusively from the pinned trusted Control object graph.
    # Membership proves both existence there and ancestry; cached candidate
    # remote refs cannot fabricate preservation. Avoid one process per historic
    # commit (large real histories otherwise exceed the frozen-plan lifetime).
    if not SHA.fullmatch(commit) or commit not in ancestors:
        raise Hold("unique_or_local_only_history")


def trusted(config, pins):
    control = config["control"]
    tree = scan(control, pins, shared=True)
    common = control / ".git"
    inv.plain(common, directory=True)
    safe_config(common)
    verify_index_bytes(control, tree)
    if git(control, "symbolic-ref", "HEAD") != "refs/heads/main" or git(
        control, "status", "--porcelain=v1", "--untracked-files=all"
    ):
        raise Hold("control_not_clean_main")
    main = remote_main(control)
    if (
        git(control, "rev-parse", "HEAD") != main
        or git(control, "rev-parse", "refs/remotes/origin/main") != main
    ):
        raise Hold("control_not_current")
    return main, tree


def verify_index_bytes(path, tree):
    """Do not trust status's index flags or cached timestamps as clean proof."""
    flags = git(path, "ls-files", "-v", "-z").split("\0")
    if any(item and not item.startswith("H ") for item in flags):
        raise Hold("hidden_index_state")
    expected, names = [], []
    scanned = set(tree["paths"])
    for item in git(path, "ls-files", "--stage", "-z").split("\0"):
        if not item:
            continue
        metadata, name = item.split("\t", 1)
        mode, obj, stage = metadata.split()
        file = inv.absolute(str(path / name))
        if (
            stage != "0"
            or mode not in {"100644", "100755"}
            or file not in scanned
            or not inv.within(file, path)
            or not SHA.fullmatch(obj)
        ):
            raise Hold("unsupported_index")
        names.append(name)
        expected.append(obj)
    # Git C quoting handles arbitrary UTF-8/newline filenames without allowing
    # option or path injection. Git hashes real bytes, including its safe text
    # normalization, without writing objects or trusting stat caches. Filters
    # cannot execute: safe_config rejects all filter/include/core execution settings.
    quoted = "".join(
        '"' + "".join(f"\\{b:03o}" for b in name.encode("utf-8")) + '"\n'
        for name in names
    )
    actual = git(
        path, "hash-object", "--stdin-paths", input_bytes=quoted.encode("ascii")
    ).splitlines()
    if actual != expected:
        raise Hold("uncommitted_bytes")


def inspect(config, entry, pins, main):
    path = entry["path"]
    if (
        entry["role"] != "workspace"
        or entry.get("active") is not False
        or entry.get("artifacts_resolved") is not True
    ):
        raise Hold("ownership_or_artifacts_unresolved")
    if not any(path.parent == root for root in config["workspace_roots"]):
        raise Hold("not_task_child")
    if path == config["owner_root"] or any(
        inv.within(path, config[n]) or inv.within(config[n], path)
        for n in ("stable", "control", "preview")
    ):
        raise Hold("protected_boundary")
    if inv.protected(path):
        raise Hold("private_marker")
    tree = scan(path, pins)
    dotgit = path / ".git"
    info = inv.plain(dotgit)
    admin_tree = None
    if stat.S_ISDIR(info.st_mode):
        if "git_dir" in entry or "git_common_dir" in entry:
            raise Hold("git_declaration_mismatch")
        kind, common, admin = "independent_clone", dotgit, dotgit
        if (common / "worktrees").exists() or (common / "commondir").exists():
            raise Hold("shared_git_clone")
    else:
        kind = "linked_worktree"
        common, admin = entry.get("git_common_dir"), entry.get("git_dir")
        # Shared metadata authority is exclusively trusted Control; never follow
        # an arbitrary pointer into Stable/Preview/another client/unknown clone.
        if (
            common != config["control"] / ".git"
            or admin is None
            or admin.parent != common / "worktrees"
        ):
            raise Hold("undeclared_or_untrusted_git_pointer")
        pointer = inv.read_metadata(dotgit).strip()
        if (
            pointer != "gitdir: " + str(admin)
            and pointer != "gitdir: " + admin.as_posix()
        ):
            raise Hold("git_pointer_mismatch")
        admin_tree = scan(admin, pins)
        allowed = {
            ".",
            "HEAD",
            "index",
            "commondir",
            "gitdir",
            "logs",
            "logs/HEAD",
            "ORIG_HEAD",
            "refs",  # Git may create this empty directory for an ordinary worktree
        }
        if any(
            p.relative_to(admin).as_posix() not in allowed for p in admin_tree["paths"]
        ):
            raise Hold("additional_worktree_metadata")
        if (admin / "refs").exists():
            inv.plain(admin / "refs", directory=True)
        if inv.read_metadata(admin / "commondir").strip() != "../..":
            raise Hold("git_pointer_mismatch")
        back = inv.absolute(inv.read_metadata(admin / "gitdir").strip())
        if back != dotgit or (admin / "locked").exists():
            raise Hold("git_pointer_mismatch")
    safe_config(common)
    verify_index_bytes(path, tree)
    if git(path, "rev-parse", "--show-toplevel") != str(path).replace("\\", "/"):
        raise Hold("git_root_mismatch")
    # No untracked OR ignored artifacts are silently discarded.
    if git(path, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"):
        raise Hold("dirty_untracked_or_ignored")
    templates = [
        p.relative_to(path).as_posix()
        for p in tree["paths"]
        if p.name == ".env.example"
    ]
    template_hashes = {}
    for template in templates:
        if git(path, "ls-files", "--error-unmatch", "--", template) != template:
            raise Hold("untracked_template")
        # Only now is this known to be a tracked public template. Retain bytes
        # for the Windows handle handover, without exposing content in the plan.
        template_path = path / template
        ident, _ = pins.records[template_path]
        pins.records[template_path] = (
            ident,
            hashlib.sha256(template_path.read_bytes()).hexdigest(),
        )
        template_hashes[template] = pins.records[template_path][1]
    head = git(path, "rev-parse", "--verify", "HEAD^{commit}")
    ancestors = set(git(config["control"], "rev-list", main).splitlines())
    if main not in ancestors or not all(SHA.fullmatch(c) for c in ancestors):
        raise Hold("invalid_ancestry_evidence")
    preserved(head, ancestors)
    refs = git(path, "for-each-ref", "--format=%(refname) %(objectname)")
    if kind == "independent_clone":
        for line in refs.splitlines():
            ref, obj = line.split()
            if ref.startswith(("refs/stash", "refs/replace/")):
                raise Hold("stash_or_replace_ref")
            preserved(git(path, "rev-parse", obj + "^{commit}"), ancestors)
        # Include reflog-only history, not just tips. Dangling blobs/trees and
        # commits are also HOLD: their preservation needs an Owner decision.
        for commit in set(git(path, "rev-list", "--all", "--reflog").splitlines()):
            preserved(commit, ancestors)
        if git(path, "fsck", "--unreachable", "--no-progress"):
            raise Hold("unreachable_git_objects")
    elif (admin / "logs" / "HEAD").exists():
        # Registration deletion removes this private-to-the-worktree reflog.
        # Other shared branches/stashes/reflogs stay in Control untouched.
        commits = set()
        for line in inv.read_metadata(admin / "logs" / "HEAD").splitlines():
            fields = line.split(" ", 2)
            if len(fields) != 3 or not all(SHA.fullmatch(c) for c in fields[:2]):
                raise Hold("invalid_reflog")
            commits.update(c for c in fields[:2] if c != "0" * 40)
        for commit in commits:
            preserved(commit, ancestors)
    if kind == "linked_worktree" and (admin / "ORIG_HEAD").exists():
        preserved(inv.read_metadata(admin / "ORIG_HEAD").strip(), ancestors)
    evidence = {
        "kind": kind,
        "head": head,
        "tree": tree["fingerprint"],
        "bytes": tree["bytes"],
        "admin": admin_tree["fingerprint"] if admin_tree else None,
        "refs": digest(refs),
        "templates": digest(template_hashes),
    }
    return evidence, tree["paths"] + (admin_tree["paths"] if admin_tree else [])


def plan(config, *, now=None):
    now = int(time.time()) if now is None else now
    rows = []
    with Pins() as pins:
        main, control_tree = trusted(config, pins)
        for index, entry in enumerate(config["entries"]):
            try:
                # Separate candidate pins; common Control pins remain held.
                with Pins() as candidate:
                    evidence, _ = inspect(config, entry, candidate, main)
                rows.append(
                    {"entry": index, "state": "CANDIDATE", "evidence": evidence}
                )
            except Hold as exc:
                rows.append({"entry": index, "state": "HOLD", "reason": str(exc)})
            except (inv.InventoryError, OSError, ValueError, configparser.Error):
                rows.append(
                    {"entry": index, "state": "HOLD", "reason": "unsafe_or_unresolved"}
                )
    return {
        "version": 1,
        "mode": "frozen_plan",
        "created": now,
        "expires": now + TTL,
        "config": portable(config),
        "main": main,
        "control_identity": identity(inv.plain(config["control"])),
        "entries": rows,
        "control_tree": control_tree["fingerprint"],
    }


def apply(config, frozen, approved_digest, *, now=None, journal=None):
    now = int(time.time()) if now is None else now
    if os.name != "nt":
        raise Hold("windows_apply_required")
    if (
        digest(frozen) != approved_digest
        or frozen.get("config") != portable(config)
        or frozen.get("version") != 1
    ):
        raise Hold("plan_mismatch")
    if (
        type(frozen.get("created")) is not int
        or type(frozen.get("expires")) is not int
        or not frozen["created"] <= now <= frozen["expires"]
        or frozen["expires"] - frozen["created"] != TTL
    ):
        raise Hold("stale_plan")
    deleted = []
    if not isinstance(frozen.get("entries"), list) or len(frozen["entries"]) != len(
        config["entries"]
    ):
        raise Hold("invalid_plan")
    for index, row in enumerate(frozen["entries"]):
        if (
            not isinstance(row, dict)
            or row.get("entry") != index
            or row.get("state") not in {"HOLD", "CANDIDATE"}
        ):
            raise Hold("invalid_plan")
    for row in frozen["entries"]:
        if row["state"] != "CANDIDATE":
            continue
        index = row["entry"]
        if journal:
            journal(index, "revalidating")
        with ExitStack() as stack:
            pins = stack.enter_context(Pins())
            target = stack.enter_context(Pins())
            main, _ = trusted(
                config, pins
            )  # fresh remote proof immediately per deletion
            if (
                main != frozen["main"]
                or identity(inv.plain(config["control"])) != frozen["control_identity"]
            ):
                raise Hold("trusted_state_changed")
            if int(time.time()) > frozen["expires"]:
                raise Hold("stale_plan")
            evidence, paths = inspect(config, config["entries"][index], target, main)
            if evidence != row["evidence"]:
                raise Hold("candidate_changed")
            target.upgrade(paths)
            if journal:
                journal(index, "deleting")
            if int(time.time()) > frozen["expires"]:
                raise Hold("stale_plan")
            target.erase(paths)
            deleted.append(index)
            if journal:
                journal(index, "deleted")
    return {"mode": "applied", "deleted_entries": deleted}


def run_cli(args):
    with Pins() as inputs:
        config_path = inv.absolute(str(args.config))
        inputs.ancestors(config_path)
        inputs.pin(config_path)
        config = load_config(config_path)
        destination = inv.absolute(str(args.plan))
        forbidden = config["workspace_roots"] + [
            config[n] for n in ("stable", "control", "preview")
        ]
        if any(
            inv.within(p, root)
            for p in (destination, config_path)
            for root in forbidden
        ):
            raise Hold("unsafe_document_destination")
        inputs.ancestors(destination)
        inputs.pin(destination.parent, ancestor=True)
        if args.mode == "plan":
            frozen = plan(config)
            with destination.open("x", encoding="utf-8") as stream:
                json.dump(frozen, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            return {
                "mode": "plan",
                "sha256": digest(frozen),
                "candidates": sum(r["state"] == "CANDIDATE" for r in frozen["entries"]),
                "holds": sum(r["state"] == "HOLD" for r in frozen["entries"]),
            }
        if not args.approve_sha256:
            raise Hold("explicit_plan_approval_required")
        inputs.pin(destination)
        frozen = read_json(destination)
        # Exclusive sidecar; a plan cannot be replayed after a partial deletion.
        journal_path = destination.with_name(destination.name + ".apply.jsonl")
        with journal_path.open("x", encoding="utf-8") as stream:

            def journal(entry, state):
                stream.write(
                    json.dumps(
                        {
                            "plan_sha256": args.approve_sha256,
                            "time": int(time.time()),
                            "entry": entry,
                            "state": state,
                        }
                    )
                    + "\n"
                )
                stream.flush()
                os.fsync(stream.fileno())

            try:
                return apply(config, frozen, args.approve_sha256, journal=journal)
            except Exception:
                journal(None, "refused_or_incomplete_reinventory_required")
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("plan", "apply"), default="plan")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--plan",
        required=True,
        type=Path,
        help="Owner-local file outside every protected/workspace tree",
    )
    parser.add_argument(
        "--approve-sha256",
        help="Explicit Owner approval of the exact canonical JSON plan digest",
    )
    args = parser.parse_args()
    try:
        print(json.dumps(run_cli(args)))
        return 0
    except (
        Hold,
        inv.InventoryError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
        configparser.Error,
    ):
        print(
            json.dumps(
                {"error": "cleanup_refused_or_incomplete", "reinventory_required": True}
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
