"""Per-file month intake; successful siblings retain their own Save receipt."""

import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from hermes_finance.api.mybroker_import import _bytes
from hermes_finance.api.settings import session_for_request
from hermes_finance.api.uploads import BoundedUploadRoute
from hermes_finance.services import broker_sources, source_intake_pdf
from hermes_finance.services.source_monthly_returns import source_read_snapshot
from hermes_finance.statement_import.mybroker import MyBrokerError, digest

router = APIRouter(route_class=BoundedUploadRoute, prefix="/api/months", tags=["broker-sources"])


@router.get("/{month_id}/broker-sources")
def read(month_id: int, session: Session = Depends(session_for_request)):
    try:
        with source_read_snapshot(session):
            return broker_sources.read_sources(session, month_id)
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None


@router.post("/{month_id}/broker-sources")
async def upload(
    month_id: int,
    files: list[UploadFile] = File(...),
    request_id: str = Form(..., pattern=r"^[A-Za-z0-9_-]{1,64}$"),
    session: Session = Depends(session_for_request),
):
    try:
        broker_sources._month(session, month_id, editable=True)
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None
    results = []
    for index, file in enumerate(files):
        try:
            document = await _bytes(file)
            if document.startswith(b"%PDF-"):
                save = source_intake_pdf.save_descriptor
            elif document.lstrip().startswith((b"<", b"\xef\xbb\xbf<")):
                save = broker_sources.save_xml
            else:
                raise MyBrokerError("broker_source_type_unsupported")
            result = save(
                session,
                month_id,
                document,
                file.filename or "",
                digest(
                    [
                        "broker-sources",
                        month_id,
                        request_id,
                        hashlib.sha256(document).hexdigest(),
                        digest(file.filename or ""),
                    ]
                ),
            )
            results.append({"index": index, **result, "error": None})
        except (MyBrokerError, HTTPException) as error:
            session.rollback()
            code = str(error) if isinstance(error, MyBrokerError) else str(error.detail)
            message = (
                "Файл относится к другому периоду."
                if code == "broker_source_period_mismatch"
                else "Нужна XML-выписка или PDF отчёта о выплатах выбранного месяца."
                if code == "broker_source_type_unsupported"
                else "Не удалось прочитать PDF отчёта о выплатах."
                if code == "broker_source_pdf_unsupported"
                else "Не удалось определить период выплат PDF."
                if code == "broker_source_pdf_period_unknown"
                else "Не удалось сохранить файл; проверь его в подробностях."
            )
            results.append(
                {
                    "index": index,
                    "item": None,
                    "error": {
                        "code": code,
                        "message": message,
                    },
                }
            )
    return {"results": results, **broker_sources.read_sources(session, month_id)}
