"""Public total-income JSON contract and latest-CLOSED identity guard."""

from pathlib import Path

from _month_close_helpers import close_fixture_month_http
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base


def money(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def test_total_income_contract_and_month_guard(tmp_path: Path) -> None:
    database = create_database(tmp_path / "api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            empty = client.get("/api/analytics/total-income")
            assert empty.status_code == 200
            assert empty.json()["latest_closed_report_id"] is None
            assert empty.json()["points"] == []
            assert empty.json()["windows"]["all"]["monthly_average"] is None
            ids = []
            for month in (1, 4, 5):
                response = client.post(
                    "/api/months",
                    json={
                        "year": 2031,
                        "month": month,
                        "snapshot_date": f"2031-{month:02d}-28",
                    },
                )
                assert response.status_code == 201, response.text
                month_id = response.json()["id"]
                ids.append(month_id)
                if month == 4:
                    for kind, amount in (
                        ("salary", "1200.00"),
                        ("bonus", "120.00"),
                        ("cashback", "99.00"),
                    ):
                        response = client.post(
                            "/api/incomes",
                            json={
                                "reporting_month_id": month_id,
                                "income_type": kind,
                                "name": f"Synthetic {kind}",
                                "gross_amount": money(amount),
                                "tax_amount": money("0.00"),
                                "net_amount": money(amount),
                            },
                        )
                        assert response.status_code == 201, response.text
                if month != 5:
                    response = close_fixture_month_http(client, month_id)
                    assert response.status_code == 200, response.text
            response = client.put(
                "/api/settings", json={"passive_income_history_start_month": "2031-04"}
            )
            assert response.status_code == 200, response.text
            response = client.get(f"/api/analytics/total-income?month_id={ids[1]}")
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["latest_closed_report_id"] == ids[1]
            assert body["configured_start_month"] == "2031-04"
            assert body["points"] == [
                {
                    "reporting_month_id": ids[0],
                    "year": 2031,
                    "month": 1,
                    "salary_net": money("1200.00"),
                    "salary_is_estimate": True,
                    "bonus_net": money("0.00"),
                    "passive_actual": None,
                    "other_net": money("0.00"),
                },
                {
                    "reporting_month_id": ids[1],
                    "year": 2031,
                    "month": 4,
                    "salary_net": money("1200.00"),
                    "salary_is_estimate": False,
                    "bonus_net": money("120.00"),
                    "passive_actual": money("0.00"),
                    "other_net": money("99.00"),
                },
            ]
            window = body["windows"]["calendar_year"]
            assert window == {
                "from": "2031-01",
                "to": "2031-04",
                "months_observed": 2,
                "months_used": ["2031-01", "2031-04"],
                "salary_months": 2,
                "passive_months": 1,
                "bonus_months": 2,
                "bonus_target_months": 12,
                "estimate_months": 1,
                "salary_sum": money("2400.00"),
                "passive_sum": money("0.00"),
                "bonus_sum": money("120.00"),
                "other_sum": money("99.00"),
                "salary_monthly_average": money("1200.00"),
                "passive_monthly_average": money("0.00"),
                "bonus_smoothed_monthly": money("10.00"),
                "monthly_average": money("1210.00"),
                "current_level": money("1210.00"),
                "current_passive_months": 1,
                "warnings": [
                    "Зарплата за 1 мес оценена по апрельской (04.2031)",
                    "Пассивка учитывается с 04.2031",
                    "Премия учтена за 2 мес из 12; сумма распределена на 12 месяцев",
                ],
            }
            assert body["windows"]["rolling_12"]["from"] == "2030-05"
            assert body["windows"]["all"]["from"] == "2031-01"
            assert client.get("/api/analytics/total-income").json() == body
            for invalid in (ids[0], ids[2], 99999):
                response = client.get(f"/api/analytics/total-income?month_id={invalid}")
                assert response.status_code == 404
                assert response.json()["error"]["code"] == "not_found"
            assert client.get("/api/analytics/total-income?month_id=0").status_code == 422
            # The estimate never changed the stored January zero/absence.
            incomes = client.get(f"/api/incomes?month_id={ids[0]}")
            assert incomes.status_code == 200, incomes.text
            assert incomes.json() == []
    finally:
        database.engine.dispose()
