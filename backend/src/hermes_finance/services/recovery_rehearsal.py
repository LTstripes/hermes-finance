"""Fail-closed isolated recovery rehearsal for managed recovery points (ADR 0017)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from alembic.config import Config
from alembic.script import ScriptDirectory

from hermes_finance.services import protected_backups
from hermes_finance.services.protected_backups import (
    FORMAT_VERSION,
    ProtectedBackupError,
    protection_destination_alias,
)
from hermes_finance.services.recovery_process import (
    ProcessTreeError,
    file_identity_token,
    run_owned_process,
)

RECOVERY_PROFILE_KIND = "recovery_rehearsal"
RELATIONSHIP_SAME_REVISION = "same_revision"
RELATIONSHIP_FORWARD_UPGRADE = "forward_upgrade"
RECOVERY_ACTION_REQUIRED = (
    "isolated recovery rehearsal was not completed; use a new target after resolving the failure"
)
RECOVERY_READINESS_FAILURE_REASONS = frozenset(
    {
        "port_conflict",
        "backend_exit",
        "readiness_probe_defect",
        "months_response_invalid",
        "dashboard_http_status",
        "listener_not_owned",
        "recovery_identity_mismatch",
        "api_http_status",
        "startup_http_unavailable",
        "readiness_timeout",
    }
)
_RECOVERY_READINESS_FAILURE_PREFIX = "HERMES_RECOVERY_READINESS_FAILURE="
_FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")
_REPARSE_POINT = 0x400
_SIDECAR_NAME = ".hermes-data-identity.json"
_STAGING_NAME = ".finance.db.recovery.incomplete"
_READ_CHUNK = 1024 * 1024
_WINDOWS_INVALID_LEAF = re.compile(r'[<>:"/\\|?*]')
_WINDOWS_RESERVED_LEAVES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class RecoveryRehearsalError(RuntimeError):
    """A privacy-safe recovery stage failed closed."""

    def __init__(
        self,
        stage: str,
        message: str,
        *,
        target_mutated: bool = False,
        failure_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.target_mutated = target_mutated
        self.failure_reason = (
            failure_reason if failure_reason in RECOVERY_READINESS_FAILURE_REASONS else None
        )


def _privacy_safe_readiness_failure_reason(
    stdout: str | bytes | None, stderr: str | bytes | None
) -> str | None:
    for captured in (stdout, stderr):
        if isinstance(captured, bytes):
            text = captured.decode("utf-8", errors="replace")
        elif isinstance(captured, str):
            text = captured
        else:
            continue
        for line in text.splitlines():
            if line.startswith(_RECOVERY_READINESS_FAILURE_PREFIX):
                candidate = line[len(_RECOVERY_READINESS_FAILURE_PREFIX) :].strip()
                if candidate in RECOVERY_READINESS_FAILURE_REASONS:
                    return candidate
    return None


@dataclass(frozen=True, slots=True)
class CheckoutProof:
    checkout: Path
    selected_sha: str
    repository_key: str
    git_directory: Path
    common_directory: Path


@dataclass(frozen=True, slots=True)
class CompatibilityProof:
    source_revisions: tuple[str, ...]
    selected_heads: tuple[str, ...]
    relationship: str


@dataclass(slots=True)
class _DirectoryGuard:
    path: Path
    identity: tuple[int, int]
    descriptor: int | None = None
    handle: int | None = None
    containment_handle: int | None = None
    containment_path: str | None = None
    closed: bool = False

    def assert_path_identity(self) -> None:
        if self.closed:
            raise OSError("directory guard is closed")
        _assert_no_linked_components(self.path)
        if sys.platform == "win32":
            inspected_handle, identity, attributes = _open_windows_directory(
                self.path, deny_delete=False
            )
            try:
                if attributes & _REPARSE_POINT or identity != self.identity:
                    raise OSError("directory identity changed")
            finally:
                _close_windows_handle(inspected_handle)
            return
        if self.descriptor is None:
            raise OSError("directory descriptor is unavailable")
        inspected = self.path.lstat()
        if (
            self.path.is_symlink()
            or not stat.S_ISDIR(inspected.st_mode)
            or _file_identity(inspected) != self.identity
            or _file_identity(os.fstat(self.descriptor)) != self.identity
        ):
            raise OSError("directory identity changed")

    def create_directory(self, name: str) -> _DirectoryGuard:
        self.assert_path_identity()
        path = self.path / name
        if sys.platform == "win32":
            path.mkdir()
        else:
            if self.descriptor is None:
                raise OSError("directory descriptor is unavailable")
            os.mkdir(name, dir_fd=self.descriptor)
        created = _open_directory_guard(path)
        self.assert_path_identity()
        created.assert_path_identity()
        return created

    def open_exclusive_leaf(self, name: str) -> int:
        self.assert_path_identity()
        flags = (
            os.O_CREAT
            | os.O_EXCL
            | os.O_RDWR
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        if sys.platform == "win32":
            descriptor = _create_windows_exclusive_leaf(self.path / name)
        else:
            if self.descriptor is None:
                raise OSError("directory descriptor is unavailable")
            descriptor = os.open(name, flags, 0o600, dir_fd=self.descriptor)
        self.assert_path_identity()
        return descriptor

    def publish_no_overwrite(self, staging_name: str, final_name: str) -> None:
        self.assert_path_identity()
        if sys.platform == "win32":
            os.rename(self.path / staging_name, self.path / final_name)
        else:
            if self.descriptor is None:
                raise OSError("directory descriptor is unavailable")
            os.link(
                staging_name,
                final_name,
                src_dir_fd=self.descriptor,
                dst_dir_fd=self.descriptor,
                follow_symlinks=False,
            )
            os.unlink(staging_name, dir_fd=self.descriptor)
        self.assert_path_identity()

    def close(self) -> None:
        if self.closed:
            return
        if self.handle is not None:
            _close_windows_handle(self.handle)
        if self.containment_handle is not None:
            _close_windows_handle(self.containment_handle)
            try:
                if self.containment_path is not None:
                    os.unlink(self.containment_path)
            except FileNotFoundError:
                pass
        if self.descriptor is not None:
            os.close(self.descriptor)
        self.closed = True


@dataclass(slots=True)
class _RegularFileGuard:
    path: Path
    identity: tuple[int, int]
    descriptor: int | None = None
    handle: int | None = None
    closed: bool = False

    def assert_path_identity(self) -> None:
        if self.closed:
            raise OSError("file guard is closed")
        _assert_regular_leaf_identity(self.path, self.identity)
        if self.handle is not None:
            identity, attributes, link_count = _windows_handle_information(self.handle)
            if identity != self.identity or attributes & _REPARSE_POINT or link_count != 1:
                raise OSError("file identity changed")
        elif self.descriptor is not None:
            inspected = os.fstat(self.descriptor)
            if (
                _file_identity(inspected) != self.identity
                or not stat.S_ISREG(inspected.st_mode)
                or inspected.st_nlink != 1
            ):
                raise OSError("file identity changed")
        else:
            raise OSError("file guard is unavailable")

    def close(self) -> None:
        if self.closed:
            return
        if self.handle is not None:
            _close_windows_handle(self.handle)
        if self.descriptor is not None:
            os.close(self.descriptor)
        self.closed = True


@dataclass(slots=True)
class TargetPlan:
    profile: Path
    data: Path
    database: Path
    parent_guard: _DirectoryGuard
    profile_guard: _DirectoryGuard | None = None
    data_guard: _DirectoryGuard | None = None
    database_identity: tuple[int, int] | None = None
    database_guard: _RegularFileGuard | None = None

    def close(self) -> None:
        if self.database_guard is not None:
            self.database_guard.close()
        for guard in (self.data_guard, self.profile_guard, self.parent_guard):
            if guard is not None:
                guard.close()

    def assert_bound(self) -> None:
        self.parent_guard.assert_path_identity()
        if self.profile_guard is not None:
            self.profile_guard.assert_path_identity()
        if self.data_guard is not None:
            self.data_guard.assert_path_identity()
        if self.database_guard is not None:
            self.database_guard.assert_path_identity()
        elif self.database_identity is not None:
            _assert_regular_leaf_identity(self.database, self.database_identity)


@dataclass(frozen=True, slots=True)
class VerifiedSource:
    path: Path
    descriptor: int
    artifact_bytes: bytes
    snapshot_bytes: bytes
    manifest: dict[str, Any]
    artifact_sha256: str
    artifact_size_bytes: int
    identity: tuple[int, int] | None
    modified_ns: int
    link_count: int

    def assert_unchanged(self) -> None:
        """Prove both the opened object and its pathname still identify the same bytes."""

        try:
            opened_stat = os.fstat(self.descriptor)
            if (
                _file_identity(opened_stat) != self.identity
                or opened_stat.st_size != self.artifact_size_bytes
                or opened_stat.st_mtime_ns != self.modified_ns
                or opened_stat.st_nlink != self.link_count
            ):
                raise RecoveryRehearsalError(
                    "source-immutability", "managed recovery point changed during rehearsal"
                )
            if _sha256_fd(self.descriptor) != self.artifact_sha256:
                raise RecoveryRehearsalError(
                    "source-immutability", "managed recovery point changed during rehearsal"
                )
            protected_backups._assert_no_reparse_components(self.path)
            path_stat = self.path.lstat()
            if (
                not stat.S_ISREG(path_stat.st_mode)
                or self.path.is_symlink()
                or bool(getattr(path_stat, "st_file_attributes", 0) & _REPARSE_POINT)
                or _file_identity(path_stat) != self.identity
                or path_stat.st_size != self.artifact_size_bytes
                or path_stat.st_mtime_ns != self.modified_ns
                or path_stat.st_nlink != self.link_count
            ):
                raise RecoveryRehearsalError(
                    "source-immutability", "managed recovery point changed during rehearsal"
                )
            verification_fd = _open_regular_read_only(self.path)
            try:
                verification_stat = os.fstat(verification_fd)
                if (
                    _file_identity(verification_stat) != self.identity
                    or _sha256_fd(verification_fd) != self.artifact_sha256
                ):
                    raise RecoveryRehearsalError(
                        "source-immutability", "managed recovery point changed during rehearsal"
                    )
            finally:
                os.close(verification_fd)
        except RecoveryRehearsalError:
            raise
        except (OSError, ProtectedBackupError) as error:
            raise RecoveryRehearsalError(
                "source-immutability", "managed recovery point could not be re-verified"
            ) from error

    def close(self) -> None:
        os.close(self.descriptor)


@dataclass(frozen=True, slots=True)
class RecoveryRehearsalResult:
    status: str
    source_verified: bool
    source_unchanged: bool
    restored: bool
    prepared: bool
    validated: bool
    readiness: str
    destination_alias: str
    protection_state: str
    protection_mode: str
    format_version: int
    artifact_sha256: str
    artifact_identity_sha256: str
    snapshot_sha256: str
    producer_git_sha: str
    source_alembic_revisions: tuple[str, ...]
    selected_recovery_sha: str
    selected_checkout_heads: tuple[str, ...]
    schema_relationship: str
    resulting_alembic_revisions: tuple[str, ...]
    structural_counts: dict[str, int]
    action_required: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_verified": self.source_verified,
            "source_unchanged": self.source_unchanged,
            "restored": self.restored,
            "prepared": self.prepared,
            "validated": self.validated,
            "readiness": self.readiness,
            "destination_alias": self.destination_alias,
            "protection_state": self.protection_state,
            "protection_mode": self.protection_mode,
            "format_version": self.format_version,
            "artifact_sha256": self.artifact_sha256,
            "artifact_identity_sha256": self.artifact_identity_sha256,
            "snapshot_sha256": self.snapshot_sha256,
            "producer_git_sha": self.producer_git_sha,
            "source_alembic_revisions": list(self.source_alembic_revisions),
            "selected_recovery_sha": self.selected_recovery_sha,
            "selected_checkout_heads": list(self.selected_checkout_heads),
            "schema_relationship": self.schema_relationship,
            "resulting_alembic_revisions": list(self.resulting_alembic_revisions),
            "structural_counts": dict(self.structural_counts),
            "action_required": self.action_required,
        }


def _file_identity(value: os.stat_result) -> tuple[int, int] | None:
    device = int(getattr(value, "st_dev", 0))
    inode = int(getattr(value, "st_ino", 0))
    if device == 0 and inode == 0:
        return None
    if sys.platform == "win32":
        return 0, inode
    return device, inode


def _windows_handle_information(handle: int) -> tuple[tuple[int, int], int, int]:
    import ctypes
    from ctypes import wintypes

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("file_attributes", wintypes.DWORD),
            ("creation_time", wintypes.FILETIME),
            ("last_access_time", wintypes.FILETIME),
            ("last_write_time", wintypes.FILETIME),
            ("volume_serial_number", wintypes.DWORD),
            ("file_size_high", wintypes.DWORD),
            ("file_size_low", wintypes.DWORD),
            ("number_of_links", wintypes.DWORD),
            ("file_index_high", wintypes.DWORD),
            ("file_index_low", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    information = ByHandleFileInformation()
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = (wintypes.HANDLE, ctypes.POINTER(ByHandleFileInformation))
    get_information.restype = wintypes.BOOL
    if not get_information(handle, ctypes.byref(information)):
        raise OSError(ctypes.get_last_error(), "filesystem identity could not be read")
    identity = (
        0,
        (int(information.file_index_high) << 32) | int(information.file_index_low),
    )
    return identity, int(information.file_attributes), int(information.number_of_links)


def _open_windows_path(
    path: Path, *, directory: bool, deny_delete: bool
) -> tuple[int, tuple[int, int], int, int]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    share = 0x00000001 | 0x00000002
    if not deny_delete:
        share |= 0x00000004
    flags = 0x00200000
    if directory:
        flags |= 0x02000000
    handle = create_file(
        str(path),
        0x00000080 if directory else 0x80000000,
        share,
        None,
        3,
        flags,
        None,
    )
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_last_error(), "filesystem handle could not be opened")
    try:
        identity, attributes, link_count = _windows_handle_information(int(handle))
    except OSError:
        kernel32.CloseHandle(handle)
        raise
    return int(handle), identity, attributes, link_count


def _create_windows_exclusive_leaf(path: Path) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        0x80000000 | 0x40000000,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        1,
        0x00200000,
        None,
    )
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_last_error(), "exclusive file could not be created")
    try:
        return msvcrt.open_osfhandle(int(handle), os.O_RDWR | getattr(os, "O_BINARY", 0))
    except OSError:
        kernel32.CloseHandle(handle)
        raise


def _open_windows_directory(path: Path, *, deny_delete: bool) -> tuple[int, tuple[int, int], int]:
    handle, identity, attributes, _link_count = _open_windows_path(
        path, directory=True, deny_delete=deny_delete
    )
    return handle, identity, attributes


def _open_windows_containment_lock(path: Path) -> tuple[int, str]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    containment_path = str(path) + ":hermes-recovery-containment-" + secrets.token_hex(16)
    handle = create_file(
        containment_path,
        0x80000000 | 0x40000000,
        0x00000001 | 0x00000002,
        None,
        4,
        0,
        None,
    )
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_last_error(), "directory containment could not be opened")
    return int(handle), containment_path


def _close_windows_handle(handle: int) -> None:
    import ctypes

    if not ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle):
        raise OSError(ctypes.get_last_error(), "directory handle could not be closed")


def _open_directory_guard(path: Path) -> _DirectoryGuard:
    _assert_no_linked_components(path)
    if sys.platform == "win32":
        handle, identity, attributes = _open_windows_directory(path, deny_delete=True)
        if attributes & _REPARSE_POINT:
            _close_windows_handle(handle)
            raise OSError("directory is a reparse point")
        try:
            containment_handle, containment_path = _open_windows_containment_lock(path)
        except OSError:
            _close_windows_handle(handle)
            raise
        return _DirectoryGuard(
            path=path,
            identity=identity,
            handle=handle,
            containment_handle=containment_handle,
            containment_path=containment_path,
        )
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    inspected = os.fstat(descriptor)
    identity = _file_identity(inspected)
    if identity is None or not stat.S_ISDIR(inspected.st_mode):
        os.close(descriptor)
        raise OSError("directory identity is unavailable")
    return _DirectoryGuard(path=path, identity=identity, descriptor=descriptor)


def _open_regular_file_guard(path: Path) -> _RegularFileGuard:
    _assert_no_linked_components(path)
    if sys.platform == "win32":
        handle, identity, attributes, link_count = _open_windows_path(
            path, directory=False, deny_delete=True
        )
        if attributes & _REPARSE_POINT or link_count != 1:
            _close_windows_handle(handle)
            raise OSError("file identity is linked")
        return _RegularFileGuard(path=path, identity=identity, handle=handle)
    descriptor = _open_regular_read_only(path)
    inspected = os.fstat(descriptor)
    identity = _file_identity(inspected)
    if identity is None or inspected.st_nlink != 1:
        os.close(descriptor)
        raise OSError("file identity is unavailable")
    return _RegularFileGuard(path=path, identity=identity, descriptor=descriptor)


def _assert_regular_leaf_identity(path: Path, expected: tuple[int, int]) -> None:
    inspected = path.lstat()
    if (
        path.is_symlink()
        or bool(getattr(inspected, "st_file_attributes", 0) & _REPARSE_POINT)
        or not stat.S_ISREG(inspected.st_mode)
        or inspected.st_nlink != 1
        or _file_identity(inspected) != expected
    ):
        raise OSError("file identity changed")


def _open_regular_read_only(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode):
        os.close(descriptor)
        raise OSError("source is not a regular file")
    return descriptor


def _read_fd(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, _READ_CHUNK)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _sha256_fd(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        chunk = os.read(descriptor, _READ_CHUNK)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _absolute_path(value: Path, *, stage: str) -> Path:
    expanded = value.expanduser()
    if not expanded.is_absolute():
        raise RecoveryRehearsalError(stage, "recovery paths must be absolute")
    absolute = Path(os.path.abspath(expanded))
    try:
        _assert_no_linked_components(absolute)
    except OSError as error:
        raise RecoveryRehearsalError(stage, "recovery path uses a linked boundary") from error
    return absolute.resolve(strict=False)


def _assert_no_linked_components(path: Path) -> None:
    components: list[Path] = []
    current = path
    while True:
        components.append(current)
        if current.parent == current:
            break
        current = current.parent
    for component in reversed(components):
        try:
            inspected = component.lstat()
        except FileNotFoundError:
            continue
        if component.is_symlink() or bool(
            getattr(inspected, "st_file_attributes", 0) & _REPARSE_POINT
        ):
            raise OSError("linked path component")


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _path_is_within(child: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((_path_key(child), _path_key(parent))) == _path_key(parent)
    except ValueError:
        return False


def _paths_overlap(left: Path, right: Path) -> bool:
    return _path_is_within(left, right) or _path_is_within(right, left)


def _verify_source(path: Path, *, protection_state: str, protection_mode: str) -> VerifiedSource:
    try:
        protection_destination_alias(protection_state, protection_mode)
    except ProtectedBackupError as error:
        raise RecoveryRehearsalError(
            "protection", "protected recovery boundary attestation is invalid"
        ) from error
    source = _absolute_path(path, stage="source-verification")
    try:
        protected_backups._assert_no_reparse_components(source.parent)
        descriptor = _open_regular_read_only(source)
    except (OSError, ProtectedBackupError) as error:
        raise RecoveryRehearsalError(
            "source-verification", "managed recovery point is missing or unreadable"
        ) from error
    try:
        opened = os.fstat(descriptor)
        if opened.st_nlink != 1:
            raise RecoveryRehearsalError(
                "source-verification", "managed recovery point uses a linked file identity"
            )
        artifact_bytes = _read_fd(descriptor)
        try:
            manifest, artifact_sha256, artifact_size = protected_backups._verify_payload(
                artifact_bytes
            )
        except Exception as error:
            raise RecoveryRehearsalError(
                "source-verification", "managed recovery point verification failed"
            ) from error
        name_match = protected_backups._MANAGED_FILENAME_RE.fullmatch(source.name)
        if name_match is None or name_match.group("digest") != artifact_sha256[:16]:
            raise RecoveryRehearsalError(
                "source-verification", "managed recovery point name identity is invalid"
            )
        if (
            manifest.get("protection_state") != protection_state
            or manifest.get("protection_mode") != protection_mode
        ):
            raise RecoveryRehearsalError(
                "source-verification",
                "managed recovery point protection identity does not match",
            )
        with zipfile.ZipFile(io.BytesIO(artifact_bytes), "r") as archive:
            snapshot_bytes = archive.read(protected_backups._SNAPSHOT_NAME)
        result = VerifiedSource(
            path=source,
            descriptor=descriptor,
            artifact_bytes=artifact_bytes,
            snapshot_bytes=snapshot_bytes,
            manifest=manifest,
            artifact_sha256=artifact_sha256,
            artifact_size_bytes=artifact_size,
            identity=_file_identity(opened),
            modified_ns=opened.st_mtime_ns,
            link_count=opened.st_nlink,
        )
        result.assert_unchanged()
        return result
    except Exception:
        os.close(descriptor)
        raise


def _run_git(checkout: Path, arguments: list[str], *, stage: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=checkout,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RecoveryRehearsalError(stage, "Git identity verification failed") from error
    return completed.stdout.strip()


def _remote_key(value: str) -> str:
    candidate = value.strip().rstrip("/\\")
    ssh_match = re.fullmatch(r"git@([^:]+):(.+)", candidate)
    url_match = re.fullmatch(r"(?:https?|ssh)://([^/]+)/(.+)", candidate)
    if ssh_match:
        candidate = f"{ssh_match.group(1)}/{ssh_match.group(2)}"
    elif url_match:
        candidate = f"{url_match.group(1)}/{url_match.group(2)}"
    elif candidate.lower().startswith("file://"):
        from urllib.parse import unquote, urlparse

        candidate = os.path.abspath(unquote(urlparse(candidate).path))
    elif os.path.isabs(candidate):
        candidate = os.path.abspath(candidate)
    if candidate.lower().endswith(".git"):
        candidate = candidate[:-4]
    return candidate.rstrip("/\\").lower()


def _git_path(checkout: Path, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = checkout / candidate
    return candidate.resolve()


def _executing_checkout() -> Path:
    checkout = Path(__file__).resolve().parents[4]
    if not (checkout / "backend" / "pyproject.toml").is_file():
        raise RecoveryRehearsalError(
            "checkout-identity", "executing recovery checkout is unavailable"
        )
    return checkout


def _assert_no_private_runtime_content(checkout: Path) -> None:
    if (checkout / ".env").exists() or (checkout / "private").exists():
        raise RecoveryRehearsalError(
            "checkout-identity", "recovery checkout contains a private runtime boundary"
        )
    data = checkout / "data"
    if data.exists():
        try:
            unexpected = [item for item in data.iterdir() if item.name != ".gitkeep"]
        except OSError as error:
            raise RecoveryRehearsalError(
                "checkout-identity", "recovery checkout data boundary cannot be inspected"
            ) from error
        if unexpected:
            raise RecoveryRehearsalError(
                "checkout-identity", "recovery checkout already contains runtime data"
            )


def _validate_recovery_checkout(
    recovery_checkout: Path, control_checkout: Path, selected_sha: str
) -> CheckoutProof:
    normalized_sha = selected_sha.strip().lower()
    if _FULL_SHA_RE.fullmatch(normalized_sha) is None:
        raise RecoveryRehearsalError(
            "checkout-identity", "selected recovery SHA must be one full commit identity"
        )
    recovery = _absolute_path(recovery_checkout, stage="checkout-identity")
    control = _absolute_path(control_checkout, stage="checkout-identity")
    executing = _executing_checkout().resolve()
    if _path_key(recovery) != _path_key(executing):
        raise RecoveryRehearsalError(
            "checkout-identity", "selected recovery checkout is not the executing checkout"
        )
    if _paths_overlap(recovery, control):
        raise RecoveryRehearsalError(
            "checkout-identity", "recovery and control checkouts are not independent"
        )
    if not recovery.is_dir() or not control.is_dir():
        raise RecoveryRehearsalError("checkout-identity", "required checkout is unavailable")
    control_top = Path(
        _run_git(control, ["rev-parse", "--show-toplevel"], stage="checkout-identity")
    )
    if _path_key(control_top) != _path_key(control):
        raise RecoveryRehearsalError("checkout-identity", "control checkout identity is ambiguous")
    required = (
        recovery / "backend" / "pyproject.toml",
        recovery / "backend" / "alembic.ini",
        recovery / "scripts" / "prepare-runtime-dependencies.ps1",
        recovery / "scripts" / "prepare-runtime.ps1",
        recovery / "scripts" / "recovery-rehearsal.ps1",
        recovery / "scripts" / "recovery-bootstrap-boundary.ps1",
        recovery / "scripts" / "recovery-bootstrap-safety.ps1",
        recovery / "scripts" / "recovery-runtime-boundary.ps1",
        recovery / "scripts" / "recovery-runtime-safety.ps1",
        recovery / "scripts" / "recovery-readiness.ps1",
        recovery / "scripts" / "start-local.ps1",
    )
    if any(not item.is_file() for item in required):
        raise RecoveryRehearsalError("checkout-identity", "recovery checkout is incomplete")
    top = Path(_run_git(recovery, ["rev-parse", "--show-toplevel"], stage="checkout-identity"))
    if _path_key(top) != _path_key(recovery):
        raise RecoveryRehearsalError("checkout-identity", "recovery checkout identity is ambiguous")
    head = _run_git(
        recovery, ["rev-parse", "--verify", "HEAD^{commit}"], stage="checkout-identity"
    ).lower()
    if head != normalized_sha:
        raise RecoveryRehearsalError(
            "checkout-identity", "recovery checkout is not pinned to the selected SHA"
        )
    branch = (
        _run_git(
            recovery, ["symbolic-ref", "--quiet", "--short", "HEAD"], stage="checkout-identity"
        )
        if _symbolic_head_exists(recovery)
        else ""
    )
    if branch:
        raise RecoveryRehearsalError(
            "checkout-identity", "recovery checkout must use detached immutable HEAD"
        )
    status_text = _run_git(
        recovery,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        stage="checkout-identity",
    )
    conflicts = _run_git(recovery, ["ls-files", "-u"], stage="checkout-identity")
    if status_text or conflicts:
        raise RecoveryRehearsalError("checkout-identity", "recovery checkout is not clean")
    git_dir = _git_path(
        recovery, _run_git(recovery, ["rev-parse", "--git-dir"], stage="checkout-identity")
    )
    common_dir = _git_path(
        recovery,
        _run_git(recovery, ["rev-parse", "--git-common-dir"], stage="checkout-identity"),
    )
    if not (recovery / ".git").is_dir() or not _path_is_within(git_dir, recovery):
        raise RecoveryRehearsalError(
            "checkout-identity", "recovery checkout is a linked Git worktree"
        )
    if not _path_is_within(common_dir, recovery):
        raise RecoveryRehearsalError(
            "checkout-identity", "recovery checkout Git metadata is not independent"
        )
    recovery_remote = _run_git(recovery, ["remote", "get-url", "origin"], stage="checkout-identity")
    control_remote = _run_git(control, ["remote", "get-url", "origin"], stage="checkout-identity")
    if not recovery_remote or _remote_key(recovery_remote) != _remote_key(control_remote):
        raise RecoveryRehearsalError(
            "checkout-identity", "recovery checkout repository identity is invalid"
        )
    _assert_no_private_runtime_content(recovery)
    return CheckoutProof(
        checkout=recovery,
        selected_sha=normalized_sha,
        repository_key=_remote_key(recovery_remote),
        git_directory=git_dir,
        common_directory=common_dir,
    )


def _symbolic_head_exists(checkout: Path) -> bool:
    try:
        completed = subprocess.run(
            ["git", "symbolic-ref", "--quiet", "HEAD"],
            cwd=checkout,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RecoveryRehearsalError(
            "checkout-identity", "Git identity verification failed"
        ) from error
    if completed.returncode not in (0, 1):
        raise RecoveryRehearsalError("checkout-identity", "Git identity verification failed")
    return completed.returncode == 0


def _recheck_checkout(proof: CheckoutProof, *, stage: str) -> None:
    recovery = proof.checkout
    head = _run_git(recovery, ["rev-parse", "HEAD^{commit}"], stage=stage).lower()
    status_text = _run_git(
        recovery, ["status", "--porcelain=v1", "--untracked-files=all"], stage=stage
    )
    common = _git_path(recovery, _run_git(recovery, ["rev-parse", "--git-common-dir"], stage=stage))
    if (
        head != proof.selected_sha
        or status_text
        or _path_key(common) != _path_key(proof.common_directory)
        or _symbolic_head_exists(recovery)
    ):
        raise RecoveryRehearsalError(stage, "recovery checkout identity changed")
    _assert_no_private_runtime_content(recovery)


def _assert_prepare_output_boundary(path: Path, *, directory: bool) -> None:
    try:
        inspected = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise RecoveryRehearsalError(
            "runtime-prepare-boundary", "prepared output boundary cannot be inspected"
        ) from error
    if path.is_symlink() or bool(getattr(inspected, "st_file_attributes", 0) & _REPARSE_POINT):
        raise RecoveryRehearsalError(
            "runtime-prepare-boundary", "prepared output boundary is linked"
        )
    if directory:
        if not stat.S_ISDIR(inspected.st_mode):
            raise RecoveryRehearsalError(
                "runtime-prepare-boundary", "prepared output boundary has the wrong type"
            )
        for root, directories, files in os.walk(path, followlinks=False):
            for name in directories:
                candidate = Path(root) / name
                child = candidate.lstat()
                linked = candidate.is_symlink()
                if bool(getattr(child, "st_file_attributes", 0) & _REPARSE_POINT) or (
                    linked
                    and not _safe_posix_prepare_link(candidate, boundary=path, directory=True)
                ):
                    raise RecoveryRehearsalError(
                        "runtime-prepare-boundary",
                        "prepared output tree contains a linked directory",
                    )
            for name in files:
                candidate = Path(root) / name
                child = candidate.lstat()
                linked = candidate.is_symlink()
                if (
                    bool(getattr(child, "st_file_attributes", 0) & _REPARSE_POINT)
                    or (
                        linked
                        and not _safe_posix_prepare_link(candidate, boundary=path, directory=False)
                    )
                    or (
                        not linked
                        and (
                            not stat.S_ISREG(child.st_mode)
                            or child.st_nlink != 1
                            or _file_identity(child) is None
                        )
                    )
                ):
                    raise RecoveryRehearsalError(
                        "runtime-prepare-boundary",
                        "prepared output tree contains a linked file",
                    )
        return
    if (
        not stat.S_ISREG(inspected.st_mode)
        or inspected.st_nlink != 1
        or _file_identity(inspected) is None
    ):
        raise RecoveryRehearsalError(
            "runtime-prepare-boundary", "prepared output file identity is invalid"
        )


def _safe_posix_prepare_link(candidate: Path, *, boundary: Path, directory: bool) -> bool:
    """Accept only standard, non-mutating POSIX venv links or boundary-local aliases."""

    if sys.platform == "win32":
        return False
    try:
        resolved = candidate.resolve(strict=True)
        inspected = resolved.stat()
        relative = candidate.relative_to(boundary)
        base_interpreter = Path(getattr(sys, "_base_executable", sys.executable)).resolve(
            strict=True
        )
    except (OSError, RuntimeError, ValueError):
        return False
    if _path_is_within(resolved, boundary):
        return stat.S_ISDIR(inspected.st_mode) if directory else stat.S_ISREG(inspected.st_mode)
    return bool(
        not directory
        and boundary.name == ".venv"
        and relative.parent == Path("bin")
        and re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", relative.name)
        and _path_key(resolved) == _path_key(base_interpreter)
        and stat.S_ISREG(inspected.st_mode)
        and os.access(resolved, os.X_OK)
    )


def _validate_prepare_boundaries(checkout: CheckoutProof) -> None:
    root = checkout.checkout
    for path, directory in (
        (root / "backend" / ".venv", True),
        (root / "frontend" / "node_modules", True),
        (root / "frontend" / "node_modules" / ".tmp", True),
        (root / "frontend" / "dist", True),
        (root / ".tmp", True),
        (root / ".hermes-runtime-prepared.json", False),
    ):
        if not _path_is_within(path, root):
            raise RecoveryRehearsalError(
                "runtime-prepare-boundary", "prepared output escapes the recovery checkout"
            )
        try:
            _assert_no_linked_components(path)
        except OSError as error:
            raise RecoveryRehearsalError(
                "runtime-prepare-boundary", "prepared output boundary is linked"
            ) from error
        _assert_prepare_output_boundary(path, directory=directory)


@contextmanager
def _hold_prepare_boundary_guards(checkout: CheckoutProof) -> Iterator[None]:
    root = checkout.checkout
    paths = (
        root / "backend" / ".venv",
        root / "frontend" / "node_modules",
        root / "frontend" / "dist",
        root / ".tmp",
    )
    guards: list[_DirectoryGuard] = []
    try:
        _validate_prepare_boundaries(checkout)
        for path in paths:
            try:
                path.mkdir()
            except FileExistsError:
                pass
            guards.append(_open_directory_guard(path))
        for guard in guards:
            guard.assert_path_identity()
        _validate_prepare_boundaries(checkout)
        yield
        for guard in guards:
            guard.assert_path_identity()
        _validate_prepare_boundaries(checkout)
    except RecoveryRehearsalError:
        raise
    except OSError as error:
        raise RecoveryRehearsalError(
            "runtime-prepare-boundary",
            "prepared output containment could not be preserved",
            target_mutated=True,
        ) from error
    finally:
        for guard in reversed(guards):
            guard.close()


@contextmanager
def _hold_prepare_build_boundary_guards(checkout: CheckoutProof) -> Iterator[None]:
    root = checkout.checkout
    paths = (root / "frontend" / "node_modules" / ".tmp",)
    guards: list[_DirectoryGuard] = []
    try:
        _validate_prepare_boundaries(checkout)
        for path in paths:
            try:
                path.mkdir()
            except FileExistsError:
                pass
            _assert_prepare_output_boundary(path, directory=True)
            guards.append(_open_directory_guard(path))
        for guard in guards:
            guard.assert_path_identity()
        _validate_prepare_boundaries(checkout)
        yield
        for guard in guards:
            guard.assert_path_identity()
        _validate_prepare_boundaries(checkout)
    except RecoveryRehearsalError:
        raise
    except OSError as error:
        raise RecoveryRehearsalError(
            "runtime-prepare-boundary",
            "prepared build output containment could not be preserved",
            target_mutated=True,
        ) from error
    finally:
        for guard in reversed(guards):
            guard.close()


def _isolated_runtime_environment(
    checkout: CheckoutProof, *, database: Path | None = None
) -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("UV_PROJECT", "UV_WORKING_DIR", "VIRTUAL_ENV"):
        environment.pop(name, None)
    environment["UV_PROJECT_ENVIRONMENT"] = str(checkout.checkout / "backend" / ".venv")
    environment["UV_LINK_MODE"] = "copy"
    environment["TEMP"] = str(checkout.checkout / ".tmp")
    environment["TMP"] = str(checkout.checkout / ".tmp")
    environment["HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN"] = ""
    environment["PYTHONPATH"] = ""
    if database is not None:
        environment["HERMES_FINANCE_DATABASE_PATH"] = str(database)
    return environment


def _script_directory(checkout: Path) -> ScriptDirectory:
    config_path = checkout / "backend" / "alembic.ini"
    try:
        return ScriptDirectory.from_config(Config(str(config_path)))
    except Exception as error:
        raise RecoveryRehearsalError(
            "schema-compatibility", "selected checkout Alembic graph is unavailable"
        ) from error


def _compatibility(
    checkout: Path, source_revisions: tuple[str, ...], producer_sha: str
) -> CompatibilityProof:
    script = _script_directory(checkout)
    source = tuple(sorted(set(source_revisions)))
    if not source or source != source_revisions:
        raise RecoveryRehearsalError(
            "schema-compatibility", "source Alembic revision identity is invalid"
        )
    try:
        for revision in source:
            if script.get_revision(revision) is None:
                raise RecoveryRehearsalError(
                    "schema-compatibility", "source Alembic revision is unknown"
                )
        heads = tuple(sorted(script.get_heads()))
    except RecoveryRehearsalError:
        raise
    except Exception as error:
        raise RecoveryRehearsalError(
            "schema-compatibility", "Alembic compatibility could not be proven"
        ) from error
    if not heads:
        raise RecoveryRehearsalError(
            "schema-compatibility", "selected checkout has no supported Alembic head"
        )
    if source == heads:
        relationship = RELATIONSHIP_SAME_REVISION
    else:
        if len(source) != 1 or len(heads) != 1:
            raise RecoveryRehearsalError(
                "schema-compatibility", "forward Alembic relationship is ambiguous"
            )
        current = heads[0]
        visited: set[str] = set()
        while current != source[0]:
            if current in visited:
                raise RecoveryRehearsalError(
                    "schema-compatibility", "forward Alembic relationship is cyclic"
                )
            visited.add(current)
            revision = script.get_revision(current)
            if revision is None:
                raise RecoveryRehearsalError(
                    "schema-compatibility", "selected Alembic path is incomplete"
                )
            parents = revision.down_revision
            if isinstance(parents, str):
                normalized_parents = (parents,)
            elif parents is None:
                normalized_parents = ()
            else:
                normalized_parents = tuple(parents)
            if len(normalized_parents) != 1:
                raise RecoveryRehearsalError(
                    "schema-compatibility", "forward Alembic relationship is ambiguous"
                )
            current = normalized_parents[0]
        relationship = RELATIONSHIP_FORWARD_UPGRADE
    producer = producer_sha.strip().lower()
    if _FULL_SHA_RE.fullmatch(producer) is None:
        raise RecoveryRehearsalError("schema-compatibility", "producer Git identity is invalid")
    try:
        producer_type = _run_git(
            checkout, ["cat-file", "-t", producer], stage="schema-compatibility"
        )
    except RecoveryRehearsalError as error:
        raise RecoveryRehearsalError(
            "schema-compatibility", "producer Git identity is unavailable"
        ) from error
    if producer_type != "commit":
        raise RecoveryRehearsalError(
            "schema-compatibility", "producer Git identity is not a commit"
        )
    return CompatibilityProof(
        source_revisions=source,
        selected_heads=heads,
        relationship=relationship,
    )


def _runtime_inventory(runtime_config: Path) -> tuple[Path, ...]:
    config_path = _absolute_path(runtime_config, stage="runtime-inventory")
    try:
        if not config_path.is_file() or config_path.is_symlink():
            raise OSError("config is not a regular file")
        document = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecoveryRehearsalError(
            "runtime-inventory", "Owner runtime inventory is unavailable or invalid"
        ) from error
    if not isinstance(document, dict) or document.get("version") != 1:
        raise RecoveryRehearsalError("runtime-inventory", "Owner runtime inventory is invalid")
    canonical = document.get("canonical_production")
    profiles = document.get("profiles")
    if not isinstance(canonical, dict) or not isinstance(profiles, list):
        raise RecoveryRehearsalError("runtime-inventory", "Owner runtime inventory is invalid")
    profile_types: list[str] = []
    stable_boundaries: tuple[Path, Path, Path] | None = None
    canonical_boundaries: tuple[Path, Path, Path] | None = None
    boundaries: list[Path] = []
    for item in [canonical, *profiles]:
        if not isinstance(item, dict):
            raise RecoveryRehearsalError("runtime-inventory", "Owner runtime inventory is invalid")
        if item is not canonical:
            profile_type = item.get("type")
            if profile_type not in {"stable", "preview", "experiment"}:
                raise RecoveryRehearsalError(
                    "runtime-inventory", "Owner runtime inventory has an unsupported profile"
                )
            profile_types.append(profile_type)
        item_boundaries: list[Path] = []
        for key in ("checkout", "data_dir", "database"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                raise RecoveryRehearsalError(
                    "runtime-inventory", "Owner runtime inventory is incomplete"
                )
            boundary = _absolute_path(Path(value), stage="runtime-inventory")
            boundaries.append(boundary)
            item_boundaries.append(boundary)
        if item is canonical:
            canonical_boundaries = tuple(item_boundaries)  # type: ignore[assignment]
        elif item.get("type") == "stable":
            stable_boundaries = tuple(item_boundaries)  # type: ignore[assignment]
    if profile_types.count("stable") != 1:
        raise RecoveryRehearsalError(
            "runtime-inventory", "Owner runtime inventory must contain one Stable profile"
        )
    if (
        canonical_boundaries is None
        or stable_boundaries is None
        or any(
            _path_key(left) != _path_key(right)
            for left, right in zip(canonical_boundaries, stable_boundaries, strict=True)
        )
    ):
        raise RecoveryRehearsalError(
            "runtime-inventory", "Stable runtime inventory does not match canonical production"
        )
    return tuple(boundaries)


def _worktree_inventory(control_checkout: Path) -> tuple[Path, ...]:
    output = _run_git(
        control_checkout, ["worktree", "list", "--porcelain"], stage="runtime-inventory"
    )
    roots: list[Path] = []
    for line in output.splitlines():
        if line.startswith("worktree "):
            roots.append(
                _absolute_path(Path(line.removeprefix("worktree ")), stage="runtime-inventory")
            )
    if not roots:
        raise RecoveryRehearsalError(
            "runtime-inventory", "development workspace inventory is unavailable"
        )
    return tuple(roots)


def _assert_source_outside_forbidden(source: VerifiedSource, forbidden: tuple[Path, ...]) -> None:
    for boundary in forbidden:
        if _paths_overlap(source.path, boundary):
            raise RecoveryRehearsalError(
                "runtime-inventory", "recovery point aliases an existing runtime boundary"
            )
        try:
            if boundary.is_file() and _file_identity(boundary.stat()) == source.identity:
                raise RecoveryRehearsalError(
                    "runtime-inventory", "recovery point aliases an existing runtime object"
                )
        except OSError as error:
            raise RecoveryRehearsalError(
                "runtime-inventory", "runtime boundary identity cannot be inspected"
            ) from error


def _assert_checkout_outside_forbidden(
    checkout: CheckoutProof, forbidden: tuple[Path, ...]
) -> None:
    for boundary in forbidden:
        if _paths_overlap(checkout.checkout, boundary):
            raise RecoveryRehearsalError(
                "runtime-inventory",
                "recovery checkout conflicts with an existing runtime or development workspace",
            )


def _validate_supported_database_path(database: Path) -> None:
    name = database.name
    if not name or "\x00" in name:
        raise RecoveryRehearsalError("target-boundary", "target database name is unsupported")
    if sys.platform == "win32":
        stem = name.split(".", 1)[0].casefold()
        if (
            _WINDOWS_INVALID_LEAF.search(name)
            or name.endswith((" ", "."))
            or stem in _WINDOWS_RESERVED_LEAVES
        ):
            raise RecoveryRehearsalError("target-boundary", "target database name is unsupported")
    try:
        database.as_uri()
    except ValueError as error:
        raise RecoveryRehearsalError(
            "target-boundary", "target database name is unsupported"
        ) from error


def _validate_fresh_target(
    *,
    target_profile: Path,
    target_data: Path,
    target_database: Path,
    source: VerifiedSource,
    checkout: CheckoutProof,
    forbidden: tuple[Path, ...],
) -> TargetPlan:
    profile = _absolute_path(target_profile, stage="target-boundary")
    data = _absolute_path(target_data, stage="target-boundary")
    database = _absolute_path(target_database, stage="target-boundary")
    if profile.parent == profile:
        raise RecoveryRehearsalError("target-boundary", "target profile boundary is too broad")
    if data.parent != profile or database.parent != data:
        raise RecoveryRehearsalError(
            "target-boundary", "target profile, data, and database boundaries are not exact"
        )
    _validate_supported_database_path(database)
    generated = (database, data / _SIDECAR_NAME, data / _STAGING_NAME)
    if len({_path_key(path) for path in generated}) != len(generated) or len(
        {path.name.casefold() for path in generated}
    ) != len(generated):
        raise RecoveryRehearsalError(
            "target-boundary", "target database conflicts with a reserved recovery path"
        )
    if any(_paths_overlap(profile, path) for path in (source.path, source.path.parent)):
        raise RecoveryRehearsalError(
            "target-boundary", "target aliases the managed recovery-point boundary"
        )
    if _paths_overlap(profile, checkout.checkout):
        raise RecoveryRehearsalError(
            "target-boundary", "target aliases the selected recovery checkout"
        )
    for boundary in forbidden:
        if _paths_overlap(profile, boundary):
            raise RecoveryRehearsalError(
                "target-boundary", "target conflicts with an existing runtime or workspace"
            )
    try:
        protected_backups._assert_outside_git_boundaries(profile.parent)
    except ProtectedBackupError as error:
        raise RecoveryRehearsalError(
            "target-boundary", "target is inside a Git repository or worktree"
        ) from error
    if not profile.parent.is_dir():
        raise RecoveryRehearsalError("target-boundary", "target parent boundary is unavailable")
    try:
        parent_guard = _open_directory_guard(profile.parent)
    except OSError as error:
        raise RecoveryRehearsalError(
            "target-boundary", "target parent boundary cannot be bound"
        ) from error
    try:
        parent_guard.assert_path_identity()
        for path in (*generated, profile, data):
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            except OSError as error:
                raise RecoveryRehearsalError(
                    "target-boundary", "target boundary cannot be inspected"
                ) from error
            raise RecoveryRehearsalError(
                "target-boundary", "target boundary already exists or is non-empty"
            )
        parent_guard.assert_path_identity()
    except Exception:
        parent_guard.close()
        raise
    return TargetPlan(
        profile=profile,
        data=data,
        database=database,
        parent_guard=parent_guard,
    )


def _create_target_directories(target: TargetPlan) -> None:
    try:
        target.profile_guard = target.parent_guard.create_directory(target.profile.name)
        target.data_guard = target.profile_guard.create_directory(target.data.name)
        target.assert_bound()
    except OSError as error:
        raise RecoveryRehearsalError(
            "restore-write", "fresh isolated target could not be created", target_mutated=True
        ) from error


def _write_exclusive_leaf(guard: _DirectoryGuard, name: str, payload: bytes) -> _RegularFileGuard:
    descriptor = guard.open_exclusive_leaf(name)
    try:
        view = memoryview(payload)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("created file could not be written")
            written += count
        os.fsync(descriptor)
        inspected = os.fstat(descriptor)
        identity = _file_identity(inspected)
        if identity is None or not stat.S_ISREG(inspected.st_mode) or inspected.st_nlink != 1:
            raise OSError("created file identity is unavailable")
        created = _RegularFileGuard(
            path=guard.path / name,
            identity=identity,
            descriptor=descriptor,
        )
        descriptor = -1
        guard.assert_path_identity()
        created.assert_path_identity()
        return created
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def _restore_snapshot(snapshot_bytes: bytes, target: TargetPlan) -> None:
    if target.data_guard is None:
        raise RecoveryRehearsalError(
            "restore-write", "isolated data boundary is unavailable", target_mutated=True
        )
    staging_guard: _RegularFileGuard | None = None
    database_guard: _RegularFileGuard | None = None
    try:
        staging_guard = _write_exclusive_leaf(target.data_guard, _STAGING_NAME, snapshot_bytes)
        staging_identity = staging_guard.identity
        staging_guard.assert_path_identity()
        target.data_guard.publish_no_overwrite(_STAGING_NAME, target.database.name)
        staging_guard.path = target.database
        staging_guard.assert_path_identity()
        database_guard = _open_regular_file_guard(target.database)
        if database_guard.identity != staging_identity:
            raise OSError("published database identity changed")
        staging_guard.assert_path_identity()
        target.database_identity = staging_identity
        target.database_guard = database_guard
        database_guard = None
        target.assert_bound()
    except OSError as error:
        raise RecoveryRehearsalError(
            "restore-write", "isolated database restore failed", target_mutated=True
        ) from error
    finally:
        if database_guard is not None:
            database_guard.close()
        if staging_guard is not None:
            staging_guard.close()


def _assert_restored_snapshot_hash(target: TargetPlan, *, expected_sha256: str, stage: str) -> None:
    if target.database_identity is None or target.database_guard is None:
        raise RecoveryRehearsalError(
            stage, "restored database identity is unavailable", target_mutated=True
        )
    descriptor = -1
    try:
        target.assert_bound()
        descriptor = _open_regular_read_only(target.database)
        inspected = os.fstat(descriptor)
        if (
            _file_identity(inspected) != target.database_identity
            or inspected.st_nlink != 1
            or _sha256_fd(descriptor) != expected_sha256
        ):
            raise OSError("restored snapshot bytes changed")
        target.assert_bound()
    except OSError as error:
        raise RecoveryRehearsalError(
            stage, "restored snapshot identity is invalid", target_mutated=True
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


@contextmanager
def _open_database_read_only(
    database: Path, *, expected_identity: tuple[int, int], stage: str
) -> Iterator[sqlite3.Connection]:
    guard: _RegularFileGuard | None = None
    connection: sqlite3.Connection | None = None
    try:
        guard = _open_regular_file_guard(database)
        if guard.identity != expected_identity:
            raise OSError("restored SQLite identity changed")
        guard.assert_path_identity()
        uri_path = database
        if guard.descriptor is not None:
            descriptor_path = Path(f"/proc/self/fd/{guard.descriptor}")
            if descriptor_path.exists():
                uri_path = descriptor_path
        connection = sqlite3.connect(f"{uri_path.as_uri()}?mode=ro&immutable=1", uri=True)
        rows = connection.execute("PRAGMA database_list").fetchall()
        main_paths = [str(path) for _, name, path in rows if name == "main"]
        if len(main_paths) != 1:
            raise sqlite3.DatabaseError("main database identity is unavailable")
        opened = Path(main_paths[0])
        opened_identity = _file_identity(opened.stat())
        if opened_identity != expected_identity:
            raise sqlite3.DatabaseError("SQLite opened an unexpected database")
        if uri_path == database and _path_key(opened) != _path_key(database):
            raise sqlite3.DatabaseError("SQLite opened an unexpected database")
        guard.assert_path_identity()
    except (OSError, ValueError, sqlite3.Error) as error:
        if connection is not None:
            connection.close()
        if guard is not None:
            guard.close()
        raise RecoveryRehearsalError(
            stage, "restored SQLite identity is invalid", target_mutated=True
        ) from error
    try:
        if connection is None:
            raise RecoveryRehearsalError(
                stage, "restored SQLite identity is invalid", target_mutated=True
            )
        yield connection
    finally:
        connection.close()
        if guard is not None:
            guard.close()


def _database_facts(
    database: Path,
    *,
    expected_identity: tuple[int, int],
    expected_revisions: tuple[str, ...],
    stage: str,
) -> tuple[tuple[str, ...], dict[str, int]]:
    try:
        with _open_database_read_only(
            database, expected_identity=expected_identity, stage=stage
        ) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise RecoveryRehearsalError(
                    stage, "restored SQLite integrity is invalid", target_mutated=True
                )
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RecoveryRehearsalError(
                    stage, "restored SQLite foreign keys are invalid", target_mutated=True
                )
            revisions = protected_backups._snapshot_revision_set(connection)
            if revisions != expected_revisions:
                raise RecoveryRehearsalError(
                    stage, "restored Alembic revision identity is invalid", target_mutated=True
                )
            rows = connection.execute(
                "SELECT type, name FROM sqlite_schema "
                "WHERE name NOT LIKE 'sqlite_%' AND name <> 'alembic_version' "
                "ORDER BY type, name"
            ).fetchall()
            tables = [str(name) for object_type, name in rows if object_type == "table"]
            indexes = [name for object_type, name in rows if object_type == "index"]
            views = [name for object_type, name in rows if object_type == "view"]
            populated = 0
            for table in tables:
                if (
                    connection.execute(
                        f"SELECT 1 FROM {_quote_identifier(table)} LIMIT 1"
                    ).fetchone()
                    is not None
                ):
                    populated += 1
            month_count = 0
            if "reporting_months" in tables:
                month_count = int(
                    connection.execute("SELECT COUNT(*) FROM reporting_months").fetchone()[0]
                )
    except RecoveryRehearsalError:
        raise
    except sqlite3.Error as error:
        raise RecoveryRehearsalError(
            stage, "restored SQLite structure is unreadable", target_mutated=True
        ) from error
    counts = {
        "user_table_count": len(tables),
        "user_index_count": len(indexes),
        "user_view_count": len(views),
        "populated_user_table_count": populated,
        "reporting_month_count": month_count,
    }
    return revisions, counts


def _write_sidecar(
    target: TargetPlan,
    *,
    source: VerifiedSource,
    checkout: CheckoutProof,
    compatibility: CompatibilityProof,
) -> None:
    sidecar = {
        "artifact_sha256": source.artifact_sha256,
        "kind": RECOVERY_PROFILE_KIND,
        "profile_id": "isolated-recovery",
        "schema_relationship": compatibility.relationship,
        "selected_recovery_sha": checkout.selected_sha,
        "source": "managed_recovery_point",
        "source_alembic_revisions": list(compatibility.source_revisions),
    }
    if target.data_guard is None:
        raise RecoveryRehearsalError(
            "restore-write", "isolated data boundary is unavailable", target_mutated=True
        )
    sidecar_guard: _RegularFileGuard | None = None
    try:
        sidecar_guard = _write_exclusive_leaf(
            target.data_guard,
            _SIDECAR_NAME,
            (
                json.dumps(sidecar, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8"),
        )
        target.assert_bound()
    except OSError as error:
        raise RecoveryRehearsalError(
            "restore-write", "recovery profile identity could not be written", target_mutated=True
        ) from error
    finally:
        if sidecar_guard is not None:
            sidecar_guard.close()


def _powershell() -> str:
    executable = shutil.which("powershell.exe")
    if executable is None:
        raise RecoveryRehearsalError(
            "runtime-prepare", "Windows PowerShell runtime is unavailable", target_mutated=True
        )
    return executable


def _run_runtime_script(
    checkout: CheckoutProof,
    *,
    script_name: str,
    arguments: list[str],
    stage: str,
    database: Path | None = None,
    environment_overrides: dict[str, str] | None = None,
    timeout: int,
) -> None:
    script = checkout.checkout / "scripts" / script_name
    boundary = checkout.checkout / "scripts" / "recovery-runtime-boundary.ps1"
    powershell = _powershell()
    environment = _isolated_runtime_environment(checkout, database=database)
    if environment_overrides:
        environment.update(environment_overrides)
    # A pwsh parent can prepend PowerShell 7 modules to PSModulePath. Windows
    # PowerShell then discovers those incompatible modules before its own and
    # loses built-ins such as Get-FileHash. The Owner runtime scripts only use
    # inbox modules, so bind the child to the selected executable's module set.
    environment["PSModulePath"] = str(Path(powershell).resolve().parent / "Modules")
    ownership_token = secrets.token_hex(32)
    try:
        completed = run_owned_process(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(boundary),
                "-Script",
                str(script),
                "-ArgumentsJson",
                json.dumps(arguments, ensure_ascii=True, separators=(",", ":")),
                "-OwnershipToken",
                ownership_token,
            ],
            cwd=checkout.checkout,
            environment=environment,
            ownership_token=ownership_token,
            timeout=timeout,
        )
    except ProcessTreeError as error:
        failure_stage = "runtime-cleanup" if error.reason.startswith("cleanup-") else stage
        raise RecoveryRehearsalError(
            failure_stage,
            "existing runtime operation could not complete safely",
            target_mutated=True,
        ) from error
    if completed.returncode != 0:
        failure_reason = None
        if script_name == "start-local.ps1" and stage == "runtime-start":
            failure_reason = _privacy_safe_readiness_failure_reason(
                completed.stdout, completed.stderr
            )
        raise RecoveryRehearsalError(
            stage,
            "existing runtime operation failed",
            target_mutated=True,
            failure_reason=failure_reason,
        )


def _prepare_and_validate(checkout: CheckoutProof) -> None:
    with _hold_prepare_boundary_guards(checkout):
        _run_runtime_script(
            checkout,
            script_name="prepare-runtime-dependencies.ps1",
            arguments=["-Checkout", str(checkout.checkout), "-Prepare"],
            stage="runtime-prepare",
            timeout=1200,
        )
        _validate_prepare_boundaries(checkout)
        _recheck_checkout(checkout, stage="runtime-prepare")
        with _hold_prepare_build_boundary_guards(checkout):
            _run_runtime_script(
                checkout,
                script_name="prepare-runtime.ps1",
                arguments=["-Checkout", str(checkout.checkout), "-Prepare"],
                stage="runtime-prepare",
                timeout=1200,
            )
            _validate_prepare_boundaries(checkout)
            _recheck_checkout(checkout, stage="runtime-prepare")
            _run_runtime_script(
                checkout,
                script_name="prepare-runtime.ps1",
                arguments=["-Checkout", str(checkout.checkout), "-Validate"],
                stage="runtime-validate",
                timeout=300,
            )
            _validate_prepare_boundaries(checkout)
            _recheck_checkout(checkout, stage="runtime-validate")


def _start_and_probe(
    checkout: CheckoutProof, target: TargetPlan, *, expected_snapshot_sha256: str
) -> None:
    if target.database_identity is None:
        raise RecoveryRehearsalError(
            "runtime-start", "restored database identity is unavailable", target_mutated=True
        )
    target.assert_bound()
    _assert_restored_snapshot_hash(
        target,
        expected_sha256=expected_snapshot_sha256,
        stage="pre-start-restored-snapshot",
    )
    _recheck_checkout(checkout, stage="runtime-start")
    readiness_token = secrets.token_hex(32)
    database_token = file_identity_token(target.database)
    _run_runtime_script(
        checkout,
        script_name="start-local.ps1",
        arguments=["-ExitAfterReady", "-RecoveryReadiness"],
        stage="runtime-start",
        database=target.database,
        environment_overrides={
            "HERMES_FINANCE_RECOVERY_READINESS_TOKEN": readiness_token,
            "HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY": database_token,
            "HERMES_FINANCE_RECOVERY_CHECKOUT_SHA": checkout.selected_sha,
        },
        timeout=120,
    )
    target.assert_bound()


def rehearse_recovery(
    recovery_point: Path,
    *,
    protection_state: str,
    protection_mode: str,
    selected_recovery_sha: str,
    recovery_checkout: Path,
    control_checkout: Path,
    runtime_config: Path,
    target_profile: Path,
    target_data: Path,
    target_database: Path,
) -> RecoveryRehearsalResult:
    """Verify, restore, prepare, and readiness-test one isolated recovery profile."""

    source = _verify_source(
        recovery_point,
        protection_state=protection_state,
        protection_mode=protection_mode,
    )
    target_mutated = False
    target: TargetPlan | None = None
    try:
        checkout = _validate_recovery_checkout(
            recovery_checkout, control_checkout, selected_recovery_sha
        )
        runtime_boundaries = _runtime_inventory(runtime_config)
        worktree_boundaries = _worktree_inventory(control_checkout)
        forbidden = (*runtime_boundaries, *worktree_boundaries)
        _assert_checkout_outside_forbidden(checkout, forbidden)
        _assert_source_outside_forbidden(source, forbidden)
        compatibility = _compatibility(
            checkout.checkout,
            tuple(source.manifest["source_alembic_revisions"]),
            str(source.manifest["producer_git_sha"]),
        )
        _validate_prepare_boundaries(checkout)
        target = _validate_fresh_target(
            target_profile=target_profile,
            target_data=target_data,
            target_database=target_database,
            source=source,
            checkout=checkout,
            forbidden=forbidden,
        )
        source.assert_unchanged()
        _recheck_checkout(checkout, stage="pre-restore-identity")

        _create_target_directories(target)
        target_mutated = True
        _restore_snapshot(source.snapshot_bytes, target)
        _write_sidecar(target, source=source, checkout=checkout, compatibility=compatibility)
        if target.database_identity is None:
            raise RecoveryRehearsalError(
                "restore-write", "restored database identity is unavailable", target_mutated=True
            )
        _database_facts(
            target.database,
            expected_identity=target.database_identity,
            expected_revisions=compatibility.source_revisions,
            stage="restored-database-validation",
        )
        expected_snapshot_sha256 = str(source.manifest["snapshot_sha256"])
        _assert_restored_snapshot_hash(
            target,
            expected_sha256=expected_snapshot_sha256,
            stage="pre-prepare-restored-snapshot",
        )
        source.assert_unchanged()

        _prepare_and_validate(checkout)
        source.assert_unchanged()
        _start_and_probe(
            checkout,
            target,
            expected_snapshot_sha256=expected_snapshot_sha256,
        )
        resulting_revisions, structural_counts = _database_facts(
            target.database,
            expected_identity=target.database_identity,
            expected_revisions=compatibility.selected_heads,
            stage="result-validation",
        )
        source.assert_unchanged()
        _recheck_checkout(checkout, stage="result-validation")
        destination_alias = protection_destination_alias(protection_state, protection_mode)
        return RecoveryRehearsalResult(
            status="rehearsed",
            source_verified=True,
            source_unchanged=True,
            restored=True,
            prepared=True,
            validated=True,
            readiness="verified",
            destination_alias=destination_alias,
            protection_state=protection_state,
            protection_mode=protection_mode,
            format_version=FORMAT_VERSION,
            artifact_sha256=source.artifact_sha256,
            artifact_identity_sha256=str(source.manifest["artifact_identity_sha256"]),
            snapshot_sha256=str(source.manifest["snapshot_sha256"]),
            producer_git_sha=str(source.manifest["producer_git_sha"]),
            source_alembic_revisions=compatibility.source_revisions,
            selected_recovery_sha=checkout.selected_sha,
            selected_checkout_heads=compatibility.selected_heads,
            schema_relationship=compatibility.relationship,
            resulting_alembic_revisions=resulting_revisions,
            structural_counts=structural_counts,
            action_required=None,
        )
    except RecoveryRehearsalError as error:
        if target_mutated and not error.target_mutated:
            error.target_mutated = True
        raise
    finally:
        if target is not None:
            target.close()
        source.close()
