"""Explicit synthetic fixture completion for read-model/legacy-history tests.

These helpers do not replace tests of authoritative Close. An empty fixture uses
the separately typed policy, with audit and no invented cash/income. Every other
hard guard still goes through the ordinary service/HTTP error path.
"""

from uuid import uuid4

from hermes_finance.services.intentional_empty_close import (
    POLICY_VERSION,
    IntentionalEmptyCloseCommand,
    close_intentionally_empty_month,
    empty_close_identity,
)
from hermes_finance.services.reporting_months import (
    close_hard_guards,
    close_reporting_month,
    get_reporting_month,
)


def close_fixture_month(session, month_id):
    month = get_reporting_month(session, month_id)
    if [code for code, _ in close_hard_guards(month, session)] == ["empty_manual_month"]:
        close_intentionally_empty_month(
            session,
            month_id,
            IntentionalEmptyCloseCommand(
                **empty_close_identity(session, month).model_dump(),
                command="close_intentionally_empty_manual_month",
                policy_version=POLICY_VERSION,
                request_id=uuid4().hex,
                reason="Synthetic fixture intentionally has no recorded financial facts",
            ),
        )
        return get_reporting_month(session, month_id)
    return close_reporting_month(session, month_id)


def close_fixture_month_http(client, month_id):
    readiness = client.get(f"/api/months/{month_id}/close-readiness")
    assert readiness.status_code == 200, readiness.text
    option = readiness.json()["intentional_empty_close"]
    if option and option["eligible"]:
        return client.post(
            f"/api/months/{month_id}/close-intentionally-empty",
            json={
                **{k: v for k, v in option.items() if k != "eligible"},
                "request_id": uuid4().hex,
                "reason": "Synthetic fixture intentionally has no recorded financial facts",
            },
        )
    return client.post(f"/api/months/{month_id}/close")
