"""Synthetic security review regressions; no runtime, provider or real credentials.

All six findings are active regressions; dependency/setup failures stay errors.
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
            request = f"GET {target} HTTP/1.1\r\nHost: 127.0.0.1:8000\r\nConnection: close\r\n\r\n"
            protocol.data_received(request.encode("ascii"))
            await asyncio.gather(*tuple(state.tasks))
        finally:
            protocol.connection_lost(None)

    asyncio.run(exchange())


def test_default_access_log_does_not_record_private_query(tmp_path, caplog):
    marker = "SYNTHETIC_PRIVATE_AMOUNT_12345"
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        _uvicorn_request(_app(tmp_path), f"/api/health?note={marker}")
    assert any(record.name == "uvicorn.access" for record in caplog.records)
    assert marker not in caplog.text, "Default server access log retained the query value"


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


def test_tracked_content_guard_detects_generic_password(monkeypatch):
    checker = _script("privacy_check", monkeypatch)
    synthetic = hashlib.sha256(b"security-review-synthetic-only").hexdigest()
    payload = f'service_password = "{synthetic}"'.encode()
    assert checker.content_findings("config/service.conf", payload), (
        "Generic credential was not flagged"
    )


def test_tracked_path_guard_rejects_git_credential_store(monkeypatch):
    checker = _script("privacy_check", monkeypatch)
    # Test a path string only; never create or read a credential store.
    assert checker.forbidden_path(".git-credentials") is not None


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


def test_invalid_account_type_not_echoed_in_error_response(tmp_path):
    from fastapi.testclient import TestClient

    marker = "SYNTHETIC_PII"
    with TestClient(_app(tmp_path), base_url="http://127.0.0.1:8000") as client:
        response = client.post(
            "/api/accounts", json={"name": "Synthetic account", "account_type": marker}
        )
    assert response.status_code == 422
    assert marker not in response.text, "Rejected input value was copied into the error DTO"


@pytest.fixture
def account_app(tmp_path):
    from hermes_finance.database import create_database
    from hermes_finance.main import create_app
    from hermes_finance.persistence import Base

    database = create_database(tmp_path / "synthetic-account.sqlite3")
    Base.metadata.create_all(database.engine)
    try:
        yield create_app(database, static_dir=tmp_path / "missing-frontend")
    finally:
        database.engine.dispose()


@pytest.mark.parametrize("field", ["account_type", "status"])
def test_account_update_validation_preserves_guidance_without_input(account_app, field):
    from fastapi.testclient import TestClient

    marker = "SYNTHETIC_PII"
    with TestClient(account_app) as client:
        account = client.post(
            "/api/accounts", json={"name": "Synthetic account", "account_type": "brokerage"}
        )
        assert account.status_code == 201
        response = client.patch(f"/api/accounts/{account.json()['id']}", json={field: marker})
    assert response.status_code == 422
    assert marker not in response.text
    assert f"unsupported account {'type' if field == 'account_type' else 'status'}" in response.text


@pytest.mark.parametrize("method", ["post", "patch"])
def test_duplicate_account_code_is_not_echoed(account_app, method):
    from fastapi.testclient import TestClient

    marker = "SYNTHETIC_PRIVATE_ACCOUNT_CODE"
    payload = {"name": "Synthetic account", "account_type": "brokerage", "external_code": marker}
    with TestClient(account_app) as client:
        assert client.post("/api/accounts", json=payload).status_code == 201
        if method == "post":
            response = client.post("/api/accounts", json=payload)
        else:
            other = client.post(
                "/api/accounts",
                json={"name": "Other synthetic account", "account_type": "brokerage"},
            )
            assert other.status_code == 201
            response = client.patch(
                f"/api/accounts/{other.json()['id']}", json={"external_code": marker}
            )
    assert response.status_code == 409
    assert marker not in response.text
    assert response.json()["error"] == {
        "code": "conflict",
        "message": "external_code already exists",
        "details": [],
    }


@pytest.mark.parametrize("length", [None, "1"])
def test_upload_stream_counter_rejects_absent_or_dishonest_length(monkeypatch, length):
    from fastapi import HTTPException
    from starlette.requests import Request

    from hermes_finance.api import uploads

    monkeypatch.setattr(uploads, "MAX_FILE_BYTES", 4)
    body = (
        b'--bound\r\nContent-Disposition: form-data; name="file"; filename="synthetic.xml"'
        b"\r\n\r\n12345\r\n--bound--\r\n"
    )
    headers = [(b"content-type", b"multipart/form-data; boundary=bound")]
    if length is not None:
        headers.append((b"content-length", length.encode()))
    chunks = iter(body[i : i + 3] for i in range(0, len(body), 3))

    async def receive():
        chunk = next(chunks, b"")
        return {"type": "http.request", "body": chunk, "more_body": bool(chunk)}

    request = Request({"type": "http", "headers": headers}, receive)
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(uploads._read_form(request))
    assert rejected.value.status_code == 413


def test_upload_content_length_rejected_before_receiving(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    from hermes_finance.api import uploads

    monkeypatch.setattr(uploads, "MAX_WIRE_BYTES", 10)

    async def receive():
        pytest.fail("Oversized Content-Length must be rejected before reading")

    request = Request(
        {
            "type": "http",
            "headers": [
                (b"content-type", b"multipart/form-data; boundary=bound"),
                (b"content-length", b"11"),
            ],
        },
        receive,
    )
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(uploads._read_form(request))
    assert rejected.value.status_code == 413


@pytest.mark.parametrize(
    "path,field",
    [
        ("/api/mybroker-import/preview", "file"),
        ("/api/statement-import/inspect", "document"),
        ("/api/broker-months/preview", "file"),
        ("/api/broker-months/intakes", "file"),
        ("/api/broker-statement-returns/preview", "file"),
        ("/api/broker-statement-what-if/context", "file"),
        ("/api/broker-statement-provisional/context", "file"),
    ],
)
def test_upload_routes_enforce_limits_before_dependency_resolution(
    tmp_path, monkeypatch, path, field
):
    from fastapi.testclient import TestClient

    from hermes_finance.api import uploads

    monkeypatch.setattr(uploads, "MAX_FILE_BYTES", 4)
    with TestClient(_app(tmp_path)) as client:
        response = client.post(path, files={field: ("synthetic.xml", b"12345", "application/xml")})
    assert response.status_code == 413
    if "what-if" in path or "provisional" in path:
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("style", ["raw", "quoted", "suffix"])
def test_validation_errors_never_echo_submitted_values(tmp_path, style):
    from fastapi.testclient import TestClient
    from pydantic import BaseModel, field_validator

    marker = "SYNTHETIC_PRIVATE_INPUT"
    app = _app(tmp_path)

    class Payload(BaseModel):
        value: str

        @field_validator("value")
        @classmethod
        def validate_value(cls, value):
            if style == "quoted":
                raise ValueError(f"unsupported value: {value!r}")
            if style == "suffix":
                raise ValueError(f"unsupported value: {value}")
            raise ValueError(value)

    def fail(payload):
        return {}

    fail.__annotations__["payload"] = Payload
    app.post("/api/security-validation")(fail)

    with TestClient(app) as client:
        response = client.post("/api/security-validation", json={"value": marker})
    assert response.status_code == 422
    assert marker not in response.text
    error = response.json()["error"]
    assert error["message"] == "Request validation failed"
    assert error["details"][0]["field"] == "value"
    assert "input" not in error["details"][0]
    assert "ctx" not in error["details"][0]
    if style != "raw":
        assert "unsupported value:" in error["details"][0]["message"]


@pytest.mark.parametrize("exception", ["value", "http", "lookup", "pydantic"])
def test_curated_error_messages_are_preserved(tmp_path, exception):
    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from pydantic import BaseModel, field_validator

    app = _app(tmp_path)
    message = "reporting month already has a salary"

    class Payload(BaseModel):
        value: str

        @field_validator("value")
        @classmethod
        def validate_value(cls, value):
            raise ValueError(message)

    if exception == "pydantic":

        def fail(payload):
            return {}

        fail.__annotations__["payload"] = Payload
        app.post("/api/security-curated")(fail)
    else:

        @app.post("/api/security-curated")
        def fail():
            if exception == "http":
                raise HTTPException(409, message)
            if exception == "lookup":
                raise LookupError(message)
            raise ValueError(message)

    with TestClient(app) as client:
        response = client.post("/api/security-curated", json={"value": "salary"})
    error = response.json()["error"]
    if exception == "pydantic":
        assert response.status_code == 422
        assert error == {
            "code": "unprocessable",
            "message": "Request validation failed",
            "details": [{"field": "value", "message": f"Value error, {message}"}],
        }
    else:
        status, code = {
            "value": (422, "unprocessable"),
            "http": (409, "conflict"),
            "lookup": (404, "not_found"),
        }[exception]
        assert response.status_code == status
        assert error == {"code": code, "message": message, "details": []}


def test_access_log_uses_template_and_omits_path_parameter(tmp_path, caplog):
    app = _app(tmp_path)
    marker = "SYNTHETIC_PRIVATE_PATH"

    @app.get("/api/security-template/{item}")
    def show(item: str):
        return {"ok": True}

    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        _uvicorn_request(app, f"/api/security-template/{marker}")
    assert marker not in caplog.text
    assert "/api/security-template/{item}" in caplog.text


@pytest.mark.parametrize("kind", ["size", "count", "duplicate", "compression"])
def test_backup_metadata_rejected_before_member_open(monkeypatch, kind):
    from hermes_finance.services import protected_backups as backups

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(backups._MANIFEST_NAME, b"{}")
        archive.writestr(backups._SNAPSHOT_NAME, b"synthetic")
        if kind == "count":
            archive.writestr("extra", b"")
        if kind == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr(backups._MANIFEST_NAME, b"{}")
    if kind == "size":
        monkeypatch.setattr(backups, "MAX_MANIFEST_BYTES", 1)
    if kind == "compression":
        original = zipfile.ZipFile.infolist

        def compressed(self):
            members = original(self)
            members[0].compress_type = zipfile.ZIP_DEFLATED
            return members

        monkeypatch.setattr(zipfile.ZipFile, "infolist", compressed)

    def no_open(*args, **kwargs):
        pytest.fail("Archive metadata must be checked before opening members")

    monkeypatch.setattr(zipfile.ZipFile, "open", no_open)
    with pytest.raises(backups.ProtectedBackupError):
        backups._verify_payload(output.getvalue())


def test_oversized_recovery_file_rejected_before_read(tmp_path, monkeypatch):
    from hermes_finance.services import protected_backups as backups
    from hermes_finance.services.archive_limits import read_bounded

    path = tmp_path / "synthetic-recovery"
    path.write_bytes(b"12345")
    with pytest.raises(ValueError, match="size limit"):
        read_bounded(path, 4)
    monkeypatch.setattr(backups, "MAX_ARTIFACT_BYTES", 4)
    with pytest.raises(backups.ProtectedBackupError):
        backups._verify_artifact_content(path)


@pytest.mark.parametrize("key", ["service_password", "service_secret", "service_token"])
def test_privacy_generic_assignments_without_known_prefixes(monkeypatch, key):
    checker = _script("privacy_check", monkeypatch)
    value = hashlib.sha256(key.encode()).hexdigest()
    assert "generic credential assignment" in checker.content_findings(
        "config/service.conf", f'{key} = "{value}"'.encode()
    )


def test_privacy_credentialed_url_without_known_token_prefix(monkeypatch):
    checker = _script("privacy_check", monkeypatch)
    value = hashlib.sha256(b"synthetic-url-value").hexdigest()
    payload = ("https://operator:" + value + "@example.com").encode()
    assert "credentialed URL" in checker.content_findings("config/service.conf", payload)


@pytest.mark.parametrize("key", ["password", "service_secret", "api_token"])
def test_privacy_bare_config_assignments(monkeypatch, key):
    checker = _script("privacy_check", monkeypatch)
    value = hashlib.sha256(key.encode()).hexdigest()
    assert "generic credential assignment" in checker.content_findings(
        "config/service.conf", f"{key}={value}".encode()
    )


def test_xlsx_member_budget_checked_before_loading(tmp_path, monkeypatch):
    from hermes_finance.services import legacy_excel

    workbook = tmp_path / "synthetic.xlsx"
    with zipfile.ZipFile(workbook, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"x" * 100)
    monkeypatch.setattr(legacy_excel, "MAX_XLSX_MEMBER_BYTES", 10)
    monkeypatch.setattr(legacy_excel, "read_legacy_month_mapping", lambda _: None)

    def no_load(*args, **kwargs):
        pytest.fail("XLSX budget must be enforced before openpyxl reads members")

    monkeypatch.setattr(legacy_excel, "load_workbook", no_load)
    with pytest.raises(ValueError, match="could not be opened"):
        legacy_excel.extract_legacy_workbook(workbook, tmp_path / "unused-mapping")


def test_recovery_source_budget_checked_before_os_read(tmp_path, monkeypatch):
    import os

    from hermes_finance.services import recovery_rehearsal as recovery

    source = tmp_path / "synthetic-artifact"
    source.write_bytes(b"12345")
    descriptor = os.open(source, os.O_RDONLY)
    monkeypatch.setattr(recovery.protected_backups, "MAX_ARTIFACT_BYTES", 4)

    def no_read(*args, **kwargs):
        pytest.fail("Source size must be checked before reading the artifact")

    monkeypatch.setattr(recovery.os, "read", no_read)
    try:
        with pytest.raises(recovery.RecoveryRehearsalError, match="size limit"):
            recovery._read_fd(descriptor)
    finally:
        os.close(descriptor)


def test_upload_disconnect_closes_all_buffers(monkeypatch):
    from starlette.requests import ClientDisconnect, Request

    from hermes_finance.api import uploads

    buffers = []
    original = uploads.BytesIO

    class ObservedBuffer(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            buffers.append(self)

    monkeypatch.setattr(uploads, "BytesIO", ObservedBuffer)
    messages = iter(
        [
            {
                "type": "http.request",
                "more_body": True,
                "body": (
                    b'--bound\r\nContent-Disposition: form-data; name="file"; filename="synthetic.xml"'
                    b"\r\n\r\n123"
                ),
            },
            {"type": "http.disconnect"},
        ]
    )

    async def receive():
        return next(messages)

    request = Request(
        {"type": "http", "headers": [(b"content-type", b"multipart/form-data; boundary=bound")]},
        receive,
    )
    with pytest.raises(ClientDisconnect):
        asyncio.run(uploads._read_form(request))
    assert buffers and all(buffer.closed for buffer in buffers)


@pytest.mark.parametrize("budget", ["headers", "files", "fields", "aggregate", "wire"])
def test_multipart_resource_budgets(monkeypatch, budget):
    from fastapi import HTTPException
    from starlette.requests import Request

    from hermes_finance.api import uploads

    parts = [
        b'--bound\r\nContent-Disposition: form-data; name="file"; filename="synthetic.xml"\r\n\r\n123',
        b'--bound\r\nContent-Disposition: form-data; name="file"; filename="synthetic2.xml"\r\n\r\n456',
        b'--bound\r\nContent-Disposition: form-data; name="intent"\r\n\r\n{}',
    ]
    body = b"\r\n".join(parts) + b"\r\n--bound--\r\n"
    setting = {
        "headers": "MAX_HEADER_BYTES",
        "files": "MAX_FILES",
        "fields": "MAX_FIELDS",
        "aggregate": "MAX_TOTAL_BYTES",
        "wire": "MAX_WIRE_BYTES",
    }[budget]
    monkeypatch.setattr(uploads, setting, 0 if budget == "fields" else 1)
    messages = iter(
        [
            {"type": "http.request", "body": body[i : i + 16], "more_body": True}
            for i in range(0, len(body), 16)
        ]
        + [{"type": "http.request", "body": b"", "more_body": False}]
    )

    async def receive():
        return next(messages)

    request = Request(
        {"type": "http", "headers": [(b"content-type", b"multipart/form-data; boundary=bound")]},
        receive,
    )
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(uploads._read_form(request))
    assert rejected.value.status_code == 413


def test_database_exception_hides_bound_parameters(tmp_path):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from hermes_finance.database import create_database

    marker = "SYNTHETIC_BOUND_VALUE"
    database = create_database(tmp_path / "synthetic.sqlite3")
    try:
        with database.engine.connect() as connection:
            with pytest.raises(DBAPIError) as rejected:
                connection.execute(text("SELECT missing_function(:value)"), {"value": marker})
        assert database.engine.hide_parameters is True
        assert marker not in str(rejected.value)
    finally:
        database.engine.dispose()


@pytest.mark.parametrize("method", ["post", "patch"])
@pytest.mark.parametrize("endpoint", ["deposits", "instruments"])
def test_sibling_enum_validation_omits_input(tmp_path, method, endpoint):
    from fastapi.testclient import TestClient

    marker = "SYNTHLEAK12345"
    field = "deposit_type" if endpoint == "deposits" else "instrument_type"
    payload = {field: marker}
    if method == "post":
        payload["name"] = "Synthetic asset"
        if endpoint == "deposits":
            payload.update(
                reporting_month_id=1,
                account_id=1,
                balance={"amount": "1.00", "currency": "RUB"},
                annual_rate="1.00",
            )
    path = f"/api/{endpoint}" + ("/1" if method == "patch" else "")
    with TestClient(_app(tmp_path)) as client:
        response = getattr(client, method)(
            path, json=payload, headers={"If-Match": "2026-01-01T00:00:00"}
        )
    assert response.status_code == 422
    assert marker not in response.text
    assert response.json()["error"]["message"] == f"unsupported {field.replace('_', ' ')}"


@pytest.mark.parametrize("exception", [ValueError, LookupError])
@pytest.mark.parametrize(
    "text",
    [
        "SYNTHETIC_PRIVATE_INPUT",
        "unsupported deposit type: SYNTHETIC_PRIVATE_INPUT",
        "reporting month already has a salary SYNTHETIC_PRIVATE_INPUT",
    ],
)
def test_generic_exceptions_do_not_echo_arbitrary_text(tmp_path, exception, text):
    from fastapi.testclient import TestClient

    app = _app(tmp_path)

    @app.get("/api/security-generic")
    def fail():
        raise exception(text)

    with TestClient(app) as client:
        response = client.get("/api/security-generic")
    assert response.status_code == (422 if exception is ValueError else 404)
    assert response.json()["error"] == {
        "code": "unprocessable" if exception is ValueError else "not_found",
        "message": "Invalid request value" if exception is ValueError else "Resource not found",
        "details": [],
    }


def test_scenario_code_is_preserved_without_arbitrary_exception_text(tmp_path):
    from fastapi.testclient import TestClient

    app = _app(tmp_path)

    @app.get("/api/scenario-lab/security-error")
    def fail():
        raise ValueError("invalid_drawdown_pct: SYNTHETIC_PRIVATE_INPUT")

    with TestClient(app) as client:
        response = client.get("/api/scenario-lab/security-error")
    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "invalid_drawdown_pct",
        "message": "Invalid request value",
        "details": [],
    }


@pytest.mark.parametrize("action", ["preview", "apply"])
@pytest.mark.parametrize("count", [32, 33])
def test_broker_money_original_file_boundary(tmp_path, monkeypatch, action, count):
    from fastapi.testclient import TestClient

    from hermes_finance.api import broker_months

    received = []

    def money(session, requested, originals, **kwargs):
        received.extend(originals)
        return {"original_count": len(originals)}

    monkeypatch.setattr(broker_months, f"{action}_money", money)
    intent = {
        "contract_version": "broker_money_v1",
        "base_request_id": "synthetic-base",
        "reporting_month_id": 1,
        "account_id": 1,
    }
    if action == "apply":
        intent.update(request_id="synthetic-apply", confirmation_digest="0" * 64)
    files = [
        (
            "file" if i == 0 else "originals",
            (f"synthetic-{i}.xml", f"<synthetic>{i}</synthetic>".encode(), "application/xml"),
        )
        for i in range(count)
    ]
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            f"/api/broker-months/{action}",
            files=files,
            data={"intent" if action == "preview" else "confirmation": json.dumps(intent)},
        )
    if count == 32:
        assert response.status_code == 200
        assert response.json() == {"original_count": 32}
        assert received == [
            (f"synthetic-{i}.xml", f"<synthetic>{i}</synthetic>".encode()) for i in range(count)
        ]
    else:
        assert response.status_code == 413
        assert response.json()["error"]["message"] == "upload_file_count_exceeded"
        assert not received


@pytest.mark.parametrize("extra", [0, 1])
def test_multipart_non_file_field_one_mib_boundary(tmp_path, extra):
    from fastapi.testclient import TestClient

    app = _app(tmp_path)
    # Valid JSON whitespace lets the actual apply route parse a full-sized field.
    selections = "[]" + " " * (1024 * 1024 - 2 + extra)
    with TestClient(app) as client:
        response = client.post(
            "/api/statement-import/apply",
            files={"document": ("synthetic.pdf", b"%PDF-synthetic", "application/pdf")},
            data={"selections": selections, "expected_document_sha256": "0" * 64},
        )
    assert response.status_code == (200 if extra == 0 else 413)
    if extra == 0:
        assert response.json()["selected_count"] == 0
    else:
        assert response.json()["error"]["message"] == "document_size_invalid"
