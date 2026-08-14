"""R04-08 release verification: stable-schema upgrade and network boundary."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import httpx2
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from test_migrations import REVISION, revision_rows, run_alembic

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.settings import Settings

STABLE_REVISION = "0023_passive_income_history_eligibility"
STOCK_UID = "11111111-1111-1111-1111-111111111111"


class ForbiddenTransport(httpx2.BaseTransport):
    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        raise AssertionError(f"authenticated network must not be called: {request.url}")


def _connect(database_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(database_path)


def _seed_stable_schema(database_path: Path) -> None:
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2031,
                4,
                "2031-04-01",
                "2031-04-30",
                "2031-04-30",
                "closed",
                "manual",
                "2031-04-30 00:00:00",
                "2031-04-30 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2031,
                5,
                "2031-05-01",
                "2031-05-31",
                "2031-05-31",
                "draft",
                "manual",
                "2031-05-31 00:00:00",
                "2031-05-31 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO accounts "
            "(name, account_type, status, include_in_capital, include_in_returns) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Broker", "brokerage", "active", 1, 1),
        )
        connection.executemany(
            "INSERT INTO instruments "
            "(name, instrument_type, isin, ticker, moex_secid, currency, is_active, "
            "manual_price_allowed) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("Synthetic Manual", "stock", None, None, None, "RUB", 1, 1),
                ("Synthetic Moex", "stock", "RU0009029540", "SBER", "SBER", "RUB", 1, 1),
                ("Synthetic Alfa", "bond", None, None, None, "RUB", 1, 1),
            ],
        )
        connection.executemany(
            "INSERT INTO position_snapshots "
            "(reporting_month_id, account_id, instrument_id, quantity, "
            "average_cost_per_unit_kopecks, market_price_per_unit_kopecks, "
            "accrued_interest_kopecks, market_value_kopecks, cost_basis_kopecks, "
            "unrealized_result_kopecks, price_date, price_source, manual_adjustment, "
            "notes, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    1,
                    1,
                    1,
                    "1.000000",
                    10_000,
                    11_000,
                    None,
                    11_000,
                    10_000,
                    1_000,
                    "2031-04-15",
                    "manual",
                    0,
                    "synthetic manual snapshot",
                    "2031-04-15 00:00:00",
                ),
                (
                    1,
                    1,
                    2,
                    "2.000000",
                    20_000,
                    25_000,
                    None,
                    50_000,
                    40_000,
                    10_000,
                    "2031-04-16",
                    "moex",
                    0,
                    "synthetic moex snapshot",
                    "2031-04-16 00:00:00",
                ),
                (
                    2,
                    1,
                    3,
                    "3.000000",
                    30_000,
                    31_000,
                    500,
                    93_500,
                    90_000,
                    3_500,
                    "2031-05-10",
                    "alfa_pdf",
                    0,
                    "synthetic alfa snapshot",
                    "2031-05-10 00:00:00",
                ),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def _snapshot_fingerprint(database_path: Path) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(database_path)
    try:
        return connection.execute(
            "SELECT id, reporting_month_id, account_id, instrument_id, quantity, "
            "average_cost_per_unit_kopecks, market_price_per_unit_kopecks, "
            "accrued_interest_kopecks, market_value_kopecks, cost_basis_kopecks, "
            "unrealized_result_kopecks, price_date, price_source, notes "
            "FROM position_snapshots ORDER BY id"
        ).fetchall()
    finally:
        connection.close()


def test_stable_schema_copy_upgrades_through_provenance_without_data_loss(tmp_path: Path) -> None:
    stable_path = tmp_path / "stable-copy" / "finance.db"
    upgraded = run_alembic(stable_path, "upgrade", STABLE_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr
    assert revision_rows(stable_path) == [STABLE_REVISION]
    _seed_stable_schema(stable_path)
    before = _snapshot_fingerprint(stable_path)

    target_dir = tmp_path / "upgrade-target"
    target_dir.mkdir()
    target_path = target_dir / "finance.db"
    shutil.copy2(stable_path, target_path)

    migrated = run_alembic(target_path, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr
    assert revision_rows(target_path) == [REVISION]
    assert revision_rows(stable_path) == [STABLE_REVISION]
    assert _snapshot_fingerprint(stable_path) == before
    assert _snapshot_fingerprint(target_path) == before

    connection = _connect(target_path)
    try:
        sources = [
            row[0]
            for row in connection.execute("SELECT price_source FROM position_snapshots ORDER BY id")
        ]
        assert sources == ["manual", "moex", "alfa_pdf"]
        assert connection.execute("SELECT COUNT(*) FROM position_snapshots").fetchone()[0] == 3
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM position_snapshots WHERE price_source = 't_invest'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute(
            "SELECT year, month, status FROM reporting_months ORDER BY id"
        ).fetchall() == [(2031, 4, "closed"), (2031, 5, "draft")]
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "position_quote_provenance" in tables
        assert (
            connection.execute("SELECT COUNT(*) FROM position_quote_provenance").fetchone()[0] == 0
        )
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(position_quote_provenance)")
        }
        assert "ix_position_quote_provenance_snapshot_id" in indexes
        snapshot_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'position_snapshots'"
        ).fetchone()[0]
        assert "t_invest" in snapshot_sql
        provenance_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'position_quote_provenance'"
        ).fetchone()[0]
        assert "ck_position_quote_provenance_freshness" in provenance_sql
        assert "ck_position_quote_provenance_quote_kind" in provenance_sql
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
                "AND name = 'instrument_market_mappings'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM instrument_market_mappings").fetchone()[0] == 0
        )
    finally:
        connection.close()


def test_t_invest_downgrade_fails_closed_and_keeps_head(tmp_path: Path) -> None:
    database_path = tmp_path / "downgrade-guard.db"
    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2031,
                6,
                "2031-06-01",
                "2031-06-30",
                "2031-06-30",
                "draft",
                "manual",
                "2031-06-30 00:00:00",
                "2031-06-30 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO accounts "
            "(name, account_type, status, include_in_capital, include_in_returns) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Broker", "brokerage", "active", 1, 1),
        )
        connection.execute(
            "INSERT INTO instruments "
            "(name, instrument_type, currency, is_active, manual_price_allowed) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Applied", "stock", "RUB", 1, 1),
        )
        connection.execute(
            "INSERT INTO position_snapshots "
            "(reporting_month_id, account_id, instrument_id, quantity, "
            "average_cost_per_unit_kopecks, market_price_per_unit_kopecks, "
            "market_value_kopecks, cost_basis_kopecks, unrealized_result_kopecks, "
            "price_date, price_source, manual_adjustment, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                1,
                "1.000000",
                10_000,
                12_000,
                12_000,
                10_000,
                2_000,
                "2031-06-15",
                "t_invest",
                0,
                "2031-06-15 00:00:00",
            ),
        )
        connection.commit()
        before = connection.execute(
            "SELECT id, price_source, market_price_per_unit_kopecks FROM position_snapshots"
        ).fetchall()
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "-1")
    assert downgraded.returncode != 0
    assert "t_invest" in downgraded.stderr
    assert revision_rows(database_path) == [REVISION]

    connection = sqlite3.connect(database_path)
    try:
        assert (
            connection.execute(
                "SELECT id, price_source, market_price_per_unit_kopecks FROM position_snapshots"
            ).fetchall()
            == before
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "position_quote_provenance" in tables
    finally:
        connection.close()


def test_import_and_page_load_do_not_construct_market_clients(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    from hermes_finance.market_data import moex_iss, t_invest

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("startup must not construct a market-data client")

    monkeypatch.setattr(moex_iss, "MoexIssClient", boom)
    monkeypatch.setattr(t_invest, "TInvestClient", boom)
    database = create_database(tmp_path / "r04-08-startup.db")
    Base.metadata.create_all(database.engine)
    try:
        application = create_app(database)
        assert application.router.on_startup == []
        with TestClient(application) as client:
            health = client.get("/api/health")
            months = client.get("/api/months")
            root = client.get("/")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"
            assert "token" not in health.text.lower()
            assert months.status_code == 200
            assert months.json() == []
            assert root.status_code in {200, 404}
    finally:
        database.engine.dispose()


def test_missing_token_production_preview_makes_no_http_call(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", raising=False)
    database = create_database(tmp_path / "r04-08-preview.db")
    Base.metadata.create_all(database.engine)
    application = create_app(database)
    application.state.settings = Settings(_env_file=None)
    application.state.t_invest_http_client = httpx2.Client(transport=ForbiddenTransport())
    try:
        with TestClient(application) as client:
            month = client.post(
                "/api/months",
                json={"year": 2026, "month": 8, "snapshot_date": "2026-08-31"},
            )
            assert month.status_code == 201
            account = client.post(
                "/api/accounts",
                json={"name": "Synthetic Broker", "account_type": "brokerage"},
            )
            assert account.status_code == 201
            instrument = client.post(
                "/api/instruments",
                json={"name": "Synthetic T Stock", "instrument_type": "stock"},
            )
            assert instrument.status_code == 201
            mapped = client.put(
                f"/api/instruments/{instrument.json()['id']}/market-mapping",
                json={
                    "provider": "t_invest",
                    "provider_instrument_id": STOCK_UID,
                    "provider_venue_id": None,
                },
            )
            assert mapped.status_code == 200
            position = client.post(
                "/api/positions",
                json={
                    "reporting_month_id": month.json()["id"],
                    "account_id": account.json()["id"],
                    "instrument_id": instrument.json()["id"],
                    "quantity": "1",
                    "average_cost_per_unit": {"amount": "100.00", "currency": "RUB"},
                    "market_price_per_unit": {"amount": "100.00", "currency": "RUB"},
                    "price_date": "2026-08-01",
                    "price_source": "manual",
                },
            )
            assert position.status_code == 201
            preview = client.post(f"/api/months/{month.json()['id']}/quote-preview")
            assert preview.status_code == 200
            body = preview.json()
            assert body["batch_error_reason"] == "token_unavailable"
            assert "token is not configured" in (body["batch_error"] or "").lower()
            assert "t." not in (body["batch_error"] or "")
            row = body["rows"][0]
            assert row["status"] == "unavailable"
            assert row["failure_reason"] == "token_unavailable"
            assert row["apply_allowed"] is False
            assert "t." not in (row["message"] or "")
            listed = client.get(f"/api/positions?month_id={month.json()['id']}")
            still = listed.json()[0]
            assert still["market_price_per_unit"]["amount"] == "100.00"
            assert still["price_source"] == "manual"
    finally:
        database.engine.dispose()
