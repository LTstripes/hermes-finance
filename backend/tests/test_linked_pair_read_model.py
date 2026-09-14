"""Synthetic regression coverage for the #365-B linked-pair read model."""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from hermes_finance.database import Database, create_database
from hermes_finance.domain import AccountType, DebtType, DepositType, RubleAmount
from hermes_finance.main import create_app
from hermes_finance.persistence import Account, Base, Debt
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.debts import (
    create_debt,
    link_debt_to_account,
    unlink_debt_from_account,
)
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.linked_pairs import LinkedPairReadModelError
from hermes_finance.services.liquid_capital import (
    liquid_capital_for_month,
    liquid_capital_for_months,
)
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, Database]:
    database = create_database(tmp_path / "linked_pair.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_month(session: Session, *, month: int = 5) -> int:
    reporting_month = create_reporting_month(
        session,
        year=2035,
        month=month,
        snapshot_date=date(2035, month, 28),
    )
    return reporting_month.id


def test_linked_and_unlinked_pair_are_attribution_only(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        account = create_account(
            session,
            name="Synthetic linked cash",
            account_type=AccountType.CASH,
        )
        create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            name="Synthetic cash balance",
            amount="1000.00",
        )
        debt = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic card",
            current_balance="300.00",
        )
        create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.OTHER,
            name="Synthetic unrelated debt",
            current_balance="200.00",
        )

        unlinked = liquid_capital_for_month(session, month_id)
        assert unlinked.linked_pairs == ()
        assert unlinked.linked_pair_assets == RubleAmount(0)
        assert unlinked.linked_pair_debts == RubleAmount(0)
        assert unlinked.linked_pair_net_contribution == RubleAmount(0)

        link_debt_to_account(session, debt.id, account.id)
        linked = liquid_capital_for_month(session, month_id)

        assert linked.total_assets == RubleAmount(100_000)
        assert linked.total_debts_included == RubleAmount(50_000)
        assert linked.liquid_capital_net == RubleAmount(50_000)
        assert linked.liquid_capital_net == RubleAmount(
            linked.total_assets.kopecks - linked.total_debts_included.kopecks
        )
        assert linked.liquid_capital_net != RubleAmount(
            linked.total_assets.kopecks
            - linked.total_debts_included.kopecks
            - linked.linked_pair_debts.kopecks
        )

        assert len(linked.linked_pairs) == 1
        pair = linked.linked_pairs[0]
        assert pair.account_id == account.id
        assert pair.account_name == "Synthetic linked cash"
        assert pair.account_type == AccountType.CASH.value
        assert pair.account_balance == RubleAmount(100_000)
        assert pair.debt_id == debt.id
        assert pair.debt_balance == RubleAmount(30_000)
        assert pair.net_contribution == RubleAmount(70_000)
        assert linked.linked_pair_assets == RubleAmount(100_000)
        assert linked.linked_pair_debts == RubleAmount(30_000)
        assert linked.linked_pair_net_contribution == RubleAmount(70_000)

        unlink_debt_from_account(session, debt.id)
        unlinked_again = liquid_capital_for_month(session, month_id)
        assert unlinked_again.linked_pairs == ()
        assert unlinked_again.total_assets == unlinked.total_assets
        assert unlinked_again.total_debts_included == unlinked.total_debts_included
        assert unlinked_again.liquid_capital_net == unlinked.liquid_capital_net
    finally:
        session.close()
        database.engine.dispose()


def test_linked_account_without_attributed_balance_fact_fails_closed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        account = create_account(session, name="Synthetic missing-fact cash", account_type="cash")
        debt = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic missing-fact card",
            current_balance="300.00",
        )
        session.execute(update(Debt).where(Debt.id == debt.id).values(linked_account_id=account.id))
        session.commit()

        with pytest.raises(
            LinkedPairReadModelError,
            match="no included cash or deposit fact",
        ):
            liquid_capital_for_month(session, month_id)
    finally:
        session.close()
        database.engine.dispose()


def test_included_unattributed_cash_cannot_become_linked_pair_asset(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        account = create_account(session, name="Synthetic unattributed cash", account_type="cash")
        create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=None,
            name="Synthetic unassigned cash",
            amount="1000.00",
        )
        debt = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic unattributed card",
            current_balance="300.00",
        )
        session.execute(update(Debt).where(Debt.id == debt.id).values(linked_account_id=account.id))
        session.commit()

        with pytest.raises(
            LinkedPairReadModelError,
            match="no included cash or deposit fact",
        ):
            liquid_capital_for_month(session, month_id)
    finally:
        session.close()
        database.engine.dispose()


def test_explicit_zero_balance_fact_is_valid_linked_pair_asset(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        account = create_account(session, name="Synthetic zero-balance cash", account_type="cash")
        create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            name="Synthetic explicit zero cash",
            amount="0.00",
        )
        debt = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic zero-balance card",
            current_balance="300.00",
        )
        link_debt_to_account(session, debt.id, account.id)

        result = liquid_capital_for_month(session, month_id)

        assert len(result.linked_pairs) == 1
        assert result.linked_pairs[0].account_balance == RubleAmount(0)
        assert result.linked_pair_assets == RubleAmount(0)
        assert result.linked_pair_net_contribution == RubleAmount(-30_000)
        assert result.liquid_capital_net == RubleAmount(-30_000)
    finally:
        session.close()
        database.engine.dispose()


def test_corrupted_persisted_link_coverage_fails_closed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        account = create_account(session, name="Synthetic corrupted cash", account_type="cash")
        create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            name="Synthetic corrupted cash balance",
            amount="1000.00",
        )
        debt = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic corrupted card",
            current_balance="300.00",
        )
        link_debt_to_account(session, debt.id, account.id)

        session.execute(
            update(Account).where(Account.id == account.id).values(include_in_capital=False)
        )
        session.commit()

        with pytest.raises(
            LinkedPairReadModelError,
            match="stored linked account must be included in capital",
        ):
            liquid_capital_for_month(session, month_id)
    finally:
        session.close()
        database.engine.dispose()


def test_zero_balance_linked_debt_remains_visible(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        account = create_account(session, name="Synthetic zero-debt cash", account_type="cash")
        create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            name="Synthetic zero-debt balance",
            amount="400.00",
        )
        debt = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic zero card",
            current_balance="0.00",
        )
        link_debt_to_account(session, debt.id, account.id)

        result = liquid_capital_for_month(session, month_id)

        assert len(result.linked_pairs) == 1
        assert result.linked_pairs[0].debt_balance == RubleAmount(0)
        assert result.linked_pair_debts == RubleAmount(0)
        assert result.linked_pair_net_contribution == RubleAmount(40_000)
        assert result.liquid_capital_net == RubleAmount(40_000)
    finally:
        session.close()
        database.engine.dispose()


def test_batch_read_model_is_month_local_and_supports_deposit_accounts(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id = build_month(session, month=5)
        second_id = build_month(session, month=6)
        account = create_account(
            session,
            name="Synthetic linked deposit",
            account_type=AccountType.DEPOSIT,
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=first_id,
            account_id=account.id,
            name="Synthetic May deposit",
            deposit_type=DepositType.DEPOSIT,
            balance="2000.00",
            annual_rate="5.00",
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=second_id,
            account_id=account.id,
            name="Synthetic June deposit",
            deposit_type=DepositType.DEPOSIT,
            balance="2500.00",
            annual_rate="5.00",
        )
        debt = create_debt(
            session,
            reporting_month_id=first_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic May card",
            current_balance="500.00",
        )
        link_debt_to_account(session, debt.id, account.id)

        results = liquid_capital_for_months(session, (first_id, second_id, first_id))

        first = results[first_id]
        second = results[second_id]
        assert first.linked_pair_assets == RubleAmount(200_000)
        assert first.linked_pair_debts == RubleAmount(50_000)
        assert first.linked_pair_net_contribution == RubleAmount(150_000)
        assert first.linked_pairs[0].account_balance == RubleAmount(200_000)
        assert second.linked_pairs == ()
        assert second.linked_pair_assets == RubleAmount(0)
        assert second.liquid_capital_net == RubleAmount(250_000)
    finally:
        session.close()
        database.engine.dispose()


@pytest.fixture
def api_context(tmp_path: Path) -> Generator[tuple[TestClient, Database], None, None]:
    database = create_database(tmp_path / "linked_pair_api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            yield client, database
    finally:
        database.engine.dispose()


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def test_summary_dashboard_and_exports_share_linked_pair_facts(
    api_context: tuple[TestClient, Database],
) -> None:
    client, _database = api_context
    month_response = client.post(
        "/api/months",
        json={"year": 2036, "month": 5, "snapshot_date": "2036-05-28"},
    )
    assert month_response.status_code == 201, month_response.text
    month_id = month_response.json()["id"]

    account_response = client.post(
        "/api/accounts",
        json={"name": "Synthetic export cash", "account_type": "cash"},
    )
    assert account_response.status_code == 201, account_response.text
    account_id = account_response.json()["id"]
    cash_response = client.post(
        "/api/cash-balances",
        json={
            "reporting_month_id": month_id,
            "account_id": account_id,
            "name": "Synthetic export cash balance",
            "amount": _rub("1000.00"),
        },
    )
    assert cash_response.status_code == 201, cash_response.text
    debt_response = client.post(
        "/api/debts",
        json={
            "reporting_month_id": month_id,
            "debt_type": "credit_card",
            "name": "Synthetic export card",
            "current_balance": _rub("300.00"),
        },
    )
    assert debt_response.status_code == 201, debt_response.text
    debt_id = debt_response.json()["id"]
    link_response = client.put(
        f"/api/debts/{debt_id}/linked-account",
        json={"account_id": account_id},
    )
    assert link_response.status_code == 200, link_response.text

    summary_response = client.get(f"/api/months/{month_id}/summary")
    assert summary_response.status_code == 200, summary_response.text
    summary = summary_response.json()
    liquid = summary["liquid_capital"]
    assert liquid["liquid_capital_net"] == _rub("700.00")
    assert liquid["linked_pair_assets"] == _rub("1000.00")
    assert liquid["linked_pair_debts"] == _rub("300.00")
    assert liquid["linked_pair_net_contribution"] == _rub("700.00")
    assert liquid["linked_pairs"][0] == {
        "debt_id": debt_id,
        "debt_name": "Synthetic export card",
        "debt_type": "credit_card",
        "debt_balance": _rub("300.00"),
        "account_id": account_id,
        "account_name": "Synthetic export cash",
        "account_type": "cash",
        "account_balance": _rub("1000.00"),
        "net_contribution": _rub("700.00"),
    }

    dashboard_response = client.get(f"/api/months/{month_id}/dashboard")
    assert dashboard_response.status_code == 200, dashboard_response.text
    dashboard = dashboard_response.json()
    dashboard_liquid = dashboard["summary"]["liquid_capital"]
    assert dashboard_liquid == liquid
    assert dashboard["kpis"]["liquid_capital_net"] == _rub("700.00")

    markdown_response = client.post(f"/api/months/{month_id}/export/markdown")
    assert markdown_response.status_code == 200, markdown_response.text
    markdown = markdown_response.content.decode("utf-8")
    assert "### Связанные пары (актив — кредитная карта)" in markdown
    assert "Synthetic export cash (1)" in markdown
    assert "1 000 ₽" in markdown
    assert "300 ₽" in markdown
    assert "700 ₽" in markdown

    json_response = client.post(f"/api/months/{month_id}/export/json")
    assert json_response.status_code == 200, json_response.text
    payload = json.loads(json_response.content.decode("utf-8"))
    assert payload["raw"]["cash_balances"][0]["account_id"] == account_id
    assert payload["raw"]["debts"][0]["linked_account_id"] == account_id
    assert payload["derived"]["dashboard"]["summary"]["liquid_capital"] == liquid
    assert payload["derived"]["report"]["debt_rows"][0]["linked_account_id"] == account_id

    close_response = client.post(f"/api/months/{month_id}/close")
    assert close_response.status_code == 200, close_response.text
    analytics_response = client.get("/api/analytics/capital-composition")
    assert analytics_response.status_code == 200, analytics_response.text
    analytics_points = analytics_response.json()["points"]
    assert len(analytics_points) == 1
    analytics_point = analytics_points[0]
    assert analytics_point["liquid_assets_total"] == _rub("1000.00")
    assert analytics_point["included_debts"] == _rub("300.00")
    assert analytics_point["liquid_capital_net"] == _rub("700.00")
    assert analytics_point["linked_pair_assets"] == _rub("1000.00")
    assert analytics_point["linked_pair_debts"] == _rub("300.00")
    assert analytics_point["linked_pair_net_contribution"] == _rub("700.00")
