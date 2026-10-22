"""Separate read-only statement return API, preview and parity JSON export."""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from hermes_finance.api.mybroker_import import _bytes
from hermes_finance.api.settings import session_for_request
from hermes_finance.api.uploads import BoundedUploadRoute
from hermes_finance.domain.broker_statement_return import BrokerStatementReturn
from hermes_finance.services.broker_statement_return import read_statement_return, statement_sources
from hermes_finance.statement_import.mybroker import MyBrokerError

router = APIRouter(
    route_class=BoundedUploadRoute,
    prefix="/api/broker-statement-returns",
    tags=["broker-statement-returns"],
)


@router.get("/sources")
def sources(account_id: int = Query(gt=0), session: Session = Depends(session_for_request)):
    return statement_sources(session, account_id)


def _read(session, request_id, account_id, expected_fingerprint=None, **kwargs):
    try:
        return read_statement_return(
            session,
            request_id=request_id,
            account_id=account_id,
            expected_fingerprint=expected_fingerprint,
            **kwargs,
        )
    except MyBrokerError as error:
        raise HTTPException(404, str(error)) from None


@router.get("", response_model=BrokerStatementReturn)
def read(
    request_id: str,
    account_id: int = Query(gt=0),
    expected_fingerprint: str | None = Query(default=None, pattern=r"^[0-9a-f]{64}$"),
    session: Session = Depends(session_for_request),
):
    return _read(session, request_id, account_id, expected_fingerprint)


@router.post("/preview", response_model=BrokerStatementReturn)
async def preview(
    request_id: str = Form(...),
    account_id: int = Form(gt=0),
    file: UploadFile = File(...),
    session: Session = Depends(session_for_request),
):
    return _read(
        session, request_id, account_id, original=await _bytes(file), filename=file.filename or ""
    )


@router.get("/export")
def export(
    request_id: str,
    account_id: int = Query(gt=0),
    expected_fingerprint: str | None = Query(default=None, pattern=r"^[0-9a-f]{64}$"),
    session: Session = Depends(session_for_request),
):
    result = _read(session, request_id, account_id, expected_fingerprint)
    return Response(
        content=json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="broker-statement-return.json"'},
    )
