import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_migrations import run_alembic

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    ExternalFlowClassification,
    ExternalFlowDirection,
    ExternalFlowKind,
    ExternalFlowScope,
    ExternalTransferStatus,
)
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.external_flows import (
    classify_external_flow,
    create_external_flow,
    create_external_transfer_link,
)
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
    delete_reporting_month,
)


def _environment(tmp_path: Path) -> tuple[Session, object, int, int, int]:
    database = create_database(tmp_path / "r08-01a.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    source = create_account(session, name="Synthetic Source", account_type=AccountType.BROKERAGE)
    destination = create_account(
        session, name="Synthetic Destination", account_type=AccountType.BROKERAGE
    )
    return session, database, month.id, source.id, destination.id


def test_external_contribution_and_withdrawal_use_exact_explicit_boundary_semantics(
    tmp_path: Path,
) -> None:
    session, database, month_id, source_id, _ = _environment(tmp_path)
    try:
        contribution = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=source_id,
            event_date=date(2030, 5, 10),
            boundary_amount="1234.56",
            direction=ExternalFlowDirection.CONTRIBUTION,
            kind=ExternalFlowKind.EXTERNAL_CONTRIBUTION,
            source="manual",
        )
        withdrawal = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=source_id,
            event_date=date(2030, 5, 11),
            boundary_amount="12.34",
            direction=ExternalFlowDirection.WITHDRAWAL,
            kind=ExternalFlowKind.EXTERNAL_WITHDRAWAL,
            source="manual",
        )

        assert contribution.boundary_amount_kopecks == 123_456
        assert contribution.amount_kopecks == 123_456
        assert contribution.event_date == date(2030, 5, 10)
        assert contribution.direction == "contribution"
        assert contribution.kind == "external_contribution"
        assert withdrawal.boundary_amount_kopecks == 1_234
        assert (
            classify_external_flow(session, contribution.id, scope=ExternalFlowScope.PORTFOLIO)
            is ExternalFlowClassification.EXTERNAL_CONTRIBUTION
        )

        with pytest.raises(ValueError, match="must not be negative"):
            create_external_flow(
                session,
                reporting_month_id=month_id,
                account_id=source_id,
                event_date=date(2030, 5, 12),
                boundary_amount="-0.01",
                direction="contribution",
                kind="external_contribution",
            )
        with pytest.raises(ValueError, match="same movement"):
            create_external_flow(
                session,
                reporting_month_id=month_id,
                account_id=source_id,
                event_date=date(2030, 5, 12),
                boundary_amount="1.00",
                direction="withdrawal",
                kind="external_contribution",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_linked_transfer_is_internal_for_portfolio_and_crosses_account_boundary(
    tmp_path: Path,
) -> None:
    session, database, month_id, source_id, destination_id = _environment(tmp_path)
    try:
        link = create_external_transfer_link(session, transfer_key="owner-transfer-1")
        source_flow = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=source_id,
            event_date=date(2030, 5, 13),
            boundary_amount="100.00",
            direction="withdrawal",
            kind="external_withdrawal",
            transfer_link_id=link.id,
        )
        assert link.status == ExternalTransferStatus.UNRESOLVED.value
        assert (
            classify_external_flow(session, source_flow.id, scope="portfolio")
            is ExternalFlowClassification.UNRESOLVED
        )

        destination_flow = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=destination_id,
            event_date=date(2030, 5, 14),
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            transfer_link_id=link.id,
        )
        session.refresh(link)
        assert link.status == ExternalTransferStatus.RESOLVED.value
        assert (
            classify_external_flow(session, source_flow.id, scope="portfolio")
            is ExternalFlowClassification.INTERNAL_TRANSFER
        )
        assert (
            classify_external_flow(session, destination_flow.id, scope="portfolio")
            is ExternalFlowClassification.INTERNAL_TRANSFER
        )
        assert (
            classify_external_flow(session, source_flow.id, scope="account", account_id=source_id)
            is ExternalFlowClassification.EXTERNAL_WITHDRAWAL
        )
        assert (
            classify_external_flow(
                session, destination_flow.id, scope="account", account_id=destination_id
            )
            is ExternalFlowClassification.EXTERNAL_CONTRIBUTION
        )
    finally:
        session.close()
        database.engine.dispose()


def test_one_sided_transfer_stays_unresolved_until_explicit_second_leg(tmp_path: Path) -> None:
    session, database, month_id, source_id, _ = _environment(tmp_path)
    try:
        link = create_external_transfer_link(session, transfer_key="owner-transfer-incomplete")
        flow = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=source_id,
            event_date=date(2030, 5, 15),
            boundary_amount="50.00",
            direction="withdrawal",
            kind="external_withdrawal",
            transfer_link_id=link.id,
        )
        assert link.status == "unresolved"
        assert classify_external_flow(session, flow.id, scope="portfolio") == (
            ExternalFlowClassification.UNRESOLVED
        )
    finally:
        session.close()
        database.engine.dispose()


def test_draft_month_delete_reconciles_surviving_transfer_link(tmp_path: Path) -> None:
    session, database, month_id, source_id, destination_id = _environment(tmp_path)
    try:
        link = create_external_transfer_link(session, transfer_key="owner-transfer-delete")
        create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=source_id,
            event_date=date(2030, 5, 16),
            boundary_amount="50.00",
            direction="withdrawal",
            kind="external_withdrawal",
            transfer_link_id=link.id,
        )
        create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=destination_id,
            event_date=date(2030, 5, 16),
            boundary_amount="50.00",
            direction="contribution",
            kind="external_contribution",
            transfer_link_id=link.id,
        )
        assert link.status == "resolved"

        delete_reporting_month(session, month_id)
        session.refresh(link)
        assert link.status == "unresolved"
    finally:
        session.close()
        database.engine.dispose()


def test_external_flow_api_crud_and_closed_month_guard(tmp_path: Path) -> None:
    database = create_database(tmp_path / "r08-01a-api.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    month = create_reporting_month(session, year=2031, month=1, snapshot_date=date(2031, 1, 31))
    account = create_account(session, name="Synthetic API Account", account_type="brokerage")
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            created = client.post(
                "/api/external-flows",
                json={
                    "reporting_month_id": month.id,
                    "account_id": account.id,
                    "event_date": "2031-01-10",
                    "boundary_amount": {"amount": "200.01", "currency": "RUB"},
                    "direction": "contribution",
                    "kind": "external_contribution",
                    "source": "manual",
                },
            )
            assert created.status_code == 201, created.text
            body = created.json()
            assert body["boundary_amount"] == {"amount": "200.01", "currency": "RUB"}
            assert body["kind"] == "external_contribution"
            flow_id = body["id"]

            fractional_kopeck = client.post(
                "/api/external-flows",
                json={
                    "reporting_month_id": month.id,
                    "account_id": account.id,
                    "event_date": "2031-01-10",
                    "boundary_amount": {"amount": "200.001", "currency": "RUB"},
                    "direction": "contribution",
                    "kind": "external_contribution",
                },
            )
            assert fractional_kopeck.status_code == 422

            listed = client.get(f"/api/external-flows?month_id={month.id}")
            assert listed.status_code == 200
            assert [row["id"] for row in listed.json()] == [flow_id]

            patched = client.patch(
                f"/api/external-flows/{flow_id}",
                json={"boundary_amount": {"amount": "201.01", "currency": "RUB"}},
            )
            assert patched.status_code == 200, patched.text
            assert patched.json()["boundary_amount"]["amount"] == "201.01"

            session = database.session_factory()
            close_reporting_month(session, month.id)
            session.close()
            blocked = client.patch(
                f"/api/external-flows/{flow_id}",
                json={"notes": "must not mutate closed history"},
            )
            assert blocked.status_code == 409
            assert blocked.json()["error"]["code"] == "conflict"

            reopened = client.post(f"/api/months/{month.id}/reopen")
            assert reopened.status_code == 200, reopened.text
            deleted = client.delete(f"/api/external-flows/{flow_id}")
            assert deleted.status_code == 204
    finally:
        database.engine.dispose()


def test_transfer_link_api_crud_and_explicit_pairing(tmp_path: Path) -> None:
    database = create_database(tmp_path / "r08-01a-transfer-api.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    month = create_reporting_month(session, year=2031, month=2, snapshot_date=date(2031, 2, 28))
    source = create_account(session, name="Synthetic Transfer Source", account_type="brokerage")
    destination = create_account(
        session, name="Synthetic Transfer Destination", account_type="brokerage"
    )
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            source_flow = client.post(
                "/api/external-flows",
                json={
                    "reporting_month_id": month.id,
                    "account_id": source.id,
                    "event_date": "2031-02-10",
                    "amount": {"amount": "75.00", "currency": "RUB"},
                    "direction": "withdrawal",
                    "flow_type": "external_withdrawal",
                },
            )
            destination_flow = client.post(
                "/api/external-flows",
                json={
                    "reporting_month_id": month.id,
                    "account_id": destination.id,
                    "event_date": "2031-02-11",
                    "amount": {"amount": "75.00", "currency": "RUB"},
                    "direction": "contribution",
                    "flow_type": "external_contribution",
                },
            )
            assert source_flow.status_code == 201, source_flow.text
            assert destination_flow.status_code == 201, destination_flow.text
            source_id = source_flow.json()["id"]
            destination_id = destination_flow.json()["id"]

            created = client.post(
                "/api/transfer-links",
                json={
                    "transfer_key": "api-transfer-1",
                    "flow_ids": [source_id, destination_id],
                    "notes": "explicit owner linkage",
                },
            )
            assert created.status_code == 201, created.text
            link = created.json()
            assert link["status"] == "resolved"
            assert link["flow_ids"] == [source_id, destination_id]
            link_id = link["id"]

            source_after_link = client.get(f"/api/external-flows/{source_id}")
            assert source_after_link.status_code == 200
            assert source_after_link.json()["portfolio_scope_classification"] == "internal_transfer"

            renamed = client.patch(
                f"/api/transfer-links/{link_id}",
                json={"notes": "updated owner linkage"},
            )
            assert renamed.status_code == 200
            assert renamed.json()["notes"] == "updated owner linkage"

            detached = client.delete(f"/api/transfer-links/{link_id}/flows/{source_id}")
            assert detached.status_code == 200, detached.text
            assert detached.json()["status"] == "unresolved"
            assert detached.json()["flow_ids"] == [destination_id]

            detached_second = client.delete(f"/api/transfer-links/{link_id}/flows/{destination_id}")
            assert detached_second.status_code == 200
            assert detached_second.json()["flow_ids"] == []
            deleted = client.delete(f"/api/transfer-links/{link_id}")
            assert deleted.status_code == 204
    finally:
        database.engine.dispose()


def test_migration_keeps_ambiguous_legacy_rows_unclassified_and_downgrade_safe(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "r08-01a-migration.db"
    previous = run_alembic(database_path, "upgrade", "0029_statement_event_retract")
    assert previous.returncode == 0, previous.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2030,
                5,
                "2030-05-01",
                "2030-05-31",
                "2030-05-31",
                "draft",
                "manual",
                "2030-05-31 00:00:00",
                "2030-05-31 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO accounts (name, account_type, status, include_in_capital, include_in_returns) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Legacy Account", "brokerage", "active", 1, 1),
        )
        connection.execute(
            "INSERT INTO investment_cash_flows "
            "(reporting_month_id, account_id, instrument_id, flow_type, event_date, "
            "gross_amount_kopecks, tax_amount_kopecks, commission_amount_kopecks, "
            "net_amount_kopecks, currency, source, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 1, None, "deposit", "2030-05-10", 10000, 0, 0, 10000, "RUB", "legacy", None),
        )
        connection.execute(
            "INSERT INTO investment_cash_flows "
            "(reporting_month_id, account_id, instrument_id, flow_type, event_date, "
            "gross_amount_kopecks, tax_amount_kopecks, commission_amount_kopecks, "
            "net_amount_kopecks, currency, source, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                None,
                "withdrawal",
                "2030-05-11",
                20000,
                0,
                0,
                20000,
                "RUB",
                "legacy",
                None,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM external_flows").fetchone() == (0,)
        assert connection.execute(
            "SELECT flow_type, net_amount_kopecks, source FROM investment_cash_flows ORDER BY id"
        ).fetchall() == [("deposit", 10000, "legacy"), ("withdrawal", 20000, "legacy")]
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0029_statement_event_retract")
    assert downgraded.returncode == 0, downgraded.stderr
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "external_flows" not in tables
        assert "external_transfer_links" not in tables
        assert connection.execute(
            "SELECT flow_type, net_amount_kopecks FROM investment_cash_flows ORDER BY id"
        ).fetchall() == [("deposit", 10000), ("withdrawal", 20000)]
    finally:
        connection.close()


def test_migration_downgrade_refuses_to_delete_new_owner_data(tmp_path: Path) -> None:
    database_path = tmp_path / "r08-01a-migration-data.db"
    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO external_transfer_links "
            "(transfer_key, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("synthetic-transfer", "unresolved", "2030-05-01", "2030-05-01"),
        )
        connection.commit()
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0029_statement_event_retract")
    assert downgraded.returncode != 0
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM external_transfer_links").fetchone() == (1,)
    finally:
        connection.close()


def test_external_flow_migration_is_network_and_provider_free() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0030_external_flow_persistence.py"
    ).read_text(encoding="utf-8")
    lowered = migration.lower()
    assert "httpx" not in lowered
    assert "urllib" not in lowered
    assert "socket" not in lowered
