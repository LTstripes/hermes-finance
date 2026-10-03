"""Offline synthetic-only Owner inventory privacy/filesystem regressions."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "owner_workspace_inventory.py"
spec = importlib.util.spec_from_file_location("owner_inventory", SCRIPT)
assert spec and spec.loader
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def git(path, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return (
        subprocess.check_output(
            ["git", "-c", f"safe.directory={path}", "-C", str(path), *args], env=env
        )
        .decode()
        .strip()
    )


@pytest.fixture
def checkout(tmp_path):
    path = tmp_path / "workspaces" / "synthetic-task"
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("synthetic code\n")
    git(path, "add", "README.md")
    git(
        path,
        "-c",
        "user.name=Synthetic",
        "-c",
        "user.email=synthetic@example.com",
        "commit",
        "-q",
        "-m",
        "synthetic",
    )
    git(path, "remote", "add", "origin", tool.CANONICAL_ORIGIN)
    git(path, "update-ref", "refs/remotes/origin/main", "HEAD")
    return path


def registry(tmp_path, entries):
    file = tmp_path / "registry.json"
    file.write_text(
        json.dumps(
            {"version": 1, "workspace_roots": [str(tmp_path / "workspaces")], "entries": entries}
        )
    )
    return tool.load_registry(file)


def row(tmp_path, path, **fields):
    data = registry(tmp_path, [{"role": "workspace", "path": str(path), **fields}])
    return tool.inventory(data)["entries"][0]


def test_clean_clone_is_offline_unknown_not_deletion_permission(tmp_path, checkout):
    before = {
        p: (p.stat().st_size, p.stat().st_mtime_ns) for p in checkout.rglob("*") if p.is_file()
    }
    report = row(tmp_path, checkout, active=False, artifacts_resolved=True)
    assert report["git"]["head"] == git(checkout, "rev-parse", "HEAD")
    assert report["git"]["origin"] == "canonical"
    assert report["git"]["branch"] == "main"
    assert report["git"]["dirty"] is False
    assert report["git"]["unique_commits_to_cached_remotes"] is False
    assert report["classification"] == "UNKNOWN"
    assert str(tmp_path) not in json.dumps(report)
    assert before == {
        p: (p.stat().st_size, p.stat().st_mtime_ns) for p in checkout.rglob("*") if p.is_file()
    }


def test_dirty_and_hidden_local_branch_are_detected(tmp_path, checkout):
    (checkout / "README.md").write_text("modified synthetic code\n")
    assert row(tmp_path, checkout)["git"]["dirty"] is True
    git(checkout, "add", "README.md")
    git(
        checkout,
        "-c",
        "user.name=Synthetic",
        "-c",
        "user.email=synthetic@example.com",
        "commit",
        "-q",
        "-m",
        "unpublished",
    )
    git(checkout, "branch", "private-looking-name")
    git(checkout, "reset", "--hard", "refs/remotes/origin/main")  # fixture ONLY
    report = row(tmp_path, checkout)
    assert report["git"]["unique_commits_to_cached_remotes"] is True
    assert "private-looking-name" not in json.dumps(report)
    assert report["classification"] == "ACTIVE WORKSPACE"


@pytest.mark.parametrize(
    "name",
    [".env", "data/finance.db", "private/payload.json", "backups/test.bak", "exports/test.csv"],
)
def test_private_markers_disable_content_based_git_status(tmp_path, checkout, monkeypatch, name):
    private = checkout / name
    private.parent.mkdir(exist_ok=True)
    private.write_text("SYNTHETIC_SENTINEL_MUST_NOT_APPEAR")
    calls = []
    original = tool.subprocess.run

    def observed(args, **kwargs):
        calls.append(args)
        return original(args, **kwargs)

    monkeypatch.setattr(tool.subprocess, "run", observed)
    report = row(tmp_path, checkout, active=False)
    assert report["git"]["dirty"] == "unknown"
    assert report["disk"]["private_markers"] is True
    assert not any("status" in args for args in calls)
    assert name not in json.dumps(report)
    assert "SYNTHETIC_SENTINEL" not in json.dumps(report)


def test_runtime_never_hashes_private_worktree_files(tmp_path, checkout, monkeypatch):
    calls = []
    original = tool.subprocess.run
    monkeypatch.setattr(
        tool.subprocess, "run", lambda args, **kw: (calls.append(args), original(args, **kw))[1]
    )
    runtime = tmp_path / "stable"
    checkout.rename(runtime)
    (runtime / ".env").write_text("synthetic")
    data = registry(
        tmp_path, [{"role": "stable", "path": str(runtime), "data_path": str(runtime / "data")}]
    )
    report = tool.inventory(data)["entries"][0]
    assert report["classification"] == "KEEP"
    assert report["git"]["dirty"] == "unknown"
    assert report["data_disk"]["complete"] is False
    assert not any("status" in args for args in calls)


@pytest.mark.parametrize("kind", ["hardlink", "symlink", "git_pointer", "alternate"])
def test_indirection_stays_unknown_without_following(tmp_path, checkout, kind):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "sentinel"
    secret.write_text("synthetic")
    if kind == "hardlink":
        os.link(secret, checkout / "alias")
    elif kind == "symlink":
        try:
            (checkout / "alias").symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("Windows symlink privilege unavailable; junction probe runs separately")
    elif kind == "git_pointer":
        pointer = tmp_path / "workspaces" / "pointer"
        pointer.mkdir()
        (pointer / ".git").write_text("gitdir: " + str(outside))
        checkout = pointer
    else:
        (checkout / ".git" / "objects" / "info" / "alternates").write_text(str(outside))
    report = row(tmp_path, checkout, active=False)
    assert report["git"]["dirty"] == "unknown"
    assert report["classification"] == "UNKNOWN"
    assert str(outside) not in json.dumps(report)


def test_windows_junction_and_ancestor_are_not_followed(tmp_path, checkout):
    if os.name != "nt":
        pytest.skip("Windows junction probe")
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = checkout / "alias"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)], check=True, capture_output=True
    )
    assert row(tmp_path, checkout)["disk"]["indirection"] is True
    with pytest.raises(tool.InventoryError):
        tool.plain(junction / "child")


@pytest.mark.parametrize(
    "extra",
    [
        "[include]\n path = ../outside",
        '[filter "evil"]\n clean = malicious-command',
        "[core]\n worktree = ../outside",
    ],
)
def test_unsafe_git_configuration_never_starts_git(tmp_path, checkout, monkeypatch, extra):
    with (checkout / ".git" / "config").open("a") as stream:
        stream.write("\n" + extra + "\n")
    monkeypatch.setattr(
        tool.subprocess, "run", lambda *a, **kw: pytest.fail("unsafe config executed Git")
    )
    assert row(tmp_path, checkout)["git"]["head"] is None


def test_unreachable_and_scan_limit_are_unknown(tmp_path, checkout, monkeypatch):
    monkeypatch.setattr(tool, "MAX_FILES", 1)
    report = row(tmp_path, checkout, active=False)
    assert report["disk"]["complete"] is False
    assert report["git"]["dirty"] == "unknown"
    assert row(tmp_path, checkout / "missing", active=False)["classification"] == "UNKNOWN"


@pytest.mark.parametrize(
    "mutation", ["overlap", "duplicate", "relative", "unknown_field", "boolean_version"]
)
def test_invalid_registry_fails_closed(tmp_path, mutation):
    workspace = str(tmp_path / "workspaces" / "task")
    value = {
        "version": 1,
        "workspace_roots": [str(tmp_path / "workspaces")],
        "entries": [{"role": "workspace", "path": workspace}],
    }
    if mutation == "overlap":
        value["entries"].append({"role": "stable", "path": workspace + "/runtime"})
    elif mutation == "duplicate":
        value["entries"].append(value["entries"][0])
    elif mutation == "relative":
        value["entries"][0]["path"] = "relative"
    elif mutation == "unknown_field":
        value["entries"][0]["delete"] = True
    else:
        value["version"] = True
    file = tmp_path / "registry.json"
    file.write_text(json.dumps(value))
    with pytest.raises(tool.InventoryError):
        tool.load_registry(file)


def test_cli_hides_private_errors_and_paths(tmp_path):
    proc = subprocess.run(
        [os.sys.executable, str(SCRIPT), "--registry", str(tmp_path / "private-name.json")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["cleanup_authorized"] is False
    assert str(tmp_path) not in proc.stdout + proc.stderr


def test_unknown_entry_inside_workspace_root_is_preserved(tmp_path, checkout):
    data = registry(tmp_path, [{"role": "unknown", "path": str(checkout)}])
    report = tool.inventory(data)["entries"][0]
    assert report["classification"] == "UNKNOWN"
    assert report["git"]["dirty"] == "unknown"
