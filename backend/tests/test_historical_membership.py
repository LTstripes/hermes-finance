"""Synthetic finite membership lifecycle, capture fencing and HTTP form safety."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_r08_01a_external_flows import _environment

from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Account,
    CashBoundaryCoverage,
    InKindBoundaryCoverage,
    ObservedValuationPoint,
    ReportingMonth,
)
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership as Membership,
)
from hermes_finance.services.external_flows import create_external_flow
from hermes_finance.services.historical_membership import Interval, stage_replace, state_identity
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.valuation_boundaries import create_observed_valuation_point
from hermes_finance.services.valuation_material_signature import material_signature_for_boundary

START = date(2030, 5, 1)
END = date(2030, 5, 31)


@pytest.fixture
def env(tmp_path):
    session, database, month, account, partner = _environment(tmp_path)
    with TestClient(create_app(database=database)) as client:
        yield client, session, database, month, account, partner
    session.close()
    database.engine.dispose()


def context(env):
    return dict(account_id=env[4], start_date=str(START), end_date=str(END), scope="account")


def read(env):
    response = env[0].get("/api/performance/membership", params=context(env))
    assert response.status_code == 200, response.text
    return response.json()


def payload(env, **changes):
    return (
        dict(
            **context(env),
            form_token=read(env)["form_token"],
            replaced_ids=[],
            replacements=[
                dict(effective_from=str(START), effective_to=str(END), include_in_returns=True)
            ],
            attested=True,
        )
        | changes
    )


def post(env, body):
    return env[0].post("/api/performance/membership", json=body)


def membership(env, account=None, start=START, end=END, included=True):
    row = Membership(
        account_id=account or env[4],
        effective_from=start,
        effective_to=end,
        include_in_returns=included,
    )
    env[1].add(row)
    env[1].commit()
    return row.id


def flow(env, account=None):
    return create_external_flow(
        env[1],
        reporting_month_id=env[3],
        account_id=account or env[4],
        event_date=date(2030, 5, 12),
        boundary_amount="10.00",
        direction="contribution",
        kind="external_contribution",
        scope_membership="stable_in_scope",
    )


def signature(env, target, scope="account", account=None):
    return material_signature_for_boundary(
        env[1],
        external_flow_id=target.id,
        scope=scope,
        account_id=(account or env[4]) if scope == "account" else None,
    )


def capture(env, target, scope="account", account=None, expected=None):
    return create_observed_valuation_point(
        env[1],
        reporting_month_id=env[3],
        observed_date=target.event_date,
        total_value="100.00",
        performance_currency="RUB",
        provenance_kind="synthetic",
        relation="pre_external_flow",
        scope=scope,
        account_id=(account or env[4]) if scope == "account" else None,
        external_flow_id=target.id,
        expected_material_signature=expected or signature(env, target, scope, account),
    )


def test_explicit_creation_does_not_change_current_flags_and_rereads_both_solvers(env):
    before = env[1].get(Account, env[4]).include_in_returns
    body = payload(env)
    body["replacements"][0]["include_in_returns"] = False
    response = post(env, body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["rows"][0]["include_in_returns"] is False
    assert result["identity"] == read(env)["identity"]
    assert result["readiness"]["xirr"]["metric"] == "xirr"
    assert result["readiness"]["twrr"]["metric"] == "twrr"
    env[1].expire_all()
    assert env[1].get(Account, env[4]).include_in_returns == before


def test_duplicate_concurrent_submission_has_one_winner(env):
    body = payload(env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: post(env, body).status_code, range(2)))
    assert sorted(results) == [200, 409]
    assert len(read(env)["rows"]) == 1


def test_stale_form_and_restore_epoch_and_restart_fail_closed(env):
    body = payload(env)
    membership(env, account=env[5])
    assert post(env, body).status_code == 409
    body = payload(env)
    # A same-material restore still retires forms; no schema revision is needed.
    with env[2].maintenance.restore():
        pass
    assert post(env, body).status_code == 409
    body = payload(env)
    with TestClient(create_app(database=env[2])) as restarted:
        assert restarted.post("/api/performance/membership", json=body).status_code == 409


@pytest.mark.parametrize("end", [None, "2030-04-30"])
def test_finite_ordered_intervals_only(env, end):
    body = payload(env)
    body["replacements"][0]["effective_to"] = end
    assert post(env, body).status_code in (409, 422)
    assert read(env)["rows"] == []


def test_overlap_rejected_adjacency_and_unknown_gap_preserved(env):
    membership(env, end=date(2030, 5, 10))
    body = payload(env)
    body["replacements"][0]["effective_from"] = "2030-05-10"
    assert post(env, body).status_code == 409
    body = payload(env)
    body["replacements"][0]["effective_from"] = "2030-05-11"
    body["replacements"][0]["effective_to"] = "2030-05-12"
    assert post(env, body).status_code == 200
    body = payload(env)
    body["replacements"][0]["effective_from"] = "2030-05-20"
    assert post(env, body).status_code == 200
    assert len(read(env)["rows"]) == 3


def test_open_ended_rows_cannot_be_replaced_and_block_overlap(env):
    row_id = membership(env, end=None)
    assert post(env, payload(env, replaced_ids=[row_id])).status_code == 409
    assert post(env, payload(env)).status_code == 409
    body = payload(env)
    body["replacements"][0].update(effective_from="2030-04-01", effective_to="2030-04-30")
    assert post(env, body).status_code == 200


def test_ambiguous_rows_require_complete_explicit_correction(env):
    first = membership(env)
    second = membership(env, start=date(2030, 5, 5), included=False)
    assert post(env, payload(env, replaced_ids=[first])).status_code == 409
    assert post(env, payload(env, replaced_ids=[first, second])).status_code == 200
    assert len(read(env)["rows"]) == 1


def test_withdrawal_and_duplicate_identity_reject(env):
    row_id = membership(env)
    assert (
        post(env, payload(env, replaced_ids=[row_id, row_id], replacements=[])).status_code == 409
    )
    body = payload(env, replaced_ids=[row_id], replacements=[])
    assert post(env, body).status_code == 200
    assert read(env)["rows"] == []
    assert post(env, body).status_code == 409


@pytest.mark.parametrize("boundary", ["old", "new", "snapshot"])
def test_closed_full_union_includes_old_new_and_snapshot_dates(env, boundary):
    row_id = membership(env, start=date(2030, 4, 1), end=date(2030, 4, 30))
    april = create_reporting_month(env[1], year=2030, month=4, snapshot_date=date(2030, 4, 30))
    month = env[1].get(ReportingMonth, env[3] if boundary == "new" else april.id)
    month.status = "closed"
    if boundary == "snapshot":
        month.period_start = date(2030, 3, 1)
        month.period_end = date(2030, 3, 31)
        month.snapshot_date = START
    env[1].commit()
    assert post(env, payload(env, replaced_ids=[row_id])).status_code == 409
    assert read(env)["rows"][0]["effective_from"] == "2030-04-01"


def test_closed_gap_is_not_filled_by_union(env):
    row_id = membership(env, start=date(2030, 4, 1), end=date(2030, 4, 30))
    month = env[1].get(ReportingMonth, env[3])
    month.status = "closed"
    env[1].commit()
    body = payload(env, replaced_ids=[row_id])
    body["replacements"][0].update(effective_from="2030-06-01", effective_to="2030-06-30")
    assert post(env, body).status_code == 200


def test_exact_invalidation_preserves_unrelated_accounts_and_immutable_flows(env):
    row_id = membership(env)
    membership(env, account=env[5])
    target = flow(env, env[5])
    own = flow(env)
    own_observation = capture(env, own).id
    portfolio = capture(env, target, "portfolio").id
    unrelated = capture(env, target, account=env[5]).id
    for model in (CashBoundaryCoverage, InKindBoundaryCoverage):
        for account in (env[4], env[5]):
            env[1].add(
                model(
                    account_id=account,
                    covered_from=date(2030, 4, 1),
                    covered_to=date(2030, 6, 30),
                    coverage_state="complete",
                    provenance_kind="owner_attestation",
                    provenance_reference="synthetic",
                )
            )
    env[1].commit()
    body = payload(env, replaced_ids=[row_id])
    body["replacements"][0]["include_in_returns"] = False
    response = post(env, body)
    assert response.status_code == 200, response.text
    assert sorted(response.json()["affected"]["retired_observation_ids"]) == sorted(
        [own_observation, portfolio]
    )
    env[1].expire_all()
    assert [r.id for r in env[1].scalars(select(ObservedValuationPoint))] == [unrelated]
    for model in (CashBoundaryCoverage, InKindBoundaryCoverage):
        for row in env[1].scalars(select(model)):
            assert row.coverage_state == ("unknown" if row.account_id == env[4] else "complete")
            assert row.provenance_reference == "synthetic"
            assert row.covered_from == date(2030, 4, 1)
            assert row.covered_to == date(2030, 6, 30)
    assert target.scope_membership == "stable_in_scope"


@pytest.mark.parametrize("change", ["flag", "endpoint", "withdraw"])
def test_inflight_capture_rejected_after_membership_correction(env, change):
    row_id = membership(env)
    target = flow(env)
    old = signature(env, target)
    body = payload(env, replaced_ids=[row_id])
    if change == "flag":
        body["replacements"][0]["include_in_returns"] = False
    elif change == "endpoint":
        body["replacements"][0]["effective_from"] = "2030-05-02"
    else:
        body["replacements"] = []
    assert post(env, body).status_code == 200
    with pytest.raises(ValueError, match="changed materially"):
        capture(env, target, expected=old)
    env[1].rollback()
    if change != "withdraw":
        assert capture(env, target).material_signature != old


def test_scope_binding_metadata_and_legacy_v1(env):
    membership(env)
    partner_id = membership(env, account=env[5])
    target = flow(env)
    account_signature = signature(env, target)
    portfolio_signature = signature(env, target, "portfolio")
    partner = env[1].get(Membership, partner_id)
    partner.include_in_returns = False
    env[1].commit()
    assert signature(env, target) == account_signature
    assert signature(env, target, "portfolio") != portfolio_signature
    env[1].get(Account, env[4]).name = "Synthetic Renamed"
    env[1].get(Account, env[4]).include_in_returns = False
    env[1].commit()
    assert signature(env, target) == account_signature
    with pytest.raises(ValueError, match="changed materially"):
        capture(env, target, expected="0" * 64)
    env[1].rollback()


def test_rollback_restores_history_and_invalidation(env):
    row_id = membership(env)
    target = flow(env)
    point_id = capture(env, target).id
    before = state_identity(env[1])
    stage_replace(
        env[1],
        account_id=env[4],
        expected_identity=before,
        replaced_ids=[row_id],
        replacements=[Interval(START, END, False)],
    )
    env[1].rollback()
    assert state_identity(env[1]) == before
    assert env[1].get(ObservedValuationPoint, point_id) is not None


def test_stored_observation_parent_closed_even_when_canonical_target_draft(env):
    row_id = membership(env)
    target = flow(env)
    observation = capture(env, target)
    other = create_reporting_month(env[1], year=2030, month=8, snapshot_date=date(2030, 8, 31))
    observation.reporting_month_id = other.id
    other.status = "closed"
    env[1].commit()
    assert post(env, payload(env, replaced_ids=[row_id], replacements=[])).status_code == 409


def test_new_capture_after_form_opening_makes_form_stale(env):
    row_id = membership(env)
    target = flow(env)
    body = payload(env, replaced_ids=[row_id], replacements=[])
    capture(env, target)
    assert post(env, body).status_code == 409


def test_portfolio_group_without_changed_account_flow_is_retired(env):
    from hermes_finance.services.valuation_boundaries import create_external_flow_boundary_group

    row_id = membership(env)
    membership(env, account=env[5])
    target = flow(env, account=env[5])
    group = create_external_flow_boundary_group(
        env[1],
        reporting_month_id=env[3],
        boundary_date=target.event_date,
        flow_ids=[target.id],
        scope="portfolio",
    )
    original = material_signature_for_boundary(
        env[1], scope="portfolio", account_id=None, boundary_group_id=group.id
    )
    point = create_observed_valuation_point(
        env[1],
        reporting_month_id=env[3],
        observed_date=target.event_date,
        total_value="100.00",
        performance_currency="RUB",
        provenance_kind="synthetic",
        relation="pre_external_flow",
        scope="portfolio",
        boundary_group_id=group.id,
        expected_material_signature=original,
    )
    point_id = point.id
    response = post(env, payload(env, replaced_ids=[row_id], replacements=[]))
    assert response.status_code == 200, response.text
    assert response.json()["affected"]["retired_observation_ids"] == [point_id]
    env[1].expire_all()
    assert (
        material_signature_for_boundary(
            env[1], scope="portfolio", account_id=None, boundary_group_id=group.id
        )
        is None
    )


def test_form_identity_covers_unobserved_groups_and_members(env):
    from hermes_finance.persistence import (
        ExternalFlowBoundaryGroup,
        ExternalFlowBoundaryGroupMember,
    )

    target = flow(env)
    first = state_identity(env[1])
    group = ExternalFlowBoundaryGroup(
        reporting_month_id=env[3], scope="portfolio", boundary_date=target.event_date
    )
    env[1].add(group)
    env[1].commit()
    second = state_identity(env[1])
    env[1].add(
        ExternalFlowBoundaryGroupMember(boundary_group_id=group.id, external_flow_id=target.id)
    )
    env[1].commit()
    assert first != second != state_identity(env[1])


def test_a_b_a_does_not_revive_old_form(env):
    old = payload(env)
    other_form = payload(env)
    response = post(env, other_form)
    row_id = response.json()["rows"][0]["id"]
    assert post(env, payload(env, replaced_ids=[row_id], replacements=[])).status_code == 200
    assert read(env)["rows"] == []
    assert post(env, old).status_code == 409


@pytest.mark.parametrize("first", ["close", "membership"])
def test_close_and_membership_serialize_under_writer_reservation(env, first):
    from threading import Event

    from sqlalchemy import text

    from hermes_finance.services.reporting_months import close_reporting_month

    ready, release, attempting = Event(), Event(), Event()
    expected = state_identity(env[1])

    def operation(kind, hold):
        with env[2].session_factory() as session:
            try:
                if not hold:
                    attempting.set()
                session.execute(text("UPDATE reporting_months SET status = status WHERE 0"))
                if hold:
                    ready.set()
                    assert release.wait(10)
                if kind == "close":
                    close_reporting_month(session, env[3])
                else:
                    stage_replace(
                        session,
                        account_id=env[4],
                        expected_identity=expected,
                        replaced_ids=[],
                        replacements=[Interval(START, END, True)],
                    )
                    session.commit()
                return "ok"
            except ValueError:
                session.rollback()
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        winner = pool.submit(operation, first, True)
        assert ready.wait(10)
        loser = pool.submit(operation, "membership" if first == "close" else "close", False)
        assert attempting.wait(10)
        release.set()
        assert winner.result(timeout=10) == "ok"
        assert loser.result(timeout=10) == ("rejected" if first == "close" else "ok")
    assert len(read(env)["rows"]) == (0 if first == "close" else 1)


def test_restore_retires_forms_issued_while_active_operations_drain(env):
    from time import monotonic, sleep

    from hermes_finance.api.historical_membership import Context, Registry

    maintenance = env[2].maintenance
    registry = Registry()
    request = Context(**context(env))

    def restore():
        with maintenance.restore():
            pass

    with ThreadPoolExecutor(max_workers=1) as pool:
        with maintenance.operation():
            future = pool.submit(restore)
            deadline = monotonic() + 5
            while not maintenance.is_restoring and monotonic() < deadline:
                sleep(0.001)
            assert maintenance.is_restoring
            token = registry.issue(maintenance.form_epoch, request, "synthetic-state")
        future.result(timeout=5)
    with pytest.raises(ValueError, match="restored"):
        registry.consume(token, maintenance.form_epoch, request)


def test_api_failure_after_staged_invalidation_rolls_everything_back(env, monkeypatch):
    from hermes_finance.api import historical_membership as api

    row_id = membership(env)
    capture(env, flow(env))
    before = state_identity(env[1])
    body = payload(env, replaced_ids=[row_id], replacements=[])
    original = api.stage_replace

    def fail_after_stage(*args, **kwargs):
        original(*args, **kwargs)
        raise ValueError("synthetic failure after invalidation")

    monkeypatch.setattr(api, "stage_replace", fail_after_stage)
    assert post(env, body).status_code == 409
    env[1].expire_all()
    assert state_identity(env[1]) == before


def test_readback_failure_is_not_success_and_original_post_cannot_be_replayed(env, monkeypatch):
    from starlette.responses import JSONResponse

    from hermes_finance.api import historical_membership as api

    body = payload(env)
    monkeypatch.setattr(
        api,
        "read_performance_readiness",
        lambda *args, **kwargs: JSONResponse(status_code=503, content={"error": "synthetic"}),
    )
    assert post(env, body).status_code == 503
    assert post(env, body).status_code == 409
    env[1].expire_all()
    assert len(list(env[1].scalars(select(Membership)))) == 1
