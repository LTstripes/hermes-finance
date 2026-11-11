"""Private row indexes for Returns' existing immutable source snapshot.

No index is available to writers or survives the outer source read. ORM rows
stay internal to evidence readers; public readers continue returning owned DTOs.
"""

import json

from sqlalchemy import select

from hermes_finance.persistence import ExecutedTrade, MyBrokerImport


def _row(session, model, field, value):
    from hermes_finance.services.source_monthly_returns import _SOURCE_SCOPE_READS

    cache = session.info.get(_SOURCE_SCOPE_READS)
    if cache is None:
        return session.scalar(select(model).where(field == value))
    key = ("returns_row_index", model)
    if key not in cache:
        cache[key] = {getattr(row, field.key): row for row in session.scalars(select(model))}
    return cache[key].get(value)


def source_import(session, digest):
    return _row(session, MyBrokerImport, MyBrokerImport.document_sha256, digest)


def executed_trade(session, identity):
    return _row(session, ExecutedTrade, ExecutedTrade.source_identity, identity)


def normalized_import(session, source):
    """Private parser operand; equality readers never mutate or expose it."""
    from hermes_finance.services.source_monthly_returns import _SOURCE_SCOPE_READS

    cache = session.info.get(_SOURCE_SCOPE_READS)
    if cache is None:
        return json.loads(source.normalized_json)
    key = ("returns_normalized_import", source.id, source.normalized_json)
    if key not in cache:
        cache[key] = json.loads(source.normalized_json)
    return cache[key]


def money_proof_head(session, key):
    """Borrow one private receipt operand for nonmutating evidence checks only."""
    from hermes_finance.services.source_monthly_returns import _SOURCE_SCOPE_READS
    from hermes_finance.services.source_return_evidence import _payout_money_heads

    cache = session.info.get(_SOURCE_SCOPE_READS)
    if cache is None:
        return _payout_money_heads(session).get(key)
    inventory = ("returns_payout_money_heads", _payout_money_heads)
    if inventory not in cache:
        cache[inventory] = _payout_money_heads(session)
    return cache[inventory].get(key)


def source_blockers(session, view):
    """Parse inventory once for private, unmodified source-builder operands."""
    from hermes_finance.services.source_monthly_returns import _SOURCE_SCOPE_READS
    from hermes_finance.statement_import.mybroker_return_structure import source_return_blockers

    cache = session.info.get(_SOURCE_SCOPE_READS)
    if cache is None:
        return source_return_blockers(view)
    key = ("returns_source_blockers", id(view), source_return_blockers)
    if key not in cache:
        cache[key] = (view, frozenset(source_return_blockers(view)))
    return set(cache[key][1])


def repo_identities(session, view, *, identity_reader=None):
    """Reuse inventory parsing only for private, unmodified builder operands."""
    from hermes_finance.services.source_monthly_returns import _SOURCE_SCOPE_READS

    if identity_reader is None:
        from hermes_finance.services.clean_repo_pairs import repo_return_identities

        identity_reader = repo_return_identities
    cache = session.info.get(_SOURCE_SCOPE_READS)
    if cache is None:
        return identity_reader(view)
    key = ("instrument_repo_identities", id(view), identity_reader)
    if key not in cache:
        # Retain the private view as well, preventing object-id reuse.
        cache[key] = (view, identity_reader(view))
    return cache[key][1]
