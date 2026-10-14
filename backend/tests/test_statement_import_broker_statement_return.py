"""Synthetic S3 equation, source identity, read-only API/export and strict isolation."""

import json
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from test_statement_import_mybroker import FILENAME
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import (
    _broker_month_apply,
    _broker_month_preview,
    _broker_month_setup,
    broker_month_xml,
)
from test_statement_import_mybroker_metadata import (
    _insert_section_history,
    _section_accept,
    _section_second_source,
    metadata_xml,
    section_setup,
)
from test_statement_import_source_cash_coverage import certify, claims, continuous_membership

from hermes_finance.domain.broker_statement_return import (
    NKD_WARNING,
    PERIOD_WARNING,
    BrokerStatementBasis,
    StatementCrossing,
    StatementEndpoint,
    StatementPosition,
    StatementSource,
    calculate_statement_return,
)
from hermes_finance.domain.source_cash_coverage import SourceCashIntent
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Account,
    CashBoundaryCoverage,
    MyBrokerImport,
    ReportingMonth,
)
from hermes_finance.services.broker_statement_return import read_statement_return
from hermes_finance.services.source_cash_coverage import (
    preview_source_cash_coverage,
    read_source_cash_coverage,
)

T0, MID, T1 = date(2026, 8, 31), date(2026, 9, 15), date(2026, 9, 30)


def basis(v0=1000000, v1=1121100, flows=((MID, 100000),), **changes):
    def endpoint(day, value):
        return StatementEndpoint(
            account_id=1,
            valuation_date=day,
            positions=(
                StatementPosition(
                    instrument_id=1,
                    isin="RU000A000000",
                    quantity="1",
                    market_value_kopecks=value,
                    source_ordinal=0,
                ),
            ),
            positions_value_kopecks=value,
            cash_kopecks=0,
            total_value_kopecks=value,
            inventory_state="complete",
        )

    return BrokerStatementBasis(
        account_id=1,
        t0=T0,
        t1=T1,
        opening=endpoint(T0, v0),
        closing=endpoint(T1, v1),
        sources=(
            StatementSource(
                import_id=1,
                document_sha256="a" * 64,
                parser_version="mybroker-s1-v2",
                source_signature="b" * 64,
                request_id="synthetic",
                confirmation_digest="c" * 64,
            ),
        ),
        material_fingerprint="d" * 64,
        crossings=tuple(
            StatementCrossing(
                event_id=f"flow-{i}",
                account_id=1,
                event_date=day,
                currency="RUB",
                signed_amount_kopecks=amount,
                revision_id=1,
                material_signature="e" * 64,
            )
            for i, (day, amount) in enumerate(flows)
        ),
        cash_coverage_state="complete",
        cash_coverage_revision_id=1,
        membership_state="complete",
        exposure_state="assessed",
    ).model_copy(update=changes)


@pytest.mark.parametrize(
    ("v0", "v1", "flows", "expected"),
    [
        (1000000, 1121100, ((MID, 100000),), "0.0201"),
        (1000000, 1500000, ((MID, 500000),), "0"),
        (1000000, 500000, ((MID, -500000),), "0"),
        (1000000, 1028000, (), "0.028"),
        (1000000, 800000, (), "-0.2"),
        (1000000, 1100000, ((T1, 100000),), "0"),
    ],
)
def test_decimal_period_return_and_independent_ruble_residual(v0, v1, flows, expected):
    result = calculate_statement_return(basis(v0, v1, flows))
    assert result.status == result.quality == "indicative"
    assert result.annualized is False and NKD_WARNING in result.warnings
    with localcontext() as ctx:
        ctx.prec = 60
        rate = Decimal(result.rate_fraction)
        assert abs(rate - Decimal(expected)) <= Decimal("1e-8")
        # Independently compound the opening RUB amount and each real crossing.
        growth = Decimal(1) + rate
        endpoint = Decimal(v0) / 100 * growth
        for day, amount in flows:
            endpoint += Decimal(amount) / 100 * growth ** (Decimal((T1 - day).days) / 30)
        assert abs(endpoint - Decimal(v1) / 100) < Decimal("0.01")


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"cash_coverage_state": "unknown"}, "account_crossing_coverage_unproved"),
        ({"cash_coverage_revision_id": None}, "account_crossing_coverage_unproved"),
        ({"membership_state": "unknown"}, "statement_account_membership_unproved"),
        ({"exposure_state": "unknown"}, "material_account_exposure_unassessed"),
        ({"t0": T1}, "statement_interval_invalid"),
        ({"sources": ()}, "statement_source_missing"),
        ({"reason_codes": ("missing_dated_crossing",)}, "missing_dated_crossing"),
    ],
)
def test_unknown_evidence_never_becomes_zero(changes, reason):
    result = calculate_statement_return(basis(1000000, 1000000, (), **changes))
    assert result.rate_fraction is None and result.status == "unavailable"
    assert reason in result.reason_codes


def test_endpoint_crossing_boundaries_components_and_root_guards():
    start = basis()
    invalid = [
        (
            start.model_copy(
                update={"opening": start.opening.model_copy(update={"account_id": 2})}
            ),
            "statement_endpoint_identity_mismatch",
        ),
        (
            start.model_copy(
                update={"closing": start.closing.model_copy(update={"cash_kopecks": None})}
            ),
            "statement_endpoint_value_unavailable",
        ),
        (
            start.model_copy(
                update={"closing": start.closing.model_copy(update={"total_value_kopecks": 0})}
            ),
            "statement_endpoint_components_mismatch",
        ),
        (
            start.model_copy(
                update={"crossings": (start.crossings[0].model_copy(update={"event_date": T0}),)}
            ),
            "statement_crossing_evidence_invalid",
        ),
        (
            start.model_copy(
                update={"crossings": (start.crossings[0].model_copy(update={"account_id": 2}),)}
            ),
            "statement_crossing_evidence_invalid",
        ),
        (
            start.model_copy(update={"crossings": start.crossings * 2}),
            "statement_crossing_identity_ambiguous",
        ),
        (basis(0, 1000000, ()), "not_computable_xirr_no_valid_root"),
        (
            basis(1000000, 500000, ((MID, -2000000), (date(2026, 9, 16), 2000000))),
            "not_computable_xirr_root_ambiguity",
        ),
    ]
    for values, reason in invalid:
        result = calculate_statement_return(values)
        assert result.rate_fraction is None and reason in result.reason_codes
    result = calculate_statement_return(start, max_iterations=0)
    assert result.rate_fraction is None
    assert "not_computable_xirr_convergence_failed" in result.reason_codes


def test_retained_coupon_and_fee_are_already_inside_endpoint_cash():
    values = basis(1000000, 1000000, ())
    values = values.model_copy(
        update={
            "closing": values.closing.model_copy(
                update={"cash_kopecks": 28000, "total_value_kopecks": 1028000}
            )
        }
    )
    result = calculate_statement_return(values)
    assert abs(Decimal(result.rate_fraction) - Decimal("0.028")) <= Decimal("1e-8")
    assert result.crossings == ()
    assert result.closing.positions_value_kopecks == 1000000
    assert result.closing.cash_kopecks == 28000
    assert NKD_WARNING in result.warnings


def native_xml(*, opaque=False):
    root = ET.fromstring(broker_month_xml())
    for name in ("Trades", "Trades2"):
        section = root.find(f"{{MyBroker}}{name}/{{MyBroker}}Report")
        for child in list(section):
            section.remove(child)
    p = root.find(".//{MyBroker}Details[@ISIN1]")
    p.set("income_rest", "10")
    p.set("income_volume", "10000")
    p.set("real_volume", "10280")
    rub = root.find(".//{MyBroker}Details[@active_name='RUB']")
    rub.set("income_rest", "0")
    rub.set("real_rest", "0")
    if opaque:
        section = root.find("{MyBroker}Trades3/{MyBroker}Report")
        ET.SubElement(section, "{MyBroker}Tablix1")
    return ET.tostring(root, encoding="utf-8")


def prepared(database, *, covered=False, opaque=False):
    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    raw = native_xml(opaque=opaque)
    reviewed = _broker_month_preview(client, intent, raw)
    assert reviewed["can_apply"], reviewed
    applied = _broker_month_apply(client, intent, reviewed, raw)
    assert applied.status_code == 200, applied.text
    if covered:
        with database.session_factory() as session:
            continuous_membership(session, 1)
            candidate = SourceCashIntent(
                account_id=1, opening_date=date(2029, 12, 31), closing_date=date(2030, 1, 31)
            )
            certify(session, claims(session, candidate, zero=True))
    return client, raw


def test_committed_native_facts_missing_flows_and_zero_write_preview_export(database):
    client, raw = prepared(database)
    writes = []

    def spy(_connection, _cursor, statement, _parameters, _context, _many):
        if (
            statement.lstrip()
            .upper()
            .startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER"))
        ):
            writes.append(statement)

    event.listen(database.engine, "before_cursor_execute", spy)
    try:
        url = "/api/broker-statement-returns?account_id=1&request_id=synthetic-batch"
        response = client.get(url)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "unavailable" and result["rate_fraction"] is None
        assert result["opening"]["total_value_kopecks"] == "1000000"
        assert result["closing"]["total_value_kopecks"] == "1028000"
        assert result["t0"] == "2029-12-31" and result["t1"] == "2030-01-31"
        assert "account_crossing_coverage_unproved" in result["reason_codes"]
        previewed = client.post(
            "/api/broker-statement-returns/preview",
            data={"account_id": "1", "request_id": "synthetic-batch"},
            files={"file": (FILENAME, raw, "application/xml")},
        )
        assert previewed.status_code == 200, previewed.text
        assert previewed.json() == result
        assert client.get(url.replace("returns?", "returns/export?")).json() == result
        assert client.get(url.replace("account_id=1", "account_id=2")).status_code == 404
        assert client.get("/api/broker-statement-returns/sources?account_id=2").json() == []
        assert len(client.get("/api/broker-statement-returns/sources?account_id=1").json()) == 1
        assert writes == []
    finally:
        event.remove(database.engine, "before_cursor_execute", spy)


def test_effective_existing_coverage_permits_indicative_but_exact_stays_closed(database):
    client, _ = prepared(database, covered=True)
    result = client.get(
        "/api/broker-statement-returns?account_id=1&request_id=synthetic-batch"
    ).json()
    assert result["status"] == "indicative", result
    assert abs(Decimal(result["rate_fraction"]) - Decimal("0.028")) < Decimal("1e-8")
    assert result["cash_coverage_state"] == "complete"
    assert PERIOD_WARNING in result["warnings"]
    assert client.get("/api/broker-months/synthetic-batch").json()["exact_return_ready"] is False
    # The strict source-native endpoint reader is still unavailable as exact XIRR.
    exact = client.get(
        "/api/performance/xirr?scope=account&account_id=1&start_date=2029-12-31&end_date=2030-01-31"
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["quality"] == "unavailable"


@pytest.mark.parametrize(
    "change",
    ["source", "hash", "mapping_json", "date", "account", "projection", "membership", "coverage"],
)
def test_revision_and_stale_read_are_fail_closed(database, change):
    client, _ = prepared(database, covered=True)
    with database.session_factory() as session:
        original = read_statement_return(session, request_id="synthetic-batch", account_id=1)
        source = session.scalar(select(MyBrokerImport))
        if change == "source":
            source.normalized_json += " "
        elif change == "hash":
            source.document_sha256 = "f" * 64
        elif change == "mapping_json":
            session.execute(text("UPDATE mybroker_imports SET mappings_json='['"))
        elif change == "date":
            session.scalar(select(ReportingMonth)).snapshot_date = date(2030, 1, 30)
        elif change == "account":
            session.get(Account, 1).status = "frozen"
        elif change == "projection":
            session.execute(
                text("UPDATE position_snapshots SET market_value_kopecks=market_value_kopecks+1")
            )
        elif change == "membership":
            session.execute(
                text("UPDATE account_performance_scope_memberships SET include_in_returns=0")
            )
        else:
            session.execute(text("UPDATE cash_boundary_coverages SET coverage_state='unknown'"))
        session.commit()
        changed = read_statement_return(
            session,
            request_id="synthetic-batch",
            account_id=1,
            expected_fingerprint=original.material_fingerprint,
        )
    assert changed.rate_fraction is None and changed.status == "unavailable"
    assert "statement_preview_stale" in changed.reason_codes
    if change in {"source", "hash", "mapping_json"}:
        assert changed.opening.total_value_kopecks is None


def test_diagnostic_empty_wrapper_cannot_assess_financial_exposure(database):
    client, _ = prepared(database, opaque=True)
    result = client.get(
        "/api/broker-statement-returns?account_id=1&request_id=synthetic-batch"
    ).json()
    assert result["rate_fraction"] is None
    assert "material_account_exposure_unassessed" in result["reason_codes"]


def test_new_competing_source_blocks_existing_result(database):
    from test_statement_import_mybroker import apply, preview

    client, raw = prepared(database, covered=True)
    root = ET.fromstring(raw)
    root.find(".//{MyBroker}Details[@ISIN1]").set("active_name", "Synthetic competing name")
    other = ET.tostring(root, encoding="utf-8")
    with database.session_factory() as session:
        apply(session, other, preview(session, other))
    result = client.get(
        "/api/broker-statement-returns?account_id=1&request_id=synthetic-batch"
    ).json()
    assert result["rate_fraction"] is None
    assert "statement_overlapping_source" in result["reason_codes"]


def test_native_midpoint_deposit_from_existing_money_and_h2_coverage(database):
    from copy import deepcopy

    from test_statement_import_mybroker_endpoints import _money_apply, _money_decide
    from test_statement_import_mybroker_money_candidates import original

    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.services.reporting_months import create_reporting_month

    root = ET.fromstring(native_xml())
    incoming = ET.fromstring(original())
    table = deepcopy(incoming.find("{MyBroker}Trades2/{MyBroker}Report/{MyBroker}Tablix1"))
    day = table.find(".//{MyBroker}settlement_date")
    day.set("settlement_date", "2030-09-15T00:00:00")
    collection = table.find(".//{MyBroker}rn_Collection")
    for row in list(collection):
        if row.find(".//{MyBroker}comment").get("comment") != "из АО Synthetic bank":
            collection.remove(row)
        else:
            row.set("last_update", "2030-09-15T10:00:00")
            row.find(".//{MyBroker}p_code[@volume]").set("volume", "1000.00")
    root.find("{MyBroker}Trades2/{MyBroker}Report").append(table)
    root.find(".//{MyBroker}Details[@ISIN1]").set("real_volume", "10211")
    root.find(".//{MyBroker}Details[@active_name='RUB']").set("real_rest", "1000")
    raw = ET.tostring(root, encoding="utf-8")
    filename = "Брокерский 1234567 (01.09.30-30.09.30).xml"
    with database.session_factory() as session:
        month = create_reporting_month(session, year=2030, month=9, snapshot_date=date(2030, 9, 30))
        continuous_membership(session, 1)
        month_id = month.id
    scope = {"reporting_month_id": month_id, "account_id": 1}
    client = TestClient(create_app(database=database))
    plan = _broker_month_preview(client, scope, raw, filename)
    result = _broker_month_apply(client, scope, plan, raw, filename=filename)
    assert result.status_code == 200, result.text
    with database.session_factory() as session:
        intent = MoneyIntent(
            contract_version="broker_money_v1", base_request_id="synthetic-batch", **scope
        )
        intent = _money_decide(session, intent, [(filename, raw)], bond_id=1)
        _money_apply(session, intent, [(filename, raw)])
        candidate = SourceCashIntent(
            account_id=1, opening_date=date(2030, 8, 31), closing_date=date(2030, 9, 30)
        )
        certify(session, claims(session, candidate))
        value = read_statement_return(session, request_id="synthetic-batch", account_id=1)
    assert value.status == "indicative", value.reason_codes
    assert abs(Decimal(value.rate_fraction) - Decimal("0.0201")) <= Decimal("1e-8")
    assert len(value.crossings) == 1
    assert value.crossings[0].event_date == date(2030, 9, 15)
    assert value.crossings[0].signed_amount_kopecks == 100000


def section_result(client, *, request_id="section-base", expected=None, export=False):
    response = client.get(
        "/api/broker-statement-returns" + ("/export" if export else ""),
        params={
            "account_id": 1,
            "request_id": request_id,
            **({"expected_fingerprint": expected} if expected else {}),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def assert_opaque_unavailable(value):
    assert value["status"] == value["quality"] == "unavailable"
    assert value["rate_fraction"] is None and not value["annualized"]
    assert value["exposure_state"] == "unknown"
    assert "material_account_exposure_unassessed" in value["reason_codes"]
    assert all(s["period_scope"] == "unknown" for s in value["section_authority"])


def test_section_safe_xml_missing_and_partial_grants_are_not_period_evidence(database):
    client, intent, raw = section_setup(database, raw=metadata_xml(native_xml()))
    missing = section_result(client)
    assert_opaque_unavailable(missing)
    assert [s["state"] for s in missing["section_authority"]] == ["missing"] * 2
    assert all(
        s["pattern"] is None and s["head_request_id"] is None for s in missing["section_authority"]
    )
    single = {**intent, "sections": [{"section": "4_Transfers"}]}
    _section_accept(client, single, raw)
    partial = section_result(client)
    assert_opaque_unavailable(partial)
    assert [s["state"] for s in partial["section_authority"]] == ["effective", "missing"]
    assert partial["section_authority"][0]["pattern"] == "empty_transfers"
    assert partial["section_authority"][1]["pattern"] is None
    assert "5_UFSR_unsupported" in partial["reason_codes"]
    assert partial["cash_coverage_state"] == "unknown"
    assert partial["material_fingerprint"] != missing["material_fingerprint"]


def test_section_effective_get_original_export_ten_reads_no_writes(database):
    from test_statement_import_mybroker_endpoints import _all_month_tables

    client, intent, raw = section_setup(database, raw=metadata_xml(native_xml()))
    proof = _section_accept(client, intent, raw)["proof"]
    before = _all_month_tables(database)
    writes = []

    def spy(_connection, _cursor, statement, _parameters, _context, _many):
        if (
            statement.lstrip()
            .upper()
            .startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"))
        ):
            writes.append(statement)

    event.listen(database.engine, "before_cursor_execute", spy)
    try:
        result = section_result(client)
        assert_opaque_unavailable(result)
        for s, shape in zip(result["section_authority"], proof["sections"], strict=True):
            assert (s["import_id"], s["account_id"], s["reporting_month_id"]) == (
                intent["import_id"],
                intent["account_id"],
                intent["reporting_month_id"],
            )
            assert s["state"] == "effective" and s["pattern"] == shape["pattern"]
            assert s["head_request_id"] == "section-proof"
            assert len(s["proof_material_signature"]) == 64
        for _ in range(10):
            assert section_result(client) == result
            previewed = client.post(
                "/api/broker-statement-returns/preview",
                data={"account_id": "1", "request_id": "section-base"},
                files={"file": (FILENAME, raw, "application/xml")},
            )
            assert previewed.status_code == 200, previewed.text
            assert previewed.json() == result
            exported = client.get(
                "/api/broker-statement-returns/export",
                params={
                    "account_id": 1,
                    "request_id": "section-base",
                    "expected_fingerprint": result["material_fingerprint"],
                },
            )
            assert exported.headers["content-type"] == "application/json"
            assert "attachment" in exported.headers["content-disposition"]
            assert json.loads(exported.content) == result
        assert writes == []
        assert _all_month_tables(database) == before
    finally:
        event.remove(database.engine, "before_cursor_execute", spy)


@pytest.mark.parametrize("change", ["account", "source", "mapping", "month"])
def test_section_stale_dependencies_never_disclose_a_safe_pattern(database, change):
    client, intent, raw = section_setup(database, raw=metadata_xml(native_xml()))
    _section_accept(client, intent, raw)
    original = section_result(client)
    with database.session_factory() as session:
        if change == "account":
            session.get(Account, 1).status = "frozen"
        elif change == "source":
            session.get(MyBrokerImport, intent["import_id"]).normalized_json += " "
        elif change == "mapping":
            source = session.get(MyBrokerImport, intent["import_id"])
            bindings = json.loads(source.mappings_json)
            next(b for b in bindings if b["kind"] == "account")["hermes_id"] = 2
            source.mappings_json = json.dumps(bindings)
        else:
            session.get(ReportingMonth, intent["reporting_month_id"]).snapshot_date = date(
                2030, 1, 30
            )
        session.commit()
    result = section_result(client, expected=original["material_fingerprint"])
    assert_opaque_unavailable(result)
    assert all(
        s["state"] == "blocked" and s["pattern"] is None for s in result["section_authority"]
    )
    assert "statement_preview_stale" in result["reason_codes"]
    assert section_result(client, expected=original["material_fingerprint"], export=True) == result


def test_section_aba_fresh_reacceptance_uses_only_current_head(database):
    client, intent, raw = section_setup(database, raw=metadata_xml(native_xml()))
    _section_accept(client, intent, raw, "proof-A")
    first = section_result(client)
    with database.session_factory() as session:
        account = session.get(Account, 1)
        name = account.name
        account.name = "Synthetic ABA"
        session.commit()
        account.name = name
        session.commit()
    aba = section_result(client, expected=first["material_fingerprint"])
    assert all(s["state"] == "blocked" and s["pattern"] is None for s in aba["section_authority"])
    assert "statement_preview_stale" in aba["reason_codes"]
    replacement = {
        **intent,
        "sections": [{**s, "expected_predecessor": "proof-A"} for s in intent["sections"]],
    }
    _section_accept(client, replacement, raw, "proof-C")
    fresh = section_result(client)
    assert_opaque_unavailable(fresh)
    assert all(
        s["state"] == "effective" and s["head_request_id"] == "proof-C"
        for s in fresh["section_authority"]
    )
    assert fresh["reason_codes"] == first["reason_codes"]
    assert fresh["material_fingerprint"] != first["material_fingerprint"]


def test_section_head_change_with_unchanged_null_reasons_invalidates_preview_and_export(database):
    client, intent, raw = section_setup(database, raw=metadata_xml(native_xml()))
    proof = _section_accept(client, intent, raw, "proof-A")["proof"]
    first = section_result(client)
    # Synthetic sealed successor changes only the immutable head/chain material;
    # financial inputs and current dependencies stay identical.
    successor = deepcopy(proof)
    for s in successor["intent"]["sections"]:
        s["expected_predecessor"] = "proof-A"
    _insert_section_history(database, intent, "proof-B", successor)
    changed = section_result(client)
    assert changed["reason_codes"] == first["reason_codes"]
    assert changed["rate_fraction"] is first["rate_fraction"] is None
    assert (
        changed["section_authority"][0]["proof_material_signature"]
        != first["section_authority"][0]["proof_material_signature"]
    )
    assert all(s["head_request_id"] == "proof-B" for s in changed["section_authority"])
    assert changed["material_fingerprint"] != first["material_fingerprint"]
    stale = section_result(client, expected=first["material_fingerprint"])
    assert "statement_preview_stale" in stale["reason_codes"]
    assert section_result(client, expected=first["material_fingerprint"], export=True) == stale


@pytest.mark.parametrize(
    "case", ["corrupt", "fork", "missing-predecessor", "cycle", "cross-account", "shape"]
)
def test_section_bad_proof_chain_never_falls_back_to_old_safe_head(database, case):
    client, intent, raw = section_setup(database, raw=metadata_xml(native_xml()))
    proof = _section_accept(client, intent, raw, "proof-A")["proof"]
    first = section_result(client)
    bad = deepcopy(proof)
    if case == "corrupt":
        bad.pop("bindings")
    elif case == "missing-predecessor":
        for s in bad["intent"]["sections"]:
            s["expected_predecessor"] = "absent"
    elif case == "cycle":
        for s in bad["intent"]["sections"]:
            s["expected_predecessor"] = "bad-proof"
    elif case == "cross-account":
        bad["intent"]["account_id"] = 2
    elif case == "shape":
        bad["sections"][0]["pattern"] = "economic_transfer"
    _insert_section_history(database, intent, "bad-proof", bad)
    result = section_result(client, expected=first["material_fingerprint"])
    assert_opaque_unavailable(result)
    assert all(
        s["state"] == "blocked" and s["pattern"] is None and s["head_request_id"] is None
        for s in result["section_authority"]
    )
    expected = (
        "section_authority_chain_conflict"
        if case in {"fork", "missing-predecessor", "cycle"}
        else "broker_month_receipt_invalid"
    )
    assert expected in result["reason_codes"]
    assert "statement_preview_stale" in result["reason_codes"]
    # Another unresolved fork must change material even with the same blockers.
    _insert_section_history(database, intent, "bad-proof-2", bad)
    second = section_result(client)
    assert second["material_fingerprint"] != result["material_fingerprint"]


def test_section_unexpected_none_proof_is_blocked_not_partial_response(database, monkeypatch):
    from hermes_finance.services import broker_sections

    client, intent, raw = section_setup(database, raw=metadata_xml(native_xml()))
    _section_accept(client, intent, raw)
    original = section_result(client)
    resolve_heads = broker_sections._heads

    def broken_heads(*args):
        heads, errors = resolve_heads(*args)
        return {s: (row, None) for s, (row, _proof) in heads.items()}, errors

    monkeypatch.setattr(broker_sections, "_heads", broken_heads)
    result = section_result(client, expected=original["material_fingerprint"])
    assert_opaque_unavailable(result)
    assert all(
        s["state"] == "blocked" and s["pattern"] is None for s in result["section_authority"]
    )
    assert "statement_section_evidence_invalid" in result["reason_codes"]


@pytest.mark.parametrize("both_safe", [False, True])
def test_section_safe_a_never_clears_unsafe_or_overlapping_b(database, both_safe):
    raw_a = metadata_xml(native_xml())
    root = ET.fromstring(raw_a)
    root.find(".//{MyBroker}Details[@ISIN1]").set("active_name", "Synthetic source B")
    if not both_safe:
        root.find("{MyBroker}Trades3/{MyBroker}Report/{MyBroker}Tablix1").set("volume", "5.00")
        root.find("{MyBroker}Trades4/{MyBroker}Report/{MyBroker}Tablix1").set(
            "Textbox4", "Неизвестен"
        )
    raw_b = ET.tostring(root)
    client, intent_a, _ = section_setup(database, raw=raw_a)
    intent_b = _section_second_source(client, intent_a, raw_b, "source-B")
    _section_accept(client, intent_a, raw_a, "proof-A")
    if both_safe:
        _section_accept(client, intent_b, raw_b, "proof-B")
    for request_id in ("section-base", "source-B"):
        result = section_result(client, request_id=request_id)
        assert_opaque_unavailable(result)
        assert "statement_overlapping_source" in result["reason_codes"]
        by_source = {
            i: [s for s in result["section_authority"] if s["import_id"] == i]
            for i in (intent_a["import_id"], intent_b["import_id"])
        }
        assert all(s["state"] == "effective" for s in by_source[intent_a["import_id"]])
        assert all(
            s["state"] == ("effective" if both_safe else "missing")
            for s in by_source[intent_b["import_id"]]
        )
        if not both_safe:
            assert {"4_Transfers_unsupported", "5_UFSR_unsupported"} <= set(result["reason_codes"])
            assert all(s["pattern"] is None for s in by_source[intent_b["import_id"]])


def test_effective_sections_do_not_override_real_h2_a2_reader(database):
    # Establish real accepted H2-A2 on a clean source first. A newly disclosed
    # opaque source retires its reviewed context, even after effective #800.
    client, _ = prepared(database, covered=True)
    with database.session_factory() as session:
        coverage_id = session.scalar(select(CashBoundaryCoverage.id))
        assert read_source_cash_coverage(session, coverage_id)["effective_state"] == "accepted"
        source_id = session.scalar(select(MyBrokerImport.id))
        month_id = session.scalar(select(ReportingMonth.id))
    intent = {
        "contract_version": "mybroker-section-disposition-v1",
        "account_id": 1,
        "reporting_month_id": month_id,
        "import_id": source_id,
        "base_request_id": "synthetic-batch",
        "sections": [{"section": "4_Transfers"}, {"section": "5_UFSR"}],
    }
    raw = metadata_xml(native_xml())
    safe = _section_second_source(client, intent, raw, "opaque-source")
    _section_accept(client, safe, raw)
    with database.session_factory() as session:
        frozen_s1 = session.get(MyBrokerImport, safe["import_id"]).normalized_json
        readback = read_source_cash_coverage(session, coverage_id)
        assert readback["effective_state"] == "retired"
        assert {"frozen_dependency_changed", "claim_binding_mismatch"} <= set(readback["blockers"])
        plan = preview_source_cash_coverage(
            session,
            SourceCashIntent(
                account_id=1, opening_date=date(2029, 12, 31), closing_date=date(2030, 1, 31)
            ),
        )
        assert not plan["can_apply"]
        assert "owner_cash_coverage_claims_missing" in plan["blockers"]
        authority = next(
            s["section_authority"]
            for s in plan["evidence"]["dependencies"]["sources"]
            if s["import_id"] == safe["import_id"]
        )
        assert {"4_Transfers_unsupported", "5_UFSR_unsupported"} <= set(authority["raw_blockers"])
        assert authority["effective_blockers"] == []
        result = read_statement_return(session, request_id="opaque-source", account_id=1)
        assert result.cash_coverage_state == "unknown"
        assert set(readback["blockers"]) <= set(result.reason_codes)
        assert all(
            s.state == "effective"
            for s in result.section_authority
            if s.import_id == safe["import_id"]
        )
        assert session.get(MyBrokerImport, safe["import_id"]).normalized_json == frozen_s1
        assert_opaque_unavailable(result.model_dump(mode="json"))
