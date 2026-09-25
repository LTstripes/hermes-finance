"""Explicit owner-triggered managed recovery-point publisher CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hermes_finance.database import create_database
from hermes_finance.services.protected_backups import (
    DESTINATION_ALIAS,
    PLAINTEXT_SYNCED_MODE,
    PLAINTEXT_SYNCED_STATE,
    PROTECTION_MODE,
    PROTECTION_STATE,
    RETENTION_NOT_RUN,
    ProtectedBackupError,
    protection_destination_alias,
    publish_recovery_point,
)
from hermes_finance.settings import Settings

_PROTECTED_PUBLICATION_ACTION = "protected recovery-point publication was not completed"
_PLAINTEXT_PUBLICATION_ACTION = "synced-filesystem recovery-point publication was not completed"
_UNSUPPORTED_PUBLICATION_ACTION = "recovery-point publication was not completed"


class _PrivacySafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise ProtectedBackupError("protected recovery-point arguments are invalid")


def _build_parser() -> argparse.ArgumentParser:
    parser = _PrivacySafeArgumentParser(
        description="Publish one verified recovery point to an Owner-accepted filesystem destination."
    )
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="Existing Owner-accepted destination directory",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="Database to snapshot; defaults to the configured local database",
    )
    parser.add_argument(
        "--checkout",
        type=Path,
        help="Optional guard that must resolve to the executing Hermes checkout",
    )
    parser.add_argument(
        "--protection-state",
        choices=(PROTECTION_STATE, PLAINTEXT_SYNCED_STATE),
        required=True,
        help="Explicit Owner-accepted destination state; must match the mode",
    )
    parser.add_argument(
        "--protection-mode",
        choices=(PROTECTION_MODE, PLAINTEXT_SYNCED_MODE),
        required=True,
        help="Explicit destination mode; must match the selected state",
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


def _failure_payload(
    *,
    protection_state: str | None = None,
    protection_mode: str | None = None,
    destination_alias: str | None = None,
    action_required: str = _UNSUPPORTED_PUBLICATION_ACTION,
) -> dict[str, object]:
    return {
        "status": "action_required",
        "created": False,
        "verified": False,
        "published": False,
        "destination_alias": destination_alias,
        "protection_state": protection_state,
        "protection_mode": protection_mode,
        "format_version": 1,
        "created_at": None,
        "read_back": "not_verified",
        "retention": RETENTION_NOT_RUN,
        "size_bytes": None,
        "action_required": action_required,
    }


def main(argv: list[str] | None = None) -> int:
    database = None
    failure = _failure_payload()
    try:
        args = _build_parser().parse_args(argv)
        try:
            requested_alias = protection_destination_alias(
                args.protection_state, args.protection_mode
            )
        except ProtectedBackupError:
            requested_alias = None
        if requested_alias is None:
            failure = _failure_payload(
                protection_state=args.protection_state,
                protection_mode=args.protection_mode,
                destination_alias=None,
                action_required=_UNSUPPORTED_PUBLICATION_ACTION,
            )
        else:
            action_required = _PROTECTED_PUBLICATION_ACTION
            if args.protection_mode == PLAINTEXT_SYNCED_MODE:
                action_required = _PLAINTEXT_PUBLICATION_ACTION
            failure = _failure_payload(
                protection_state=args.protection_state,
                protection_mode=args.protection_mode,
                destination_alias=requested_alias,
                action_required=action_required,
            )
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
        print(json.dumps(failure, ensure_ascii=True, sort_keys=True))
        return 2
    finally:
        if database is not None:
            database.engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
