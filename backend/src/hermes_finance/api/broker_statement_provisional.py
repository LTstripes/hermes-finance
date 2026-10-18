"""Transient source-intake provisional reads. No scenario persistence or writes."""

import json

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from hermes_finance.api.mybroker_import import _bytes
from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.broker_statement_provisional import ProvisionalAssumptions
from hermes_finance.services import broker_statement_provisional as service
from hermes_finance.statement_import.mybroker import MyBrokerError

NO_STORE = {"Cache-Control": "no-store"}


class ProvisionalRoute(APIRoute):
    """Typed errors and no-store also cover multipart validation and upload failures."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                response = await handler(request)
            except (StarletteHTTPException, RequestValidationError) as error:
                code = (
                    str(error.detail)
                    if isinstance(error, StarletteHTTPException) and error.status_code != 400
                    else "provisional_request_invalid"
                )
                response = JSONResponse(
                    status_code=(
                        error.status_code
                        if isinstance(error, StarletteHTTPException) and error.status_code != 400
                        else 422
                    ),
                    content={"error": {"code": code, "message": code, "details": []}},
                )
            response.headers.update(NO_STORE)
            return response

        return guarded


router = APIRouter(
    prefix="/api/broker-statement-provisional",
    tags=["broker-statement-provisional"],
    route_class=ProvisionalRoute,
)


def _digest(value) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError
    return value


async def _read(request, session, file, operation):
    form = await request.form()
    required = {"file", "intake_id", "expected_manifest_digest"}
    if operation != "context":
        required |= {"assumptions", "expected_context_fingerprint"}
    if operation == "export":
        required.add("expected_result_fingerprint")
    if (
        set(form) != required
        or any(len(form.getlist(key)) != 1 for key in form)
        or request.query_params
    ):
        raise HTTPException(422, "provisional_request_fields_invalid", headers=NO_STORE)
    try:
        intake = form["intake_id"]
        if (
            not isinstance(intake, str)
            or not intake.isascii()
            or not intake.isdigit()
            or int(intake) <= 0
        ):
            raise ValueError
        expected_manifest_digest = _digest(form["expected_manifest_digest"])
        expected_context_fingerprint = (
            _digest(form["expected_context_fingerprint"]) if operation != "context" else None
        )
        expected_result_fingerprint = (
            _digest(form["expected_result_fingerprint"]) if operation == "export" else None
        )
        assumptions = (
            ProvisionalAssumptions.model_validate_json(form["assumptions"])
            if operation != "context"
            else None
        )
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(422, "provisional_request_invalid", headers=NO_STORE) from None
    source = dict(
        intake_id=int(intake),
        original=await _bytes(file),
        filename=file.filename or "",
        expected_manifest_digest=expected_manifest_digest,
    )
    try:
        if operation == "context":
            result = service.read_context(session, **source)
        else:
            result = service.evaluate(
                session,
                **source,
                assumptions=assumptions,
                expected_context_fingerprint=expected_context_fingerprint,
                expected_result_fingerprint=expected_result_fingerprint,
            )
    except service.ProvisionalStaleError as error:
        raise HTTPException(409, str(error), headers=NO_STORE) from None
    except MyBrokerError as error:
        raise HTTPException(
            404 if str(error) == "source_intake_not_found" else 409,
            str(error),
            headers=NO_STORE,
        ) from None
    headers = dict(NO_STORE)
    if operation == "export":
        headers["Content-Disposition"] = 'attachment; filename="broker-statement-provisional.json"'
    return Response(
        content=json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        media_type="application/json",
        headers=headers,
    )


@router.post("/context")
async def context(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(session_for_request),
):
    return await _read(request, session, file, "context")


@router.post("/evaluate")
async def evaluate(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(session_for_request),
):
    return await _read(request, session, file, "evaluate")


@router.post("/export")
async def export(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(session_for_request),
):
    return await _read(request, session, file, "export")
