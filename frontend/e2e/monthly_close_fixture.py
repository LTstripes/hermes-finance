"""Synthetic, temporary real API runtime for the native Monthly Close journey."""

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.services.reporting_months import create_reporting_month


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    with TemporaryDirectory(prefix="hermes-close-571-synthetic-") as temporary:
        database = create_database(Path(temporary) / "finance.db")
        Base.metadata.create_all(database.engine)
        with database.session_factory() as session:
            create_reporting_month(
                session, year=2031, month=5, snapshot_date=date(2031, 5, 31)
            )
        app = create_app(database, static_dir=root / "frontend" / "dist")
        uvicorn.run(app, host="127.0.0.1", port=18757, access_log=False)
        database.engine.dispose()


if __name__ == "__main__":
    main()
