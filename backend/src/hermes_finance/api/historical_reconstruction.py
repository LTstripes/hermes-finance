"""Owner-local H0 Preview from persisted evidence only; no financial Apply."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.services.historical_reconstruction import preview_historical_reconstruction
from hermes_finance.statement_import.mybroker import MyBrokerError

router = APIRouter(prefix="/api/historical-reconstruction", tags=["historical-reconstruction"])


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_ids: list[int] = Field(min_length=1, max_length=100)
    requested_from: date
    requested_to: date


@router.post("/preview")
def preview(request: Selection, session: Session = Depends(session_for_request)):
    try:
        return preview_historical_reconstruction(session, **request.model_dump())
    except MyBrokerError as error:
        raise HTTPException(422, str(error)) from None
