from __future__ import annotations

import argparse
import json
from pathlib import Path

from hermes_finance.services.legacy_excel import extract_legacy_workbook
from hermes_finance.settings import Settings


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(
        description="Extract the known Hermes Finance legacy Excel format"
    )
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument(
        "--mapping", type=Path, default=settings.database_path.parent / "legacy_month_mapping.json"
    )
    parser.add_argument(
        "--output", type=Path, default=settings.database_path.parent / "legacy_extraction.json"
    )
    args = parser.parse_args(argv)
    try:
        extraction = extract_legacy_workbook(args.workbook, args.mapping)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(extraction.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except (OSError, ValueError) as error:
        print(f"legacy extraction failed: {error}")
        return 2
    section_counts = sum(
        len(getattr(month, field))
        for month in extraction.months
        for field in (
            "deposits",
            "stocks",
            "bonds",
            "gold",
            "mandatory_expenses",
            "saving_allocations",
            "cashback",
            "debts_receivable",
            "debts_payable",
            "goals",
            "dividends",
            "comments",
        )
    )
    print(
        f"legacy extraction is valid: months={len(extraction.months)} rows={section_counts} warnings={len(extraction.warnings)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
