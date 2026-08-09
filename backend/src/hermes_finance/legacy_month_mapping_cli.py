from __future__ import annotations

import argparse
from pathlib import Path

from hermes_finance.services.legacy_month_mapping import load_legacy_month_mapping
from hermes_finance.settings import Settings


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(description="Validate the local legacy Excel month mapping")
    parser.add_argument(
        "--mapping",
        type=Path,
        default=settings.database_path.parent / "legacy_month_mapping.json",
        help="Path to legacy_month_mapping.json",
    )
    args = parser.parse_args(argv)

    try:
        result = load_legacy_month_mapping(args.mapping)
    except ValueError as error:
        print(f"legacy month mapping validation failed: {error}")
        return 2

    print(
        "legacy month mapping is valid: "
        f"total_mappings={result.total_mappings} "
        f"importable_mappings={result.importable_mappings} "
        f"skipped_mappings={result.skipped_mappings}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
