"""Privacy-safe CLI for one isolated managed recovery-point rehearsal."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hermes_finance.services.protected_backups import (
    FORMAT_VERSION,
    PLAINTEXT_SYNCED_MODE,
    PLAINTEXT_SYNCED_STATE,
    PROTECTION_MODE,
    PROTECTION_STATE,
    ProtectedBackupError,
    protection_destination_alias,
)
from hermes_finance.services.recovery_rehearsal import (
    RECOVERY_ACTION_REQUIRED,
    RECOVERY_READINESS_FAILURE_REASONS,
    RecoveryRehearsalError,
    rehearse_recovery,
)


class _PrivacySafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise RecoveryRehearsalError("arguments", "recovery rehearsal arguments are invalid")


def _build_parser() -> argparse.ArgumentParser:
    parser = _PrivacySafeArgumentParser(
        description="Verify and rehearse one managed recovery point in a fresh isolated profile."
    )
    parser.add_argument("--recovery-point", type=Path, required=True)
    parser.add_argument("--recovery-sha", required=True)
    parser.add_argument("--recovery-checkout", type=Path, required=True)
    parser.add_argument("--control-checkout", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--target-profile", type=Path, required=True)
    parser.add_argument("--target-data", type=Path, required=True)
    parser.add_argument("--target-database", type=Path, required=True)
    parser.add_argument(
        "--protection-state",
        choices=(PROTECTION_STATE, PLAINTEXT_SYNCED_STATE),
        required=True,
    )
    parser.add_argument(
        "--protection-mode",
        choices=(PROTECTION_MODE, PLAINTEXT_SYNCED_MODE),
        required=True,
    )
    return parser


def _failure_payload(
    stage: str,
    *,
    failure_reason: str | None = None,
    protection_state: str | None = None,
    protection_mode: str | None = None,
    destination_alias: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "action_required",
        "failure_stage": stage,
        "source_verified": False,
        "source_unchanged": False,
        "restored": False,
        "prepared": False,
        "validated": False,
        "readiness": "not_verified",
        "destination_alias": destination_alias,
        "protection_state": protection_state,
        "protection_mode": protection_mode,
        "format_version": FORMAT_VERSION,
        "artifact_sha256": None,
        "artifact_identity_sha256": None,
        "snapshot_sha256": None,
        "producer_git_sha": None,
        "source_alembic_revisions": [],
        "selected_recovery_sha": None,
        "selected_checkout_heads": [],
        "schema_relationship": None,
        "resulting_alembic_revisions": [],
        "structural_counts": {},
        "action_required": RECOVERY_ACTION_REQUIRED,
    }
    if failure_reason in RECOVERY_READINESS_FAILURE_REASONS:
        payload["failure_reason"] = failure_reason
    return payload


def main(argv: list[str] | None = None) -> int:
    failure_identity: dict[str, str | None] = {}
    try:
        args = _build_parser().parse_args(argv)
        try:
            requested_alias = protection_destination_alias(
                args.protection_state, args.protection_mode
            )
        except ProtectedBackupError:
            requested_alias = None
        failure_identity = {
            "protection_state": args.protection_state,
            "protection_mode": args.protection_mode,
            "destination_alias": requested_alias,
        }
        result = rehearse_recovery(
            args.recovery_point,
            protection_state=args.protection_state,
            protection_mode=args.protection_mode,
            selected_recovery_sha=args.recovery_sha,
            recovery_checkout=args.recovery_checkout,
            control_checkout=args.control_checkout,
            runtime_config=args.runtime_config,
            target_profile=args.target_profile,
            target_data=args.target_data,
            target_database=args.target_database,
        )
        print(json.dumps(result.as_dict(), ensure_ascii=True, sort_keys=True))
        return 0
    except RecoveryRehearsalError as error:
        print(
            json.dumps(
                _failure_payload(
                    error.stage,
                    failure_reason=error.failure_reason,
                    **failure_identity,
                ),
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 2
    except Exception:
        print(
            json.dumps(
                _failure_payload("unexpected", **failure_identity),
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
