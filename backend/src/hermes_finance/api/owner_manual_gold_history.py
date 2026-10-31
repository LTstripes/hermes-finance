"""Gold-only Owner evidence commands; no monthly financial writer."""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.services.owner_manual_gold_history import (
    VERSION,
    GoldHistoryConfirmation,
    GoldHistoryError,
    GoldHistoryIntent,
    apply_gold_history,
    preview_gold_history,
    read_gold_histories,
    read_gold_history,
    read_gold_history_receipt,
)

PREFIX = "/api/owner-manual-gold-history"


class GoldHistoryNoStoreMiddleware:
    """Cover successful and rejected private-source responses, including 405."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        private = scope["type"] == "http" and (
            scope["path"] == PREFIX or scope["path"].startswith(PREFIX + "/")
        )

        async def private_send(message):
            if private and message["type"] == "http.response.start":
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"cache-control"
                ]
                message["headers"] = [*headers, (b"cache-control", b"no-store")]
            await send(message)

        await self.app(scope, receive, private_send)


def _query_shape(request: Request):
    allowed = (
        {"account_id", "instrument_id"}
        if (request.method == "GET" and request.url.path == PREFIX)
        else set()
    )
    if any(
        key not in allowed or len(request.query_params.getlist(key)) != 1
        for key in request.query_params
    ):
        raise HTTPException(422, "unknown_or_duplicate_query_parameter")


router = APIRouter(prefix=PREFIX, tags=["owner-gold-history"], dependencies=[Depends(_query_shape)])


@router.post("/preview")
def preview(request: GoldHistoryIntent, session: Session = Depends(session_for_request)):
    try:
        return preview_gold_history(session, request)
    except (GoldHistoryError, ValidationError) as error:
        raise HTTPException(422, str(error)) from None


@router.post("/apply")
def apply(request: GoldHistoryConfirmation, session: Session = Depends(session_for_request)):
    try:
        return apply_gold_history(session, request)
    except GoldHistoryError as error:
        raise HTTPException(409, str(error)) from None


@router.get("")
def read_all(
    account_id: int | None = Query(default=None, gt=0),
    instrument_id: int | None = Query(default=None, gt=0),
    session: Session = Depends(session_for_request),
):
    return {
        "contract_version": VERSION,
        "histories": read_gold_histories(
            session, account_id=account_id, instrument_id=instrument_id
        ),
    }


@router.get("/receipts/{request_id}")
def read_receipt(
    request_id: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"),
    session: Session = Depends(session_for_request),
):
    try:
        return read_gold_history_receipt(session, request_id)
    except GoldHistoryError as error:
        raise HTTPException(404, str(error)) from None


@router.get("/{history_id}")
def read_one(history_id: int = Path(gt=0), session: Session = Depends(session_for_request)):
    try:
        return read_gold_history(session, history_id)
    except GoldHistoryError as error:
        raise HTTPException(404, str(error)) from None
