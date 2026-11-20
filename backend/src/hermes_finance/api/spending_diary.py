"""Local spending diary v1 API. Uploads never use month-fact writers."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import (
    SpendingCategory,
    SpendingOperation,
    SpendingReview,
    SpendingRule,
    SpendingUpload,
)
from hermes_finance.services import spending_diary as diary
from hermes_finance.services import spending_insights as insights
from hermes_finance.services import spending_payment_rules as payments
from hermes_finance.services.spending_previews import PreviewStore
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
    duplicate_of_id: int | None = None
    remember: bool = False


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


class CategoryPatch(StrictRequest):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    expense_type: Literal["mandatory", "comfortable", "other"] | None = None


class MergeRequest(StrictRequest):
    target_id: int = Field(ge=1)


class SavedChoice(StrictRequest):
    id: str
    action: Literal[
        "expense",
        "refund",
        "not_spending",
        "separate",
        "duplicate",
        "link",
        "unlink",
        "acknowledge",
    ]
    category: str | None = Field(default=None, min_length=1, max_length=128)
    duplicate_of_id: int | None = Field(default=None, ge=1)
    operation_ids: list[int] = Field(default_factory=list)
    remember: bool = False


class SavedDecisions(StrictRequest):
    decisions: list[SavedChoice]


class PreviewLink(StrictRequest):
    expense_entry_id: int = Field(ge=1)
    action: Literal["link", "separate"]
    operation_ids: list[int] = Field(default_factory=list)
    remember: bool = False


class PreviewDecisions(StrictRequest):
    choices: list[Choice] = Field(default_factory=list)
    entry_links: list[PreviewLink] = Field(default_factory=list)
    skip_error_lines: list[int] | None = None


class ApplyPreview(StrictRequest):
    confirm_removal: bool = False
    skip_unreadable_manual: bool = False


def _private_response(session: Session, result):
    values = {
        value
        for row in diary._objects(session, SpendingOperation)
        for value in (row.account, row.card)
        if value
    }
    values.update(
        upload.account for upload in diary._objects(session, SpendingUpload) if upload.account
    )
    values.update(session.info.get("spending_redactions", set()))

    def scrub(value):
        if isinstance(value, str):
            for secret in sorted(values, key=len, reverse=True):
                value = value.replace(secret, "··" + secret[-4:])
            return value
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(jsonable_encoder(result))


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
        return JSONResponse(
            _private_response(session, result), headers={"Cache-Control": "no-store"}
        )
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
                    "stale": code == 409,
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
def months(
    session: SessionDep, until: str | None = None, count: int = Query(default=12, ge=1, le=1200)
):
    return _call(session, lambda: diary.list_months(session, until=until, count=count))


@router.get("/months/{month}")
@router.get("/month/{month}")
def month_spending(month: str, session: SessionDep):
    return _call(session, lambda: diary.read_month(session, month))


@router.get("/operations")
def operation_list(
    month: str,
    session: SessionDep,
    category: int | None = None,
    source: str | None = None,
    limit: int = Query(default=50, ge=1, le=100000),
):
    return _call(
        session,
        lambda: insights.operations(
            session,
            diary.read_month_base(session, month),
            category=category,
            source=source,
            limit=limit,
        ),
    )


@router.get("/categories/{category_id}/history")
def category_history(
    category_id: int,
    session: SessionDep,
    until: str | None = None,
    count: int = Query(default=12, ge=1, le=1200),
):
    return _call(
        session, lambda: insights.history(session, until=until, count=count, category=category_id)
    )


@router.get("/exceptions")
def exceptions(month: str, session: SessionDep):
    return _call(session, lambda: insights.exceptions(session, month))


@router.post("/exceptions/decisions")
def exceptions_decisions(month: str, request: SavedDecisions, session: SessionDep):
    return _call(
        session,
        lambda: insights.decide_exceptions(
            session, month, [decision.model_dump() for decision in request.decisions]
        ),
        write=True,
    )


@router.get("/manual-template")
def manual_template(month: str):
    try:
        diary.month_bounds(month)
    except ValueError:
        return JSONResponse({"error": {"code": "invalid_month"}}, status_code=422)
    body = f"---\nfinance_expenses: 1\nmonth: {month}\n---\n\n| Дата | Сумма | Категория | Описание | Оплата |\n|---|---|---|---|---|\n"
    return Response(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="finance-expenses-{month}.md"',
            "Cache-Control": "no-store",
        },
    )


def _store(request: Request) -> PreviewStore:
    if not hasattr(request.app.state, "spending_previews"):
        request.app.state.spending_previews = PreviewStore()
    return request.app.state.spending_previews


@router.post("/preview")
async def screen_preview(
    request: Request,
    session: SessionDep,
    month: Annotated[str, Form()],
    statement: Annotated[UploadFile | None, File()] = None,
    manual: Annotated[UploadFile | None, File()] = None,
):
    files = []
    for source, file in (("alfa_csv", statement), ("manual_md", manual)):
        if file is not None:
            files.append(
                dict(source=source, filename=file.filename or "", content=await file.read())
            )
    return _call(session, lambda: _store(request).create(session, month, files))


@router.get("/preview/{preview_id}")
def get_preview(preview_id: str, request: Request, session: SessionDep):
    return _call(session, lambda: _store(request).read(session, preview_id))


@router.post("/preview/{preview_id}/decisions")
def preview_decisions(
    preview_id: str, body: PreviewDecisions, request: Request, session: SessionDep
):
    return _call(
        session,
        lambda: _store(request).decide(
            session,
            preview_id,
            [choice.model_dump() for choice in body.choices],
            [link.model_dump() for link in body.entry_links],
            body.skip_error_lines,
        ),
    )


@router.post("/preview/{preview_id}/apply")
def apply_preview(preview_id: str, body: ApplyPreview, request: Request, session: SessionDep):
    return _call(
        session, lambda: _store(request).apply(session, preview_id, **body.model_dump()), write=True
    )


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
@router.delete("/entry-links/{link_id}")
def unlink(link_id: int, session: SessionDep):
    def build():
        diary.delete_link(session, link_id)
        return {"deleted": True}

    return _call(session, build, write=True)


@router.get("/entry-links")
def entry_links(session: SessionDep, month: str | None = None):
    def build():
        months = [month] if month is not None else diary.known_months(session)
        return [
            dict(month=value, **link)
            for value in months
            for link in insights._entry_links(
                session, diary.read_month_base(session, value), include_unconfirmed=True
            )
        ]

    return _call(session, build)


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


@router.patch("/categories/{category_id}")
def patch_category(category_id: int, request: CategoryPatch, session: SessionDep):
    def build():
        obj = session.get(SpendingCategory, category_id)
        if obj is None:
            raise LookupError("Категория не найдена")
        name = request.name.strip() if request.name is not None else obj.name
        if not name or any(
            c.id != obj.id and normalize(name) in {c.name_key, normalize(c.name)}
            for c in diary._objects(session, SpendingCategory)
        ):
            raise ValueError("Введите уникальное имя категории")
        obj.name = name
        if request.expense_type is not None:
            obj.expense_type = request.expense_type
        session.flush()
        return dict(id=obj.id, name=obj.name, expense_type=obj.expense_type)

    return _call(session, build, write=True)


@router.post("/categories/{category_id}/merge")
def merge_category(category_id: int, request: MergeRequest, session: SessionDep):
    return _call(
        session,
        lambda: insights.merge_category(session, category_id, request.target_id),
        write=True,
    )


PaymentSource = Literal["alfa", "cash", "sber", "manual_other", "month_entries"]


class PaymentRuleRequest(StrictRequest):
    token: str = Field(min_length=64, max_length=64)
    note: str = Field(max_length=2000)
    mandatory_override: bool | None
    repeat: bool
    period_months: int | None = Field(ge=1, le=120)
    next_due: date | None
    amount: str | None = Field(pattern=r"^(0|[1-9][0-9]{0,13})(\.[0-9]{1,2})?$")


class PaymentReattachRequest(StrictRequest):
    token: str = Field(min_length=64, max_length=64)
    rule_id: int = Field(ge=1)
    version: int = Field(ge=1)


@router.get("/payment-rules")
def payment_rules(session: SessionDep, month: str):
    return _call(session, lambda: payments.payment_rules_for_budget(session, month))


@router.get("/payment-rules/{source}/{operation_id}")
def payment_card(session: SessionDep, source: PaymentSource, operation_id: int, month: str):
    return _call(session, lambda: payments.card(session, month, source, operation_id))


@router.put("/payment-rules/{source}/{operation_id}")
def save_payment_card(
    session: SessionDep,
    source: PaymentSource,
    operation_id: int,
    month: str,
    body: PaymentRuleRequest,
):
    return _call(
        session,
        lambda: payments.save(session, month, source, operation_id, body.model_dump()),
        write=True,
    )


@router.post("/payment-rules/{source}/{operation_id}/reattach")
def reattach_payment_card(
    session: SessionDep,
    source: PaymentSource,
    operation_id: int,
    month: str,
    body: PaymentReattachRequest,
):
    return _call(
        session,
        lambda: payments.reattach(session, month, source, operation_id, **body.model_dump()),
        write=True,
    )
