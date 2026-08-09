import json
from pathlib import Path

import pytest

from hermes_finance.legacy_month_mapping_cli import main
from hermes_finance.services.legacy_month_mapping import load_legacy_month_mapping


def _payload() -> dict[str, object]:
    return {
        "$schema": "./legacy_month_mapping.schema.json",
        "schema_version": 1,
        "source_file": "synthetic_legacy_history.xlsx",
        "mappings": [
            {
                "sheet_name": "Archive_A",
                "reporting_month": {"year": 2024, "month": 1},
                "snapshot_date": "2024-01-31",
                "import_flag": True,
            },
            {
                "sheet_name": "Archive_B",
                "reporting_month": {"year": 2024, "month": 2},
                "snapshot_date": "2024-02-29",
                "import_flag": False,
            },
        ],
    }


def _write_mapping(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "legacy_month_mapping.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_legacy_mapping_validates_explicit_periods_and_import_flags(tmp_path: Path) -> None:
    result = load_legacy_month_mapping(_write_mapping(tmp_path, _payload()))

    assert result.source_file == "synthetic_legacy_history.xlsx"
    assert result.total_mappings == 2
    assert result.importable_mappings == 1
    assert result.skipped_mappings == 1


def test_legacy_mapping_rejects_duplicate_reporting_periods(tmp_path: Path) -> None:
    payload = _payload()
    mappings = payload["mappings"]
    assert isinstance(mappings, list)
    mappings[1] = {
        **mappings[1],
        "sheet_name": "Archive_Different_Name",
        "reporting_month": {"year": 2024, "month": 1},
    }

    with pytest.raises(ValueError, match="duplicate reporting periods"):
        load_legacy_month_mapping(_write_mapping(tmp_path, payload))


def test_legacy_mapping_rejects_duplicate_sheet_names(tmp_path: Path) -> None:
    payload = _payload()
    mappings = payload["mappings"]
    assert isinstance(mappings, list)
    mappings[1] = {**mappings[1], "sheet_name": "Archive_A"}

    with pytest.raises(ValueError, match="duplicate sheet names"):
        load_legacy_month_mapping(_write_mapping(tmp_path, payload))


def test_legacy_mapping_cli_hides_mapping_identifiers(tmp_path: Path, capsys) -> None:
    path = _write_mapping(tmp_path, _payload())

    exit_code = main(["--mapping", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == (
        "legacy month mapping is valid: total_mappings=2 importable_mappings=1 skipped_mappings=1"
    )
    assert "Archive_A" not in captured.out
    assert "synthetic_legacy_history.xlsx" not in captured.out
    assert captured.err == ""


def test_legacy_mapping_cli_hides_invalid_payload_and_path(tmp_path: Path, capsys) -> None:
    path = tmp_path / "legacy_month_mapping.json"
    path.write_text("{not-json", encoding="utf-8")

    exit_code = main(["--mapping", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out.strip() == (
        "legacy month mapping validation failed: legacy month mapping validation failed"
    )
    assert str(path) not in captured.out
    assert "not-json" not in captured.out
    assert captured.err == ""
