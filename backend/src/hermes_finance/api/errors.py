"""Unified API error handling (D08).

Provides a single error response shape for all API errors and registers
exception handlers on a FastAPI application.

Response shape::

    {"error": {"code": "...", "message": "...", "details": [...]}}

Privacy invariant: handlers log the exception class, request path and status
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
from hermes_finance.services.concurrency import ConcurrencyError
from hermes_finance.services.reporting_months import ClosedReportingMonthError
from hermes_finance.services.salary_tax_context import SalaryTaxHistoryIncompleteError

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
            "%s path=%s status=%d code=%s",
            exc.__class__.__name__,
            request.url.path,
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
            details.append(ErrorDetail(field=field, message=err.get("msg", "validation error")))
        logger.info(
            "%s path=%s status=422 code=unprocessable",
            exc.__class__.__name__,
            request.url.path,
        )
        return _error_response(422, "unprocessable", "Request validation failed", details)

    @application.exception_handler(LookupError)
    async def _not_found_handler(request: Request, exc: LookupError) -> JSONResponse:
        logger.info(
            "%s path=%s status=404 code=not_found",
            exc.__class__.__name__,
            request.url.path,
        )
        return _error_response(404, "not_found", str(exc))

    @application.exception_handler(ClosedReportingMonthError)
    async def _closed_month_handler(
        request: Request, exc: ClosedReportingMonthError
    ) -> JSONResponse:
        logger.info(
            "%s path=%s status=409 code=conflict",
            exc.__class__.__name__,
            request.url.path,
        )
        return _error_response(409, "conflict", str(exc))

    @application.exception_handler(IntegrityError)
    async def _integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        logger.info(
            "%s path=%s status=409 code=conflict",
            exc.__class__.__name__,
            request.url.path,
        )
        return _error_response(409, "conflict", "Database integrity constraint violated")

    @application.exception_handler(ConcurrencyError)
    async def _concurrency_error_handler(request: Request, exc: ConcurrencyError) -> JSONResponse:
        logger.info(
            "%s path=%s status=409 code=conflict",
            exc.__class__.__name__,
            request.url.path,
        )
        return _error_response(409, "conflict", str(exc))

    @application.exception_handler(DatabaseMaintenanceError)
    async def _database_maintenance_handler(
        request: Request, exc: DatabaseMaintenanceError
    ) -> JSONResponse:
        logger.info(
            "%s path=%s status=409 code=conflict",
            exc.__class__.__name__,
            request.url.path,
        )
        return _error_response(409, "conflict", str(exc))

    @application.exception_handler(SalaryTaxHistoryIncompleteError)
    async def _salary_tax_history_incomplete_handler(
        request: Request, exc: SalaryTaxHistoryIncompleteError
    ) -> JSONResponse:
        logger.info(
            "%s path=%s status=422 code=%s",
            exc.__class__.__name__,
            request.url.path,
            exc.code,
        )
        return _error_response(422, exc.code, str(exc))

    @application.exception_handler(ValueError)
    async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        logger.info(
            "%s path=%s status=422 code=unprocessable",
            exc.__class__.__name__,
            request.url.path,
        )
        return _error_response(422, "unprocessable", str(exc))
