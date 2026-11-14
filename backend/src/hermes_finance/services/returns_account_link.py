"""Explicit source identity metadata; never financial acceptance or an amount join."""

from collections import defaultdict

from sqlalchemy import select

from hermes_finance.persistence import Account, BrokerIdentityMapping
from hermes_finance.statement_import.mybroker import PROVIDER


def account_link(session, source_account, canonical=None):
    from hermes_finance.services.returns_view import _source_scopes
    from hermes_finance.services.source_monthly_returns import _selected_sources

    canonical = _source_scopes(session) if canonical is None else canonical
    native = canonical.get(source_account, source_account)
    selected, scope = _selected_sources(session, native, identity_only=True)
    mappings, reverse = defaultdict(set), defaultdict(set)
    for identity, account_id in session.execute(
        select(
            BrokerIdentityMapping.provider_identity, BrokerIdentityMapping.hermes_account_id
        ).where(
            BrokerIdentityMapping.provider == PROVIDER,
            BrokerIdentityMapping.subject_kind == "account",
            BrokerIdentityMapping.status == "effective",
        )
    ):
        key = canonical.get(identity, identity)
        mappings[key].add(account_id)
        reverse[account_id].add(key)
    ids = mappings[native]
    reason = None
    account = session.get(Account, next(iter(ids))) if len(ids) == 1 else None
    if not selected or scope != {native} or any(error for _, _, error in selected):
        reason = "source_account_identity_unproven"
    elif not ids:
        reason = "source_account_mapping_missing"
    elif len(ids) != 1 or any(len(reverse[key]) != 1 for key in ids):
        reason = "source_account_mapping_ambiguous"
    elif account is None:
        reason = "source_account_mapping_missing"
    elif account.account_type not in {"brokerage", "iis"}:
        reason = "source_account_type_unsupported"
    linked = reason is None
    kind = account.account_type if linked else None
    fallback = ("ИИС" if kind == "iis" else "Брокерский") + " " + native if linked else native
    return {
        "source_account_id": native,
        "financial_account_id": account.id if linked else None,
        "account_type": kind,
        "label": account.name if linked and account.name and account.name.strip() else fallback,
        "status": "linked" if linked else "unlinked",
        "reason_codes": [] if linked else [reason],
    }
