"""Private-free H3 consumer regressions through real H1/H2 acceptance APIs."""

import copy
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from test_r08_02_portfolio_xirr import _history
from test_statement_import_historical_endpoints import accept as accept_endpoint
from test_statement_import_historical_endpoints import attest as attest_endpoint
from test_statement_import_historical_owner_flows import accept as accept_flow
from test_statement_import_historical_owner_flows import attest as attest_flow
from test_statement_import_historical_owner_flows import xml as cash_xml
from test_statement_import_historical_portfolio_flows import accept as accept_portfolio
from test_statement_import_historical_portfolio_flows import attest as attest_portfolio
from test_statement_import_mybroker import ACCOUNT, apply, preview
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import endpoint_xml, positions_only
from test_statement_import_source_cash_coverage import certify, claims

from hermes_finance.domain import XirrCashFlow, calculate_xirr
from hermes_finance.domain.historical_endpoints import EndpointIntent
from hermes_finance.domain.historical_owner_flows import COMPATIBLE_FLOW_CONTRACT, OwnerFlowIntent
from hermes_finance.domain.historical_portfolio_flows import PortfolioFlowIntent
from hermes_finance.domain.source_cash_coverage import SourceCashIntent
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    AppSettings,
    CashBoundaryCoverage,
    ExternalFlow,
    HistoricalEndpointRevision,
    InKindBoundaryCoverage,
    ReportingMonth,
)
from hermes_finance.services.broker_identity_mappings import confirm_mapping
from hermes_finance.services.cash_boundary_coverage import cash_boundary_coverage_for_interval
from hermes_finance.services.historical_endpoints import endpoint_key
from hermes_finance.services.historical_portfolio_flows import (
    apply_historical_portfolio_flow,
    preview_historical_portfolio_flow,
)
from hermes_finance.services.in_kind_boundary_coverage import attest_in_kind_boundary_history
from hermes_finance.services.performance_availability import performance_availability_for_interval
from hermes_finance.services.portfolio_twrr import twrr_for_interval
from hermes_finance.services.portfolio_xirr import xirr_for_interval
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.source_cash_coverage import read_source_cash_coverage
from hermes_finance.statement_import.mybroker import PROVIDER

A, B, DAY = date(2030, 1, 16), date(2030, 1, 31), date(2030, 1, 17)


def source_document(*, value, amounts=(), alias=ACCOUNT, different_days=False):
    root = ET.fromstring(positions_only(endpoint_xml(rub_amounts=(None, "0"))))
    security = root.find(".//{MyBroker}Details[@ISIN1]")
    security.set("real_rest", "3")
    security.set("forward_rest", "3")
    security.set("real_volume", value)
    if amounts:
        money = ET.fromstring(cash_xml(amount=amounts[0], extra_amounts=amounts[1:]))
        target = root.find("{MyBroker}Trades2")
        root.remove(target)
        root.append(copy.deepcopy(money.find("{MyBroker}Trades2")))
        if different_days:
            collection = root.find(".//{MyBroker}settlement_date_Collection")
            group = collection.find("{MyBroker}settlement_date")
            rows = group.find("{MyBroker}rn_Collection")
            second = ET.SubElement(
                collection, "{MyBroker}settlement_date", settlement_date="2030-01-18T00:00:00"
            )
            other_rows = ET.SubElement(second, "{MyBroker}rn_Collection")
            for row in list(rows)[1:]:
                rows.remove(row)
                other_rows.append(row)
    for node in root.iter():
        for name, value in list(node.attrib.items()):
            if value == ACCOUNT:
                node.set(name, alias)
    return ET.tostring(root, encoding="utf-8")


def prepare(
    session, *, amounts=(), opening="1000.00", closing="1100.00", other=False, different_days=False
):
    if other:
        account = Account(
            name="Synthetic second", account_type="brokerage", include_in_returns=False
        )
        session.add(account)
        session.commit()
        for alias in ("7654321", "7654321-000"):
            confirm_mapping(
                session,
                provider=PROVIDER,
                subject_kind="account",
                provider_identity=alias,
                hermes_target_id=account.id,
            )
        alias, filename_account = "7654321-000", "7654321"
    else:
        account = session.scalar(select(Account))
        alias, filename_account = ACCOUNT, "1234567"
    account_id = account.id
    session.add(
        AccountPerformanceScopeMembership(
            account_id=account_id,
            effective_from=date(2029, 1, 1),
            effective_to=date(2032, 1, 1),
            include_in_returns=True,
        )
    )
    session.commit()
    attest_in_kind_boundary_history(session, account_id=account_id, covered_from=A, covered_to=B)
    imports = []
    for day, value, events in ((A, opening, ()), (B, closing, amounts)):
        raw = source_document(
            value=value, amounts=events, alias=alias, different_days=different_days
        )
        filename = f"Брокерский {filename_account} (01.01.30-{day:%d.%m.%y}).xml"
        imports.append(apply(session, raw, preview(session, raw, filename), filename)["import_id"])
    return account_id, imports, amounts


def accept_inputs(session, prepared, *, endpoints=True, coverage=True):
    account_id, imports, amounts = prepared
    flows = []
    for ordinal in range(len(amounts)):
        intent = OwnerFlowIntent(
            account_id=account_id,
            evidence_version=COMPATIBLE_FLOW_CONTRACT,
            seed={"import_id": imports[1], "ordinal": ordinal},
        )
        flows.append(
            accept_flow(session, attest_flow(session, intent), f"flow-{account_id}-{ordinal}")[
                "readback"
            ]
        )
    if coverage:
        raw = SourceCashIntent(account_id=account_id, opening_date=A, closing_date=B)
        certify(session, claims(session, raw, zero=not amounts), f"coverage-{account_id}")
    if endpoints:
        for day, import_id in zip((A, B), imports, strict=True):
            raw = EndpointIntent(
                account_id=account_id, valuation_date=day, source_import_id=import_id
            )
            accept_endpoint(session, attest_endpoint(session, raw), f"endpoint-{account_id}-{day}")
    return flows


def portfolio_authority(session, flows):
    for flow in flows:
        raw = PortfolioFlowIntent(
            flow_id=flow["flow_id"],
            expected_flow_revision=flow["revision"],
            expected_portfolio_revision=0,
        )
        accept_portfolio(session, attest_portfolio(session, raw), "portfolio-" + flow["flow_id"])


def result(session, account_id=None):
    return xirr_for_interval(
        session,
        start_date=A,
        end_date=B,
        scope="account" if account_id else "portfolio",
        account_id=account_id,
    )


def adjacent_coverage(session, prepared, *, defect=None):
    """Accept immutable H2-A2 slices through their real Preview/Apply path."""
    account_id, _, amounts = prepared
    split = date(2030, 1, 22)
    first = SourceCashIntent(account_id=account_id, opening_date=A, closing_date=split)
    first_view = certify(session, claims(session, first, zero=not amounts), f"first-{account_id}")[
        "readback"
    ]
    second_start = date(2030, 1, 23) if defect == "gap" else split
    second = SourceCashIntent(account_id=account_id, opening_date=second_start, closing_date=B)
    if defect == "source_free":
        session.add(
            CashBoundaryCoverage(
                account_id=account_id,
                covered_from=date(2030, 1, 23),
                covered_to=B,
                coverage_state="complete",
                provenance_kind="owner_attested_cash_history",
            )
        )
        session.commit()
        return
    accepted = certify(session, claims(session, second, zero=True), f"second-{account_id}")[
        "readback"
    ]
    if defect == "retired":
        # A→B→A in the second slice retires it permanently; the first stays effective.
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=B)
        changed = ExternalFlow(
            reporting_month_id=month.id,
            account_id=account_id,
            event_date=B,
            boundary_amount_kopecks=1,
            direction="contribution",
            kind="external_contribution",
            source="synthetic",
        )
        session.add(changed)
        session.commit()
        session.delete(changed)
        session.commit()
        assert (
            read_source_cash_coverage(session, accepted["coverage_id"])["acceptance_state"]
            == "retired"
        )
        assert (
            read_source_cash_coverage(session, first_view["coverage_id"])["coverage_state"]
            == "complete"
        )
    elif defect == "unknown":
        session.get(CashBoundaryCoverage, accepted["coverage_id"]).coverage_state = "unknown"
        session.commit()
    elif defect == "overlap":
        # Corrupt/legacy overlap must remain a refusal even beside accepted slices.
        session.add(
            CashBoundaryCoverage(
                account_id=account_id,
                covered_from=split,
                covered_to=date(2030, 1, 23),
                coverage_state="complete",
                provenance_kind="owner_attested_source_cash_history",
            )
        )
        session.commit()


@pytest.mark.parametrize("scope", ["account", "portfolio"])
@pytest.mark.parametrize("defect", [None, "gap", "retired", "unknown", "overlap", "source_free"])
def test_adjacent_effective_source_coverage_uses_shared_assessor(
    database, monkeypatch, scope, defect
):
    with database.session_factory() as session:
        first = prepare(session, amounts=("100.00",), closing="1200.00")
        accounts = [first]
        if scope == "portfolio":
            accounts.append(prepare(session, other=True, opening="500.00", closing="550.00"))
        flows = []
        for index, prepared in enumerate(accounts):
            flows.extend(accept_inputs(session, prepared, coverage=False))
            adjacent_coverage(session, prepared, defect=defect if index == 0 else None)
        if scope == "portfolio":
            portfolio_authority(session, flows)
        membership = list(session.scalars(select(AccountPerformanceScopeMembership)))
        coverage = cash_boundary_coverage_for_interval(
            session,
            scope="account",
            account_id=first[0],
            start_date=DAY,
            end_date=B,
            rows_by_account={first[0]: membership},
            ledger_binding=COMPATIBLE_FLOW_CONTRACT,
        )
        assert coverage.status == ("unknown" if defect else "complete")
        if defect:

            def forbidden(*_args, **_kwargs):
                pytest.fail("incomplete source coverage must precede solver")

            monkeypatch.setattr("hermes_finance.services.portfolio_xirr.calculate_xirr", forbidden)
        actual = result(session, first[0] if scope == "account" else None)
        if defect:
            assert not actual.is_available
            assert "not_computable_external_flows_incomplete" in actual.reason_codes
        else:
            assert len(coverage.evidence) == 2
            opening, closing = (100000, 120000) if scope == "account" else (150000, 175000)
            expected = calculate_xirr(
                [XirrCashFlow(A, -opening), XirrCashFlow(DAY, -10000), XirrCashFlow(B, closing)]
            )
            assert actual.is_available and actual.quality.value == "exact"
            assert actual.annualized_rate == expected.annualized_rate


@pytest.mark.parametrize("scope", ["account", "portfolio"])
def test_real_readiness_composes_source_xirr_without_promoting_legacy_or_twrr(database, scope):
    with database.session_factory() as session:
        prepared = prepare(session, amounts=("100.00",), closing="1200.00")
        flows = accept_inputs(session, prepared, coverage=False)
        adjacent_coverage(session, prepared)
        if scope == "portfolio":
            portfolio_authority(session, flows)
        expected = result(session, prepared[0] if scope == "account" else None)
    params = {"start_date": str(A), "end_date": str(B), "scope": scope}
    if scope == "account":
        params["account_id"] = prepared[0]
    before = list(database.engine.raw_connection().iterdump())
    with TestClient(create_app(database=database)) as client:
        response = client.get("/api/performance/readiness", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["xirr"]["value"] == str(expected.value)
        assert body["xirr"]["availability"] == "available" and body["xirr"]["quality"] == "exact"
        assert body["twrr"]["availability"] == "not_computable"
        assert body["evidence"]["xirr"]["availability"] == "not_computable"
        assert body["diagnostics"] and all(
            diagnostic["affected_metrics"] == ["twrr"] for diagnostic in body["diagnostics"]
        )
    assert list(database.engine.raw_connection().iterdump()) == before


@pytest.mark.parametrize("authority", ["endpoint", "account_flow", "portfolio_flow"])
def test_real_readiness_explains_historical_authority_refusal(database, authority):
    with database.session_factory() as session:
        prepared = prepare(session, amounts=("100.00",), closing="1200.00")
        flows = accept_inputs(session, prepared)
        if authority == "endpoint":
            accept_endpoint(
                session,
                EndpointIntent(
                    operation="revoke",
                    account_id=prepared[0],
                    valuation_date=A,
                    expected_revision=1,
                    reason_code="owner_withdrawal",
                ),
                "readiness-revoke-endpoint",
            )
            key, code = "historical_endpoint", "not_computable_historical_endpoint_ineffective"
        elif authority == "account_flow":
            accept_flow(
                session,
                OwnerFlowIntent(
                    operation="revoke",
                    flow_id=flows[0]["flow_id"],
                    expected_revision=1,
                    reason_code="attestation_withdrawn",
                ),
                "readiness-revoke-flow",
            )
            key, code = (
                "historical_account_flow",
                "not_computable_historical_owner_flow_ineffective",
            )
        else:
            key, code = (
                "historical_portfolio_flow",
                "not_computable_historical_portfolio_flow_unknown",
            )
    params = {"start_date": str(A), "end_date": str(B)}
    if authority != "portfolio_flow":
        params.update(scope="account", account_id=prepared[0])
    before = list(database.engine.raw_connection().iterdump())
    with TestClient(create_app(database=database)) as client:
        response = client.get("/api/performance/readiness", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["xirr"]["availability"] == "not_computable"
        assert code in body["xirr"]["reason_codes"]
        diagnostic = next(d for d in body["diagnostics"] if code in d["reason_codes"])
        assert diagnostic["key"] == key
        assert diagnostic["affected_metrics"] == ["xirr"]
        assert diagnostic["category"] == "limitation"
        assert diagnostic["action"]["kind"] == "inspect_result"
        assert diagnostic["action"]["capability"] == "source_required"
        assert all(d["key"] != "unknown_reason" for d in body["diagnostics"])
    assert list(database.engine.raw_connection().iterdump()) == before


@pytest.mark.parametrize(
    "amounts,closing",
    [
        ((), "1100.00"),
        (("100.00",), "1200.00"),
        (("-100.00",), "1000.00"),
        (("100.00", "90.00", "-20.00"), "1270.00"),
    ],
)
def test_exact_account_signs_multiplicity_no_months_or_writes(database, amounts, closing):
    with database.session_factory() as session:
        prepared = prepare(session, amounts=amounts, closing=closing)
        flows = accept_inputs(session, prepared)
        account_id = prepared[0]
        assert not performance_availability_for_interval(
            session, start_date=A, end_date=B, scope="account", account_id=account_id
        ).xirr.is_available
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement)

        event.listen(database.engine, "before_cursor_execute", capture)
        try:
            actual = result(session, account_id)
        finally:
            event.remove(database.engine, "before_cursor_execute", capture)
        assert not any(
            s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
            for s in statements
        )
        expected = calculate_xirr(
            [
                XirrCashFlow(A, -100000),
                *(XirrCashFlow(DAY, -int(Decimal(amount) * 100)) for amount in amounts),
                XirrCashFlow(B, int(Decimal(closing) * 100)),
            ]
        )
        assert actual.is_available and actual.quality.value == "exact"
        assert actual.annualized_rate == expected.annualized_rate
        assert len(flows) == len(amounts)
        assert not list(session.scalars(select(ReportingMonth)))
        # H3 does not enable TWRR or the legacy availability path.
        assert not twrr_for_interval(
            session, start_date=A, end_date=B, scope="account", account_id=account_id
        ).is_available


def test_exact_portfolio_all_historical_accounts_and_api(database):
    with database.session_factory() as session:
        first = prepare(session, amounts=("100.00",), closing="1200.00")
        second = prepare(session, other=True, opening="500.00", closing="550.00")
        flows = accept_inputs(session, first) + accept_inputs(session, second)
        portfolio_authority(session, flows)
        actual = result(session)
        expected = calculate_xirr(
            [XirrCashFlow(A, -150000), XirrCashFlow(DAY, -10000), XirrCashFlow(B, 175000)]
        )
        assert actual.is_available and actual.annualized_rate == expected.annualized_rate
    # Current inclusion flag on the second account is false, yet history includes it.
    with TestClient(create_app(database=database)) as client:
        response = client.get(
            "/api/performance/xirr", params={"start_date": A.isoformat(), "end_date": B.isoformat()}
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["value"] == str(actual.value)
        assert payload["annualized"] is True and payload["value_unit"] == "percentage_points"


@pytest.mark.parametrize(
    "gate,reason",
    [
        ("endpoint", "not_computable_historical_endpoint_ineffective"),
        ("coverage", "not_computable_external_flows_incomplete"),
        ("flow", "not_computable_historical_owner_flow_ineffective"),
        ("membership", "not_computable_scope_membership_history_missing"),
        ("in_kind", "not_computable_in_kind_boundary_coverage_unknown"),
        ("currency", "not_computable_currency_conversion_incomplete"),
    ],
)
def test_dependency_loss_on_reread_blocks_solver(database, monkeypatch, gate, reason):
    with database.session_factory() as session:
        prepared = prepare(session, amounts=("100.00",), closing="1200.00")
        flows = accept_inputs(session, prepared)
        assert result(session, prepared[0]).is_available
        if gate == "endpoint":
            raw = EndpointIntent(
                operation="revoke",
                account_id=prepared[0],
                valuation_date=A,
                expected_revision=1,
                reason_code="owner_withdrawal",
            )
            accept_endpoint(session, raw, "revoke-endpoint")
        elif gate == "flow":
            raw = OwnerFlowIntent(
                operation="revoke",
                flow_id=flows[0]["flow_id"],
                expected_revision=1,
                reason_code="attestation_withdrawn",
            )
            accept_flow(session, raw, "revoke-flow")
        elif gate == "coverage":
            session.scalar(select(CashBoundaryCoverage)).coverage_state = "unknown"
            session.commit()
        elif gate == "membership":
            session.scalar(select(AccountPerformanceScopeMembership)).effective_from = DAY
            session.commit()
        elif gate == "in_kind":
            session.scalar(select(InKindBoundaryCoverage)).coverage_state = "unknown"
            session.commit()
        elif gate == "currency":
            session.add(AppSettings(id=1, base_currency="USD"))
            session.commit()

        def forbidden(*_args, **_kwargs):
            pytest.fail("evidence refusal must precede solver")

        monkeypatch.setattr("hermes_finance.services.portfolio_xirr.calculate_xirr", forbidden)
        actual = result(session, prepared[0])
        assert not actual.is_available and reason in actual.reason_codes


def test_portfolio_requires_authority_and_missing_account_blocks(database):
    with database.session_factory() as session:
        first = prepare(session, amounts=("100.00",), closing="1200.00")
        second = prepare(session, other=True)
        flows = accept_inputs(session, first)
        accept_inputs(session, second, endpoints=False)
        actual = result(session)
        assert "not_computable_historical_portfolio_flow_unknown" in actual.reason_codes
        assert "not_computable_opening_valuation_missing" in actual.reason_codes
        # Exact account result is unaffected by another account's missing endpoints.
        assert result(session, first[0]).is_available
        portfolio_authority(session, flows)
        assert not result(session).is_available


def test_solver_reason_propagation_is_separate(database):
    with database.session_factory() as session:
        prepared = prepare(session, closing="0")
        accept_inputs(session, prepared)
        actual = result(session, prepared[0])
        assert actual.reason_codes == ("not_computable_xirr_no_valid_root",)


def test_no_endpoint_side_mixing(database):
    with database.session_factory() as session:
        prepared = prepare(session, amounts=("100.00",), closing="1200.00")
        accept_inputs(session, prepared, endpoints=False)
        raw = EndpointIntent(
            account_id=prepared[0], valuation_date=B, source_import_id=prepared[1][1]
        )
        accept_endpoint(session, attest_endpoint(session, raw), "closing-only")
        assert (
            "not_computable_opening_valuation_missing" in result(session, prepared[0]).reason_codes
        )


def test_root_ambiguity_keeps_numerical_reason(database):
    with database.session_factory() as session:
        prepared = prepare(session, amounts=("-5000.00", "5000.00"), different_days=True)
        accept_inputs(session, prepared)
        actual = result(session, prepared[0])
        assert actual.reason_codes == ("not_computable_xirr_root_ambiguity",)


def test_portfolio_not_in_scope_flow_adds_no_amount(database):
    with database.session_factory() as session:
        first = prepare(session)
        second = prepare(session, other=True, amounts=("100.00",))
        session.scalar(
            select(AccountPerformanceScopeMembership).where(
                AccountPerformanceScopeMembership.account_id == second[0]
            )
        ).include_in_returns = False
        session.commit()
        accept_inputs(session, first)
        accept_inputs(session, second, endpoints=False, coverage=False)
        actual = result(session)
        expected = calculate_xirr([XirrCashFlow(A, -100000), XirrCashFlow(B, 110000)])
        assert actual.is_available and actual.annualized_rate == expected.annualized_rate


def test_portfolio_revocation_preserves_account_xirr(database):
    with database.session_factory() as session:
        prepared = prepare(session, amounts=("100.00",), closing="1200.00")
        flows = accept_inputs(session, prepared)
        portfolio_authority(session, flows)
        assert result(session).is_available
        raw = PortfolioFlowIntent(
            operation="revoke",
            flow_id=flows[0]["flow_id"],
            expected_flow_revision=1,
            expected_portfolio_revision=1,
            reason_code="attestation_withdrawn",
        )
        plan = preview_historical_portfolio_flow(session, raw)
        assert plan["can_apply"], plan["blockers"]
        apply_historical_portfolio_flow(
            session,
            raw,
            confirmation_digest=plan["confirmation_digest"],
            request_id="revoke-portfolio",
        )
        assert "not_computable_historical_portfolio_flow_unknown" in result(session).reason_codes
        assert result(session, prepared[0]).is_available


@pytest.mark.parametrize("kind", ["source_free", "partial", "wrong_window"])
def test_incomplete_or_wrong_ledger_coverage_refuses(database, kind):
    with database.session_factory() as session:
        prepared = prepare(session)
        accept_inputs(session, prepared, coverage=False)
        session.add(
            CashBoundaryCoverage(
                account_id=prepared[0],
                covered_from=DAY,
                covered_to=B if kind != "wrong_window" else DAY,
                coverage_state="unknown" if kind == "partial" else "complete",
                provenance_kind="owner_attestation",
            )
        )
        session.commit()
        assert (
            "not_computable_external_flows_incomplete" in result(session, prepared[0]).reason_codes
        )


def test_suspected_legacy_transfer_cannot_bypass_source_gates(database):
    with database.session_factory() as session:
        prepared = prepare(session, amounts=("100.00",), closing="1200.00")
        flows = accept_inputs(session, prepared)
        portfolio_authority(session, flows)
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=B)
        session.add(
            ExternalFlow(
                reporting_month_id=month.id,
                account_id=prepared[0],
                event_date=DAY,
                direction="withdrawal",
                boundary_amount_kopecks=10000,
                currency="RUB",
                scope_membership="unknown",
                kind="external_withdrawal",
                source="synthetic",
            )
        )
        session.commit()
        actual = result(session)
        assert not actual.is_available
        assert "not_computable_external_flows_incomplete" in actual.reason_codes
        assert "not_computable_historical_portfolio_flow_unknown" in actual.reason_codes


def test_legacy_available_path_never_calls_source_bridge(tmp_path, monkeypatch):
    session, database, _, _, account_id = _history(tmp_path)

    def forbidden(*_args, **_kwargs):
        pytest.fail("complete legacy evidence must preserve its path")

    monkeypatch.setattr(
        "hermes_finance.services.portfolio_xirr.historical_xirr_evidence", forbidden
    )
    try:
        assert xirr_for_interval(
            session,
            start_date=date(2030, 1, 31),
            end_date=date(2032, 1, 31),
            scope="account",
            account_id=account_id,
        ).is_available
    finally:
        session.close()
        database.engine.dispose()


def test_year_interval_needs_no_intermediate_month_end(database, monkeypatch):
    monkeypatch.setitem(globals(), "A", date(2030, 1, 31))
    monkeypatch.setitem(globals(), "B", date(2031, 1, 31))
    with database.session_factory() as session:
        prepared = prepare(session)
        accept_inputs(session, prepared)
        actual = result(session, prepared[0])
        assert actual.is_available and abs(actual.annualized_rate - Decimal("0.1")) < Decimal(
            "1e-24"
        )
        assert not list(session.scalars(select(ReportingMonth)))


def test_corroborating_source_occurrences_count_one_economic_flow(database):
    with database.session_factory() as session:
        prepared = prepare(session, amounts=("100.00",), closing="1200.00")
        raw = source_document(value="1200.00", amounts=("100.00",)).replace(
            b"2030-01-17T10:00:10", b"2030-01-17T10:00:11"
        )
        filename = "Брокерский 1234567 (01.01.30-31.01.30).xml"
        apply(session, raw, preview(session, raw, filename), filename)
        flows = accept_inputs(session, prepared)
        assert len(flows) == 1 and len(flows[0]["owned_occurrences"]) == 2
        actual = result(session, prepared[0])
        expected = calculate_xirr(
            [XirrCashFlow(A, -100000), XirrCashFlow(DAY, -10000), XirrCashFlow(B, 120000)]
        )
        assert actual.is_available and actual.annualized_rate == expected.annualized_rate


def test_source_bridge_keeps_one_snapshot_across_dependency_change(database, monkeypatch):
    from hermes_finance.services import historical_xirr_evidence as bridge

    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one() == "wal"
    with database.session_factory() as session:
        prepared = prepare(session)
        accept_inputs(session, prepared)
        original = bridge.read_historical_endpoint
        changed = False

        def interleave(read_session, key):
            nonlocal changed
            view = original(read_session, key)
            if not changed:
                changed = True
                with database.session_factory() as writer:
                    writer.scalar(select(CashBoundaryCoverage)).coverage_state = "unknown"
                    writer.commit()
            return view

        monkeypatch.setattr(bridge, "read_historical_endpoint", interleave)
        assert result(session, prepared[0]).is_available
        assert not result(session, prepared[0]).is_available


def test_endpoint_retirement_cannot_resurrect_after_membership_restore(database):
    with database.session_factory() as session:
        prepared = prepare(session)
        accept_inputs(session, prepared)
        row = session.scalar(select(AccountPerformanceScopeMembership))
        row.include_in_returns = False
        session.commit()
        row.include_in_returns = True
        session.commit()
        actual = result(session, prepared[0])
        assert "not_computable_historical_endpoint_ineffective" in actual.reason_codes
        assert (
            session.scalar(
                select(HistoricalEndpointRevision)
                .where(HistoricalEndpointRevision.endpoint_key == endpoint_key(prepared[0], A))
                .order_by(HistoricalEndpointRevision.revision.desc())
            ).acceptance_state
            == "retired"
        )
