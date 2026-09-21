from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

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
        lambda _checkout, _database: events.append("start-readiness"),
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

    def run_stub(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setenv("PSModulePath", str(tmp_path / "PowerShell" / "Modules"))
    monkeypatch.setattr(recovery_rehearsal, "_powershell", lambda: str(powershell))
    monkeypatch.setattr(recovery_rehearsal.subprocess, "run", run_stub)

    recovery_rehearsal._run_runtime_script(
        _proof(),
        script_name="prepare-runtime.ps1",
        arguments=["-Prepare"],
        stage="runtime-prepare",
        timeout=1,
    )

    environment = captured["kwargs"]["env"]
    assert environment["PSModulePath"] == str(powershell.parent.resolve() / "Modules")
    assert environment["PYTHONPATH"] == ""
    assert environment["HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN"] == ""
