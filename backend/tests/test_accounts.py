from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountStatus, AccountType
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import (
    AccountNotFoundError,
    create_account,
    delete_account,
    get_account,
    list_accounts,
    update_account,
)


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "accounts.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


@pytest.mark.parametrize("account_type", list(AccountType))
def test_account_types_are_persisted(account_type: AccountType, tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = create_account(
            session, name=f"Synthetic {account_type.value}", account_type=account_type
        )
        assert account.account_type == account_type.value
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize("status", list(AccountStatus))
def test_account_statuses_are_persisted(status: AccountStatus, tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = create_account(
            session,
            name=f"Synthetic {status.value}",
            account_type=AccountType.OTHER,
            status=status,
            include_in_capital=status == AccountStatus.FROZEN,
        )
        assert account.status == status.value
        if status == AccountStatus.FROZEN:
            assert account.include_in_capital is True
    finally:
        session.close()
        database.engine.dispose()


def test_external_code_is_unique_only_when_provided(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first = create_account(
            session,
            name="Synthetic Broker",
            account_type=AccountType.BROKERAGE,
            external_code="broker-001",
        )
        second = create_account(
            session,
            name="Synthetic Cash",
            account_type=AccountType.CASH,
        )
        third = create_account(
            session,
            name="Synthetic Other",
            account_type=AccountType.OTHER,
        )
        assert first.external_code == "broker-001"
        assert second.external_code is None
        assert third.external_code is None

        with pytest.raises(ValueError, match="external_code must be unique"):
            create_account(
                session,
                name="Synthetic Duplicate",
                account_type=AccountType.BROKERAGE,
                external_code="broker-001",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_account_crud_updates_flags_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = create_account(
            session,
            name="  Synthetic IIS  ",
            account_type=AccountType.IIS,
            include_in_capital=False,
            include_in_returns=False,
        )
        updated = update_account(
            session,
            account.id,
            name="Synthetic IIS Updated",
            status=AccountStatus.FROZEN,
            include_in_capital=True,
            notes="synthetic note",
        )
        assert updated.name == "Synthetic IIS Updated"
        assert updated.status == AccountStatus.FROZEN.value
        assert updated.include_in_capital is True
        assert updated.include_in_returns is False
        assert updated.notes == "synthetic note"
        assert get_account(session, account.id).name == "Synthetic IIS Updated"
        assert len(list_accounts(session)) == 1

        delete_account(session, account.id)
        with pytest.raises(AccountNotFoundError):
            get_account(session, account.id)
    finally:
        session.close()
        database.engine.dispose()


def test_account_validation_rejects_invalid_type_and_empty_name(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        with pytest.raises(ValueError, match="must not be empty"):
            create_account(session, name="  ", account_type=AccountType.OTHER)
        with pytest.raises(ValueError, match="unsupported account type"):
            create_account(session, name="Synthetic", account_type="crypto_wallet")
        with pytest.raises(ValueError, match="unsupported account status"):
            create_account(
                session, name="Synthetic", account_type=AccountType.OTHER, status="paused"
            )
    finally:
        session.close()
        database.engine.dispose()
