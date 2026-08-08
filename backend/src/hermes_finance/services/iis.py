from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hermes_finance.domain import RubleAmount, TaxBenefitStatus
from hermes_finance.persistence import Account, IisContribution, IisProfile, TaxBenefit
from hermes_finance.services.accounts import AccountNotFoundError

_MIN_TAX_YEAR = 1900
_MAX_TAX_YEAR = 9999


class IisProfileNotFoundError(LookupError):
    pass


class IisContributionNotFoundError(LookupError):
    pass


class TaxBenefitNotFoundError(LookupError):
    pass


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


# --- read helpers (additive, D04) ---


def get_iis_profile_by_account(session: Session, account_id: int) -> IisProfile | None:
    return session.scalar(select(IisProfile).where(IisProfile.account_id == account_id))


def list_iis_contributions(
    session: Session, account_id: int, *, tax_year: int | None = None
) -> list[IisContribution]:
    stmt = select(IisContribution).where(IisContribution.account_id == account_id)
    if tax_year is not None:
        stmt = stmt.where(IisContribution.tax_year == tax_year)
    stmt = stmt.order_by(IisContribution.tax_year, IisContribution.id)
    return list(session.scalars(stmt))


def list_tax_benefits(
    session: Session,
    account_id: int,
    *,
    status: TaxBenefitStatus | str | None = None,
) -> list[TaxBenefit]:
    stmt = select(TaxBenefit).where(TaxBenefit.account_id == account_id)
    if status is not None:
        status_value = TaxBenefitStatus(status).value
        stmt = stmt.where(TaxBenefit.status == status_value)
    stmt = stmt.order_by(TaxBenefit.tax_year, TaxBenefit.benefit_type, TaxBenefit.id)
    return list(session.scalars(stmt))


def get_iis_contribution(session: Session, contribution_id: int) -> IisContribution:
    contribution = session.get(IisContribution, contribution_id)
    if contribution is None:
        raise IisContributionNotFoundError(f"IIS contribution {contribution_id} was not found")
    return contribution


def get_iis_contribution_by_key(
    session: Session, *, account_id: int, tax_year: int
) -> IisContribution | None:
    """Return the contribution for ``(account, tax_year)`` or ``None``.

    Read-only lookup used by the API layer to map duplicate-contribution
    creation attempts to an HTTP 409 conflict without changing the
    ValueError contract of :func:`create_iis_contribution`.
    """
    return session.scalar(
        select(IisContribution).where(
            IisContribution.account_id == account_id,
            IisContribution.tax_year == tax_year,
        )
    )


def get_tax_benefit(session: Session, benefit_id: int) -> TaxBenefit:
    benefit = session.get(TaxBenefit, benefit_id)
    if benefit is None:
        raise TaxBenefitNotFoundError(f"tax benefit {benefit_id} was not found")
    return benefit


def get_tax_benefit_by_key(
    session: Session, *, account_id: int, tax_year: int, benefit_type: str
) -> TaxBenefit | None:
    """Return the benefit for ``(account, tax_year, benefit_type)`` or ``None``.

    Read-only lookup used by the API layer to map duplicate-benefit creation
    attempts to an HTTP 409 conflict without changing the ValueError
    contract of :func:`create_tax_benefit`.
    """
    return session.scalar(
        select(TaxBenefit).where(
            TaxBenefit.account_id == account_id,
            TaxBenefit.tax_year == tax_year,
            TaxBenefit.benefit_type == benefit_type,
        )
    )


# --- update/delete (additive, D04) ---


def update_iis_profile(
    session: Session,
    profile_id: int | None = None,
    *,
    account_id: int | None = None,
    iis_type: str | None = None,
    opened_at: date | None = None,
    eligible_close_at: date | None = None,
    notes: str | None = None,
) -> IisProfile:
    if profile_id is not None:
        profile = session.get(IisProfile, profile_id)
    elif account_id is not None:
        profile = get_iis_profile_by_account(session, account_id)
    else:
        raise TypeError("either profile_id or account_id must be provided")
    if profile is None:
        raise IisProfileNotFoundError("IIS profile was not found")
    if iis_type is not None:
        profile.iis_type = _require_text(iis_type, field="iis_type")
    if opened_at is not None:
        profile.opened_at = opened_at
    if eligible_close_at is not None:
        profile.eligible_close_at = eligible_close_at
    if notes is not None:
        profile.notes = notes
    if profile.eligible_close_at is not None and profile.eligible_close_at < profile.opened_at:
        raise ValueError("eligible_close_at must not precede opened_at")
    _commit_unique(session, "IIS profile already exists for account")
    session.refresh(profile)
    return profile


def delete_iis_profile(
    session: Session, profile_id: int | None = None, *, account_id: int | None = None
) -> None:
    if profile_id is not None:
        profile = session.get(IisProfile, profile_id)
    elif account_id is not None:
        profile = get_iis_profile_by_account(session, account_id)
    else:
        raise TypeError("either profile_id or account_id must be provided")
    if profile is None:
        raise IisProfileNotFoundError("IIS profile was not found")
    session.delete(profile)
    session.commit()


def update_iis_contribution(
    session: Session,
    contribution_id: int,
    *,
    tax_year: int | None = None,
    amount: RubleAmount | str | None = None,
    is_target_reached: bool | None = None,
    notes: str | None = None,
) -> IisContribution:
    contribution = get_iis_contribution(session, contribution_id)
    if tax_year is not None:
        contribution.tax_year = _require_tax_year(tax_year)
    if amount is not None:
        contribution.amount_kopecks = _require_amount(amount)
    if is_target_reached is not None:
        contribution.is_target_reached = is_target_reached
    if notes is not None:
        contribution.notes = notes
    _commit_unique(session, "contribution already exists for account and tax year")
    session.refresh(contribution)
    return contribution


def delete_iis_contribution(session: Session, contribution_id: int) -> None:
    contribution = get_iis_contribution(session, contribution_id)
    session.delete(contribution)
    session.commit()


def update_tax_benefit(
    session: Session,
    benefit_id: int,
    *,
    tax_year: int | None = None,
    benefit_type: str | None = None,
    status: TaxBenefitStatus | str | None = None,
    amount: RubleAmount | str | None = None,
    received_at: date | None = None,
    notes: str | None = None,
) -> TaxBenefit:
    benefit = get_tax_benefit(session, benefit_id)
    if tax_year is not None:
        benefit.tax_year = _require_tax_year(tax_year)
    if benefit_type is not None:
        benefit.benefit_type = _require_text(benefit_type, field="benefit_type")
    if status is not None:
        benefit.status = TaxBenefitStatus(status).value
    if amount is not None:
        benefit.amount_kopecks = _require_amount(amount)
    if received_at is not None:
        benefit.received_at = received_at
    if notes is not None:
        benefit.notes = notes
    _commit_unique(session, "tax benefit already exists for account, tax year and type")
    session.refresh(benefit)
    return benefit


def delete_tax_benefit(session: Session, benefit_id: int) -> None:
    benefit = get_tax_benefit(session, benefit_id)
    session.delete(benefit)
    session.commit()
