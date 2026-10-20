"""Explicit local user choices for provisional saved source money rows."""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.source_money_classifications import MoneyClassification
from hermes_finance.services.source_money_classifications import choose_classification
from hermes_finance.statement_import.mybroker import MyBrokerError

router = APIRouter(prefix="/api/source-intakes", tags=["source-intake"])


class MoneyClassificationChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: MoneyClassification


class MoneyClassificationResponse(MoneyClassificationChoice):
    intake_id: int
    source_reference: str
    date: date
    amount_kopecks: int | None
    currency: str
    operation: str
    narrative: str
    origin: Literal["user_choice"]
    status: Literal["confirmed"]
    created_at: datetime
    updated_at: datetime


@router.put("/{intake_id}/money-classifications/{ref}", response_model=MoneyClassificationResponse)
def put_money_classification(
    intake_id: int,
    ref: str,
    choice: MoneyClassificationChoice,
    response: Response,
    session: Session = Depends(session_for_request),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return choose_classification(session, intake_id, ref, choice.classification)
    except MyBrokerError as error:
        raise HTTPException(
            404
            if str(error) in {"source_intake_not_found", "money_classification_not_found"}
            else 409,
            str(error),
        ) from None
