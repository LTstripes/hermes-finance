"""Explicit owner-triggered protected recovery-point publisher CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hermes_finance.database import create_database
from hermes_finance.services.protected_backups import (
    PROTECTION_MODE,
    PROTECTION_STATE,
    ProtectedBackupError,
    publish_recovery_point,
)
from hermes_finance.settings import Settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish one verified recovery point to an already-mounted protected destination."
    )
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="Existing Owner-opened/mounted protected destination directory",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="Database to snapshot; defaults to the configured local database",
    )
    parser.add_argument(
        "--checkout",
        type=Path,
        default=Path.cwd(),
        help="Trusted producing checkout; defaults to the current checkout",
    )
    parser.add_argument(
        "--protection-state",
        choices=(PROTECTION_STATE,),
        required=True,
        help="Explicitly attest that the mounted destination is Owner-protected",
    )
    parser.add_argument(
        "--protection-mode",
        choices=(PROTECTION_MODE,),
        required=True,
        help="Explicitly attest the supported external protection boundary",
    )
    return parser


def _require_regular_database(path: Path) -> Path:
    resolved = path.expanduser().absolute()
    try:
        attributes = getattr(resolved.lstat(), "st_file_attributes", 0)
    except OSError as error:
        raise ProtectedBackupError("source database is unavailable") from error
    if not resolved.is_file() or resolved.is_symlink() or bool(attributes & 0x400):
        raise ProtectedBackupError("source database is unavailable")
    return resolved


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    database = None
    try:
        settings = Settings()
        database_path = _require_regular_database(
            args.database if args.database else settings.database_path
        )
        database = create_database(database_path)
        result = publish_recovery_point(
            database,
            args.destination,
            protection_state=args.protection_state,
            protection_mode=args.protection_mode,
            source_checkout=args.checkout,
        )
        print(json.dumps(result.as_dict(), ensure_ascii=True, sort_keys=True))
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "status": "action_required",
                    "created": False,
                    "verified": False,
                    "published": False,
                    "destination_alias": "protected-destination",
                    "protection_state": PROTECTION_STATE,
                    "protection_mode": PROTECTION_MODE,
                    "format_version": 1,
                    "created_at": None,
                    "read_back": "not_verified",
                    "size_bytes": None,
                    "action_required": "protected recovery-point publication was not completed",
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 2
    finally:
        if database is not None:
            database.engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
