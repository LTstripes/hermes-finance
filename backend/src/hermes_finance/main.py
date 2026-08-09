from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from hermes_finance import __version__
from hermes_finance.api.accounts import router as accounts_router
from hermes_finance.api.cash import router as cash_router
from hermes_finance.api.comments import router as comments_router
from hermes_finance.api.dashboard import router as dashboard_router
from hermes_finance.api.debts import router as debts_router
from hermes_finance.api.deposits import router as deposits_router
from hermes_finance.api.errors import register_error_handlers
from hermes_finance.api.expected_flows import router as expected_flows_router
from hermes_finance.api.expenses import router as expenses_router
from hermes_finance.api.exports import router as exports_router
from hermes_finance.api.iis import router as iis_router
from hermes_finance.api.incomes import router as incomes_router
from hermes_finance.api.instruments import router as instruments_router
from hermes_finance.api.investment_flows import router as investment_flows_router
from hermes_finance.api.months import router as months_router
from hermes_finance.api.positions import router as positions_router
from hermes_finance.api.properties import router as properties_router
from hermes_finance.api.savings import router as savings_router
from hermes_finance.api.settings import router as settings_router
from hermes_finance.database import Database


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


def create_app(database: Database | None = None) -> FastAPI:
    application = FastAPI(title="Hermes Finance API", version=__version__)
    if database is not None:
        application.state.database = database
    register_error_handlers(application)
    application.include_router(settings_router)
    application.include_router(months_router)
    application.include_router(dashboard_router)
    application.include_router(accounts_router)
    application.include_router(instruments_router)
    application.include_router(iis_router)
    application.include_router(positions_router)
    application.include_router(deposits_router)
    application.include_router(cash_router)
    application.include_router(incomes_router)
    application.include_router(investment_flows_router)
    application.include_router(expected_flows_router)
    application.include_router(expenses_router)
    application.include_router(savings_router)
    application.include_router(debts_router)
    application.include_router(properties_router)
    application.include_router(comments_router)
    application.include_router(exports_router)

    @application.get("/api/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    return application


app = create_app()
