"""Synthetic forward-recovery protocol; real Windows sharing/rename/process probes.

Publication, installed identity and process inventory are synthetic declarations
in the service harness. No real runtime, backup or financial data is accessed.
The runtime admission/SQLite handles, migration, crash and Start are real.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest
from alembic import command

from hermes_finance import cli
from hermes_finance.database import create_database
from hermes_finance.services import forward_recovery as recovery
from hermes_finance.services import protected_backups
from hermes_finance.services import recovery_rehearsal as safety
from hermes_finance.services.database_admission import (
    AdmissionError,
    database_admission,
    fence_path,
)
from hermes_finance.services.migrations import _alembic_config, upgrade_database

ROOT = Path(__file__).resolve().parents[2]
WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="native Windows recovery protocol")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fence_precedes_cli_migration_and_database_creation(tmp_path, monkeypatch):
    database = tmp_path / "synthetic.db"
    fence_path(database).write_text("malformed fence must block too")
    before = fence_path(database).read_bytes()
    monkeypatch.setenv("HERMES_FINANCE_DATABASE_PATH", str(database))
    monkeypatch.setattr(cli, "upgrade_database", lambda *_: pytest.fail("writer was reached"))
    with pytest.raises(AdmissionError, match="fenced"):
        cli.main([])
    with pytest.raises(AdmissionError, match="fenced"):
        create_database(database)
    with pytest.raises(AdmissionError, match="fenced"):
        upgrade_database(database)
    assert not database.exists()
    assert fence_path(database).read_bytes() == before


def test_connection_open_checks_fence_after_engine_construction(tmp_path):
    path = tmp_path / "synthetic.db"
    database = create_database(path)
    fence_path(path).write_text("fenced")
    try:
        with pytest.raises(AdmissionError):
            with database.engine.connect():
                pytest.fail("connection admitted after fence")
        assert not path.exists()
    finally:
        database.engine.dispose()


def test_direct_migration_command_is_fenced_before_writer(tmp_path):
    path = tmp_path / "synthetic.db"
    fence_path(path).write_text("fenced")
    with pytest.raises(AdmissionError):
        command.upgrade(_alembic_config(path), "head")
    assert not path.exists()


@WINDOWS
@pytest.mark.parametrize("process", ["empty", "legacy_console", "hidden", "unbound_runtime"])
def test_stopped_proof_refuses_legacy_or_unknown_runtime_before_writer(tmp_path, process):
    stable = tmp_path / "synthetic-stable"
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps({"canonical_production": {"checkout": str(stable)}, "profiles": []})
    )
    payload = (
        []
        if process == "empty"
        else [
            {
                "Name": "hermes-finance-api.exe" if process == "legacy_console" else "python.exe",
                "ProcessId": 999999,
                "CommandLine": (
                    str(stable / "backend/.venv/Scripts/hermes-finance-api.exe")
                    if process == "legacy_console"
                    else None
                    if process == "hidden"
                    else "python -m hermes_finance.cli"
                ),
            }
        ]
    )
    process_file = tmp_path / "processes.json"
    process_file.write_text(json.dumps(payload))
    harness = tmp_path / "stopped-harness.ps1"
    harness.write_text("""param([string]$Script,[string]$Inventory,[string]$Processes)
$global:RecoverySyntheticRows = Get-Content -LiteralPath $Processes -Raw | ConvertFrom-Json
function global:Get-CimInstance { foreach ($row in $global:RecoverySyntheticRows) { Write-Output $row } }
& $Script -RuntimeConfig $Inventory -RecoveryPid $PID
exit $LASTEXITCODE
""")
    child = subprocess.run(
        [
            safety._powershell(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
            str(ROOT / "scripts/forward-recovery-stopped.ps1"),
            str(inventory),
            str(process_file),
        ],
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert child.returncode == (0 if process == "empty" else 1), child.stdout


@pytest.fixture(scope="module")
def old_snapshot(tmp_path_factory):
    from test_r13_00_release_verification import _seed_released_database

    path = tmp_path_factory.mktemp("synthetic-0058") / "source.db"
    _seed_released_database(path)
    command.upgrade(_alembic_config(path), recovery.OLD_REVISION)
    return path


def _online(source, target):
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()


@pytest.fixture
def profile(tmp_path, old_snapshot, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("native Windows protocol")
    stable = tmp_path / "synthetic-stable"
    data = tmp_path / "synthetic-data"
    data.mkdir()
    (stable / ".git").mkdir(parents=True)
    (stable / ".git/HEAD").write_text("synthetic future detached HEAD")
    (stable / ".hermes-runtime-prepared.json").write_text("synthetic preparation proof")
    database = data / "finance.db"
    (stable / ".env").write_text("HERMES_FINANCE_DATABASE_PATH=" + str(database) + "\n")
    from hermes_finance import scratch_preflight

    monkeypatch.setattr(scratch_preflight, "_prepared", lambda _: None)

    def synthetic_selector(root):
        from hermes_finance.settings import Settings

        value = Settings(_env_file=root / ".env").database_path.expanduser()
        return value if value.is_absolute() else root / "backend" / value

    monkeypatch.setattr(recovery, "_effective_database", synthetic_selector)
    _online(old_snapshot, database)
    upgrade_database(database)
    # Incident remains a valid supported schema, but differs from the checkpoint.
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE reporting_months SET status='draft' WHERE id=1")
    # Explicitly close, rather than relying on sqlite connection context GC.
    connection.close()
    (data / ".hermes-data-identity.json").write_text(
        json.dumps({"kind": "production", "profile_id": "stable"}, indent=2) + "\n"
    )
    identity = {"checkout": str(stable), "data_dir": str(data), "database": str(database)}
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "version": 1,
                "canonical_production": identity,
                "profiles": [{"id": "stable", "type": "stable", **identity}],
            }
        )
    )
    destination = tmp_path / "synthetic-managed"
    destination.mkdir()
    payload = old_snapshot.read_bytes()
    producer = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    # Deliberately synthetic producer; no real backup is relabeled in this test.
    monkeypatch.setattr(recovery, "OLD_SHA", producer)
    manifest = {
        "artifact_identity_sha256": "0" * 64,
        "artifact_size_bytes": 0,
        "created_at": "2035-01-02T03:04:05.000000Z",
        "format_version": 1,
        "producer_git_sha": producer,
        "protection_state": protected_backups.PROTECTION_STATE,
        "protection_mode": protected_backups.PROTECTION_MODE,
        "snapshot_sha256": hashlib.sha256(payload).hexdigest(),
        "snapshot_size_bytes": len(payload),
        "source_alembic_revisions": [recovery.OLD_REVISION],
    }
    encoded = protected_backups._artifact_bytes(old_snapshot, manifest)
    artifact = destination / (
        "hermes_recovery_20350102T030405000000Z-"
        + hashlib.sha256(encoded).hexdigest()[:16]
        + ".hermes-recovery"
    )
    artifact.write_bytes(encoded)
    proof = safety.CheckoutProof(
        ROOT, producer, "github.com/ltstripes/hermes-finance", ROOT / ".git", ROOT / ".git"
    )
    monkeypatch.setattr(recovery, "_code", lambda *_: proof)
    monkeypatch.setattr(safety, "_recheck_checkout", lambda *_args, **_kwargs: None)
    real_git = safety._run_git
    real_symbolic = safety._symbolic_head_exists
    monkeypatch.setattr(
        safety,
        "_symbolic_head_exists",
        lambda path: False if path == stable else real_symbolic(path),
    )
    monkeypatch.setattr(
        safety,
        "_run_git",
        lambda checkout, args, **kwargs: (
            (producer if args == ["rev-parse", "HEAD"] else "")
            if checkout == stable
            else real_git(checkout, args, **kwargs)
        ),
    )
    monkeypatch.setattr(recovery, "_stopped", lambda _: None)
    work = tmp_path / "transaction"
    result = recovery.qualify(
        database=database,
        artifact=artifact,
        inventory=inventory,
        checkout=ROOT,
        control=tmp_path / "control",
        selected_sha=producer,
        work=work,
        protection_state=protected_backups.PROTECTION_STATE,
        protection_mode=protected_backups.PROTECTION_MODE,
    )
    return {
        "database": database,
        "artifact": artifact,
        "inventory": inventory,
        "work": work,
        "plan": work / "plan.json",
        "before": digest(database),
        "arguments": {
            "plan_sha256": result["plan_sha256"],
            "accept_checkpoint": result["snapshot_sha256"],
        },
    }


@WINDOWS
def test_forward_recovery_preserves_incident_and_requires_separate_finish(profile):
    database, work = profile["database"], profile["work"]
    source_hash = digest(profile["artifact"])
    result = recovery.recover(profile["plan"], **profile["arguments"])
    assert result["status"] == "installed_fenced"
    assert fence_path(database).exists()
    assert digest(work / "incident.db") == profile["before"]
    assert digest(profile["artifact"]) == source_hash
    with pytest.raises(AdmissionError):
        upgrade_database(database)
    assert (
        recovery.finish(profile["plan"], **profile["arguments"])["status"]
        == "finished_start_separate"
    )
    assert not fence_path(database).exists()
    upgrade_database(database)
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT status FROM reporting_months WHERE id=1").fetchone() == (
            "closed",
        )
    finally:
        connection.close()
    old_id = (work / "incident.db").stat().st_ino
    assert recovery.recover(profile["plan"], **profile["arguments"])["status"] == "already_finished"
    assert recovery.finish(profile["plan"], **profile["arguments"])["status"] == "already_finished"
    assert (work / "incident.db").stat().st_ino == old_id


@WINDOWS
@pytest.mark.parametrize(
    "phase", ["fenced", "snapshot", "migrated", "staged", "incident", "installed", "recorded"]
)
def test_explicit_resume_after_each_mutation_boundary_never_reinstalls_incident(
    profile, monkeypatch, phase
):
    def failure(boundary):
        if boundary == phase:
            raise RuntimeError("synthetic lost worker")

    monkeypatch.setattr(recovery, "_boundary", failure)
    with pytest.raises(RuntimeError):
        recovery.recover(profile["plan"], **profile["arguments"])
    assert fence_path(profile["database"]).exists()
    with pytest.raises(AdmissionError):
        create_database(profile["database"])
    monkeypatch.setattr(recovery, "_boundary", lambda _: None)
    assert (
        recovery.recover(profile["plan"], resume=True, **profile["arguments"])["status"]
        == "installed_fenced"
    )
    assert digest(profile["work"] / "incident.db") == profile["before"]
    recovery.finish(profile["plan"], **profile["arguments"])


@WINDOWS
@pytest.mark.parametrize("phase", ["accepted", "released"])
def test_lost_finish_ack_reconciles_without_repeating_install(profile, monkeypatch, phase):
    recovery.recover(profile["plan"], **profile["arguments"])
    installed_id = profile["database"].stat().st_ino

    def failure(boundary):
        if boundary == phase:
            raise RuntimeError("synthetic lost ACK")

    monkeypatch.setattr(recovery, "_boundary", failure)
    with pytest.raises(RuntimeError):
        recovery.finish(profile["plan"], **profile["arguments"])
    monkeypatch.setattr(recovery, "_boundary", lambda _: None)
    recovery.finish(profile["plan"], **profile["arguments"])
    assert profile["database"].stat().st_ino == installed_id
    assert digest(profile["work"] / "incident.db") == profile["before"]


@WINDOWS
@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal", "-mj-synthetic"])
def test_sidecar_refusal_precedes_fence_and_preserves_family(profile, suffix):
    path = Path(str(profile["database"]) + suffix)
    path.write_bytes(b"synthetic sidecar")
    with pytest.raises(recovery.ForwardRecoveryError, match="sidecars"):
        recovery.recover(profile["plan"], **profile["arguments"])
    assert not fence_path(profile["database"]).exists()
    assert path.read_bytes() == b"synthetic sidecar"
    assert digest(profile["database"]) == profile["before"]


@WINDOWS
def test_live_writer_prevents_custody_before_fence(profile):
    connection = sqlite3.connect(profile["database"])
    try:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(recovery.ForwardRecoveryError, match="custody"):
            recovery.recover(profile["plan"], **profile["arguments"])
        assert not fence_path(profile["database"]).exists()
    finally:
        connection.close()


@WINDOWS
@pytest.mark.parametrize("record", ["accepted.json", "installed.json", "completed-fence.json"])
def test_forged_or_torn_completion_never_reports_success(profile, record):
    recovery.recover(profile["plan"], **profile["arguments"])
    recovery.finish(profile["plan"], **profile["arguments"])
    (profile["work"] / record).write_bytes(b"{}")
    with pytest.raises((recovery.ForwardRecoveryError, KeyError)):
        recovery.recover(profile["plan"], **profile["arguments"])


@WINDOWS
def test_fail_before_first_writer_excludes_other_start_even_without_listener(tmp_path):
    path = tmp_path / "synthetic.db"
    with database_admission(path, recovery=True):
        env = os.environ.copy()
        env["HERMES_FINANCE_DATABASE_PATH"] = str(path)
        child = subprocess.run(
            [sys.executable, "-I", "-c", "from hermes_finance.cli import main; main([])"],
            env=env,
            capture_output=True,
            timeout=20,
            check=False,
        )
        assert child.returncode != 0 and b"database_admission_busy" in child.stderr
        assert not path.exists()


@WINDOWS
def test_native_custody_blocks_external_writer_and_survives_handle_rename(tmp_path):
    path = tmp_path / "synthetic.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE facts(id INTEGER PRIMARY KEY)")
    connection.close()
    before = digest(path)
    with recovery.CustodyContext(path, rename=True) as guard:
        child = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import sqlite3,sys; sqlite3.connect(sys.argv[1]).execute('CREATE TABLE bad(id)')",
                str(path),
            ],
            capture_output=True,
            timeout=20,
            check=False,
        )
        assert child.returncode != 0
        guard.rename(tmp_path / "incident.db")
        assert recovery._hash(guard.read()) == before
    assert not path.exists()
    assert digest(tmp_path / "incident.db") == before


def test_runtime_outer_admission_drains_inflight_connection_borrow(tmp_path):
    from hermes_finance.services import database_admission as admission

    path = tmp_path / "synthetic.db"
    entered, leave_owner, borrowed, leave_borrow, finished = [threading.Event() for _ in range(5)]

    def owner():
        with database_admission(path):
            entered.set()
            assert leave_owner.wait(10)
        finished.set()

    def borrow():
        with database_admission(path):
            borrowed.set()
            assert leave_borrow.wait(10)

    outer = threading.Thread(target=owner)
    outer.start()
    assert entered.wait(10)
    inner = threading.Thread(target=borrow)
    inner.start()
    assert borrowed.wait(10)
    leave_owner.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with admission._registry_lock:
            if admission._owners[admission._key(path)].closing:
                break
        time.sleep(0.01)
    try:
        assert not finished.is_set()
        with pytest.raises(AdmissionError):
            with database_admission(path, recovery=True):
                pytest.fail("outer mutex released ahead of borrow")
        with pytest.raises(AdmissionError):
            with database_admission(path):
                pytest.fail("new borrow admitted during closing")
    finally:
        leave_borrow.set()
        inner.join(10)
        outer.join(10)
    assert finished.is_set()
    with database_admission(path, recovery=True):
        pass


@WINDOWS
@pytest.mark.parametrize(
    "phase",
    [
        "fenced",
        "snapshot",
        "migrated",
        "staged",
        "incident",
        "installed",
        "recorded",
        "accepted",
        "released",
    ],
)
def test_abrupt_process_exit_and_explicit_reconciliation(profile, phase):
    code = r"""
import os,sys,json
from pathlib import Path
from hermes_finance.services import forward_recovery as r, recovery_rehearsal as s
p=Path(sys.argv[1]); plan=json.loads(p.read_bytes()); phase=sys.argv[2]
root=Path(plan['checkout']); stable=Path(json.loads(Path(plan['inventory']).read_bytes())['canonical_production']['checkout'])
proof=s.CheckoutProof(root,plan['selected_sha'],'github.com/ltstripes/hermes-finance',root/'.git',root/'.git')
r.OLD_SHA=plan['selected_sha']
r._code=lambda *_:proof
s._recheck_checkout=lambda *a,**k:None
s._symbolic_head_exists=lambda *_:False
original=s._run_git
s._run_git=lambda checkout,args,**kwargs:(plan['selected_sha'] if args==['rev-parse','HEAD'] else '') if checkout==stable else original(checkout,args,**kwargs)
from hermes_finance import scratch_preflight
scratch_preflight._prepared=lambda *_:None
from hermes_finance.settings import Settings
r._effective_database=lambda root:Settings(_env_file=root/'.env').database_path.expanduser()
r._stopped=lambda *_:None
r._boundary=lambda current:os._exit(81) if current==phase else None
arguments={'plan_sha256':sys.argv[3],'accept_checkpoint':sys.argv[4]}
r.recover(p,**arguments)
if phase in ('accepted','released'):r.finish(p,**arguments)
raise RuntimeError('phase not reached')
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            code,
            str(profile["plan"]),
            phase,
            profile["arguments"]["plan_sha256"],
            profile["arguments"]["accept_checkpoint"],
        ],
        capture_output=True,
        check=False,
        timeout=40,
    )
    assert result.returncode == 81, result.stderr.decode(errors="replace")
    if phase != "released":
        assert fence_path(profile["database"]).exists()
        with pytest.raises(AdmissionError):
            upgrade_database(profile["database"])
    if phase not in ("accepted", "released"):
        recovery.recover(profile["plan"], resume=True, **profile["arguments"])
    recovery.finish(profile["plan"], **profile["arguments"])
    assert digest(profile["work"] / "incident.db") == profile["before"]
    assert not fence_path(profile["database"]).exists()


def test_schema_signature_ignores_only_constraint_order():
    a = "CREATE TABLE t (id INTEGER, name TEXT DEFAULT 'x,y', CONSTRAINT c CHECK(name IN ('x,y','z')), PRIMARY KEY(id))"
    b = "CREATE TABLE t (id INTEGER, name TEXT DEFAULT 'x,y', PRIMARY KEY(id), CONSTRAINT c CHECK(name IN ('x,y','z')))"
    assert recovery._canonical_ddl(a) == recovery._canonical_ddl(b)
    assert recovery._canonical_ddl(a) != recovery._canonical_ddl(b.replace("'z'", "'b'"))
    assert recovery._canonical_ddl(a) != recovery._canonical_ddl(b.replace("id INTEGER", "id TEXT"))


@pytest.mark.parametrize("selector", [None, "relative.db", "absolute"])
@WINDOWS
def test_effective_selector_matches_stock_backend_working_directory(
    tmp_path, monkeypatch, selector
):
    monkeypatch.delenv("HERMES_FINANCE_DATABASE_PATH", raising=False)
    stable = ROOT
    if selector is None:
        expected = stable / "data/finance.db"
    elif selector == "absolute":
        expected = tmp_path / "external.db"
        monkeypatch.setenv("HERMES_FINANCE_DATABASE_PATH", str(expected))
    else:
        expected = stable / "backend" / selector
        monkeypatch.setenv("HERMES_FINANCE_DATABASE_PATH", selector)
    assert recovery._effective_database(stable) == expected


@WINDOWS
def test_mutable_fresh_leaf_cannot_be_replaced_before_sqlite_writer(tmp_path):
    path, other = tmp_path / "stage.db", tmp_path / "other-profile.db"
    with sqlite3.connect(other) as connection:
        connection.execute("CREATE TABLE important(id INTEGER PRIMARY KEY)")
    connection.close()
    other_hash = digest(other)
    with recovery._mutable_database(path) as guard:
        child = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import os,sys; os.replace(sys.argv[1],sys.argv[2])",
                str(other),
                str(path),
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert child.returncode != 0
        guard.assert_path_identity()
        with sqlite3.connect(path) as writer:
            writer.execute("CREATE TABLE permitted(id INTEGER PRIMARY KEY)")
        writer.close()
    assert digest(other) == other_hash


@WINDOWS
def test_stage_swap_during_sealing_is_refused_before_incident_move(profile, monkeypatch):
    real = recovery._make_stage

    def swapped(*args):
        path, identity, sha = real(*args)
        kept = path.with_suffix(".retained")
        path.rename(kept)
        _online(kept, path)
        return path, identity, sha

    monkeypatch.setattr(recovery, "_make_stage", swapped)
    with pytest.raises(recovery.ForwardRecoveryError, match="sealing_changed"):
        recovery.recover(profile["plan"], **profile["arguments"])
    assert digest(profile["database"]) == profile["before"]
    assert not (profile["work"] / "incident.db").exists()
    assert fence_path(profile["database"]).exists()


@WINDOWS
def test_failed_artifact_custody_releases_live_handle(profile):
    plan = json.loads(profile["plan"].read_bytes())
    artifact = profile["artifact"]
    artifact.rename(artifact.with_suffix(".retained"))
    with pytest.raises(recovery.ForwardRecoveryError, match="custody"):
        recovery.qualify(
            database=profile["database"],
            artifact=artifact,
            inventory=profile["inventory"],
            checkout=Path(plan["checkout"]),
            control=Path(plan["control"]),
            selected_sha=plan["selected_sha"],
            work=profile["work"].with_name("second-qualification"),
            protection_state=plan["protection_state"],
            protection_mode=plan["protection_mode"],
        )
    with sqlite3.connect(profile["database"]) as writer:
        writer.execute("BEGIN IMMEDIATE")
    writer.close()
    assert digest(profile["database"]) == profile["before"]


@WINDOWS
@pytest.mark.parametrize("change", ["checkpoint", "selector", "plan", "inventory", "incident"])
def test_changed_inputs_refuse_before_operational_fence(profile, change):
    arguments = dict(profile["arguments"])
    if change == "checkpoint":
        arguments["accept_checkpoint"] = "0" * 64
    elif change == "selector":
        inventory = json.loads(profile["inventory"].read_bytes())
        (Path(inventory["canonical_production"]["checkout"]) / ".env").write_text(
            "HERMES_FINANCE_DATABASE_PATH=other.db"
        )
    elif change == "plan":
        profile["plan"].write_bytes(profile["plan"].read_bytes() + b" ")
    elif change == "inventory":
        profile["inventory"].write_bytes(profile["inventory"].read_bytes() + b" ")
    else:
        with sqlite3.connect(profile["database"]) as connection:
            connection.execute("UPDATE reporting_months SET status='closed' WHERE id=1")
        connection.close()
    with pytest.raises(recovery.ForwardRecoveryError):
        recovery.recover(profile["plan"], **arguments)
    assert not fence_path(profile["database"]).exists()
    assert not (profile["work"] / "incident.db").exists()


@WINDOWS
@pytest.mark.parametrize("target", ["live", "incident"])
def test_finish_refuses_late_sidecar_and_retains_fence(profile, target):
    recovery.recover(profile["plan"], **profile["arguments"])
    path = profile["database"] if target == "live" else profile["work"] / "incident.db"
    sidecar = Path(str(path) + "-wal")
    sidecar.write_bytes(b"synthetic late sidecar")
    with pytest.raises(recovery.ForwardRecoveryError, match="sidecars"):
        recovery.finish(profile["plan"], **profile["arguments"])
    assert fence_path(profile["database"]).exists()
    assert sidecar.read_bytes() == b"synthetic late sidecar"


@WINDOWS
@pytest.mark.parametrize("target", ["live", "incident"])
def test_finish_refuses_sidecar_after_durable_acceptance(profile, monkeypatch, target):
    recovery.recover(profile["plan"], **profile["arguments"])
    path = profile["database"] if target == "live" else profile["work"] / "incident.db"
    sidecar = Path(str(path) + "-wal")

    def inject(boundary):
        if boundary == "accepted":
            sidecar.write_bytes(b"synthetic post-ACK sidecar")

    monkeypatch.setattr(recovery, "_boundary", inject)
    with pytest.raises(recovery.ForwardRecoveryError, match="sidecars"):
        recovery.finish(profile["plan"], **profile["arguments"])
    assert (profile["work"] / "accepted.json").exists()
    assert fence_path(profile["database"]).exists()
    assert not (profile["work"] / "completed-fence.json").exists()
    assert sidecar.read_bytes() == b"synthetic post-ACK sidecar"


@WINDOWS
@pytest.mark.parametrize("phase", ["fenced", "accepted"])
def test_transaction_holds_same_fence_against_write_or_substitution(profile, monkeypatch, phase):
    fence = fence_path(profile["database"])
    if phase == "accepted":
        recovery.recover(profile["plan"], **profile["arguments"])

    def inject(boundary):
        if boundary == phase:
            with pytest.raises(PermissionError):
                fence.write_bytes(b"foreign fence")
            with pytest.raises(PermissionError):
                fence.rename(profile["work"] / "stolen-fence.json")
            raise RuntimeError("synthetic interrupted held fence")

    monkeypatch.setattr(recovery, "_boundary", inject)
    action = recovery.finish if phase == "accepted" else recovery.recover
    with pytest.raises(RuntimeError, match="interrupted held fence"):
        action(profile["plan"], **profile["arguments"])
    assert recovery._read_record(fence) == {
        "kind": recovery.KIND,
        "plan_sha256": profile["arguments"]["plan_sha256"],
    }
    assert not (profile["work"] / "stolen-fence.json").exists()
    monkeypatch.setattr(recovery, "_boundary", lambda _: None)
    if phase == "fenced":
        recovery.recover(profile["plan"], resume=True, **profile["arguments"])
    recovery.finish(profile["plan"], **profile["arguments"])
    assert not fence.exists()


@WINDOWS
def test_unavailable_volume_root_refuses_instead_of_looping(monkeypatch):
    monkeypatch.setattr(Path, "exists", lambda _: False)
    with pytest.raises(recovery.ForwardRecoveryError, match="volume_unknown"):
        recovery._volume(Path("Z:/synthetic/work"))


@WINDOWS
def test_ancestor_custody_blocks_rename_junction_redirection_of_writers(tmp_path):
    ancestor = tmp_path / "transaction-parent"
    work = ancestor / "work"
    work.mkdir(parents=True)
    external = tmp_path / "external-synthetic-profile"
    external.mkdir()
    marker = external / "preserve.txt"
    marker.write_bytes(b"preserve external synthetic profile")
    # Establish that junction creation actually works in this Windows environment.
    probe = tmp_path / "junction-probe"
    junction_command = ["cmd.exe", "/d", "/c", "mklink", "/J"]
    probe_result = subprocess.run(
        [*junction_command, str(probe), str(external)], capture_output=True, timeout=10
    )
    assert probe_result.returncode == 0, probe_result.stderr.decode(errors="replace")
    moved = tmp_path / "displaced-transaction-parent"
    assert ancestor.resolve().is_relative_to(tmp_path.resolve())
    assert moved.resolve().is_relative_to(tmp_path.resolve())
    stage, live = work / "stage.db", work / "live.db"
    with recovery._ancestors([stage, live]):
        rename = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "from pathlib import Path; import sys; Path(sys.argv[1]).rename(sys.argv[2])",
                str(ancestor),
                str(moved),
            ],
            capture_output=True,
            timeout=10,
        )
        assert rename.returncode != 0
        replacement = subprocess.run(
            [*junction_command, str(ancestor), str(external)], capture_output=True, timeout=10
        )
        assert replacement.returncode != 0
        assert not moved.exists()
        with recovery._mutable_database(stage):
            connection = sqlite3.connect(stage)
            try:
                connection.execute("CREATE TABLE synthetic(id INTEGER PRIMARY KEY)")
                connection.commit()
            finally:
                connection.close()
        with recovery.CustodyContext(stage, rename=True) as sealed:
            sealed.rename(live)
    assert live.is_file() and not stage.exists()
    assert sorted(path.name for path in external.iterdir()) == ["preserve.txt"]
    assert marker.read_bytes() == b"preserve external synthetic profile"


@WINDOWS
def test_synthetic_failure_recovery_finish_and_real_cli_start(profile):
    # Simulate a stopped failed candidate after its first migration. No listener
    # is started until explicit recovery and finish have completed.
    env = os.environ.copy()
    env["HERMES_FINANCE_DATABASE_PATH"] = str(profile["database"])
    failure = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "from hermes_finance import cli; cli.uvicorn.run=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('synthetic startup failure')); cli.main([])",
        ],
        env=env,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert failure.returncode != 0 and b"synthetic startup failure" in failure.stderr
    # Same revision startup is idempotent but SQLite may update its file header.
    # Freeze a fresh plan after the failure, as a real operator must do.
    assert digest(profile["database"]) == profile["before"]
    recovery.recover(profile["plan"], **profile["arguments"])
    recovery.finish(profile["plan"], **profile["arguments"])
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    env["HERMES_FINANCE_PORT"] = str(port)
    env["HERMES_FINANCE_HOST"] = "127.0.0.1"
    env["HERMES_FINANCE_RELOAD"] = "false"
    child = subprocess.Popen(
        [sys.executable, "-I", "-c", "from hermes_finance.cli import main; main([])"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            assert child.poll() is None
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/months", timeout=1
                ) as response:
                    months = json.load(response)
                assert months
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("synthetic stock CLI did not reach readiness")
        with pytest.raises(AdmissionError):
            recovery.recover(profile["plan"], resume=True, **profile["arguments"])
    finally:
        child.terminate()
        child.wait(timeout=15)
