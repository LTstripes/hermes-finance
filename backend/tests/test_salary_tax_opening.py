from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import IncomeType
from hermes_finance.persistence import Base
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
    reopen_reporting_month,
)
from hermes_finance.services.salary import calculate_salary_tax
from hermes_finance.services.salary_tax_context import (
    SalaryTaxHistoryIncompleteError,
    delete_salary_tax_year_context,
    get_salary_tax_year_context,
    upsert_salary_tax_year_context,
)


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "salary_tax_opening.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_month(session: Session, year: int, month: int, *, closed: bool = False) -> int:
    reporting_month = create_reporting_month(
        session, year=year, month=month, snapshot_date=date(year, month, 15)
    )
    if closed:
        close_reporting_month(session, reporting_month.id)
    return reporting_month.id


def add_salary(session: Session, month_id: int, gross: str, net: str | None = None) -> None:
    create_income_entry(
        session,
        reporting_month_id=month_id,
        income_type=IncomeType.SALARY,
        name="Synthetic Salary",
        gross_amount=gross,
        tax_amount="0.00",
        net_amount=net or gross,
    )


def test_opening_context_progresses_from_may_without_earlier_rows(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        upsert_salary_tax_year_context(
            session,
            tax_year=2031,
            effective_from_month=5,
            opening_taxable_gross="2300000.00",
        )
        may_id = build_month(session, 2031, 5)
        add_salary(session, may_id, "300000.00")

        result = calculate_salary_tax(session, may_id)

        assert [(part.rate_bps, part.taxable_kopecks) for part in result.parts] == [
            (1300, 10_000_000),
            (1500, 20_000_000),
        ]
        assert result.tax_kopecks == 4_300_000
        assert result.calculated_net_kopecks == 25_700_000
    finally:
        session.close()
        database.engine.dispose()


def test_opening_is_not_doubled_by_real_earlier_months(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        upsert_salary_tax_year_context(
            session,
            tax_year=2031,
            effective_from_month=5,
            opening_taxable_gross="2300000.00",
        )
        for month in range(1, 5):
            month_id = build_month(session, 2031, month)
            add_salary(session, month_id, "100000.00")
            close_reporting_month(session, month_id)
        may_id = build_month(session, 2031, 5)
        add_salary(session, may_id, "300000.00")

        result = calculate_salary_tax(session, may_id)

        # Jan-Apr are historical detail only; opening remains the sole baseline.
        assert result.tax_kopecks == 4_300_000

    finally:
        session.close()
        database.engine.dispose()


def test_missing_opening_context_fails_closed_for_first_may_payment(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        may_id = build_month(session, 2031, 5)
        add_salary(session, may_id, "100000.00")

        with pytest.raises(SalaryTaxHistoryIncompleteError) as error:
            calculate_salary_tax(session, may_id)

        assert error.value.code == "salary_tax_history_incomplete"
    finally:
        session.close()
        database.engine.dispose()


def test_draft_prior_month_is_not_known_and_reopen_invalidates_history(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        upsert_salary_tax_year_context(
            session,
            tax_year=2031,
            effective_from_month=5,
            opening_taxable_gross="400000.00",
        )
        may_id = build_month(session, 2031, 5)
        june_id = build_month(session, 2031, 6)
        add_salary(session, june_id, "100000.00")

        with pytest.raises(SalaryTaxHistoryIncompleteError):
            calculate_salary_tax(session, june_id)

        add_salary(session, may_id, "100000.00")
        close_reporting_month(session, may_id)
        assert calculate_salary_tax(session, june_id).tax_kopecks == 1_300_000

        reopen_reporting_month(session, may_id)
        with pytest.raises(SalaryTaxHistoryIncompleteError):
            calculate_salary_tax(session, june_id)
    finally:
        session.close()
        database.engine.dispose()


def test_closed_salary_free_month_is_known_zero(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        upsert_salary_tax_year_context(
            session,
            tax_year=2031,
            effective_from_month=5,
            opening_taxable_gross="2300000.00",
        )
        may_id = build_month(session, 2031, 5, closed=True)
        june_id = build_month(session, 2031, 6)
        add_salary(session, june_id, "300000.00")

        result = calculate_salary_tax(session, june_id)

        assert result.tax_kopecks == 4_300_000
        assert may_id != june_id
    finally:
        session.close()
        database.engine.dispose()


def test_full_closed_history_works_without_opening_context(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        for month in range(1, 5):
            month_id = build_month(session, 2031, month)
            add_salary(session, month_id, "500000.00")
            close_reporting_month(session, month_id)
        may_id = build_month(session, 2031, 5)
        add_salary(session, may_id, "500000.00")

        result = calculate_salary_tax(session, may_id)

        assert result.tax_kopecks == 6_700_000
    finally:
        session.close()
        database.engine.dispose()


def test_zero_payment_does_not_require_complete_history(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        june_id = build_month(session, 2031, 6)

        result = calculate_salary_tax(session, june_id)

        assert result.tax_kopecks == 0
        assert result.parts == ()
    finally:
        session.close()
        database.engine.dispose()


def test_opening_context_validation_and_delete(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        with pytest.raises(ValueError, match="opening taxable gross must be zero"):
            upsert_salary_tax_year_context(
                session,
                tax_year=2031,
                effective_from_month=1,
                opening_taxable_gross="0.01",
            )
        with pytest.raises(ValueError, match="must not be negative"):
            upsert_salary_tax_year_context(
                session,
                tax_year=2031,
                effective_from_month=5,
                opening_taxable_gross="-1.00",
            )

        created = upsert_salary_tax_year_context(
            session,
            tax_year=2031,
            effective_from_month=5,
            opening_taxable_gross="400000.00",
        )
        assert created.opening_taxable_gross_kopecks == 40_000_000
        assert get_salary_tax_year_context(session, 2031).tax_year == created.tax_year

        delete_salary_tax_year_context(session, 2031)
        assert get_salary_tax_year_context(session, 2031) is None
    finally:
        session.close()
        database.engine.dispose()
