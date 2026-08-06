from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hermes_finance.domain import RubleAmount, TaxBenefitStatus
from hermes_finance.persistence import Account, IisContribution, IisProfile, TaxBenefit
from hermes_finance.services.accounts import AccountNotFoundError

_MIN_TAX_YEAR = 1900
_MAX_TAX_YEAR = 9999


def _require_account(session: Session, account_id: int) -> None:
    if session.get(Account, account_id) is None:
        raise AccountNotFoundError(f"account {account_id} was not found")


def _require_tax_year(tax_year: int) -> int:
    if isinstance(tax_year, bool) or not isinstance(tax_year, int):
        raise TypeError("tax year must be an int")
    if not _MIN_TAX_YEAR <= tax_year <= _MAX_TAX_YEAR:
        raise ValueError("tax year must be between 1900 and 9999")
    return tax_year


def _require_amount(amount: RubleAmount | str) -> int:
    if isinstance(amount, str):
        amount = RubleAmount.from_api(amount)
    if not isinstance(amount, RubleAmount):
        raise TypeError("amount must be RubleAmount or decimal string")
    if amount.kopecks < 0:
        raise ValueError("amount must not be negative")
    return amount.kopecks


def _require_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _commit_unique(session: Session, error_message: str) -> None:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ValueError(error_message) from error


def create_iis_profile(
    session: Session,
    *,
    account_id: int,
    iis_type: str,
    opened_at: date,
    eligible_close_at: date | None = None,
    notes: str | None = None,
) -> IisProfile:
    _require_account(session, account_id)
    if eligible_close_at is not None and eligible_close_at < opened_at:
        raise ValueError("eligible_close_at must not precede opened_at")
    profile = IisProfile(
        account_id=account_id,
        iis_type=_require_text(iis_type, field="iis_type"),
        opened_at=opened_at,
        eligible_close_at=eligible_close_at,
        notes=notes,
    )
    session.add(profile)
    _commit_unique(session, "IIS profile already exists for account")
    session.refresh(profile)
    return profile


def create_iis_contribution(
    session: Session,
    *,
    account_id: int,
    tax_year: int,
    amount: RubleAmount | str,
    is_target_reached: bool = False,
    notes: str | None = None,
) -> IisContribution:
    _require_account(session, account_id)
    contribution = IisContribution(
        account_id=account_id,
        tax_year=_require_tax_year(tax_year),
        amount_kopecks=_require_amount(amount),
        is_target_reached=is_target_reached,
        notes=notes,
    )
    session.add(contribution)
    _commit_unique(session, "contribution already exists for account and tax year")
    session.refresh(contribution)
    return contribution


def create_tax_benefit(
    session: Session,
    *,
    account_id: int,
    tax_year: int,
    benefit_type: str,
    status: TaxBenefitStatus | str,
    amount: RubleAmount | str,
    received_at: date | None = None,
    notes: str | None = None,
) -> TaxBenefit:
    _require_account(session, account_id)
    benefit = TaxBenefit(
        account_id=account_id,
        tax_year=_require_tax_year(tax_year),
        benefit_type=_require_text(benefit_type, field="benefit_type"),
        status=TaxBenefitStatus(status).value,
        amount_kopecks=_require_amount(amount),
        received_at=received_at,
        notes=notes,
    )
    session.add(benefit)
    _commit_unique(session, "tax benefit already exists for account, tax year and type")
    session.refresh(benefit)
    return benefit
