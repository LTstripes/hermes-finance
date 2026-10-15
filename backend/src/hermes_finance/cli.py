import os
import re
import sys
from pathlib import Path

import uvicorn

from hermes_finance.database import create_database
from hermes_finance.services.recovery_process import file_identity_token
from hermes_finance.settings import Settings

_TOKEN_RE = re.compile(r"[0-9a-f]{64}")


def upgrade_database(database_path: Path) -> None:
    # Keep migration-capable imports entirely outside the scratch entry point.
    from hermes_finance.services.migrations import upgrade_database as upgrade

    upgrade(database_path)


def _recovery_readiness(database_path: Path) -> dict[str, str] | None:
    values = {
        "token": os.environ.get("HERMES_FINANCE_RECOVERY_READINESS_TOKEN", ""),
        "database_identity": os.environ.get("HERMES_FINANCE_RECOVERY_DATABASE_IDENTITY", ""),
        "checkout_sha": os.environ.get("HERMES_FINANCE_RECOVERY_CHECKOUT_SHA", ""),
    }
    if not any(values.values()):
        return None
    if (
        not all(values.values())
        or _TOKEN_RE.fullmatch(values["token"]) is None
        or _TOKEN_RE.fullmatch(values["database_identity"]) is None
        or re.fullmatch(r"[0-9a-f]{40}", values["checkout_sha"]) is None
    ):
        raise RuntimeError("recovery readiness identity is invalid")
    if file_identity_token(database_path) != values["database_identity"]:
        raise RuntimeError("recovery database identity is invalid")
    return values


def main(arguments: list[str] | None = None) -> None:
    arguments = sys.argv[1:] if arguments is None else arguments
    if arguments[:1] == ["scratch-preflight"]:
        from hermes_finance.scratch_preflight import main as scratch_main

        scratch_main(arguments[1:])
        return
    if arguments:
        raise SystemExit("unsupported_start_mode")
    from hermes_finance.main import app as standard_app

    globals()["app"] = standard_app  # Preserve the standard CLI application identity.
    settings = Settings()
    upgrade_database(settings.database_path)
    database = create_database(settings.database_path)
    try:
        standard_app.state.database = database
        recovery_readiness = _recovery_readiness(settings.database_path)
        if recovery_readiness is not None:
            standard_app.state.recovery_readiness = recovery_readiness
        elif hasattr(standard_app.state, "recovery_readiness"):
            del standard_app.state.recovery_readiness
        uvicorn.run(
            "hermes_finance.main:app",
            host=settings.host,
            port=settings.port,
            reload=settings.reload,
        )
    finally:
        database.engine.dispose()
