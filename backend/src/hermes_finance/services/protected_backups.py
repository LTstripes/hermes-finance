"""Managed protected-destination recovery-point publication (ADR 0017)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import uuid
import zipfile
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
_MANAGED_FILENAME_RE = re.compile(
    rf"^{re.escape(MANAGED_FILENAME_PREFIX)}"
    rf"(?P<timestamp>\d{{8}}T\d{{12}}Z)"
    rf"-(?P<digest>[0-9a-f]{{16}})"
    rf"(?:-(?P<sequence>\d+))?{re.escape(MANAGED_FILENAME_SUFFIX)}$"
)
_INCOMPLETE_PREFIX = ".hermes_recovery_"
_INCOMPLETE_SUFFIX = ".incomplete"
_LOCK_NAME = ".hermes_recovery.lock"
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


def _verify_artifact(path: Path) -> tuple[dict[str, Any], str, int]:
    try:
        _assert_no_reparse_components(path)
        if not path.is_file() or path.is_symlink():
            raise ProtectedBackupError("managed artifact is not a regular file")
        artifact_bytes = path.read_bytes()
        actual = hashlib.sha256(artifact_bytes).hexdigest()
        size_bytes = len(artifact_bytes)
        with zipfile.ZipFile(io.BytesIO(artifact_bytes), "r") as archive:
            if archive.namelist() != [_MANIFEST_NAME, _SNAPSHOT_NAME]:
                raise ProtectedBackupError("managed artifact members are invalid")
            manifest = json.loads(archive.read(_MANIFEST_NAME))
            if not isinstance(manifest, dict):
                raise ProtectedBackupError("managed artifact manifest is invalid")
            _validate_manifest_shape(manifest)
            snapshot_bytes = archive.read(_SNAPSHOT_NAME)
            with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as stream:
                stream.write(snapshot_bytes)
                snapshot_path = Path(stream.name)
            try:
                snapshot_digest = hashlib.sha256(snapshot_bytes).hexdigest()
                if manifest.get("snapshot_sha256") != snapshot_digest:
                    raise ProtectedBackupError("managed artifact snapshot hash is invalid")
                if manifest.get("snapshot_size_bytes") != len(snapshot_bytes):
                    raise ProtectedBackupError("managed artifact snapshot size is invalid")
                connection = sqlite3.connect(snapshot_path)
                try:
                    if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                        raise ProtectedBackupError("managed artifact SQLite integrity is invalid")
                    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                        raise ProtectedBackupError(
                            "managed artifact SQLite foreign keys are invalid"
                        )
                    snapshot_revisions = _snapshot_revision_set(connection)
                finally:
                    connection.close()
            finally:
                snapshot_path.unlink(missing_ok=True)
            if manifest.get("source_alembic_revisions") != list(snapshot_revisions):
                raise ProtectedBackupError(
                    "managed artifact Alembic revision identity does not verify"
                )
        normalized = dict(manifest)
        expected = normalized.get("artifact_identity_sha256")
        normalized["artifact_identity_sha256"] = _ZERO_DIGEST
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ProtectedBackupError("managed artifact canonical identity is invalid")
        if (
            hashlib.sha256(_zip_bytes_from_bytes(snapshot_bytes, normalized)).hexdigest()
            != expected
        ):
            raise ProtectedBackupError("managed artifact canonical identity does not verify")
        if manifest.get("artifact_size_bytes") != size_bytes:
            raise ProtectedBackupError("managed artifact size does not verify")
        name_match = _MANAGED_FILENAME_RE.fullmatch(path.name)
        if name_match is None or name_match.group("digest") != actual[:16]:
            raise ProtectedBackupError("managed artifact name identity does not verify")
        return manifest, actual, size_bytes
    except (OSError, KeyError, json.JSONDecodeError, sqlite3.Error, zipfile.BadZipFile) as error:
        raise ProtectedBackupError("managed artifact read-back verification failed") from error


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
                staged = validated_destination / (
                    f"{_INCOMPLETE_PREFIX}{uuid.uuid4().hex}{_INCOMPLETE_SUFFIX}"
                )
                with staged.open("xb") as stream:
                    stream.write(artifact_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                with staged.open("rb") as stream:
                    final_digest = hashlib.sha256(stream.read()).hexdigest()
                final = _expose_final_without_overwrite(
                    staged, created_at, final_digest, validated_destination
                )
                read_manifest, _, size_bytes = _verify_artifact(final)
                for key, value in manifest.items():
                    if (
                        key not in {"artifact_identity_sha256", "artifact_size_bytes"}
                        and read_manifest.get(key) != value
                    ):
                        raise ProtectedBackupError("managed artifact manifest changed on read-back")
                if read_manifest.get("artifact_size_bytes") != size_bytes:
                    raise ProtectedBackupError("managed artifact size changed on read-back")
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
                    action_required=None,
                )
            except (OSError, ProtectedBackupError) as error:
                if "final" in locals() and final.exists():
                    final.unlink(missing_ok=True)
                raise ProtectedBackupError("recovery-point publication failed") from error
            finally:
                snapshot.unlink(missing_ok=True)
