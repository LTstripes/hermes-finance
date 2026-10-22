"""Synthetic security review regressions; no runtime, provider or real credentials.

Run normally for strict XFAIL, and with --runxfail to expose the assertions.
Only assertion failures qualify as expected: dependency/setup errors stay errors.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import io
import json
import logging
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]
pytestmark = [pytest.mark.runtime, pytest.mark.network_free]


def _script(name, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    import os
    import socket
    import sys

    for name in tuple(os.environ):
        if name.startswith(("HERMES_", "HERMES_FINANCE_")):
            monkeypatch.delenv(name)
    for name in ("TMP", "TEMP", "TMPDIR"):
        monkeypatch.setenv(name, str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    original_connect = socket.socket.connect

    def no_connect(sock, address, *args, **kwargs):
        # Python on Windows implements event-loop socketpair with private loopback sockets.
        # Permit only that stdlib call site, never a connection to an app/provider.
        caller = sys._getframe(1)
        if caller.f_code.co_name == "_fallback_socketpair" and (
            Path(caller.f_code.co_filename).name == "socket.py"
        ):
            return original_connect(sock, address, *args, **kwargs)
        pytest.fail("Security reproductions must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", no_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", no_connect)
    def no_create_connection(*args, **kwargs):
        pytest.fail("Security reproductions must not open network connections")

    monkeypatch.setattr(socket, "create_connection", no_create_connection)


def _app(tmp_path):
    from hermes_finance.api.settings import session_for_request
    from hermes_finance.main import create_app

    app = create_app(static_dir=tmp_path / "missing-frontend")
    # No database creation or migration, including during multipart dependency resolution.
    app.dependency_overrides[session_for_request] = lambda: None
    return app


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-01: ingress logs raw URL paths",
)
def test_rejected_request_does_not_log_private_filename(tmp_path, caplog):
    from fastapi.testclient import TestClient

    marker = "SYNTHETIC_ACCOUNT_statement_12345.xml"
    with caplog.at_level(logging.INFO, logger="hermes_finance.security"):
        with TestClient(_app(tmp_path), base_url="http://127.0.0.1:8000") as client:
            response = client.get(f"/api/{marker}", headers={"host": "attacker.example"})
    assert response.status_code == 400
    assert marker not in caplog.text, "Rejected private URL component entered an ingress log"


def _uvicorn_request(app, target):
    """Drive the actual HTTP protocol in memory; never bind a listening socket."""
    import uvicorn
    from uvicorn.protocols.http.h11_impl import H11Protocol
    from uvicorn.server import ServerState

    async def exchange():
        config = uvicorn.Config(app, log_config=None, lifespan="off", http="h11", loop="asyncio")
        state = ServerState()
        protocol = H11Protocol(config, state, {}, _loop=asyncio.get_running_loop())
        transport = Mock()
        transport.get_extra_info.side_effect = lambda name: {
            "peername": ("127.0.0.1", 43210),
            "sockname": ("127.0.0.1", 8000),
        }.get(name)
        transport.is_closing.return_value = False
        protocol.connection_made(transport)
        try:
            request = (
                f"GET {target} HTTP/1.1\r\n"
                "Host: 127.0.0.1:8000\r\nConnection: close\r\n\r\n"
            )
            protocol.data_received(request.encode("ascii"))
            await asyncio.gather(*tuple(state.tasks))
        finally:
            protocol.connection_lost(None)

    asyncio.run(exchange())


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-01: default access log includes query",
)
def test_default_access_log_does_not_record_private_query(tmp_path, caplog):
    marker = "SYNTHETIC_PRIVATE_AMOUNT_12345"
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        _uvicorn_request(_app(tmp_path), f"/api/health?note={marker}")
    assert any(record.name == "uvicorn.access" for record in caplog.records)
    assert marker not in caplog.text, "Default server access log retained the query value"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-01: unhandled errors log raw exception",
)
def test_unhandled_error_log_drops_financial_exception_text(tmp_path, caplog):
    app = _app(tmp_path)
    marker = "SYNTHETIC_ACCOUNT_AMOUNT_12345"

    @app.get("/api/security-review-error")
    async def fail():
        raise RuntimeError(marker)

    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        _uvicorn_request(app, "/api/security-review-error")
    assert any(record.exc_info for record in caplog.records)
    assert marker not in caplog.text, "Unhandled exception text entered server diagnostics"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-02: release error echoes remote userinfo",
)
def test_release_remote_error_redacts_credentials():
    shell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if shell is None:
        pytest.skip("PowerShell is required for the operational helper reproduction")
    # This is constructed synthetic input, never a configured Git remote.
    marker = "SYNTHETIC_" + hashlib.sha256(b"review-remote-password").hexdigest()
    remote = f"https://review-user:{marker}@github.com/LTstripes/hermes-finance.git"
    helper = str(ROOT / "scripts" / "release-lib.ps1").replace("'", "''")
    command = (
        f"$ErrorActionPreference = 'Stop'; . '{helper}'; "
        f"try {{ Test-HermesExpectedGitHubRemote -Url '{remote}'; exit 2 }} "
        "catch { [Console]::WriteLine($_.Exception.Message); exit 0 }"
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        timeout=20,
        cwd=ROOT,
    )
    if result.returncode != 0 or not result.stdout.startswith("origin does not point to"):
        raise RuntimeError("Remote-validation reproduction did not reach the intended rejection")
    assert marker not in result.stdout + result.stderr, "Remote password appeared in rejection text"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-03: file limit is after multipart spooling",
)
def test_oversized_xml_is_rejected_before_disk_spooling(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from starlette import formparsers

    from hermes_finance.statement_import.mybroker import MAX_BYTES

    rolled = []
    original = formparsers.SpooledTemporaryFile

    class ObservedSpool(original):
        def rollover(self):
            rolled.append(True)
            return super().rollover()

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", ObservedSpool)
    with TestClient(_app(tmp_path), base_url="http://127.0.0.1:8000") as client:
        response = client.post(
            "/api/mybroker-import/preview",
            files={"file": ("synthetic.xml", b"x" * (MAX_BYTES + 1), "application/xml")},
        )
    assert response.status_code == 413
    assert not rolled, "Oversized original reached disk before the route's 8 MiB check"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-04: ZIP member expanded before validation",
)
def test_compressed_recovery_manifest_rejected_before_expansion(monkeypatch):
    from hermes_finance.services import protected_backups as backups

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(backups._MANIFEST_NAME, b" " * (256 * 1024) + b"{}")
        archive.writestr(backups._SNAPSHOT_NAME, b"synthetic-not-a-database")
    reads = []
    original = zipfile.ZipFile.read

    def observed_read(self, name, *args, **kwargs):
        reads.append(name)
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "read", observed_read)
    with pytest.raises(backups.ProtectedBackupError):
        backups._verify_payload(output.getvalue())
    assert not reads, "Compressed member was expanded before enforcing the stored-only format"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-05: privacy guard misses generic passwords",
)
def test_tracked_content_guard_detects_generic_password(monkeypatch):
    checker = _script("privacy_check", monkeypatch)
    synthetic = hashlib.sha256(b"security-review-synthetic-only").hexdigest()
    payload = f'service_password = "{synthetic}"'.encode()
    assert checker.content_findings("config/service.conf", payload), (
        "Generic credential was not flagged"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-05: credential store path is permitted",
)
def test_tracked_path_guard_rejects_git_credential_store(monkeypatch):
    checker = _script("privacy_check", monkeypatch)
    # Test a path string only; never create or read a credential store.
    assert checker.forbidden_path(".git-credentials") is not None


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-05: evidence package permits nested logs",
)
def test_evidence_package_rejects_nested_diagnostic_log(tmp_path, monkeypatch):
    evidence = _script("ui_evidence_identity", monkeypatch)
    package = tmp_path / "package"
    screenshots = package / "screenshots"
    screenshots.mkdir(parents=True)
    for name in (*evidence.REQUIRED_SCREENSHOTS, "ui-v2-extra.png"):
        (screenshots / name).write_bytes(b"synthetic-image-placeholder")
    dist = package / "frontend-dist"
    dist.mkdir()
    (dist / "index.html").write_text("synthetic frontend", encoding="utf-8")
    (dist / "diagnostic.log").write_text("SYNTHETIC_ACCOUNT_AMOUNT", encoding="utf-8")
    expected = evidence.build_provenance(
        candidate_sha="1" * 40,
        base_sha="2" * 40,
        checked_out_sha="1" * 40,
        checked_out_tree="3" * 40,
        event_sha="4" * 40,
        merge_tree=None,
        run_id="1",
        run_attempt="1",
    )
    (package / "provenance.json").write_text(json.dumps(expected), encoding="utf-8")
    assert evidence.package_errors(package, expected), (
        "Nested diagnostic log passed package validation"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="SEC-06: validation response echoes input value",
)
def test_invalid_account_type_not_echoed_in_error_response(tmp_path):
    from fastapi.testclient import TestClient

    marker = "SYNTHETIC_PII"
    with TestClient(_app(tmp_path), base_url="http://127.0.0.1:8000") as client:
        response = client.post(
            "/api/accounts", json={"name": "Synthetic account", "account_type": marker}
        )
    assert response.status_code == 422
    assert marker not in response.text, "Rejected input value was copied into the error DTO"
