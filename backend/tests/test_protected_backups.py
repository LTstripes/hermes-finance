from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hermes_finance.database import create_database
from hermes_finance.protected_backup_cli import main as protected_backup_main
from hermes_finance.services import protected_backups
from hermes_finance.services.protected_backups import (
    PROTECTION_MODE,
    PROTECTION_STATE,
    RETENTION_ACTION_REQUIRED,
    RETENTION_COMPLETED,
    RETENTION_FAILED,
    RETENTION_NOT_RUN,
    VERIFIED_RETENTION_LIMIT,
    ProtectedBackupError,
    is_managed_recovery_name,
    publish_recovery_point,
)


@pytest.fixture
def synthetic_database(tmp_path: Path):
    database = create_database(tmp_path / "runtime" / "finance.db")
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE synthetic_ledger (id INTEGER PRIMARY KEY, label TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES ('0041_debt_linked_account')"
        )
        connection.exec_driver_sql("INSERT INTO synthetic_ledger VALUES (1, 'alpha')")
    try:
        yield database
    finally:
        database.engine.dispose()


def _publish(
    monkeypatch,
    database,
    destination: Path,
    *,
    now: datetime | None = None,
    git_sha: str = "a" * 40,
):
    monkeypatch.setattr(
        protected_backups,
        "_git_identity",
        lambda _checkout: git_sha,
    )
    return publish_recovery_point(
        database,
        destination,
        protection_state=PROTECTION_STATE,
        protection_mode=PROTECTION_MODE,
        source_checkout=Path(__file__).resolve().parents[2],
        now=now or datetime(2035, 1, 2, 3, 4, 5, 678000, tzinfo=UTC),
    )


def _managed_names(destination: Path) -> set[str]:
    return {path.name for path in destination.iterdir() if is_managed_recovery_name(path.name)}


def _create_clean_git_checkout(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=path, check=True)
    (path / "synthetic.txt").write_text("synthetic\n", encoding="utf-8")
    subprocess.run(["git", "add", "synthetic.txt"], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Hermes Synthetic",
            "-c",
            "user.email=synthetic",
            "commit",
            "--quiet",
            "-m",
            "synthetic checkout",
        ],
        cwd=path,
        check=True,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert status.stdout == ""


def test_publisher_creates_verified_single_artifact_with_deterministic_manifest(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()

    result = _publish(monkeypatch, synthetic_database, destination)

    assert result.status == "published"
    assert result.read_back == "verified"
    assert result.retention == RETENTION_COMPLETED
    assert result.action_required is None
    artifacts = [path for path in destination.iterdir() if is_managed_recovery_name(path.name)]
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert result.size_bytes == artifact.stat().st_size
    operation_result = result.as_dict()
    assert "name" not in operation_result
    assert "artifact_sha256" not in operation_result
    with zipfile.ZipFile(artifact) as archive:
        assert archive.namelist() == ["manifest.json", "snapshot.sqlite3"]
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["format_version"] == 1
    assert manifest["protection_mode"] == PROTECTION_MODE
    assert manifest["producer_git_sha"] == "a" * 40
    assert manifest["protection_state"] == PROTECTION_STATE
    assert manifest["source_alembic_revisions"] == ["0041_debt_linked_account"]
    assert len(manifest["snapshot_sha256"]) == 64
    assert len(manifest["artifact_identity_sha256"]) == 64
    assert manifest["artifact_size_bytes"] == artifact.stat().st_size
    assert not (destination / ".hermes_recovery.lock").exists()
    assert not list(destination.glob(".hermes_recovery_*.incomplete"))


def test_supplied_clean_checkout_cannot_replace_executing_producer_identity(
    tmp_path: Path, synthetic_database
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    other_checkout = tmp_path / "clean-checkout-b"
    _create_clean_git_checkout(other_checkout)

    with pytest.raises(ProtectedBackupError, match="does not match executing"):
        publish_recovery_point(
            synthetic_database,
            destination,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
            source_checkout=other_checkout,
        )

    assert not list(destination.iterdir())


def test_destination_inside_differently_named_git_checkout_fails_closed(
    tmp_path: Path, synthetic_database
) -> None:
    other_checkout = tmp_path / "encrypted-vault-7392"
    _create_clean_git_checkout(other_checkout)
    destination = other_checkout / "mounted-protected-destination"
    destination.mkdir()

    with pytest.raises(ProtectedBackupError, match="Git repository or worktree"):
        publish_recovery_point(
            synthetic_database,
            destination,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
            source_checkout=Path(__file__).resolve().parents[2],
        )

    assert not [path for path in destination.iterdir() if is_managed_recovery_name(path.name)]


def test_destination_with_worktree_git_file_fails_closed(
    tmp_path: Path, synthetic_database
) -> None:
    destination = tmp_path / "encrypted-vault-worktree-4815"
    destination.mkdir()
    (destination / ".git").write_text("gitdir: ../synthetic-gitdir\n", encoding="utf-8")

    with pytest.raises(ProtectedBackupError, match="Git repository or worktree"):
        publish_recovery_point(
            synthetic_database,
            destination,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
            source_checkout=Path(__file__).resolve().parents[2],
        )

    assert not [path for path in destination.iterdir() if is_managed_recovery_name(path.name)]


def test_missing_or_unknown_protection_attestation_fails_before_staging(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    monkeypatch.setattr(protected_backups, "_git_identity", lambda _checkout: "d" * 40)

    with pytest.raises(ProtectedBackupError, match="unsupported protection mode"):
        publish_recovery_point(
            synthetic_database,
            destination,
            protection_state="unattested",
            protection_mode=PROTECTION_MODE,
            source_checkout=Path(__file__).resolve().parents[2],
        )
    assert not list(destination.iterdir())


def test_source_revision_set_is_sorted_and_deterministic(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    with synthetic_database.engine.begin() as connection:
        connection.exec_driver_sql("DELETE FROM alembic_version")
        connection.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES ('0041_debt_linked_account'), ('0040_in_kind_boundary_coverage')"
        )
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    _publish(monkeypatch, synthetic_database, destination)
    artifact = next(path for path in destination.iterdir() if is_managed_recovery_name(path.name))
    with zipfile.ZipFile(artifact) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["source_alembic_revisions"] == [
        "0040_in_kind_boundary_coverage",
        "0041_debt_linked_account",
    ]


def test_publisher_fails_closed_for_boundary_and_lock(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    monkeypatch.setattr(protected_backups, "_git_identity", lambda _checkout: "b" * 40)

    with pytest.raises(ProtectedBackupError, match="unsupported protection mode"):
        publish_recovery_point(
            synthetic_database,
            destination,
            protection_state=PROTECTION_STATE,
            protection_mode="plaintext",
            source_checkout=Path(__file__).resolve().parents[2],
        )

    (destination / ".hermes_recovery.lock").write_text("stale", encoding="ascii")
    with pytest.raises(ProtectedBackupError, match="contended or stale"):
        publish_recovery_point(
            synthetic_database,
            destination,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
            source_checkout=Path(__file__).resolve().parents[2],
        )

    with pytest.raises(ProtectedBackupError, match="local runtime backup boundary"):
        publish_recovery_point(
            synthetic_database,
            synthetic_database.database_path.parent,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
            source_checkout=Path(__file__).resolve().parents[2],
        )


def test_corrupt_readback_is_not_verified(tmp_path: Path, synthetic_database, monkeypatch) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    _publish(monkeypatch, synthetic_database, destination)
    artifact = next(path for path in destination.iterdir() if is_managed_recovery_name(path.name))
    artifact.write_bytes(b"corrupt")

    with pytest.raises(ProtectedBackupError, match="read-back verification"):
        protected_backups._verify_artifact(artifact)


def test_readback_binds_one_immutable_artifact_byte_sequence(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    _publish(monkeypatch, synthetic_database, destination)
    artifact = next(path for path in destination.iterdir() if is_managed_recovery_name(path.name))
    original_bytes = artifact.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()
    original_read_bytes = Path.read_bytes

    def replace_after_read(path: Path) -> bytes:
        content = original_read_bytes(path)
        if path == artifact:
            path.write_bytes(b"replacement-after-read")
        return content

    monkeypatch.setattr(Path, "read_bytes", replace_after_read)
    _manifest, verified_hash, verified_size = protected_backups._verify_artifact(artifact)

    assert verified_hash == original_hash
    assert verified_size == len(original_bytes)
    assert artifact.read_bytes() == b"replacement-after-read"


def test_verification_never_uses_redirected_default_temp_storage(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    _publish(monkeypatch, synthetic_database, destination)
    artifact = next(path for path in destination.iterdir() if is_managed_recovery_name(path.name))
    redirected_temp = tmp_path / "redirected-system-temp"
    redirected_temp.mkdir()
    monkeypatch.setenv("TMP", str(redirected_temp))
    monkeypatch.setenv("TEMP", str(redirected_temp))
    monkeypatch.setenv("TMPDIR", str(redirected_temp))
    monkeypatch.setattr(tempfile, "tempdir", str(redirected_temp))

    protected_backups._verify_artifact(artifact)

    assert not list(redirected_temp.iterdir())


def test_in_memory_verification_write_failure_leaves_no_plaintext_temp_residue(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    _publish(monkeypatch, synthetic_database, destination)
    artifact = next(path for path in destination.iterdir() if is_managed_recovery_name(path.name))
    redirected_temp = tmp_path / "redirected-system-temp"
    redirected_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(redirected_temp))

    class FailingWriteConnection:
        closed = False

        def deserialize(self, _payload: bytes) -> None:
            raise sqlite3.OperationalError("synthetic in-memory write failure")

        def close(self) -> None:
            self.closed = True

    connection = FailingWriteConnection()
    monkeypatch.setattr(protected_backups.sqlite3, "connect", lambda _target: connection)

    with pytest.raises(ProtectedBackupError, match="read-back verification"):
        protected_backups._verify_artifact(artifact)

    assert connection.closed is True
    assert not list(redirected_temp.iterdir())


def test_in_memory_verification_close_failure_leaves_no_plaintext_temp_residue(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    _publish(monkeypatch, synthetic_database, destination)
    artifact = next(path for path in destination.iterdir() if is_managed_recovery_name(path.name))
    redirected_temp = tmp_path / "redirected-system-temp"
    redirected_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(redirected_temp))
    real_connect = protected_backups.sqlite3.connect

    class FailingCloseConnection:
        def __init__(self) -> None:
            self._connection = real_connect(":memory:")

        def __getattr__(self, name: str):
            return getattr(self._connection, name)

        def close(self) -> None:
            self._connection.close()
            raise sqlite3.OperationalError("synthetic in-memory close failure")

    monkeypatch.setattr(
        protected_backups.sqlite3, "connect", lambda _target: FailingCloseConnection()
    )

    with pytest.raises(ProtectedBackupError, match="read-back verification"):
        protected_backups._verify_artifact(artifact)

    assert not list(redirected_temp.iterdir())


def test_readback_binds_manifest_revisions_to_snapshot(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    result = _publish(monkeypatch, synthetic_database, destination)
    artifact = next(path for path in destination.iterdir() if is_managed_recovery_name(path.name))
    with zipfile.ZipFile(artifact) as archive:
        snapshot_bytes = archive.read("snapshot.sqlite3")
        manifest = json.loads(archive.read("manifest.json"))
    manifest["source_alembic_revisions"] = ["0040_in_kind_boundary_coverage"]
    snapshot_path = tmp_path / "mismatch.sqlite3"
    snapshot_path.write_bytes(snapshot_bytes)
    mismatched_bytes = protected_backups._artifact_bytes(snapshot_path, manifest)
    mismatched_digest = hashlib.sha256(mismatched_bytes).hexdigest()
    mismatched = (
        destination
        / protected_backups._managed_name(result.created_at, mismatched_digest, destination).name
    )
    mismatched.write_bytes(mismatched_bytes)

    with pytest.raises(ProtectedBackupError, match="revision identity does not verify"):
        protected_backups._verify_artifact(mismatched)


def test_atomic_final_rename_preserves_existing_managed_point(tmp_path: Path) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    created_at = datetime(2035, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
    digest = "a" * 64
    existing = destination / (
        "hermes_recovery_20350102T030405678000Z-aaaaaaaaaaaaaaaa.hermes-recovery"
    )
    existing.write_bytes(b"prior verified point")
    staged = destination / ".hermes_recovery_staged.incomplete"
    staged.write_bytes(b"new verified point")

    final = protected_backups._expose_final_without_overwrite(
        staged, created_at, digest, destination
    )

    assert final.name.endswith("-1.hermes-recovery")
    assert final.read_bytes() == b"new verified point"
    assert existing.read_bytes() == b"prior verified point"
    assert not staged.exists()


def test_interrupted_publication_leaves_only_unrecognized_incomplete_name(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    monkeypatch.setattr(protected_backups, "_git_identity", lambda _checkout: "e" * 40)

    def fail_expose(*_args, **_kwargs):
        raise ProtectedBackupError("synthetic interrupted finalization")

    monkeypatch.setattr(protected_backups, "_expose_final_without_overwrite", fail_expose)
    with pytest.raises(ProtectedBackupError, match="publication failed"):
        publish_recovery_point(
            synthetic_database,
            destination,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
            source_checkout=Path(__file__).resolve().parents[2],
        )
    assert not [path for path in destination.iterdir() if is_managed_recovery_name(path.name)]
    assert list(destination.glob(".hermes_recovery_*.incomplete"))


def test_staged_corruption_never_reaches_final_exposure(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    monkeypatch.setattr(protected_backups, "_git_identity", lambda _checkout: "9" * 40)
    original_verify_content = protected_backups._verify_artifact_content
    exposure_reached = False

    def corrupt_staging(path: Path, **kwargs):
        if path.name.endswith(".incomplete"):
            path.write_bytes(b"synthetic staged corruption")
        return original_verify_content(path, **kwargs)

    def record_exposure(*_args, **_kwargs):
        nonlocal exposure_reached
        exposure_reached = True
        raise AssertionError("final exposure must not be reached")

    monkeypatch.setattr(protected_backups, "_verify_artifact_content", corrupt_staging)
    monkeypatch.setattr(protected_backups, "_expose_final_without_overwrite", record_exposure)

    with pytest.raises(ProtectedBackupError, match="publication failed"):
        publish_recovery_point(
            synthetic_database,
            destination,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
            source_checkout=Path(__file__).resolve().parents[2],
        )

    assert exposure_reached is False
    assert not [path for path in destination.iterdir() if is_managed_recovery_name(path.name)]


def test_readback_corruption_during_publish_removes_new_final_name(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    monkeypatch.setattr(protected_backups, "_git_identity", lambda _checkout: "f" * 40)
    monkeypatch.setattr(
        protected_backups,
        "_verify_artifact",
        lambda _path, **_kwargs: (_ for _ in ()).throw(
            ProtectedBackupError("synthetic corruption")
        ),
    )
    with pytest.raises(ProtectedBackupError, match="publication failed"):
        publish_recovery_point(
            synthetic_database,
            destination,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
            source_checkout=Path(__file__).resolve().parents[2],
        )
    assert not [path for path in destination.iterdir() if is_managed_recovery_name(path.name)]


def test_failed_next_run_preserves_prior_verified_point(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    _publish(monkeypatch, synthetic_database, destination)
    prior_artifact = next(
        path for path in destination.iterdir() if is_managed_recovery_name(path.name)
    )
    monkeypatch.setattr(
        protected_backups,
        "_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ProtectedBackupError("synthetic snapshot failure")
        ),
    )
    with pytest.raises(ProtectedBackupError):
        publish_recovery_point(
            synthetic_database,
            destination,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
            source_checkout=Path(__file__).resolve().parents[2],
        )
    assert prior_artifact.is_file()


def test_concurrent_publication_fails_closed_on_destination_lock(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    second_database = create_database(synthetic_database.database_path)
    entered = threading.Event()
    release = threading.Event()
    original_snapshot = protected_backups._snapshot
    monkeypatch.setattr(protected_backups, "_git_identity", lambda _checkout: "1" * 40)

    def blocked_snapshot(database, path):
        entered.set()
        assert release.wait(5)
        return original_snapshot(database, path)

    monkeypatch.setattr(protected_backups, "_snapshot", blocked_snapshot)
    first_error: list[BaseException] = []

    def run_first() -> None:
        try:
            _publish(monkeypatch, synthetic_database, destination)
        except BaseException as error:  # pragma: no cover - failure surfaced below
            first_error.append(error)

    first = threading.Thread(target=run_first)
    first.start()
    assert entered.wait(5)
    with pytest.raises(ProtectedBackupError, match="contended or stale"):
        publish_recovery_point(
            second_database,
            destination,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
            source_checkout=Path(__file__).resolve().parents[2],
        )
    release.set()
    first.join(timeout=10)
    second_database.engine.dispose()
    assert not first_error


def test_managed_name_recognition_is_exact_and_dirty_checkout_fails_closed(
    monkeypatch,
) -> None:
    assert is_managed_recovery_name(
        "hermes_recovery_20350102T030405678000Z-abcdef0123456789.hermes-recovery"
    )
    assert not is_managed_recovery_name(
        "hermes_recovery_20350102T030405678000Z-abcdef0123456789.incomplete"
    )
    assert not is_managed_recovery_name(
        "foreign_20350102T030405678000Z-abcdef0123456789.hermes-recovery"
    )
    original_run = protected_backups.subprocess.run

    def dirty_status_run(*args, **kwargs):
        if args and args[0][:2] == ["git", "status"]:
            return subprocess.CompletedProcess(args[0], 0, stdout=" M synthetic.txt\n", stderr="")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(protected_backups.subprocess, "run", dirty_status_run)
    with pytest.raises(ProtectedBackupError, match="not clean"):
        protected_backups._git_identity(Path(__file__).resolve().parents[2])


def test_reparse_destination_alias_is_rejected_when_supported(
    tmp_path: Path, synthetic_database
) -> None:
    target = tmp_path / "mounted-protected-destination"
    target.mkdir()
    alias = tmp_path / "destination-alias"
    try:
        os.symlink(target, alias, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic-link creation is unavailable on this Windows host")
    with pytest.raises(ProtectedBackupError, match="reparse"):
        publish_recovery_point(
            synthetic_database,
            alias,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
            source_checkout=Path(__file__).resolve().parents[2],
        )


def test_explicit_cli_returns_privacy_safe_result(
    tmp_path: Path, synthetic_database, monkeypatch, capsys
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    monkeypatch.setattr(protected_backups, "_git_identity", lambda _checkout: "c" * 40)

    exit_code = protected_backup_main(
        [
            "--database",
            str(synthetic_database.database_path),
            "--destination",
            str(destination),
            "--checkout",
            str(Path(__file__).resolve().parents[2]),
            "--protection-mode",
            PROTECTION_MODE,
            "--protection-state",
            PROTECTION_STATE,
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert str(synthetic_database.database_path) not in output
    assert str(destination) not in output
    payload = json.loads(output)
    assert payload["status"] == "published"
    assert payload["created"] is True
    assert payload["verified"] is True
    assert payload["published"] is True
    assert payload["destination_alias"] == "protected-destination"
    assert payload["retention"] == RETENTION_COMPLETED
    assert payload["action_required"] is None


def test_explicit_cli_failure_is_privacy_safe(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing-private-finance.db"
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    exit_code = protected_backup_main(
        [
            "--database",
            str(missing),
            "--destination",
            str(destination),
            "--checkout",
            str(Path(__file__).resolve().parents[2]),
            "--protection-mode",
            PROTECTION_MODE,
            "--protection-state",
            PROTECTION_STATE,
        ]
    )
    output = capsys.readouterr().out
    assert exit_code == 2
    assert str(missing) not in output
    payload = json.loads(output)
    assert payload["status"] == "action_required"
    assert payload["created"] is False
    assert payload["verified"] is False
    assert payload["published"] is False
    assert payload["format_version"] == 1
    assert payload["created_at"] is None
    assert payload["retention"] == RETENTION_NOT_RUN
    assert "name" not in payload
    assert "artifact_sha256" not in payload


@pytest.mark.parametrize(
    "private_args",
    [
        ["--protection-mode", r"C:\synthetic-private\owner\finance.db"],
        [
            "--protection-mode",
            PROTECTION_MODE,
            "--synthetic-private-argument",
            r"C:\synthetic-private\owner\finance.db",
        ],
    ],
)
def test_cli_parser_failure_does_not_echo_private_argv(
    private_args: list[str], tmp_path: Path, capsys
) -> None:
    private_value = r"C:\synthetic-private\owner\finance.db"
    exit_code = protected_backup_main(
        [
            "--destination",
            str(tmp_path / "mounted-protected-destination"),
            "--protection-state",
            PROTECTION_STATE,
            *private_args,
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert private_value not in captured.out
    assert private_value not in captured.err
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["status"] == "action_required"
    assert payload["created"] is False
    assert payload["verified"] is False
    assert payload["published"] is False
    assert payload["retention"] == RETENTION_NOT_RUN
    assert payload["action_required"] == ("protected recovery-point publication was not completed")


def _publish_series(monkeypatch, database, destination: Path, count: int, *, now_day: int = 1):
    created: list[str] = []
    results = []
    for offset in range(count):
        before = _managed_names(destination)
        result = _publish(
            monkeypatch,
            database,
            destination,
            now=datetime(2035, 1, now_day + offset, 8, 0, 0, tzinfo=UTC),
        )
        after = _managed_names(destination)
        added = after - before
        assert len(added) == 1
        created.append(next(iter(added)))
        results.append(result)
    return created, results


def test_managed_recency_key_is_deterministic() -> None:
    base = "hermes_recovery_20350102T030405678000Z-abcdef0123456789.hermes-recovery"
    sequenced = "hermes_recovery_20350102T030405678000Z-abcdef0123456789-1.hermes-recovery"
    later = "hermes_recovery_20350102T030405678001Z-0000000000000000.hermes-recovery"
    assert protected_backups._managed_recency_key(base) < protected_backups._managed_recency_key(
        sequenced
    )
    assert protected_backups._managed_recency_key(
        sequenced
    ) < protected_backups._managed_recency_key(later)


def test_retention_keeps_newest_twelve_verified_points(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    created, results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT + 1
    )

    assert all(result.published is True for result in results)
    assert all(result.retention == RETENTION_COMPLETED for result in results)
    remaining = _managed_names(destination)
    assert len(remaining) == VERIFIED_RETENTION_LIMIT
    assert created[0] not in remaining
    assert set(created[1:]) == remaining
    verified = protected_backups._verified_managed_recovery_points(destination)
    assert [path.name for path in verified] == created[1:]


def test_retention_does_not_delete_by_age_when_under_limit(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    old = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        now=datetime(2010, 1, 1, tzinfo=UTC),
    )
    mid = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        now=datetime(2020, 6, 15, tzinfo=UTC),
    )
    newest = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        now=datetime(2035, 12, 31, tzinfo=UTC),
    )

    remaining = _managed_names(destination)
    assert len(remaining) == 3
    assert old.retention == RETENTION_COMPLETED
    assert mid.retention == RETENTION_COMPLETED
    assert newest.retention == RETENTION_COMPLETED
    assert newest.published is True


def test_retention_preserves_unknown_partial_and_corrupt_files(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    unknown = destination / "owner-notes.txt"
    unknown.write_text("unrelated owner note", encoding="utf-8")
    foreign = destination / "foreign-archive.zip"
    foreign.write_bytes(b"not-a-hermes-recovery")
    nested_dir = destination / "unrelated-folder"
    nested_dir.mkdir()
    nested = nested_dir / "hermes_recovery_20350101T000000000000Z-abcdef0123456789.hermes-recovery"
    nested.write_bytes(b"nested-foreign")
    partial = destination / ".hermes_recovery_ab12cd34ef56.incomplete"
    partial.write_bytes(b"partial-staging")
    corrupt = (
        destination / "hermes_recovery_19990101T000000000000Z-ffffffffffffffff.hermes-recovery"
    )
    corrupt.write_bytes(b"corrupt-managed-name")
    invalid_shape = destination / "hermes_recovery_notimestamp-abcdef0123456789.hermes-recovery"
    invalid_shape.write_bytes(b"invalid-shape")

    created, _results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT + 1
    )

    remaining_verified = {
        path.name for path in protected_backups._verified_managed_recovery_points(destination)
    }
    assert remaining_verified == set(created[1:])
    assert unknown.read_text(encoding="utf-8") == "unrelated owner note"
    assert foreign.read_bytes() == b"not-a-hermes-recovery"
    assert nested.read_bytes() == b"nested-foreign"
    assert partial.read_bytes() == b"partial-staging"
    assert corrupt.read_bytes() == b"corrupt-managed-name"
    assert invalid_shape.read_bytes() == b"invalid-shape"
    assert corrupt.name in _managed_names(destination)


def test_failed_next_publication_does_not_run_retention(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    created, _results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT
    )
    prior = set(created)

    def retention_must_not_run(*_args, **_kwargs):
        raise AssertionError("retention must not run after a failed publication")

    monkeypatch.setattr(
        protected_backups, "_retain_verified_recovery_points", retention_must_not_run
    )
    monkeypatch.setattr(
        protected_backups,
        "_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ProtectedBackupError("synthetic snapshot failure")
        ),
    )
    with pytest.raises(ProtectedBackupError):
        publish_recovery_point(
            synthetic_database,
            destination,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
            source_checkout=Path(__file__).resolve().parents[2],
            now=datetime(2035, 1, 20, tzinfo=UTC),
        )

    assert _managed_names(destination) == prior
    assert all((destination / name).is_file() for name in prior)


def test_retention_cleanup_failure_does_not_invalidate_new_backup(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    created, _results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT
    )

    def fail_unlink(_path: Path) -> None:
        raise OSError("synthetic retention unlink failure")

    monkeypatch.setattr(protected_backups, "_unlink_verified_recovery_point", fail_unlink)
    result = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        now=datetime(2035, 1, 20, tzinfo=UTC),
    )

    remaining = _managed_names(destination)
    assert result.status == "published"
    assert result.created is True
    assert result.verified is True
    assert result.published is True
    assert result.read_back == "verified"
    assert result.retention == RETENTION_FAILED
    assert result.action_required == RETENTION_ACTION_REQUIRED
    assert len(remaining) == VERIFIED_RETENTION_LIMIT + 1
    assert set(created).issubset(remaining)
    assert str(destination) not in result.as_dict().values()


def test_retention_ordering_is_independent_of_directory_listing(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    created, _results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT
    )
    real_listdir = os.listdir

    def reversed_listdir(path):
        names = real_listdir(path)
        if os.path.normcase(str(path)) == os.path.normcase(str(destination)):
            return list(reversed(names))
        return names

    monkeypatch.setattr(os, "listdir", reversed_listdir)
    result = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        now=datetime(2035, 1, 20, 9, 0, 0, tzinfo=UTC),
    )
    remaining = _managed_names(destination)
    added = remaining - set(created)

    assert result.retention == RETENTION_COMPLETED
    assert len(remaining) == VERIFIED_RETENTION_LIMIT
    assert created[0] not in remaining
    assert len(added) == 1
    expected = set(created[1:]) | added
    assert remaining == expected


def test_same_timestamp_retention_uses_sequence_then_digest(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    now = datetime(2035, 6, 7, 8, 9, 10, 123000, tzinfo=UTC)
    created: list[str] = []
    for _index in range(VERIFIED_RETENTION_LIMIT + 1):
        before = _managed_names(destination)
        _publish(monkeypatch, synthetic_database, destination, now=now)
        added = _managed_names(destination) - before
        assert len(added) == 1
        created.append(next(iter(added)))

    remaining = _managed_names(destination)
    keys = [protected_backups._managed_recency_key(name) for name in created]
    assert all(key is not None for key in keys)
    expected = {
        name for _key, name in sorted(zip(keys, created, strict=True))[-VERIFIED_RETENTION_LIMIT:]
    }
    assert remaining == expected
    assert created[0] not in remaining or created[0] in expected
