from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from hermes_finance.database import create_database
from hermes_finance.services.legacy_excel import extract_legacy_workbook
from hermes_finance.services.legacy_migration import (
    LegacyMigrationAlreadyAppliedError,
    LegacyMigrationConflictError,
    apply_legacy_migration,
    load_legacy_decisions,
)
from hermes_finance.settings import Settings


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ValueError("legacy workbook could not be hashed") from error
    return digest.hexdigest()


def _period(value: str) -> tuple[int, int]:
    try:
        year_text, month_text = value.split("-", maxsplit=1)
        year, month = int(year_text), int(month_text)
        if len(year_text) != 4 or len(month_text) != 2 or month not in range(1, 13):
            raise ValueError
    except ValueError as error:
        raise argparse.ArgumentTypeError("period must use YYYY-MM") from error
    return year, month


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(
        description="Transactionally migrate the known Hermes Finance legacy workbook"
    )
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument(
        "--mapping",
        type=Path,
        default=settings.database_path.parent / "legacy_month_mapping.json",
    )
    parser.add_argument(
        "--review",
        type=Path,
        default=settings.database_path.parent / "legacy_unmatched_instruments.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=settings.database_path.parent / "legacy_migration_report.json",
    )
    parser.add_argument("--database", type=Path, default=settings.database_path)
    parser.add_argument(
        "--replace-period",
        type=_period,
        action="append",
        default=[],
        help="replace one existing draft/manual period after backup (repeatable)",
    )
    args = parser.parse_args(argv)

    database = create_database(args.database)
    try:
        extraction = extract_legacy_workbook(args.workbook, args.mapping)
        decisions = load_legacy_decisions(args.review)
        report = apply_legacy_migration(
            database,
            extraction,
            source_sha256=_sha256(args.workbook),
            decisions=decisions,
            report_path=args.report,
            replace_periods=set(args.replace_period),
        )
    except (
        LegacyMigrationAlreadyAppliedError,
        LegacyMigrationConflictError,
        OSError,
        ValueError,
    ) as error:
        print(f"legacy migration failed: {error}")
        return 2
    finally:
        database.engine.dispose()

    print(
        "legacy migration committed: "
        f"months={report.months_imported} "
        f"positions={report.counts['position_snapshots']} "
        f"nullable_isin_policy=create_without_isin "
        f"backup={report.backup_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
