"""Offline synthetic-only Owner inventory privacy/filesystem regressions."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
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


# Separate cleanup command; the original inventory contract above stays intact.
sys.modules["owner_workspace_inventory"] = tool
cleanup_spec = importlib.util.spec_from_file_location(
    "owner_cleanup", SCRIPT.with_name("owner_workspace_cleanup.py")
)
assert cleanup_spec and cleanup_spec.loader
cleanup = importlib.util.module_from_spec(cleanup_spec)
cleanup_spec.loader.exec_module(cleanup)


@pytest.fixture
def cleanup_case(tmp_path, checkout, monkeypatch):
    control = tmp_path / "control"
    git(checkout, "clone", "--no-hardlinks", str(checkout), str(control))
    git(control, "remote", "set-url", "origin", tool.CANONICAL_ORIGIN)
    monkeypatch.setattr(cleanup, "remote_main", lambda p: git(p, "rev-parse", "HEAD"))
    config_file = tmp_path / "cleanup-config.json"
    config_file.write_text(
        json.dumps(
            {
                "version": 1,
                "owner_root": str(tmp_path),
                "stable": str(tmp_path / "stable"),
                "preview": str(tmp_path / "preview"),
                "control": str(control),
                "workspace_roots": [str(checkout.parent)],
                "entries": [
                    {
                        "path": str(checkout),
                        "role": "workspace",
                        "active": False,
                        "artifacts_resolved": True,
                    }
                ],
            }
        )
    )
    return cleanup.load_config(config_file), checkout, control


def cleanup_row(case):
    return cleanup.plan(case[0])["entries"][0]


def test_cleanup_plan_freezes_clean_independent_clone_without_mutation(cleanup_case):
    config, path, _ = cleanup_case
    with cleanup.Pins() as pins:
        before = cleanup.scan(path, pins)["fingerprint"]
    frozen = cleanup.plan(config)
    assert frozen["entries"][0]["state"] == "CANDIDATE"
    assert frozen["entries"][0]["evidence"]["kind"] == "independent_clone"
    assert frozen["expires"] - frozen["created"] == cleanup.TTL
    with cleanup.Pins() as pins:
        assert cleanup.scan(path, pins)["fingerprint"] == before


@pytest.mark.parametrize(
    "change",
    [
        "dirty",
        "untracked",
        "ignored",
        "ref",
        "stash",
        "reflog",
        "env",
        "untracked_template",
        "hardlink",
        "active",
        "artifacts",
        "unknown",
        "pointer",
        "include",
        "nested_git",
    ],
)
def test_cleanup_unsafe_cases_hold(cleanup_case, change):
    config, path, _ = cleanup_case
    if change == "dirty":
        (path / "README.md").write_text("changed")
    elif change == "untracked":
        (path / "extra").write_text("synthetic")
    elif change == "ignored":
        (path / ".git" / "info" / "exclude").write_text("extra\n")
        (path / "extra").write_text("synthetic")
    elif change in {"ref", "reflog", "stash"}:
        (path / "README.md").write_text("unique synthetic")
        if change == "stash":
            git(
                path,
                "-c",
                "user.name=Synthetic",
                "-c",
                "user.email=synthetic@example.com",
                "stash",
                "push",
            )
        else:
            git(path, "add", "README.md")
            git(
                path,
                "-c",
                "user.name=Synthetic",
                "-c",
                "user.email=synthetic@example.com",
                "commit",
                "-qm",
                "unique",
            )
            if change == "ref":
                git(path, "branch", "unique")
            git(path, "reset", "--hard", "origin/main")  # synthetic fixture ONLY
    elif change in {"env", "untracked_template"}:
        (path / (".env" if change == "env" else ".env.example")).write_text(
            "SYNTHETIC_PRIVATE_SENTINEL"
        )
    elif change == "hardlink":
        os.link(path / "README.md", path / "alias")
    elif change == "active":
        config["entries"][0]["active"] = True
    elif change == "artifacts":
        del config["entries"][0]["artifacts_resolved"]
    elif change == "unknown":
        config["entries"][0]["role"] = "unknown"
    elif change == "pointer":
        git(path, "worktree", "add", "--detach", str(path.parent / "linked"), "HEAD")
        config["entries"][0]["path"] = path.parent / "linked"
    elif change == "include":
        with (path / ".git" / "config").open("a") as stream:
            stream.write("\n[include]\npath = ../outside\n")
    else:
        (path / "nested" / ".git").mkdir(parents=True)
    assert cleanup_row(cleanup_case)["state"] == "HOLD"
    assert "SYNTHETIC_PRIVATE_SENTINEL" not in json.dumps(cleanup.plan(config))


def test_cleanup_tracked_env_example_only_is_allowed(cleanup_case):
    config, path, control = cleanup_case
    (control / ".env.example").write_text("PUBLIC_TEMPLATE=\n")
    (control / "backend").mkdir()
    (control / "backend" / ".env.example").write_text("PUBLIC_TEMPLATE=\n")
    git(control, "add", ".")
    git(
        control,
        "-c",
        "user.name=Synthetic",
        "-c",
        "user.email=synthetic@example.com",
        "commit",
        "-qm",
        "templates",
    )
    git(control, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(path, "fetch", str(control), "main")
    git(path, "merge", "--ff-only", "FETCH_HEAD")
    assert cleanup_row(cleanup_case)["state"] == "CANDIDATE"
    assert tool.protected(path / ".env.example")  # inventory intentionally unchanged


def test_cleanup_tracked_project_lockfile_is_allowed(cleanup_case):
    _, path, control = cleanup_case
    (control / "backend").mkdir()
    (control / "backend" / "uv.lock").write_text("version = 1\n")
    git(control, "add", ".")
    git(
        control,
        "-c",
        "user.name=Synthetic",
        "-c",
        "user.email=synthetic@example.com",
        "commit",
        "-qm",
        "tracked lockfile",
    )
    git(control, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(path, "fetch", str(control), "main")
    git(path, "merge", "--ff-only", "FETCH_HEAD")
    assert cleanup_row(cleanup_case)["state"] == "CANDIDATE"


def test_cleanup_git_admin_lockfile_holds(cleanup_case):
    _, path, _ = cleanup_case
    (path / ".git" / "index.lock").write_text("synthetic lock")
    assert cleanup_row(cleanup_case)["state"] == "HOLD"


def make_linked(case):
    config, old, control = case
    path = old.parent / "linked-task"
    git(control, "worktree", "add", "-b", "preserved-task", str(path), "HEAD")
    admin = control / ".git" / "worktrees" / path.name
    config["entries"][0].update(path=path, git_dir=admin, git_common_dir=control / ".git")
    return path, admin


def test_cleanup_declared_linked_worktree_plans_and_preserves_shared_refs(cleanup_case):
    path, _ = make_linked(cleanup_case)
    row = cleanup_row(cleanup_case)
    assert row["state"] == "CANDIDATE"
    assert row["evidence"]["kind"] == "linked_worktree"
    assert path.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="Windows handle deletion probe")
@pytest.mark.parametrize("linked", [False, True])
def test_cleanup_windows_apply_exact_objects_and_preserves_refs(cleanup_case, linked):
    config, path, control = cleanup_case
    admin = None
    if linked:
        path, admin = make_linked(cleanup_case)
    refs = git(control, "for-each-ref", "--format=%(refname) %(objectname)")
    frozen = cleanup.plan(config)
    assert frozen["entries"][0]["state"] == "CANDIDATE"
    assert cleanup.apply(config, frozen, cleanup.digest(frozen))["deleted_entries"] == [0]
    assert not path.exists()
    assert path.parent.is_dir() and control.is_dir()
    assert git(control, "for-each-ref", "--format=%(refname) %(objectname)") == refs
    if admin:
        assert not admin.exists()
        assert str(path).replace("\\", "/") not in git(control, "worktree", "list", "--porcelain")


@pytest.mark.skipif(os.name != "nt", reason="Windows handle/path probe")
@pytest.mark.parametrize(
    "change", ["stale", "dirty", "substitution", "junction", "digest", "remote", "config"]
)
def test_cleanup_windows_apply_rejects_changed_exact_plan(
    cleanup_case, change, tmp_path, monkeypatch
):
    config, path, _ = cleanup_case
    frozen = cleanup.plan(config)
    approved = cleanup.digest(frozen)
    if change == "stale":
        frozen["created"] -= cleanup.TTL + 1
        frozen["expires"] -= cleanup.TTL + 1
        approved = cleanup.digest(frozen)
    elif change == "dirty":
        (path / "README.md").write_text("changed")
    elif change in {"substitution", "junction"}:
        kept = tmp_path / "kept"
        path.rename(kept)
        if change == "substitution":
            git(kept, "clone", "--no-hardlinks", str(kept), str(path))
            git(path, "remote", "set-url", "origin", tool.CANONICAL_ORIGIN)
        else:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(path), str(kept)], check=True, capture_output=True
            )
    elif change == "digest":
        frozen["entries"][0]["evidence"]["head"] = "0" * 40
    elif change == "remote":
        monkeypatch.setattr(cleanup, "remote_main", lambda p: "0" * 40)
    else:
        config["entries"][0]["active"] = True
    with pytest.raises((cleanup.Hold, tool.InventoryError, OSError)):
        cleanup.apply(config, frozen, approved)
    assert path.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows locking probe")
def test_cleanup_windows_pins_reject_live_substitution_and_write(cleanup_case):
    _, path, _ = cleanup_case
    with cleanup.Pins() as pins:
        cleanup.scan(path, pins)
        with pytest.raises(OSError):
            path.rename(path.with_name("replaced"))
        with pytest.raises(OSError):
            (path / "README.md").write_text("concurrent change")


def test_cleanup_remote_failure_and_control_mismatch_refuse_plan(cleanup_case, monkeypatch):
    def unavailable(_):
        raise cleanup.Hold("remote_evidence_unavailable")

    monkeypatch.setattr(cleanup, "remote_main", unavailable)
    with pytest.raises(cleanup.Hold):
        cleanup.plan(cleanup_case[0])


def test_cleanup_root_and_runtime_entries_hold_without_scan(cleanup_case, monkeypatch):
    config, _, _ = cleanup_case
    for name in ("owner_root", "stable", "preview", "control"):
        config["entries"][0]["path"] = config[name]
        with cleanup.Pins() as pins, pytest.raises(cleanup.Hold):
            cleanup.inspect(config, config["entries"][0], pins, "0" * 40)
    config["entries"][0]["path"] = config["workspace_roots"][0]
    with cleanup.Pins() as pins, pytest.raises(cleanup.Hold):
        cleanup.inspect(config, config["entries"][0], pins, "0" * 40)


def test_cleanup_cli_frozen_local_plan_defaults_and_exclusive_output(cleanup_case):
    config, path, _ = cleanup_case
    parent = path.parent.parent
    args = argparse.Namespace(
        mode="plan",
        config=parent / "cleanup-config.json",
        plan=parent / "frozen-owner-plan.json",
        approve_sha256=None,
    )
    result = cleanup.run_cli(args)
    assert result["mode"] == "plan" and result["candidates"] == 1
    frozen = cleanup.read_json(args.plan)
    assert cleanup.digest(frozen) == result["sha256"]
    assert frozen["config"] == cleanup.portable(config)
    assert path.is_dir()
    with pytest.raises(FileExistsError):
        cleanup.run_cli(args)
    args.mode = "apply"
    with pytest.raises(cleanup.Hold, match="explicit_plan_approval_required"):
        cleanup.run_cli(args)


@pytest.mark.skipif(os.name != "nt", reason="Windows journal probe")
def test_cleanup_cli_apply_journal_and_replay_refusal(cleanup_case):
    _, path, _ = cleanup_case
    parent = path.parent.parent
    args = argparse.Namespace(
        mode="plan",
        config=parent / "cleanup-config.json",
        plan=parent / "frozen-owner-plan.json",
        approve_sha256=None,
    )
    result = cleanup.run_cli(args)
    args.mode = "apply"
    args.approve_sha256 = result["sha256"]
    assert cleanup.run_cli(args)["deleted_entries"] == [0]
    journal = args.plan.with_name(args.plan.name + ".apply.jsonl")
    assert [json.loads(line)["state"] for line in journal.read_text().splitlines()] == [
        "revalidating",
        "deleting",
        "deleted",
    ]
    with pytest.raises(FileExistsError):
        cleanup.run_cli(args)


def test_cleanup_linked_own_unique_reflog_holds(cleanup_case):
    path, _ = make_linked(cleanup_case)
    git(path, "checkout", "--detach")
    (path / "README.md").write_text("unique detached history")
    git(path, "add", "README.md")
    git(
        path,
        "-c",
        "user.name=Synthetic",
        "-c",
        "user.email=synthetic@example.com",
        "commit",
        "-qm",
        "unique",
    )
    git(path, "reset", "--hard", "main")  # synthetic fixture ONLY
    assert cleanup_row(cleanup_case)["state"] == "HOLD"


def test_cleanup_linked_unrelated_shared_refs_are_retained(cleanup_case):
    _, _, control = cleanup_case
    git(control, "checkout", "-b", "unrelated-history")
    (control / "README.md").write_text("unrelated shared history")
    git(control, "add", "README.md")
    git(
        control,
        "-c",
        "user.name=Synthetic",
        "-c",
        "user.email=synthetic@example.com",
        "commit",
        "-qm",
        "unique shared",
    )
    unique = git(control, "rev-parse", "HEAD")
    git(control, "checkout", "main")
    make_linked(cleanup_case)
    assert cleanup_row(cleanup_case)["state"] == "CANDIDATE"
    if os.name == "nt":
        config = cleanup_case[0]
        frozen = cleanup.plan(config)
        cleanup.apply(config, frozen, cleanup.digest(frozen))
        assert git(control, "rev-parse", "unrelated-history") == unique


def test_cleanup_private_scan_never_reads_contents_or_starts_git(cleanup_case, monkeypatch):
    config, path, _ = cleanup_case
    (path / ".env").write_text("synthetic secret")
    monkeypatch.setattr(cleanup, "git", lambda *a: pytest.fail("private tree started Git"))
    monkeypatch.setattr(Path, "open", lambda *a, **kw: pytest.fail("private tree read content"))
    with cleanup.Pins() as pins, pytest.raises(cleanup.Hold, match="private_marker"):
        cleanup.inspect(config, config["entries"][0], pins, "0" * 40)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction target privacy probe")
def test_cleanup_junction_does_not_open_target(cleanup_case, tmp_path, monkeypatch):
    config, path, _ = cleanup_case
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ".env").write_text("synthetic secret")
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(path / "alias"), str(outside)],
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(Path, "open", lambda *a, **kw: pytest.fail("aliased tree read content"))
    with cleanup.Pins() as pins, pytest.raises(tool.InventoryError):
        cleanup.inspect(config, config["entries"][0], pins, "0" * 40)


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_cleanup_index_flags_cannot_hide_dirty_code(cleanup_case, flag):
    _, path, _ = cleanup_case
    git(path, "update-index", flag, "README.md")
    (path / "README.md").write_text("uncommitted hidden edit")
    assert not git(path, "status", "--porcelain")  # reproduces misleading clean status
    assert cleanup_row(cleanup_case)["state"] == "HOLD"


def test_cleanup_control_grafts_refuse_before_git(cleanup_case):
    _, _, control = cleanup_case
    (control / ".git" / "info" / "grafts").write_text(git(control, "rev-parse", "HEAD") + "\n")
    with pytest.raises(cleanup.Hold):
        cleanup.plan(cleanup_case[0])


def test_cleanup_linked_per_worktree_unique_ref_holds(cleanup_case):
    path, _ = make_linked(cleanup_case)
    git(path, "checkout", "--detach")
    (path / "README.md").write_text("unique per-worktree reference")
    git(path, "add", "README.md")
    git(
        path,
        "-c",
        "user.name=Synthetic",
        "-c",
        "user.email=synthetic@example.com",
        "commit",
        "-qm",
        "unique",
    )
    unique = git(path, "rev-parse", "HEAD")
    git(path, "update-ref", "refs/worktree/retained", unique)
    git(path, "reset", "--hard", "main")  # synthetic fixture ONLY
    git(path, "reflog", "expire", "--expire=now", "--all")  # fixture removes competing proof
    assert cleanup_row(cleanup_case)["state"] == "HOLD"


@pytest.mark.skipif(os.name != "nt", reason="Windows final authorization boundary")
@pytest.mark.parametrize("phase", ["inspect", "upgrade"])
def test_cleanup_expiry_during_final_validation_never_deletes(cleanup_case, monkeypatch, phase):
    config, path, _ = cleanup_case
    frozen = cleanup.plan(config)
    approved = cleanup.digest(frozen)
    clock_value = [frozen["created"]]
    monkeypatch.setattr(cleanup.time, "time", lambda: clock_value[0])
    if phase == "inspect":
        original = cleanup.inspect

        def expired(*a, **kw):
            result = original(*a, **kw)
            clock_value[0] = frozen["expires"] + 1
            return result

        monkeypatch.setattr(cleanup, "inspect", expired)
    else:
        original = cleanup.Pins.upgrade

        def expired(*a, **kw):
            result = original(*a, **kw)
            clock_value[0] = frozen["expires"] + 1
            return result

        monkeypatch.setattr(cleanup.Pins, "upgrade", expired)
    monkeypatch.setattr(
        cleanup.Pins, "erase", lambda *a: pytest.fail("expired approval reached deletion")
    )
    with pytest.raises(cleanup.Hold, match="stale_plan"):
        cleanup.apply(config, frozen, approved)
    assert path.is_dir()


def test_cleanup_cached_stat_cannot_hide_dirty_bytes(cleanup_case):
    _, path, _ = cleanup_case
    file = path / "README.md"
    before = file.stat()
    file.write_bytes(b"x" * before.st_size)
    os.utime(file, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert cleanup_row(cleanup_case)["state"] == "HOLD"


def test_cleanup_control_common_pointer_never_executes_git(cleanup_case, tmp_path, monkeypatch):
    config, _, control = cleanup_case
    outside = tmp_path / "outside-metadata"
    outside.mkdir()
    (outside / "config").write_text("SYNTHETIC_EXTERNAL_SENTINEL")
    (control / ".git" / "commondir").write_text(str(outside))
    monkeypatch.setattr(
        cleanup, "git", lambda *a, **kw: pytest.fail("unvalidated Control started Git")
    )
    original = Path.open

    def observed(path, *a, **kw):
        assert outside not in path.parents, "external Git metadata was read"
        return original(path, *a, **kw)

    monkeypatch.setattr(Path, "open", observed)
    with pytest.raises(cleanup.Hold, match="external_or_incomplete_git"):
        cleanup.plan(config)


def test_cleanup_template_directory_never_reads_descendants(cleanup_case, monkeypatch):
    config, path, _ = cleanup_case
    directory = path / ".env.example"
    directory.mkdir()
    (directory / "ordinary-name").write_text("synthetic private content")
    monkeypatch.setattr(
        Path, "open", lambda *a, **kw: pytest.fail("template directory content was opened")
    )
    monkeypatch.setattr(
        cleanup, "git", lambda *a, **kw: pytest.fail("template directory started Git")
    )
    with cleanup.Pins() as pins, pytest.raises(cleanup.Hold, match="private_marker"):
        cleanup.inspect(config, config["entries"][0], pins, "0" * 40)


def test_cleanup_private_named_task_root_never_reads_contents(cleanup_case, monkeypatch):
    config, path, _ = cleanup_case
    private_root = path.with_name("private")
    path.rename(private_root)
    config["entries"][0]["path"] = private_root
    monkeypatch.setattr(Path, "open", lambda *a, **kw: pytest.fail("private task root was read"))
    with cleanup.Pins() as pins, pytest.raises(cleanup.Hold, match="private_marker"):
        cleanup.inspect(config, config["entries"][0], pins, "0" * 40)


def test_cleanup_remote_host_is_canonical_despite_environment(cleanup_case, monkeypatch):
    _, _, control = cleanup_case
    monkeypatch.setenv("GH_HOST", "untrusted.invalid")
    calls = []

    def run(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=b"a" * 40 + b"\n", stderr=b"")

    monkeypatch.setattr(cleanup.subprocess, "run", run)
    # Fixture replaced remote_main for offline tests; exercise the actual function.
    original_spec = importlib.util.spec_from_file_location(
        "cleanup_remote", SCRIPT.with_name("owner_workspace_cleanup.py")
    )
    remote_tool = importlib.util.module_from_spec(original_spec)
    original_spec.loader.exec_module(remote_tool)
    assert remote_tool.remote_main(control) == "a" * 40
    assert calls == [
        [
            "gh",
            "api",
            "--hostname",
            "github.com",
            "repos/LTstripes/hermes-finance/git/ref/heads/main",
            "--jq",
            ".object.sha",
        ]
    ]


def test_cleanup_frozen_template_bytes_survive_git_normalization(cleanup_case):
    config, path, control = cleanup_case
    (control / ".gitattributes").write_text("* text=auto eol=lf\n")
    (control / ".env.example").write_bytes(b"a\r\nb\n")
    git(control, "add", ".")
    git(control, "add", "--renormalize", ".")
    git(
        control,
        "-c",
        "user.name=Synthetic",
        "-c",
        "user.email=synthetic@example.com",
        "commit",
        "-qm",
        "public template",
    )
    git(control, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(path, "fetch", str(control), "main")
    git(path, "merge", "--ff-only", "FETCH_HEAD")
    template = path / ".env.example"
    template.write_bytes(b"a\r\nb\n")
    git(path, "add", ".env.example")  # fixture: refresh cached stat with unchanged normalized blob
    assert not git(path, "status", "--porcelain")
    before = template.stat()
    frozen = cleanup.plan(config)
    assert frozen["entries"][0]["state"] == "CANDIDATE"
    template.write_bytes(b"a\nb\r\n")
    os.utime(template, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert not git(path, "status", "--porcelain")  # normalization-equivalent bytes
    changed = cleanup.plan(config)
    assert changed["entries"][0]["state"] == "CANDIDATE"
    assert (
        changed["entries"][0]["evidence"]["templates"]
        != frozen["entries"][0]["evidence"]["templates"]
    )
    if os.name == "nt":
        with pytest.raises(cleanup.Hold, match="candidate_changed"):
            cleanup.apply(config, frozen, cleanup.digest(frozen))
        assert path.is_dir()
