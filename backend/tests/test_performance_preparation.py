"""Owner workflow: canonical mutations, coherent inspection and stale-write rejection."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_r08_01a_external_flows import _environment

from hermes_finance.main import create_app
from hermes_finance.services.reporting_months import close_reporting_month


@pytest.fixture
def env(tmp_path):
    session, database, month, account, partner = _environment(tmp_path)
    with TestClient(create_app(database=database)) as client:
        yield client, session, database, month, account, partner
    session.close()
    database.engine.dispose()


def read(env, account_id=None):
    response = env[0].get(
        "/api/performance/preparation",
        params={
            "account_id": env[4] if account_id is None else account_id,
            "start_date": "2030-05-01",
            "end_date": "2030-05-31",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def headers(env):
    return {"X-Performance-Evidence": read(env)["evidence_token"]}


def flow(env, **patch):
    return dict(
        reporting_month_id=env[3],
        account_id=env[4],
        event_date="2030-05-12",
        boundary_amount={"amount": "123.45", "currency": "RUB"},
        direction="contribution",
        kind="external_contribution",
        **patch,
    )


def coverage(env):
    return dict(
        account_id=env[4],
        covered_from="2030-05-01",
        covered_to="2030-05-31",
        coverage_state="complete",
        provenance_kind="owner_attestation",
    )


def test_inspection_is_read_only_empty_is_not_attested(env):
    before = read(env)
    assert before["flows"] == before["cash_coverages"] == before["in_kind_coverages"] == []
    assert read(env) == before
    schema = env[0].get("/openapi.json").json()
    assert set(schema["paths"]["/api/performance/preparation"]) == {"get"}


def test_double_submit_and_stale_edit_are_rejected(env):
    client = env[0]
    old = headers(env)
    created = client.post("/api/external-flows", json=flow(env), headers=old)
    assert created.status_code == 201, created.text
    assert created.json()["scope_membership"] == "unknown"
    assert client.post("/api/external-flows", json=flow(env), headers=old).status_code == 409
    target = f"/api/external-flows/{created.json()['id']}"
    current = headers(env)
    assert client.patch(target, json={"source": "corrected"}, headers=current).status_code == 200
    assert client.patch(target, json={"source": "stale"}, headers=current).status_code == 409
    assert read(env)["flows"][0]["source"] == "corrected"
    assert len(read(env)["flows"]) == 1


def test_concurrent_duplicate_create_has_one_winner(env):
    token = headers(env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: env[0].post("/api/external-flows", json=flow(env), headers=token),
                range(2),
            )
        )
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert len(read(env)["flows"]) == 1


def test_move_flow_between_accounts_rereads_both_ledgers_and_rejects_old_token(env):
    from sqlalchemy import select

    from hermes_finance.persistence import AccountPerformanceScopeMembership

    client, session, _, month, account, partner = env
    created = client.post("/api/external-flows", json=flow(env), headers=headers(env))
    assert created.status_code == 201, created.text
    flow_id = created.json()["id"]
    for owner in (account, partner):
        response = client.post(
            "/api/cash-boundary-coverages",
            json={**coverage(env), "account_id": owner},
            headers=headers(env),
        )
        assert response.status_code == 201, response.text
    assert [row["id"] for row in read(env)["flows"]] == [flow_id]
    assert read(env, partner)["flows"] == []
    old = headers(env)
    path = f"/api/external-flows/{flow_id}"
    moved = client.patch(path, json={"account_id": partner}, headers=old)
    assert moved.status_code == 200, moved.text
    assert moved.json()["account_id"] == partner
    assert moved.json()["scope_membership"] == "unknown"
    source, destination = read(env), read(env, partner)
    assert source["flows"] == []
    assert [row["id"] for row in destination["flows"]] == [flow_id]
    assert destination["flows"][0]["account_id"] == partner
    assert source["evidence_token"] == destination["evidence_token"]
    for ledger in (source, destination):
        assert ledger["cash_coverages"][0]["coverage_state"] == "unknown"
    assert client.patch(path, json={"account_id": account}, headers=old).status_code == 409
    assert read(env, partner)["flows"][0]["account_id"] == partner
    assert list(session.scalars(select(AccountPerformanceScopeMembership))) == []
    close_reporting_month(session, month)
    blocked = client.patch(path, json={"account_id": account}, headers=headers(env))
    assert blocked.status_code == 409, blocked.text
    assert read(env)["flows"] == []
    assert read(env, partner)["flows"][0]["id"] == flow_id


@pytest.mark.parametrize("kind", ["cash", "in-kind"])
def test_coverage_explicit_and_closed_guard_even_with_fresh_token(env, kind):
    client, session, _, month, _, _ = env
    path = f"/api/{kind}-boundary-coverages"
    stale = headers(env)
    close_reporting_month(session, month)
    assert client.post(path, json=coverage(env), headers=stale).status_code == 409
    response = client.post(path, json=coverage(env), headers=headers(env))
    assert response.status_code == 409, response.text
    assert read(env)["cash_coverages"] == read(env)["in_kind_coverages"] == []


def test_correction_invalidates_cash_but_does_not_attest_in_kind(env):
    client = env[0]
    created = client.post(
        "/api/external-flows",
        json=flow(env, scope_membership="stable_in_scope"),
        headers=headers(env),
    )
    assert created.status_code == 201
    assert (
        client.post(
            "/api/cash-boundary-coverages", json=coverage(env), headers=headers(env)
        ).status_code
        == 201
    )
    assert read(env)["cash_coverages"][0]["coverage_state"] == "complete"
    response = client.patch(
        f"/api/external-flows/{created.json()['id']}",
        json={"boundary_amount": {"amount": "124.45", "currency": "RUB"}},
        headers=headers(env),
    )
    assert response.status_code == 200, response.text
    assert read(env)["cash_coverages"][0]["coverage_state"] == "unknown"
    assert read(env)["in_kind_coverages"] == []


def test_ledger_change_rejects_old_attestation_and_independent_coverages(env):
    client = env[0]
    token = headers(env)
    assert client.post("/api/external-flows", json=flow(env)).status_code == 201
    assert (
        client.post("/api/cash-boundary-coverages", json=coverage(env), headers=token).status_code
        == 409
    )
    assert (
        client.post(
            "/api/cash-boundary-coverages", json=coverage(env), headers=headers(env)
        ).status_code
        == 201
    )
    assert read(env)["in_kind_coverages"] == []
    assert (
        client.post(
            "/api/in-kind-boundary-coverages", json=coverage(env), headers=headers(env)
        ).status_code
        == 201
    )
    assert read(env)["in_kind_coverages"][0]["coverage_state"] == "complete"


def test_transfer_classifications_are_canonical(env):
    client = env[0]
    source = flow(env, scope_membership="stable_in_scope")
    source.update(direction="withdrawal", kind="external_withdrawal")
    first = client.post("/api/external-flows", json=source).json()
    other = flow(env, scope_membership="stable_in_scope")
    other["account_id"] = env[5]
    second = client.post("/api/external-flows", json=other).json()
    linked = client.post(
        "/api/transfer-links", json={"flow_ids": [first["id"], second["id"]]}, headers=headers(env)
    )
    assert linked.status_code == 201, linked.text
    row = read(env)["flows"][0]
    assert row["portfolio_scope_classification"] == "internal_transfer"
    assert row["account_scope_classification"] == "external_withdrawal"
    # Moving a linked leg onto its partner's account still uses canonical validation.
    token = headers(env)
    rejected = client.patch(
        f"/api/external-flows/{first['id']}", json={"account_id": env[5]}, headers=token
    )
    assert rejected.status_code == 422, rejected.text
    assert headers(env) == token
    assert read(env)["flows"][0]["account_id"] == env[4]
    assert read(env)["flows"][0]["transfer_link_id"] == linked.json()["id"]


def test_failed_write_rolls_back_and_token_remains_usable(env):
    token = headers(env)
    assert env[0].post(
        "/api/external-flows", json=flow(env, transfer_link_id=9999), headers=token
    ).status_code in {404, 422}
    assert headers(env) == token
    assert env[0].post("/api/external-flows", json=flow(env), headers=token).status_code == 201


def test_explicit_zero_history_then_reclose_rereads_available_metrics(tmp_path):
    from sqlalchemy import delete
    from test_r08_02_portfolio_xirr import END, START, _history

    from hermes_finance.persistence import CashBoundaryCoverage

    session, database, opening, closing, account = _history(tmp_path, close_months=False)
    try:
        session.execute(delete(CashBoundaryCoverage))
        session.commit()
        with TestClient(create_app(database=database)) as client:
            params = {"start_date": str(START), "end_date": str(END)}
            close_reporting_month(session, opening)
            close_reporting_month(session, closing)
            initial = client.get("/api/performance/readiness", params=params).json()
            assert initial["xirr"]["availability"] != "available"
            # Owner explicitly reopens; preparation itself never changes month status.
            assert client.post(f"/api/months/{opening}/reopen").status_code == 200
            assert client.post(f"/api/months/{closing}/reopen").status_code == 200
            inspected = client.get(
                "/api/performance/preparation", params={**params, "account_id": account}
            ).json()
            assert inspected["flows"] == []
            response = client.post(
                "/api/cash-boundary-coverages",
                headers={"X-Performance-Evidence": inspected["evidence_token"]},
                json={
                    "account_id": account,
                    "covered_from": str(START),
                    "covered_to": str(END),
                    "coverage_state": "complete",
                    "provenance_kind": "owner_attestation",
                },
            )
            assert response.status_code == 201, response.text
            # Saved coverage alone is not computability while boundary months are open.
            assert (
                client.get("/api/performance/readiness", params=params).json()["xirr"][
                    "availability"
                ]
                != "available"
            )
            assert client.post(f"/api/months/{opening}/close").status_code == 200
            assert client.post(f"/api/months/{closing}/close").status_code == 200
            after = client.get("/api/performance/readiness", params=params).json()
            assert after["xirr"]["availability"] == "available"
            assert after["twrr"]["availability"] == "available"
    finally:
        session.close()
        database.engine.dispose()
