"""Separate indicative, nonannualized statement MWR. No financial authority."""

from datetime import date
from decimal import Decimal, DecimalException, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from hermes_finance.domain.xirr import XirrCashFlow, calculate_xirr

NKD_WARNING = "По оценке брокера; учёт НКД в стоимости облигаций не подтверждён"
PERIOD_WARNING = "Доходность за фактический период; не приведена к году"


class StatementModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class StatementPosition(StatementModel):
    instrument_id: int
    isin: str
    quantity: str | None
    market_value_kopecks: int | None
    source_ordinal: int

    @field_serializer("market_value_kopecks", when_used="json")
    def money_string(self, value):
        return str(value) if value is not None else None


class StatementEndpoint(StatementModel):
    account_id: int
    valuation_date: date
    timing: Literal["eod"] = "eod"
    currency: str = "RUB"
    positions: tuple[StatementPosition, ...] = ()
    positions_value_kopecks: int | None
    cash_kopecks: int | None
    total_value_kopecks: int | None
    inventory_state: Literal["complete", "unknown"]

    @field_serializer(
        "positions_value_kopecks", "cash_kopecks", "total_value_kopecks", when_used="json"
    )
    def money_string(self, value):
        return str(value) if value is not None else None


class StatementCrossing(StatementModel):
    event_id: str
    account_id: int
    event_date: date
    currency: str
    signed_amount_kopecks: int  # positive INTO the account, including self-transfers
    revision_id: int
    material_signature: str

    @field_serializer("signed_amount_kopecks", when_used="json")
    def money_string(self, value):
        return str(value)


class StatementSource(StatementModel):
    import_id: int
    document_sha256: str
    parser_version: str
    source_signature: str
    request_id: str
    confirmation_digest: str


class StatementSectionAuthority(StatementModel):
    """Current source-bound metadata authority; never economic-period evidence."""

    import_id: int
    account_id: int
    reporting_month_id: int
    section: Literal["4_Transfers", "5_UFSR"]
    state: Literal["effective", "missing", "blocked"]
    pattern: Literal["empty_transfers", "ufsr_open_connection"] | None = None
    head_request_id: str | None = None
    proof_material_signature: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    period_scope: Literal["unknown"] = "unknown"


class BrokerStatementBasis(StatementModel):
    account_id: int
    t0: date
    t1: date
    currency: Literal["RUB"] = "RUB"
    opening: StatementEndpoint
    closing: StatementEndpoint
    sources: tuple[StatementSource, ...]
    material_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    section_authority: tuple[StatementSectionAuthority, ...] = ()
    crossings: tuple[StatementCrossing, ...] = ()
    cash_coverage_state: Literal["complete", "unknown"] = "unknown"
    cash_coverage_revision_id: int | None = None
    membership_state: Literal["complete", "unknown"] = "unknown"
    exposure_state: Literal["assessed", "unknown"] = "unknown"
    bond_nkd_basis: Literal["unknown", "not_applicable"] = "unknown"
    reason_codes: tuple[str, ...] = ()


class BrokerStatementReturn(BrokerStatementBasis):
    method: Literal["broker_statement_mwr_period_v1"] = "broker_statement_mwr_period_v1"
    scope: Literal["account"] = "account"
    status: Literal["indicative", "unavailable"]
    quality: Literal["indicative", "unavailable"]
    rate_fraction: str | None
    annualized: Literal[False] = False
    warnings: tuple[str, ...]


def calculate_statement_return(
    basis: BrokerStatementBasis, *, max_iterations: int = 256
) -> BrokerStatementReturn:
    """Consume server-verified evidence, reuse only the Decimal solver kernel."""
    reasons = set(basis.reason_codes)
    if basis.t0 >= basis.t1:
        reasons.add("statement_interval_invalid")
    if not basis.sources:
        reasons.add("statement_source_missing")
    for endpoint, day in ((basis.opening, basis.t0), (basis.closing, basis.t1)):
        if endpoint.account_id != basis.account_id or endpoint.valuation_date != day:
            reasons.add("statement_endpoint_identity_mismatch")
        if endpoint.currency != "RUB":
            reasons.add("statement_currency_unproved")
        if endpoint.inventory_state != "complete":
            reasons.add("statement_inventory_incomplete")
        values = (endpoint.positions_value_kopecks, endpoint.cash_kopecks)
        if any(v is None or v < 0 for v in values):
            reasons.add("statement_endpoint_value_unavailable")
        elif endpoint.total_value_kopecks != sum(values):
            reasons.add("statement_endpoint_components_mismatch")
        row_values = [p.market_value_kopecks for p in endpoint.positions]
        identities = [p.instrument_id for p in endpoint.positions]
        if len(set(identities)) != len(identities) or any(i <= 0 for i in identities):
            reasons.add("statement_instrument_identity_unproved")
        for position in endpoint.positions:
            try:
                quantity = Decimal(position.quantity) if position.quantity is not None else None
                if (
                    quantity is None
                    or not quantity.is_finite()
                    or quantity < 0
                    or (quantity == 0 and position.market_value_kopecks != 0)
                ):
                    reasons.add("statement_quantity_unproved")
            except DecimalException:
                reasons.add("statement_quantity_unproved")
        if any(v is None or v < 0 for v in row_values):
            reasons.add("statement_position_value_unavailable")
        elif sum(row_values) != endpoint.positions_value_kopecks:
            reasons.add("statement_position_components_mismatch")
    if basis.cash_coverage_state != "complete" or basis.cash_coverage_revision_id is None:
        reasons.add("account_crossing_coverage_unproved")
    if basis.membership_state != "complete":
        reasons.add("statement_account_membership_unproved")
    if basis.exposure_state != "assessed":
        reasons.add("material_account_exposure_unassessed")
    ids = [c.event_id for c in basis.crossings]
    if len(set(ids)) != len(ids):
        reasons.add("statement_crossing_identity_ambiguous")
    for crossing in basis.crossings:
        if (
            crossing.account_id != basis.account_id
            or crossing.currency != "RUB"
            or not basis.t0 < crossing.event_date <= basis.t1
            or crossing.revision_id <= 0
            or len(crossing.material_signature) != 64
        ):
            reasons.add("statement_crossing_evidence_invalid")
    rate = None
    if not reasons:
        vector = [
            XirrCashFlow(basis.t0, -basis.opening.total_value_kopecks),
            *(XirrCashFlow(c.event_date, -c.signed_amount_kopecks) for c in basis.crossings),
            XirrCashFlow(basis.t1, basis.closing.total_value_kopecks),
        ]
        result = calculate_xirr(vector, max_iterations=max_iterations)
        if result.annualized_rate is None:
            reasons.update(result.reason_codes)
        else:
            try:
                with localcontext() as ctx:
                    ctx.prec = 60
                    period = (Decimal(1) + result.annualized_rate) ** (
                        Decimal((basis.t1 - basis.t0).days) / Decimal(365)
                    ) - Decimal(1)
                    if not period.is_finite():
                        raise DecimalException
                    rate = format(period, "f")
            except DecimalException:
                reasons.add("not_computable_xirr_convergence_failed")
    status = "indicative" if rate is not None else "unavailable"
    return BrokerStatementReturn(
        **basis.model_dump(exclude={"reason_codes"}),
        reason_codes=tuple(sorted(reasons)),
        status=status,
        quality=status,
        rate_fraction=rate,
        warnings=(PERIOD_WARNING, NKD_WARNING)
        if basis.bond_nkd_basis == "unknown"
        else (PERIOD_WARNING,),
    )
