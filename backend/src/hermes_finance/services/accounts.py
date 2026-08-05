from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hermes_finance.domain import AccountStatus, AccountType
from hermes_finance.persistence import Account


class AccountNotFoundError(LookupError):
    pass


def _coerce_account_type(account_type: AccountType | str) -> AccountType:
    try:
        return AccountType(account_type)
    except ValueError as error:
        raise ValueError(f"unsupported account type: {account_type!r}") from error


def _coerce_account_status(status: AccountStatus | str) -> AccountStatus:
    try:
        return AccountStatus(status)
    except ValueError as error:
        raise ValueError(f"unsupported account status: {status!r}") from error


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("account name must not be empty")
    return normalized


def _normalize_external_code(external_code: str | None) -> str | None:
    if external_code is None:
        return None
    normalized = external_code.strip()
    return normalized or None


def list_accounts(session: Session) -> list[Account]:
    return list(session.scalars(select(Account).order_by(Account.name, Account.id)))


def get_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError(f"account {account_id} was not found")
    return account


def create_account(
    session: Session,
    *,
    name: str,
    account_type: AccountType | str,
    external_code: str | None = None,
    status: AccountStatus | str = AccountStatus.ACTIVE,
    include_in_capital: bool = True,
    include_in_returns: bool = True,
    notes: str | None = None,
) -> Account:
    account = Account(
        name=_normalize_name(name),
        account_type=_coerce_account_type(account_type).value,
        external_code=_normalize_external_code(external_code),
        status=_coerce_account_status(status).value,
        include_in_capital=include_in_capital,
        include_in_returns=include_in_returns,
        notes=notes,
    )
    session.add(account)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ValueError("external_code must be unique when provided") from error
    session.refresh(account)
    return account


def update_account(
    session: Session,
    account_id: int,
    *,
    name: str | None = None,
    account_type: AccountType | str | None = None,
    external_code: str | None = None,
    status: AccountStatus | str | None = None,
    include_in_capital: bool | None = None,
    include_in_returns: bool | None = None,
    notes: str | None = None,
) -> Account:
    account = get_account(session, account_id)
    if name is not None:
        account.name = _normalize_name(name)
    if account_type is not None:
        account.account_type = _coerce_account_type(account_type).value
    if external_code is not None:
        account.external_code = _normalize_external_code(external_code)
    if status is not None:
        account.status = _coerce_account_status(status).value
    if include_in_capital is not None:
        account.include_in_capital = include_in_capital
    if include_in_returns is not None:
        account.include_in_returns = include_in_returns
    if notes is not None:
        account.notes = notes

    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ValueError("external_code must be unique when provided") from error
    session.refresh(account)
    return account


def delete_account(session: Session, account_id: int) -> None:
    account = get_account(session, account_id)
    session.delete(account)
    session.commit()
