"""Monthly comments API (D06)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.services.comments import (
    create_monthly_comment,
    delete_monthly_comment,
    get_monthly_comment,
    list_monthly_comments,
    move_monthly_comment,
    update_monthly_comment,
)

router = APIRouter(prefix="/api/comments", tags=["comments"])


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    text: str = Field(min_length=1, max_length=4000)


class CommentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)


class CommentMove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_position: int = Field(ge=1)


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporting_month_id: int
    position: int
    text: str


def _response(comment: object) -> CommentResponse:
    return CommentResponse(
        id=comment.id,
        reporting_month_id=comment.reporting_month_id,
        position=comment.position,
        text=comment.text,
    )


@router.get("", response_model=list[CommentResponse])
def list_comments(
    month_id: int = Query(...),
    session: Session = Depends(session_for_request),
) -> list[CommentResponse]:
    return [_response(item) for item in list_monthly_comments(session, month_id)]


@router.post("", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
def create_comment(
    payload: CommentCreate,
    session: Session = Depends(session_for_request),
) -> CommentResponse:
    comment = create_monthly_comment(
        session,
        reporting_month_id=payload.reporting_month_id,
        text=payload.text,
    )
    return _response(comment)


@router.get("/{comment_id}", response_model=CommentResponse)
def get_comment(
    comment_id: int,
    session: Session = Depends(session_for_request),
) -> CommentResponse:
    return _response(get_monthly_comment(session, comment_id))


@router.patch("/{comment_id}", response_model=CommentResponse)
def update_comment(
    comment_id: int,
    payload: CommentUpdate,
    session: Session = Depends(session_for_request),
) -> CommentResponse:
    comment = update_monthly_comment(session, comment_id, text=payload.text)
    return _response(comment)


@router.post("/{comment_id}/move", response_model=CommentResponse)
def move_comment(
    comment_id: int,
    payload: CommentMove,
    session: Session = Depends(session_for_request),
) -> CommentResponse:
    comment = move_monthly_comment(session, comment_id, new_position=payload.new_position)
    return _response(comment)


@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    comment_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_monthly_comment(session, comment_id)
