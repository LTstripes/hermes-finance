from __future__ import annotations

import hashlib
import json
import os
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


def _publish(monkeypatch, database, destination: Path):
    monkeypatch.setattr(
        protected_backups,
        "_git_identity",
        lambda _checkout: "a" * 40,
    )
    return publish_recovery_point(
        database,
        destination,
        protection_state=PROTECTION_STATE,
        protection_mode=PROTECTION_MODE,
        source_checkout=Path(__file__).resolve().parents[2],
        now=datetime(2035, 1, 2, 3, 4, 5, 678000, tzinfo=UTC),
    )


def test_publisher_creates_verified_single_artifact_with_deterministic_manifest(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()

    result = _publish(monkeypatch, synthetic_database, destination)

    assert result.status == "published"
    assert result.read_back == "verified"
    assert result.name is not None
    assert is_managed_recovery_name(result.name)
    artifact = destination / result.name
    assert result.artifact_sha256 == hashlib.sha256(artifact.read_bytes()).hexdigest()
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
    result = _publish(monkeypatch, synthetic_database, destination)
    with zipfile.ZipFile(destination / result.name) as archive:
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
    result = _publish(monkeypatch, synthetic_database, destination)
    artifact = destination / result.name
    artifact.write_bytes(b"corrupt")

    with pytest.raises(ProtectedBackupError, match="read-back verification"):
        protected_backups._verify_artifact(artifact)


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


def test_readback_corruption_during_publish_removes_new_final_name(
    tmp_path: Path, synthetic_database, monkeypatch
) -> None:
    destination = tmp_path / "mounted-protected-destination"
    destination.mkdir()
    monkeypatch.setattr(protected_backups, "_git_identity", lambda _checkout: "f" * 40)
    monkeypatch.setattr(
        protected_backups,
        "_verify_artifact",
        lambda _path: (_ for _ in ()).throw(ProtectedBackupError("synthetic corruption")),
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
    prior = _publish(monkeypatch, synthetic_database, destination)
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
    assert (destination / prior.name).is_file()


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
    tmp_path: Path,
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
