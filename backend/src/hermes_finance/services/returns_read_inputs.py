"""Private row indexes for Returns' existing immutable source snapshot.

No index is available to writers or survives the outer source read. ORM rows
stay internal to evidence readers; public readers continue returning owned DTOs.
"""

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


def repo_identities(session, view):
    """Reuse inventory parsing only for private, unmodified builder operands."""
    from hermes_finance.services.clean_repo_pairs import repo_return_identities
    from hermes_finance.services.source_monthly_returns import _SOURCE_SCOPE_READS

    cache = session.info.get(_SOURCE_SCOPE_READS)
    if cache is None:
        return repo_return_identities(view)
    key = ("instrument_repo_identities", id(view), repo_return_identities)
    if key not in cache:
        # Retain the private view as well, preventing object-id reuse.
        cache[key] = (view, repo_return_identities(view))
    return cache[key][1]
