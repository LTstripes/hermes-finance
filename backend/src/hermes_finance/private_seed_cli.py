from __future__ import annotations

import argparse
from pathlib import Path

from hermes_finance.database import create_database
from hermes_finance.services.private_seed import load_private_seed
from hermes_finance.settings import Settings


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(description="Load the local private seed into SQLite")
    parser.add_argument("--database", type=Path, default=settings.database_path)
    parser.add_argument(
        "--seed",
        type=Path,
        default=None,
        help="Path to private_seed.json (defaults to data/private_seed.json)",
    )
    args = parser.parse_args(argv)

    database = create_database(args.database)
    try:
        result = load_private_seed(database, args.seed)
    except ValueError as error:
        print(f"private seed load failed: {error}")
        return 2
    finally:
        database.engine.dispose()

    print(
        "private seed loaded: "
        f"accounts_created={result.accounts_created} "
        f"accounts_updated={result.accounts_updated} "
        f"settings_updated={result.settings_updated}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
