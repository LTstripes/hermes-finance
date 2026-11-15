"""Synthetic isolated server for goal-plan browser acceptance."""

from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.services.database_admission import database_admission


def main():
    with TemporaryDirectory(prefix="hermes-1129-browser-") as temporary:
        database = create_database(Path(temporary) / "finance.db")
        try:
            Base.metadata.create_all(database.engine)
            app = create_app(database)
            with TestClient(app) as client:
                month = client.post(
                    "/api/months",
                    json={"year": 2032, "month": 1, "snapshot_date": "2032-01-31"},
                ).json()
                result = client.post(
                    "/api/cash-balances",
                    json={
                        "reporting_month_id": month["id"],
                        "name": "Synthetic cash",
                        "amount": {"amount": "1000000", "currency": "RUB"},
                    },
                )
                assert result.status_code == 201, result.text
                result = client.post(
                    "/api/goals",
                    json={
                        "name": "Капитал для проекта",
                        "goal_type": "capital",
                        "calculation_mode": "liquid_capital_net",
                        "target_value": {"amount": "1500000", "currency": "RUB"},
                        "target_date": "2032-12-31",
                    },
                )
                assert result.status_code == 201, result.text
                assert client.get("/api/goals").status_code == 200
            with database_admission(database.database_path):
                uvicorn.run(app, host="127.0.0.1", port=18929)
        finally:
            database.engine.dispose()


if __name__ == "__main__":
    main()
