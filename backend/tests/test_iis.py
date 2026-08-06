from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import Database, create_database
from hermes_finance.domain import AccountType, RubleAmount, TaxBenefitStatus
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.iis import (
    create_iis_contribution,
    create_iis_profile,
    create_tax_benefit,
)


def session_for(tmp_path: Path) -> tuple[Session, Database]:
    database = create_database(tmp_path / "iis.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def account_id(session: Session) -> int:
    return create_account(
        session,
        name="Synthetic IIS account",
        account_type=AccountType.IIS,
    ).id


def test_iis_profile_stores_control_dates_and_links_account(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = account_id(session)
        profile = create_iis_profile(
            session,
            account_id=account,
            iis_type="type_a",
            opened_at=date(2030, 5, 12),
            eligible_close_at=date(2033, 5, 12),
            notes="Synthetic control date",
        )

        assert profile.account_id == account
        assert profile.iis_type == "type_a"
        assert profile.opened_at == date(2030, 5, 12)
        assert profile.eligible_close_at == date(2033, 5, 12)
        with pytest.raises(ValueError, match="IIS profile already exists"):
            create_iis_profile(
                session,
                account_id=account,
                iis_type="type_a",
                opened_at=date(2030, 5, 12),
            )
    finally:
        session.close()
        database.engine.dispose()


def test_iis_contribution_stores_exact_kopecks_and_unique_tax_year(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = account_id(session)
        contribution = create_iis_contribution(
            session,
            account_id=account,
            tax_year=2025,
            amount=RubleAmount.from_api("400000.01"),
            is_target_reached=True,
        )

        assert contribution.amount_kopecks == 40_000_001
        assert contribution.is_target_reached is True
        with pytest.raises(ValueError, match="contribution already exists"):
            create_iis_contribution(
                session,
                account_id=account,
                tax_year=2025,
                amount="1.00",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_tax_benefit_statuses_are_explicit(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = account_id(session)
        for status in TaxBenefitStatus:
            benefit = create_tax_benefit(
                session,
                account_id=account,
                tax_year=2025,
                benefit_type=f"{status.value}_benefit",
                status=status,
                amount=RubleAmount.from_api("1000.00"),
                received_at=date(2030, 5, 12) if status is TaxBenefitStatus.RECEIVED else None,
            )
            assert benefit.status == status.value
    finally:
        session.close()
        database.engine.dispose()


def test_planned_benefit_is_not_received(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = account_id(session)
        planned = create_tax_benefit(
            session,
            account_id=account,
            tax_year=2025,
            benefit_type="type_a",
            status=TaxBenefitStatus.PLANNED,
            amount="52000.00",
        )
        submitted = create_tax_benefit(
            session,
            account_id=account,
            tax_year=2026,
            benefit_type="type_a",
            status=TaxBenefitStatus.SUBMITTED,
            amount="52000.00",
        )
        received = create_tax_benefit(
            session,
            account_id=account,
            tax_year=2027,
            benefit_type="type_a",
            status=TaxBenefitStatus.RECEIVED,
            amount="52000.00",
            received_at=date(2028, 5, 12),
        )

        assert planned.counts_as_received is False
        assert submitted.counts_as_received is False
        assert received.counts_as_received is True
    finally:
        session.close()
        database.engine.dispose()


def test_tax_benefit_rejects_duplicate_account_year_and_type(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = account_id(session)
        create_tax_benefit(
            session,
            account_id=account,
            tax_year=2025,
            benefit_type="type_a",
            status=TaxBenefitStatus.PLANNED,
            amount="1.00",
        )
        with pytest.raises(ValueError, match="tax benefit already exists"):
            create_tax_benefit(
                session,
                account_id=account,
                tax_year=2025,
                benefit_type="type_a",
                status=TaxBenefitStatus.RECEIVED,
                amount="1.00",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_iis_constraints_reject_invalid_dates_years_and_negative_amounts(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    try:
        account = account_id(session)
        with pytest.raises(ValueError, match="eligible_close_at"):
            create_iis_profile(
                session,
                account_id=account,
                iis_type="type_a",
                opened_at=date(2030, 5, 12),
                eligible_close_at=date(2029, 5, 12),
            )
        with pytest.raises(ValueError, match="tax year"):
            create_iis_contribution(
                session,
                account_id=account,
                tax_year=1899,
                amount="1.00",
            )
        with pytest.raises(ValueError, match="must not be negative"):
            create_tax_benefit(
                session,
                account_id=account,
                tax_year=2025,
                benefit_type="type_a",
                status=TaxBenefitStatus.PLANNED,
                amount="-1.00",
            )
    finally:
        session.close()
        database.engine.dispose()
