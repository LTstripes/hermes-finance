"""Tests for reporting-month clone (D03).

Covers the full happy path (permanent state copied, actuals zeroed) and the
transactional failure path (rollback leaves no target month).
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import RubleAmount
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Base,
    CashBalance,
    Debt,
    DepositSnapshot,
    ExpenseEntry,
    IncomeEntry,
    InvestmentCashFlow,
    MonthlyComment,
    PositionSnapshot,
    PropertySnapshot,
    ReportingMonth,
    SavingAllocation,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.comments import create_monthly_comment
from hermes_finance.services.debts import create_debt
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.expenses import create_expense_entry, create_saving_allocation
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.month_clone import clone_reporting_month
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.properties import create_property_snapshot
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
    get_reporting_month_by_period,
    list_reporting_months,
)


def _session(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "clone.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _seed_source(session: Session) -> int:
    month = create_reporting_month(session, year=2031, month=1, snapshot_date=date(2031, 1, 31))
    account = create_account(session, name="Брокер", account_type="brokerage")
    instrument = create_instrument(session, name="ОФЗ", instrument_type="bond")

    create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        quantity="10",
        average_cost_per_unit=RubleAmount(100_000),
        market_price_per_unit=RubleAmount(125_000),
        price_date=date(2031, 1, 31),
        price_source="manual",
    )
    create_deposit_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        name="Вклад",
        deposit_type="deposit",
        balance=RubleAmount(1_000_000_00),
        annual_rate="12.00",
        actual_interest_received=RubleAmount(5_000_00),
    )
    create_cash_balance(
        session,
        reporting_month_id=month.id,
        name="Наличные",
        amount=RubleAmount(50_000_00),
    )
    create_expense_entry(
        session,
        reporting_month_id=month.id,
        category="ЖКХ",
        amount=RubleAmount(12_000_00),
        expense_type="mandatory",
        is_recurring=True,
    )
    create_expense_entry(
        session,
        reporting_month_id=month.id,
        category="Рестораны",
        amount=RubleAmount(8_000_00),
        expense_type="comfortable",
    )
    create_saving_allocation(
        session,
        reporting_month_id=month.id,
        destination="Подушка",
        amount=RubleAmount(30_000_00),
    )
    create_debt(
        session,
        reporting_month_id=month.id,
        debt_type="credit_card",
        name="Карта",
        current_balance=RubleAmount(45_000_00),
    )
    create_property_snapshot(
        session,
        reporting_month_id=month.id,
        name="Квартира",
        estimated_value=RubleAmount(15_000_000_00),
        mortgage_balance=RubleAmount(5_000_000_00),
        monthly_payment=RubleAmount(75_000_00),
    )
    create_income_entry(
        session,
        reporting_month_id=month.id,
        income_type="salary",
        name="Зарплата",
        gross_amount=RubleAmount(200_000_00),
        tax_amount=RubleAmount(26_000_00),
        net_amount=RubleAmount(174_000_00),
        received_at=date(2031, 1, 10),
        is_recurring=True,
    )
    create_income_entry(
        session,
        reporting_month_id=month.id,
        income_type="bonus",
        name="Премия",
        gross_amount=RubleAmount(50_000_00),
        tax_amount=RubleAmount(6_500_00),
        net_amount=RubleAmount(43_500_00),
        is_recurring=False,
    )
    create_income_entry(
        session,
        reporting_month_id=month.id,
        income_type="cashback",
        name="Кэшбэк",
        gross_amount=RubleAmount(500_00),
        tax_amount=RubleAmount(0),
        net_amount=RubleAmount(500_00),
    )
    create_investment_cash_flow(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        flow_type="dividend",
        event_date=date(2031, 1, 15),
        gross_amount=RubleAmount(1_000_00),
        tax_amount=RubleAmount(130_00),
        commission_amount=RubleAmount(0),
        net_amount=RubleAmount(870_00),
        source="manual",
    )
    create_monthly_comment(session, reporting_month_id=month.id, text="Заметка января")
    return month.id


def _count(session: Session, model: type, month_id: int) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(model).where(model.reporting_month_id == month_id)
        )
        or 0
    )


def test_clone_copies_permanent_state_and_zeros_actuals(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        source_id = _seed_source(session)
        close_reporting_month(session, source_id)  # cloning from closed is allowed

        target = clone_reporting_month(
            session,
            source_id,
            target_year=2031,
            target_month=2,
            snapshot_date=date(2031, 2, 28),
        )

        assert target.year == 2031 and target.month == 2
        assert target.status == "draft"
        assert target.period_start == date(2031, 2, 1)
        assert target.period_end == date(2031, 2, 28)
        assert len(list_reporting_months(session)) == 2

        # permanent state copied
        assert _count(session, PositionSnapshot, target.id) == 1
        assert _count(session, DepositSnapshot, target.id) == 1
        assert _count(session, CashBalance, target.id) == 1
        assert _count(session, ExpenseEntry, target.id) == 1  # mandatory only
        assert _count(session, SavingAllocation, target.id) == 1
        assert _count(session, Debt, target.id) == 1
        assert _count(session, PropertySnapshot, target.id) == 1
        assert _count(session, IncomeEntry, target.id) == 1  # recurring salary only

        # actual event streams NOT copied
        assert _count(session, InvestmentCashFlow, target.id) == 0
        assert _count(session, MonthlyComment, target.id) == 0

        deposit = session.scalar(
            select(DepositSnapshot).where(DepositSnapshot.reporting_month_id == target.id)
        )
        assert deposit is not None
        assert deposit.actual_interest_received_kopecks == 0
        assert deposit.balance_kopecks == 1_000_000_00
        # 1_000_000.00 RUB * 12% / 12 = 10_000.00 RUB
        assert deposit.expected_monthly_interest_kopecks == 10_000_00

        salary = session.scalar(
            select(IncomeEntry).where(IncomeEntry.reporting_month_id == target.id)
        )
        assert salary is not None
        assert salary.income_type == "salary"
        assert salary.is_recurring is True
        assert salary.received_at is None
        assert salary.net_amount_kopecks == 174_000_00

        expense = session.scalar(
            select(ExpenseEntry).where(ExpenseEntry.reporting_month_id == target.id)
        )
        assert expense is not None
        assert expense.expense_type == "mandatory"
        assert expense.category == "ЖКХ"

        # source month intact (closed + original actuals)
        assert _count(session, InvestmentCashFlow, source_id) == 1
        assert _count(session, MonthlyComment, source_id) == 1
        assert _count(session, IncomeEntry, source_id) == 3
        assert _count(session, ExpenseEntry, source_id) == 2
        source_deposit = session.scalar(
            select(DepositSnapshot).where(DepositSnapshot.reporting_month_id == source_id)
        )
        assert source_deposit is not None
        assert source_deposit.actual_interest_received_kopecks == 5_000_00
    finally:
        session.close()
        database.engine.dispose()


def test_clone_rejects_duplicate_target_and_invalid_snapshot(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        source_id = _seed_source(session)
        create_reporting_month(session, year=2031, month=2, snapshot_date=date(2031, 2, 15))
        with pytest.raises(ValueError, match="already exists"):
            clone_reporting_month(
                session,
                source_id,
                target_year=2031,
                target_month=2,
                snapshot_date=date(2031, 2, 28),
            )
        with pytest.raises(ValueError, match="snapshot_date"):
            clone_reporting_month(
                session,
                source_id,
                target_year=2031,
                target_month=3,
                snapshot_date=date(2031, 2, 1),
            )
    finally:
        session.close()
        database.engine.dispose()


def test_clone_rolls_back_on_mid_flight_failure(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        source_id = _seed_source(session)

        with patch(
            "hermes_finance.services.month_clone._copy_properties",
            side_effect=RuntimeError("simulated failure"),
        ):
            with pytest.raises(RuntimeError, match="simulated failure"):
                clone_reporting_month(
                    session,
                    source_id,
                    target_year=2031,
                    target_month=2,
                    snapshot_date=date(2031, 2, 28),
                )

        assert get_reporting_month_by_period(session, year=2031, month=2) is None
        assert len(list_reporting_months(session)) == 1
        assert session.scalar(select(func.count()).select_from(ReportingMonth)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(PositionSnapshot)
                .where(PositionSnapshot.reporting_month_id != source_id)
            )
            or 0
        ) == 0
    finally:
        session.close()
        database.engine.dispose()


# --- API ---


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "clone_api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def test_clone_endpoint_happy_path_and_conflict(client: TestClient) -> None:
    source = client.post(
        "/api/months",
        json={"year": 2031, "month": 1, "snapshot_date": "2031-01-31"},
    )
    assert source.status_code == 201
    source_id = source.json()["id"]

    account = client.post(
        "/api/accounts", json={"name": "Брокер", "account_type": "brokerage"}
    ).json()
    instrument = client.post(
        "/api/instruments", json={"name": "ОФЗ", "instrument_type": "bond"}
    ).json()
    client.post(
        "/api/positions",
        json={
            "reporting_month_id": source_id,
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "5",
            "average_cost_per_unit": _rub("1000.00"),
            "market_price_per_unit": _rub("1100.00"),
            "price_source": "manual",
            "price_date": "2031-01-31",
        },
    )
    client.post(
        "/api/deposits",
        json={
            "reporting_month_id": source_id,
            "account_id": account["id"],
            "name": "Вклад",
            "deposit_type": "deposit",
            "balance": _rub("100000.00"),
            "annual_rate": "12.00",
            "actual_interest_received": _rub("500.00"),
        },
    )
    client.post(
        "/api/comments",
        json={"reporting_month_id": source_id, "text": "не клонировать"},
    )
    client.post(f"/api/months/{source_id}/close")

    cloned = client.post(
        f"/api/months/{source_id}/clone",
        json={"year": 2031, "month": 2, "snapshot_date": "2031-02-28"},
    )
    assert cloned.status_code == 201, cloned.text
    body = cloned.json()
    assert body["year"] == 2031
    assert body["month"] == 2
    assert body["status"] == "draft"
    target_id = body["id"]

    positions = client.get(f"/api/positions?month_id={target_id}")
    assert positions.status_code == 200
    assert len(positions.json()) == 1

    deposits = client.get(f"/api/deposits?month_id={target_id}")
    assert deposits.status_code == 200
    assert len(deposits.json()) == 1
    assert deposits.json()[0]["actual_interest_received"] == _rub("0.00")
    assert deposits.json()[0]["expected_monthly_interest"] == _rub("1000.00")

    comments = client.get(f"/api/comments?month_id={target_id}")
    assert comments.status_code == 200
    assert comments.json() == []

    conflict = client.post(
        f"/api/months/{source_id}/clone",
        json={"year": 2031, "month": 2, "snapshot_date": "2031-02-28"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "conflict"

    missing = client.post(
        "/api/months/99999/clone",
        json={"year": 2031, "month": 3, "snapshot_date": "2031-03-15"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
