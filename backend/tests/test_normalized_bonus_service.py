"""Integration tests for the ORM normalized-bonus service (C08)."""

from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import IncomeType, RubleAmount
from hermes_finance.persistence import Base
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.normalized_bonus import normalized_bonus
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "normalized_bonus.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_month(session: Session, year: int, month: int) -> int:
    reporting_month = create_reporting_month(
        session, year=year, month=month, snapshot_date=date(year, month, 1)
    )
    return reporting_month.id


def add_bonus(session: Session, month_id: int, net: str) -> None:
    create_income_entry(
        session,
        reporting_month_id=month_id,
        income_type=IncomeType.BONUS,
        name="Synthetic Bonus",
        gross_amount=net,
        tax_amount="0.00",
        net_amount=net,
    )


# --- no closed months ---


def test_no_closed_months_returns_zeros(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        result = normalized_bonus(session)
        assert result.monthly_average == RubleAmount(0)
        assert result.sum_total == RubleAmount(0)
        assert result.count_months == 0
        assert result.is_complete_12m is False
        assert result.warnings == ("Нет закрытых месяцев для оценки нормализованной премии",)
    finally:
        session.close()
        database.engine.dispose()


# --- three closed months average ---


def test_three_closed_months_average(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        for i, net in enumerate(("3000.00", "6000.00", "9000.00"), start=1):
            month_id = build_month(session, 2031, i)
            add_bonus(session, month_id, net)
            close_reporting_month(session, month_id)

        result = normalized_bonus(session)
        # (3000 + 6000 + 9000) / 3 = 6000.00 RUB
        assert result.monthly_average == RubleAmount(600_000)
        assert result.sum_total == RubleAmount(1_800_000)
        assert result.count_months == 3
        assert result.is_complete_12m is False
        assert result.warnings == ("Премия оценена по 3 месяцев из 12",)
    finally:
        session.close()
        database.engine.dispose()


# --- draft months excluded ---


def test_draft_months_are_excluded(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        draft_id = build_month(session, 2031, 1)
        add_bonus(session, draft_id, "10000.00")
        # draft month intentionally left open
        closed_id = build_month(session, 2031, 2)
        add_bonus(session, closed_id, "2000.00")
        close_reporting_month(session, closed_id)

        result = normalized_bonus(session)
        assert result.count_months == 1
        assert result.sum_total == RubleAmount(200_000)
        assert result.monthly_average == RubleAmount(200_000)
    finally:
        session.close()
        database.engine.dispose()


# --- multiple bonus entries in one month sum ---


def test_multiple_bonus_entries_sum_per_month(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2031, 1)
        add_bonus(session, month_id, "500.00")
        add_bonus(session, month_id, "1500.00")
        close_reporting_month(session, month_id)

        result = normalized_bonus(session)
        assert result.count_months == 1
        assert result.sum_total == RubleAmount(200_000)
        assert result.months[0].amount == RubleAmount(200_000)
    finally:
        session.close()
        database.engine.dispose()


# --- 13 closed months use last twelve ---


def test_thirteen_closed_months_use_last_twelve(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        for i in range(1, 13):
            month_id = build_month(session, 2031, i)
            add_bonus(session, month_id, f"{1000 * i}.00")
            close_reporting_month(session, month_id)
        month_id = build_month(session, 2032, 1)
        add_bonus(session, month_id, "13000.00")
        close_reporting_month(session, month_id)

        result = normalized_bonus(session)
        # kept: (2031,2)..(2031,12) = 2000..12000 + (2032,1) = 13000 -> sum 90000.00
        assert result.is_complete_12m is True
        assert result.count_months == 12
        assert result.sum_total == RubleAmount(9_000_000)
        # 90000 / 12 = 7500.00 RUB
        assert result.monthly_average == RubleAmount(750_000)
        assert result.months[0].year == 2031
        assert result.months[0].month == 2
        assert result.warnings == ()
    finally:
        session.close()
        database.engine.dispose()


# --- closed month with no bonus counts as zero ---


def test_closed_month_without_bonus_counts_as_zero(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2031, 1)
        add_bonus(session, month_id, "500.00")
        close_reporting_month(session, month_id)
        empty_id = build_month(session, 2031, 2)
        close_reporting_month(session, empty_id)

        result = normalized_bonus(session)
        # (500 + 0) / 2 = 250.00 RUB
        assert result.count_months == 2
        assert result.sum_total == RubleAmount(50_000)
        assert result.monthly_average == RubleAmount(25_000)
    finally:
        session.close()
        database.engine.dispose()


# --- ordering by year/month ---


def test_result_months_ordered_by_year_month(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        for year, month in ((2032, 3), (2031, 1), (2032, 1), (2031, 12)):
            month_id = build_month(session, year, month)
            add_bonus(session, month_id, "1000.00")
            close_reporting_month(session, month_id)

        result = normalized_bonus(session)
        assert [(m.year, m.month) for m in result.months] == [
            (2031, 1),
            (2031, 12),
            (2032, 1),
            (2032, 3),
        ]
    finally:
        session.close()
        database.engine.dispose()
