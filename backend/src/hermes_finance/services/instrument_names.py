"""Display-only security names. Never resolves identity or financial evidence."""

from sqlalchemy import select

from hermes_finance.persistence import Instrument


def short_instrument_name(name, *, isin=None, ticker=None):
    """Remove known identity suffixes, retaining meaningful parentheses."""
    value = (name or "").strip()
    previous = None
    while value != previous:
        previous = value
        for identity in (ticker, isin):
            suffix = f"({identity})" if identity else None
            if suffix and value.endswith(suffix):
                value = value[: -len(suffix)].rstrip()
    return (
        None
        if not value or value.casefold() in {x.casefold() for x in (isin, ticker) if x}
        else value
    )


class InstrumentNames:
    def __init__(self, instruments):
        self.by_id = {row.id: row for row in instruments}
        self.by_isin = {}
        self.by_name = {}
        for row in self.by_id.values():
            self.by_name.setdefault(row.name, []).append(row)
            if row.isin:
                self.by_isin.setdefault(row.isin, []).append(row)

    def name(self, *, instrument_id=None, isin=None, name=None, ticker=None):
        rows = (
            [self.by_id[instrument_id]]
            if instrument_id in self.by_id
            else self.by_isin.get(isin, []) or self.by_name.get(name, [])
        )
        names = {
            short_instrument_name(row.name, isin=row.isin, ticker=row.ticker) for row in rows
        } - {None}
        return (
            next(iter(names))
            if len(names) == 1
            else short_instrument_name(name, isin=isin, ticker=ticker)
        )

    def project(self, value):
        candidates = {}

        def collect(item):
            if isinstance(item, list):
                for child in item:
                    collect(child)
            elif isinstance(item, dict):
                if item.get("isin") and "name" in item:
                    label = short_instrument_name(
                        item["name"], isin=item["isin"], ticker=item.get("ticker")
                    )
                    if label:
                        candidates.setdefault(item["isin"], set()).add(label)
                for child in item.values():
                    collect(child)

        collect(value)
        return self._project(value, candidates)

    def _project(self, value, candidates):
        if isinstance(value, list):
            return [self._project(item, candidates) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: self._project(item, candidates) for key, item in value.items()}
        # Only presentation records, never arbitrary proof operands/identity maps.
        if "isin" in value and "name" in value:
            result["short_name"] = self.name(
                isin=value["isin"], name=value["name"], ticker=value.get("ticker")
            )
            labels = candidates.get(value["isin"], set())
            if result["short_name"] is None and len(labels) == 1:
                result["short_name"] = next(iter(labels))
        return result


def instrument_names(session):
    return InstrumentNames(session.scalars(select(Instrument).order_by(Instrument.id)))


def instrument_reference(instrument):
    """Use the already selected catalogue row in every canonical reader."""
    return {
        "id": instrument.id,
        "name": instrument.name,
        "short_name": short_instrument_name(
            instrument.name, isin=instrument.isin, ticker=instrument.ticker
        ),
    }


def with_short_names(session, value):
    return instrument_names(session).project(value)


def source_label_candidates(session, views):
    """Reuse existing exact source identities for labels, never payout attribution."""
    from hermes_finance.domain.money_security import parse_money_security
    from hermes_finance.services.money_instrument_links import MoneyInstrumentResolver
    from hermes_finance.services.source_instrument_events import _registration_scope
    from hermes_finance.services.source_instrument_returns import _identities

    result = _identities(views)
    resolver = None
    for view in views:
        for saved in view.get("money_classifications", ()):
            if saved.get("classification") != "dividend":
                continue
            security = parse_money_security(saved.get("narrative") or "")
            if security is None:
                continue
            if resolver is None:
                resolver = MoneyInstrumentResolver(session)
            isin = _registration_scope(saved, security, resolver)
            if isin:
                result[isin]["names"].add(security.issuer_name)
    return result


def with_document_short_names(session, value):
    """Keep receipt documents exact; attach display metadata beside their envelope."""
    names = instrument_names(session)
    document = value.get("document") or (value.get("accepted") or {}).get("document")
    if not isinstance(document, dict):
        return value
    source_names = {
        row["isin"]: row.get("source_name")
        for row in (value.get("identity") or {}).get("instruments", [])
    }
    isins = {row["isin"] for row in document.get("positions", [])}
    isins.update(row["core"]["isin"] for row in document.get("trades", []))
    return {
        **value,
        "instrument_labels": [
            {"isin": isin, "short_name": names.name(isin=isin, name=source_names.get(isin))}
            for isin in sorted(isins)
        ],
    }


def with_reference_short_names(session, value):
    """Label instrument references in read-only analysis DTOs, not their evidence."""
    names = instrument_names(session)

    def visit(item):
        if isinstance(item, list):
            return [visit(child) for child in item]
        if not isinstance(item, dict):
            return item
        result = {key: visit(child) for key, child in item.items()}
        ref = result.get("instrument")
        if isinstance(ref, dict) and "name" in ref:
            ref["short_name"] = names.name(
                instrument_id=ref.get("id", ref.get("hermes_id")),
                isin=ref.get("isin"),
                name=ref["name"],
            )
        return result

    return visit(value)
