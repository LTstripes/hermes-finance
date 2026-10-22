"""Local original-bound, journal-only commands. No financial endpoint here."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from hermes_finance.api.mybroker_import import _bytes
from hermes_finance.api.settings import session_for_request
from hermes_finance.api.uploads import BoundedUploadRoute
from hermes_finance.domain.source_intake import ConfirmIntake, ReviewIntake, SaveIntake
from hermes_finance.services import source_intake
from hermes_finance.statement_import.mybroker import MyBrokerError

router = APIRouter(route_class=BoundedUploadRoute, prefix="/intakes", tags=["source-intake"])


@router.get("")
def listing(
    reporting_month_id: int | None = None,
    include_unbound: bool = False,
    session: Session = Depends(session_for_request),
):
    try:
        return source_intake.list_intakes(session, reporting_month_id, include_unbound)
    except (MyBrokerError, ValueError, KeyError, TypeError):
        raise HTTPException(409, "source_intake_journal_invalid") from None


@router.post("")
async def save(
    file: UploadFile = File(...),
    intent: str = Form(...),
    session: Session = Depends(session_for_request),
):
    try:
        requested = SaveIntake.model_validate_json(intent)
        return source_intake.save_intake(
            session,
            document=await _bytes(file),
            filename=file.filename or "",
            **requested.model_dump(exclude={"contract_version"}),
        )
    except ValidationError:
        raise HTTPException(422, "source_intake_intent_invalid") from None
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None


@router.get("/{intake_id}")
def read(intake_id: int, session: Session = Depends(session_for_request)):
    try:
        return source_intake.read_intake(session, intake_id)
    except MyBrokerError as error:
        raise HTTPException(
            404 if str(error) == "source_intake_not_found" else 409, str(error)
        ) from None


@router.post("/{intake_id}/review-preview")
async def review(
    intake_id: int,
    file: UploadFile = File(...),
    intent: str = Form(...),
    session: Session = Depends(session_for_request),
):
    try:
        requested = ReviewIntake.model_validate_json(intent)
        return source_intake.preview_review(
            session, intake_id, await _bytes(file), file.filename or "", requested
        )
    except ValidationError:
        raise HTTPException(422, "source_intake_intent_invalid") from None
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None


async def _confirm(intake_id, file, confirmation, session, *, link):
    try:
        requested = ConfirmIntake.model_validate_json(confirmation)
        intent = ReviewIntake.model_validate(
            requested.model_dump(exclude={"request_id", "confirmation_digest"})
        )
        return source_intake.apply_review(
            session,
            intake_id,
            await _bytes(file),
            file.filename or "",
            intent,
            requested.request_id,
            requested.confirmation_digest,
            finance_link=link,
        )
    except ValidationError:
        raise HTTPException(422, "source_intake_confirmation_invalid") from None
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None


@router.post("/{intake_id}/decisions")
async def decisions(
    intake_id: int,
    file: UploadFile = File(...),
    confirmation: str = Form(...),
    session: Session = Depends(session_for_request),
):
    return await _confirm(intake_id, file, confirmation, session, link=False)


@router.post("/{intake_id}/finance-link")
async def finance_link(
    intake_id: int,
    file: UploadFile = File(...),
    confirmation: str = Form(...),
    session: Session = Depends(session_for_request),
):
    return await _confirm(intake_id, file, confirmation, session, link=True)
