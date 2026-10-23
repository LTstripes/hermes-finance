"""Offline, provisional payout attribution. Never create identity mappings."""

from collections import defaultdict

from sqlalchemy import select

from hermes_finance.domain.money_security import parse_money_security
from hermes_finance.persistence import BrokerIdentityMapping, Instrument, SecurityRegIsinMapping
from hermes_finance.statement_import.mybroker import PROVIDER


def _identifier(value):
    return (value or "").strip().upper()


def _name(value):
    # Exact whole issuer, allowing only typography/case/whitespace differences.
    return " ".join(value.casefold().replace("«", '"').replace("»", '"').split())


class MoneyInstrumentResolver:
    """Index catalog identifiers, effective MyBroker aliases and owner crosswalks.

    Co-occurrence, trade identifiers, ticker and issuer alone never invent a
    registration-number/ISIN bridge.
    """

    def __init__(self, session):
        self.instruments = {row.id: row for row in session.scalars(select(Instrument))}
        self.identifiers = defaultdict(set)
        self.aliases = defaultdict(set)
        self.mapping_targets = defaultdict(set)
        self.reg_isins = {
            row.reg_number: row.isin for row in session.scalars(select(SecurityRegIsinMapping))
        }
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

    def _related(self, identifier):
        # Traverse the complete explicit alias component, independent of query
        # order. Cycles terminate; contradictions propagate through every alias.
        related, pending = {identifier}, [identifier]
        while pending:
            for alias in self.aliases.get(pending.pop(), ()):
                if alias not in related:
                    related.add(alias)
                    pending.append(alias)
        return related

    def _candidates(self, related):
        return {target for identifier in related for target in self.identifiers.get(identifier, ())}

    def resolve(self, security):
        reg = security.reg_number
        owner_isin = self.reg_isins.get(reg)
        # Owner mappings are directional: candidates must be reachable from the
        # mapped ISIN, not merely a registration alias or another crosswalk row.
        related = self._related(owner_isin or reg)
        candidates = self._candidates(related)
        if owner_isin:
            reg_related = self._related(reg)
            if reg_related & self.conflicts or not self._candidates(reg_related) <= candidates:
                return None, "unresolved_ambiguous"
        mapped = set()
        for identifier in related:
            mapped.update(self.mapping_targets.get(identifier, ()))
        if related & self.conflicts or ((mapped or owner_isin) and len(candidates) > 1):
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
    if security is None:
        row.instrument_link_status = "not_parsed"
        return
    if security.kind != row.classification:
        row.instrument_link_status = "kind_mismatch"
        return
    row.security_reg_number, row.security_issuer = security.reg_number, security.issuer_name
    row.instrument_id, row.instrument_link_status = resolver.resolve(security)
