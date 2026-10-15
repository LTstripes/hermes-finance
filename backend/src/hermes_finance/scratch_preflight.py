"""Explicit, snapshot-bound scratch reader. Never prepares, migrates or creates data.

The manifest and runtime inventory are Owner-local declarations, not financial
attestations. Windows handles pin the existing snapshot and its directory chain;
SQLite's read-only immutable connection cannot create journals or sidecars.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

import uvicorn
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI, Request
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from starlette.responses import JSONResponse

from hermes_finance import __version__
from hermes_finance.api.mybroker_preflight import router
from hermes_finance.database import Database
from hermes_finance.persistence import Base
from hermes_finance.security import LocalhostSecurityMiddleware
from hermes_finance.services import recovery_rehearsal as safety
from hermes_finance.services.recovery_process import file_identity_token

KIND = "mybroker_preflight_scratch"
ROOT = Path(__file__).resolve().parents[3]
HEX64 = re.compile(r"[0-9a-f]{64}")


class ScratchError(RuntimeError):
    """A bounded diagnostic; never echo configuration, paths or database content."""


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ScratchError("scratch_config_invalid")
        result[key] = value
    return result


def _drive_type(root: str) -> int:
    from ctypes import wintypes

    query = ctypes.WinDLL("kernel32", use_last_error=True).GetDriveTypeW
    query.argtypes = (wintypes.LPCWSTR,)
    query.restype = wintypes.UINT
    return query(root)


def _path(value) -> Path:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ScratchError("scratch_path_invalid")
    if (
        ".." in Path(value).parts
        or value.replace("\\", "/").startswith("//")
        or (sys.platform == "win32" and any(":" in p for p in Path(value).parts[1:]))
    ):
        raise ScratchError("scratch_local_path_required")
    if sys.platform == "win32" and _drive_type(Path(value).anchor) not in {2, 3, 5, 6}:
        raise ScratchError("scratch_local_drive_required")
    return safety._absolute_path(Path(value), stage="scratch")


def _read_json(path: Path) -> dict:
    safety._assert_no_linked_components(path)
    if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > 65536:
        raise ScratchError("scratch_config_invalid")
    result = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_pairs)
    if not isinstance(result, dict):
        raise ScratchError("scratch_config_invalid")
    return result


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _prepared(checkout: Path) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        raise ScratchError("scratch_powershell_unavailable")
    # A pwsh parent may prepend PowerShell 7 modules to PSModulePath. The
    # nested Windows PowerShell Validate must load its own inbox Get-FileHash,
    # just as the established recovery-rehearsal runtime already does.
    environment = os.environ.copy()
    environment["PSModulePath"] = str(Path(powershell).resolve().parent / "Modules")
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(checkout / "scripts/prepare-runtime.ps1"),
            "-Checkout",
            str(checkout),
            "-Validate",
        ],
        env=environment,
        capture_output=True,
        timeout=90,
    )
    if result.returncode != 0:
        raise ScratchError("scratch_runtime_not_prepared")


def _interpreter(checkout: Path) -> None:
    expected = checkout / "backend/.venv"
    prefix = _path(sys.prefix)
    executable = _path(sys.executable)
    if safety._path_key(prefix) != safety._path_key(expected) or safety._path_key(
        executable
    ) != safety._path_key(expected / "Scripts/python.exe"):
        raise ScratchError("scratch_interpreter_mismatch")
    file_identity_token(executable)  # Also rejects a hardlinked launcher.


def _inventory(path: Path) -> tuple[Path, ...]:
    # Keep the reused reader's second read bound to the same immutable config.
    # Otherwise it could read newly substituted UNC paths after our syntax check.
    with _hold_snapshot(path):
        inventory = _read_json(path)
        profiles = inventory.get("profiles")
        canonical = inventory.get("canonical_production")
        if not isinstance(profiles, list) or not isinstance(canonical, dict):
            raise ScratchError("scratch_config_invalid")
        if not any(isinstance(p, dict) and p.get("type") == "preview" for p in profiles):
            raise ScratchError("scratch_test_inventory_required")
        for item in [canonical, *profiles]:
            if not isinstance(item, dict):
                raise ScratchError("scratch_config_invalid")
            for key in ("checkout", "data_dir", "database"):
                _path(item.get(key))
        return safety._runtime_inventory(path)


def _git_boundary(checkout: Path) -> None:
    git_directory = _path(str(checkout / ".git"))
    if not git_directory.is_dir():
        raise ScratchError("scratch_git_not_independent")
    for name in ("objects", "config", "HEAD"):
        _path(str(git_directory / name))
    for name in ("commondir", "objects/info/alternates"):
        if _path(str(git_directory / name)).exists():
            raise ScratchError("scratch_git_not_independent")


def _worktrees(control: Path) -> tuple[Path, ...]:
    # Same control-worktree exclusion inventory, with local syntax validated
    # before the recovery helper's filesystem normalization could follow a UNC.
    output = safety._run_git(control, ["worktree", "list", "--porcelain"], stage="scratch")
    roots = tuple(_path(line[9:]) for line in output.splitlines() if line.startswith("worktree "))
    if not roots:
        raise ScratchError("scratch_workspace_inventory_required")
    return roots


def validate_manifest(path: Path) -> dict:
    """Prove declared isolation before any SQLite connection or listener."""
    path = _path(str(path))
    document = _read_json(path)
    required = {
        "version",
        "kind",
        "profile_id",
        "checkout",
        "checkout_sha",
        "database",
        "database_identity",
        "snapshot_sha256",
        "runtime_inventory",
        "control_checkout",
        "owner_root",
        "ops_root",
        "workspace_roots",
    }
    if set(document) != required or document["version"] != 1 or document["kind"] != KIND:
        raise ScratchError("scratch_config_invalid")
    if not isinstance(document["profile_id"], str) or not re.fullmatch(
        r"[a-zA-Z0-9-]{1,64}", document["profile_id"]
    ):
        raise ScratchError("scratch_profile_invalid")
    checkout = _path(document["checkout"])
    database = _path(document["database"])
    control = _path(document["control_checkout"])
    inventory_path = _path(document["runtime_inventory"])
    if any(safety._path_is_within(p, checkout) for p in (path, inventory_path)):
        raise ScratchError("scratch_config_in_checkout")
    forbidden = list(_inventory(inventory_path))
    roots = document["workspace_roots"]
    if not isinstance(roots, list) or not roots or len(roots) > 64:
        raise ScratchError("scratch_workspace_inventory_required")
    forbidden.extend(_path(value) for value in roots)
    forbidden.extend((_path(document["owner_root"]), _path(document["ops_root"]), control))
    _git_boundary(control)
    _git_boundary(checkout)
    forbidden.extend(_worktrees(control))
    if any(
        safety._paths_overlap(candidate, boundary)
        for candidate in (checkout, database.parent)
        for boundary in forbidden
    ) or safety._paths_overlap(checkout, database.parent):
        raise ScratchError("scratch_boundary_overlap")
    if safety._path_key(checkout) != safety._path_key(ROOT):
        raise ScratchError("scratch_executing_checkout_mismatch")
    safety._validate_recovery_checkout(checkout, control, document["checkout_sha"])
    _interpreter(checkout)
    for key in ("database_identity", "snapshot_sha256"):
        if not isinstance(document[key], str) or not HEX64.fullmatch(document[key]):
            raise ScratchError("scratch_snapshot_binding_invalid")
    sidecar = _read_json(database.parent / ".hermes-data-identity.json")
    if sidecar != {"kind": KIND, "id": document["profile_id"]}:
        raise ScratchError("scratch_profile_mismatch")
    for private in (checkout / ".hermes-preview-boundary.json", checkout / ".env"):
        if private.exists():
            raise ScratchError("scratch_ambiguous_profile")
    _check_snapshot(document)
    _prepared(checkout)
    safety._validate_recovery_checkout(checkout, control, document["checkout_sha"])
    document["database"] = str(database)
    return document


def _check_snapshot(document: dict) -> None:
    path = _path(document["database"])
    if file_identity_token(path) != document["database_identity"]:
        raise ScratchError("scratch_database_identity_mismatch")
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ScratchError("scratch_snapshot_has_sidecars")
    if _digest(path) != document["snapshot_sha256"]:
        raise ScratchError("scratch_snapshot_hash_mismatch")


@contextmanager
def _hold_snapshot(path: Path):
    """Deny write/delete sharing on Windows, with ancestry rename guards."""
    with ExitStack() as stack:
        if sys.platform == "win32":
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = (
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            )
            create.restype = wintypes.HANDLE
            for parent in path.parents:
                handle, _, _ = safety._open_windows_directory(parent, deny_delete=True)
                stack.callback(safety._close_windows_handle, handle)
            handle = create(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
            if handle in (None, ctypes.c_void_p(-1).value):
                raise ScratchError("scratch_snapshot_busy")
            stack.callback(safety._close_windows_handle, handle)
            _, attributes, links = safety._windows_handle_information(int(handle))
            if attributes & 0x400 or links != 1:
                raise ScratchError("scratch_snapshot_linked")
        else:
            guard = safety._open_regular_file_guard(path)
            stack.callback(guard.close)
        yield


def _read_database(document: dict) -> Database:
    path = Path(document["database"])

    def connect():
        _check_snapshot(document)
        # Only standalone consistent snapshots are accepted above. immutable also
        # prevents sidecar creation for an offline backup whose header says WAL.
        connection = sqlite3.connect(
            path.as_uri() + "?mode=ro&immutable=1", uri=True, check_same_thread=False
        )
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        actual = connection.execute("PRAGMA database_list").fetchall()
        if len(actual) != 1 or Path(actual[0][2]).resolve() != path.resolve():
            connection.close()
            raise ScratchError("scratch_loaded_database_mismatch")
        return connection

    engine = create_engine("sqlite+pysqlite://", creator=connect, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            backend = ROOT / "backend"
            config = Config(str(backend / "alembic.ini"))
            config.set_main_option("script_location", str(backend / "migrations"))
            expected = tuple(ScriptDirectory.from_config(config).get_heads())
            actual = MigrationContext.configure(connection).get_current_heads()
            if len(expected) != 1 or tuple(actual) != expected:
                raise ScratchError("scratch_schema_head_mismatch")
            if connection.exec_driver_sql("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ScratchError("scratch_integrity_failed")
            if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
                raise ScratchError("scratch_foreign_keys_failed")
            schema = inspect(connection)
            if set(schema.get_table_names()) != set(Base.metadata.tables) | {"alembic_version"}:
                raise ScratchError("scratch_schema_drift")
            for name, table in Base.metadata.tables.items():
                if {c["name"] for c in schema.get_columns(name)} != set(table.columns.keys()):
                    raise ScratchError("scratch_schema_drift")
    except BaseException:
        engine.dispose()
        raise
    return Database(
        path, engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )


def create_reader(database: Database, document: dict, token: str) -> FastAPI:
    application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    application.state.database = database
    started = time.time_ns()

    @application.middleware("http")
    async def binding(request: Request, call_next):
        try:
            _check_snapshot(document)
            response = await call_next(request)
        except Exception:
            # SQL/configuration errors must never leak source operands or paths.
            return JSONResponse({"detail": "scratch_reader_failed_closed"}, status_code=503)
        response.headers["X-Hermes-Recovery-Token"] = token
        response.headers["X-Hermes-Recovery-Database-Identity"] = document["database_identity"]
        response.headers["X-Hermes-Recovery-Checkout-SHA"] = document["checkout_sha"]
        return response

    @application.get("/api/health")
    def health():
        return {
            "status": "ok",
            "version": __version__,
            "mode": KIND,
            "pid": os.getpid(),
            "process_started_ns": started,
            "executable": sys.executable,
            "checkout_sha": document["checkout_sha"],
            "database_identity": document["database_identity"],
        }

    application.include_router(router)
    application.add_middleware(LocalhostSecurityMiddleware)
    return application


@contextmanager
def reader_runtime(manifest: Path, token: str):
    document = validate_manifest(manifest)
    if not HEX64.fullmatch(token):
        raise ScratchError("scratch_readiness_token_invalid")
    with _hold_snapshot(Path(document["database"])):
        _check_snapshot(document)
        database = _read_database(document)
        try:
            yield create_reader(database, document, token)
        finally:
            database.engine.dispose()
            _check_snapshot(document)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ScratchError("scratch_arguments_invalid")


def main(arguments=None) -> None:
    parser = _Parser(add_help=False)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--readiness-token", required=True)
    parser.add_argument("--check", action="store_true")
    try:
        args = parser.parse_args(arguments)
        if sys.platform != "win32":
            raise ScratchError("scratch_windows_required")
        with reader_runtime(args.manifest, args.readiness_token) as application:
            if args.check:
                return
            # Reserve the actual listening socket: fail on conflicts, never probe
            # or terminate another process, and avoid a check/bind race.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                if sys.platform == "win32":
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind(("127.0.0.1", 8000))
                listener.listen(128)
                server = uvicorn.Server(
                    uvicorn.Config(application, access_log=False, log_level="error")
                )
                server.run(sockets=[listener])
    except ScratchError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
    except (Exception, KeyboardInterrupt):
        # Do not expose argparse inputs, traceback, private SQL or filesystem paths.
        print("scratch_preflight_start_failed", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
