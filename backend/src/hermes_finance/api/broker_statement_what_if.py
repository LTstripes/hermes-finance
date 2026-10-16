"""Transient original-bound WHAT-IF reads. No scenario persistence or authority writes."""

import json

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from hermes_finance.api.mybroker_import import _bytes
from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.broker_statement_what_if import StatementWhatIfAssumptions
from hermes_finance.services import broker_statement_what_if as service
from hermes_finance.statement_import.mybroker import MyBrokerError

NO_STORE = {"Cache-Control": "no-store"}


class WhatIfRoute(APIRoute):
    """Typed errors and no-store also cover multipart validation and upload failures."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                response = await handler(request)
            except (HTTPException, RequestValidationError) as error:
                code = (
                    str(error.detail)
                    if isinstance(error, HTTPException)
                    else "what_if_request_invalid"
                )
                response = JSONResponse(
                    status_code=error.status_code if isinstance(error, HTTPException) else 422,
                    content={"error": {"code": code, "message": code, "details": []}},
                )
            response.headers.update(NO_STORE)
            return response

        return guarded


router = APIRouter(
    prefix="/api/broker-statement-what-if",
    tags=["broker-statement-what-if"],
    route_class=WhatIfRoute,
)


async def _read(request, session, file, operation):
    form = await request.form()
    required = {"file", "account_id", "request_id", "expected_actual_fingerprint"}
    if operation != "context":
        required |= {"assumptions", "expected_context_fingerprint"}
    if operation == "export":
        required.add("expected_result_fingerprint")
    if (
        set(form) != required
        or any(len(form.getlist(k)) != 1 for k in form)
        or request.query_params
    ):
        raise HTTPException(422, "what_if_request_fields_invalid", headers=NO_STORE)
    try:
        account = form["account_id"]
        if (
            not isinstance(account, str)
            or not account.isascii()
            or not account.isdigit()
            or int(account) <= 0
        ):
            raise ValueError
        request_id = form["request_id"]
        if not isinstance(request_id, str) or not request_id or len(request_id) > 200:
            raise ValueError
        for name in required & {
            "expected_actual_fingerprint",
            "expected_context_fingerprint",
            "expected_result_fingerprint",
        }:
            value = form[name]
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise ValueError
        assumptions = (
            StatementWhatIfAssumptions.model_validate_json(form["assumptions"])
            if operation != "context"
            else None
        )
    except (ValueError, TypeError, ValidationError):
        # Never include the request body or original financial values in errors.
        raise HTTPException(422, "what_if_request_invalid", headers=NO_STORE) from None
    source = dict(
        account_id=int(account),
        request_id=request_id,
        original=await _bytes(file),
        filename=file.filename or "",
        expected_actual_fingerprint=form["expected_actual_fingerprint"],
    )
    try:
        if operation == "context":
            result = service.read_context(session, **source)
        else:
            result = service.evaluate(
                session,
                **source,
                assumptions=assumptions,
                expected_context_fingerprint=form["expected_context_fingerprint"],
                expected_result_fingerprint=form.get("expected_result_fingerprint"),
            )
    except service.WhatIfStaleError as error:
        raise HTTPException(409, str(error), headers=NO_STORE) from None
    except MyBrokerError as error:
        raise HTTPException(404, str(error), headers=NO_STORE) from None
    headers = dict(NO_STORE)
    if operation == "export":
        headers["Content-Disposition"] = 'attachment; filename="broker-statement-what-if.json"'
    return Response(
        content=json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        media_type="application/json",
        headers=headers,
    )


@router.post("/context")
async def context(
    request: Request, file: UploadFile = File(...), session: Session = Depends(session_for_request)
):
    return await _read(request, session, file, "context")


@router.post("/evaluate")
async def evaluate(
    request: Request, file: UploadFile = File(...), session: Session = Depends(session_for_request)
):
    return await _read(request, session, file, "evaluate")


@router.post("/export")
async def export(
    request: Request, file: UploadFile = File(...), session: Session = Depends(session_for_request)
):
    return await _read(request, session, file, "export")
