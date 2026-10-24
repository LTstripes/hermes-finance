"""Unified API error handling (D08).

Provides a single error response shape for all API errors and registers
exception handlers on a FastAPI application.

Response shape::

    {"error": {"code": "...", "message": "...", "details": [...]}}

Privacy invariant: handlers log the exception class, route template and status
code only — never money amounts, request payloads, or financial details.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from hermes_finance.database import DatabaseMaintenanceError
from hermes_finance.diagnostics import request_route
from hermes_finance.services.backups import RestoreOutcomeAmbiguousError
from hermes_finance.services.concurrency import ConcurrencyError
from hermes_finance.services.debts import DebtAccountLinkConflictError
from hermes_finance.services.instruments import InstrumentDeletionBlockedError
from hermes_finance.services.linked_pairs import (
    LinkedPairBalanceEvidenceConflictError,
    LinkedPairReadModelError,
)
from hermes_finance.services.payout_preview import PayoutMappingRequiredError
from hermes_finance.services.quote_apply import PreviewChangedError
from hermes_finance.services.quote_preview_evidence import QuotePreviewEvidenceError
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    CloseGuardError,
    ReportingMonthNotFoundError,
)
from hermes_finance.services.salary_tax_context import SalaryTaxHistoryIncompleteError
from hermes_finance.services.scenario_lab import ScenarioLabError
from hermes_finance.services.statement_import_retract import StatementRetractError
from hermes_finance.services.tax_brackets import TaxBracketYearLockedError

logger = logging.getLogger("hermes_finance.api.errors")

_STATUS_CODE_TO_CODE: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "unprocessable",
    500: "internal_error",
}


# Exact reviewed literals only: never accept prefixes/suffixes containing input.
# Typed domain exceptions retain their own handlers below.
_SAFE_GENERIC_MESSAGES = frozenset(
    {
        "IIS profile was not found",
        "Backup is not a valid SQLite database",
        "Backup schema is incompatible with the live database",
        "MOEX ISS mapping — production provider disabled",
        "T-Invest инструмент не совместим с типом «Акция».",
        "T-Invest инструмент не совместим с типом «Облигация».",
        "T-Invest инструмент не совместим с типом «Фонд».",
        "accepted mapping identity was not found among provider candidates",
        "ambiguous market-data candidates cannot be accepted automatically",
        "engine/market is incompatible with instrument type",
        "isin mismatch between instrument and market identity",
        "isin mismatch between instrument and provider candidate",
        "opening taxable gross must be zero when effective_from_month is 1",
        "selected payout identity does not match the accepted local mapping",
        "unsupported instrument type for market mapping",
        "t_invest mapping requires provider verification",
        "base_kopecks must be >=0",
        "invalid_assumed_rate_pct: binary float not allowed",
        "invalid_assumed_rate_pct: empty",
        "invalid_assumed_rate_pct: must be decimal string or int",
        "invalid_assumed_rate_pct: negative rate not allowed",
        "invalid_assumed_rate_pct: not a decimal",
        "invalid_assumed_rate_pct: not finite",
        "invalid_assumed_rate_pct: unsupported type",
        "invalid_drawdown_pct: binary float not allowed",
        "invalid_drawdown_pct: empty",
        "invalid_drawdown_pct: must be decimal string or number",
        "invalid_drawdown_pct: not a decimal",
        "invalid_drawdown_pct: not finite",
        "invalid_drawdown_pct: out of range 0..100",
        "invalid_drawdown_pct: unsupported type",
        "invalid_inflation_pct: binary float not allowed",
        "invalid_inflation_pct: empty",
        "invalid_inflation_pct: must be decimal string or int",
        "invalid_inflation_pct: negative inflation not allowed",
        "invalid_inflation_pct: not a decimal",
        "invalid_inflation_pct: not finite",
        "invalid_inflation_pct: unsupported type",
        "invalid_reporting_value_change_pct: below -100",
        "invalid_reporting_value_change_pct: binary float not allowed",
        "invalid_reporting_value_change_pct: empty",
        "invalid_reporting_value_change_pct: must be decimal string or number",
        "invalid_reporting_value_change_pct: not a decimal",
        "invalid_reporting_value_change_pct: not finite",
        "invalid_reporting_value_change_pct: unsupported type",
        "invalid_target_currency: canonical three-letter identifier required",
        "invalid_target_currency: must be a string",
        "months_ahead must be >= 0",
        "account cannot be deleted while it is linked to a debt",
        "account name must not be empty",
        "account type cannot change while the account is linked to a debt",
        "amount must not be negative",
        "annual_rate must not be negative",
        "balance must not be negative",
        "cannot change a T-Invest quote while keeping t_invest price_source",
        "currency must not be empty",
        "current_balance must not be negative",
        "deposit and savings interest must be recorded in deposit_snapshots.actual_interest_received",
        "eligible_close_at must not precede opened_at",
        "expected cash flow already exists in forecast version",
        "expected cash flow is retained by historical payout reconciliation",
        "expected_net_amount must equal gross_amount minus expected_tax_amount",
        "expected_net_amount must equal gross_amount when tax is unknown",
        "external_code must be unique when provided",
        "forecast_version must use one source_as_of_date per reporting month",
        "instrument name must not be empty",
        "isin must be unique when provided",
        "linked account must already be included in capital",
        "linked account must be cash, deposit, or savings",
        "linked account must remain included in capital",
        "linked debt must already be included in liquid capital",
        "linked debt must remain a credit_card debt",
        "linked debt must remain included in liquid capital",
        "market_price_per_unit must not be negative",
        "name must not be empty",
        "net_amount must equal gross_amount minus tax_amount and commission_amount",
        "nominal_value must not be negative",
        "only credit_card debts can be linked to an account",
        "only other income may be included in passive income",
        "position snapshot already exists for month, account and instrument",
        "quantity must be finite",
        "quantity must be positive",
        "quantity must have at most 6 decimal places",
        "realized_loss net_amount must be negative",
        "reporting month already has a salary",
        "reporting month already has a salary income entry",
        "source-owned payout requires a reviewed source revision",
        "source-owned position cannot be replaced by a market quote",
        "source-owned position requires a reviewed source revision",
        "stock quantity must be a positive whole number",
        "t_invest price_source can only be set by quote apply",
        "tax year must be between 1900 and 9999",
        "unsupported account status",
        "unsupported account type",
        "unsupported debt type",
        "unsupported deposit type",
        "unsupported expected flow type",
        "unsupported expense type",
        "unsupported income type",
        "unsupported instrument type",
        "unsupported investment flow type",
        "unsupported price source",
        "unsupported tax benefit status",
    }
)


def _generic_message(exc: Exception, fallback: str) -> str:
    message = str(exc)
    return message if message in _SAFE_GENERIC_MESSAGES else fallback


def _code_for_status(status_code: int) -> str:
    return _STATUS_CODE_TO_CODE.get(status_code, f"status_{status_code}")


class ErrorDetail(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = []


class ErrorResponse(BaseModel):
    error: ErrorBody


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=ErrorBody(
                code=code,
                message=message,
                details=details or [],
            ),
        ).model_dump(),
    )


def _validation_message(error: dict) -> str:
    """Keep validation guidance while omitting values embedded by validators.

    The response deliberately projects only loc/msg, never Pydantic's input
    or ctx. Custom validators can also interpolate input into msg itself.
    """
    message = error.get("msg", "validation error")
    value = error.get("input")
    if isinstance(value, str) and value:
        message = message.replace(repr(value), "[redacted]")
        if message == f"Value error, {value}":
            message = "Value error, [redacted]"
        elif message.endswith(f": {value}"):
            message = message[: -len(value)] + "[redacted]"
    return message


def register_error_handlers(application: FastAPI) -> None:
    """Register unified exception handlers on *application*."""

    @application.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        status_code = exc.status_code
        code = _code_for_status(status_code)
        message = str(exc.detail) if exc.detail is not None else code
        logger.info(
            "%s route=%s status=%d code=%s",
            exc.__class__.__name__,
            request_route(request),
            status_code,
            code,
        )
        return _error_response(status_code, code, message)

    @application.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details: list[ErrorDetail] = []
        for err in exc.errors():
            loc = err.get("loc", ())
            field = ".".join(str(part) for part in loc if part != "body")
            details.append(
                ErrorDetail(
                    field=field,
                    message=_validation_message(err),
                )
            )
        logger.info(
            "%s route=%s status=422 code=unprocessable",
            exc.__class__.__name__,
            request_route(request),
        )
        return _error_response(422, "unprocessable", "Request validation failed", details)

    @application.exception_handler(LookupError)
    async def _not_found_handler(request: Request, exc: LookupError) -> JSONResponse:
        logger.info(
            "%s route=%s status=404 code=not_found",
            exc.__class__.__name__,
            request_route(request),
        )
        return _error_response(404, "not_found", _generic_message(exc, "Resource not found"))

    @application.exception_handler(LinkedPairReadModelError)
    async def _linked_pair_read_model_handler(
        request: Request, exc: LinkedPairReadModelError
    ) -> JSONResponse:
        logger.info(
            "%s route=%s status=422 code=%s",
            exc.__class__.__name__,
            request_route(request),
            exc.code,
        )
        return _error_response(422, exc.code, str(exc))

    @application.exception_handler(PreviewChangedError)
    @application.exception_handler(QuotePreviewEvidenceError)
    async def _preview_changed_handler(request: Request, exc: PreviewChangedError) -> JSONResponse:
        logger.info(
            "%s route=%s status=409 code=%s",
            exc.__class__.__name__,
            request_route(request),
            exc.code,
        )
        return _error_response(409, exc.code, str(exc))

    @application.exception_handler(CloseGuardError)
    async def _close_guard_handler(request: Request, exc: CloseGuardError) -> JSONResponse:
        logger.info(
            "%s route=%s status=%d code=%s",
            exc.__class__.__name__,
            request_route(request),
            exc.status_code,
            exc.code,
        )
        return _error_response(exc.status_code, exc.code, str(exc))

    @application.exception_handler(ClosedReportingMonthError)
    async def _closed_month_handler(
        request: Request, exc: ClosedReportingMonthError
    ) -> JSONResponse:
        logger.info(
            "%s route=%s status=409 code=conflict",
            exc.__class__.__name__,
            request_route(request),
        )
        return _error_response(409, "conflict", str(exc))

    @application.exception_handler(InstrumentDeletionBlockedError)
    async def _instrument_deletion_blocked_handler(
        request: Request, exc: InstrumentDeletionBlockedError
    ) -> JSONResponse:
        logger.info(
            "%s route=%s status=409 code=%s",
            exc.__class__.__name__,
            request_route(request),
            exc.code,
        )
        return _error_response(409, exc.code, str(exc))

    @application.exception_handler(DebtAccountLinkConflictError)
    async def _debt_account_link_conflict_handler(
        request: Request, exc: DebtAccountLinkConflictError
    ) -> JSONResponse:
        logger.info(
            "%s route=%s status=409 code=conflict",
            exc.__class__.__name__,
            request_route(request),
        )
        return _error_response(409, "conflict", str(exc))

    @application.exception_handler(LinkedPairBalanceEvidenceConflictError)
    async def _linked_pair_balance_evidence_conflict_handler(
        request: Request, exc: LinkedPairBalanceEvidenceConflictError
    ) -> JSONResponse:
        logger.info(
            "%s route=%s status=409 code=%s",
            exc.__class__.__name__,
            request_route(request),
            exc.code,
        )
        return _error_response(409, exc.code, str(exc))

    @application.exception_handler(TaxBracketYearLockedError)
    async def _tax_bracket_year_locked_handler(
        request: Request, exc: TaxBracketYearLockedError
    ) -> JSONResponse:
        logger.info(
            "%s route=%s status=409 code=tax_brackets_year_locked",
            exc.__class__.__name__,
            request_route(request),
        )
        return _error_response(
            409,
            "tax_brackets_year_locked",
            str(exc),
            [
                ErrorDetail(field="closed_month", message=f"{exc.year:04d}-{month:02d}")
                for month in exc.closed_months
            ],
        )

    @application.exception_handler(IntegrityError)
    async def _integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        logger.info(
            "%s route=%s status=409 code=conflict",
            exc.__class__.__name__,
            request_route(request),
        )
        return _error_response(409, "conflict", "Database integrity constraint violated")

    @application.exception_handler(ConcurrencyError)
    async def _concurrency_error_handler(request: Request, exc: ConcurrencyError) -> JSONResponse:
        logger.info(
            "%s route=%s status=409 code=conflict",
            exc.__class__.__name__,
            request_route(request),
        )
        return _error_response(409, "conflict", str(exc))

    @application.exception_handler(DatabaseMaintenanceError)
    async def _database_maintenance_handler(
        request: Request, exc: DatabaseMaintenanceError
    ) -> JSONResponse:
        logger.info(
            "%s route=%s status=409 code=conflict",
            exc.__class__.__name__,
            request_route(request),
        )
        return _error_response(409, "conflict", str(exc))

    @application.exception_handler(RestoreOutcomeAmbiguousError)
    async def _restore_outcome_ambiguous_handler(
        request: Request, exc: RestoreOutcomeAmbiguousError
    ) -> JSONResponse:
        logger.info(
            "%s route=%s status=500 code=restore_outcome_ambiguous",
            exc.__class__.__name__,
            request_route(request),
        )
        return _error_response(500, "restore_outcome_ambiguous", str(exc))

    @application.exception_handler(SalaryTaxHistoryIncompleteError)
    async def _salary_tax_history_incomplete_handler(
        request: Request, exc: SalaryTaxHistoryIncompleteError
    ) -> JSONResponse:
        logger.info(
            "%s route=%s status=422 code=%s",
            exc.__class__.__name__,
            request_route(request),
            exc.code,
        )
        return _error_response(422, exc.code, str(exc))

    @application.exception_handler(PayoutMappingRequiredError)
    async def _payout_mapping_required_handler(
        request: Request, exc: PayoutMappingRequiredError
    ) -> JSONResponse:
        logger.info(
            "%s route=%s status=422 code=%s",
            exc.__class__.__name__,
            request_route(request),
            exc.code,
        )
        return _error_response(422, exc.code, str(exc))

    @application.exception_handler(StatementRetractError)
    async def _statement_retract_handler(
        request: Request, exc: StatementRetractError
    ) -> JSONResponse:
        logger.info(
            "%s route=%s status=%d code=%s",
            exc.__class__.__name__,
            request_route(request),
            exc.status_code,
            exc.code,
        )
        return _error_response(exc.status_code, exc.code, str(exc))

    @application.exception_handler(ValueError)
    async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        # Scenario Lab domain validators raise plain ValueError with a
        # machine-readable prefix ("invalid_target_currency: ...",
        # "invalid_reporting_value_change_pct: ...",
        # "invalid_drawdown_pct: ..."). For scenario-lab paths we
        # surface that prefix as the exact error.code so owner tooling
        # can branch without parsing messages. All other paths keep
        # generic unprocessable.
        message = str(exc)
        code = "unprocessable"
        if "scenario-lab" in request_route(request) and ":" in message:
            prefix = message.split(":", 1)[0].strip()
            if prefix in {
                "invalid_target_currency",
                "invalid_reporting_value_change_pct",
                "invalid_drawdown_pct",
            }:
                code = prefix
        logger.info(
            "%s route=%s status=422 code=%s",
            exc.__class__.__name__,
            request_route(request),
            code,
        )
        return _error_response(422, code, _generic_message(exc, "Invalid request value"))

    # Scenario handlers are registered alongside the generic ValueError and
    # LookupError handlers; Starlette resolves handlers by walking the
    # exception MRO (most derived class first), so the concrete
    # ScenarioLabError (a ValueError subclass) and
    # ReportingMonthNotFoundError (a LookupError subclass) branches win
    # over their bases. The service machine-readable codes
    # (unsupported_composition_v1, unsupported_shock_type_v1,
    # invalid_shock_input, invalid_top_n, ...) are preserved verbatim in
    # the unified error envelope.

    @application.exception_handler(ScenarioLabError)
    async def _scenario_lab_error_handler(request: Request, exc: ScenarioLabError) -> JSONResponse:
        logger.info(
            "%s route=%s status=422 code=%s",
            exc.__class__.__name__,
            request_route(request),
            exc.code,
        )
        return _error_response(422, exc.code, str(exc))

    @application.exception_handler(ReportingMonthNotFoundError)
    async def _reporting_month_not_found_handler(
        request: Request, exc: ReportingMonthNotFoundError
    ) -> JSONResponse:
        # Scenario Lab requires a distinct machine-readable code so
        # owner tooling can distinguish a missing month deterministically,
        # but the historical global mapping is 404/not_found. We keep
        # backward compatibility: scenario-lab paths surface
        # reporting_month_not_found while all other callers keep not_found.
        path = request_route(request)
        if "scenario-lab" in path:
            code = "reporting_month_not_found"
        else:
            code = "not_found"
        logger.info(
            "%s route=%s status=404 code=%s",
            exc.__class__.__name__,
            request_route(request),
            code,
        )
        return _error_response(404, code, str(exc))
