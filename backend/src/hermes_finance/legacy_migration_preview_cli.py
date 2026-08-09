from __future__ import annotations

import argparse
import json
from pathlib import Path

from hermes_finance.services.legacy_excel import extract_legacy_workbook
from hermes_finance.services.legacy_migration_preview import (
    build_migration_preview,
    render_migration_preview_markdown,
)
from hermes_finance.settings import Settings


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(
        description="Build a no-write preview for the known Hermes Finance legacy Excel format"
    )
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument(
        "--mapping", type=Path, default=settings.database_path.parent / "legacy_month_mapping.json"
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=settings.database_path.parent / "legacy_migration_preview.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=settings.database_path.parent / "legacy_migration_preview.md",
    )
    args = parser.parse_args(argv)
    try:
        extraction = extract_legacy_workbook(args.workbook, args.mapping)
        preview = build_migration_preview(extraction)
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(preview.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        args.markdown_output.write_text(
            render_migration_preview_markdown(preview), encoding="utf-8"
        )
    except (OSError, ValueError) as error:
        print(f"legacy migration preview failed: {error}")
        return 2
    unmatched = sum(len(month.unmatched_rows) for month in preview.months)
    different = sum(
        diff.status == "different" for month in preview.months for diff in month.control_diffs
    )
    print(
        f"legacy migration preview is valid: months={len(preview.months)} "
        f"unmatched={unmatched} different={different}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
