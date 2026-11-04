"""Explicit custody compatibility maintenance; never invoked by Start or GET.

Prepare is read-only. Apply requires an authorized offline maintenance window
and a verified backup; it appends metadata in the existing proof table only.
"""

import argparse
import json
import sqlite3
from pathlib import Path

from sqlalchemy import URL, create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.services.source_return_proofs import (
    ProofError,
    apply_legacy_recovery,
    prepare_legacy_recovery,
)
from hermes_finance.source_proof_file import file_incarnation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-account")
    mode.add_argument("--apply-plan", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    path = args.database.resolve(strict=True)
    if not path.is_file() or not file_incarnation(path):
        parser.error("database incarnation unavailable")
    if args.prepare_account is not None:
        if args.output is None or args.output.exists():
            parser.error("prepare requires a new private --output file")

        def connect():
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            connection.execute("PRAGMA query_only=ON")
            return connection

        engine = create_engine(
            URL.create("sqlite", database=str(path)), creator=connect, hide_parameters=True
        )

        @event.listens_for(engine, "connect")
        def stamp(_connection, record):
            record.info["source_proof_incarnation"] = file_incarnation(path)

        try:
            with Session(engine, autoflush=False) as session:
                prepared = prepare_legacy_recovery(
                    session,
                    source_account=args.prepare_account,
                    progress=lambda attempted, total: print(
                        json.dumps({"attempted": attempted, "total": total}), flush=True
                    ),
                )
            with args.output.open("x", encoding="utf-8") as output:
                json.dump(prepared, output, sort_keys=True, indent=2)
            print(
                json.dumps(
                    {
                        "prepared": True,
                        "database_write": False,
                        "table_deltas": prepared["table_deltas"],
                        "financial_effects": 0,
                    }
                )
            )
        finally:
            engine.dispose()
    else:
        if args.output is not None:
            parser.error("--output is only for prepare")
        prepared = json.loads(args.apply_plan.read_text(encoding="utf-8"))
        database = create_database(path)
        try:
            with database.session_factory() as session:
                result = apply_legacy_recovery(
                    session, plan=prepared["plan"], plan_digest=prepared["plan_digest"]
                )
            print(
                json.dumps(
                    {
                        "status": result["proof"]["status"],
                        "replay": result["replay"],
                        "financial_effects": 0,
                    }
                )
            )
        finally:
            database.engine.dispose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProofError as error:
        print(json.dumps({"status": "refused", "reason": str(error)}))
        raise SystemExit(1) from None
    except (OSError, ValueError, TypeError, KeyError, SQLAlchemyError):
        print(json.dumps({"status": "refused", "reason": "custody_recovery_failed"}))
        raise SystemExit(1) from None
