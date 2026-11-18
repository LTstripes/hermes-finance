"""Bounded process-local previews; bytes remain private and never write on preview."""

from __future__ import annotations

import copy
from time import monotonic
from uuid import uuid4

from sqlalchemy.orm import Session

from hermes_finance.services import spending_diary as diary
from hermes_finance.services import spending_insights as insights
from hermes_finance.spending_files import FileProblem, digest, month_bounds

TTL_SECONDS = 1800
MAX_PREVIEWS = 16


class PreviewStore:
    def __init__(self):
        self.items = {}

    def get(self, preview_id: str) -> dict:
        item = self.items.get(preview_id)
        if item is None or monotonic() - item["created"] > TTL_SECONDS:
            self.items.pop(preview_id, None)
            raise LookupError("Preview истёк: загрузите файлы снова")
        return item

    def create(self, session: Session, month: str, files: list[dict]) -> dict:
        month_bounds(month)
        if not files:
            raise ValueError("Выберите хотя бы один файл")
        if sum(len(file["content"]) for file in files) > 16 * 1024 * 1024:
            raise ValueError("Размер файлов превышает 16 MiB")
        while len(self.items) >= MAX_PREVIEWS:
            self.items.pop(next(iter(self.items)))
        item = dict(
            id=uuid4().hex,
            month=month,
            files=files,
            choices=[],
            link_choices=[],
            skipped=[],
            created=monotonic(),
            state=diary._state_token(session),
        )
        result = self.build(session, item)
        item["last"] = result
        item["redactions"] = set(session.info.get("spending_redactions", set()))
        self.items[item["id"]] = item
        return result

    def read(self, session: Session, preview_id: str) -> dict:
        item = self.get(preview_id)
        session.info.setdefault("spending_redactions", set()).update(item["redactions"])
        stale = item["state"] != diary._state_token(session)
        return {
            **copy.deepcopy(item["last"]),
            "stale": stale,
            "applicable": item["last"]["applicable"] and not stale,
        }

    def decide(
        self,
        session: Session,
        preview_id: str,
        choices: list[dict],
        link_choices: list[dict],
        skipped: list[int] | None,
    ) -> dict:
        item = copy.deepcopy(self.get(preview_id))
        if item["state"] != diary._state_token(session):
            raise diary.PreviewChanged("Данные изменились: получите новое preview")
        existing = {diary._identity(choice): choice for choice in item["choices"]}
        for choice in choices:
            existing[diary._identity(choice)] = choice
        item["choices"] = list(existing.values())
        links = {choice["expense_entry_id"]: choice for choice in item["link_choices"]}
        links.update({choice["expense_entry_id"]: choice for choice in link_choices})
        item["link_choices"] = list(links.values())
        if skipped is not None:
            item["skipped"] = skipped
        result = self.build(session, item)
        item["last"] = result
        self.items[preview_id] = item
        return result

    def build(self, session: Session, item: dict) -> dict:
        month = item["month"]
        before = diary.read_month_base(session, month)
        projected = diary._month_rows(session, month)
        plans, errors, overrides = [], [], []
        choices_left = {diary._identity(choice): choice for choice in item["choices"]}
        for file in item["files"]:
            # Identity is known only after parsing; first project without new decisions.
            try:
                initial = diary._plan(
                    session,
                    file["source"],
                    month,
                    file["filename"],
                    file["content"],
                    [],
                    item["skipped"] if file["source"] == "manual_md" else [],
                    current_rows=projected,
                )
            except FileProblem as error:
                errors.append(
                    dict(
                        file="statement" if file["source"] == "alfa_csv" else "manual",
                        code=error.code,
                        **{"month": month, **error.parameters},
                    )
                )
                continue
            identities = {diary._identity(row) for row in initial["incoming"]}
            choices = [
                choices_left.pop(identity)
                for identity in list(choices_left)
                if identity in identities
            ]
            plan = (
                diary._plan(
                    session,
                    file["source"],
                    month,
                    file["filename"],
                    file["content"],
                    choices,
                    item["skipped"] if file["source"] == "manual_md" else [],
                    current_rows=projected,
                )
                if choices
                else initial
            )
            errors.extend(plan["public"]["file_errors"])
            # A rejected source must not affect the projected totals, replacements
            # or the valid file's duplicate candidates.
            if not plan["public"]["applicable"]:
                continue
            for row in plan["incoming"]:
                if row["id"] is None:
                    row["id"] = -int(digest(diary._identity(row))[:13], 16)
            projected = plan["projected"]
            plans.append(plan)
            for account, span in plan["scopes"].items():
                period = plan["period"]
                overrides.append(
                    dict(
                        source=file["source"],
                        account=account,
                        period_from=period[0] if period else None,
                        period_to=period[1] if period else None,
                        date_from=span[0],
                        date_to=span[1],
                    )
                )
        if choices_left:
            raise ValueError("Решение относится к отсутствующей строке")
        after = diary._read(
            session,
            month,
            projected,
            loaded=True,
            link_choices=item["link_choices"],
            rule_overrides=diary._preview_rules(session, projected, item["choices"]),
        )
        after.update(insights.coverage_status(session, month, overrides))
        final_rows = diary._effective(
            session, projected, diary._preview_rules(session, projected, item["choices"])
        )
        for plan in plans:
            for scope, account in zip(plan["public"]["sets"], plan["scopes"], strict=True):
                source = (
                    next(row["source"] for row in plan["projected"] if row["account"] == account)
                    if plan["incoming"]
                    else "manual_md"
                )
                scope["total_after"] = insights.money(
                    sum(
                        row["amount_kopecks"]
                        for row in final_rows
                        if row["source"] == source and row["account"] == account and row["included"]
                    )
                )
        lost = [
            receipt for plan in plans for receipt in plan["public"]["decisions_not_transferred"]
        ]
        if lost:
            after["total_kopecks"] = None
        exceptions = insights.exception_views(session, after)
        for exception in exceptions:
            if exception["carried_over_failed"]:
                exception["previous_decision"] = next(
                    (
                        receipt
                        for receipt in lost
                        if receipt.get("fingerprint") == exception.get("fingerprint")
                    ),
                    exception.get("previous_decision"),
                )
                exception["previous_decisions"] = lost
        technical = [
            row
            for row in after["operations"]
            if row["kind"] in {"transfer", "interest", "repayment"}
        ]
        outside = [plan["public"]["out_of_month"] for plan in plans]
        removed = [row for plan in plans for row in plan["public"]["disappearing"]]
        result = dict(
            preview_id=item["id"],
            month=month,
            stale=False,
            applicable=bool(plans),
            total_before=insights.money(before["total_kopecks"]) if before["loaded"] else None,
            total_after=insights.money(after["total_kopecks"]),
            sets=[scope for plan in plans for scope in plan["public"]["sets"]],
            exceptions=exceptions,
            technical=dict(count=len(technical), items=technical),
            processing=dict(
                count=sum(
                    row["included"] and row["status"] == "В обработке"
                    for row in after["operations"]
                ),
                amount=insights.money(after["pending_kopecks"]),
            ),
            coverage=after["coverage"],
            file_errors=errors,
            out_of_month={
                "count": sum(span["count"] for span in outside),
                "from": min((span["from"] for span in outside if span["from"]), default=None),
                "to": max((span["to"] for span in outside if span["to"]), default=None),
            },
            blocking=dict(
                needs_removal_confirmation=bool(removed),
                unreadable_manual_rows=[
                    error["line"]
                    for error in errors
                    if error["file"] == "manual"
                    and "line" in error
                    and error["line"] not in item["skipped"]
                ],
            ),
            operations=after["operations"],
            entry_links=insights._entry_links(session, after),
            added=sum(len(plan["public"]["added"]) for plan in plans),
            changed=sum(len(plan["public"]["changed"]) for plan in plans),
            removed=len(removed),
        )
        return result

    def apply(
        self,
        session: Session,
        preview_id: str,
        *,
        confirm_removal: bool,
        skip_unreadable_manual: bool,
    ) -> dict:
        item = self.get(preview_id)
        if item["state"] != diary._state_token(session):
            raise diary.PreviewChanged("Данные изменились: получите новое preview")
        # Work on a copy so failed/rolled-back applies leave the preview intact.
        item = copy.deepcopy(item)
        if skip_unreadable_manual:
            item["skipped"] = [
                error["line"]
                for error in item["last"]["file_errors"]
                if error["file"] == "manual" and "line" in error
            ]
        public = self.build(session, item)
        if not public["applicable"]:
            raise ValueError("Исправьте ошибки файла или подтвердите пропуск строк ручного файла")
        if public["removed"] and not confirm_removal:
            raise ValueError("Подтвердите исчезновение операций")
        identities = {row["id"]: diary._identity(row) for row in public["operations"]}

        def actual_id(operation_id):
            if operation_id is None or operation_id > 0:
                return operation_id
            identity = identities.get(operation_id)
            found = next(
                (
                    row["id"]
                    for row in diary._month_rows(session, item["month"])
                    if diary._identity(row) == identity
                ),
                None,
            )
            if found is None:
                raise ValueError("Кандидат preview больше не найден")
            return found

        applicable_kinds = {scope["kind"] for scope in public["sets"]}
        applied_choices = set()
        for file in item["files"]:
            kind = "statement" if file["source"] == "alfa_csv" else "manual"
            if kind not in applicable_kinds:
                continue
            initial = diary._plan(
                session,
                file["source"],
                item["month"],
                file["filename"],
                file["content"],
                [],
                item["skipped"] if file["source"] == "manual_md" else [],
            )
            keys = {diary._identity(row) for row in initial["incoming"]}
            choices = [
                {**choice, "duplicate_of_id": actual_id(choice.get("duplicate_of_id"))}
                for choice in item["choices"]
                if diary._identity(choice) in keys
            ]
            applied_choices.update(diary._identity(choice) for choice in choices)
            kwargs = dict(
                source=file["source"],
                month=item["month"],
                filename=file["filename"],
                content=file["content"],
                choices=choices,
                skip_error_lines=item["skipped"] if file["source"] == "manual_md" else [],
            )
            fresh = diary.preview_upload(session, **kwargs)
            diary.apply_upload(
                session,
                **kwargs,
                preview_token=fresh["preview_token"],
                confirm_disappearance=confirm_removal,
            )
        for choice in item["link_choices"]:
            if choice["action"] == "separate":
                diary.separate_month_expense(session, choice["expense_entry_id"])
            else:
                diary.create_link(
                    session,
                    choice["expense_entry_id"],
                    [actual_id(i) for i in choice["operation_ids"]],
                    remember=choice.get("remember", False),
                )
        for choice in item["choices"]:
            if choice.get("remember") and diary._identity(choice) in applied_choices:
                row = next(
                    row
                    for row in diary._month_rows(session, item["month"])
                    if diary._identity(row) == diary._identity(choice)
                )
                diary.decide_operation(
                    session,
                    row["id"],
                    action=choice["action"],
                    category=choice.get("category"),
                    duplicate_of_id=actual_id(choice.get("duplicate_of_id")),
                    remember=True,
                )
        return dict(
            added=public["added"],
            changed=public["changed"],
            removed=public["removed"],
            month=diary.read_month(session, item["month"]),
        )
