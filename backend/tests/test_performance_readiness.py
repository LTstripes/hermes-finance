"""Synthetic acceptance of the coherent read projection, without new calculations."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from test_r08_02_portfolio_xirr import END, MID, START, _history
from test_r08_03_portfolio_twrr import END as TWRR_END
from test_r08_03_portfolio_twrr import FIRST_FLOW_DATE, _close_interval, _environment, _flow

from hermes_finance.domain import AccountType, XirrAvailabilityStatus, XirrQuality
from hermes_finance.domain.performance_availability import AvailabilityReasonCode as R
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership,
    CashBoundaryCoverage,
    InKindBoundaryCoverage,
)
from hermes_finance.services import performance_readiness as service
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash_boundary_coverage import attest_cash_boundary_history


@pytest.fixture
def history(tmp_path):
    session, database, opening, closing, account = _history(tmp_path, closing="1000.00")
    yield session, database, opening, closing, account
    session.close()
    database.engine.dispose()


def read(session, **kwargs):
    return service.readiness_for_interval(session, start_date=START, end_date=END, **kwargs)


def test_exact_zero_and_legacy_endpoints_unchanged_read_only(history):
    session, database, _, _, _ = history
    before = list(database.engine.raw_connection().iterdump())
    with TestClient(create_app(database=database)) as client:
        params = {"start_date": str(START), "end_date": str(END)}
        previous = {
            name: client.get(f"/api/performance/{name}", params=params).json()
            for name in ("availability", "xirr", "twrr")
        }
        response = client.get("/api/performance/readiness", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["schema_version"] == 1
        assert body["xirr"] == previous["xirr"]
        assert body["twrr"] == previous["twrr"]
        assert body["evidence"] == previous["availability"]
        assert body["diagnostics"] == []
        assert body["xirr"]["value"] == body["twrr"]["value"] == "0"
        assert body["xirr"]["annualized"] is True
        assert body["twrr"]["annualized"] is False
        for name, old in previous.items():
            assert client.get(f"/api/performance/{name}", params=params).json() == old
        schema = client.get("/openapi.json").json()
        assert "/api/performance/readiness" in schema["paths"]
        assert set(schema["paths"]["/api/performance/readiness"]) == {"get"}
    assert list(database.engine.raw_connection().iterdump()) == before


def test_xirr_available_despite_missing_twrr_observations(tmp_path):
    session, database, opening, closing, account = _environment(tmp_path)
    try:
        flow = _flow(
            session,
            closing,
            account,
            event_date=FIRST_FLOW_DATE,
            amount="100.00",
            direction="contribution",
            kind="external_contribution",
        )
        attest_cash_boundary_history(
            session, account_id=account, covered_from=START, covered_to=TWRR_END
        )
        _close_interval(session, opening, closing)
        result = service.readiness_for_interval(session, start_date=START, end_date=TWRR_END)
        assert result.xirr.is_available
        assert not result.twrr.is_available
        assert not result.evidence.is_available
        diagnostics = [d for d in result.diagnostics if d.key == "valuation_boundary"]
        assert len(diagnostics) == 1
        assert diagnostics[0].affected_metrics == ("twrr",)
        assert diagnostics[0].refs.external_flow_ids == (flow.id,)
        assert diagnostics[0].action.capability == "not_implemented"
    finally:
        session.close()
        database.engine.dispose()


def test_catalog_cash_and_in_kind_sets_remain_distinct(history):
    session, _, _, _, included = history
    excluded = create_account(session, name="Synthetic excluded", account_type=AccountType.CASH)
    missing = create_account(session, name="Synthetic gap", account_type=AccountType.CASH)
    cash_only = create_account(session, name="Synthetic cash only", account_type=AccountType.CASH)
    session.add_all(
        [
            AccountPerformanceScopeMembership(
                account_id=excluded.id, effective_from=date(2029, 1, 1), include_in_returns=False
            ),
            AccountPerformanceScopeMembership(
                account_id=cash_only.id, effective_from=date(2029, 1, 1), include_in_returns=True
            ),
        ]
    )
    session.commit()
    result = read(session)
    assert set(result.evidence.scope_membership.account_ids) == {
        included,
        excluded.id,
        missing.id,
        cash_only.id,
    }
    assert set(result.evidence.cash_boundary_coverage.account_ids) == {included, cash_only.id}
    assert result.evidence.in_kind_boundary_coverage.account_ids == (included,)
    diagnostic = next(d for d in result.diagnostics if d.key == "membership_history")
    assert diagnostic.refs.account_ids == (missing.id,)
    assert diagnostic.action.capability == "available"


def test_empty_ledger_is_not_complete_and_multiple_evidence_causes(history, monkeypatch):
    session, _, _, _, account = history
    session.execute(delete(CashBoundaryCoverage))
    session.commit()
    real = service.performance_availability_for_interval

    def with_legacy(*args, **kwargs):
        result = real(*args, **kwargs)
        return replace(
            result,
            external_flows=replace(result.external_flows, legacy_unclassified_flow_ids=(73,)),
        )

    monkeypatch.setattr(service, "performance_availability_for_interval", with_legacy)
    result = read(session)
    assert not result.xirr.is_available
    diagnostics = {d.key: d for d in result.diagnostics}
    assert diagnostics["cash_history"].refs.account_ids == (account,)
    assert diagnostics["cash_history"].action.capability == "requires_reopen"
    assert diagnostics["legacy_flows"].refs.legacy_flow_ids == (73,)
    assert diagnostics["legacy_flows"].action.capability == "not_implemented"
    assert result.evidence.external_flows.flows == ()


@pytest.mark.parametrize(
    "code,key",
    [
        ("not_computable_xirr_root_ambiguity", "xirr_ambiguous"),
        ("not_computable_future_flow_problem", "unknown_reason"),
    ],
)
def test_final_solver_not_prerequisites_controls_metric(history, monkeypatch, code, key):
    session = history[0]
    real = service.xirr_for_interval

    def unavailable(*args, **kwargs):
        return replace(
            real(*args, **kwargs),
            availability=XirrAvailabilityStatus.NOT_COMPUTABLE,
            quality=XirrQuality.UNAVAILABLE,
            annualized_rate=None,
            reason_codes=(code,),
        )

    monkeypatch.setattr(service, "xirr_for_interval", unavailable)
    result = read(session)
    assert result.evidence.xirr.is_available
    assert not result.xirr.is_available
    assert result.twrr.is_available
    assert result.diagnostics[0].key == key
    assert result.diagnostics[0].affected_metrics == ("xirr",)
    assert result.diagnostics[0].action.capability == "unsupported"
    assert result.diagnostics[0].refs == service.DiagnosticRefs()


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": 999},
        {"start_date": MID},
        {"performance_currency": "USD"},
        {"quality": XirrQuality.UNAVAILABLE},
        {"annualized_rate": None},
        {"annualized_rate": Decimal("NaN")},
    ],
)
def test_mismatched_final_dto_is_technical_error(history, monkeypatch, changes):
    session, database, *_ = history
    real = service.xirr_for_interval
    monkeypatch.setattr(
        service, "xirr_for_interval", lambda *a, **k: replace(real(*a, **k), **changes)
    )
    with TestClient(create_app(database=database)) as client:
        response = client.get(
            "/api/performance/readiness", params={"start_date": str(START), "end_date": str(END)}
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "performance_readiness_technical_error"
        assert "diagnostics" not in response.json()


def test_failure_does_not_leak_exception_or_claim_missing_financial_data(history, monkeypatch):
    _, database, *_ = history

    def fail(*args, **kwargs):
        raise RuntimeError("SYNTHETIC-PRIVATE-PATH")

    monkeypatch.setattr(service, "twrr_for_interval", fail)
    with TestClient(create_app(database=database)) as client:
        response = client.get(
            "/api/performance/readiness", params={"start_date": str(START), "end_date": str(END)}
        )
        assert response.status_code == 503
        assert "SYNTHETIC-PRIVATE-PATH" not in response.text


def test_missing_boundary_is_exact_date_without_invented_month(history):
    result = service.readiness_for_interval(history[0], start_date=date(2029, 1, 31), end_date=END)
    diagnostic = next(d for d in result.diagnostics if d.key == "opening_valuation")
    assert diagnostic.refs.dates == (date(2029, 1, 31),)
    assert diagnostic.refs.reporting_month_ids == ()


def test_one_snapshot_across_evidence_and_both_solvers(history, monkeypatch):
    session, database, *_ = history
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one() == "wal"
    real = service.xirr_for_interval
    committed = False

    def interleave(*args, **kwargs):
        nonlocal committed
        if not committed:
            committed = True
            with database.session_factory() as writer:
                writer.execute(delete(CashBoundaryCoverage))
                writer.commit()
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "xirr_for_interval", interleave)
    old = read(session)
    assert old.evidence.is_available and old.xirr.is_available and old.twrr.is_available
    fresh = read(session)
    assert (
        not fresh.evidence.is_available
        and not fresh.xirr.is_available
        and not fresh.twrr.is_available
    )


def test_account_request_keeps_identity_and_private_references_out(history):
    session, database, _, _, account = history
    coverage = session.scalar(select(CashBoundaryCoverage))
    coverage.provenance_reference = "SYNTHETIC-PRIVATE-PATH"
    session.commit()
    with TestClient(create_app(database=database)) as client:
        params = {
            "start_date": str(START),
            "end_date": str(END),
            "scope": "account",
            "account_id": account,
        }
        response = client.get("/api/performance/readiness", params=params)
        assert response.status_code == 200
        assert "SYNTHETIC-PRIVATE-PATH" not in response.text
        body = response.json()
        assert body["scope"] == body["xirr"]["scope"] == body["twrr"]["scope"] == "account"
        assert (
            body["account_id"]
            == body["xirr"]["account_id"]
            == body["twrr"]["account_id"]
            == account
        )


@pytest.mark.parametrize(
    "query",
    [
        "start_date=2030-01-31",
        "start_date=invalid&end_date=2032-01-31",
        "start_date=2032-01-31&end_date=2030-01-31",
        "start_date=2030-01-31&end_date=2032-01-31&scope=account",
        "start_date=2030-01-31&end_date=2032-01-31&account_id=1",
        "start_date=2030-01-31&start_date=2031-01-31&end_date=2032-01-31",
    ],
)
def test_invalid_context_is_not_technical_or_defaulted(history, query):
    with TestClient(create_app(database=history[1])) as client:
        response = client.get(f"/api/performance/readiness?{query}")
        assert response.status_code == 422


def test_capabilities_use_exact_rules():
    assert service._RULES[R.SNAPSHOT_DATE_MISSING][2] == "source_required"
    assert service._RULES[R.CURRENCY_CONVERSION_INCOMPLETE][2] == "unsupported"
    assert set(R).issubset(service._RULES)


def test_cash_complete_does_not_cover_in_kind(history):
    session = history[0]
    session.execute(delete(InKindBoundaryCoverage))
    session.commit()
    result = read(session)
    assert result.evidence.cash_boundary_coverage.is_complete
    assert not result.xirr.is_available and not result.twrr.is_available
    diagnostic = next(d for d in result.diagnostics if d.key == "in_kind_history")
    assert diagnostic.refs.account_ids == (history[4],)
    assert diagnostic.action.capability == "requires_reopen"


def test_open_interval_cash_attestation_is_actionable(tmp_path):
    session, database, *_ = _history(tmp_path, close_months=False)
    try:
        session.execute(delete(CashBoundaryCoverage))
        session.commit()
        result = read(session)
        diagnostic = next(d for d in result.diagnostics if d.key == "cash_history")
        assert diagnostic.action.capability == "available"
        assert diagnostic.category == "actionable"
        assert any(d.key == "no_recorded_external_flows" for d in result.diagnostics)
    finally:
        session.close()
        database.engine.dispose()


def test_unknown_account_is_context_error(history):
    with TestClient(create_app(database=history[1])) as client:
        response = client.get(
            "/api/performance/readiness",
            params={
                "start_date": str(START),
                "end_date": str(END),
                "scope": "account",
                "account_id": 999,
            },
        )
        assert response.status_code == 422


def test_snapshot_rejects_accidental_write_and_rolls_back(history, monkeypatch):
    session = history[0]

    def mutate(session, **kwargs):
        session.execute(delete(CashBoundaryCoverage))

    monkeypatch.setattr(service, "xirr_for_interval", mutate)
    with pytest.raises(Exception):
        read(session)
    assert session.scalar(select(CashBoundaryCoverage)) is not None
