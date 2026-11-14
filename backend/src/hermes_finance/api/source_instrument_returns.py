"""Read-only provisional instrument returns for one native source account."""

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.returns_view import AccountLink
from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.instrument_return import AccountReconciliation, InstrumentEvent
from hermes_finance.services.source_instrument_returns import (
    InstrumentIncome,
    InstrumentReturnGap,
    ReturnBreakdown,
    SourceInstrumentReturn,
    read_instrument_returns,
)

router = APIRouter(prefix="/api/source-returns", tags=["source-returns"])


@dataclass(frozen=True)
class NamedSourceInstrumentReturn(SourceInstrumentReturn):
    short_name: str | None = None


class SourceInstrumentReturnsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_account: str
    account_link: AccountLink | None
    native_source_account: str | None
    unresolved_events: tuple[InstrumentEvent, ...]
    account_reconciliation_events: tuple[InstrumentEvent, ...]
    reconciliation: AccountReconciliation | None
    breakdown: ReturnBreakdown | None
    instruments: tuple[NamedSourceInstrumentReturn, ...]
    income: tuple[InstrumentIncome, ...]
    gaps: tuple[InstrumentReturnGap, ...]
    authority: Literal["provisional"]
    financial_authority: Literal["none"]
    currency: Literal["RUB"]


@router.get("/instruments", response_model=SourceInstrumentReturnsResponse)
def instrument_returns(
    response: Response,
    source_account: Annotated[str, Query(min_length=1, max_length=256, pattern=r"^\S+$")],
    isin: Annotated[str | None, Query(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")] = None,
    opening_date: date | None = None,
    closing_date: date | None = None,
    session: Session = Depends(session_for_request),
):
    response.headers["Cache-Control"] = "no-store"
    if (opening_date is None) != (closing_date is None) or (
        opening_date is not None and opening_date >= closing_date
    ):
        raise HTTPException(422, "both dates are required, with opening_date < closing_date")
    result = read_instrument_returns(
        session,
        source_account=source_account,
        isin=isin,
        opening_date=opening_date,
        closing_date=closing_date,
    ).to_dict()

    from hermes_finance.services.instrument_names import instrument_names

    names = instrument_names(session)
    for row in result["instruments"]:
        row["short_name"] = names.name(isin=row["isin"], name=row["source_name"])
    missing = [row for row in result["instruments"] if row["short_name"] is None]
    if missing:
        from hermes_finance.services.instrument_names import source_label_candidates
        from hermes_finance.services.source_investment_proofs import (
            read_latest_display_candidates,
            resolve_display_name,
        )
        from hermes_finance.services.source_monthly_returns import _selected_sources

        # Use the same whole-history source labels as Overall. Selecting saved
        # source metadata does not recalculate the older financial interval.
        selected, _ = _selected_sources(session, source_account)
        native = source_label_candidates(
            session, [view for _, view, error in selected if view and not error]
        )
        for row in missing:
            row["short_name"] = names.name(
                isin=row["isin"],
                name=resolve_display_name(row["isin"], source_labels=native[row["isin"]]["names"]),
            )
        missing = [row for row in missing if row["short_name"] is None]
        # PDF-only labels retain the existing current-proof guard. Neither
        # source names nor numeric fields of the financial response are changed.
        labels = (
            read_latest_display_candidates(
                session, source_account=source_account, requested_isin=isin
            )
            if missing
            else {"source": {}, "pdf": {}}
        )
        for row in missing:
            row["short_name"] = names.name(
                isin=row["isin"],
                name=resolve_display_name(
                    row["isin"],
                    source_labels=labels["source"].get(row["isin"], ()),
                    pdf_labels=labels["pdf"].get(row["isin"], ()),
                ),
            )
    return result
