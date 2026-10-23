"""Owner crosswalk CLI, with an explicit existing DB selector and no server startup."""

import argparse
import csv
import json
import os
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from hermes_finance.database import create_database
from hermes_finance.services import security_reg_isin_mappings as mappings
from hermes_finance.services.migrations import _alembic_config, _database_heads
from hermes_finance.statement_import.mybroker import MyBrokerError


def main(arguments=None):
    parser = argparse.ArgumentParser(prog="hermes-finance-api reg-isin")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List locally saved mappings as JSON")
    set_command = commands.add_parser("set", help="Upsert one mapping; then run relink")
    set_command.add_argument("reg_number")
    set_command.add_argument("isin")
    set_command.add_argument("--note")
    remove_command = commands.add_parser("remove", help="Remove a mapping; then run relink")
    remove_command.add_argument("reg_number")
    import_command = commands.add_parser(
        "import", help="Atomically upsert UTF-8 CSV; then run relink"
    )
    import_command.add_argument("csv_path", type=Path)
    commands.add_parser(
        "relink", help="Refresh saved links, preserving decisions; skip CLOSED months"
    )
    args = parser.parse_args(arguments)

    selector = os.environ.get("HERMES_FINANCE_DATABASE_PATH", "").strip()
    if not selector:
        parser.error("HERMES_FINANCE_DATABASE_PATH is required")
    path = Path(selector).expanduser().resolve()
    if not path.is_file():
        parser.error("reg_isin_database_not_found: select an existing migrated database")
    try:
        _database_heads(path, _alembic_config(path))
    except (RuntimeError, SQLAlchemyError):
        parser.error("reg_isin_database_not_current: migrate the selected database explicitly")
    database = create_database(path)
    try:
        with database.session_factory() as session:
            match args.command:
                case "list":
                    result = mappings.list_mappings(session)
                case "set":
                    result = mappings.set_mapping(session, args.reg_number, args.isin, args.note)
                case "remove":
                    result = mappings.remove_mapping(session, args.reg_number)
                case "import":
                    result = mappings.import_csv(session, args.csv_path)
                case "relink":
                    result = mappings.relink(session)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, csv.Error, MyBrokerError) as error:
        parser.error(str(error))
    except SQLAlchemyError:
        parser.error("reg_isin_database_error: no changes committed")
    finally:
        database.engine.dispose()
