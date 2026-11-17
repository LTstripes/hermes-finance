"""Local spending diary v1 API. Uploads never use month-fact writers."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import SpendingCategory, SpendingReview, SpendingRule
from hermes_finance.services import spending_diary as diary
from hermes_finance.spending_files import normalize

router = APIRouter(prefix="/api/spending", tags=["spending"])
SessionDep = Annotated[Session, Depends(session_for_request)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Choice(StrictRequest):
    fingerprint: str = Field(min_length=64, max_length=64)
    ordinal: int = Field(ge=1)
    action: Literal["expense", "refund", "not_spending", "separate", "duplicate"]
    category: str | None = Field(default=None, min_length=1, max_length=128)
    duplicate_of_id: int | None = Field(default=None, ge=1)


class Decision(StrictRequest):
    action: Literal["expense", "refund", "not_spending", "separate", "duplicate"]
    category: str | None = Field(default=None, min_length=1, max_length=128)
    duplicate_of_id: int | None = Field(default=None, ge=1)
    remember: bool = False


class RuleRequest(StrictRequest):
    scope: Literal["merchant", "bank_category"]
    key: str = Field(min_length=1, max_length=2000)
    action: Literal["expense", "refund", "not_spending"]
    category: str | None = Field(default=None, min_length=1, max_length=128)


class LinkRequest(StrictRequest):
    expense_entry_id: int = Field(ge=1)
    operation_ids: list[int] = Field(min_length=1)
    remember: bool = False


class CategoryRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=128)
    expense_type: Literal["mandatory", "comfortable", "other"] = "other"


def _call(session: Session, build, *, write: bool = False):
    try:
        if write:
            # Serialize validation + replacement under the same SQLite write reservation.
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            result = build()
            session.commit()
        else:
            with coherent_read_snapshot(session):
                result = build()
        return JSONResponse(jsonable_encoder(result), headers={"Cache-Control": "no-store"})
    except (ValueError, LookupError) as error:
        session.rollback()
        code = (
            409
            if isinstance(error, diary.PreviewChanged)
            else 404
            if isinstance(error, LookupError)
            else 422
        )
        return JSONResponse(
            {
                "error": {
                    "code": "preview_changed" if code == 409 else "spending_invalid",
                    "message": str(error),
                    "details": [],
                }
            },
            status_code=code,
        )


def _options(choices: str, skip_error_lines: str) -> tuple[list[dict], list[int]]:
    try:
        parsed = TypeAdapter(list[Choice]).validate_json(choices)
        skipped = TypeAdapter(list[int]).validate_json(skip_error_lines, strict=True)
    except ValidationError as error:
        raise ValueError("Неверный формат решений или номеров пропускаемых строк") from error
    return [c.model_dump() for c in parsed], skipped


@router.post("/uploads/preview")
async def preview(
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    source: Annotated[Literal["alfa_csv", "manual_md"], Form()],
    month: Annotated[str, Form()],
    choices: Annotated[str, Form()] = "[]",
    skip_error_lines: Annotated[str, Form()] = "[]",
):
    content = await file.read()

    def build():
        decisions, skipped = _options(choices, skip_error_lines)
        return diary.preview_upload(
            session,
            source=source,
            month=month,
            filename=file.filename or "",
            content=content,
            choices=decisions,
            skip_error_lines=skipped,
        )

    return _call(session, build)


@router.post("/uploads/apply")
async def apply(
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    source: Annotated[Literal["alfa_csv", "manual_md"], Form()],
    month: Annotated[str, Form()],
    preview_token: Annotated[str, Form()],
    confirm_disappearance: Annotated[bool, Form()] = False,
    choices: Annotated[str, Form()] = "[]",
    skip_error_lines: Annotated[str, Form()] = "[]",
):
    content = await file.read()

    def build():
        decisions, skipped = _options(choices, skip_error_lines)
        return diary.apply_upload(
            session,
            source=source,
            month=month,
            filename=file.filename or "",
            content=content,
            preview_token=preview_token,
            confirm_disappearance=confirm_disappearance,
            choices=decisions,
            skip_error_lines=skipped,
        )

    return _call(session, build, write=True)


@router.get("/months")
def months(session: SessionDep):
    return _call(session, lambda: diary.list_months(session))


@router.get("/months/{month}")
def month_spending(month: str, session: SessionDep):
    return _call(session, lambda: diary.read_month(session, month))


@router.put("/operations/{operation_id}/decision")
def decision(operation_id: int, request: Decision, session: SessionDep):
    return _call(
        session,
        lambda: diary.decide_operation(session, operation_id, **request.model_dump()),
        write=True,
    )


@router.get("/rules")
def rules(session: SessionDep):
    return _call(
        session,
        lambda: [
            dict(id=r.id, scope=r.scope, key=r.key, action=r.action, category_id=r.category_id)
            for r in diary._objects(session, SpendingRule)
        ],
    )


@router.put("/rules")
def rule(request: RuleRequest, session: SessionDep):
    return _call(
        session, lambda: dict(id=diary.set_rule(session, **request.model_dump())), write=True
    )


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, session: SessionDep):
    def build():
        rule = session.get(SpendingRule, rule_id)
        if rule is None:
            raise LookupError("Правило не найдено")
        session.delete(rule)
        return {"deleted": True}

    return _call(session, build, write=True)


@router.post("/links")
def link(request: LinkRequest, session: SessionDep):
    return _call(
        session, lambda: dict(id=diary.create_link(session, **request.model_dump())), write=True
    )


@router.delete("/links/{link_id}")
def unlink(link_id: int, session: SessionDep):
    def build():
        diary.delete_link(session, link_id)
        return {"deleted": True}

    return _call(session, build, write=True)


@router.post("/month-expenses/{expense_entry_id}/separate")
def separate_expense(expense_entry_id: int, session: SessionDep):
    def build():
        diary.separate_month_expense(session, expense_entry_id)
        return {"separate": True}

    return _call(session, build, write=True)


@router.post("/reviews/{review_id}/acknowledge")
def acknowledge(review_id: int, session: SessionDep):
    def build():
        review = session.get(SpendingReview, review_id)
        if review is None:
            raise LookupError("Исключение не найдено")
        review.resolved = True
        session.flush()
        return diary.read_month(session, review.month)

    return _call(session, build, write=True)


@router.get("/categories")
def categories(session: SessionDep):
    return _call(
        session,
        lambda: [
            dict(id=c.id, name=c.name, expense_type=c.expense_type)
            for c in diary._objects(session, SpendingCategory)
        ],
    )


@router.put("/categories/{category_id}")
def category(category_id: int, request: CategoryRequest, session: SessionDep):
    def build():
        if not request.name.strip():
            raise ValueError("Введите имя категории")
        obj = session.get(SpendingCategory, category_id)
        if obj is None:
            raise LookupError("Категория не найдена")
        if any(
            c.id != obj.id and normalize(request.name) in {c.name_key, normalize(c.name)}
            for c in diary._objects(session, SpendingCategory)
        ):
            raise ValueError(
                "Категория с таким именем уже существует; используйте соответствие категорий"
            )
        obj.name, obj.expense_type = request.name.strip(), request.expense_type
        # name_key is the immutable source alias; rename retains original bank/manual matching.
        return {"id": obj.id, "name": obj.name, "expense_type": obj.expense_type}

    return _call(session, build, write=True)
