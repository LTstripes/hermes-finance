"""One offline 0058 -> selected-head recovery transaction on local Windows NTFS.

No Start, code switch, downgrade, raw DB copy, API-restore override or OPS02.
An explicit finish reconciles identities before retiring the durable fence.
All transaction artifacts remain local and are retained, including failed stages.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path

from alembic import command

from hermes_finance.services import protected_backups
from hermes_finance.services import recovery_rehearsal as safety
from hermes_finance.services.database_admission import database_admission, fence_path
from hermes_finance.services.migrations import _alembic_config, upgrade_database

OLD_REVISION = "0058_broker_money_ownership"
OLD_SHA = "a9c88266fffe26e83688c52fc8f425b04fa14812"
ROOT = Path(__file__).resolve().parents[4]
KIND = "hermes_forward_recovery_v1"


class ForwardRecoveryError(RuntimeError):
    """Bounded, non-path-bearing operational diagnostic."""


def _boundary(phase: str) -> None:
    """Phase seam for crash tests; no environment-controlled fault injection."""


def _json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _path(value: str | Path) -> Path:
    # Use O4's local path/link checks; do not resolve away a linked component.
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or str(path).startswith(("\\\\", "//")):
        raise ForwardRecoveryError("recovery_local_absolute_path_required")
    if sys.platform == "win32" and any(":" in part for part in path.parts[1:]):
        raise ForwardRecoveryError("recovery_path_invalid")
    safety._assert_no_linked_components(path)
    return path


def _sidecar_free(path: Path) -> None:
    # Deliberately reject any SQLite-family suffix, including super-journals.
    if any(path.parent.glob(path.name + "-*")):
        raise ForwardRecoveryError("recovery_sqlite_sidecars_present")


def _native() -> None:
    if sys.platform != "win32":
        raise ForwardRecoveryError("recovery_requires_windows_ntfs")


def _volume(path: Path) -> int:
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    while not path.exists():
        if path.parent == path:
            raise ForwardRecoveryError("recovery_volume_unknown")
        path = path.parent
    root = ctypes.create_unicode_buffer(32768)
    get_path = kernel.GetVolumePathNameW
    get_path.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    get_path.restype = wintypes.BOOL
    if not get_path(str(path), root, len(root)):
        raise ForwardRecoveryError("recovery_volume_unknown")
    drive_type = kernel.GetDriveTypeW
    drive_type.argtypes = (wintypes.LPCWSTR,)
    drive_type.restype = wintypes.UINT
    fs = ctypes.create_unicode_buffer(64)
    serial = wintypes.DWORD()
    info = kernel.GetVolumeInformationW
    info.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.LPWSTR,
        wintypes.DWORD,
    )
    info.restype = wintypes.BOOL
    if (
        drive_type(root.value) != 3
        or not info(root.value, None, 0, ctypes.byref(serial), None, None, fs, len(fs))
        or fs.value != "NTFS"
    ):
        raise ForwardRecoveryError("recovery_local_fixed_ntfs_required")
    return int(serial.value)


def _same_volume(database: Path, work: Path) -> None:
    if _volume(database) != _volume(work):
        raise ForwardRecoveryError("recovery_same_volume_required")


def _stopped(inventory: Path) -> None:
    environment = os.environ.copy()
    environment["PSModulePath"] = str(Path(safety._powershell()).resolve().parent / "Modules")
    completed = subprocess.run(
        [
            safety._powershell(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts/forward-recovery-stopped.ps1"),
            "-RuntimeConfig",
            str(inventory),
            "-RecoveryPid",
            str(os.getpid()),
        ],
        capture_output=True,
        timeout=30,
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        raise ForwardRecoveryError("recovery_runtime_stopped_unproven")


@contextmanager
def _bindings_held(plan):
    inventory = Path(plan["inventory"])
    database = Path(plan["database"])
    parsed = json.loads(inventory.read_text(encoding="utf-8"))
    stable = Path(parsed["canonical_production"]["checkout"])
    paths = [
        inventory,
        database.parent / ".hermes-data-identity.json",
        stable / ".git/HEAD",
        stable / ".hermes-runtime-prepared.json",
    ]
    if (stable / ".env").exists():
        paths.append(stable / ".env")
    with (
        _ancestors([*paths, Path(plan["artifact"]), Path(plan["work"]) / "x"]),
        ExitStack() as stack,
    ):
        guards = [stack.enter_context(CustodyContext(path)) for path in paths]
        hashes = [_hash(guard.read()) for guard in guards]

        def recheck():
            if [_hash(guard.read()) for guard in guards] != hashes:
                raise ForwardRecoveryError("recovery_binding_changed")
            if hashes[0] != plan["inventory_sha256"]:
                raise ForwardRecoveryError("recovery_inventory_changed")
            _binding(inventory, database, Path(plan["checkout"]), plan["selected_sha"])

        recheck()
        yield recheck
        recheck()


class Custody:
    """Deny outside writes/deletes; own DELETE access enables handle-bound rename.

    SQLite inspections deserialize bytes read through this handle in memory.
    They never reopen a DELETE-owned DB by path or process a live journal.
    """

    def __init__(self, path: Path, *, rename: bool = False):
        from ctypes import wintypes

        _native()
        self.path = _path(path)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = self.kernel.CreateFileW
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
        self.handle = create(
            str(path), 0x80000000 | (0x10000 if rename else 0), 1, None, 3, 0x00200000, None
        )
        if self.handle in (None, ctypes.c_void_p(-1).value):
            raise ForwardRecoveryError("recovery_file_custody_unavailable")
        try:
            self.identity, attributes, links = safety._windows_handle_information(self.handle)
            if attributes & 0x400 or links != 1:
                raise ForwardRecoveryError("recovery_linked_file")
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self) -> None:
        safety._assert_regular_leaf_identity(self.path, self.identity)
        identity, attributes, links = safety._windows_handle_information(self.handle)
        if identity != self.identity or attributes & 0x400 or links != 1:
            raise ForwardRecoveryError("recovery_file_identity_changed")

    def read(self) -> bytes:
        self.check()
        if self.path.stat().st_size > protected_backups.MAX_ARTIFACT_BYTES:
            raise ForwardRecoveryError("recovery_file_budget_exceeded")
        return protected_backups._win_read_handle(self.handle)

    def rename(self, destination: Path) -> None:
        from ctypes import wintypes

        self.check()
        _path(destination)
        if os.path.lexists(destination):
            raise ForwardRecoveryError("recovery_destination_exists")

        class RenameInformation(ctypes.Structure):
            _fields_ = [
                ("replace", wintypes.BOOL),
                ("root", wintypes.HANDLE),
                ("length", wintypes.DWORD),
                ("name", wintypes.WCHAR * 1),
            ]

        name = str(destination).encode("utf-16-le")
        # Supply a zero-terminated, fully sized FILE_RENAME_INFO allocation too;
        # do not let native Win32 filename handling read beyond a flexible tail.
        size = max(ctypes.sizeof(RenameInformation), RenameInformation.name.offset + len(name) + 2)
        buffer = ctypes.create_string_buffer(size)
        info = ctypes.cast(buffer, ctypes.POINTER(RenameInformation)).contents
        info.replace = False  # never overwrite an unexpected file
        info.root = None
        info.length = len(name)
        ctypes.memmove(ctypes.addressof(buffer) + RenameInformation.name.offset, name, len(name))
        rename = self.kernel.SetFileInformationByHandle
        rename.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        rename.restype = wintypes.BOOL
        if not rename(self.handle, 3, buffer, size):
            raise ForwardRecoveryError(
                "recovery_handle_rename_failed_" + str(ctypes.get_last_error())
            )
        self.path = destination
        self.check()

    def close(self) -> None:
        safety._close_windows_handle(self.handle)


@contextmanager
def _ancestors(paths):
    with ExitStack() as stack:
        pinned = {}
        for path in paths:
            for parent in reversed(path.parents):
                key = str(parent).casefold()
                if key not in pinned:
                    _path(parent)
                    handle, identity, _ = safety._open_windows_directory(parent, deny_delete=True)
                    stack.callback(safety._close_windows_handle, handle)
                    pinned[key] = (parent, identity)
        # Handles deny ancestor rename/delete without O4's ADS mutation.
        yield
        for parent, identity in pinned.values():
            if safety._file_identity(parent.stat()) != identity:
                raise ForwardRecoveryError("recovery_ancestor_identity_changed")


def _record(path: Path, value) -> None:
    _path(path)
    payload = _json(value)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def _mutable_database(path: Path):
    """Own the fresh leaf from CREATE_NEW through all RW SQLite reopens."""
    _path(path)
    descriptor = safety._create_windows_exclusive_leaf(path, deny_delete=True)
    try:
        identity = safety._file_identity(os.fstat(descriptor))
        if identity is None:
            raise ForwardRecoveryError("recovery_created_identity_unknown")
        guard = safety._RegularFileGuard(path, identity, descriptor=descriptor)
        guard.assert_path_identity()
        yield guard
        guard.assert_path_identity()
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _mutable_hash(guard) -> str:
    guard.assert_path_identity()
    result = safety._sha256_fd(guard.descriptor)
    guard.assert_path_identity()
    return result


def _reference(path: Path, revision: str) -> str:
    with _mutable_database(path) as guard:
        command.upgrade(_alembic_config(path), revision)
        guard.assert_path_identity()
        _sidecar_free(path)
        # This guard allows writes but excludes pathname substitution. SQLite has
        # finished and the sealed identity/hash transition below excludes later drift.
        expected_id, expected_hash = guard.identity, _mutable_hash(guard)
    with CustodyContext(path) as sealed:
        if sealed.identity != expected_id or _hash(sealed.read()) != expected_hash:
            raise ForwardRecoveryError("recovery_reference_changed")
        with _memory(sealed.read()) as connection:
            return _signature(connection)


def _read_record(path: Path):
    with CustodyContext(path) as guard:
        return _guard_record(guard)


def _guard_record(guard: Custody):
    raw = guard.read()
    if len(raw) > 1024 * 1024:
        raise ForwardRecoveryError("recovery_record_budget_exceeded")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ForwardRecoveryError("recovery_record_ambiguous") from None
    if not isinstance(result, dict) or _json(result) != raw:
        raise ForwardRecoveryError("recovery_record_ambiguous")
    return result


@contextmanager
def _memory(payload: bytes):
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(payload)
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ForwardRecoveryError("recovery_integrity_failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ForwardRecoveryError("recovery_foreign_keys_failed")
        yield connection
    finally:
        connection.close()


def _canonical_ddl(sql: str | None) -> str | None:
    """Sort only table-level constraints; preserve every expression and column.

    Alembic batch reflection iterates SQLAlchemy constraint sets in process hash
    order. Literal sqlite_schema SQL therefore is not a stable release signature.
    Quotes and nested parentheses keep commas inside CHECK/DEFAULT intact.
    """
    if sql is None or not sql.upper().startswith("CREATE TABLE"):
        return sql
    opening, closing = sql.find("("), sql.rfind(")")
    if opening < 0 or closing < opening:
        raise ForwardRecoveryError("recovery_schema_sql_invalid")
    parts, start, depth, quote, index = [], opening + 1, 0, None, opening + 1
    while index < closing:
        character = sql[index]
        if quote is not None:
            if character == quote:
                if index + 1 < closing and sql[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif character in "'\"`[":
            quote = "]" if character == "[" else character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(sql[start:index].strip())
            start = index + 1
        index += 1
    if quote is not None or depth:
        raise ForwardRecoveryError("recovery_schema_sql_invalid")
    parts.append(sql[start:closing].strip())
    constraints = (
        "CONSTRAINT ",
        "PRIMARY KEY",
        "FOREIGN KEY",
        "UNIQUE ",
        "UNIQUE(",
        "CHECK ",
        "CHECK(",
    )
    columns = [part for part in parts if not part.upper().startswith(constraints)]
    ordered = sorted(part for part in parts if part.upper().startswith(constraints))
    return sql[: opening + 1] + ",".join([*columns, *ordered]) + sql[closing:]


def _signature(connection) -> str:
    rows = connection.execute(
        "SELECT type,name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ).fetchall()
    return _hash(_json([(kind, name, _canonical_ddl(sql)) for kind, name, sql in rows]))


def _revision(connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT version_num FROM alembic_version ORDER BY version_num"
        )
    ]


def _logical(connection, projection=None):
    if projection is None:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name <> 'alembic_version' ORDER BY name"
            )
        ]
        projection = {
            table: [
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(" + safety._quote_identifier(table) + ")"
                )
            ]
            for table in tables
        }
    result = {}
    for table, columns in projection.items():
        sql = "SELECT " + ",".join(map(safety._quote_identifier, columns))
        sql += " FROM " + safety._quote_identifier(table)
        hashes = sorted(_hash(repr(row).encode("utf-8")) for row in connection.execute(sql))
        result[table] = {"columns": columns, "count": len(hashes), "sha256": _hash(_json(hashes))}
    return result


def _code(checkout: Path, control: Path, sha: str):
    from hermes_finance import __version__
    from hermes_finance.scratch_preflight import _interpreter

    if sys.flags.isolated != 1:
        raise ForwardRecoveryError("recovery_isolated_interpreter_required")
    _interpreter(checkout)
    proof = safety._validate_recovery_checkout(checkout, control, sha)
    environment = os.environ.copy()
    environment["PSModulePath"] = str(Path(safety._powershell()).resolve().parent / "Modules")
    completed = subprocess.run(
        [
            safety._powershell(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(checkout / "scripts/forward-recovery-release-proof.ps1"),
            "-Checkout",
            str(checkout),
            "-ExpectedSha",
            sha,
            "-Version",
            __version__,
        ],
        capture_output=True,
        timeout=120,
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        raise ForwardRecoveryError("recovery_published_prepared_code_required")
    return proof


def _binding(inventory: Path, database: Path, checkout: Path, sha: str) -> None:
    from hermes_finance.scratch_preflight import _prepared

    boundaries = safety._runtime_inventory(inventory)
    document = json.loads(inventory.read_text(encoding="utf-8"))
    canonical = document["canonical_production"]
    if _path(canonical["database"]) != database or _path(canonical["data_dir"]) != database.parent:
        raise ForwardRecoveryError("recovery_production_binding_mismatch")
    stable = _path(canonical["checkout"])
    if safety._paths_overlap(stable, checkout):
        raise ForwardRecoveryError("recovery_code_not_independent")
    if safety._symbolic_head_exists(stable):
        raise ForwardRecoveryError("recovery_stable_detached_head_required")
    if safety._run_git(stable, ["rev-parse", "HEAD"], stage="recovery") != sha:
        raise ForwardRecoveryError("recovery_stable_code_mismatch")
    if safety._run_git(
        stable, ["status", "--porcelain=v1", "--untracked-files=all"], stage="recovery"
    ):
        raise ForwardRecoveryError("recovery_stable_code_dirty")
    sidecar = database.parent / ".hermes-data-identity.json"
    with CustodyContext(sidecar) as guard:
        identity = json.loads(guard.read())
    if identity.get("kind") != "production" or identity.get("profile_id") != "stable":
        raise ForwardRecoveryError("recovery_production_identity_missing")
    _prepared(stable)
    if _effective_database(stable) != database:
        raise ForwardRecoveryError("recovery_effective_database_mismatch")
    for boundary in boundaries[3:]:
        if boundary not in (stable, database.parent, database) and safety._paths_overlap(
            database, boundary
        ):
            raise ForwardRecoveryError("recovery_conflicting_profile")


def _effective_database(stable: Path) -> Path:
    from hermes_finance.services.recovery_process import file_identity_token

    interpreter = _path(stable / "backend/.venv/Scripts/python.exe")
    file_identity_token(interpreter)
    # Exact installed Settings, interpreter and stock Start WorkingDirectory.
    # Only the selector is returned; .env credentials never leave the child.
    code = (
        "import json,sys; from pathlib import Path; "
        "from hermes_finance.settings import Settings,REPOSITORY_ROOT; "
        "root=Path(sys.argv[1]); "
        "assert REPOSITORY_ROOT.resolve()==root.resolve(); "
        "assert Path(sys.prefix).resolve()==(root/'backend/.venv').resolve(); "
        "print(json.dumps(str(Settings().database_path.expanduser().resolve())))"
    )
    completed = subprocess.run(
        [str(interpreter), "-I", "-c", code, str(stable)],
        cwd=stable / "backend",
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode or len(completed.stdout) > 32768:
        raise ForwardRecoveryError("recovery_effective_selector_unproven")
    return _path(json.loads(completed.stdout))


def _source(plan):
    source = safety._verify_source(
        Path(plan["artifact"]),
        protection_state=plan["protection_state"],
        protection_mode=plan["protection_mode"],
    )
    if (
        source.artifact_sha256 != plan["artifact_sha256"]
        or source.manifest["snapshot_sha256"] != plan["snapshot_sha256"]
        or source.manifest["producer_git_sha"] != OLD_SHA
        or source.manifest["source_alembic_revisions"] != [OLD_REVISION]
    ):
        source.close()
        raise ForwardRecoveryError("recovery_source_identity_mismatch")
    return source


def qualify(
    *,
    database: Path,
    artifact: Path,
    inventory: Path,
    checkout: Path,
    control: Path,
    selected_sha: str,
    work: Path,
    protection_state: str,
    protection_mode: str,
) -> dict:
    """Explicit isolated preparation; does not fence, change or migrate live DB.

    Writes only a fresh disjoint qualification directory. Its returned plan digest
    must be supplied separately at execution together with checkpoint acceptance.
    """
    _native()
    database, artifact, inventory, checkout, control, work = map(
        _path, (database, artifact, inventory, checkout, control, work)
    )
    proof = _code(checkout, control, selected_sha)
    _binding(inventory, database, checkout, selected_sha)
    _same_volume(database, work)
    _volume(artifact)
    forbidden = (*safety._runtime_inventory(inventory), checkout, control, artifact.parent)
    if work.exists() or any(safety._paths_overlap(work, path) for path in forbidden):
        raise ForwardRecoveryError("recovery_qualification_boundary_invalid")
    with database_admission(database, recovery=True), _ancestors([database, artifact, work]):
        _stopped(inventory)
        if os.path.lexists(fence_path(database)):
            raise ForwardRecoveryError("recovery_existing_transaction")
        _sidecar_free(database)
        live = Custody(database, rename=True)
        source_guard = None
        try:
            source_guard = Custody(artifact)
            _sidecar_free(database)
            live_bytes = live.read()
            with _memory(live_bytes) as live_db:
                live_revisions = _revision(live_db)
                live_signature = _signature(live_db)
            source = safety._verify_source(
                artifact, protection_state=protection_state, protection_mode=protection_mode
            )
            try:
                safety._assert_source_outside_forbidden(
                    source, (*safety._runtime_inventory(inventory), checkout, control)
                )
                protected_backups._assert_outside_git_boundaries(artifact)
                if source.manifest["producer_git_sha"] != OLD_SHA or source.manifest[
                    "source_alembic_revisions"
                ] != [OLD_REVISION]:
                    raise ForwardRecoveryError("recovery_requires_authentic_0058_point")
                relationship = safety._compatibility(checkout, (OLD_REVISION,), OLD_SHA)
                if relationship.relationship != "forward_upgrade":
                    raise ForwardRecoveryError("recovery_forward_upgrade_required")
                safety._compatibility(checkout, tuple(live_revisions), selected_sha)
                # References are derived from the actual selected migration graph.
                # Released migration bytes remain governed by existing release digest guards.
                work.mkdir()
                reference = work / "reference-0058.db"
                source_signature = _reference(reference, OLD_REVISION)
                with _memory(source.snapshot_bytes) as snapshot:
                    if _signature(snapshot) != source_signature:
                        raise ForwardRecoveryError("recovery_source_schema_drift")
                    logical = _logical(snapshot)
                target_reference = work / "reference-head.db"
                target_signature = _reference(target_reference, "head")
                if live_revisions == [OLD_REVISION]:
                    expected_live = source_signature
                elif live_revisions == list(relationship.selected_heads):
                    expected_live = target_signature
                else:
                    if len(live_revisions) != 1:
                        raise ForwardRecoveryError("recovery_incident_revision_ambiguous")
                    live_reference = work / "reference-incident.db"
                    expected_live = _reference(live_reference, live_revisions[0])
                if live_signature != expected_live:
                    raise ForwardRecoveryError("recovery_incident_schema_drift")
                source.assert_unchanged()
                safety._recheck_checkout(proof, stage="recovery-plan")
                plan = {
                    "kind": KIND,
                    "database": str(database),
                    "inventory": str(inventory),
                    "inventory_sha256": _hash(inventory.read_bytes()),
                    "artifact": str(artifact),
                    "artifact_sha256": source.artifact_sha256,
                    "snapshot_sha256": source.manifest["snapshot_sha256"],
                    "protection_state": protection_state,
                    "protection_mode": protection_mode,
                    "checkout": str(checkout),
                    "control": str(control),
                    "selected_sha": selected_sha,
                    "heads": list(relationship.selected_heads),
                    "work": str(work),
                    "live_identity": list(live.identity),
                    "live_sha256": _hash(live_bytes),
                    "live_revisions": live_revisions,
                    "source_signature": source_signature,
                    "target_signature": target_signature,
                    "logical": logical,
                    "incident": str(work / "incident.db"),
                }
                _record(work / "plan.json", plan)
                return {
                    "plan_sha256": _hash(_json(plan)),
                    "snapshot_sha256": plan["snapshot_sha256"],
                }
            finally:
                source.close()
        finally:
            if source_guard is not None:
                source_guard.close()
            live.close()


@contextmanager
def CustodyContext(path: Path, *, rename: bool = False):
    guard = Custody(path, rename=rename)
    try:
        yield guard
    finally:
        guard.close()


def _load(plan_path: Path, digest: str, checkpoint: str):
    plan = _read_record(_path(plan_path))
    if _hash(_json(plan)) != digest or plan.get("kind") != KIND:
        raise ForwardRecoveryError("recovery_plan_changed")
    if checkpoint != plan["snapshot_sha256"]:
        raise ForwardRecoveryError("recovery_checkpoint_acceptance_required")
    for key in ("database", "artifact", "inventory", "checkout", "control", "work", "incident"):
        _path(plan[key])
    if Path(plan["work"]) / "plan.json" != plan_path:
        raise ForwardRecoveryError("recovery_plan_location_changed")
    proof = _code(Path(plan["checkout"]), Path(plan["control"]), plan["selected_sha"])
    if _hash(Path(plan["inventory"]).read_bytes()) != plan["inventory_sha256"]:
        raise ForwardRecoveryError("recovery_inventory_changed")
    _binding(
        Path(plan["inventory"]),
        Path(plan["database"]),
        Path(plan["checkout"]),
        plan["selected_sha"],
    )
    return plan, proof


def _completed(work: Path, plan_sha256: str) -> bool:
    receipt = _read_record(work / "accepted.json")
    installed = _read_record(work / "installed.json")
    completed = _read_record(work / "completed-fence.json")
    if (
        receipt != installed
        or receipt.get("plan_sha256") != plan_sha256
        or completed != {"kind": KIND, "plan_sha256": plan_sha256}
    ):
        raise ForwardRecoveryError("recovery_completion_evidence_invalid")
    return True


def _validate_stage(guard: Custody, plan) -> str:
    _sidecar_free(guard.path)
    payload = guard.read()
    with _memory(payload) as connection:
        if (
            _revision(connection) != plan["heads"]
            or _signature(connection) != plan["target_signature"]
        ):
            raise ForwardRecoveryError("recovery_stage_schema_mismatch")
        projection = {name: value["columns"] for name, value in plan["logical"].items()}
        if _logical(connection, projection) != plan["logical"]:
            raise ForwardRecoveryError("recovery_stage_preservation_failed")
    return _hash(payload)


def _make_stage(plan, source):
    path = Path(plan["work"]) / ("stage-" + uuid.uuid4().hex + ".db")
    with _mutable_database(path) as guard:
        _boundary("reserved")
        guard.assert_path_identity()
        with _memory(source.snapshot_bytes) as memory:
            target = sqlite3.connect(path)
            try:
                memory.backup(target)
                target.commit()
            finally:
                target.close()
        _boundary("snapshot")
        guard.assert_path_identity()
        upgrade_database(path)
        guard.assert_path_identity()
        _sidecar_free(path)
        _boundary("migrated")
        expected_id, expected_hash = guard.identity, _mutable_hash(guard)
    return path, expected_id, expected_hash


def recover(plan_path: Path, *, plan_sha256: str, accept_checkpoint: str, resume: bool = False):
    """Install once, keeping Start fenced. Explicit resume reconciles actual IDs.

    Before a sealed stage record exists, resume builds a NEW stage and retains any
    prior incomplete attempt. After sealing it never migrates or recreates stage.
    Unknown/torn records or object arrangements remain fenced and refuse.
    """
    _native()
    plan_path = _path(plan_path)
    plan, proof = _load(plan_path, plan_sha256, accept_checkpoint)
    database, work, artifact = map(Path, (plan["database"], plan["work"], plan["artifact"]))
    fence = fence_path(database)
    incident = Path(plan["incident"])
    _same_volume(database, work)
    with database_admission(database, recovery=True), _bindings_held(plan) as binding_check:
        _stopped(Path(plan["inventory"]))
        if (work / "accepted.json").exists() and not os.path.lexists(fence):
            _completed(work, plan_sha256)
            return {"status": "already_finished", "plan_sha256": plan_sha256}
        existing = os.path.lexists(fence)
        if existing:
            if not resume or _read_record(fence) != {"kind": KIND, "plan_sha256": plan_sha256}:
                raise ForwardRecoveryError("recovery_explicit_matching_resume_required")
        elif resume or (work / "staged.json").exists():
            raise ForwardRecoveryError("recovery_transaction_state_ambiguous")
        for path in (database, incident):
            _sidecar_free(path)
        with CustodyContext(artifact):
            source = _source(plan)
            try:
                with ExitStack() as stack:
                    staged = (
                        _read_record(work / "staged.json")
                        if (work / "staged.json").exists()
                        else None
                    )
                    old_path = incident if incident.exists() else database
                    old = stack.enter_context(CustodyContext(old_path, rename=True))
                    if (
                        list(old.identity) != plan["live_identity"]
                        or _hash(old.read()) != plan["live_sha256"]
                    ):
                        raise ForwardRecoveryError("recovery_incident_changed")
                    _sidecar_free(old_path)
                    source.assert_unchanged()
                    safety._recheck_checkout(proof, stage="recovery-pre-fence")
                    binding_check()
                    if not existing:
                        # All source/live validation failures above are non-mutating.
                        _record(fence, {"kind": KIND, "plan_sha256": plan_sha256})
                    fence_guard = stack.enter_context(CustodyContext(fence))
                    if _guard_record(fence_guard) != {"kind": KIND, "plan_sha256": plan_sha256}:
                        raise ForwardRecoveryError("recovery_fence_changed")
                    _boundary("fenced")
                    if staged is None:
                        if old_path != database or incident.exists():
                            raise ForwardRecoveryError("recovery_unrecorded_incident")
                        path, expected_id, expected_hash = _make_stage(plan, source)
                        stage = stack.enter_context(CustodyContext(path, rename=True))
                        if stage.identity != expected_id or _hash(stage.read()) != expected_hash:
                            raise ForwardRecoveryError("recovery_stage_sealing_changed")
                        digest = _validate_stage(stage, plan)
                        staged = {
                            "plan_sha256": plan_sha256,
                            "path": str(path),
                            "identity": list(stage.identity),
                            "sha256": digest,
                        }
                        _record(work / "staged.json", staged)
                    else:
                        if staged["plan_sha256"] != plan_sha256:
                            raise ForwardRecoveryError("recovery_stage_record_changed")
                        path = _path(staged["path"])
                        if path.parent != work or not path.name.startswith("stage-"):
                            raise ForwardRecoveryError("recovery_stage_path_invalid")
                        stage_path = (
                            database if old_path == incident and database.exists() else path
                        )
                        stage = stack.enter_context(CustodyContext(stage_path, rename=True))
                        if (
                            list(stage.identity) != staged["identity"]
                            or _validate_stage(stage, plan) != staged["sha256"]
                        ):
                            raise ForwardRecoveryError("recovery_sealed_stage_changed")
                    _boundary("staged")
                    source.assert_unchanged()
                    safety._recheck_checkout(proof, stage="recovery-pre-install")
                    binding_check()
                    _sidecar_free(database)
                    if old.path == database:
                        old.rename(incident)
                    _boundary("incident")
                    if stage.path != database:
                        stage.rename(database)
                    _boundary("installed")
                    if (
                        _hash(old.read()) != plan["live_sha256"]
                        or _validate_stage(stage, plan) != staged["sha256"]
                    ):
                        raise ForwardRecoveryError("recovery_readback_failed")
                    source.assert_unchanged()
                    safety._recheck_checkout(proof, stage="recovery-readback")
                    binding_check()
                    installed = {
                        "plan_sha256": plan_sha256,
                        "identity": staged["identity"],
                        "sha256": staged["sha256"],
                    }
                    if not (work / "installed.json").exists():
                        _record(work / "installed.json", installed)
                    elif _read_record(work / "installed.json") != installed:
                        raise ForwardRecoveryError("recovery_receipt_changed")
                    _boundary("recorded")
                    return {"status": "installed_fenced", "plan_sha256": plan_sha256}
            finally:
                source.close()


def finish(plan_path: Path, *, plan_sha256: str, accept_checkpoint: str):
    """Explicit authoritative readback, then retire fence; never Start or reinstall."""
    _native()
    plan, proof = _load(_path(plan_path), plan_sha256, accept_checkpoint)
    database, work = Path(plan["database"]), Path(plan["work"])
    _same_volume(database, work)
    with (
        database_admission(database, recovery=True),
        _bindings_held(plan) as binding_check,
        ExitStack() as stack,
    ):
        _stopped(Path(plan["inventory"]))
        receipt = work / "accepted.json"
        fence = fence_path(database)
        if not os.path.lexists(fence):
            if receipt.exists() and _completed(work, plan_sha256):
                return {"status": "already_finished", "plan_sha256": plan_sha256}
            raise ForwardRecoveryError("recovery_transaction_state_ambiguous")
        fence_guard = stack.enter_context(CustodyContext(fence, rename=True))
        if _guard_record(fence_guard) != {"kind": KIND, "plan_sha256": plan_sha256}:
            raise ForwardRecoveryError("recovery_fence_changed")
        installed = _read_record(work / "installed.json")
        _sidecar_free(database)
        _sidecar_free(Path(plan["incident"]))
        with (
            CustodyContext(Path(plan["artifact"])),
            CustodyContext(database, rename=True) as live,
            CustodyContext(Path(plan["incident"])) as old,
        ):
            source = _source(plan)
            try:
                if (
                    installed["plan_sha256"] != plan_sha256
                    or list(live.identity) != installed["identity"]
                    or _validate_stage(live, plan) != installed["sha256"]
                    or list(old.identity) != plan["live_identity"]
                    or _hash(old.read()) != plan["live_sha256"]
                ):
                    raise ForwardRecoveryError("recovery_finish_readback_failed")
                source.assert_unchanged()
                safety._recheck_checkout(proof, stage="recovery-finish")
                binding_check()
                _sidecar_free(database)
                _sidecar_free(old.path)
                if _hash(old.read()) != plan["live_sha256"]:
                    raise ForwardRecoveryError("recovery_incident_changed")
                if not receipt.exists():
                    _record(receipt, installed)
                elif _read_record(receipt) != installed:
                    raise ForwardRecoveryError("recovery_receipt_changed")
                _boundary("accepted")
                _sidecar_free(database)
                _sidecar_free(old.path)
                if _hash(old.read()) != plan["live_sha256"]:
                    raise ForwardRecoveryError("recovery_incident_changed")
                fence_guard.rename(work / "completed-fence.json")
                _boundary("released")
                return {"status": "finished_start_separate", "plan_sha256": plan_sha256}
            finally:
                source.close()
