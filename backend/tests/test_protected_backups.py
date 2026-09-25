from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
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
    PLAINTEXT_RETENTION_ACTION_REQUIRED,
    PLAINTEXT_SYNCED_ALIAS,
    PLAINTEXT_SYNCED_MODE,
    PLAINTEXT_SYNCED_STATE,
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
    protection_state: str = PROTECTION_STATE,
    protection_mode: str = PROTECTION_MODE,
):
    monkeypatch.setattr(
        protected_backups,
        "_git_identity",
        lambda _checkout: git_sha,
    )
    return publish_recovery_point(
        database,
        destination,
        protection_state=protection_state,
        protection_mode=protection_mode,
        source_checkout=Path(__file__).resolve().parents[2],
        now=now or datetime(2035, 1, 2, 3, 4, 5, 678000, tzinfo=UTC),
    )


def _managed_names(destination: Path) -> set[str]:
    return {path.name for path in destination.iterdir() if is_managed_recovery_name(path.name)}


def _eligible_names(
    destination: Path,
    *,
    protection_state: str = PROTECTION_STATE,
    protection_mode: str = PROTECTION_MODE,
) -> set[str]:
    return {
        path.name
        for path in protected_backups._verified_managed_recovery_points(
            destination,
            protection_state=protection_state,
            protection_mode=protection_mode,
        )
    }


def _object_bound_deletion_available(destination: Path) -> bool:
    try:
        protected_backups._preflight_object_bound_deletion(destination)
    except ProtectedBackupError:
        return False
    return True


def _bypass_preflight_if_unsupported(monkeypatch, destination: Path) -> None:
    """Reach the destroy hook on platforms that fail closed at capability preflight."""

    if not _object_bound_deletion_available(destination):
        monkeypatch.setattr(
            protected_backups, "_preflight_object_bound_deletion", lambda _destination: None
        )


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


def _assert_no_provider_claim(payload: dict) -> None:
    blob = json.dumps(payload, ensure_ascii=True).lower()
    for token in ("google", "oauth", "googleapis", "cloud_delivered", "offsite_delivered"):
        assert token not in blob


def _manifest_of(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert isinstance(manifest, dict)
    return manifest


@pytest.mark.parametrize(
    ("protection_state", "protection_mode"),
    [
        (PROTECTION_STATE, PLAINTEXT_SYNCED_MODE),
        (PLAINTEXT_SYNCED_STATE, PROTECTION_MODE),
        (PLAINTEXT_SYNCED_STATE, "plaintext"),
        ("unattested", PLAINTEXT_SYNCED_MODE),
    ],
)
def test_mismatched_protection_pairs_fail_before_staging(
    tmp_path: Path,
    synthetic_database,
    protection_state: str,
    protection_mode: str,
) -> None:
    destination = tmp_path / "synced-filesystem-destination"
    destination.mkdir()

    with pytest.raises(ProtectedBackupError, match="unsupported protection mode"):
        publish_recovery_point(
            synthetic_database,
            destination,
            protection_state=protection_state,
            protection_mode=protection_mode,
            source_checkout=Path(__file__).resolve().parents[2],
        )

    assert list(destination.iterdir()) == []


def test_plaintext_synced_mode_publishes_verifies_and_retains(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "synced-filesystem-destination"
    destination.mkdir()
    foreign = destination / "owner-notes.txt"
    foreign.write_text("unrelated owner note", encoding="utf-8")
    created, results = _publish_series(
        monkeypatch,
        synthetic_database,
        destination,
        VERIFIED_RETENTION_LIMIT + 1,
        protection_state=PLAINTEXT_SYNCED_STATE,
        protection_mode=PLAINTEXT_SYNCED_MODE,
    )

    assert all(result.published and result.verified for result in results)
    assert all(result.read_back == "verified" for result in results)
    assert all(result.protection_state == PLAINTEXT_SYNCED_STATE for result in results)
    assert all(result.protection_mode == PLAINTEXT_SYNCED_MODE for result in results)
    assert all(result.destination_alias == PLAINTEXT_SYNCED_ALIAS for result in results)
    assert all("protected" not in result.destination_alias for result in results)
    assert all("encrypted" not in result.protection_mode for result in results)
    for result in results:
        _assert_no_provider_claim(result.as_dict())
        assert str(destination) not in json.dumps(result.as_dict())
        assert str(synthetic_database.database_path) not in json.dumps(result.as_dict())

    can_delete = _object_bound_deletion_available(destination)
    remaining = _eligible_names(
        destination,
        protection_state=PLAINTEXT_SYNCED_STATE,
        protection_mode=PLAINTEXT_SYNCED_MODE,
    )
    if can_delete:
        assert all(result.retention == RETENTION_COMPLETED for result in results)
        assert remaining == set(created[1:])
    else:
        assert results[-1].retention == RETENTION_FAILED
        assert remaining == set(created)
    for name in remaining:
        manifest = _manifest_of(destination / name)
        assert manifest["protection_state"] == PLAINTEXT_SYNCED_STATE
        assert manifest["protection_mode"] == PLAINTEXT_SYNCED_MODE
        verified, digest, size = protected_backups._verify_artifact(destination / name)
        assert verified["protection_state"] == PLAINTEXT_SYNCED_STATE
        assert verified["protection_mode"] == PLAINTEXT_SYNCED_MODE
        assert len(digest) == 64
        assert size == (destination / name).stat().st_size
    assert foreign.read_text(encoding="utf-8") == "unrelated owner note"


def test_mismatched_manifest_is_not_retained(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "synced-filesystem-destination"
    destination.mkdir()
    snapshot = tmp_path / "snapshot.bin"
    snapshot.write_bytes(b"synthetic-snapshot")
    crossed = {
        "artifact_identity_sha256": "0" * 64,
        "artifact_size_bytes": 0,
        "created_at": "2035-01-01T00:00:00Z",
        "format_version": 1,
        "producer_git_sha": "b" * 40,
        "protection_state": PROTECTION_STATE,
        "protection_mode": PLAINTEXT_SYNCED_MODE,
        "snapshot_sha256": hashlib.sha256(b"synthetic-snapshot").hexdigest(),
        "snapshot_size_bytes": len(b"synthetic-snapshot"),
        "source_alembic_revisions": ["0041_debt_linked_account"],
    }
    artifact_bytes = protected_backups._artifact_bytes(snapshot, crossed)
    digest = hashlib.sha256(artifact_bytes).hexdigest()
    mismatched = destination / (
        f"hermes_recovery_20350101T000000000000Z-{digest[:16]}.hermes-recovery"
    )
    mismatched.write_bytes(artifact_bytes)
    original = mismatched.read_bytes()

    with pytest.raises(ProtectedBackupError, match="protection state is invalid"):
        protected_backups._verify_payload(original)

    result = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        protection_state=PLAINTEXT_SYNCED_STATE,
        protection_mode=PLAINTEXT_SYNCED_MODE,
    )

    assert result.retention == RETENTION_COMPLETED
    assert mismatched.read_bytes() == original
    plaintext_names = _eligible_names(
        destination,
        protection_state=PLAINTEXT_SYNCED_STATE,
        protection_mode=PLAINTEXT_SYNCED_MODE,
    )
    assert mismatched.name not in plaintext_names
    assert _manifest_of(destination / next(iter(plaintext_names)))["protection_mode"] == (
        PLAINTEXT_SYNCED_MODE
    )


def test_plaintext_cli_result_stays_truthful_and_privacy_safe(
    tmp_path: Path, synthetic_database, monkeypatch, capsys
) -> None:
    destination = tmp_path / "synced-filesystem-destination"
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
            "--protection-state",
            PLAINTEXT_SYNCED_STATE,
            "--protection-mode",
            PLAINTEXT_SYNCED_MODE,
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert str(synthetic_database.database_path) not in output
    assert str(destination) not in output
    payload = json.loads(output)
    assert payload["status"] == "published"
    assert payload["published"] is True
    assert payload["verified"] is True
    assert payload["read_back"] == "verified"
    assert payload["protection_state"] == PLAINTEXT_SYNCED_STATE
    assert payload["protection_mode"] == PLAINTEXT_SYNCED_MODE
    assert payload["destination_alias"] == PLAINTEXT_SYNCED_ALIAS
    assert payload["retention"] == RETENTION_COMPLETED
    _assert_no_provider_claim(payload)


def test_plaintext_cli_failure_does_not_claim_protected_mode(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing-private-finance.db"
    destination = tmp_path / "synced-filesystem-destination"
    destination.mkdir()

    exit_code = protected_backup_main(
        [
            "--database",
            str(missing),
            "--destination",
            str(destination),
            "--protection-state",
            PLAINTEXT_SYNCED_STATE,
            "--protection-mode",
            PLAINTEXT_SYNCED_MODE,
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 2
    assert str(missing) not in output
    assert str(destination) not in output
    payload = json.loads(output)
    assert payload["published"] is False
    assert payload["protection_state"] == PLAINTEXT_SYNCED_STATE
    assert payload["protection_mode"] == PLAINTEXT_SYNCED_MODE
    assert payload["destination_alias"] == PLAINTEXT_SYNCED_ALIAS
    assert "protected" not in payload["action_required"]
    assert "encrypted" not in payload["action_required"]
    _assert_no_provider_claim(payload)


@pytest.mark.parametrize(
    ("protection_state", "protection_mode"),
    [
        (PROTECTION_STATE, PLAINTEXT_SYNCED_MODE),
        (PLAINTEXT_SYNCED_STATE, PROTECTION_MODE),
    ],
)
def test_publisher_cli_crossed_pair_keeps_requested_identity(
    tmp_path: Path,
    synthetic_database,
    capsys,
    protection_state: str,
    protection_mode: str,
) -> None:
    destination = tmp_path / "crossed-pair-destination"
    destination.mkdir()

    exit_code = protected_backup_main(
        [
            "--database",
            str(synthetic_database.database_path),
            "--destination",
            str(destination),
            "--checkout",
            str(Path(__file__).resolve().parents[2]),
            "--protection-state",
            protection_state,
            "--protection-mode",
            protection_mode,
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 2
    assert str(destination) not in output
    assert str(synthetic_database.database_path) not in output
    assert "protected-destination" not in output
    payload = json.loads(output)
    assert payload["published"] is False
    assert payload["created"] is False
    assert payload["verified"] is False
    assert payload["retention"] == RETENTION_NOT_RUN
    assert payload["protection_state"] == protection_state
    assert payload["protection_mode"] == protection_mode
    assert payload["destination_alias"] is None
    assert "protected" not in payload["action_required"]
    assert list(destination.iterdir()) == []
    _assert_no_provider_claim(payload)


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
        [],
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
    assert payload["protection_state"] is None
    assert payload["protection_mode"] is None
    assert payload["destination_alias"] is None
    assert payload["action_required"] == "recovery-point publication was not completed"


def _publish_series(
    monkeypatch,
    database,
    destination: Path,
    count: int,
    *,
    now_day: int = 1,
    protection_state: str = PROTECTION_STATE,
    protection_mode: str = PROTECTION_MODE,
):
    created: list[str] = []
    results = []
    for offset in range(count):
        before = _managed_names(destination)
        result = _publish(
            monkeypatch,
            database,
            destination,
            now=datetime(2035, 1, now_day + offset, 8, 0, 0, tzinfo=UTC),
            protection_state=protection_state,
            protection_mode=protection_mode,
        )
        after = _managed_names(destination)
        added = after - before
        assert len(added) == 1
        created.append(next(iter(added)))
        results.append(result)
    return created, results


def test_verified_recency_orders_created_at_then_hash_then_sequence() -> None:
    older = datetime(2035, 1, 1, 8, 0, 0, tzinfo=UTC)
    newer = datetime(2035, 1, 2, 8, 0, 0, tzinfo=UTC)
    low = "0" * 64
    high = "f" * 64
    left = protected_backups._RetentionCandidate(
        path=Path("left"),
        created_at=older,
        artifact_hash=high,
        sequence=9,
        name="left",
        file_id=(1, 1),
    )
    right = protected_backups._RetentionCandidate(
        path=Path("right"),
        created_at=newer,
        artifact_hash=low,
        sequence=0,
        name="right",
        file_id=(1, 2),
    )
    assert left.recency_key() < right.recency_key()
    same_time_low = protected_backups._RetentionCandidate(
        path=Path("a"),
        created_at=newer,
        artifact_hash=low,
        sequence=0,
        name="hermes_recovery_20350102T080000000000Z-0000000000000000.hermes-recovery",
        file_id=(1, 3),
    )
    same_time_high = protected_backups._RetentionCandidate(
        path=Path("b"),
        created_at=newer,
        artifact_hash=high,
        sequence=0,
        name="hermes_recovery_20350102T080000000000Z-ffffffffffffffff.hermes-recovery",
        file_id=(1, 4),
    )
    assert same_time_low.recency_key() < same_time_high.recency_key()
    sequenced = protected_backups._RetentionCandidate(
        path=Path("c"),
        created_at=newer,
        artifact_hash=high,
        sequence=1,
        name="hermes_recovery_20350102T080000000000Z-ffffffffffffffff-1.hermes-recovery",
        file_id=(1, 5),
    )
    assert same_time_high.recency_key() < sequenced.recency_key()


def test_bound_created_at_rejects_missing_and_mismatched_identity() -> None:
    name = "hermes_recovery_20350102T030405678000Z-abcdef0123456789.hermes-recovery"
    bound = protected_backups._bound_retention_created_at(
        name, {"created_at": "2035-01-02T03:04:05.678000Z"}
    )
    assert bound == datetime(2035, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
    assert protected_backups._bound_retention_created_at(name, {}) is None
    assert protected_backups._bound_retention_created_at(name, {"created_at": None}) is None
    assert (
        protected_backups._bound_retention_created_at(
            name, {"created_at": "1999-01-01T00:00:00.000000Z"}
        )
        is None
    )


def test_select_retention_deletions_keeps_preserve_plus_eleven_newest(tmp_path: Path) -> None:
    destination = tmp_path / "retention-selection"
    destination.mkdir()
    items: list[protected_backups._RetentionCandidate] = []
    for index in range(VERIFIED_RETENTION_LIMIT):
        path = destination / f"point-{index}"
        path.write_bytes(b"x")
        items.append(
            protected_backups._RetentionCandidate(
                path=path,
                created_at=datetime(2035, 1, index + 1, tzinfo=UTC),
                artifact_hash=f"{index:064x}",
                sequence=0,
                name=path.name,
                file_id=(1, index),
            )
        )
    preserve_path = destination / "preserve-old"
    preserve_path.write_bytes(b"y")
    preserve = protected_backups._RetentionCandidate(
        path=preserve_path,
        created_at=datetime(1999, 1, 1, tzinfo=UTC),
        artifact_hash="f" * 64,
        sequence=0,
        name=preserve_path.name,
        file_id=(1, 99),
    )
    to_delete = protected_backups._select_retention_deletions(
        [*items, preserve], preserve=preserve_path
    )
    assert [item.name for item in to_delete] == ["point-0"]


def test_retention_keeps_newest_twelve_verified_points(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    can_delete = _object_bound_deletion_available(destination)
    created, results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT + 1
    )

    assert all(result.published is True and result.verified is True for result in results)
    remaining = _eligible_names(destination)
    if can_delete:
        assert all(result.retention == RETENTION_COMPLETED for result in results)
        assert len(remaining) == VERIFIED_RETENTION_LIMIT
        assert created[0] not in remaining
        assert set(created[1:]) == remaining
        verified = protected_backups._verified_managed_recovery_points(
            destination,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
        )
        assert [path.name for path in verified] == created[1:]
        return
    assert all(result.retention == RETENTION_COMPLETED for result in results[:-1])
    assert results[-1].retention == RETENTION_FAILED
    assert remaining == set(created)
    candidates = protected_backups._list_retention_candidates(
        destination,
        protection_state=PROTECTION_STATE,
        protection_mode=PROTECTION_MODE,
    )
    to_delete = protected_backups._select_retention_deletions(
        candidates, preserve=destination / created[-1]
    )
    assert [item.name for item in to_delete] == [created[0]]


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

    can_delete = _object_bound_deletion_available(destination)
    created, _results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT + 1
    )

    remaining_verified = {
        path.name
        for path in protected_backups._verified_managed_recovery_points(
            destination,
            protection_state=PROTECTION_STATE,
            protection_mode=PROTECTION_MODE,
        )
    }
    if can_delete:
        assert remaining_verified == set(created[1:])
    else:
        assert remaining_verified == set(created)
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

    def fail_commit(_candidates) -> None:
        raise OSError("synthetic retention unlink failure")

    monkeypatch.setattr(protected_backups, "_commit_retention_deletions", fail_commit)
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


@pytest.mark.parametrize(
    ("protection_state", "protection_mode", "expected_action"),
    [
        (
            PLAINTEXT_SYNCED_STATE,
            PLAINTEXT_SYNCED_MODE,
            PLAINTEXT_RETENTION_ACTION_REQUIRED,
        ),
        (PROTECTION_STATE, PROTECTION_MODE, RETENTION_ACTION_REQUIRED),
    ],
)
def test_forced_retention_failure_action_matches_publication_mode(
    tmp_path: Path,
    synthetic_database,
    monkeypatch,
    protection_state: str,
    protection_mode: str,
    expected_action: str,
) -> None:
    destination = tmp_path / "retention-failure-destination"
    destination.mkdir()

    def fail_commit(_candidates) -> None:
        raise OSError("synthetic retention unlink failure")

    monkeypatch.setattr(protected_backups, "_commit_retention_deletions", fail_commit)
    result = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        protection_state=protection_state,
        protection_mode=protection_mode,
    )

    assert result.published is True
    assert result.verified is True
    assert result.read_back == "verified"
    assert result.retention == RETENTION_FAILED
    assert result.action_required == expected_action
    assert result.protection_state == protection_state
    assert result.protection_mode == protection_mode
    if protection_mode == PLAINTEXT_SYNCED_MODE:
        assert "protected" not in expected_action
        assert result.action_required != RETENTION_ACTION_REQUIRED
    artifact = next(path for path in destination.iterdir() if is_managed_recovery_name(path.name))
    manifest = _manifest_of(artifact)
    assert manifest["protection_state"] == protection_state
    assert manifest["protection_mode"] == protection_mode
    verified, _digest, _size = protected_backups._verify_artifact(artifact)
    assert verified["snapshot_sha256"] == manifest["snapshot_sha256"]


@pytest.mark.parametrize(
    ("kept_state", "kept_mode", "new_state", "new_mode"),
    [
        (
            PROTECTION_STATE,
            PROTECTION_MODE,
            PLAINTEXT_SYNCED_STATE,
            PLAINTEXT_SYNCED_MODE,
        ),
        (
            PLAINTEXT_SYNCED_STATE,
            PLAINTEXT_SYNCED_MODE,
            PROTECTION_STATE,
            PROTECTION_MODE,
        ),
    ],
)
def test_retention_keeps_the_other_protection_pair(
    tmp_path: Path,
    synthetic_database,
    monkeypatch,
    kept_state: str,
    kept_mode: str,
    new_state: str,
    new_mode: str,
) -> None:
    destination = tmp_path / "mixed-protection-destination"
    destination.mkdir()
    created, _results = _publish_series(
        monkeypatch,
        synthetic_database,
        destination,
        VERIFIED_RETENTION_LIMIT,
        protection_state=kept_state,
        protection_mode=kept_mode,
    )
    before = {name: (destination / name).read_bytes() for name in created}

    result = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        now=datetime(2035, 2, 1, 8, 0, 0, tzinfo=UTC),
        protection_state=new_state,
        protection_mode=new_mode,
    )

    assert result.published is True
    assert result.verified is True
    assert result.read_back == "verified"
    assert result.retention == RETENTION_COMPLETED
    assert result.action_required is None
    assert result.protection_state == new_state
    assert result.protection_mode == new_mode
    for name, payload in before.items():
        assert (destination / name).read_bytes() == payload
    assert _eligible_names(
        destination, protection_state=kept_state, protection_mode=kept_mode
    ) == set(created)
    added = _eligible_names(destination, protection_state=new_state, protection_mode=new_mode)
    assert len(added) == 1
    assert added.isdisjoint(created)


@pytest.mark.parametrize(
    ("target_state", "target_mode", "other_state", "other_mode"),
    [
        (
            PROTECTION_STATE,
            PROTECTION_MODE,
            PLAINTEXT_SYNCED_STATE,
            PLAINTEXT_SYNCED_MODE,
        ),
        (
            PLAINTEXT_SYNCED_STATE,
            PLAINTEXT_SYNCED_MODE,
            PROTECTION_STATE,
            PROTECTION_MODE,
        ),
    ],
)
def test_mixed_mode_retention_thirteenth_deletes_only_same_pair_oldest(
    tmp_path: Path,
    synthetic_database,
    monkeypatch,
    target_state: str,
    target_mode: str,
    other_state: str,
    other_mode: str,
) -> None:
    destination = tmp_path / "mixed-protection-retention-bound"
    destination.mkdir()
    target_created, _target_results = _publish_series(
        monkeypatch,
        synthetic_database,
        destination,
        VERIFIED_RETENTION_LIMIT,
        now_day=1,
        protection_state=target_state,
        protection_mode=target_mode,
    )
    other_created, _other_results = _publish_series(
        monkeypatch,
        synthetic_database,
        destination,
        VERIFIED_RETENTION_LIMIT,
        now_day=13,
        protection_state=other_state,
        protection_mode=other_mode,
    )
    target_before = {name: (destination / name).read_bytes() for name in target_created}
    other_before = {name: (destination / name).read_bytes() for name in other_created}

    result = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        now=datetime(2035, 1, 31, 8, 0, 0, tzinfo=UTC),
        protection_state=target_state,
        protection_mode=target_mode,
    )

    assert result.published is True
    assert result.verified is True
    assert result.retention == RETENTION_COMPLETED
    target_after = _eligible_names(
        destination,
        protection_state=target_state,
        protection_mode=target_mode,
    )
    other_after = _eligible_names(
        destination,
        protection_state=other_state,
        protection_mode=other_mode,
    )
    assert len(target_after) == VERIFIED_RETENTION_LIMIT
    assert target_created[0] not in target_after
    assert set(target_created[1:]).issubset(target_after)
    assert len(target_after - set(target_created)) == 1
    assert other_after == set(other_created)
    assert not (destination / target_created[0]).exists()
    for name in target_created[1:]:
        assert (destination / name).read_bytes() == target_before[name]
    for name, payload in other_before.items():
        assert (destination / name).read_bytes() == payload


def test_retention_ordering_is_independent_of_directory_listing(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    can_delete = _object_bound_deletion_available(destination)
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

    assert result.published is True
    assert result.verified is True
    assert len(added) == 1
    if can_delete:
        assert result.retention == RETENTION_COMPLETED
        assert len(remaining) == VERIFIED_RETENTION_LIMIT
        assert created[0] not in remaining
        expected = set(created[1:]) | added
        assert remaining == expected
        return
    assert result.retention == RETENTION_FAILED
    assert remaining == set(created) | added
    candidates = protected_backups._list_retention_candidates(
        destination,
        protection_state=PROTECTION_STATE,
        protection_mode=PROTECTION_MODE,
    )
    to_delete = protected_backups._select_retention_deletions(
        candidates, preserve=destination / next(iter(added))
    )
    assert [item.name for item in to_delete] == [created[0]]


def test_same_timestamp_retention_uses_verified_hash_then_sequence(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    can_delete = _object_bound_deletion_available(destination)
    now = datetime(2035, 6, 7, 8, 9, 10, 123000, tzinfo=UTC)
    captured: list[protected_backups._RetentionCandidate] = []
    for _index in range(VERIFIED_RETENTION_LIMIT + 1):
        before = _managed_names(destination)
        _publish(monkeypatch, synthetic_database, destination, now=now)
        added = _managed_names(destination) - before
        assert len(added) == 1
        added_name = next(iter(added))
        candidate = next(
            item
            for item in protected_backups._list_retention_candidates(
                destination,
                protection_state=PROTECTION_STATE,
                protection_mode=PROTECTION_MODE,
            )
            if item.name == added_name
        )
        captured.append(candidate)

    preserve = captured[-1]
    others = [item for item in captured if item.name != preserve.name]
    others.sort(key=lambda item: item.recency_key(), reverse=True)
    expected = {preserve.name} | {item.name for item in others[: VERIFIED_RETENTION_LIMIT - 1]}
    remaining = _eligible_names(destination)
    hashes = {item.artifact_hash for item in captured}
    assert len(hashes) >= 1
    if can_delete:
        assert remaining == expected
        assert len(remaining) == VERIFIED_RETENTION_LIMIT
        return
    assert remaining == {item.name for item in captured}
    to_delete = protected_backups._select_retention_deletions(captured, preserve=preserve.path)
    assert {item.name for item in captured} - {item.name for item in to_delete} == expected


def test_clock_rollback_keeps_replacement_and_exact_twelve(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    can_delete = _object_bound_deletion_available(destination)
    created, _results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT
    )
    result = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        now=datetime(2010, 1, 1, 8, 0, 0, tzinfo=UTC),
    )
    remaining = _eligible_names(destination)
    added = remaining - set(created)

    assert result.published is True
    assert result.verified is True
    assert len(added) == 1
    if can_delete:
        assert result.retention == RETENTION_COMPLETED
        assert len(remaining) == VERIFIED_RETENTION_LIMIT
        assert created[0] not in remaining
        assert set(created[1:]) | added == remaining
        return
    assert result.retention == RETENTION_FAILED
    assert remaining == set(created) | added
    candidates = protected_backups._list_retention_candidates(
        destination,
        protection_state=PROTECTION_STATE,
        protection_mode=PROTECTION_MODE,
    )
    to_delete = protected_backups._select_retention_deletions(
        candidates, preserve=destination / next(iter(added))
    )
    assert [item.name for item in to_delete] == [created[0]]


def test_preserve_outside_nominal_top_twelve_caps_verified_set(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    can_delete = _object_bound_deletion_available(destination)
    created, _results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT
    )
    result = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        now=datetime(1999, 12, 31, 23, 59, 59, tzinfo=UTC),
    )
    remaining = _eligible_names(destination)
    preserve = next(iter(remaining - set(created)))
    nominal_newest = set(created)

    assert result.published is True
    assert result.verified is True
    assert preserve in remaining
    assert preserve not in nominal_newest
    if can_delete:
        assert result.retention == RETENTION_COMPLETED
        assert len(remaining) == VERIFIED_RETENTION_LIMIT
        assert created[0] not in remaining
        return
    assert result.retention == RETENTION_FAILED
    assert remaining == set(created) | {preserve}
    candidates = protected_backups._list_retention_candidates(
        destination,
        protection_state=PROTECTION_STATE,
        protection_mode=PROTECTION_MODE,
    )
    to_delete = protected_backups._select_retention_deletions(
        candidates, preserve=destination / preserve
    )
    assert [item.name for item in to_delete] == [created[0]]


def test_missing_and_mismatched_created_at_are_not_deleted(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    scratch = tmp_path / "scratch-protected-destination"
    scratch.mkdir()
    _publish(monkeypatch, synthetic_database, scratch)
    source = next(path for path in scratch.iterdir() if is_managed_recovery_name(path.name))
    with zipfile.ZipFile(source) as archive:
        snapshot_bytes = archive.read("snapshot.sqlite3")
        manifest = json.loads(archive.read("manifest.json"))
    snapshot_path = tmp_path / "synthetic-snapshot.sqlite3"
    snapshot_path.write_bytes(snapshot_bytes)

    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    missing_manifest = dict(manifest)
    missing_manifest.pop("created_at", None)
    missing_payload = protected_backups._artifact_bytes(snapshot_path, missing_manifest)
    missing_digest = hashlib.sha256(missing_payload).hexdigest()
    missing_time = datetime(2034, 5, 6, 7, 8, 9, tzinfo=UTC)
    missing_path = destination / (
        f"{protected_backups.MANAGED_FILENAME_PREFIX}"
        f"{missing_time.strftime('%Y%m%dT%H%M%S%fZ')}-"
        f"{missing_digest[:16]}{protected_backups.MANAGED_FILENAME_SUFFIX}"
    )
    missing_path.write_bytes(missing_payload)
    protected_backups._verify_artifact(missing_path)

    good_payload = source.read_bytes()
    good_digest = hashlib.sha256(good_payload).hexdigest()[:16]
    mismatched = (
        destination / f"hermes_recovery_19990101T000000000000Z-{good_digest}.hermes-recovery"
    )
    mismatched.write_bytes(good_payload)
    protected_backups._verify_artifact(mismatched)

    can_delete = _object_bound_deletion_available(destination)
    created, results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT + 1
    )

    remaining_eligible = _eligible_names(destination)
    assert all(item.published is True and item.verified is True for item in results)
    if can_delete:
        assert all(item.retention == RETENTION_COMPLETED for item in results)
        assert remaining_eligible == set(created[1:])
        assert len(remaining_eligible) == VERIFIED_RETENTION_LIMIT
    else:
        assert results[-1].retention == RETENTION_FAILED
        assert remaining_eligible == set(created)
    assert missing_path.read_bytes() == missing_payload
    assert mismatched.read_bytes() == good_payload
    assert missing_path.name not in remaining_eligible
    assert mismatched.name not in remaining_eligible


def test_retention_refuses_to_delete_pathname_replaced_after_handle_verification(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    created, _results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT
    )
    _bypass_preflight_if_unsupported(monkeypatch, destination)
    replacement = b"replacement-after-verification"

    def replace_after_handle_verification(
        targets: list[protected_backups._DeletionTarget],
    ) -> None:
        assert targets
        path = targets[0].candidate.path
        os.unlink(path)
        path.write_bytes(replacement)

    monkeypatch.setattr(
        protected_backups, "_retention_before_destroy", replace_after_handle_verification
    )
    result = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        now=datetime(2035, 1, 20, 9, 0, 0, tzinfo=UTC),
    )
    target = destination / created[0]

    assert result.published is True
    assert result.verified is True
    assert result.retention != RETENTION_COMPLETED
    assert result.retention == RETENTION_FAILED
    assert result.action_required == RETENTION_ACTION_REQUIRED
    assert target.is_file()
    assert target.read_bytes() == replacement
    assert created[0] in _managed_names(destination)


def test_retention_survives_rename_aside_and_replacement_before_destroy(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    created, _results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT
    )
    _bypass_preflight_if_unsupported(monkeypatch, destination)
    replacement = b"replacement-after-rename-aside"

    def rename_aside_then_replace(targets: list[protected_backups._DeletionTarget]) -> None:
        assert targets
        path = targets[0].candidate.path
        aside = path.parent / f"aside-{path.name}"
        os.rename(path, aside)
        path.write_bytes(replacement)

    monkeypatch.setattr(protected_backups, "_retention_before_destroy", rename_aside_then_replace)
    result = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        now=datetime(2035, 1, 20, 9, 0, 0, tzinfo=UTC),
    )
    target = destination / created[0]

    assert result.published is True
    assert result.verified is True
    assert result.retention == RETENTION_FAILED
    assert target.is_file()
    assert target.read_bytes() == replacement


def test_preflight_failure_deletes_no_retention_candidates(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    created, _results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT
    )
    noop_retain = protected_backups._retain_verified_recovery_points

    monkeypatch.setattr(
        protected_backups,
        "_retain_verified_recovery_points",
        lambda *_args, **_kwargs: (RETENTION_COMPLETED, None),
    )
    _publish(
        monkeypatch,
        synthetic_database,
        destination,
        now=datetime(2035, 1, 13, 8, 0, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(protected_backups, "_retain_verified_recovery_points", noop_retain)

    def fail_preflight(_destination: Path) -> None:
        raise ProtectedBackupError("retention identity is not proven")

    monkeypatch.setattr(protected_backups, "_preflight_object_bound_deletion", fail_preflight)
    before = _managed_names(destination)
    assert len(before) == VERIFIED_RETENTION_LIMIT + 1
    result = _publish(
        monkeypatch,
        synthetic_database,
        destination,
        now=datetime(2035, 1, 20, 9, 0, 0, tzinfo=UTC),
    )

    assert result.published is True
    assert result.retention == RETENTION_FAILED
    remaining = _managed_names(destination)
    assert before.issubset(remaining)
    assert len(remaining) == VERIFIED_RETENTION_LIMIT + 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handle deletion")
def test_windows_same_handle_deletion_without_replacement_hook(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    disposition_calls = {"count": 0}
    real_mark = protected_backups._mark_deletion_target
    unlinked_names: list[str] = []
    real_unlink = os.unlink

    def counting_mark(target: protected_backups._DeletionTarget) -> None:
        assert target.kind == "windows"
        disposition_calls["count"] += 1
        real_mark(target)

    def spy_unlink(path, *args, **kwargs):
        unlinked_names.append(Path(path).name)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(protected_backups, "_mark_deletion_target", counting_mark)
    monkeypatch.setattr(os, "unlink", spy_unlink)
    created, results = _publish_series(
        monkeypatch, synthetic_database, destination, VERIFIED_RETENTION_LIMIT + 1
    )

    assert results[-1].retention == RETENTION_COMPLETED
    assert created[0] not in _eligible_names(destination)
    assert disposition_calls["count"] >= 1
    assert not any(is_managed_recovery_name(name) for name in unlinked_names)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux unlinkat")
def test_linux_handle_unlink_is_object_bound_or_fails_closed(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "hermes_recovery_20350101T000000000000Z-0123456789abcdef.hermes-recovery"
    payload = b"delete-via-fd"
    path.write_bytes(payload)
    candidate = protected_backups._RetentionCandidate(
        path=path,
        created_at=datetime(2035, 1, 1, tzinfo=UTC),
        artifact_hash=hashlib.sha256(payload).hexdigest(),
        sequence=0,
        name=path.name,
        file_id=protected_backups._file_identity(path.lstat()),
    )
    unlinked: list[str] = []
    real_os_unlink = os.unlink
    real_path_unlink = Path.unlink

    def spy_os_unlink(name, *args, **kwargs):
        unlinked.append(Path(name).name)
        return real_os_unlink(name, *args, **kwargs)

    def spy_path_unlink(self, *args, **kwargs):
        unlinked.append(self.name)
        return real_path_unlink(self, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", spy_os_unlink)
    monkeypatch.setattr(Path, "unlink", spy_path_unlink)
    target = protected_backups._open_deletion_target(candidate)
    try:
        try:
            protected_backups._mark_deletion_target(target)
        except OSError:
            assert path.is_file()
            assert path.read_bytes() == payload
        else:
            assert not path.exists()
        assert path.name not in unlinked
    finally:
        protected_backups._close_deletion_target(target)
