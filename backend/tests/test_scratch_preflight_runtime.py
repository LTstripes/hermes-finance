"""Fabricated snapshots/configuration only; never uses an Owner database/profile."""

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import venv
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_preflight import original

from hermes_finance import cli
from hermes_finance import scratch_preflight as scratch
from hermes_finance.persistence import Base
from hermes_finance.services.recovery_process import file_identity_token

REPO = Path(__file__).resolve().parents[2]
TOKEN = "a" * 64


def snapshot_binding(path, sha="b" * 40):
    return {
        "database": str(path),
        "database_identity": file_identity_token(path),
        "snapshot_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "checkout_sha": sha,
    }


def head():
    return ScriptDirectory.from_config(Config(str(REPO / "backend/alembic.ini"))).get_heads()[0]


def stamp_fixture(path):
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(64) PRIMARY KEY)")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (head(),))
        connection.commit()


@pytest.fixture
def snapshot(tmp_path):
    from hermes_finance.database import create_database

    path = tmp_path / "synthetic.db"
    db = create_database(path)
    Base.metadata.create_all(db.engine)
    db.engine.dispose()
    stamp_fixture(path)
    return path


def files(path):
    return {str(p): p.read_bytes() for p in path.parent.iterdir() if p.is_file()}


def test_standard_path_reaches_upgrade_but_scratch_dispatch_does_not(monkeypatch, tmp_path):
    def bomb(*args, **kwargs):
        raise AssertionError("migration reached")

    monkeypatch.setattr(command, "upgrade", bomb)
    monkeypatch.setenv("HERMES_FINANCE_DATABASE_PATH", str(tmp_path / "standard.db"))
    monkeypatch.setattr(sys, "argv", ["hermes-finance-api"])
    with pytest.raises(AssertionError, match="migration reached"):
        cli.main()
    observed = []
    monkeypatch.setattr(scratch, "main", lambda args: observed.extend(args))
    monkeypatch.setattr(sys, "argv", ["hermes-finance-api", "scratch-preflight", "--manifest", "x"])
    cli.main()
    assert observed == ["--manifest", "x"]
    assert not (tmp_path / "standard.db").exists()


@pytest.mark.parametrize(
    "arguments", [["--skip-migrations"], ["scratch-prefligh"], ["--manifest", "x"]]
)
def test_unknown_mode_cannot_fall_back_to_standard_migrations(monkeypatch, arguments):
    monkeypatch.setattr(command, "upgrade", lambda *a, **kw: pytest.fail("upgrade invoked"))
    with pytest.raises(SystemExit, match="unsupported_start_mode"):
        cli.main(arguments)


def test_mode_ro_survives_query_only_cleanup_and_rejects_dml_ddl(snapshot, monkeypatch):
    monkeypatch.setattr(command, "upgrade", lambda *a, **kw: pytest.fail("migration invoked"))
    before = files(snapshot)
    db = scratch._read_database(snapshot_binding(snapshot))
    try:
        with db.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA query_only=OFF")
            for statement in (
                "CREATE TABLE forbidden (id INTEGER)",
                "DELETE FROM accounts",
                "INSERT INTO accounts (id) VALUES (99)",
            ):
                with pytest.raises(OperationalError, match="readonly"):
                    connection.execute(text(statement))
                connection.rollback()
    finally:
        db.engine.dispose()
    assert files(snapshot) == before


def test_scratch_imports_do_not_load_migration_entrypoint():
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import hermes_finance.cli; "
            "import hermes_finance.scratch_preflight; "
            "assert 'hermes_finance.services.migrations' not in sys.modules",
        ],
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    "path", [r"\\synthetic-host\share\db", "//synthetic-host/share/db", r"C:\synthetic\db:stream"]
)
def test_remote_and_stream_paths_reject_before_filesystem_access(monkeypatch, path):
    monkeypatch.setattr(
        scratch.safety, "_absolute_path", lambda *a, **kw: pytest.fail("filesystem accessed")
    )
    with pytest.raises(scratch.ScratchError):
        scratch._path(path)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file sharing and junctions")
def test_windows_snapshot_guard_denies_other_writers_and_junction(snapshot, tmp_path):
    before = files(snapshot)
    with scratch._hold_snapshot(snapshot):
        with pytest.raises(PermissionError):
            with snapshot.open("r+b"):
                pytest.fail("snapshot accepted another writer")
        with pytest.raises(PermissionError):
            snapshot.rename(tmp_path / "renamed.db")
    assert files(snapshot) == before
    target = tmp_path / "link-target"
    target.mkdir()
    junction = tmp_path / "junction"
    subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(junction), str(target)],
        check=True,
        capture_output=True,
    )
    with pytest.raises(Exception):
        scratch._path(str(junction / snapshot.name))


@pytest.mark.parametrize(
    "fault", ["missing", "corrupt", "old", "unknown", "multiple", "drift", "fk"]
)
def test_bad_snapshot_refuses_before_serving(snapshot, fault):
    if fault == "missing":
        snapshot.unlink()
        with pytest.raises(OSError):
            snapshot_binding(snapshot)
        return
    if fault == "corrupt":
        snapshot.write_bytes(b"fabricated corrupt SQLite")
    else:
        with closing(sqlite3.connect(snapshot)) as connection:
            if fault in {"old", "unknown", "multiple"}:
                connection.execute(
                    "UPDATE alembic_version SET version_num=?",
                    ("0057_broker_month_batch" if fault == "old" else "unknown",),
                )
                if fault == "multiple":
                    connection.execute("INSERT INTO alembic_version VALUES ('another')")
            elif fault == "drift":
                connection.execute("CREATE TABLE unexpected (id INTEGER)")
            else:
                connection.execute("PRAGMA foreign_keys=OFF")
                connection.execute(
                    "INSERT INTO instrument_market_mappings "
                    "(instrument_id,provider,provider_instrument_id,excluded,updated_at) "
                    "VALUES (999,'test','x',1,'2030-01-01')"
                )
            connection.commit()
    binding = snapshot_binding(snapshot)
    before = files(snapshot)
    with pytest.raises(Exception):
        scratch._read_database(binding)
    assert files(snapshot) == before


@pytest.mark.parametrize("fault", ["identity", "hash", "sidecar", "hardlink"])
def test_snapshot_binding_failures(snapshot, fault, tmp_path):
    document = snapshot_binding(snapshot)
    if fault == "identity":
        document["database_identity"] = "0" * 64
    elif fault == "hash":
        document["snapshot_sha256"] = "0" * 64
    elif fault == "sidecar":
        Path(str(snapshot) + "-wal").touch()
    else:
        os.link(snapshot, tmp_path / "alias.db")
    before = files(snapshot)
    with pytest.raises((scratch.ScratchError, OSError)):
        scratch._read_database(document)
    assert files(snapshot) == before


def test_actual_minimal_endpoint_two_accounts_missing_binding_and_no_writes(database, monkeypatch):
    path = database.database_path
    database.engine.dispose()
    stamp_fixture(path)
    document = snapshot_binding(path)
    before = files(path)
    monkeypatch.setattr(command, "upgrade", lambda *a, **kw: pytest.fail("upgrade invoked"))
    reader = scratch._read_database(document)
    try:
        app = scratch.create_reader(reader, document, TOKEN)
        originals = [
            original(trades=True),
            original(
                2,
                trades=True,
                opening="10",
                closing="12",
                opening_value="1000",
                closing_value="1200",
                cash_open="400",
                cash_close="200",
            ),
        ]
        originals += [
            (name.replace("1234567", "7654321"), raw.replace(b"1234567", b"7654321"))
            for name, raw in list(originals)
        ]
        with TestClient(app, base_url="http://127.0.0.1:8000") as client:
            assert client.get("/api/health").json()["pid"] == os.getpid()
            response = client.post(
                "/api/mybroker-preflight/preview",
                files=[("files", (name, raw, "application/xml")) for name, raw in originals],
            )
            assert response.status_code == 200, response.text
            result = response.json()
            assert len(result["documents"]) == 4 and len(result["seams"]) == 2
            assert any(d["mappings"]["state"] == "blocked" for d in result["documents"])
            assert all(
                d["statuses"]["financial_completeness"] == "unknown" for d in result["documents"]
            )
            assert result["financial_apply_available"] is False
            assert result["close_performance"] == "blocked"
            assert result["native_trade_inventory"]
            assert all(s["state"] == "equal_observations" for s in result["seams"])
            for route in (
                "/api/accounts",
                "/api/settings",
                "/api/quote-preview",
                "/api/mybroker-preflight/apply",
                "/docs",
                "/openapi.json",
                "/",
            ):
                assert client.get(route).status_code == 404
                assert client.post(route).status_code == 404
            assert (
                client.post(
                    "/api/mybroker-preflight/preview", headers={"Origin": "https://example.com"}
                ).status_code
                == 403
            )
            assert client.get("/api/health", headers={"Host": "example.com"}).status_code == 400
        with reader.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA query_only=OFF")
            with pytest.raises(OperationalError, match="readonly"):
                connection.exec_driver_sql("DELETE FROM accounts")
    finally:
        reader.engine.dispose()
    assert files(path) == before


def git(root, *args):
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={root}", *args], cwd=root, text=True, stderr=subprocess.PIPE
    ).strip()


def synthetic_layout(tmp_path, snapshot):
    checkout = tmp_path / "scratch code Кириллица"
    checkout.mkdir()
    for folder in ("backend/src", "backend/migrations", "scripts"):
        shutil.copytree(
            REPO / folder, checkout / folder, ignore=shutil.ignore_patterns("__pycache__")
        )
    for name in ("backend/pyproject.toml", "backend/alembic.ini", ".gitignore"):
        shutil.copyfile(REPO / name, checkout / name)
    (checkout / "frontend").mkdir()
    (checkout / "frontend/package.json").write_text("{}")
    # Isolate process/path tests from frontend preparation. The real validator
    # remains exercised by the existing prepared-runtime Windows suite.
    (checkout / "scripts/prepare-runtime.ps1").write_text(
        "param($Checkout,[switch]$Validate)\nexit 0\n"
    )
    git(checkout, "init")
    git(checkout, "add", ".")
    git(
        checkout,
        "-c",
        "user.name=Synthetic",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "fixture",
    )
    sha = git(checkout, "rev-parse", "HEAD")
    git(checkout, "switch", "--detach", sha)
    git(checkout, "remote", "add", "origin", "https://github.com/LTstripes/hermes-finance.git")
    control = tmp_path / "control"
    control.mkdir()
    git(control, "init")
    (control / "fixture").touch()
    git(control, "add", ".")
    git(
        control,
        "-c",
        "user.name=Synthetic",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "fixture",
    )
    git(control, "remote", "add", "origin", "https://github.com/LTstripes/hermes-finance.git")
    data = tmp_path / "scratch data Кириллица"
    data.mkdir()
    target = data / "snapshot.db"
    # Test input is a closed synthetic DB; exercise the consistent backup API.
    with (
        closing(sqlite3.connect(snapshot)) as source,
        closing(sqlite3.connect(target)) as destination,
    ):
        source.backup(destination)
    (data / ".hermes-data-identity.json").write_text(
        json.dumps({"kind": scratch.KIND, "id": "synthetic"})
    )
    protected = []
    for kind in ("stable", "preview"):
        protected.append(
            {
                "id": kind,
                "type": kind,
                "checkout": str(tmp_path / kind / "code"),
                "data_dir": str(tmp_path / kind / "data"),
                "database": str(tmp_path / kind / "data/db"),
            }
        )
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "version": 1,
                "canonical_production": {
                    k: protected[0][k] for k in ("checkout", "data_dir", "database")
                },
                "profiles": protected,
            }
        )
    )
    document = {
        "version": 1,
        "kind": scratch.KIND,
        "profile_id": "synthetic",
        "checkout": str(checkout),
        **snapshot_binding(target, sha),
        "runtime_inventory": str(inventory),
        "control_checkout": str(control),
        "owner_root": str(tmp_path / "owner"),
        "ops_root": str(tmp_path / "ops"),
        "workspace_roots": [str(tmp_path / "agents")],
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    return manifest, document


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "protected",
        "sha",
        "profile",
        "config",
        "prepared",
        "linked",
        "missing",
        "duplicate",
        "relative",
    ],
)
def test_manifest_guards_before_connection(snapshot, tmp_path, monkeypatch, fault):
    manifest, document = synthetic_layout(tmp_path, snapshot)
    checkout = Path(document["checkout"])
    monkeypatch.setattr(scratch, "ROOT", checkout)
    monkeypatch.setattr(scratch.safety, "_executing_checkout", lambda: checkout)
    monkeypatch.setattr(sys, "prefix", str(checkout / "backend/.venv"))
    monkeypatch.setattr(scratch, "_prepared", lambda c: None)
    if fault == "protected":
        document["workspace_roots"] = [document["checkout"]]
    elif fault == "sha":
        document["checkout_sha"] = "0" * 40
    elif fault == "profile":
        document["profile_id"] = "wrong"
    elif fault == "config":
        document["version"] = 999
    elif fault == "prepared":

        def fail(_):
            raise scratch.ScratchError("scratch_runtime_not_prepared")

        monkeypatch.setattr(scratch, "_prepared", fail)
    elif fault == "linked":
        os.link(Path(document["database"]), tmp_path / "linked.db")
    elif fault == "missing":
        document["database"] = str(tmp_path / "does-not-exist.db")
    elif fault == "relative":
        document["database"] = "relative.db"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    if fault == "duplicate":
        manifest.write_text('{"version":1,"version":1}', encoding="utf-8")
    monkeypatch.setattr(
        sqlite3, "connect", lambda *a, **kw: pytest.fail("connected before isolation")
    )
    if fault is None:
        assert scratch.validate_manifest(manifest) == document
    else:
        with pytest.raises(Exception):
            scratch.validate_manifest(manifest)
        assert not (tmp_path / "does-not-exist.db").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Start/process/handle integration")
@pytest.mark.parametrize("fault", [None, "port", "identity", "unprepared"])
def test_windows_guarded_start_and_cleanup(snapshot, tmp_path, monkeypatch, fault):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 8000))
        except OSError:
            pytest.skip("port already owned; never probe or stop another process")
    manifest, document = synthetic_layout(tmp_path, snapshot)
    checkout = Path(document["checkout"])
    venv.EnvBuilder().create(checkout / "backend/.venv")
    site = checkout / "backend/.venv/Lib/site-packages"
    (site / "fixture.pth").write_text(
        str(Path(sys.prefix) / "Lib/site-packages") + "\n" + str(checkout / "backend/src") + "\n",
        encoding="utf-8",
    )
    uv = tmp_path / "uv.cmd"
    uv.write_text(
        '@echo off\nchcp 65001 >nul\nshift\nshift\nshift\nshift\nshift\n"'
        + str(checkout / "backend/.venv/Scripts/python.exe")
        + '" -c "from hermes_finance.cli import main; main()" "%~1" "%~2" "%~3" "%~4" "%~5"\n',
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PATH"] = str(tmp_path) + os.pathsep + environment["PATH"]
    for key in tuple(environment):
        if key.startswith(("HERMES_FINANCE_", "UV_", "PYTHON")):
            environment.pop(key)
    held = None
    if fault == "port":
        held = socket.socket()
        held.bind(("127.0.0.1", 8000))
        held.listen()
    elif fault == "identity":
        document["database_identity"] = "0" * 64
        manifest.write_text(json.dumps(document), encoding="utf-8")
    elif fault == "unprepared":
        # Commit the synthetic validation behavior so cleanliness is not the reason.
        (checkout / "scripts/prepare-runtime.ps1").write_text(
            "param($Checkout,[switch]$Validate)\nexit 1\n"
        )
        git(checkout, "add", ".")
        git(
            checkout,
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "stale preparation",
        )
        document["checkout_sha"] = git(checkout, "rev-parse", "HEAD")
        manifest.write_text(json.dumps(document), encoding="utf-8")
    before = files(Path(document["database"]))
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(checkout / "scripts/start-local.ps1"),
                "-ScratchPreflight",
                "-ScratchManifest",
                str(manifest),
                "-ExitAfterReady",
            ],
            env=environment,
            capture_output=True,
            timeout=75,
            text=True,
        )
        assert (result.returncode == 0) == (fault is None), result.stdout + result.stderr
        assert ("is ready" in result.stdout) == (fault is None)
        assert files(Path(document["database"])) == before
    finally:
        if held:
            held.close()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 8000))  # Owned process tree must be gone.
