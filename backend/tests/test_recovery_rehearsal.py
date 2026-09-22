from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.recovery_rehearsal_cli import main as recovery_rehearsal_main
from hermes_finance.services import protected_backups, recovery_rehearsal
from hermes_finance.services.protected_backups import PROTECTION_MODE, PROTECTION_STATE
from hermes_finance.services.recovery_rehearsal import (
    RELATIONSHIP_FORWARD_UPGRADE,
    RELATIONSHIP_SAME_REVISION,
    CheckoutProof,
    RecoveryRehearsalError,
    rehearse_recovery,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG = REPOSITORY_ROOT / "backend" / "alembic.ini"


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _alembic_head() -> str:
    heads = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG))).get_heads()
    assert len(heads) == 1
    return heads[0]


def _make_snapshot(path: Path, *, revision: str, month_count: int = 1) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);
            CREATE TABLE reporting_months (
                id INTEGER PRIMARY KEY,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                status VARCHAR(16) NOT NULL
            );
            CREATE INDEX ix_reporting_months_year ON reporting_months(year);
            """
        )
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        for index in range(month_count):
            connection.execute(
                "INSERT INTO reporting_months VALUES (?, ?, ?, 'open')",
                (index + 1, 2035, index + 1),
            )
        connection.commit()
    finally:
        connection.close()


def _managed_artifact(
    root: Path,
    *,
    revision: str | None = None,
    producer_sha: str | None = None,
    month_count: int = 1,
) -> Path:
    destination = root / "mounted-protected-destination"
    destination.mkdir(parents=True)
    snapshot = root / "snapshot.sqlite3"
    source_revision = revision or _alembic_head()
    _make_snapshot(snapshot, revision=source_revision, month_count=month_count)
    snapshot_bytes = snapshot.read_bytes()
    manifest = {
        "artifact_identity_sha256": "0" * 64,
        "artifact_size_bytes": 0,
        "created_at": datetime(2035, 1, 2, 3, 4, 5, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "format_version": protected_backups.FORMAT_VERSION,
        "producer_git_sha": producer_sha or _git_head(),
        "protection_state": PROTECTION_STATE,
        "protection_mode": PROTECTION_MODE,
        "snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
        "snapshot_size_bytes": len(snapshot_bytes),
        "source_alembic_revisions": [source_revision],
    }
    artifact_bytes = protected_backups._artifact_bytes(snapshot, manifest)
    digest = hashlib.sha256(artifact_bytes).hexdigest()
    artifact = destination / (
        f"hermes_recovery_20350102T030405000000Z-{digest[:16]}.hermes-recovery"
    )
    artifact.write_bytes(artifact_bytes)
    snapshot.unlink()
    return artifact


def _target_paths(tmp_path: Path, name: str = "isolated-recovery") -> tuple[Path, Path, Path]:
    parent = tmp_path / "target-parent"
    parent.mkdir(exist_ok=True)
    profile = parent / name
    data = profile / "data"
    database = data / "finance.db"
    return profile, data, database


def _proof() -> CheckoutProof:
    checkout = REPOSITORY_ROOT.resolve()
    return CheckoutProof(
        checkout=checkout,
        selected_sha=_git_head(),
        repository_key="github.com/ltstripes/hermes-finance",
        git_directory=checkout / ".git",
        common_directory=checkout / ".git",
    )


def _install_isolated_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    calls: list[str] | None = None,
    *,
    runtime_boundaries: tuple[Path, ...] = (),
    worktree_boundaries: tuple[Path, ...] = (),
) -> CheckoutProof:
    proof = _proof()
    events = calls if calls is not None else []
    monkeypatch.setattr(
        recovery_rehearsal,
        "_validate_recovery_checkout",
        lambda *_args, **_kwargs: proof,
    )
    monkeypatch.setattr(
        recovery_rehearsal,
        "_runtime_inventory",
        lambda _path: runtime_boundaries,
    )
    monkeypatch.setattr(
        recovery_rehearsal,
        "_worktree_inventory",
        lambda _path: worktree_boundaries or (tmp_path / "development-worktree",),
    )
    monkeypatch.setattr(recovery_rehearsal, "_recheck_checkout", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        recovery_rehearsal,
        "_prepare_and_validate",
        lambda _checkout: events.extend(("prepare", "validate")),
    )
    monkeypatch.setattr(
        recovery_rehearsal,
        "_start_and_probe",
        lambda _checkout, _database, **_kwargs: events.append("start-readiness"),
    )
    return proof


def _run_isolated(
    artifact: Path,
    tmp_path: Path,
    *,
    profile: Path | None = None,
    data: Path | None = None,
    database: Path | None = None,
):
    default_profile, default_data, default_database = _target_paths(tmp_path)
    return rehearse_recovery(
        artifact,
        protection_state=PROTECTION_STATE,
        protection_mode=PROTECTION_MODE,
        selected_recovery_sha=_git_head(),
        recovery_checkout=REPOSITORY_ROOT,
        control_checkout=REPOSITORY_ROOT,
        runtime_config=tmp_path / "runtime-config.json",
        target_profile=profile or default_profile,
        target_data=data or default_data,
        target_database=database or default_database,
    )


def _validated_target_plan(
    artifact: Path,
    tmp_path: Path,
    *,
    database_name: str = "finance.db",
) -> tuple[recovery_rehearsal.VerifiedSource, recovery_rehearsal.TargetPlan]:
    source = recovery_rehearsal._verify_source(
        artifact,
        protection_state=PROTECTION_STATE,
        protection_mode=PROTECTION_MODE,
    )
    profile, data, _database = _target_paths(tmp_path)
    target = recovery_rehearsal._validate_fresh_target(
        target_profile=profile,
        target_data=data,
        target_database=data / database_name,
        source=source,
        checkout=_proof(),
        forbidden=(),
    )
    return source, target


def test_isolated_restore_composes_prepare_validate_and_bounded_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _managed_artifact(tmp_path)
    source_before = artifact.read_bytes()
    calls: list[str] = []
    _install_isolated_harness(monkeypatch, tmp_path, calls)

    result = _run_isolated(artifact, tmp_path)

    profile, data, database = _target_paths(tmp_path)
    assert result.status == "rehearsed"
    assert result.source_verified is True
    assert result.source_unchanged is True
    assert result.schema_relationship == RELATIONSHIP_SAME_REVISION
    assert result.resulting_alembic_revisions == (_alembic_head(),)
    assert result.structural_counts == {
        "user_table_count": 1,
        "user_index_count": 1,
        "user_view_count": 0,
        "populated_user_table_count": 1,
        "reporting_month_count": 1,
    }
    assert calls == ["prepare", "validate", "start-readiness"]
    assert database.is_file()
    sidecar = json.loads((data / ".hermes-data-identity.json").read_text(encoding="utf-8"))
    assert sidecar["kind"] == "recovery_rehearsal"
    assert sidecar["selected_recovery_sha"] == _git_head()
    assert str(profile) not in json.dumps(result.as_dict())
    assert artifact.read_bytes() == source_before


@pytest.mark.parametrize("case", ["missing", "corrupt", "wrong-name", "unreadable"])
def test_wrong_missing_corrupt_or_unreadable_source_fails_before_target_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    artifact = _managed_artifact(tmp_path)
    if case == "missing":
        artifact.unlink()
    elif case == "corrupt":
        artifact.write_bytes(b"not-a-recovery-point")
    elif case == "wrong-name":
        renamed = artifact.with_name("foreign.hermes-recovery")
        artifact.rename(renamed)
        artifact = renamed
    else:
        monkeypatch.setattr(
            recovery_rehearsal,
            "_open_regular_read_only",
            lambda _path: (_ for _ in ()).throw(PermissionError("synthetic")),
        )
    _install_isolated_harness(monkeypatch, tmp_path)
    profile, _, _ = _target_paths(tmp_path)

    with pytest.raises(RecoveryRehearsalError) as captured:
        _run_isolated(artifact, tmp_path)

    assert captured.value.stage == "source-verification"
    assert not profile.exists()


def test_missing_or_wrong_protection_attestation_fails_before_source_or_target_mutation(
    tmp_path: Path,
) -> None:
    artifact = _managed_artifact(tmp_path)
    profile, data, database = _target_paths(tmp_path)
    source_before = artifact.read_bytes()

    with pytest.raises(RecoveryRehearsalError) as captured:
        rehearse_recovery(
            artifact,
            protection_state="unknown",
            protection_mode=PROTECTION_MODE,
            selected_recovery_sha=_git_head(),
            recovery_checkout=REPOSITORY_ROOT,
            control_checkout=REPOSITORY_ROOT,
            runtime_config=tmp_path / "runtime-config.json",
            target_profile=profile,
            target_data=data,
            target_database=database,
        )

    assert captured.value.stage == "protection"
    assert artifact.read_bytes() == source_before
    assert not profile.exists()


def test_unknown_source_revision_fails_compatibility_before_target_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _managed_artifact(tmp_path, revision="unknown_revision")
    _install_isolated_harness(monkeypatch, tmp_path)
    profile, _, _ = _target_paths(tmp_path)

    with pytest.raises(RecoveryRehearsalError) as captured:
        _run_isolated(artifact, tmp_path)

    assert captured.value.stage == "schema-compatibility"
    assert not profile.exists()


@pytest.mark.parametrize("boundary_kind", ["stable", "preview", "development"])
def test_stable_preview_and_development_workspace_targets_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary_kind: str,
) -> None:
    artifact = _managed_artifact(tmp_path)
    stable = tmp_path / "owner-stable"
    preview = tmp_path / "owner-preview"
    development = tmp_path / "development-worktree"
    runtime = (stable, stable / "data", stable / "data" / "finance.db", preview)
    _install_isolated_harness(
        monkeypatch,
        tmp_path,
        runtime_boundaries=runtime,
        worktree_boundaries=(development,),
    )
    root = {"stable": stable, "preview": preview, "development": development}[boundary_kind]
    root.mkdir(parents=True)
    profile = root / "isolated-recovery"
    data = profile / "data"
    database = data / "finance.db"

    with pytest.raises(RecoveryRehearsalError) as captured:
        _run_isolated(
            artifact,
            tmp_path,
            profile=profile,
            data=data,
            database=database,
        )

    assert captured.value.stage == "target-boundary"
    assert not profile.exists()


def test_existing_stable_or_development_checkout_cannot_be_selected_for_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _managed_artifact(tmp_path)
    proof = _proof()
    _install_isolated_harness(
        monkeypatch,
        tmp_path,
        runtime_boundaries=(proof.checkout,),
    )
    profile, _, _ = _target_paths(tmp_path)

    with pytest.raises(RecoveryRehearsalError) as captured:
        _run_isolated(artifact, tmp_path)

    assert captured.value.stage == "runtime-inventory"
    assert not profile.exists()


def test_non_empty_or_conflicting_target_is_rejected_without_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _managed_artifact(tmp_path)
    _install_isolated_harness(monkeypatch, tmp_path)
    profile, data, database = _target_paths(tmp_path)
    profile.mkdir()
    marker = profile / "foreign.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(RecoveryRehearsalError) as captured:
        _run_isolated(
            artifact,
            tmp_path,
            profile=profile,
            data=data,
            database=database,
        )

    assert captured.value.stage == "target-boundary"
    assert marker.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize(
    "database_name",
    [
        "finance#archive.db",
        "finance%archive.db",
        "finance%23encoded-looking.db",
        "finance records.db",
        "финансы.db",
    ],
)
def test_read_only_sqlite_uri_preserves_literal_supported_database_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_name: str,
) -> None:
    artifact = _managed_artifact(tmp_path)
    _install_isolated_harness(monkeypatch, tmp_path)
    profile, data, _database = _target_paths(tmp_path)
    database = data / database_name

    result = _run_isolated(
        artifact,
        tmp_path,
        profile=profile,
        data=data,
        database=database,
    )

    assert result.status == "rehearsed"
    assert database.is_file()
    identity = recovery_rehearsal._file_identity(database.stat())
    assert identity is not None
    with recovery_rehearsal._open_database_read_only(
        database,
        expected_identity=identity,
        stage="test-read-only",
    ) as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE must_not_exist (id INTEGER)")
    assert {path.name for path in data.iterdir()} == {
        database_name,
        ".hermes-data-identity.json",
    }


@pytest.mark.parametrize(
    "database_name",
    [".hermes-data-identity.json", ".finance.db.recovery.incomplete"],
)
def test_reserved_generated_database_name_fails_before_target_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_name: str,
) -> None:
    artifact = _managed_artifact(tmp_path)
    source_before = artifact.read_bytes()
    _install_isolated_harness(monkeypatch, tmp_path)
    profile, data, _database = _target_paths(tmp_path)

    with pytest.raises(RecoveryRehearsalError) as captured:
        _run_isolated(
            artifact,
            tmp_path,
            profile=profile,
            data=data,
            database=data / database_name,
        )

    assert captured.value.stage == "target-boundary"
    assert not profile.exists()
    assert artifact.read_bytes() == source_before


def _make_directory_link(link: Path, target: Path) -> bool:
    if sys.platform == "win32":
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        return completed.returncode == 0
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        return False
    return True


def test_reparse_linked_target_is_rejected_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _managed_artifact(tmp_path)
    _install_isolated_harness(monkeypatch, tmp_path)
    real_parent = tmp_path / "real-target-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-target-parent"
    if not _make_directory_link(linked_parent, real_parent):
        pytest.skip("directory link creation is unavailable")
    profile = linked_parent / "isolated-recovery"
    data = profile / "data"
    database = data / "finance.db"

    with pytest.raises(RecoveryRehearsalError) as captured:
        _run_isolated(
            artifact,
            tmp_path,
            profile=profile,
            data=data,
            database=database,
        )

    assert captured.value.stage == "target-boundary"
    assert not (real_parent / "isolated-recovery").exists()


def test_bound_parent_prevents_ancestor_replacement_from_redirecting_creation(
    tmp_path: Path,
) -> None:
    artifact = _managed_artifact(tmp_path)
    source, target = _validated_target_plan(artifact, tmp_path)
    moved_parent = target.profile.parent.with_name("validated-parent-moved")
    replacement_created = False
    try:
        try:
            target.profile.parent.rename(moved_parent)
        except OSError:
            assert sys.platform == "win32"
            assert target.profile.parent.is_dir()
        else:
            target.profile.parent.mkdir()
            replacement_created = True
            with pytest.raises(RecoveryRehearsalError) as captured:
                recovery_rehearsal._create_target_directories(target)
            assert captured.value.stage == "restore-write"
            assert not target.profile.exists()
            assert not (moved_parent / target.profile.name).exists()
    finally:
        target.close()
        source.close()
    if not replacement_created:
        assert not target.profile.exists()


def test_database_publication_does_not_overwrite_late_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _managed_artifact(tmp_path)
    source, target = _validated_target_plan(artifact, tmp_path)
    recovery_rehearsal._create_target_directories(target)
    foreign = b"late foreign database"
    original_publish = recovery_rehearsal._DirectoryGuard.publish_no_overwrite

    def publish_with_conflict(
        guard: recovery_rehearsal._DirectoryGuard, staging_name: str, final_name: str
    ) -> None:
        (guard.path / final_name).write_bytes(foreign)
        original_publish(guard, staging_name, final_name)

    monkeypatch.setattr(
        recovery_rehearsal._DirectoryGuard,
        "publish_no_overwrite",
        publish_with_conflict,
    )
    try:
        with pytest.raises(RecoveryRehearsalError) as captured:
            recovery_rehearsal._restore_snapshot(source.snapshot_bytes, target)
        assert captured.value.stage == "restore-write"
        assert target.database.read_bytes() == foreign
    finally:
        target.close()
        source.close()


def test_staging_replacement_after_writer_close_is_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _managed_artifact(tmp_path)
    source_before = artifact.read_bytes()
    events: list[str] = []
    _install_isolated_harness(monkeypatch, tmp_path, events)
    alternate = tmp_path / "alternate-valid.sqlite3"
    _make_snapshot(alternate, revision=_git_head(), month_count=2)
    alternate_bytes = alternate.read_bytes()
    original_write = recovery_rehearsal._write_exclusive_leaf

    def replace_after_close(
        guard: recovery_rehearsal._DirectoryGuard, name: str, payload: bytes
    ) -> recovery_rehearsal._RegularFileGuard:
        created = original_write(guard, name, payload)
        if name == recovery_rehearsal._STAGING_NAME:
            created.close()
            created.path.unlink()
            created.path.write_bytes(alternate_bytes)
        return created

    monkeypatch.setattr(recovery_rehearsal, "_write_exclusive_leaf", replace_after_close)

    with pytest.raises(RecoveryRehearsalError) as captured:
        _run_isolated(artifact, tmp_path)

    assert captured.value.stage == "restore-write"
    assert events == []
    assert artifact.read_bytes() == source_before


def test_restored_snapshot_hash_is_rechecked_before_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _managed_artifact(tmp_path)
    source, target = _validated_target_plan(artifact, tmp_path)
    recovery_rehearsal._create_target_directories(target)
    recovery_rehearsal._restore_snapshot(source.snapshot_bytes, target)
    alternate = tmp_path / "alternate-before-start.sqlite3"
    _make_snapshot(alternate, revision=_git_head(), month_count=2)
    target.database.write_bytes(alternate.read_bytes())
    runtime_calls: list[str] = []
    monkeypatch.setattr(recovery_rehearsal, "_recheck_checkout", lambda *_a, **_k: None)
    monkeypatch.setattr(
        recovery_rehearsal,
        "_run_runtime_script",
        lambda *_a, **_k: runtime_calls.append("start"),
    )
    try:
        with pytest.raises(RecoveryRehearsalError) as captured:
            recovery_rehearsal._start_and_probe(
                _proof(),
                target,
                expected_snapshot_sha256=str(source.manifest["snapshot_sha256"]),
            )
        assert captured.value.stage == "pre-start-restored-snapshot"
        assert runtime_calls == []
    finally:
        target.close()
        source.close()


@pytest.mark.parametrize("alias_kind", ["foreign", "source"])
def test_sidecar_exclusive_creation_does_not_follow_late_alias(
    tmp_path: Path,
    alias_kind: str,
) -> None:
    artifact = _managed_artifact(tmp_path)
    source_before = artifact.read_bytes()
    source, target = _validated_target_plan(artifact, tmp_path)
    compatibility = recovery_rehearsal._compatibility(
        REPOSITORY_ROOT,
        tuple(source.manifest["source_alembic_revisions"]),
        str(source.manifest["producer_git_sha"]),
    )
    recovery_rehearsal._create_target_directories(target)
    recovery_rehearsal._restore_snapshot(source.snapshot_bytes, target)
    alias_target = artifact
    foreign = tmp_path / "foreign-sidecar-target"
    if alias_kind == "foreign":
        foreign.write_bytes(b"preserve foreign bytes")
        alias_target = foreign
    sidecar = target.data / ".hermes-data-identity.json"
    try:
        os.link(alias_target, sidecar)
    except OSError:
        target.close()
        source.close()
        pytest.skip("hard-link creation is unavailable")
    try:
        with pytest.raises(RecoveryRehearsalError) as captured:
            recovery_rehearsal._write_sidecar(
                target,
                source=source,
                checkout=_proof(),
                compatibility=compatibility,
            )
        assert captured.value.stage == "restore-write"
        assert alias_target.read_bytes() == (
            source_before if alias_kind == "source" else b"preserve foreign bytes"
        )
    finally:
        target.close()
        source.close()


def test_hardlinked_source_is_rejected_before_target_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _managed_artifact(tmp_path)
    linked = artifact.with_name(artifact.stem + "-linked" + artifact.suffix)
    os.link(artifact, linked)
    _install_isolated_harness(monkeypatch, tmp_path)
    profile, _, _ = _target_paths(tmp_path)

    with pytest.raises(RecoveryRehearsalError) as captured:
        _run_isolated(artifact, tmp_path)

    assert captured.value.stage == "source-verification"
    assert not profile.exists()


def test_source_change_during_runtime_is_detected_and_never_reported_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _managed_artifact(tmp_path)
    _install_isolated_harness(monkeypatch, tmp_path)

    def mutate_source(_checkout: CheckoutProof) -> None:
        artifact.write_bytes(artifact.read_bytes() + b"changed")

    monkeypatch.setattr(recovery_rehearsal, "_prepare_and_validate", mutate_source)

    with pytest.raises(RecoveryRehearsalError) as captured:
        _run_isolated(artifact, tmp_path)

    assert captured.value.stage == "source-immutability"


def test_current_graph_accepts_same_revision_and_one_linear_forward_upgrade() -> None:
    head = _alembic_head()
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG)))
    head_revision = script.get_revision(head)
    assert head_revision is not None
    previous = head_revision.down_revision
    assert isinstance(previous, str)
    producer = _git_head()

    same = recovery_rehearsal._compatibility(REPOSITORY_ROOT, (head,), producer)
    forward = recovery_rehearsal._compatibility(REPOSITORY_ROOT, (previous,), producer)

    assert same.relationship == RELATIONSHIP_SAME_REVISION
    assert same.selected_heads == (head,)
    assert forward.relationship == RELATIONSHIP_FORWARD_UPGRADE
    assert forward.selected_heads == (head,)


def test_full_sha_is_required_before_checkout_inspection(tmp_path: Path) -> None:
    with pytest.raises(RecoveryRehearsalError, match="full commit identity"):
        recovery_rehearsal._validate_recovery_checkout(
            tmp_path / "recovery", tmp_path / "control", "main"
        )


def test_runtime_inventory_binds_stable_preview_and_canonical_production(tmp_path: Path) -> None:
    stable = tmp_path / "stable"
    preview = tmp_path / "preview"
    config = tmp_path / "runtime-config.json"
    config.write_text(
        json.dumps(
            {
                "version": 1,
                "canonical_production": {
                    "checkout": str(stable),
                    "data_dir": str(stable / "data"),
                    "database": str(stable / "data" / "finance.db"),
                },
                "profiles": [
                    {
                        "id": "stable",
                        "type": "stable",
                        "checkout": str(stable),
                        "data_dir": str(stable / "data"),
                        "database": str(stable / "data" / "finance.db"),
                    },
                    {
                        "id": "preview",
                        "type": "preview",
                        "checkout": str(preview),
                        "data_dir": str(preview / "data"),
                        "database": str(preview / "data" / "finance.db"),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    boundaries = recovery_rehearsal._runtime_inventory(config)

    assert stable.resolve() in boundaries
    assert preview.resolve() in boundaries
    assert (stable / "data" / "finance.db").resolve() in boundaries


def test_runtime_inventory_rejects_stable_that_differs_from_canonical_production(
    tmp_path: Path,
) -> None:
    stable = tmp_path / "stable"
    other = tmp_path / "other-stable"
    config = tmp_path / "runtime-config.json"
    config.write_text(
        json.dumps(
            {
                "version": 1,
                "canonical_production": {
                    "checkout": str(stable),
                    "data_dir": str(stable / "data"),
                    "database": str(stable / "data" / "finance.db"),
                },
                "profiles": [
                    {
                        "id": "stable",
                        "type": "stable",
                        "checkout": str(other),
                        "data_dir": str(other / "data"),
                        "database": str(other / "data" / "finance.db"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RecoveryRehearsalError, match="canonical production"):
        recovery_rehearsal._runtime_inventory(config)


def test_cli_argument_failure_is_json_and_does_not_echo_private_inputs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_value = "owner-private-recovery-location"

    exit_code = recovery_rehearsal_main(["--recovery-point", private_value])

    assert exit_code == 2
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["status"] == "action_required"
    assert payload["failure_stage"] == "arguments"
    assert private_value not in output


def test_bounded_start_reuses_existing_readiness_and_adds_recovery_surfaces() -> None:
    source = (REPOSITORY_ROOT / "scripts" / "start-local.ps1").read_text(encoding="utf-8-sig")

    assert "[switch]$RecoveryReadiness" in source
    assert "$RecoveryReadiness -and -not $ExitAfterReady" in source
    assert "http://127.0.0.1:8000/api/health" in source
    assert "http://127.0.0.1:8000/api/months" in source
    assert "http://127.0.0.1:8000/api/accounts" in source
    assert '"http://127.0.0.1:8000/api/months/{0}/dashboard"' in source
    assert "-RequireRecoverySurfaces ([bool]$RecoveryReadiness)" in source


def test_runtime_script_uses_windows_powershell_inbox_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    powershell = tmp_path / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    captured: dict[str, object] = {}

    def run_stub(
        command: list[str],
        *,
        cwd: Path,
        environment: dict[str, str],
        ownership_token: str,
        timeout: int | float,
    ) -> subprocess.CompletedProcess[str]:
        captured.update(
            command=command,
            cwd=cwd,
            environment=environment,
            ownership_token=ownership_token,
            timeout=timeout,
        )
        return subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

    monkeypatch.setenv("PSModulePath", str(tmp_path / "PowerShell" / "Modules"))
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / "external-stable-env"))
    monkeypatch.setattr(recovery_rehearsal, "_powershell", lambda: str(powershell))
    monkeypatch.setattr(recovery_rehearsal, "run_owned_process", run_stub)

    recovery_rehearsal._run_runtime_script(
        _proof(),
        script_name="prepare-runtime.ps1",
        arguments=["-Prepare"],
        stage="runtime-prepare",
        timeout=1,
    )

    environment = captured["environment"]
    assert environment["PSModulePath"] == str(powershell.parent.resolve() / "Modules")
    assert environment["PYTHONPATH"] == ""
    assert environment["HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN"] == ""
    assert environment["UV_PROJECT_ENVIRONMENT"] == str(REPOSITORY_ROOT / "backend" / ".venv")
    assert environment["UV_LINK_MODE"] == "copy"
    assert captured["command"][5] == str(
        REPOSITORY_ROOT / "scripts" / "recovery-runtime-boundary.ps1"
    )


def test_recovery_identity_headers_bind_every_readiness_response(tmp_path: Path) -> None:
    database = create_database(tmp_path / "readiness.db")
    Base.metadata.create_all(database.engine)
    application = create_app(database)
    expected = {
        "X-Hermes-Recovery-Token": "a" * 64,
        "X-Hermes-Recovery-Database-Identity": "b" * 64,
        "X-Hermes-Recovery-Checkout-SHA": "c" * 40,
    }
    application.state.recovery_readiness = {
        "token": expected["X-Hermes-Recovery-Token"],
        "database_identity": expected["X-Hermes-Recovery-Database-Identity"],
        "checkout_sha": expected["X-Hermes-Recovery-Checkout-SHA"],
    }
    try:
        with TestClient(application) as client:
            month = client.post(
                "/api/months",
                json={"year": 2035, "month": 1, "snapshot_date": "2035-01-31"},
            )
            assert month.status_code == 201
            responses = (
                client.get("/api/health"),
                client.get("/api/months"),
                client.get("/api/accounts"),
                client.get(f"/api/months/{month.json()['id']}/dashboard"),
            )
            for response in responses:
                assert response.status_code == 200, response.text
                for header, value in expected.items():
                    assert response.headers[header] == value
    finally:
        database.engine.dispose()


def _run_git_at(path: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _synthetic_bootstrap_checkout(
    tmp_path: Path, *, detached: bool = True
) -> tuple[Path, Path, Path, str]:
    checkout = tmp_path / "synthetic recovery checkout"
    control = tmp_path / "synthetic control checkout"
    scripts = checkout / "scripts"
    backend = checkout / "backend"
    frontend = checkout / "frontend"
    scripts.mkdir(parents=True)
    backend.mkdir()
    frontend.mkdir()
    for name in (
        "recovery-rehearsal.ps1",
        "recovery-bootstrap-boundary.ps1",
        "recovery-bootstrap-safety.ps1",
    ):
        shutil.copy2(REPOSITORY_ROOT / "scripts" / name, scripts)
    for path in (
        backend / "pyproject.toml",
        backend / "uv.lock",
        frontend / "package.json",
        frontend / "package-lock.json",
    ):
        path.write_text("synthetic\n", encoding="utf-8")
    (checkout / ".gitignore").write_text(
        "backend/.venv/\nfrontend/node_modules/\nfrontend/dist/\n.tmp/\n"
        ".hermes-runtime-prepared.json*\n",
        encoding="utf-8",
    )
    _run_git_at(checkout, "init", "--quiet")
    _run_git_at(checkout, "config", "user.name", "Hermes Recovery Test")
    _run_git_at(checkout, "config", "user.email", "recovery-test.invalid")
    _run_git_at(checkout, "remote", "add", "origin", "https://example.invalid/hermes-finance.git")
    _run_git_at(checkout, "add", ".")
    _run_git_at(checkout, "commit", "--quiet", "-m", "synthetic recovery checkout")
    head = _run_git_at(checkout, "rev-parse", "HEAD")
    if detached:
        _run_git_at(checkout, "checkout", "--quiet", "--detach", head)

    control.mkdir()
    _run_git_at(control, "init", "--quiet")
    _run_git_at(control, "config", "user.name", "Hermes Recovery Test")
    _run_git_at(control, "config", "user.email", "recovery-test.invalid")
    _run_git_at(control, "remote", "add", "origin", "https://example.invalid/hermes-finance.git")
    (control / "README.md").write_text("synthetic control\n", encoding="utf-8")
    _run_git_at(control, "add", ".")
    _run_git_at(control, "commit", "--quiet", "-m", "synthetic control checkout")

    stable = tmp_path / "synthetic stable runtime"
    runtime_config = tmp_path / "runtime.json"
    runtime_config.write_text(
        json.dumps(
            {
                "version": 1,
                "canonical_production": {
                    "checkout": str(stable),
                    "data_dir": str(stable / "data"),
                    "database": str(stable / "data" / "finance.db"),
                },
                "profiles": [
                    {
                        "id": "stable",
                        "type": "stable",
                        "checkout": str(stable),
                        "data_dir": str(stable / "data"),
                        "database": str(stable / "data" / "finance.db"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return checkout, control, runtime_config, head


def _bootstrap_command(
    powershell: str,
    checkout: Path,
    control: Path,
    runtime_config: Path,
    head: str,
    tmp_path: Path,
    *extra: str,
) -> list[str]:
    return [
        powershell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(checkout / "scripts" / "recovery-rehearsal.ps1"),
        "-RecoveryCheckout",
        str(checkout),
        "-RecoveryPoint",
        str(tmp_path / "point.hermes-recovery"),
        "-RecoverySha",
        head,
        "-ControlCheckout",
        str(control),
        "-RuntimeConfig",
        str(runtime_config),
        "-TargetProfile",
        str(tmp_path / "target"),
        "-TargetData",
        str(tmp_path / "target" / "data"),
        "-TargetDatabase",
        str(tmp_path / "target" / "data" / "finance.db"),
        "-ProtectionState",
        PROTECTION_STATE,
        "-ProtectionMode",
        PROTECTION_MODE,
        *extra,
    ]


_BOOTSTRAP_LISTENER_CHILD = """
import os
import socket
import sys
import time
from pathlib import Path

listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen(1)
Path(sys.argv[1]).write_text(
    f"{os.getpid()}:{listener.getsockname()[1]}", encoding="utf-8"
)
time.sleep(120)
"""


def _write_hanging_fake_uv(tmp_path: Path) -> tuple[Path, Path, Path]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    child_script = tmp_path / "bootstrap-listener-child.py"
    child_script.write_text(_BOOTSTRAP_LISTENER_CHILD, encoding="utf-8")
    marker = tmp_path / "owned-bootstrap-child.txt"
    (fake_bin / "uv.cmd").write_text(
        "@echo off\n"
        'start "" /b "%HERMES_TEST_PYTHON%" '
        '"%HERMES_TEST_CHILD_SCRIPT%" "%HERMES_TEST_CHILD_MARKER%"\n'
        ":wait\n"
        "ping -n 2 127.0.0.1 >nul\n"
        "goto wait\n",
        encoding="utf-8",
    )
    return fake_bin, child_script, marker


def _process_is_alive(process_id: int) -> bool:
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            return bool(
                kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                and int(exit_code.value) == 259
            )
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    return True


def _read_listener_marker(marker: Path) -> tuple[int, int]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            process_id, port = marker.read_text(encoding="utf-8").split(":", 1)
            return int(process_id), int(port)
        except (FileNotFoundError, ValueError):
            pass
        time.sleep(0.05)
    pytest.fail("listener marker was not written completely")


def _wait_process_gone(process_id: int) -> None:
    deadline = time.monotonic() + 10
    while _process_is_alive(process_id) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _process_is_alive(process_id)


def _assert_listener_unavailable(port: int) -> None:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        assert probe.connect_ex(("127.0.0.1", port)) != 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows bootstrap contract")
def test_bootstrap_neutralizes_external_uv_project_environment_before_first_uv_run(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    checkout, control, runtime_config, head = _synthetic_bootstrap_checkout(tmp_path)
    external_environment = tmp_path / "stable-external-env"
    external_environment.mkdir()
    marker = external_environment / "unchanged.txt"
    marker.write_text("preserve", encoding="utf-8")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    capture = tmp_path / "captured-environment.txt"
    (fake_bin / "uv.cmd").write_text(
        "@echo off\n"
        '> "%HERMES_TEST_CAPTURE%" echo %UV_PROJECT_ENVIRONMENT%\n'
        '>> "%HERMES_TEST_CAPTURE%" echo %UV_LINK_MODE%\n'
        ">&2 echo synthetic uv bootstrap diagnostic\n"
        'echo {"status":"synthetic"}\n'
        "exit /b 0\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]
    environment["HERMES_TEST_CAPTURE"] = str(capture)
    environment["UV_PROJECT_ENVIRONMENT"] = str(external_environment)
    completed = subprocess.run(
        _bootstrap_command(powershell, checkout, control, runtime_config, head, tmp_path),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    captured = capture.read_text(encoding="utf-8").splitlines()
    assert Path(captured[0]) == checkout / "backend" / ".venv"
    assert captured[1] == "copy"
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert "synthetic uv bootstrap diagnostic" not in completed.stdout
    assert "synthetic uv bootstrap diagnostic" not in completed.stderr

    (fake_bin / "uv.cmd").write_text(
        "@echo off\n>&2 echo owner-private-bootstrap-path\nexit /b 7\n",
        encoding="utf-8",
    )
    failed = subprocess.run(
        completed.args,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )
    assert failed.returncode == 2
    assert json.loads(failed.stdout)["failure_stage"] == "bootstrap"
    assert "owner-private-bootstrap-path" not in failed.stdout
    assert "owner-private-bootstrap-path" not in failed.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows bootstrap contract")
def test_forbidden_development_checkout_is_rejected_before_uv(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    checkout, control, runtime_config, head = _synthetic_bootstrap_checkout(
        tmp_path, detached=False
    )
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    invoked = tmp_path / "uv-invoked.txt"
    (fake_bin / "uv.cmd").write_text(
        '@echo off\n> "%HERMES_TEST_UV_INVOKED%" echo invoked\n'
        'echo {"status":"unexpected"}\nexit /b 0\n',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]
    environment["HERMES_TEST_UV_INVOKED"] = str(invoked)

    completed = subprocess.run(
        _bootstrap_command(powershell, checkout, control, runtime_config, head, tmp_path),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["failure_stage"] == "bootstrap"
    assert not invoked.exists()
    assert not (checkout / "backend" / ".venv").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows bootstrap contract")
def test_forbidden_stable_checkout_is_rejected_before_uv(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    checkout, control, runtime_config, head = _synthetic_bootstrap_checkout(tmp_path)
    document = json.loads(runtime_config.read_text(encoding="utf-8"))
    stable_paths = {
        "checkout": str(checkout),
        "data_dir": str(checkout / "stable-data"),
        "database": str(checkout / "stable-data" / "finance.db"),
    }
    document["canonical_production"].update(stable_paths)
    document["profiles"][0].update(stable_paths)
    runtime_config.write_text(json.dumps(document), encoding="utf-8")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    invoked = tmp_path / "uv-invoked.txt"
    (fake_bin / "uv.cmd").write_text(
        '@echo off\n> "%HERMES_TEST_UV_INVOKED%" echo invoked\n'
        'echo {"status":"unexpected"}\nexit /b 0\n',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]
    environment["HERMES_TEST_UV_INVOKED"] = str(invoked)

    completed = subprocess.run(
        _bootstrap_command(powershell, checkout, control, runtime_config, head, tmp_path),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["failure_stage"] == "bootstrap"
    assert not invoked.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows bootstrap ownership contract")
def test_direct_owned_bootstrap_with_forged_token_never_invokes_uv(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    checkout, control, runtime_config, head = _synthetic_bootstrap_checkout(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    invoked = tmp_path / "uv-invoked.txt"
    (fake_bin / "uv.cmd").write_text(
        '@echo off\n> "%HERMES_TEST_UV_INVOKED%" echo invoked\n'
        'echo {"status":"unexpected"}\nexit /b 0\n',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]
    environment["HERMES_TEST_UV_INVOKED"] = str(invoked)
    environment["HERMES_RECOVERY_BOOTSTRAP_OWNERSHIP_TOKEN"] = "a" * 64
    command = _bootstrap_command(powershell, checkout, control, runtime_config, head, tmp_path)
    command.append("-OwnedBootstrap")

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["failure_stage"] == "bootstrap"
    assert not invoked.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows bootstrap contract")
def test_bootstrap_rejects_hardlinked_output_before_uv(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    checkout, control, runtime_config, head = _synthetic_bootstrap_checkout(tmp_path)
    boundary = checkout / "backend" / ".venv"
    boundary.mkdir()
    external = tmp_path / "external-generated-output"
    external.write_text("preserve", encoding="utf-8")
    try:
        os.link(external, boundary / "generated.py")
    except OSError:
        pytest.skip("hard-link creation is unavailable")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    invoked = tmp_path / "uv-invoked.txt"
    (fake_bin / "uv.cmd").write_text(
        '@echo off\n> "%HERMES_TEST_UV_INVOKED%" echo invoked\n'
        'echo {"status":"unexpected"}\nexit /b 0\n',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]
    environment["HERMES_TEST_UV_INVOKED"] = str(invoked)

    completed = subprocess.run(
        _bootstrap_command(powershell, checkout, control, runtime_config, head, tmp_path),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["failure_stage"] == "bootstrap"
    assert not invoked.exists()
    assert external.read_text(encoding="utf-8") == "preserve"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows bootstrap contract")
def test_bootstrap_guard_blocks_junction_inserted_after_validation(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    checkout, control, runtime_config, head = _synthetic_bootstrap_checkout(tmp_path)
    external = tmp_path / "external-prepare-output"
    external.mkdir()
    marker = external / "unchanged.txt"
    marker.write_text("preserve", encoding="utf-8")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    moved = tmp_path / "moved-venv"
    (fake_bin / "uv.cmd").write_text(
        "@echo off\n"
        'move "%UV_PROJECT_ENVIRONMENT%" "%HERMES_TEST_MOVED_VENV%" >nul 2>&1\n'
        "if errorlevel 1 goto safe\n"
        'mklink /J "%UV_PROJECT_ENVIRONMENT%" "%HERMES_TEST_EXTERNAL%" >nul 2>&1\n'
        '> "%UV_PROJECT_ENVIRONMENT%\\unexpected.txt" echo redirected\n'
        ":safe\n"
        'echo {"status":"synthetic"}\n'
        "exit /b 0\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]
    environment["HERMES_TEST_MOVED_VENV"] = str(moved)
    environment["HERMES_TEST_EXTERNAL"] = str(external)

    completed = subprocess.run(
        _bootstrap_command(powershell, checkout, control, runtime_config, head, tmp_path),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert not (external / "unexpected.txt").exists()
    assert (checkout / "backend" / ".venv").is_dir()
    assert not moved.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows bootstrap ownership contract")
def test_outer_bootstrap_timeout_cleans_owned_tree_but_not_unrelated_listener(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    checkout, control, runtime_config, head = _synthetic_bootstrap_checkout(tmp_path)
    fake_bin, child_script, owned_marker = _write_hanging_fake_uv(tmp_path)
    unrelated_marker = tmp_path / "unrelated-listener.txt"
    unrelated = subprocess.Popen(
        [sys.executable, "-c", _BOOTSTRAP_LISTENER_CHILD, str(unrelated_marker)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    unrelated_id, unrelated_port = _read_listener_marker(unrelated_marker)
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]
    environment["HERMES_TEST_PYTHON"] = sys.executable
    environment["HERMES_TEST_CHILD_SCRIPT"] = str(child_script)
    environment["HERMES_TEST_CHILD_MARKER"] = str(owned_marker)
    try:
        completed = subprocess.run(
            _bootstrap_command(
                powershell,
                checkout,
                control,
                runtime_config,
                head,
                tmp_path,
                "-BootstrapTimeoutSeconds",
                "12",
            ),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=45,
        )

        assert completed.returncode == 2
        assert json.loads(completed.stdout)["failure_stage"] == "bootstrap-timeout"
        owned_id, owned_port = _read_listener_marker(owned_marker)
        _wait_process_gone(owned_id)
        _assert_listener_unavailable(owned_port)
        assert unrelated.poll() is None
        assert _process_is_alive(unrelated_id)
        with socket.socket() as probe:
            probe.settimeout(0.5)
            assert probe.connect_ex(("127.0.0.1", unrelated_port)) == 0
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=10)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows bootstrap ownership contract")
def test_outer_bootstrap_wrapper_death_closes_owned_job(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    checkout, control, runtime_config, head = _synthetic_bootstrap_checkout(tmp_path)
    fake_bin, child_script, owned_marker = _write_hanging_fake_uv(tmp_path)
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]
    environment["HERMES_TEST_PYTHON"] = sys.executable
    environment["HERMES_TEST_CHILD_SCRIPT"] = str(child_script)
    environment["HERMES_TEST_CHILD_MARKER"] = str(owned_marker)
    wrapper = subprocess.Popen(
        _bootstrap_command(powershell, checkout, control, runtime_config, head, tmp_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        owned_id, owned_port = _read_listener_marker(owned_marker)
        wrapper.kill()
        wrapper.communicate(timeout=15)
        _wait_process_gone(owned_id)
        _assert_listener_unavailable(owned_port)
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.communicate(timeout=10)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows bootstrap ownership contract")
def test_outer_bootstrap_cleanup_failure_is_explicit(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    checkout, control, runtime_config, head = _synthetic_bootstrap_checkout(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    (fake_bin / "uv.cmd").write_text(
        '@echo off\necho {"status":"synthetic"}\nexit /b 0\n', encoding="utf-8"
    )
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment["PATH"]

    completed = subprocess.run(
        _bootstrap_command(
            powershell,
            checkout,
            control,
            runtime_config,
            head,
            tmp_path,
            "-TestForceBootstrapCleanupFailure",
        ),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=30,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["failure_stage"] == "bootstrap-cleanup"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction contract")
@pytest.mark.parametrize(
    "relative_boundary",
    [Path("backend/.venv"), Path("frontend/node_modules"), Path("frontend/dist")],
)
def test_bootstrap_rejects_mutable_output_junction_without_touching_external_tree(
    tmp_path: Path,
    relative_boundary: Path,
) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    checkout, control, runtime_config, head = _synthetic_bootstrap_checkout(tmp_path)
    external = tmp_path / (relative_boundary.name + "-external")
    external.mkdir()
    marker = external / "unchanged.txt"
    marker.write_text("preserve", encoding="utf-8")
    linked = checkout / relative_boundary
    if not _make_directory_link(linked, external):
        pytest.skip("directory junction creation is unavailable")

    completed = subprocess.run(
        _bootstrap_command(
            powershell,
            checkout,
            control,
            runtime_config,
            head,
            tmp_path,
            "-BootstrapOnly",
        ),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout.strip())
    assert payload["status"] == "action_required"
    assert payload["failure_stage"] == "bootstrap"
    assert marker.read_text(encoding="utf-8") == "preserve"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX venv link contract")
def test_prepare_boundary_accepts_only_safe_posix_venv_links(tmp_path: Path) -> None:
    boundary = tmp_path / ".venv"
    library = boundary / "lib"
    binaries = boundary / "bin"
    library.mkdir(parents=True)
    binaries.mkdir()
    (library / "module.py").write_text("synthetic\n", encoding="utf-8")
    (boundary / "lib64").symlink_to(library, target_is_directory=True)
    interpreter = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    (binaries / "python3").symlink_to(interpreter)

    recovery_rehearsal._assert_prepare_output_boundary(boundary, directory=True)

    external = tmp_path / "external-package-tree"
    external.mkdir()
    (external / "unchanged.txt").write_text("preserve", encoding="utf-8")
    (library / "external-alias").symlink_to(external, target_is_directory=True)

    with pytest.raises(RecoveryRehearsalError, match="linked directory"):
        recovery_rehearsal._assert_prepare_output_boundary(boundary, directory=True)
    assert (external / "unchanged.txt").read_text(encoding="utf-8") == "preserve"


def test_prepare_boundary_rejects_hardlinked_generated_output(tmp_path: Path) -> None:
    boundary = tmp_path / "node_modules"
    boundary.mkdir()
    external = tmp_path / "external-generated-file"
    external.write_text("preserve", encoding="utf-8")
    linked = boundary / "generated.js"
    try:
        os.link(external, linked)
    except OSError:
        pytest.skip("hard-link creation is unavailable")

    with pytest.raises(RecoveryRehearsalError, match="linked file"):
        recovery_rehearsal._assert_prepare_output_boundary(boundary, directory=True)

    assert external.read_text(encoding="utf-8") == "preserve"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows containment contract")
def test_prepare_containment_blocks_late_output_junction_redirection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "recovery-checkout"
    (checkout / "backend").mkdir(parents=True)
    (checkout / "frontend").mkdir()
    proof = CheckoutProof(
        checkout=checkout,
        selected_sha="a" * 40,
        repository_key="synthetic",
        git_directory=checkout / ".git",
        common_directory=checkout / ".git",
    )
    external = tmp_path / "external-prepare-tree"
    external.mkdir()
    marker = external / "unchanged.txt"
    marker.write_text("preserve", encoding="utf-8")
    moved = checkout / "backend" / ".venv-moved"

    def attempt_redirect(*_args: object, **_kwargs: object) -> None:
        boundary = checkout / "backend" / ".venv"
        boundary.rename(moved)
        if _make_directory_link(boundary, external):
            (boundary / "unexpected.txt").write_text("redirected", encoding="utf-8")

    monkeypatch.setattr(recovery_rehearsal, "_run_runtime_script", attempt_redirect)
    monkeypatch.setattr(recovery_rehearsal, "_recheck_checkout", lambda *_a, **_k: None)

    with pytest.raises(RecoveryRehearsalError) as captured:
        recovery_rehearsal._prepare_and_validate(proof)

    assert captured.value.stage == "runtime-prepare-boundary"
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert not (external / "unexpected.txt").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows containment contract")
def test_nested_prepare_containment_guards_do_not_share_lock_stream(tmp_path: Path) -> None:
    boundary = tmp_path / "prepared-output"
    boundary.mkdir()

    outer = recovery_rehearsal._open_directory_guard(boundary)
    inner = recovery_rehearsal._open_directory_guard(boundary)
    try:
        assert outer.containment_path != inner.containment_path
        inner.close()
        outer.assert_path_identity()
        moved = tmp_path / "moved-output"
        with pytest.raises(PermissionError):
            boundary.rename(moved)
        assert boundary.is_dir()
        assert not moved.exists()
    finally:
        inner.close()
        outer.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows listener ownership contract")
def test_port_race_rejects_unrelated_listener_and_accepts_owned_descendant(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is unavailable")
    helper = str(REPOSITORY_ROOT / "scripts" / "recovery-runtime-safety.ps1").replace("'", "''")
    probe = tmp_path / "listener-ownership-probe.ps1"
    probe.write_text(
        f". '{helper}'\n"
        "$rows = @(\n"
        "  [pscustomobject]@{ ProcessId = 100; ParentProcessId = 1 },\n"
        "  [pscustomobject]@{ ProcessId = 101; ParentProcessId = 100 },\n"
        "  [pscustomobject]@{ ProcessId = 900; ParentProcessId = 1 }\n"
        ")\n"
        "$foreign = @([pscustomobject]@{ State = 'Listen'; LocalPort = 8000; "
        "LocalAddress = '127.0.0.1'; OwningProcess = 900 })\n"
        "$owned = @([pscustomobject]@{ State = 'Listen'; LocalPort = 8000; "
        "LocalAddress = '127.0.0.1'; OwningProcess = 101 })\n"
        "$result = [ordered]@{\n"
        "  foreign = Test-HermesLoopbackListenerOwnership -RootProcessId 100 "
        "-Listeners $foreign -ProcessRows $rows\n"
        "  owned = Test-HermesLoopbackListenerOwnership -RootProcessId 100 "
        "-Listeners $owned -ProcessRows $rows\n"
        "}\n"
        "$result | ConvertTo-Json -Compress\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(probe),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    result = json.loads(completed.stdout)
    assert result == {"foreign": False, "owned": True}
    start_source = (REPOSITORY_ROOT / "scripts" / "start-local.ps1").read_text(encoding="utf-8-sig")
    assert '"/PID", $Process.Id' in start_source
    assert '"/PID", $listeners' not in start_source
