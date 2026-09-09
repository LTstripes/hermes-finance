"""API + deterministic JSON export tests for the Scenario Lab owner surface (#329).

Covers the issue #329 acceptance set: HTTP evaluation equals the
accepted Scenario Lab service semantics for every supported shock
(equity, deposit rate, inflation, FX candidate scope), deterministic
error mapping, full envelope exposure, byte-deterministic JSON export
that shares one adapter with the normal response, no binary floats, no
DB mutation and no provider/network access.

All data is synthetic (temp sqlite DBs). The FX baseline assertions
mirror the reconciled main semantics: matching Instrument.currency rows
stay candidate scope ``unknown`` and the exact capital aggregates are
``unavailable`` with ``fx_translation_basis_unavailable`` — never
naively revalued.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Base,
    DepositSnapshot,
    ExpectedCashFlow,
    Instrument,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.scenario_lab import evaluate_scenario_lab

EQUITY_10 = {"equity_drawdown": {"drawdown_pct": "10"}}
DEPOSIT_8 = {
    "deposit_rate_assumption": {
        "assumed_annual_rate_pct": "8",
        "all_eligible_deposits": True,
    }
}
INFLATION_12 = {"inflation_real_value": {"annual_inflation_pct": "12"}}
FX_USD_10 = {
    "fx_translation_shock": {
        "target_currency": "USD",
        "reporting_value_change_pct": "10",
    }
}

ENVELOPE_KEYS = {
    "contract_version",
    "calculation_version",
    "shock_schema_version",
    "reporting_month",
    "base_fingerprint",
    "semantic_fingerprint",
    "normalized_shock_input",
    "normalized_target_scope",
    "assumptions",
    "base",
    "stressed",
    "impact",
    "row_applicability",
    "metric_support",
    "coverage",
    "affected_canonical_refs",
    "warnings",
    "presentation_metadata",
}


@pytest.fixture
def database(tmp_path: Path):
    db = create_database(tmp_path / "scenario-lab-api.db")
    Base.metadata.create_all(db.engine)
    try:
        yield db
    finally:
        db.engine.dispose()


@pytest.fixture
def session(database):
    s = database.session_factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client(database) -> Generator[TestClient, None, None]:
    with TestClient(create_app(database)) as test_client:
        yield test_client


def _month(session, *, year: int = 2030, month: int = 5) -> ReportingMonth:
    return create_reporting_month(
        session, year=year, month=month, snapshot_date=date(year, month, 12)
    )


def _account(session, *, name: str = "Broker", account_type: AccountType = AccountType.BROKERAGE):
    return create_account(session, name=name, account_type=account_type)


def _instrument(session, *, name: str, instrument_type: InstrumentType, currency: str = "RUB"):
    return create_instrument(session, name=name, instrument_type=instrument_type, currency=currency)


def _position(session, month_id: int, account_id: int, instrument_id: int, amount: str):
    return create_position_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        quantity="1",
        average_cost_per_unit="1.00",
        market_price_per_unit=amount,
        price_date=date(2030, 5, 12),
    )


def _deposit(session, month_id: int, account_id: int):
    return create_deposit_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        name="Dep",
        deposit_type="deposit",
        balance="120000.00",
        annual_rate="6.00",
    )


def _coupon(session, month_id: int, account_id: int, instrument_id: int):
    return create_expected_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type="coupon",
        expected_date=date(2030, 6, 1),
        gross_amount="100.00",
        currency="RUB",
        source="synthetic",
        source_as_of_date=date(2030, 5, 12),
        forecast_version="v1",
    )


def _seed_equity(session, *, month: int = 5) -> int:
    """Brokerage: RUB stock 100000.00 + RUB bond 50000.00. Returns month id."""
    month_row = _month(session, month=month)
    account = _account(session)
    stock = _instrument(session, name="Stock", instrument_type=InstrumentType.STOCK)
    bond = _instrument(session, name="Bond", instrument_type=InstrumentType.BOND)
    _position(session, month_row.id, account.id, stock.id, "100000.00")
    _position(session, month_row.id, account.id, bond.id, "50000.00")
    return month_row.id


def _seed_deposit(session, *, month: int = 5) -> int:
    """Savings: deposit 120000.00 @ 6% (600.00 RUB/month ladder interest)."""
    month_row = _month(session, month=month)
    account = _account(session, name="Bank", account_type=AccountType.SAVINGS)
    _deposit(session, month_row.id, account.id)
    return month_row.id


def _seed_inflation(session, *, month: int = 5) -> int:
    """Savings deposit + brokerage bond with a +1 month coupon."""
    month_row = _month(session, month=month)
    bank = _account(session, name="Bank", account_type=AccountType.SAVINGS)
    broker = _account(session, name="Broker", account_type=AccountType.BROKERAGE)
    _deposit(session, month_row.id, bank.id)
    bond = _instrument(session, name="Bond", instrument_type=InstrumentType.BOND)
    _position(session, month_row.id, broker.id, bond.id, "1000.00")
    _coupon(session, month_row.id, broker.id, bond.id)
    return month_row.id


def _seed_fx(session, *, month: int = 5) -> tuple[int, int, int]:
    """USD stock 100000.00 (candidate) + RUB bond 50000.00 (reporting currency)."""
    month_row = _month(session, month=month)
    account = _account(session)
    usd_stock = _instrument(
        session, name="UsdStock", instrument_type=InstrumentType.STOCK, currency="USD"
    )
    rub_bond = _instrument(session, name="RubBond", instrument_type=InstrumentType.BOND)
    stock_position = _position(session, month_row.id, account.id, usd_stock.id, "100000.00")
    _position(session, month_row.id, account.id, rub_bond.id, "50000.00")
    return month_row.id, usd_stock.id, stock_position.id


def _commit(session) -> None:
    session.commit()


def _service_body(session, month_id: int, shock: dict[str, Any]) -> dict[str, Any]:
    """Service evaluation normalized to exact JSON semantics.

    The HTTP body is JSON: tuples become lists and integer dict keys
    become strings. Round-tripping the dataclass projection through JSON
    gives the same canonical form, so API-vs-service equality asserts the
    envelope content, not Python container types.
    """
    return json.loads(json.dumps(asdict(evaluate_scenario_lab(session, month_id, shock))))


def _post_scenario(client: TestClient, month_id: int, shock: dict[str, Any], **controls):
    return client.post(f"/api/months/{month_id}/scenario-lab", json={"shock": shock, **controls})


def _export_scenario(client: TestClient, month_id: int, shock: dict[str, Any], **controls):
    return client.post(
        f"/api/months/{month_id}/scenario-lab/export", json={"shock": shock, **controls}
    )


def _assert_no_floats(value: Any, path: str = "$") -> None:
    if isinstance(value, float):
        raise AssertionError(f"binary float at {path}: {value!r}")
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_no_floats(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_floats(item, f"{path}[{index}]")


def _table_counts(session) -> dict[str, int]:
    return {
        table.__name__: session.scalar(select(func.count()).select_from(table))
        for table in (
            ReportingMonth,
            PositionSnapshot,
            DepositSnapshot,
            ExpectedCashFlow,
            Instrument,
        )
    }


def _table_snapshots(session) -> dict[str, list[tuple]]:
    deposits = session.execute(
        select(
            DepositSnapshot.id,
            DepositSnapshot.account_id,
            DepositSnapshot.name,
            DepositSnapshot.deposit_type,
            DepositSnapshot.balance_kopecks,
            DepositSnapshot.annual_rate_basis_points,
            DepositSnapshot.expected_monthly_interest_kopecks,
        ).order_by(DepositSnapshot.id)
    ).all()
    positions = session.execute(
        select(
            PositionSnapshot.id,
            PositionSnapshot.account_id,
            PositionSnapshot.instrument_id,
            PositionSnapshot.market_value_kopecks,
        ).order_by(PositionSnapshot.id)
    ).all()
    return {"deposits": list(deposits), "positions": list(positions)}


# ---------------------------------------------------------------------------
# Acceptance 1-4: HTTP evaluation equals accepted service semantics per shock.
# ---------------------------------------------------------------------------


def test_equity_http_equals_service_semantics(session, client):
    month_id = _seed_equity(session)
    _commit(session)

    body = _post_scenario(client, month_id, EQUITY_10)
    assert body.status_code == 200, body.text
    payload = body.json()

    assert payload == _service_body(session, month_id, EQUITY_10)
    # Equity applied to the RUB stock only: 10% of 100000.00 RUB.
    assert payload["impact"]["liquid_assets_delta_kopecks"] == -1_000_000
    assert payload["impact"]["liquid_assets_delta"] == "-10000.00"
    assert payload["coverage"]["applied"] == 1
    assert payload["coverage"]["not_applicable"] == 1
    assert payload["normalized_shock_input"]["shock_type"] == "equity_drawdown"


def test_deposit_rate_http_equals_service_semantics(session, client):
    month_id = _seed_deposit(session)
    _commit(session)

    body = _post_scenario(client, month_id, DEPOSIT_8)
    assert body.status_code == 200, body.text
    payload = body.json()

    assert payload == _service_body(session, month_id, DEPOSIT_8)
    # Deposit-rate re-prices forecast interest only; liquid capital equal.
    assert payload["base"]["liquid_assets_kopecks"] == payload["stressed"]["liquid_assets_kopecks"]
    assert payload["impact"]["liquid_assets_delta_kopecks"] == 0
    assert payload["normalized_shock_input"]["shock_type"] == "deposit_rate_assumption"
    assert payload["assumptions"], "assumptions must be exposed"


def test_inflation_http_equals_service_semantics(session, client):
    month_id = _seed_inflation(session)
    _commit(session)

    body = _post_scenario(client, month_id, INFLATION_12)
    assert body.status_code == 200, body.text
    payload = body.json()

    assert payload == _service_body(session, month_id, INFLATION_12)
    real_rows = payload["stressed"]["cash_flow_real_value"]
    # Base month (months_ahead 0): real == nominal.
    assert real_rows["2030-05"]["nominal_income_kopecks"] == 60_000
    assert real_rows["2030-05"]["real_income_kopecks"] == 60_000
    assert real_rows["2030-05"]["real_income"] == "600.00"
    assert real_rows["2030-05"]["income_delta_kopecks"] == 0
    # Month +11: 600.00 RUB nominal in base-period purchasing power.
    assert real_rows["2031-04"]["real_income_kopecks"] == 53_779
    assert real_rows["2031-04"]["real_income"] == "537.79"
    assert payload["row_applicability"], "real-value rows must be applied"


def test_fx_candidate_scope_conservative_http(session, client):
    month_id, usd_instrument_id, usd_position_id = _seed_fx(session)
    _commit(session)

    body = _post_scenario(client, month_id, FX_USD_10)
    assert body.status_code == 200, body.text
    payload = body.json()

    assert payload == _service_body(session, month_id, FX_USD_10)
    # Candidate scope is NOT a translation basis: nothing is revalued.
    assert payload["base"] == payload["stressed"]
    assert payload["impact"]["liquid_assets_delta_kopecks"] == 0
    assert payload["coverage"]["applied"] == 0
    assert payload["coverage"]["candidate_target_currency"] == 1
    assert payload["coverage"]["not_applicable"] == 1
    # Row-level: candidate stays unknown, reporting-currency row not applicable.
    assert payload["row_applicability"][str(usd_position_id)] == "unknown"
    assert len(payload["row_applicability"]) == 2
    # Aggregate: exact capital metrics unavailable, never silently exact.
    for key in ("liquid_assets", "liquid_capital_net", "capital_goals"):
        assert payload["metric_support"][key]["status"] == "unavailable"
        assert payload["metric_support"][key]["reason_codes"] == [
            "fx_translation_basis_unavailable"
        ]
    impact_row = payload["impact"]["per_position"][str(usd_position_id)]
    assert impact_row["delta_kopecks"] == 0
    assert impact_row["reason_codes"] == ["fx_translation_basis_unavailable"]
    assert payload["normalized_shock_input"] == {
        "shock_type": "fx_translation_shock",
        "target_currency": "USD",
        "reporting_value_change_pct": "10",
    }


# ---------------------------------------------------------------------------
# Acceptance 5-8: deterministic error mapping.
# ---------------------------------------------------------------------------


def test_exactly_one_shock_required(session, client):
    month_id = _seed_equity(session)
    _commit(session)

    empty = client.post(f"/api/months/{month_id}/scenario-lab", json={"shock": {}})
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "unsupported_composition_v1"

    two = client.post(
        f"/api/months/{month_id}/scenario-lab",
        json={"shock": {**EQUITY_10, **DEPOSIT_8}},
    )
    assert two.status_code == 422
    assert two.json()["error"]["code"] == "unsupported_composition_v1"


def test_unsupported_shock_rejected(session, client):
    month_id = _seed_equity(session)
    _commit(session)

    body = client.post(
        f"/api/months/{month_id}/scenario-lab",
        json={"shock": {"issuer_impairment": {"impairment_pct": "10"}}},
    )
    assert body.status_code == 422
    assert body.json()["error"]["code"] == "unsupported_shock_type_v1"


def test_malformed_extra_fields_fail_closed(session, client):
    month_id = _seed_equity(session)
    _commit(session)

    # Unknown top-level control: extra=forbid.
    body = client.post(
        f"/api/months/{month_id}/scenario-lab",
        json={"shock": EQUITY_10, "bogus_control": 1},
    )
    assert body.status_code == 422
    assert body.json()["error"]["code"] == "unprocessable"

    # The payload-as-shock shape (payload dict not wrapped under a shock
    # type) is a payload whose key is not a supported shock type, so the
    # service deterministically maps it to unsupported_shock_type_v1.
    body = client.post(
        f"/api/months/{month_id}/scenario-lab",
        json={"shock": EQUITY_10["equity_drawdown"], "top_n": 5},
    )
    assert body.status_code == 422
    assert body.json()["error"]["code"] == "unsupported_shock_type_v1"

    # Missing shock key.
    body = client.post(f"/api/months/{month_id}/scenario-lab", json={"top_n": 5})
    assert body.status_code == 422
    assert body.json()["error"]["code"] == "unprocessable"

    # Invalid evaluation control — must surface canonical invalid_top_n
    # (service validator), not generic Pydantic validation.
    body = _post_scenario(client, month_id, EQUITY_10, top_n=0)
    assert body.status_code == 422
    assert body.json()["error"]["code"] == "invalid_top_n"

    # Invalid shock-specific input (binary float in a rate field) fails
    # closed with the exact machine-readable error.code preserved.
    body = _post_scenario(
        client,
        month_id,
        {"fx_translation_shock": {"target_currency": "USD", "reporting_value_change_pct": 10.0}},
    )
    assert body.status_code == 422
    assert body.json()["error"]["code"] == "invalid_reporting_value_change_pct"

    # Invalid shock payload type.
    body = _post_scenario(client, month_id, {"equity_drawdown": {"drawdown_pct": 12.0}})
    assert body.status_code == 422
    assert body.json()["error"]["code"] == "invalid_drawdown_pct"


def test_missing_month_not_found(client):
    body = _post_scenario(client, 999_999, EQUITY_10)
    assert body.status_code == 404
    assert body.json()["error"]["code"] == "reporting_month_not_found"


def test_fx_validation_codes_are_exact_and_export_parity(session, client):
    """Integrator blocker regression: FX validation must surface exact codes.

    ``invalid_target_currency`` and
    ``invalid_reporting_value_change_pct`` must be the error.code itself,
    not a generic unprocessable, on both the normal and export surfaces.
    """
    month_id = _seed_equity(session)
    _commit(session)

    # invalid_target_currency — empty / malformed currency tag
    body = _post_scenario(
        client,
        month_id,
        {"fx_translation_shock": {"target_currency": "", "reporting_value_change_pct": "10"}},
    )
    assert body.status_code == 422
    assert body.json()["error"]["code"] == "invalid_target_currency"

    export = _export_scenario(
        client,
        month_id,
        {"fx_translation_shock": {"target_currency": "", "reporting_value_change_pct": "10"}},
    )
    assert export.status_code == 422
    assert export.json()["error"]["code"] == "invalid_target_currency"

    # invalid_reporting_value_change_pct — binary float must preserve exact code
    body = _post_scenario(
        client,
        month_id,
        {"fx_translation_shock": {"target_currency": "USD", "reporting_value_change_pct": 10.0}},
    )
    assert body.status_code == 422
    assert body.json()["error"]["code"] == "invalid_reporting_value_change_pct"

    export = _export_scenario(
        client,
        month_id,
        {"fx_translation_shock": {"target_currency": "USD", "reporting_value_change_pct": 10.0}},
    )
    assert export.status_code == 422
    assert export.json()["error"]["code"] == "invalid_reporting_value_change_pct"

    # Another invalid_reporting_value_change_pct shape — non-numeric string
    body = _post_scenario(
        client,
        month_id,
        {
            "fx_translation_shock": {
                "target_currency": "USD",
                "reporting_value_change_pct": "not-a-number",
            }
        },
    )
    assert body.status_code == 422
    assert body.json()["error"]["code"] == "invalid_reporting_value_change_pct"


def test_invalid_top_n_canonical_code_and_export_parity(session, client):
    """invalid_top_n must be canonical on both surfaces, not Pydantic generic."""
    month_id = _seed_equity(session)
    _commit(session)

    for bad in (0, 101, -1):
        body = _post_scenario(client, month_id, EQUITY_10, top_n=bad)
        assert body.status_code == 422
        assert body.json()["error"]["code"] == "invalid_top_n"

        export = _export_scenario(client, month_id, EQUITY_10, top_n=bad)
        assert export.status_code == 422
        assert export.json()["error"]["code"] == "invalid_top_n"

    # Valid top_n stays successful on both surfaces
    body = _post_scenario(client, month_id, EQUITY_10, top_n=5)
    assert body.status_code == 200
    export = _export_scenario(client, month_id, EQUITY_10, top_n=5)
    assert export.status_code == 200


# ---------------------------------------------------------------------------
# Acceptance 9-13: full envelope, shared export adapter, determinism, floats.
# ---------------------------------------------------------------------------


def test_response_exposes_full_envelope(session, client):
    month_id = _seed_equity(session)
    _commit(session)

    payload = _post_scenario(client, month_id, EQUITY_10).json()
    assert ENVELOPE_KEYS <= payload.keys()
    assert payload["contract_version"] == "r07-09-v1"
    assert payload["base_fingerprint"]
    assert payload["semantic_fingerprint"]
    assert payload["coverage"]
    assert payload["metric_support"]["liquid_assets"]["status"] == "supported"
    assert payload["reporting_month"]["year"] == 2030
    assert payload["reporting_month"]["month"] == 5
    assert payload["warnings"] == []
    assert payload["presentation_metadata"]["account_names"]


def test_export_payload_matches_evaluation_result(session, client):
    month_id = _seed_equity(session)
    _commit(session)

    evaluation = _service_body(session, month_id, EQUITY_10)
    response = _export_scenario(client, month_id, EQUITY_10)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="scenario_lab_2030-05_equity_drawdown.json"'
    )
    exported = json.loads(response.content)
    # Same envelope adapter: exported semantic content == normal response.
    assert exported == evaluation
    assert exported == _post_scenario(client, month_id, EQUITY_10).json()


def test_export_deterministic_and_filename_does_not_change_fingerprint(session, client):
    month_id = _seed_deposit(session)
    _commit(session)

    first = _export_scenario(client, month_id, DEPOSIT_8)
    second = _export_scenario(client, month_id, DEPOSIT_8)
    assert first.status_code == 200
    assert first.content == second.content

    evaluation = _service_body(session, month_id, DEPOSIT_8)
    body = json.loads(first.content)
    # Filename/metadata is outside the body and never alters semantics.
    assert body["semantic_fingerprint"] == evaluation["semantic_fingerprint"]
    assert body["base_fingerprint"] == evaluation["base_fingerprint"]
    # Export of the same shock for a different month differs by content, not
    # by filename metadata.
    other_month = _month(session, year=2030, month=6)
    _commit(session)
    other = _export_scenario(client, other_month.id, DEPOSIT_8)
    assert other.status_code == 200
    assert json.loads(other.content)["semantic_fingerprint"] != body["semantic_fingerprint"]


def test_no_binary_floats_in_exported_values(session, client):
    month_id_equity = _seed_equity(session, month=5)
    month_id_fx, _fx_instrument_id, _fx_position_id = _seed_fx(session, month=6)
    _commit(session)

    for month_id, shock in (
        (month_id_equity, EQUITY_10),
        (month_id_equity, DEPOSIT_8),
        (month_id_fx, FX_USD_10),
        (month_id_equity, INFLATION_12),
    ):
        body = _post_scenario(client, month_id, shock)
        assert body.status_code == 200, body.text
        _assert_no_floats(body.json())
        export = _export_scenario(client, month_id, shock)
        assert export.status_code == 200
        _assert_no_floats(json.loads(export.content))


# ---------------------------------------------------------------------------
# Acceptance 14-15: read-only / no network invariants over HTTP.
# ---------------------------------------------------------------------------


@contextmanager
def _forbid_sql_writes(engine: Engine) -> Iterator[None]:
    write_verbs = {"INSERT", "UPDATE", "DELETE", "REPLACE"}

    def _before_cursor_execute(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        verb = statement.lstrip().split(None, 1)[0].upper()
        if verb in write_verbs:
            raise AssertionError(f"scenario API issued persistence write: {statement[:240]}")

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


def test_no_db_mutation(session, database, client):
    month_id = _seed_equity(session, month=5)
    deposit_month = _seed_deposit(session, month=6)
    fx_month, _fx_instrument_id, _fx_position_id = _seed_fx(session, month=7)
    _commit(session)

    before_counts = _table_counts(session)
    before_rows = _table_snapshots(session)

    with _forbid_sql_writes(database.engine):
        for month_id, shock in (
            (month_id, EQUITY_10),
            (deposit_month, DEPOSIT_8),
            (month_id, INFLATION_12),
            (fx_month, FX_USD_10),
        ):
            response = _post_scenario(client, month_id, shock)
            assert response.status_code == 200, response.text
            export = _export_scenario(client, month_id, shock)
            assert export.status_code == 200, export.text

    assert _table_counts(session) == before_counts
    assert _table_snapshots(session) == before_rows


def test_no_provider_network_access(session, client):
    month_id = _seed_deposit(session)
    _commit(session)

    # The scenario service and these endpoints perform no network work, but
    # the test must prove it at the HTTP seam. On Windows the running
    # asyncio proactor event loop itself calls isinstance(conn,
    # socket.socket) while polling its self-pipe, so replacing
    # socket.socket globally would break the TestClient loop instead of
    # proving anything. We therefore block the two realistic outbound
    # paths — TCP connects and DNS lookups — which the event loop never
    # touches; any attempt during the request raises and fails the test.
    def _no_network(*_args, **_kwargs):
        raise AssertionError("scenario evaluation attempted network access")

    original_connect = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo
    socket.create_connection = _no_network
    socket.getaddrinfo = _no_network
    try:
        response = _post_scenario(client, month_id, DEPOSIT_8)
        assert response.status_code == 200, response.text
        export = _export_scenario(client, month_id, DEPOSIT_8)
        assert export.status_code == 200, export.text
    finally:
        socket.create_connection = original_connect
        socket.getaddrinfo = original_getaddrinfo
