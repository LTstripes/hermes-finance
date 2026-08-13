from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from hermes_finance.database import Database, create_database
from hermes_finance.domain import RubleAmount
from hermes_finance.services.goals import get_or_create_main_goal
from hermes_finance.services.settings import (
    UPDATE_SETTINGS_UNSET,
    get_or_create_settings,
    parse_passive_income_history_start_month,
    update_settings,
)
from hermes_finance.settings import Settings as AppConfig

router = APIRouter(prefix="/api/settings", tags=["settings"])


class MoneyValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    amount: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: str) -> str:
        try:
            RubleAmount.from_api(value)
        except (TypeError, ValueError) as error:
            raise ValueError("amount must be a finite decimal string") from error
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if value != "RUB":
            raise ValueError("only RUB is supported")
        return value


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_currency: str | None = Field(default=None, min_length=3, max_length=3)
    locale: str | None = Field(default=None, min_length=2, max_length=32)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    passive_income_goal: MoneyValue | None = None
    formula_version: str | None = Field(default=None, min_length=1, max_length=32)
    passive_income_history_start_month: str | None = None

    @field_validator("passive_income_history_start_month")
    @classmethod
    def validate_history_start_month(cls, value: str | None) -> str | None:
        parse_passive_income_history_start_month(value)
        return value


class SettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    base_currency: str
    locale: str
    timezone: str
    passive_income_goal: MoneyValue
    formula_version: str
    passive_income_history_start_month: str | None


def _database_for_request(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:
        database = create_database(AppConfig().database_path)
        request.app.state.database = database
    return database


def session_for_request(request: Request) -> Generator[Session, None, None]:
    database = _database_for_request(request)
    with database.maintenance.operation():
        with database.session_factory() as session:
            yield session


def _response_from_settings(settings: object, main_goal: object) -> SettingsResponse:
    model = settings
    return SettingsResponse(
        base_currency=model.base_currency,
        locale=model.locale,
        timezone=model.timezone,
        passive_income_goal=MoneyValue(
            amount=RubleAmount(main_goal.target_value_kopecks).to_api(),
            currency=model.base_currency,
        ),
        formula_version=model.formula_version,
        passive_income_history_start_month=model.passive_income_history_start_month,
    )


@router.get("", response_model=SettingsResponse)
def read_settings(session: Session = Depends(session_for_request)) -> SettingsResponse:
    settings = get_or_create_settings(session)
    return _response_from_settings(settings, get_or_create_main_goal(session))


@router.put("", response_model=SettingsResponse)
def write_settings(
    payload: SettingsUpdate,
    session: Session = Depends(session_for_request),
) -> SettingsResponse:
    try:
        settings = update_settings(
            session,
            base_currency=payload.base_currency,
            locale=payload.locale,
            timezone=payload.timezone,
            passive_income_goal=(
                RubleAmount.from_api(payload.passive_income_goal.amount)
                if payload.passive_income_goal is not None
                else None
            ),
            formula_version=payload.formula_version,
            passive_income_history_start_month=(
                payload.passive_income_history_start_month
                if "passive_income_history_start_month" in payload.model_fields_set
                else UPDATE_SETTINGS_UNSET
            ),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _response_from_settings(settings, get_or_create_main_goal(session))
