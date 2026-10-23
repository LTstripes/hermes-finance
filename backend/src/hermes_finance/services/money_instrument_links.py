"""Offline, provisional payout attribution. Never create identity mappings."""

from collections import defaultdict

from sqlalchemy import select

from hermes_finance.domain.money_security import parse_money_security
from hermes_finance.persistence import BrokerIdentityMapping, Instrument, SourceIntakeObservation
from hermes_finance.statement_import.mybroker import PROVIDER


def _identifier(value):
    return (value or "").strip().upper()


def _name(value):
    # Exact whole issuer, allowing only typography/case/whitespace differences.
    return " ".join(value.casefold().replace("«", '"').replace("»", '"').split())


class MoneyInstrumentResolver:
    """Index catalog identifiers and explicit effective MyBroker aliases once.

    isin_reg/isin_reg1 are opaque in saved trade.core.isin: either an ISIN or a
    registration number. A trade is usable only through this same exact index;
    co-occurrence, p_name, ticker and issuer alone never invent a reg/ISIN bridge.
    """

    def __init__(self, session, trades):
        self.instruments = {row.id: row for row in session.scalars(select(Instrument))}
        self.identifiers = defaultdict(set)
        self.aliases = defaultdict(set)
        self.mapping_targets = defaultdict(set)
        for instrument in self.instruments.values():
            if instrument.isin:
                self.identifiers[_identifier(instrument.isin)].add(instrument.id)
        self.conflicts = set()
        mappings = list(
            session.scalars(
                select(BrokerIdentityMapping).where(
                    BrokerIdentityMapping.provider == PROVIDER,
                    BrokerIdentityMapping.subject_kind == "instrument",
                    BrokerIdentityMapping.status == "effective",
                )
            )
        )
        for mapping in mappings:
            target = self.instruments.get(mapping.hermes_instrument_id)
            alias, isin = _identifier(mapping.provider_identity), _identifier(mapping.observed_isin)
            if target is None:
                continue
            if isin and target.isin and isin != _identifier(target.isin):
                self.conflicts.add(alias)
            self.identifiers[alias].add(target.id)
            self.mapping_targets[alias].add(target.id)
            for related in (isin, _identifier(target.isin)):
                if related:
                    self.aliases[alias].add(related)
                    self.aliases[related].add(alias)
        self.trades = {_identifier(trade["core"]["isin"]) for trade in trades}

    def resolve(self, security):
        reg = security.reg_number
        # Traverse the complete explicit alias component, independent of query
        # order. Cycles terminate; contradictions propagate through every alias.
        related, pending = {reg}, [reg]
        while pending:
            for alias in self.aliases.get(pending.pop(), ()):
                if alias not in related:
                    related.add(alias)
                    pending.append(alias)
        # First collect matching same-statement trade identities, then catalog /
        # known mappings. A trade ISIN needs an explicit path from this reg.
        candidates = set()
        for identifier in self.trades & related:
            candidates.update(self.identifiers.get(identifier, ()))
        mapped = set()
        for identifier in related:
            candidates.update(self.identifiers.get(identifier, ()))
            mapped.update(self.mapping_targets.get(identifier, ()))
        if related & self.conflicts or (mapped and len(candidates) > 1):
            return None, "unresolved_ambiguous"
        if not candidates:
            return None, "unresolved_no_match"
        if len(candidates) > 1:
            named = {
                instrument_id
                for instrument_id in candidates
                if _name(self.instruments[instrument_id].name) == _name(security.issuer_name)
            }
            if len(named) != 1:
                return None, "unresolved_ambiguous"
            candidates = named
        return next(iter(candidates)), "linked"


def apply_money_instrument_link(row, resolver):
    """Derived metadata has no effect on the saved classification decision/time."""
    row.security_reg_number = row.security_issuer = row.instrument_id = None
    if (
        row.classification not in {"coupon", "dividend"}
        or row.amount_kopecks is None
        or row.amount_kopecks <= 0
    ):
        row.instrument_link_status = "not_applicable"
        return
    # Save and PUT use the same bounded persisted text and representable amount.
    # Truncation digests cannot accidentally satisfy a complete payout grammar.
    security = parse_money_security(row.narrative)
    if security is None or security.kind != row.classification:
        row.instrument_link_status = "not_parsed"
        return
    row.security_reg_number, row.security_issuer = security.reg_number, security.issuer_name
    row.instrument_id, row.instrument_link_status = resolver.resolve(security)


def intake_money_resolver(session, intake_id):
    import json

    trades = [
        json.loads(observation.facts_json)
        for observation in session.scalars(
            select(SourceIntakeObservation).where(
                SourceIntakeObservation.original_id == intake_id,
                SourceIntakeObservation.section == "trades",
                SourceIntakeObservation.generation == 1,
            )
        )
    ]
    return MoneyInstrumentResolver(session, trades)
