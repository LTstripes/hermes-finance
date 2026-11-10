"""Analytical full redemption from exact retained source facts, never a receipt."""

import re
from dataclasses import replace
from decimal import Decimal, localcontext

from hermes_finance.domain.clean_instrument_return import clean_trade_amount, trade_amount_with_nkd
from hermes_finance.domain.money_security import MoneySecurity
from hermes_finance.statement_import.investment_money import _REG, parse_investment_money_security
from hermes_finance.statement_import.mybroker import NS, digest
from hermes_finance.statement_import.mybroker_return_structure import _inventory_tree


def _face_from_purchases(events, isin, day):
    """The established NKD basis, price and quantity must reproduce one exact face."""
    faces = set()
    for event in events:
        if (
            event.isin != isin
            or event.kind != "BUY"
            or event.event_date is None
            or event.event_date >= day
        ):
            continue
        if (
            not event.current
            or not event.counted
            or event.reason_codes
            or event.price_unit != "PERCENT_OF_FACE"
            or not event.native_identity
            or len(event.native_ids) != 2
            or event.native_total_basis not in {"includes_paid_nkd", "excludes_paid_nkd"}
            or event.accrued_interest_kopecks is None
            or event.accrued_interest_kopecks < 0
            or event.unit_price is None
            or not event.unit_price.is_finite()
            or event.unit_price <= 0
            or event.quantity_delta is None
            or not event.quantity_delta.is_finite()
            or event.quantity_delta <= 0
            or trade_amount_with_nkd(event) is None
        ):
            return None
        principal = clean_trade_amount(event)
        if principal is None:
            return None
        with localcontext() as context:
            context.prec = 200
            face = Decimal(principal) / (event.unit_price * event.quantity_delta)
            if face <= 0 or face * 100 != (face * 100).to_integral_value():
                return None
            if face * event.unit_price * event.quantity_delta != principal:
                return None
        if event.face_value is not None and event.face_value != face:
            return None
        faces.add(face)
    return next(iter(faces)) if len(faces) == 1 else None


def _cancellation_quantity_digests(quantity):
    """Exact spellings within the proven -integer[.fraction] cancellation grammar."""
    if not quantity.is_finite() or quantity <= 0:
        return frozenset()
    whole, _, fraction = format(quantity, "f").partition(".")
    fraction = fraction.rstrip("0")
    if len(whole) > 18 or len(fraction) > 10:
        return frozenset()
    # No rounding or leading-zero guesses: only pad the exact fraction with zeros.
    return frozenset(
        digest("-" + whole + ("." + fraction + "0" * (places - len(fraction)) if places else ""))
        for places in range(len(fraction), 11)
    )


def _cancelled_quantity(views, isin, account, day, cancellation_dates):
    """A complete observed disappearance plus the exact dated native cancellation."""
    quantities = set()
    for view in views:
        for position in view["document"].get("positions", ()):
            if position["isin"] != isin or position["source_account"] != account:
                continue
            if not view["covered_from"] <= day.isoformat() <= view["covered_to"]:
                continue
            opening = Decimal(position["beginning_actual_quantity"])
            closing = Decimal(position["actual_quantity"])
            if not opening.is_finite() or not closing.is_finite() or closing != 0 or opening <= 0:
                return None
            # Other deliveries inside this position interval would invalidate
            # using its whole opening quantity as the cancellation quantity.
            if any(t["core"]["isin"] == isin for t in view["document"].get("trades", ())):
                return None
            quantities.add(opening)
    if len(quantities) != 1:
        return None
    quantity = next(iter(quantities))
    quantity_digests = _cancellation_quantity_digests(quantity)
    for view in views:
        if not view["covered_from"] <= day.isoformat() <= view["covered_to"]:
            continue
        if day.replace(day=1) not in cancellation_dates.get(view["id"], ()):
            return None
        tree = _inventory_tree(view["observations"])
        nodes = tree.findall("m:Trades3/m:Report/m:Tablix1/m:Details_Collection/m:Details", NS)
        # Bind the original issue label to its exact ISIN; an issuer is insufficient.
        labels = {
            o["source_name"]
            for p in view.get("proposals", ())
            if p["isin"] == isin
            for o in (p, *p.get("observations", ()))
            if o.get("source_name")
        }
        names = {digest(label + separator + isin) for label in labels for separator in ("\r\n",)}
        # Current cancellation_dates proves the original-bound Trades3 grammar,
        # including "Аннулирование выпуска [A-Z0-9]{1,32}\." comments. The code
        # may be an exchange issue code, not the ISIN; retained values are hashes.
        # Require comment_new in the exact attribute set below, and bind the issue
        # through p_name's exact label + CRLF + ISIN instead of guessing the code.
        matches = [
            node
            for node in nodes
            if (
                node.get("acc_code") == digest(account)
                and node.get("oper_type") == digest("Перевод")
                and node.get("p_name") in names
                and node.get("place_name") == digest("НРД")
                and not len(node)
                and set(node.attrib)
                == {
                    "acc_code",
                    "oper_type",
                    "comment_new",
                    "p_name",
                    "qty",
                    "settlement_date",
                    "settlement_time",
                    "place_name",
                }
            )
        ]
        if (
            len(matches) != 1
            or matches[0].get("qty") not in quantity_digests
            or matches[0].get("settlement_date") != digest(day.isoformat() + "T00:00:00")
        ):
            return None
    return quantity


def _scope_redemption_gaps(events, choices, identities, resolver):
    """Exact issue identity limits a gap; it never establishes redemption cash."""
    result = []
    for event in events:
        if (
            event.isin is not None
            or "redemption_amortization_unsupported" not in event.reason_codes
        ):
            result.append(event)
            continue
        scopes = set()
        for ref in event.source_references:
            member = choices.get(ref)
            if member is None:
                scopes.add(None)
                continue
            _, choice = member
            text = " ".join(
                str(choice.get(field) or "")
                for field in ("operation", "narrative", "security_reg_number")
            )
            registrations = {
                value.upper()
                for value in re.findall(rf"(?<![\w-]){_REG}(?![\w-])", text, re.IGNORECASE)
            }
            matches = {
                isin
                for isin, metadata in identities.items()
                if any(str(value).upper() in registrations for value in metadata["identifiers"])
            }
            for registration in registrations:
                target, status = resolver.resolve(MoneySecurity(registration.upper(), "", "coupon"))
                instrument = resolver.instruments.get(target)
                if status == "linked":
                    matches.add(
                        instrument.isin
                        if instrument and instrument.instrument_type == "bond"
                        else None
                    )
                elif status == "unresolved_ambiguous" or not any(
                    str(value).upper() == registration
                    for metadata in identities.values()
                    for value in metadata["identifiers"]
                ):
                    matches.add(None)
            scopes.add(next(iter(matches)) if len(matches) == 1 else None)
        isin = next(iter(scopes)) if len(scopes) == 1 else None
        result.append(
            replace(event, isin=isin, effective_isin=isin, attribution_basis="registration_scope")
            if isin is not None
            else event
        )
    return tuple(result)


def apply_clean_redemptions(session, events, views, cancellation_dates):
    """Reuse the cash occurrence once after issue, cancellation, face and sum agree."""

    from hermes_finance.services.broker_money_ownership import owners
    from hermes_finance.services.money_instrument_links import MoneyInstrumentResolver
    from hermes_finance.services.source_instrument_returns import _identities
    from hermes_finance.services.source_money_classifications import source_reference
    from hermes_finance.services.source_return_evidence import _source_allows_payout, bound_import

    candidates = [e for e in events if "redemption_amortization_unsupported" in e.reason_codes]
    if not candidates:
        return tuple(events), frozenset()
    choices = {
        c["source_reference"]: (view, c) for view in views for c in view["money_classifications"]
    }
    resolver = MoneyInstrumentResolver(session)
    events = _scope_redemption_gaps(events, choices, _identities(views), resolver)
    if not cancellation_dates:
        return events, frozenset()
    candidate_refs = {ref for event in candidates for ref in event.source_references}
    occurrences, references = [], {}
    for view in views:
        source = bound_import(session, view)
        if source is None:
            continue
        for raw in view["document"].get("money", ()):
            ref = source_reference(view["id"], raw)
            if ref not in candidate_refs:
                continue
            occurrence = {"import_id": source.id, "section": "money", "ordinal": raw["ordinal"]}
            occurrences.append(occurrence)
            references.setdefault((source.id, "money", raw["ordinal"]), set()).add(ref)
    occupied = (
        {
            ref
            for owner in owners(session, occurrences)
            for ref in references.get(tuple(owner["key"]), ())
        }
        if occurrences
        else set()
    )
    result, resolved = [], set()
    for event in events:
        if (
            event.kind != "UNRESOLVED"
            or event.classification != "unknown"
            or set(event.reason_codes)
            != {"unrecognized_money", "redemption_amortization_unsupported"}
            or len(event.cash_legs) != 1
            or event.cash_legs[0].account_cash_kopecks <= 0
            or event.event_date is None
        ):
            result.append(event)
            continue
        members = [choices.get(ref) for ref in event.source_references]
        securities = []
        valid = bool(members) and all(members) and not (set(event.source_references) & occupied)
        for member in members:
            if member is None:
                continue
            view, choice = member
            prefix = "полное погашение номинала "
            narrative = choice["narrative"]
            security = (
                parse_investment_money_security(narrative.replace(prefix, "погашение купона ", 1))
                if narrative.startswith(prefix)
                else None
            )
            valid = valid and (
                security is not None
                and choice["classification"] == "unknown"
                and choice["currency"] == "RUB"
                and choice["amount_kopecks"] == event.cash_legs[0].account_cash_kopecks
                and str(choice["date"]) == event.event_date.isoformat()
                and choice["origin"] in {"default_rule", "user_choice"}
                and choice["status"] in {"assumed", "confirmed"}
            )
            if security:
                securities.append(security)
        target, status = (
            resolver.resolve(securities[0]) if valid and len(set(securities)) == 1 else (None, None)
        )
        instrument = resolver.instruments.get(target)
        if (
            status != "linked"
            or instrument is None
            or instrument.instrument_type != "bond"
            or not instrument.isin
        ):
            result.append(event)
            continue
        isin = instrument.isin
        if event.isin not in (None, isin) or any(
            not _source_allows_payout(session, view, isin) for view, _ in members
        ):
            result.append(event)
            continue
        try:
            quantity = _cancelled_quantity(
                views, isin, event.native_source_account, event.event_date, cancellation_dates
            )
            face = _face_from_purchases(events, isin, event.event_date)
        except (ArithmeticError, KeyError, TypeError, ValueError):
            quantity = face = None
        other_redemptions = [
            e
            for e in events
            if e is not event
            and e.isin in (None, isin)
            and ("redemption_amortization_unsupported" in e.reason_codes or e.kind == "REDEMPTION")
        ]
        if (
            quantity is None
            or face is None
            or other_redemptions
            or quantity * face * 100 != event.cash_legs[0].account_cash_kopecks
        ):
            result.append(event)
            continue
        result.append(
            replace(
                event,
                isin=isin,
                effective_isin=isin,
                kind="REDEMPTION",
                quantity_delta=-quantity,
                depository_settlement_date=event.event_date,
                current=True,
                counted=True,
                reason_codes=(),
                attribution_basis="analytical_full_redemption",
                cash_legs=(replace(event.cash_legs[0], role="redemption"),),
            )
        )
        resolved.add(event.event_key)
    return tuple(result), frozenset(resolved)
