"""Integration tests for the salary progressive-tax (НДФЛ) service (C07)."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import IncomeType, RubleAmount
from hermes_finance.persistence import Base, IncomeEntry
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month
from hermes_finance.services.salary import actual_net_for_month, calculate_salary_tax
from hermes_finance.services.tax_brackets import (
    create_tax_bracket,
    delete_tax_bracket,
    get_or_create_default_tax_brackets,
    get_tax_bracket,
    list_tax_brackets,
    update_tax_bracket,
)


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "salary_tax.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_month(session: Session, year: int, month: int) -> int:
    reporting_month = create_reporting_month(
        session, year=year, month=month, snapshot_date=date(year, month, 15)
    )
    return reporting_month.id


def add_salary(session: Session, month_id: int, gross: str, net: str) -> None:
    create_income_entry(
        session,
        reporting_month_id=month_id,
        income_type=IncomeType.SALARY,
        name="Synthetic Salary",
        gross_amount=gross,
        tax_amount="0.00",
        net_amount=net,
    )


def add_legacy_salary(session: Session, month_id: int, *, gross_kopecks: int, net_kopecks: int) -> None:
    """Seed a pre-M03-03 duplicate directly so legacy read compatibility stays covered."""
    session.add(
        IncomeEntry(
            reporting_month_id=month_id,
            income_type=IncomeType.SALARY.value,
            name="Legacy Synthetic Salary",
            gross_amount_kopecks=gross_kopecks,
            tax_amount_kopecks=0,
            net_amount_kopecks=net_kopecks,
            received_at=None,
            is_recurring=True,
            include_in_cash_flow=True,
            include_in_passive_income=False,
            notes=None,
        )
    )
    session.commit()


# --- YTD accumulation across months of the same year ---


def test_ytd_accumulation_crosses_into_second_bracket(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_ids = [build_month(session, 2031, m) for m in range(1, 5)]
        for month_id in month_ids:
            add_salary(session, month_id, "500000.00", "435000.00")
            close_reporting_month(session, month_id)
        may_id = build_month(session, 2031, 5)
        add_salary(session, may_id, "500000.00", "435000.00")

        # ytd = 2_000_000.00 RUB (4 months), payment = 500_000.00 RUB
        result = calculate_salary_tax(session, may_id)
        assert len(result.parts) == 2
        # 400_000.00 RUB at 13% -> 52_000.00
        assert result.parts[0].rate_bps == 1300
        assert result.parts[0].taxable_kopecks == 40_000_000
        assert result.parts[0].tax_kopecks == 5_200_000
        # 100_000.00 RUB at 15% -> 15_000.00
        assert result.parts[1].rate_bps == 1500
        assert result.parts[1].taxable_kopecks == 10_000_000
        assert result.parts[1].tax_kopecks == 1_500_000
        assert result.tax_kopecks == 6_700_000  # 67_000.00 RUB
        assert result.calculated_net_kopecks == 43_300_000  # 433_000.00 RUB
        # actual employer-paid net is tracked separately from the calculation
        assert actual_net_for_month(session, may_id) == RubleAmount(43_500_000)
    finally:
        session.close()
        database.engine.dispose()


# --- month without salary ---


def test_month_without_salary_returns_zeros(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2031, 6)
        result = calculate_salary_tax(session, month_id)
        assert result.tax_kopecks == 0
        assert result.calculated_net_kopecks == 0
        assert result.parts == ()
        assert actual_net_for_month(session, month_id) == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()


# --- legacy duplicate salary entries still sum safely on read ---


def test_legacy_duplicate_salary_entries_sum_into_payment_gross(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2031, 1)
        add_legacy_salary(session, month_id, gross_kopecks=25_000_000, net_kopecks=21_750_000)
        add_legacy_salary(session, month_id, gross_kopecks=25_000_000, net_kopecks=21_750_000)

        # Legacy payment = 500_000.00 RUB in January -> 13% flat.
        result = calculate_salary_tax(session, month_id)
        assert len(result.parts) == 1
        assert result.parts[0].rate_bps == 1300
        assert result.parts[0].taxable_kopecks == 50_000_000
        assert result.tax_kopecks == 6_500_000  # 65_000.00 RUB
        assert result.calculated_net_kopecks == 43_500_000  # 435_000.00 RUB
        assert actual_net_for_month(session, month_id) == RubleAmount(43_500_000)
    finally:
        session.close()
        database.engine.dispose()


# --- seeding default brackets for an empty year ---


def test_seed_default_brackets_for_empty_year(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first = get_or_create_default_tax_brackets(session, 2031)
        assert len(first) == 5
        assert (
            first[0].threshold_from_kopecks,
            first[0].threshold_to_kopecks,
            first[0].rate_bps,
        ) == (
            0,
            240_000_000,
            1300,
        )
        assert (
            first[-1].threshold_from_kopecks,
            first[-1].threshold_to_kopecks,
            first[-1].rate_bps,
        ) == (5_000_000_000, None, 2200)

        # second call returns the same rows, no duplicates
        second = get_or_create_default_tax_brackets(session, 2031)
        assert [b.id for b in second] == [b.id for b in first]
        assert len(list_tax_brackets(session, 2031)) == 5
    finally:
        session.close()
        database.engine.dispose()


# --- seeding never overwrites user-edited brackets ---


def test_seed_keeps_custom_user_brackets(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        custom = create_tax_bracket(
            session, year=2032, threshold_from="0.00", threshold_to="100000.00", rate_bps=1300
        )
        brackets = get_or_create_default_tax_brackets(session, 2032)
        assert len(brackets) == 1
        assert brackets[0].id == custom.id
        assert brackets[0].rate_bps == 1300
        assert len(list_tax_brackets(session, 2032)) == 1
    finally:
        session.close()
        database.engine.dispose()


# --- overlap validation ---


def test_overlapping_brackets_rejected(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        create_tax_bracket(
            session, year=2031, threshold_from="0.00", threshold_to="100000.00", rate_bps=1300
        )
        with pytest.raises(ValueError):
            create_tax_bracket(
                session,
                year=2031,
                threshold_from="50000.00",
                threshold_to="200000.00",
                rate_bps=1500,
            )
    finally:
        session.close()
        database.engine.dispose()


def test_adjacent_brackets_accepted(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        create_tax_bracket(
            session, year=2031, threshold_from="0.00", threshold_to="100000.00", rate_bps=1300
        )
        # adjacent [100000.00, None) does not overlap [0.00, 100000.00)
        create_tax_bracket(
            session, year=2031, threshold_from="100000.00", threshold_to=None, rate_bps=1500
        )
        assert len(list_tax_brackets(session, 2031)) == 2
    finally:
        session.close()
        database.engine.dispose()


# --- update and delete ---


def test_update_tax_bracket_changes_fields(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        bracket = create_tax_bracket(
            session, year=2031, threshold_from="0.00", threshold_to="100000.00", rate_bps=1300
        )
        updated = update_tax_bracket(session, bracket.id, threshold_to="200000.00", rate_bps=1500)
        assert updated.threshold_to_kopecks == 20_000_000
        assert updated.rate_bps == 1500
        assert updated.threshold_from_kopecks == 0
        assert get_tax_bracket(session, bracket.id).threshold_to_kopecks == 20_000_000
    finally:
        session.close()
        database.engine.dispose()


def test_delete_tax_bracket_removes_row(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        bracket = create_tax_bracket(
            session, year=2031, threshold_from="0.00", threshold_to="100000.00", rate_bps=1300
        )
        delete_tax_bracket(session, bracket.id)
        assert list_tax_brackets(session, 2031) == []
    finally:
        session.close()
        database.engine.dispose()


# --- ordering ---


def test_list_tax_brackets_ordered_by_threshold_from(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        create_tax_bracket(
            session, year=2031, threshold_from="50000.00", threshold_to=None, rate_bps=1500
        )
        create_tax_bracket(
            session, year=2031, threshold_from="0.00", threshold_to="50000.00", rate_bps=1300
        )
        brackets = list_tax_brackets(session, 2031)
        assert [b.threshold_from_kopecks for b in brackets] == [0, 5_000_000]
    finally:
        session.close()
        database.engine.dispose()
