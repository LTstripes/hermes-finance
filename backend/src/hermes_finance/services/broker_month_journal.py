"""Explicit journal dispatch; legacy source receipts have no version field."""

import json

from hermes_finance.domain.broker_sections import CONTRACT as SECTIONS

SOURCE = "broker_month_v1"
MONEY = "broker_money_v1"
MONEY_V2 = "broker_money_v2"
MONEY_KINDS = {MONEY, MONEY_V2}
DEPENDENCY = "broker_money_dependency_v1"
PAYOUT = "broker_payout_reconciliation_v1"
PAYOUT_DEPENDENCY = "broker_payout_dependency_v1"
REVISION_KINDS = {*MONEY_KINDS, DEPENDENCY, PAYOUT, PAYOUT_DEPENDENCY}


def payload(receipt):
    try:
        value = json.loads(receipt.projection_json)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def kind(receipt):
    value = payload(receipt)
    version = value.get("contract_version")
    if "contract_version" not in value or version == SOURCE:
        required = {
            "exceptions": list,
            "position_ids": list,
            "cash_id": int,
            "trade_ids": list,
            "trade_identities": list,
            "source_digest": str,
            "projection_digest": str,
            "instruments": dict,
        }
        if all(type(value.get(k)) is t for k, t in required.items()):
            return SOURCE
    elif version in MONEY_KINDS:
        if all(
            type(value.get(k)) is t
            for k, t in {
                "targets": list,
                "sources": list,
                "base_request_id": str,
                "operation": str,
                "occurrences": list,
            }.items()
        ) and value["operation"] in {"accept", "reaffirm", "retire"}:
            return version
    elif version == PAYOUT:
        if (
            value.get("operation") in {"link", "reaffirm", "retire", "distinct"}
            and type(value.get("targets")) is list
            and type(value.get("base_request_id")) is str
            and type(value.get("journal_revision")) is int
            and value["journal_revision"] > 0
        ):
            return PAYOUT
    elif version in {DEPENDENCY, PAYOUT_DEPENDENCY}:
        if isinstance(value.get("base_request_id"), str) and isinstance(
            value.get("reason_code"), str
        ):
            return version
    elif version == SECTIONS:
        from hermes_finance.services.broker_sections import validated_proof

        if validated_proof(receipt) is not None:
            return SECTIONS
    return "invalid"
