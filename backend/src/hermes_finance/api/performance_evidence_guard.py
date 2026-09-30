"""Optional optimistic guard for the Owner preparation client, without stored revisions."""

import hashlib
import json

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    CashBalance,
    CashBoundaryCoverage,
    ExternalFlow,
    ExternalTransferLink,
    ExternalTransferReconciliationEvidence,
    InKindBoundaryCoverage,
    InKindMovement,
    ReportingMonth,
)

# Conservative catalogue-wide conflict detection: no financial interpretation.
# Include partner legs and old intervals, not merely the rows visible in a form.
_SOURCES = (
    Account,
    AccountPerformanceScopeMembership,
    ReportingMonth,
    CashBalance,
    ExternalFlow,
    ExternalTransferLink,
    ExternalTransferReconciliationEvidence,
    CashBoundaryCoverage,
    InKindBoundaryCoverage,
    InKindMovement,
)


def evidence_signature(session: Session) -> str:
    digest = hashlib.sha256(b"performance-preparation-v1")
    for model in _SOURCES:
        table = model.__table__
        digest.update(table.name.encode())
        for row in session.execute(select(table).order_by(table.c.id)):
            digest.update(json.dumps(tuple(row), default=str, ensure_ascii=True).encode())
    return digest.hexdigest()


def preparation_session(
    request: Request,
    x_performance_evidence: str | None = Header(default=None),
    session: Session = Depends(session_for_request),
) -> Session:
    """Compare after reserving SQLite's writer, held through the canonical commit.

    Legacy consumers without the optional header keep their existing contract.
    The preparation UI always sends the token captured with its displayed ledger.
    """
    if request.method in {"POST", "PATCH", "DELETE", "PUT"} and x_performance_evidence is not None:
        session.execute(text("UPDATE reporting_months SET status = status WHERE 0"))
        session.expire_all()
        if x_performance_evidence != evidence_signature(session):
            session.rollback()
            raise HTTPException(409, "Preparation evidence changed; reread before saving")
    return session
