"""Fail-closed isolated recovery rehearsal for managed recovery points (ADR 0017)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

from hermes_finance.services import protected_backups
from hermes_finance.services.protected_backups import (
    DESTINATION_ALIAS,
    FORMAT_VERSION,
    PROTECTION_MODE,
    PROTECTION_STATE,
    ProtectedBackupError,
)

RECOVERY_PROFILE_KIND = "recovery_rehearsal"
RELATIONSHIP_SAME_REVISION = "same_revision"
RELATIONSHIP_FORWARD_UPGRADE = "forward_upgrade"
RECOVERY_ACTION_REQUIRED = (
    "isolated recovery rehearsal was not completed; use a new target after resolving the failure"
)
_FULL_SHA_RE = re.compile(r"[0-9a-f]{40}")
_REPARSE_POINT = 0x400
_SIDECAR_NAME = ".hermes-data-identity.json"
_READ_CHUNK = 1024 * 1024


class RecoveryRehearsalError(RuntimeError):
    """A privacy-safe recovery stage failed closed."""

    def __init__(self, stage: str, message: str, *, target_mutated: bool = False) -> None:
        super().__init__(message)
        self.stage = stage
        self.target_mutated = target_mutated


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
    return device, inode


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
    if protection_state != PROTECTION_STATE or protection_mode != PROTECTION_MODE:
        raise RecoveryRehearsalError(
            "protection", "protected recovery boundary attestation is invalid"
        )
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
        recovery / "scripts" / "prepare-runtime.ps1",
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


def _validate_fresh_target(
    *,
    target_profile: Path,
    target_data: Path,
    target_database: Path,
    source: VerifiedSource,
    checkout: CheckoutProof,
    forbidden: tuple[Path, ...],
) -> tuple[Path, Path, Path]:
    profile = _absolute_path(target_profile, stage="target-boundary")
    data = _absolute_path(target_data, stage="target-boundary")
    database = _absolute_path(target_database, stage="target-boundary")
    if profile.parent == profile:
        raise RecoveryRehearsalError("target-boundary", "target profile boundary is too broad")
    if data.parent != profile or database.parent != data:
        raise RecoveryRehearsalError(
            "target-boundary", "target profile, data, and database boundaries are not exact"
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
    for path in (profile, data, database):
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
    return profile, data, database


def _create_target_directories(profile: Path, data: Path) -> None:
    try:
        profile.mkdir()
        data.mkdir()
        protected_backups._assert_no_reparse_components(profile)
        protected_backups._assert_no_reparse_components(data)
        if not profile.is_dir() or not data.is_dir():
            raise OSError("target boundary is not a directory")
    except (OSError, ProtectedBackupError) as error:
        raise RecoveryRehearsalError(
            "restore-write", "fresh isolated target could not be created", target_mutated=True
        ) from error


def _restore_snapshot(snapshot_bytes: bytes, data: Path, database: Path) -> None:
    temporary = data / ".finance.db.recovery.incomplete"
    try:
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(snapshot_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        if database.exists():
            raise OSError("target database appeared during restore")
        os.replace(temporary, database)
    except OSError as error:
        raise RecoveryRehearsalError(
            "restore-write", "isolated database restore failed", target_mutated=True
        ) from error


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _database_facts(
    database: Path, *, expected_revisions: tuple[str, ...], stage: str
) -> tuple[tuple[str, ...], dict[str, int]]:
    try:
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        try:
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
        finally:
            connection.close()
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
    data: Path,
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
    path = data / _SIDECAR_NAME
    try:
        path.write_text(
            json.dumps(sidecar, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as error:
        raise RecoveryRehearsalError(
            "restore-write", "recovery profile identity could not be written", target_mutated=True
        ) from error


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
    timeout: int,
) -> None:
    script = checkout.checkout / "scripts" / script_name
    environment = os.environ.copy()
    environment["HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN"] = ""
    environment["PYTHONPATH"] = ""
    if database is not None:
        environment["HERMES_FINANCE_DATABASE_PATH"] = str(database)
    try:
        completed = subprocess.run(
            [
                _powershell(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                *arguments,
            ],
            cwd=checkout.checkout,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RecoveryRehearsalError(
            stage, "existing runtime operation could not complete", target_mutated=True
        ) from error
    if completed.returncode != 0:
        raise RecoveryRehearsalError(
            stage, "existing runtime operation failed", target_mutated=True
        )


def _prepare_and_validate(checkout: CheckoutProof) -> None:
    _run_runtime_script(
        checkout,
        script_name="prepare-runtime.ps1",
        arguments=["-Checkout", str(checkout.checkout), "-Prepare"],
        stage="runtime-prepare",
        timeout=1200,
    )
    _recheck_checkout(checkout, stage="runtime-prepare")
    _run_runtime_script(
        checkout,
        script_name="prepare-runtime.ps1",
        arguments=["-Checkout", str(checkout.checkout), "-Validate"],
        stage="runtime-validate",
        timeout=300,
    )
    _recheck_checkout(checkout, stage="runtime-validate")


def _start_and_probe(checkout: CheckoutProof, database: Path) -> None:
    _recheck_checkout(checkout, stage="runtime-start")
    _run_runtime_script(
        checkout,
        script_name="start-local.ps1",
        arguments=["-ExitAfterReady", "-RecoveryReadiness"],
        stage="runtime-start",
        database=database,
        timeout=120,
    )


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
        profile, data, database = _validate_fresh_target(
            target_profile=target_profile,
            target_data=target_data,
            target_database=target_database,
            source=source,
            checkout=checkout,
            forbidden=forbidden,
        )
        source.assert_unchanged()
        _recheck_checkout(checkout, stage="pre-restore-identity")

        _create_target_directories(profile, data)
        target_mutated = True
        _restore_snapshot(source.snapshot_bytes, data, database)
        _write_sidecar(data, source=source, checkout=checkout, compatibility=compatibility)
        _database_facts(
            database,
            expected_revisions=compatibility.source_revisions,
            stage="restored-database-validation",
        )
        source.assert_unchanged()

        _prepare_and_validate(checkout)
        source.assert_unchanged()
        _start_and_probe(checkout, database)
        resulting_revisions, structural_counts = _database_facts(
            database,
            expected_revisions=compatibility.selected_heads,
            stage="result-validation",
        )
        source.assert_unchanged()
        _recheck_checkout(checkout, stage="result-validation")
        return RecoveryRehearsalResult(
            status="rehearsed",
            source_verified=True,
            source_unchanged=True,
            restored=True,
            prepared=True,
            validated=True,
            readiness="verified",
            destination_alias=DESTINATION_ALIAS,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
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
        source.close()
