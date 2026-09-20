"""Managed protected-destination recovery-point publication (ADR 0017)."""

from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import uuid
import zipfile
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

from hermes_finance.database import Database
from hermes_finance.services.backups import (
    BackupStorageError,
    _create_online_snapshot,
    _validate_sqlite_backup,
    backup_directory,
)

PROTECTION_STATE = "protected"
PROTECTION_MODE = "external_encrypted_destination_v1"
FORMAT_VERSION = 1
DESTINATION_ALIAS = "protected-destination"
MANAGED_FILENAME_PREFIX = "hermes_recovery_"
MANAGED_FILENAME_SUFFIX = ".hermes-recovery"
VERIFIED_RETENTION_LIMIT = 12
RETENTION_COMPLETED = "completed"
RETENTION_FAILED = "failed"
RETENTION_NOT_RUN = "not_run"
RETENTION_ACTION_REQUIRED = "protected recovery-point retention was not completed"
_MANAGED_FILENAME_RE = re.compile(
    rf"^{re.escape(MANAGED_FILENAME_PREFIX)}"
    rf"(?P<timestamp>\d{{8}}T\d{{12}}Z)"
    rf"-(?P<digest>[0-9a-f]{{16}})"
    rf"(?:-(?P<sequence>\d+))?{re.escape(MANAGED_FILENAME_SUFFIX)}$"
)
_INCOMPLETE_PREFIX = ".hermes_recovery_"
_INCOMPLETE_SUFFIX = ".incomplete"
_LOCK_NAME = ".hermes_recovery.lock"
_FILENAME_CREATED_AT_FORMAT = "%Y%m%dT%H%M%S%fZ"
_SNAPSHOT_NAME = "snapshot.sqlite3"
_MANIFEST_NAME = "manifest.json"
_ZERO_DIGEST = "0" * 64
_REPARSE_POINT = 0x400


class ProtectedBackupError(RuntimeError):
    """A protected recovery-point operation failed closed."""


@dataclass(frozen=True, slots=True)
class ProtectedBackupResult:
    status: str
    created: bool
    verified: bool
    published: bool
    destination_alias: str
    protection_state: str
    protection_mode: str
    format_version: int
    created_at: datetime | None
    size_bytes: int | None
    read_back: str
    retention: str
    action_required: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "created": self.created,
            "verified": self.verified,
            "published": self.published,
            "destination_alias": self.destination_alias,
            "protection_state": self.protection_state,
            "protection_mode": self.protection_mode,
            "format_version": self.format_version,
            "created_at": (
                self.created_at.isoformat().replace("+00:00", "Z")
                if self.created_at is not None
                else None
            ),
            "size_bytes": self.size_bytes,
            "read_back": self.read_back,
            "retention": self.retention,
            "action_required": self.action_required,
        }


def _normalized_now(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().absolute()))


def _is_reparse(path: Path) -> bool:
    try:
        stat_result = path.lstat()
    except OSError as error:
        raise ProtectedBackupError("destination path cannot be inspected") from error
    return path.is_symlink() or bool(getattr(stat_result, "st_file_attributes", 0) & _REPARSE_POINT)


def _assert_no_reparse_components(path: Path) -> None:
    """Inspect supplied path components before resolving aliases."""
    absolute = Path(os.path.abspath(os.path.expanduser(str(path))))
    components: list[Path] = []
    current = absolute
    while True:
        components.append(current)
        if current.parent == current:
            break
        current = current.parent
    for component in reversed(components):
        if component.exists() and _is_reparse(component):
            raise ProtectedBackupError("destination boundary is a reparse path")


def _path_is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise ProtectedBackupError("destination Git boundary cannot be inspected") from error
    return True


def _assert_outside_git_boundaries(path: Path) -> None:
    """Reject a destination at or below any repository/worktree boundary."""
    current = path
    while True:
        marker = current / ".git"
        if _entry_exists(marker):
            raise ProtectedBackupError(
                "destination is inside a Git repository or worktree boundary"
            )
        if (
            _entry_exists(current / "HEAD")
            and _entry_exists(current / "objects")
            and _entry_exists(current / "refs")
        ):
            raise ProtectedBackupError("destination is inside a Git repository boundary")
        if current.parent == current:
            break
        current = current.parent


def _validate_destination(destination: Path, database: Database, source_checkout: Path) -> Path:
    _assert_no_reparse_components(destination)
    resolved = destination.expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise ProtectedBackupError("destination is not an existing directory")
    _assert_no_reparse_components(resolved)
    _assert_outside_git_boundaries(resolved)

    db_parent = database.database_path.expanduser().resolve().parent
    local_backup = backup_directory(database).expanduser().resolve()
    checkout = source_checkout.expanduser().resolve()
    if resolved == db_parent or resolved == local_backup:
        raise ProtectedBackupError("destination is inside the local runtime backup boundary")
    if (
        _path_is_within(resolved, db_parent)
        or _path_is_within(db_parent, resolved)
        or _path_is_within(resolved, local_backup)
        or _path_is_within(local_backup, resolved)
        or _path_is_within(resolved, checkout)
        or _path_is_within(checkout, resolved)
    ):
        raise ProtectedBackupError("destination is inside a runtime or source boundary")
    probe = resolved / f".hermes-destination-probe-{uuid.uuid4().hex}"
    try:
        descriptor = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, "w+b") as stream:
            stream.write(b"ok")
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
            if stream.read() != b"ok":
                raise ProtectedBackupError("destination is not readable and writable")
        probe.unlink()
    except (OSError, PermissionError) as error:
        try:
            probe.unlink()
        except OSError:
            pass
        raise ProtectedBackupError("destination is not readable and writable") from error
    return resolved


def _git_identity(checkout: Path) -> str:
    try:
        top_level = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=checkout,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        head = (
            subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD^{commit}"],
                cwd=checkout,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            .stdout.strip()
            .lower()
        )
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=checkout,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise ProtectedBackupError("producer checkout identity is unavailable") from error
    if _path_key(Path(top_level)) != _path_key(checkout) or status:
        raise ProtectedBackupError("producer checkout identity is not clean")
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ProtectedBackupError("producer checkout identity is not a full Git SHA")
    return head


def _executing_checkout() -> Path:
    """Return the repository checkout containing the loaded publisher code."""
    checkout = Path(__file__).resolve().parents[4]
    if not (checkout / "backend" / "pyproject.toml").is_file():
        raise ProtectedBackupError("executing publisher checkout is unavailable")
    return checkout


def _producer_checkout(explicit_checkout: Path | None) -> Path:
    """Bind producer identity to executing code; an explicit path is only a guard."""
    executing = _executing_checkout()
    if explicit_checkout is not None:
        supplied = explicit_checkout.expanduser().resolve()
        if _path_key(supplied) != _path_key(executing):
            raise ProtectedBackupError(
                "explicit producer checkout does not match executing publisher checkout"
            )
    return executing


def _script_directory(checkout: Path) -> ScriptDirectory:
    config_path = checkout / "backend" / "alembic.ini"
    if not config_path.is_file():
        raise ProtectedBackupError("producer checkout Alembic configuration is unavailable")
    try:
        return ScriptDirectory.from_config(Config(str(config_path)))
    except Exception as error:  # pragma: no cover - Alembic has varied exception types
        raise ProtectedBackupError("producer checkout Alembic graph is unavailable") from error


def _source_revisions(snapshot: Path, checkout: Path) -> tuple[str, ...]:
    try:
        connection = sqlite3.connect(f"file:{snapshot.resolve().as_posix()}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT version_num FROM alembic_version ORDER BY version_num"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise ProtectedBackupError("snapshot Alembic revision set is unreadable") from error
    revisions = tuple(sorted({str(row[0]) for row in rows}))
    if not revisions or any(not revision for revision in revisions):
        raise ProtectedBackupError("snapshot Alembic revision set is missing")
    script = _script_directory(checkout)
    try:
        if any(script.get_revision(revision) is None for revision in revisions):
            raise ProtectedBackupError("snapshot Alembic revision is unknown to producer checkout")
    except ProtectedBackupError:
        raise
    except Exception as error:  # pragma: no cover - defensive Alembic boundary
        raise ProtectedBackupError("snapshot Alembic revision set is invalid") from error
    return revisions


def _snapshot(database: Database, destination: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f"{_INCOMPLETE_PREFIX}{uuid.uuid4().hex}-", suffix=".sqlite3", dir=destination
    )
    os.close(descriptor)
    snapshot = Path(name)
    try:
        _create_online_snapshot(database, snapshot)
        _validate_sqlite_backup(snapshot, database)
        return snapshot
    except (OSError, sqlite3.Error, ValueError, ProtectedBackupError, BackupStorageError) as error:
        raise ProtectedBackupError("consistent SQLite snapshot validation failed") from error


def _snapshot_identity(snapshot: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with snapshot.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _zip_bytes(snapshot: Path, manifest: dict[str, Any]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in (
            (_MANIFEST_NAME, _canonical_json(manifest)),
            (_SNAPSHOT_NAME, snapshot.read_bytes()),
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, payload)
    return output.getvalue()


def _artifact_bytes(snapshot: Path, manifest: dict[str, Any]) -> bytes:
    """Build deterministic bytes with a non-self-referential identity hash."""
    working = dict(manifest)
    while True:
        identity_manifest = dict(working)
        identity_manifest["artifact_identity_sha256"] = _ZERO_DIGEST
        identity = hashlib.sha256(_zip_bytes(snapshot, identity_manifest)).hexdigest()
        final_manifest = dict(working)
        final_manifest["artifact_identity_sha256"] = identity
        artifact = _zip_bytes(snapshot, final_manifest)
        if final_manifest["artifact_size_bytes"] == len(artifact):
            return artifact
        working["artifact_size_bytes"] = len(artifact)


def _validate_manifest_shape(manifest: dict[str, Any]) -> None:
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ProtectedBackupError("managed artifact format identity is invalid")
    if manifest.get("protection_mode") != PROTECTION_MODE:
        raise ProtectedBackupError("managed artifact protection identity is invalid")
    if manifest.get("protection_state") != PROTECTION_STATE:
        raise ProtectedBackupError("managed artifact protection state is invalid")
    producer_sha = manifest.get("producer_git_sha")
    if not isinstance(producer_sha, str) or re.fullmatch(r"[0-9a-f]{40}", producer_sha) is None:
        raise ProtectedBackupError("managed artifact producer identity is invalid")
    revisions = manifest.get("source_alembic_revisions")
    if (
        not isinstance(revisions, list)
        or not revisions
        or any(not isinstance(revision, str) or not revision for revision in revisions)
        or revisions != sorted(set(revisions))
    ):
        raise ProtectedBackupError("managed artifact Alembic revision identity is invalid")
    artifact_size = manifest.get("artifact_size_bytes")
    if not isinstance(artifact_size, int) or artifact_size <= 0:
        raise ProtectedBackupError("managed artifact size identity is invalid")


def _snapshot_revision_set(connection: sqlite3.Connection) -> tuple[str, ...]:
    try:
        rows = connection.execute(
            "SELECT version_num FROM alembic_version ORDER BY version_num"
        ).fetchall()
    except sqlite3.Error as error:
        raise ProtectedBackupError("managed artifact Alembic revision set is unreadable") from error
    revisions = tuple(sorted({str(row[0]) for row in rows}))
    if not revisions or any(not revision for revision in revisions):
        raise ProtectedBackupError("managed artifact Alembic revision set is missing")
    return revisions


def _verify_snapshot_bytes(snapshot_bytes: bytes) -> tuple[str, ...]:
    """Verify a snapshot without materializing plaintext outside the artifact."""

    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(snapshot_bytes)
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ProtectedBackupError("managed artifact SQLite integrity is invalid")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ProtectedBackupError("managed artifact SQLite foreign keys are invalid")
        return _snapshot_revision_set(connection)
    finally:
        connection.close()


def _verify_payload(
    artifact_bytes: bytes, *, expected_hash: str | None = None
) -> tuple[dict[str, Any], str, int]:
    actual = hashlib.sha256(artifact_bytes).hexdigest()
    if expected_hash is not None and actual != expected_hash:
        raise ProtectedBackupError("managed artifact full hash does not verify")
    size_bytes = len(artifact_bytes)
    with zipfile.ZipFile(io.BytesIO(artifact_bytes), "r") as archive:
        if archive.namelist() != [_MANIFEST_NAME, _SNAPSHOT_NAME]:
            raise ProtectedBackupError("managed artifact members are invalid")
        manifest = json.loads(archive.read(_MANIFEST_NAME))
        if not isinstance(manifest, dict):
            raise ProtectedBackupError("managed artifact manifest is invalid")
        _validate_manifest_shape(manifest)
        snapshot_bytes = archive.read(_SNAPSHOT_NAME)
        snapshot_digest = hashlib.sha256(snapshot_bytes).hexdigest()
        if manifest.get("snapshot_sha256") != snapshot_digest:
            raise ProtectedBackupError("managed artifact snapshot hash is invalid")
        if manifest.get("snapshot_size_bytes") != len(snapshot_bytes):
            raise ProtectedBackupError("managed artifact snapshot size is invalid")
        snapshot_revisions = _verify_snapshot_bytes(snapshot_bytes)
        if manifest.get("source_alembic_revisions") != list(snapshot_revisions):
            raise ProtectedBackupError("managed artifact Alembic revision identity does not verify")
    normalized = dict(manifest)
    expected = normalized.get("artifact_identity_sha256")
    normalized["artifact_identity_sha256"] = _ZERO_DIGEST
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ProtectedBackupError("managed artifact canonical identity is invalid")
    if hashlib.sha256(_zip_bytes_from_bytes(snapshot_bytes, normalized)).hexdigest() != expected:
        raise ProtectedBackupError("managed artifact canonical identity does not verify")
    if manifest.get("artifact_size_bytes") != size_bytes:
        raise ProtectedBackupError("managed artifact size does not verify")
    return manifest, actual, size_bytes


def _verify_artifact_content(
    path: Path, *, expected_hash: str | None = None
) -> tuple[dict[str, Any], str, int]:
    try:
        _assert_no_reparse_components(path)
        if not path.is_file() or path.is_symlink():
            raise ProtectedBackupError("managed artifact is not a regular file")
        return _verify_payload(path.read_bytes(), expected_hash=expected_hash)
    except (OSError, KeyError, json.JSONDecodeError, sqlite3.Error, zipfile.BadZipFile) as error:
        raise ProtectedBackupError("managed artifact read-back verification failed") from error


def _verify_artifact(
    path: Path, *, expected_hash: str | None = None
) -> tuple[dict[str, Any], str, int]:
    manifest, actual, size_bytes = _verify_artifact_content(path, expected_hash=expected_hash)
    name_match = _MANAGED_FILENAME_RE.fullmatch(path.name)
    if name_match is None or name_match.group("digest") != actual[:16]:
        raise ProtectedBackupError("managed artifact name identity does not verify")
    return manifest, actual, size_bytes


def _zip_bytes_from_bytes(snapshot_bytes: bytes, manifest: dict[str, Any]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in (
            (_MANIFEST_NAME, _canonical_json(manifest)),
            (_SNAPSHOT_NAME, snapshot_bytes),
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, payload)
    return output.getvalue()


def _managed_name(created_at: datetime, digest: str, destination: Path) -> Path:
    stem = f"{MANAGED_FILENAME_PREFIX}{created_at.strftime('%Y%m%dT%H%M%S%fZ')}-{digest[:16]}"
    candidate = destination / f"{stem}{MANAGED_FILENAME_SUFFIX}"
    sequence = 0
    while candidate.exists():
        sequence += 1
        candidate = destination / f"{stem}-{sequence}{MANAGED_FILENAME_SUFFIX}"
    return candidate


def _expose_final_without_overwrite(
    staged: Path, created_at: datetime, digest: str, destination: Path
) -> Path:
    """Expose a completed artifact without replacing an existing final name."""
    sequence = 0
    while sequence < 10_000:
        suffix = "" if sequence == 0 else f"-{sequence}"
        final = destination / (
            f"{MANAGED_FILENAME_PREFIX}{created_at.strftime('%Y%m%dT%H%M%S%fZ')}"
            f"-{digest[:16]}{suffix}{MANAGED_FILENAME_SUFFIX}"
        )
        try:
            if final.exists():
                sequence += 1
                continue
            os.rename(staged, final)
            return final
        except FileExistsError:
            sequence += 1
            continue
        except OSError as error:
            raise ProtectedBackupError("atomic final exposure is unavailable") from error
    raise ProtectedBackupError("managed final-name space is exhausted")


class _DestinationLock:
    def __init__(self, destination: Path) -> None:
        self.path = destination / _LOCK_NAME
        self._held = False

    def __enter__(self) -> "_DestinationLock":
        descriptor = None
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
            os.close(descriptor)
            descriptor = None
            self._held = True
        except (FileExistsError, OSError) as error:
            if descriptor is not None:
                os.close(descriptor)
                self.path.unlink(missing_ok=True)
            raise ProtectedBackupError("destination lock is contended or stale") from error
        return self

    def __exit__(self, *_: object) -> None:
        if self._held:
            try:
                self.path.unlink()
            except OSError:
                pass


def is_managed_recovery_name(name: str) -> bool:
    """Return whether a name is the exact managed final-name shape."""

    return _MANAGED_FILENAME_RE.fullmatch(name) is not None


def _destination_listing(destination: Path) -> list[str]:
    try:
        names = os.listdir(destination)
    except OSError as error:
        raise ProtectedBackupError("destination listing is unavailable") from error
    names.sort()
    return names


def _is_regular_managed_file(path: Path) -> bool:
    if not is_managed_recovery_name(path.name):
        return False
    try:
        if _is_reparse(path) or path.is_symlink() or not path.is_file():
            return False
    except (OSError, ProtectedBackupError):
        return False
    return True


def _regular_file_open_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _file_identity(stat_result: os.stat_result) -> tuple[int, int] | None:
    inode = int(getattr(stat_result, "st_ino", 0) or 0)
    device = int(getattr(stat_result, "st_dev", 0) or 0)
    if inode == 0:
        return None
    if sys.platform == "win32":
        device &= 0xFFFFFFFF
    return (device, inode)


def _read_fd(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_filename_created_at(timestamp: str) -> datetime | None:
    try:
        parsed = datetime.strptime(timestamp, _FILENAME_CREATED_AT_FORMAT)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC)


def _parse_manifest_created_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _bound_retention_created_at(name: str, manifest: dict[str, Any]) -> datetime | None:
    """Bind filename timestamp to verified manifest created_at, or reject."""

    match = _MANAGED_FILENAME_RE.fullmatch(name)
    if match is None:
        return None
    from_name = _parse_filename_created_at(match.group("timestamp"))
    from_manifest = _parse_manifest_created_at(manifest.get("created_at"))
    if from_name is None or from_manifest is None or from_name != from_manifest:
        return None
    return from_manifest


def _managed_sequence(name: str) -> int:
    match = _MANAGED_FILENAME_RE.fullmatch(name)
    if match is None or match.group("sequence") is None:
        return 0
    return int(match.group("sequence"))


@dataclass(frozen=True, slots=True)
class _RetentionCandidate:
    path: Path
    created_at: datetime
    artifact_hash: str
    sequence: int
    name: str
    file_id: tuple[int, int]

    def recency_key(self) -> tuple[datetime, str, int, str]:
        """Oldest-first verified identity.

        Newest-first is the reverse of this tuple. After created_at, ties break
        by full artifact SHA-256, then managed sequence (absent = 0), then name.
        """

        return (self.created_at, self.artifact_hash, self.sequence, self.name)


def _inspect_retention_candidate(path: Path) -> _RetentionCandidate | None:
    if not _is_regular_managed_file(path):
        return None
    match = _MANAGED_FILENAME_RE.fullmatch(path.name)
    if match is None:
        return None
    try:
        link_stat = path.lstat()
        file_id = _file_identity(link_stat)
        if file_id is None:
            return None
        fd = os.open(path, _regular_file_open_flags())
    except (OSError, ProtectedBackupError):
        return None
    try:
        opened_id = _file_identity(os.fstat(fd))
        if opened_id != file_id:
            return None
        payload = _read_fd(fd)
        manifest, artifact_hash, _size = _verify_payload(payload)
    except (
        OSError,
        ProtectedBackupError,
        KeyError,
        json.JSONDecodeError,
        sqlite3.Error,
        zipfile.BadZipFile,
    ):
        return None
    finally:
        os.close(fd)
    if match.group("digest") != artifact_hash[:16]:
        return None
    created_at = _bound_retention_created_at(path.name, manifest)
    if created_at is None:
        return None
    return _RetentionCandidate(
        path=path,
        created_at=created_at,
        artifact_hash=artifact_hash,
        sequence=_managed_sequence(path.name),
        name=path.name,
        file_id=file_id,
    )


def _list_retention_candidates(destination: Path) -> list[_RetentionCandidate]:
    """Return deletion-eligible verified points, oldest first."""

    candidates = [
        candidate
        for name in _destination_listing(destination)
        if (candidate := _inspect_retention_candidate(destination / name)) is not None
    ]
    candidates.sort(key=lambda item: item.recency_key())
    return candidates


def _verified_managed_recovery_points(destination: Path) -> list[Path]:
    """Return retention-eligible verified artifacts only, oldest first."""

    return [candidate.path for candidate in _list_retention_candidates(destination)]


_GENERIC_READ = 0x80000000
_DELETE_ACCESS = 0x00010000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_EXISTING = 3
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_NORMAL = 0x80
_FILE_BEGIN = 0
_FILE_DISPOSITION_INFO = 4
_AT_EMPTY_PATH = 0x1000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_KERNEL32: ctypes.WinDLL | None = None


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class _FILE_DISPOSITION_INFO_STRUCT(ctypes.Structure):
    _fields_ = [("DeleteFile", wintypes.BOOLEAN)]


@dataclass(slots=True)
class _DeletionTarget:
    candidate: _RetentionCandidate
    handle: int
    kind: str
    closed: bool = False


def _object_bound_deletion_supported() -> bool:
    return sys.platform == "win32" or sys.platform.startswith("linux")


def _windows_kernel32() -> ctypes.WinDLL:
    global _KERNEL32
    if _KERNEL32 is not None:
        return _KERNEL32
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.SetFilePointerEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    ]
    kernel32.SetFilePointerEx.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    _KERNEL32 = kernel32
    return kernel32


def _win_raise(action: str) -> None:
    raise OSError(None, action, None, ctypes.get_last_error())


def _win_handle_identity(handle: int) -> tuple[int, int] | None:
    info = _BY_HANDLE_FILE_INFORMATION()
    if not _windows_kernel32().GetFileInformationByHandle(handle, ctypes.byref(info)):
        return None
    file_index = (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow)
    if file_index == 0:
        return None
    return (int(info.dwVolumeSerialNumber), file_index)


def _win_read_handle(handle: int) -> bytes:
    kernel32 = _windows_kernel32()
    new_position = ctypes.c_longlong(0)
    if not kernel32.SetFilePointerEx(handle, 0, ctypes.byref(new_position), _FILE_BEGIN):
        _win_raise("SetFilePointerEx")
    chunks: list[bytes] = []
    buffer = ctypes.create_string_buffer(1024 * 1024)
    read = wintypes.DWORD(0)
    while True:
        if not kernel32.ReadFile(handle, buffer, len(buffer), ctypes.byref(read), None):
            _win_raise("ReadFile")
        if read.value == 0:
            break
        chunks.append(buffer.raw[: read.value])
    return b"".join(chunks)


def _open_windows_deletion_target(candidate: _RetentionCandidate) -> _DeletionTarget:
    kernel32 = _windows_kernel32()
    handle = kernel32.CreateFileW(
        os.fspath(candidate.path),
        _GENERIC_READ | _DELETE_ACCESS,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if ctypes.c_void_p(handle).value in {None, _INVALID_HANDLE_VALUE}:
        _win_raise("CreateFileW")
    try:
        file_id = _win_handle_identity(handle)
        if file_id is None or file_id != candidate.file_id:
            raise ProtectedBackupError("retention identity is not proven")
        digest = hashlib.sha256(_win_read_handle(handle)).hexdigest()
        if digest != candidate.artifact_hash:
            raise ProtectedBackupError("retention identity is not proven")
        return _DeletionTarget(candidate=candidate, handle=int(handle), kind="windows")
    except Exception:
        kernel32.CloseHandle(handle)
        raise


def _open_posix_deletion_target(candidate: _RetentionCandidate) -> _DeletionTarget:
    fd = os.open(candidate.path, _regular_file_open_flags())
    try:
        file_id = _file_identity(os.fstat(fd))
        if file_id is None or file_id != candidate.file_id:
            raise ProtectedBackupError("retention identity is not proven")
        digest = hashlib.sha256(_read_fd(fd)).hexdigest()
        if digest != candidate.artifact_hash:
            raise ProtectedBackupError("retention identity is not proven")
        return _DeletionTarget(candidate=candidate, handle=fd, kind="posix")
    except Exception:
        os.close(fd)
        raise


def _open_deletion_target(candidate: _RetentionCandidate) -> _DeletionTarget:
    if not is_managed_recovery_name(candidate.path.name) or candidate.path.name != candidate.name:
        raise ProtectedBackupError("retention identity is not proven")
    if sys.platform == "win32":
        return _open_windows_deletion_target(candidate)
    if sys.platform.startswith("linux"):
        return _open_posix_deletion_target(candidate)
    raise ProtectedBackupError("retention identity is not proven")


def _deletion_target_identity(target: _DeletionTarget) -> tuple[int, int] | None:
    if target.kind == "windows":
        return _win_handle_identity(target.handle)
    return _file_identity(os.fstat(target.handle))


def _deletion_target_hash(target: _DeletionTarget) -> str:
    if target.kind == "windows":
        return hashlib.sha256(_win_read_handle(target.handle)).hexdigest()
    os.lseek(target.handle, 0, os.SEEK_SET)
    return hashlib.sha256(_read_fd(target.handle)).hexdigest()


def _revalidate_deletion_target(target: _DeletionTarget) -> None:
    """Prove the open handle is still the verified object before destruction."""

    handle_id = _deletion_target_identity(target)
    if handle_id is None or handle_id != target.candidate.file_id:
        raise ProtectedBackupError("retention identity is not proven")
    try:
        path_id = _file_identity(target.candidate.path.lstat())
    except OSError as error:
        raise ProtectedBackupError("retention identity is not proven") from error
    if path_id != handle_id:
        raise ProtectedBackupError("retention identity is not proven")
    if _deletion_target_hash(target) != target.candidate.artifact_hash:
        raise ProtectedBackupError("retention identity is not proven")


def _mark_deletion_target(target: _DeletionTarget) -> None:
    """Delete the object named by the verified handle, not by pathname."""

    if target.kind == "windows":
        info = _FILE_DISPOSITION_INFO_STRUCT(True)
        if not _windows_kernel32().SetFileInformationByHandle(
            target.handle,
            _FILE_DISPOSITION_INFO,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            _win_raise("SetFileInformationByHandle")
        return
    libc = ctypes.CDLL(None, use_errno=True)
    libc.unlinkat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    libc.unlinkat.restype = ctypes.c_int
    if libc.unlinkat(target.handle, b"", _AT_EMPTY_PATH) != 0:
        raise OSError(ctypes.get_errno(), "unlinkat")


def _close_deletion_target(target: _DeletionTarget) -> None:
    if target.closed:
        return
    target.closed = True
    if target.kind == "windows":
        _windows_kernel32().CloseHandle(target.handle)
        return
    os.close(target.handle)


def _retention_before_destroy(_targets: list[_DeletionTarget]) -> None:
    """Test hook after handle verification and before handle-bound destruction."""

    return


def _commit_retention_deletions(candidates: list[_RetentionCandidate]) -> None:
    """Delete verified objects through the same handle that proved them."""

    if not candidates:
        return
    if not _object_bound_deletion_supported():
        raise ProtectedBackupError("retention identity is not proven")
    targets: list[_DeletionTarget] = []
    try:
        for candidate in candidates:
            targets.append(_open_deletion_target(candidate))
        _retention_before_destroy(targets)
        for target in targets:
            _revalidate_deletion_target(target)
        for target in targets:
            _mark_deletion_target(target)
    finally:
        for target in targets:
            try:
                _close_deletion_target(target)
            except OSError:
                pass


def _select_retention_deletions(
    candidates: list[_RetentionCandidate], *, preserve: Path
) -> list[_RetentionCandidate]:
    """Keep preserve plus the newest others, for an exact verified set of 12."""

    preserve_key = _path_key(preserve)
    matched = [item for item in candidates if _path_key(item.path) == preserve_key]
    if len(matched) != 1:
        raise ProtectedBackupError("required replacement is not retention-eligible")
    others = [item for item in candidates if _path_key(item.path) != preserve_key]
    others.sort(key=lambda item: item.recency_key(), reverse=True)
    return others[VERIFIED_RETENTION_LIMIT - 1 :]


def _retain_verified_recovery_points(
    destination: Path, *, preserve: Path
) -> tuple[str, str | None]:
    """Keep exactly 12 verified managed points, including the replacement."""

    try:
        candidates = _list_retention_candidates(destination)
        to_delete = _select_retention_deletions(candidates, preserve=preserve)
        _commit_retention_deletions(to_delete)
        remaining = _list_retention_candidates(destination)
        if len(remaining) > VERIFIED_RETENTION_LIMIT:
            return RETENTION_FAILED, RETENTION_ACTION_REQUIRED
        return RETENTION_COMPLETED, None
    except Exception:
        # A verified replacement must stay valid even if cleanup cannot finish.
        return RETENTION_FAILED, RETENTION_ACTION_REQUIRED


def publish_recovery_point(
    database: Database,
    destination: Path,
    *,
    protection_state: str,
    protection_mode: str,
    source_checkout: Path | None = None,
    now: datetime | None = None,
) -> ProtectedBackupResult:
    """Publish one verified recovery point to an already-mounted destination."""

    created_at = _normalized_now(now)
    if protection_state != PROTECTION_STATE or protection_mode != PROTECTION_MODE:
        raise ProtectedBackupError("unsupported protection mode")
    checkout = _producer_checkout(source_checkout)
    validated_destination = _validate_destination(destination, database, checkout)
    producer_sha = _git_identity(checkout)

    with database.maintenance.operation():
        with _DestinationLock(validated_destination):
            snapshot = _snapshot(database, validated_destination)
            final: Path | None = None
            size_bytes: int | None = None
            try:
                revisions = _source_revisions(snapshot, checkout)
                snapshot_hash, snapshot_size = _snapshot_identity(snapshot)
                manifest = {
                    "artifact_identity_sha256": _ZERO_DIGEST,
                    "artifact_size_bytes": 0,
                    "created_at": created_at.isoformat().replace("+00:00", "Z"),
                    "format_version": FORMAT_VERSION,
                    "producer_git_sha": producer_sha,
                    "protection_state": PROTECTION_STATE,
                    "protection_mode": PROTECTION_MODE,
                    "snapshot_sha256": snapshot_hash,
                    "snapshot_size_bytes": snapshot_size,
                    "source_alembic_revisions": list(revisions),
                }
                artifact_bytes = _artifact_bytes(snapshot, manifest)
                expected_artifact_hash = hashlib.sha256(artifact_bytes).hexdigest()
                staged = validated_destination / (
                    f"{_INCOMPLETE_PREFIX}{uuid.uuid4().hex}{_INCOMPLETE_SUFFIX}"
                )
                with staged.open("xb") as stream:
                    stream.write(artifact_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                staged_manifest, staged_hash, staged_size = _verify_artifact_content(
                    staged, expected_hash=expected_artifact_hash
                )
                if staged_hash != expected_artifact_hash:
                    raise ProtectedBackupError("staged artifact full hash changed")
                for key, value in manifest.items():
                    if (
                        key not in {"artifact_identity_sha256", "artifact_size_bytes"}
                        and staged_manifest.get(key) != value
                    ):
                        raise ProtectedBackupError("staged artifact manifest changed")
                if staged_manifest.get("artifact_size_bytes") != staged_size:
                    raise ProtectedBackupError("staged artifact size changed")
                final = _expose_final_without_overwrite(
                    staged, created_at, expected_artifact_hash, validated_destination
                )
                read_manifest, read_hash, size_bytes = _verify_artifact(
                    final, expected_hash=expected_artifact_hash
                )
                if read_hash != expected_artifact_hash:
                    raise ProtectedBackupError("managed artifact full hash changed on read-back")
                for key, value in manifest.items():
                    if (
                        key not in {"artifact_identity_sha256", "artifact_size_bytes"}
                        and read_manifest.get(key) != value
                    ):
                        raise ProtectedBackupError("managed artifact manifest changed on read-back")
                if read_manifest.get("artifact_size_bytes") != size_bytes:
                    raise ProtectedBackupError("managed artifact size changed on read-back")
            except (OSError, ProtectedBackupError) as error:
                if final is not None and final.exists():
                    final.unlink(missing_ok=True)
                raise ProtectedBackupError("recovery-point publication failed") from error
            finally:
                snapshot.unlink(missing_ok=True)

            if final is None or size_bytes is None:
                raise ProtectedBackupError("recovery-point publication failed")
            retention, retention_action = _retain_verified_recovery_points(
                validated_destination, preserve=final
            )
            return ProtectedBackupResult(
                status="published",
                created=True,
                verified=True,
                published=True,
                destination_alias=DESTINATION_ALIAS,
                protection_state=PROTECTION_STATE,
                protection_mode=PROTECTION_MODE,
                format_version=FORMAT_VERSION,
                created_at=created_at,
                size_bytes=size_bytes,
                read_back="verified",
                retention=retention,
                action_required=retention_action,
            )
