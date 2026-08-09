import json
from pathlib import Path

from openpyxl import Workbook

from hermes_finance.legacy_excel_cli import main
from hermes_finance.services.legacy_excel import extract_legacy_workbook


def _mapping(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_file": "synthetic.xlsx",
                "mappings": [
                    {
                        "sheet_name": "Январь_2026",
                        "reporting_month": {"year": 2026, "month": 1},
                        "snapshot_date": "2026-01-31",
                        "import_flag": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Январь_2026"
    sheet["B9"] = 100.005
    sheet["A17"] = "Synthetic deposit"
    sheet["B17"] = 1000
    sheet["C17"] = 10.5
    sheet["D17"] = "2026-01-31"
    sheet["A34"] = "Synthetic gold"
    sheet["B34"] = 2.5
    sheet["C34"] = 5000
    sheet["D34"] = 12500
    sheet["A46"] = "Synthetic bond"
    sheet["B46"] = "SYNTHISIN"
    sheet["C46"] = "Synthetic account"
    sheet["D46"] = 1
    sheet["A61"] = "Synthetic stock without isin"
    sheet["C61"] = "Synthetic account"
    sheet["D61"] = 2
    sheet["A62"] = "Synthetic duplicate isin"
    sheet["B62"] = "SYNTHISIN"
    sheet["C62"] = "Synthetic account"
    sheet["D62"] = 3
    sheet["H10"] = "Synthetic expense"
    sheet["I10"] = 12.34
    sheet["H20"] = "Synthetic savings"
    sheet["I20"] = 5
    sheet["H25"] = "Synthetic cashback"
    sheet["I25"] = 1.25
    sheet["H35"] = "Synthetic credit card"
    sheet["I35"] = 20
    sheet["H40"] = "Synthetic goal"
    sheet["I40"] = 100
    sheet["A94"] = "КОММЕНТАРИИ К МЕСЯЦУ"
    sheet["A95"] = 1
    sheet["B95"] = "Synthetic comment"
    sheet["A82"] = "СВОДКА И ИТОГИ"
    sheet["A83"] = "Synthetic total"
    sheet["B83"] = 123.45
    workbook.save(path)


def test_extracts_known_sections_without_binary_float_values(tmp_path: Path) -> None:
    workbook_path = tmp_path / "synthetic.xlsx"
    mapping_path = tmp_path / "mapping.json"
    _workbook(workbook_path)
    _mapping(mapping_path)

    extraction = extract_legacy_workbook(workbook_path, mapping_path)
    month = extraction.months[0]

    assert month.salary == {"name": "salary", "amount_kopecks": 10001}
    assert len(month.deposits) == 1
    assert month.deposits[0]["balance_kopecks"] == 100000
    assert month.deposits[0]["annual_rate_basis_points"] == 1050
    assert len(month.gold) == 1
    assert month.gold[0]["current_value_kopecks"] == 1_250_000
    assert len(month.mandatory_expenses) == 1
    assert len(month.saving_allocations) == 1
    assert len(month.cashback) == 1
    assert len(month.debts_payable) == 1
    assert len(month.goals) == 1
    assert month.comments == ({"position": 1, "text": "Synthetic comment"},)
    assert {warning.code for warning in extraction.warnings} == {"empty_isin", "duplicate_isin"}
    assert {warning.row for warning in extraction.warnings} == {61, 62}

    def contains_float(value: object) -> bool:
        if isinstance(value, float):
            return True
        if isinstance(value, dict):
            return any(contains_float(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return any(contains_float(item) for item in value)
        return False

    assert not contains_float(extraction.to_dict())


def test_cli_writes_private_output_and_prints_aggregate_only(
    tmp_path: Path, capsys: object
) -> None:
    workbook_path = tmp_path / "synthetic.xlsx"
    mapping_path = tmp_path / "mapping.json"
    output_path = tmp_path / "extraction.json"
    _workbook(workbook_path)
    _mapping(mapping_path)

    assert (
        main(
            [
                "--workbook",
                str(workbook_path),
                "--mapping",
                str(mapping_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert output == "legacy extraction is valid: months=1 rows=11 warnings=2\n"
    assert "Synthetic" not in output
    assert output_path.exists()
