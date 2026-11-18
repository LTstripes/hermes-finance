"""Isolated real API and synthetic starting uploads for the spending browser lane."""

import csv
import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from hermes_finance.alfa_csv import COLUMNS
from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.services.spending_diary import apply_upload, preview_upload


def seed(session, month, last_day, rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=COLUMNS)
    writer.writeheader()
    for day, title, amount in rows:
        writer.writerow(
            {
                "operationDate": f"{day:02d}.{month[5:]}.{month[:4]}",
                "accountName": "Тестовый счёт",
                "accountNumber": "SYNTHETIC-0001",
                "cardNumber": "SYNTHETIC-CARD",
                "merchant": title,
                "amount": amount,
                "currency": "RUR",
                "status": "Выполнен",
                "category": "Продукты",
                "type": "Списание",
            }
        )
    args = {
        "source": "alfa_csv",
        "month": month,
        "filename": f"Statement 01.{month[5:]}.{month[:4]} - {last_day}.{month[5:]}.{month[:4]}.csv",
        "content": output.getvalue().encode("utf-8"),
    }
    preview = preview_upload(session, **args)
    apply_upload(session, **args, preview_token=preview["preview_token"])


def main():
    port = int(os.environ["HERMES_STATEMENT_TEST_PORT"])
    if port == 8000:
        raise SystemExit("The spending fixture requires an isolated port")
    with TemporaryDirectory(prefix="hermes-spending-e2e-") as directory:
        database = create_database(Path(directory) / "finance.db")
        try:
            Base.metadata.create_all(database.engine)
            with database.session_factory() as session:
                seed(session, "2026-09", 30, [(1, "Сентябрьская покупка", "220")])
                seed(
                    session,
                    "2026-10",
                    31,
                    [(1, "Начало месяца", "150"), (15, "Старая покупка", "400")],
                )
                session.commit()
            static_dir = Path(__file__).resolve().parents[1] / "dist"
            uvicorn.run(create_app(database, static_dir=static_dir), host="127.0.0.1", port=port)
        finally:
            database.engine.dispose()


if __name__ == "__main__":
    main()
