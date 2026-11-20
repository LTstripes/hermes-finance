"""Local spending reserve plan API."""

from fastapi import APIRouter
from pydantic import Field

from hermes_finance.api.spending_diary import SessionDep, StrictRequest, _call
from hermes_finance.services import spending_reserve as reserve

router = APIRouter(prefix="/api/spending/reserve", tags=["spending"])


class Save(StrictRequest):
    expected_revision: int = Field(ge=0)
    plan: reserve.Plan


@router.get("")
def get_reserve(session: SessionDep):
    return _call(session, lambda: reserve.read(session))


@router.put("")
def update_reserve(session: SessionDep, body: Save):
    def write():
        reserve.save_plan(session, body.expected_revision, body.plan)
        return reserve.read(session)

    return _call(session, write, write=True)
