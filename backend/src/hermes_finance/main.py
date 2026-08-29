from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.responses import FileResponse

from hermes_finance import __version__
from hermes_finance.api.accounts import router as accounts_router
from hermes_finance.api.ai_analysis_bundle import router as ai_analysis_bundle_router
from hermes_finance.api.analytics import router as analytics_router
from hermes_finance.api.backups import router as backups_router
from hermes_finance.api.broker_reconciliation import router as broker_reconciliation_router
from hermes_finance.api.broker_snapshot import router as broker_snapshot_router
from hermes_finance.api.cash import router as cash_router
from hermes_finance.api.cash_flow_ladder import router as cash_flow_ladder_router
from hermes_finance.api.close_readiness import router as close_readiness_router
from hermes_finance.api.comments import router as comments_router
from hermes_finance.api.dashboard import router as dashboard_router
from hermes_finance.api.debts import router as debts_router
from hermes_finance.api.deposits import router as deposits_router
from hermes_finance.api.deterministic_insights import router as deterministic_insights_router
from hermes_finance.api.errors import register_error_handlers
from hermes_finance.api.expected_flows import router as expected_flows_router
from hermes_finance.api.expenses import router as expenses_router
from hermes_finance.api.exports import router as exports_router
from hermes_finance.api.external_flows import router as external_flows_router
from hermes_finance.api.freshness_provenance import router as freshness_provenance_router
from hermes_finance.api.goals import router as goals_router
from hermes_finance.api.iis import router as iis_router
from hermes_finance.api.incomes import router as incomes_router
from hermes_finance.api.instrument_mappings import router as instrument_mappings_router
from hermes_finance.api.instruments import router as instruments_router
from hermes_finance.api.investment_flows import router as investment_flows_router
from hermes_finance.api.months import router as months_router
from hermes_finance.api.payouts import router as payouts_router
from hermes_finance.api.performance_availability import router as performance_availability_router
from hermes_finance.api.portfolio_xirr import router as portfolio_xirr_router
from hermes_finance.api.positions import router as positions_router
from hermes_finance.api.properties import router as properties_router
from hermes_finance.api.provider_capabilities import router as provider_capabilities_router
from hermes_finance.api.quote_apply import router as quote_apply_router
from hermes_finance.api.quote_preview import router as quote_preview_router
from hermes_finance.api.risk_allocation import router as risk_allocation_router
from hermes_finance.api.salary_tax import router as salary_tax_router
from hermes_finance.api.savings import router as savings_router
from hermes_finance.api.settings import router as settings_router
from hermes_finance.api.statement_import import router as statement_import_router
from hermes_finance.api.tax_brackets import router as tax_brackets_router
from hermes_finance.api.tax_iis_planner import router as tax_iis_planner_router
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
    market_data_provider: object | None = None,
    payout_provider: object | None = None,
    broker_snapshot_provider: object | None = None,
) -> FastAPI:
    application = FastAPI(title="Hermes Finance API", version=__version__)
    application.add_middleware(LocalhostSecurityMiddleware)
    if database is not None:
        application.state.database = database
    if market_data_provider is not None:
        application.state.market_data_provider = market_data_provider
    if payout_provider is not None:
        application.state.payout_provider = payout_provider
    if broker_snapshot_provider is not None:
        application.state.broker_snapshot_provider = broker_snapshot_provider
    register_error_handlers(application)
    application.include_router(settings_router)
    application.include_router(tax_brackets_router)
    application.include_router(months_router)
    application.include_router(close_readiness_router)
    application.include_router(freshness_provenance_router)
    application.include_router(quote_preview_router)
    application.include_router(quote_apply_router)
    application.include_router(payouts_router)
    application.include_router(performance_availability_router)
    application.include_router(portfolio_xirr_router)
    application.include_router(broker_snapshot_router)
    application.include_router(broker_reconciliation_router)
    application.include_router(statement_import_router)
    application.include_router(dashboard_router)
    application.include_router(analytics_router)
    application.include_router(accounts_router)
    application.include_router(backups_router)
    application.include_router(instruments_router)
    application.include_router(instrument_mappings_router)
    application.include_router(iis_router)
    application.include_router(positions_router)
    application.include_router(deposits_router)
    application.include_router(cash_router)
    application.include_router(cash_flow_ladder_router)
    application.include_router(incomes_router)
    application.include_router(investment_flows_router)
    application.include_router(external_flows_router)
    application.include_router(expected_flows_router)
    application.include_router(expenses_router)
    application.include_router(savings_router)
    application.include_router(salary_tax_router)
    application.include_router(tax_iis_planner_router)
    application.include_router(debts_router)
    application.include_router(properties_router)
    application.include_router(provider_capabilities_router)
    application.include_router(risk_allocation_router)
    application.include_router(deterministic_insights_router)
    application.include_router(comments_router)
    application.include_router(exports_router)
    application.include_router(ai_analysis_bundle_router)
    application.include_router(goals_router)

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
