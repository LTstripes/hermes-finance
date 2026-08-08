from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from hermes_finance import __version__
from hermes_finance.api.errors import register_error_handlers
from hermes_finance.api.months import router as months_router
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

    @application.get("/api/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    return application


app = create_app()
