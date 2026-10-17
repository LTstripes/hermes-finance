"""Wholly fabricated offline UAT: containment, hard SQLite RO and Windows Start."""

import json
import os
import socket
import sqlite3
import subprocess
import sys
import venv
from contextlib import ExitStack
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from test_instrument_what_if_service import CHOSEN, A, B, setup_stock
from test_scratch_preflight_runtime import (
    TOKEN,
    files,
    git,
    snapshot_binding,
    stamp_fixture,
    synthetic_layout,
)
from test_scratch_preflight_runtime import (
    snapshot as snapshot,
)
from test_statement_import_mybroker import database as database

from hermes_finance import cli
from hermes_finance import instrument_uat as uat
from hermes_finance import scratch_preflight as scratch
from hermes_finance.database import coherent_read_snapshot
from hermes_finance.services.instrument_cash_income import known_instrument_cash_income
from hermes_finance.services.instrument_eod_observations import instrument_eod_observations
from hermes_finance.services.instrument_trades import known_instrument_trades
from hermes_finance.services.instrument_what_if import instrument_what_if

BASE = f"http://127.0.0.1:{uat.PORT}"


@pytest.fixture
def source_reader(database):
    _, stock, bond = setup_stock(database)
    database.engine.dispose()
    stamp_fixture(database.database_path)
    binding = snapshot_binding(database.database_path)
    db = scratch._read_database(binding)
    yield db, binding, stock, bond
    db.engine.dispose()


def client_for(db, binding, check=None):
    return TestClient(
        uat.create_reader(
            db,
            binding,
            TOKEN,
            {"/": (b"synthetic UAT", "text/html")},
            check or (lambda: scratch._check_snapshot(binding)),
        ),
        base_url=BASE,
    )


def test_cli_dispatch_never_imports_standard_or_calls_migration(monkeypatch):
    monkeypatch.setattr(command, "upgrade", lambda *a, **kw: pytest.fail("migration invoked"))
    monkeypatch.setattr(cli, "upgrade_database", lambda *a: pytest.fail("migrator invoked"))
    calls = []
    monkeypatch.setattr(uat, "main", lambda args: calls.append(args))
    cli.main(["instrument-uat", "--manifest", "synthetic"])
    assert calls == [["--manifest", "synthetic"]]
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import hermes_finance.instrument_uat; "
            "assert 'hermes_finance.main' not in sys.modules; "
            "assert 'hermes_finance.services.migrations' not in sys.modules",
        ],
        check=True,
        capture_output=True,
    )


def test_four_canonical_readers_parity_no_dml_and_bond_block(source_reader, monkeypatch):
    db, binding, stock, bond = source_reader
    monkeypatch.setattr(command, "upgrade", lambda *a, **kw: pytest.fail("migration invoked"))
    monkeypatch.setattr(
        socket, "create_connection", lambda *a, **kw: pytest.fail("provider network invoked")
    )
    import httpx2

    monkeypatch.setattr(
        httpx2.HTTPTransport,
        "handle_request",
        lambda *a, **kw: pytest.fail("provider HTTP invoked"),
    )
    before = files(db.database_path)
    client = client_for(db, binding)
    params = {"account_id": 1, "t0": str(A), "t1": str(B)}
    with db.session_factory() as session:
        expected = {
            "cash-income": known_instrument_cash_income(session, 1, stock, A, B),
            "eod-observations": instrument_eod_observations(session, 1, stock, A, B),
            "known-trades": known_instrument_trades(session, 1, stock, A, B),
            "conditional-return": instrument_what_if(session, 1, stock, A, B, CHOSEN, "uat"),
        }
    for route, value in expected.items():
        query = params | (
            {"request_nonce": "uat", **CHOSEN} if route == "conditional-return" else {}
        )
        response = client.get(f"/api/instruments/{stock}/{route}", params=query)
        assert response.status_code == 200, response.text
        assert response.json() == value
    result = expected["conditional-return"]
    assert result["hypothetical_result"]["conditional_result"] == "50.00"
    assert result["hypothetical_result"]["conditional_period_percent"] == "5"
    assert result["actual_instrument_return"] is None
    assert expected["known-trades"]["dependency_fingerprint"] is None
    missing = client.get(
        f"/api/instruments/{stock}/conditional-return", params=params | {"request_nonce": "missing"}
    ).json()
    assert missing["hypothetical_result"]["conditional_result"] is None
    blocked = client.get(
        f"/api/instruments/{bond}/conditional-return",
        params=params | {"request_nonce": "bond", **CHOSEN},
    ).json()
    assert "bond_dirty_basis_source_unproven" in blocked["hard_blockers"]
    assert blocked["hypothetical_result"]["conditional_result"] is None
    # Coherent snapshot cleanup explicitly turns query_only OFF; OS RO remains.
    with db.session_factory() as session:
        with coherent_read_snapshot(session):
            session.connection().exec_driver_sql("SELECT 1")
        session.connection().exec_driver_sql("PRAGMA query_only=OFF")
        for statement in ("DELETE FROM accounts", "CREATE TABLE forbidden(id)"):
            with pytest.raises(OperationalError, match="readonly"):
                session.connection().exec_driver_sql(statement)
            session.rollback()
    assert files(db.database_path) == before


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"])
def test_all_non_get_rejected_before_handler(snapshot, method):
    db = scratch._read_database(snapshot_binding(snapshot))
    try:
        client = client_for(db, snapshot_binding(snapshot))
        assert client.request(method, "/api/accounts").status_code == 405
    finally:
        db.engine.dispose()


@pytest.mark.parametrize(
    "path",
    [
        "/api/months",
        "/api/settings",
        "/api/export",
        "/api/quotes/refresh",
        "/api/instruments/1",
        "/api/instruments/1/cleanup",
        "/api/accounts/1",
        "/api/mybroker-preflight/preview",
        "/api/recovery",
        "/openapi.json",
        "/docs",
        "/v2/capital/performance",
        "/assets/main-untrusted.js",
        "/.env",
        "/%2e%2e/.env",
    ],
)
def test_no_generic_or_provider_routes(snapshot, path):
    binding = snapshot_binding(snapshot)
    db = scratch._read_database(binding)
    try:
        response = client_for(db, binding).get(path)
        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"
        assert str(snapshot) not in response.text
        assert not any("recovery" in key for key in response.headers)
    finally:
        db.engine.dispose()


def test_health_privileged_proof_and_remote_ingress(snapshot):
    binding = snapshot_binding(snapshot)
    db = scratch._read_database(binding)
    try:
        client = client_for(db, binding)
        assert client.get("/api/health").json() == {"status": "ok", "mode": uat.KIND}
        proof = client.get("/api/health", headers={"X-Hermes-Uat-Token": TOKEN}).json()
        assert proof["binding"] == uat.readiness_proof(
            TOKEN, binding, proof["pid"], proof["process_started_ns"]
        )
        assert "database_identity" not in proof and "executable" not in proof
        assert client.get("/api/accounts", headers={"Host": "evil.test"}).status_code == 400
        for origin in ("https://evil.test", "http://127.0.0.1:8000", "null"):
            assert client.get("/api/accounts", headers={"Origin": origin}).status_code == 403
        response = client.get("/api/instruments/1/conditional-return", params={"t0": str(snapshot)})
        assert response.status_code == 422
        assert str(snapshot) not in response.text
    finally:
        db.engine.dispose()


def test_failure_latches_even_after_aba(snapshot):
    binding = snapshot_binding(snapshot)
    db = scratch._read_database(binding)
    valid = [True]

    def check():
        if not valid[0]:
            raise RuntimeError("private SQL /synthetic/private/path")

    try:
        client = client_for(db, binding, check)
        assert client.get("/api/accounts").status_code == 200
        valid[0] = False
        response = client.get("/api/accounts")
        assert response.status_code == 503 and "private" not in response.text
        valid[0] = True
        assert client.get("/api/accounts").status_code == 503
    finally:
        db.engine.dispose()


def test_static_dependency_closure_rejects_main_and_traversal(tmp_path):
    dist = tmp_path / "dist"
    (dist / ".vite").mkdir(parents=True)
    (dist / "assets").mkdir()
    (dist / "instrument-uat.html").write_text("synthetic UAT")
    (dist / "assets/uat.js").write_text("// synthetic")
    manifest = dist / ".vite/manifest.json"
    chunks = {
        "instrument-uat.html": {"file": "assets/uat.js"},
        "index.html": {"file": "assets/main.js"},
    }
    manifest.write_text(json.dumps(chunks))
    with ExitStack() as stack:
        assets, _ = uat.static_bundle(dist, stack)
        assert set(assets) == {"/", "/assets/uat.js"}
    chunks["instrument-uat.html"]["file"] = "../secret.js"
    manifest.write_text(json.dumps(chunks))
    with ExitStack() as stack, pytest.raises(scratch.ScratchError):
        uat.static_bundle(dist, stack)


def test_prepared_static_is_revalidated_after_pinning(snapshot, tmp_path, monkeypatch):
    checkout = tmp_path / "code"
    dist = checkout / "frontend/dist"
    (dist / ".vite").mkdir(parents=True)
    (dist / "assets").mkdir()
    (dist / "instrument-uat.html").write_text("synthetic UAT")
    asset = dist / "assets/uat.js"
    asset.write_text("original prepared bytes")
    (dist / ".vite/manifest.json").write_text(
        json.dumps({"instrument-uat.html": {"file": "assets/uat.js"}})
    )
    manifest = tmp_path / "manifest.json"
    inventory = tmp_path / "inventory.json"
    sidecar = snapshot.parent / ".hermes-data-identity.json"
    for path in (manifest, inventory, sidecar):
        path.write_text("{}")
    document = snapshot_binding(snapshot) | {
        "checkout": str(checkout),
        "runtime_inventory": str(inventory),
        "control_checkout": str(tmp_path / "control"),
    }
    monkeypatch.setattr(scratch, "validate_manifest", lambda *a, **kw: document)
    actual_bundle = uat.static_bundle

    def replace_before_pin(dist, stack):
        asset.write_text("replaced unprepared bytes")
        return actual_bundle(dist, stack)

    monkeypatch.setattr(uat, "static_bundle", replace_before_pin)

    def prepared(checkout):
        if asset.read_text() != "original prepared bytes":
            raise scratch.ScratchError("scratch_runtime_not_prepared")

    monkeypatch.setattr(scratch, "_prepared", prepared)
    monkeypatch.setattr(
        scratch, "_read_database", lambda *a: pytest.fail("opened before prepared proof")
    )
    with pytest.raises(scratch.ScratchError, match="not_prepared"):
        with uat.reader_runtime(manifest, TOKEN):
            pytest.fail("served replaced assets")


@pytest.mark.parametrize(
    "fault", [None, "kind", "profile", "protected", "sha", "sidecar", "wal", "hardlink", "busy"]
)
def test_new_mode_manifest_reuses_physical_guards(snapshot, tmp_path, monkeypatch, fault):
    manifest, document = synthetic_layout(tmp_path, snapshot)
    checkout = Path(document["checkout"])
    document["kind"] = uat.KIND
    sidecar = Path(document["database"]).parent / ".hermes-data-identity.json"
    sidecar.write_text(json.dumps({"kind": uat.KIND, "id": "synthetic"}))
    monkeypatch.setattr(scratch, "ROOT", checkout)
    monkeypatch.setattr(scratch.safety, "_executing_checkout", lambda: checkout)
    interpreter = checkout / "backend/.venv/Scripts/python.exe"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"fabricated interpreter; never executed")
    monkeypatch.setattr(sys, "prefix", str(checkout / "backend/.venv"))
    monkeypatch.setattr(sys, "executable", str(interpreter))
    monkeypatch.setattr(scratch, "_prepared", lambda c: None)
    if fault == "kind":
        document["kind"] = scratch.KIND
    if fault == "profile":
        document["profile_id"] = "different"
    if fault == "protected":
        document["workspace_roots"] = [document["checkout"]]
    if fault == "sha":
        document["checkout_sha"] = "0" * 40
    if fault == "sidecar":
        sidecar.write_text("{}")
    if fault == "wal":
        Path(document["database"] + "-wal").touch()
    if fault == "hardlink":
        os.link(document["database"], tmp_path / "alias.db")
    manifest.write_text(json.dumps(document))
    monkeypatch.setattr(
        sqlite3, "connect", lambda *a, **kw: pytest.fail("connected before isolation")
    )
    if fault == "busy":
        if sys.platform != "win32":
            pytest.skip("Windows sharing mode")
        with open(document["database"], "r+b"), pytest.raises(scratch.ScratchError):
            with scratch._hold_snapshot(Path(document["database"])):
                pass
    elif fault is None:
        assert scratch.validate_manifest(manifest, expected_kind=uat.KIND) == document
    else:
        with pytest.raises(Exception):
            scratch.validate_manifest(manifest, expected_kind=uat.KIND)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher/process/physical boundaries")
@pytest.mark.parametrize("fault", [None, "port", "identity", "unprepared", "kind", "parent_exit"])
def test_windows_start_and_owned_cleanup(snapshot, tmp_path, fault):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", uat.PORT))
        except OSError:
            pytest.skip("port owned by another process")
    manifest, document = synthetic_layout(tmp_path, snapshot)
    checkout = Path(document["checkout"])
    document["kind"] = uat.KIND
    (Path(document["database"]).parent / ".hermes-data-identity.json").write_text(
        json.dumps({"kind": uat.KIND, "id": "synthetic"})
    )
    dist = checkout / "frontend/dist"
    (dist / ".vite").mkdir(parents=True)
    (dist / "assets").mkdir()
    (dist / "instrument-uat.html").write_text("synthetic UAT")
    (dist / "assets/uat.js").write_text("// synthetic")
    (dist / ".vite/manifest.json").write_text(
        json.dumps({"instrument-uat.html": {"file": "assets/uat.js"}})
    )
    if fault == "unprepared":
        (checkout / "scripts/prepare-runtime.ps1").write_text("exit 1\n")
    git(checkout, "add", ".")
    git(
        checkout,
        "-c",
        "user.name=Synthetic",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--allow-empty",
        "-m",
        "UAT fixture",
    )
    document["checkout_sha"] = git(checkout, "rev-parse", "HEAD")
    venv.EnvBuilder().create(checkout / "backend/.venv")
    site = checkout / "backend/.venv/Lib/site-packages"
    (site / "fixture.pth").write_text(
        str(Path(sys.prefix) / "Lib/site-packages") + "\n" + str(checkout / "backend/src") + "\n",
        encoding="utf-8",
    )
    if fault == "identity":
        document["database_identity"] = "0" * 64
    if fault == "kind":
        document["kind"] = scratch.KIND
    manifest.write_text(json.dumps(document))
    before = files(Path(document["database"]))
    held = socket.socket() if fault == "port" else None
    if held:
        held.bind(("127.0.0.1", uat.PORT))
        held.listen()
    try:
        arguments = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(checkout / "scripts/start-instrument-uat.ps1"),
            "-Manifest",
            str(manifest),
        ]
        if fault == "parent_exit":
            import time
            import urllib.request

            process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    try:
                        with urllib.request.urlopen(BASE + "/api/health", timeout=1) as response:
                            assert json.load(response)["mode"] == uat.KIND
                            break
                    except OSError:
                        time.sleep(0.2)
                else:
                    pytest.fail("owned UAT did not start")
                # Kill only the exact spawned outer launcher handle. Kernel Job
                # close must clean the listener even without PowerShell finally.
                process.kill()
                process.wait(timeout=5)
                deadline = time.monotonic() + 5
                while True:
                    with socket.socket() as probe:
                        try:
                            probe.bind(("127.0.0.1", uat.PORT))
                            break
                        except OSError:
                            if time.monotonic() >= deadline:
                                pytest.fail("listener escaped parent Job")
                            time.sleep(0.1)
                assert files(Path(document["database"])) == before
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)
            return
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(checkout / "scripts/start-instrument-uat.ps1"),
                "-Manifest",
                str(manifest),
                "-ExitAfterReady",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert (result.returncode == 0) == (fault is None), result.stdout + result.stderr
        assert ("is ready" in result.stdout) == (fault is None)
        assert files(Path(document["database"])) == before
    finally:
        if held:
            held.close()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", uat.PORT))
