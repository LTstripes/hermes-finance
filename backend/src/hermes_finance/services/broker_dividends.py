"""Strict v2 dividend evidence. No classifier authority or financial writer."""

import re
from decimal import Decimal

from sqlalchemy import select

from hermes_finance.domain.money_security import parse_money_security
from hermes_finance.persistence import BrokerIdentityMapping, Instrument, SecurityRegIsinMapping
from hermes_finance.services.money_instrument_links import MoneyInstrumentResolver
from hermes_finance.statement_import.mybroker import digest


def identity(session, registration, instrument_id):
    from hermes_finance.services.broker_money import material

    instrument = session.get(Instrument, instrument_id) if instrument_id else None
    if (
        not instrument
        or instrument.instrument_type != "stock"
        or instrument.currency != "RUB"
        or not instrument.is_active
        or not instrument.isin
    ):
        return None
    resolver = MoneyInstrumentResolver(session)
    mapped_isin = resolver.reg_isins.get(registration)
    related = resolver._related(mapped_isin or registration)
    reg_related = resolver._related(registration)
    # Explicit bridges only. Do not use the provisional resolver's issuer-name tie-break.
    if not mapped_isin and not resolver.mapping_targets.get(registration):
        return None
    if resolver._candidates(related) != {instrument_id} or related & resolver.conflicts:
        return None
    if mapped_isin and (
        mapped_isin != instrument.isin
        or reg_related & resolver.conflicts
        or not resolver._candidates(reg_related) <= {instrument_id}
    ):
        return None
    mappings = [
        row
        for row in session.scalars(select(BrokerIdentityMapping).order_by(BrokerIdentityMapping.id))
        if row.provider == "alfa_mybroker"
        and row.subject_kind == "instrument"
        and row.provider_identity in related | reg_related
    ]
    # A withdrawn exact alias cannot be rescued by the crosswalk alone.
    for alias in {row.provider_identity for row in mappings}:
        effective = [
            row for row in mappings if row.provider_identity == alias and row.status == "effective"
        ]
        if len(effective) != 1 or effective[0].hermes_instrument_id != instrument_id:
            return None
    crosswalk = session.scalar(
        select(SecurityRegIsinMapping).where(SecurityRegIsinMapping.reg_number == registration)
    )
    return {
        "registration": registration,
        "instrument_id": instrument_id,
        "identity_digest": digest(
            [material(instrument), material(crosswalk), [material(r) for r in mappings]]
        ),
    }


def evidence(session, decision, observation, inventory, blockers):
    narrative = observation["description"]
    security = parse_money_security(narrative) if len(narrative) <= 4096 else None
    result = (
        identity(session, security.reg_number, decision.instrument_id)
        if security and security.kind == "dividend"
        else None
    )
    if result is None:
        blockers.add("exact_dividend_stock_identity_required")
    for candidate in inventory:
        if candidate["amount_minor"] is None or candidate["amount_minor"] >= 0:
            continue
        parsed = parse_money_security(candidate["description"])
        if (parsed and security and parsed.reg_number == security.reg_number) or (
            candidate["date"] == observation["date"] and candidate["s1_kind"] == "unsupported"
        ):
            blockers.add("dividend_tax_or_reversal_cash_leg_unresolved")
    tax = None
    if security:
        match = re.search(
            r"\(Удержан налог ([0-9]+(?:[.,][0-9]{1,2})?) руб\.\)", narrative, re.IGNORECASE
        )
        if match and len(match[1]) <= 22:
            value = Decimal(match[1].replace(",", ".")) * 100
            if value == value.to_integral_value() and 0 <= value <= 2**63 - 1:
                tax = str(int(value))
        if tax is None:
            blockers.add("dividend_tax_annotation_unsupported")
    return {"identity_proof": result, "observed_tax_kopecks": tax, "tax_role": "annotation_only"}
