from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.responses import FileResponse

from hermes_finance import __version__
from hermes_finance.api.accounts import router as accounts_router
from hermes_finance.api.backups import router as backups_router
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
from hermes_finance.api.salary_tax import router as salary_tax_router
from hermes_finance.api.savings import router as savings_router
from hermes_finance.api.settings import router as settings_router
from hermes_finance.database import Database
from hermes_finance.security import LocalhostSecurityMiddleware
from hermes_finance.settings import Settings


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


def _frontend_response(static_dir: Path, path: str) -> FileResponse:
    if path == "" or path.startswith("api/"):
        candidate = static_dir / "index.html"
    else:
        candidate = (static_dir / path).resolve()
        if not candidate.is_relative_to(static_dir) or not candidate.is_file():
            candidate = static_dir / "index.html"

    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Frontend build is not available")
    return FileResponse(candidate)


def create_app(
    database: Database | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    application = FastAPI(title="Hermes Finance API", version=__version__)
    application.add_middleware(LocalhostSecurityMiddleware)
    if database is not None:
        application.state.database = database
    register_error_handlers(application)
    application.include_router(settings_router)
    application.include_router(months_router)
    application.include_router(dashboard_router)
    application.include_router(accounts_router)
    application.include_router(backups_router)
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
    application.include_router(salary_tax_router)
    application.include_router(debts_router)
    application.include_router(properties_router)
    application.include_router(comments_router)
    application.include_router(exports_router)

    @application.get("/api/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    resolved_static_dir = (
        (static_dir or Settings(_env_file=None).frontend_dist).expanduser().resolve()
    )
    if resolved_static_dir.is_dir():

        @application.get("/{path:path}", include_in_schema=False)
        async def frontend(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            return _frontend_response(resolved_static_dir, path)

    return application


app = create_app()
