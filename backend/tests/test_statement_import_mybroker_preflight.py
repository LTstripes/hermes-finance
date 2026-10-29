"""Fabricated original batches only; no Owner sources or reconstructed EOD."""

from copy import deepcopy
from datetime import date
from itertools import permutations
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from test_statement_import_mybroker import ACCOUNT, FILENAME, fixture, native_money_xml
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import broker_month_xml, draft_structure_xml, node

from hermes_finance.main import create_app
from hermes_finance.persistence import Base, MyBrokerImport
from hermes_finance.services.mybroker_import import stage_mybroker
from hermes_finance.services.mybroker_preflight import _difference, preview_batch
from hermes_finance.statement_import.mybroker import MyBrokerError, canonical, parse_mybroker


def original(
    month=1,
    *,
    start=None,
    end=None,
    trades=False,
    opening="8",
    closing="10",
    opening_value="800",
    closing_value="1000",
    cash_open="1400",
    cash_close="400",
):
    root = ET.fromstring(broker_month_xml())
    row = root.find(".//{MyBroker}Details[@ISIN1]")
    for key, value in {
        "income_rest": opening,
        "real_rest": closing,
        "forward_rest": closing,
        "income_volume": opening_value,
        "real_volume": closing_value,
    }.items():
        if value is None:
            row.attrib.pop(key, None)
        else:
            row.set(key, value)
    cash = root.find(".//{MyBroker}Details[@active_name='RUB']")
    cash.set("income_rest", cash_open)
    cash.set("real_rest", cash_close)
    if not trades:
        for outer in ("Trades", "Trades2"):
            report = root.find(f"{{MyBroker}}{outer}/{{MyBroker}}Report")
            for child in list(report):
                report.remove(child)
    import calendar

    start = start or date(2030, month, 1)
    end = end or date(2030, month, calendar.monthrange(2030, month)[1])
    filename = f"Брокерский 1234567 ({start:%d.%m.%y}-{end:%d.%m.%y}).xml"
    return filename, ET.tostring(root, encoding="utf-8")


def adjacent():
    return [
        original(),
        original(
            2,
            opening="10",
            closing="12",
            opening_value="1000",
            closing_value="1200",
            cash_open="400",
            cash_close="200",
        ),
    ]


def run(database, originals, **kwargs):
    with database.session_factory() as session:
        return preview_batch(session, originals=originals, **kwargs)


def snapshot(database):
    with database.session_factory() as session:
        return {
            t.name: list(session.execute(select(t)).tuples()) for t in Base.metadata.sorted_tables
        }


def test_adjacent_observations_are_separate_from_financial_completeness(database):
    result = run(database, adjacent())
    assert result["seams"][0]["state"] == "equal_observations"
    assert result["seams"][0]["rub_cash"]["delta_kopecks"] == 0
    assert all(d["mappings"]["state"] == "ready" for d in result["documents"])
    assert all(
        d["statuses"]["potential_incomplete_draft"]
        == "candidate_for_existing_separate_reviewed_draft_preview"
        for d in result["documents"]
    )
    assert all(d["statuses"]["financial_completeness"] == "unknown" for d in result["documents"])
    assert result["coverage_state"] == "unknown" and not result["financial_apply_available"]
    assert result["close_performance"] == "blocked"
    opening = result["documents"][0]["accounts"][0]["beginning"]
    assert opening["basis"] == "previous_day_eod"
    assert {"beginning_settled_inventory_unproven", "historical_membership_unknown"} <= set(
        opening["blockers"]
    )
    assert opening["complete_endpoint_state"] == "unknown"


@pytest.mark.parametrize(
    "field,value",
    [
        ("cash_open", "400.01"),
        ("cash_open", "399.99"),
        ("opening_value", "1000.01"),
        ("opening", "10.00001"),
    ],
)
def test_exact_seam_breaks_block_candidate(database, field, value):
    kwargs = {"opening": "10", "closing": "12", "opening_value": "1000", "cash_open": "400"}
    kwargs[field] = value
    result = run(database, [original(), original(2, **kwargs)])
    seam = result["seams"][0]
    assert seam["state"] == "conflict"
    assert all(
        d["statuses"]["potential_incomplete_draft"] == "blocked" for d in result["documents"]
    )
    if field == "cash_open":
        assert seam["rub_cash"]["delta_kopecks"] == (1 if value == "400.01" else -1)


def test_exact_large_decimal_and_sub_kopeck_are_not_rounded():
    result = _difference(
        "1234567890123456789012345678901234567890.00",
        "1234567890123456789012345678901234567890.01",
        money=True,
    )
    assert result["delta_kopecks"] == 1
    fractional = _difference("1.001", "1.001", money=True)
    assert fractional["minor_unit_state"] == "sub_kopeck_observation"
    assert _difference(None, "0", money=True)["state"] == "unknown"


def test_partial_and_wide_cannot_lend_missing_july_august_eod(database):
    result = run(
        database,
        [
            original(6),
            original(9, start=date(2030, 9, 15)),
            original(start=date(2030, 1, 1), end=date(2030, 9, 30), closing="20"),
            original(7, end=date(2030, 7, 15)),
        ],
        requested_from=date(2030, 6, 1),
        requested_to=date(2030, 9, 30),
    )
    july, august = result["calendar"][1:3]
    for row in (july, august):
        assert row["state"] == "unknown" and row["endpoint_references"] == []
        assert row["blockers"] == ["whole_month_original_missing", "month_end_eod_missing"]
    wide = next(d for d in result["documents"] if d["document"]["covered_from"] == "2030-01-01")
    assert wide["range_kind"] == "partial_or_wide"
    assert wide["statuses"]["potential_incomplete_draft"] == "blocked"
    assert result["report_availability"][0]["report_2025"] == "unknown_missing_original"


def test_next_month_opening_can_observe_previous_eod_without_whole_month(database):
    result = run(
        database, [original(9)], requested_from=date(2030, 8, 1), requested_to=date(2030, 9, 30)
    )
    august = result["calendar"][0]
    assert august["state"] == "unknown" and august["whole_month_documents"] == []
    assert august["endpoint_references"][0]["sides"] == ["beginning"]
    assert august["blockers"] == ["whole_month_original_missing"]


def test_order_independence_duplicates_and_pending_settled(database):
    filename, raw = original(trades=True)
    root = ET.fromstring(raw)
    pending_root = ET.fromstring(fixture(pending=True, money=False, nkd="3.50", qty="2"))
    pending = pending_root.find(".//{MyBroker}Tablix3")
    report = root.find("{MyBroker}Trades/{MyBroker}Report")
    for child in list(report):
        report.remove(child)
    report.append(pending)
    money = root.find("{MyBroker}Trades2/{MyBroker}Report")
    for child in list(money):
        money.remove(child)
    early = (filename, ET.tostring(root))
    wide_name, wide_raw = original(
        start=date(2030, 1, 1), end=date(2030, 2, 28), trades=True, closing="12"
    )
    root = ET.fromstring(wide_raw)
    root.find(".//{MyBroker}Details[@trade_no]").set("summ_nkd", "3.50")
    settled = (wide_name, ET.tostring(root))
    later_name, later_raw = original(
        start=date(2030, 1, 1), end=date(2030, 3, 31), trades=True, closing="14"
    )
    root = ET.fromstring(later_raw)
    root.find(".//{MyBroker}Details[@trade_no]").set("summ_nkd", "3.50")
    later = (later_name, ET.tostring(root))
    outputs = [run(database, list(order)) for order in permutations([early, settled, later])]
    assert all(output == outputs[0] for output in outputs)
    trade = outputs[0]["native_trade_inventory"][0]
    assert trade["state"] == "pending_to_settled" and trade["conflicts"] == []
    assert trade["projection"]["accrued_interest"] == "3.5"
    assert trade["projection"]["state"] == "settled"
    duplicate = run(database, [settled, later])["native_trade_inventory"][0]
    assert duplicate["state"] == "exact_duplicate"
    assert duplicate["money_nkd_fee_authority"] == "unknown"


@pytest.mark.parametrize(
    "change,code",
    [
        ("core", "immutable_trade_conflict"),
        ("duplicate", "native_identity_multiplicity_conflict"),
        ("missing", "native_identity_missing_in_overlap"),
    ],
)
def test_native_conflicts_are_not_economically_deduplicated(database, change, code):
    name, raw = original(trades=True)
    wider_name, wider = original(
        start=date(2030, 1, 1), end=date(2030, 2, 28), trades=True, closing="12"
    )
    root = ET.fromstring(wider)
    row = root.find(".//{MyBroker}Details[@trade_no]")
    collection = root.find(".//{MyBroker}Tablix2/{MyBroker}Details_Collection")
    if change == "core":
        row.set("qty", "3")
    elif change == "duplicate":
        collection.append(deepcopy(row))
    else:
        collection.remove(row)
    result = run(database, [(name, raw), (wider_name, ET.tostring(root))])
    assert code in result["conflicts"]
    assert result["native_trade_inventory"][0]["state"] == "conflict"


def test_unknown_money_repo_unparsed_nkd_and_fees_are_retained(database):
    name, raw = original(trades=True)
    root = ET.fromstring(raw)
    row = root.find(".//{MyBroker}Details[@trade_no]")
    row.set("trade_no", "B1001")
    row.set("repo_no", "B1002")
    row.set("comment", "репо ч.1")
    row.set("summ_nkd", "7.15")
    row.set("bank_tax", "2.45")
    root.find(".//{MyBroker}comment[@comment]").set("comment", "Synthetic opaque operation")
    rn = root.find(".//{MyBroker}rn")
    root.find(".//{MyBroker}rn_Collection").append(deepcopy(rn))
    node(root.find("{MyBroker}Trades3/{MyBroker}Report"), "Tablix1")
    node(root.find("{MyBroker}Trades4/{MyBroker}Report"), "Tablix1")
    result = run(database, [(name, ET.tostring(root))])
    inventory = result["documents"][0]["inventory"]
    assert inventory["unsupported_money_count"] == 2
    assert inventory["identityless_trade_count"] == inventory["repo_count"] == 1
    trade = inventory["trades"][0]
    assert trade["accrued_interest"] == "7.15" and trade["bank_commission"] == "2.45"
    assert inventory["money_nkd_fee_authority"] == "unknown"
    assert len(inventory["money"]) == 2 and all(
        r["kind"] == "unsupported" for r in inventory["money"]
    )
    assert {"4_Transfers_unsupported", "5_UFSR_unsupported"} <= set(inventory["syntax_blockers"])
    assert result["native_trade_inventory"] == []


def test_extra_account_instrument_type_and_denomination_missing(database):
    name, raw = original(trades=True)
    root = ET.fromstring(raw)
    row = deepcopy(root.find(".//{MyBroker}Details[@ISIN1]"))
    row.set("ISIN1", "RU000A000001")
    row.set("acc_code", "UNMAPPED-ACCOUNT")
    row.attrib.pop("active_type")
    root.find(".//{MyBroker}Details_Collection").append(row)
    result = run(database, [(name, ET.tostring(root))])["documents"][0]
    assert result["mappings"]["state"] == "blocked"
    gaps = {g["code"] for g in result["mappings"]["evidence_gaps"]}
    assert {"instrument_type_unproven", "instrument_currency_unproven"} <= gaps
    assert "account_binding_required" in result["mappings"]["conflicts"]
    assert result["statuses"]["potential_incomplete_draft"] == "blocked"


def test_accepted_legacy_money_selector_and_missing_immutable_binder(database):
    raw = native_money_xml()
    with database.session_factory() as session:
        source = stage_mybroker(session, parse_mybroker(raw, FILENAME, money_linkage_version=None))
        session.commit()
        source_id = source.id
    before = snapshot(database)
    result = run(database, [(FILENAME, raw)])
    assert all(r["kind"] == "unsupported" for r in result["documents"][0]["document"]["money"])
    assert snapshot(database) == before
    with database.session_factory() as session:
        source = session.get(MyBrokerImport, source_id)
        stored = __import__("json").loads(source.normalized_json)
        stored.pop("document_sha256")
        source.normalized_json = canonical(stored)
        session.commit()
    result = run(database, [(FILENAME, raw)])
    assert "immutable_source_binder_mismatch" in result["documents"][0]["binder_blockers"]


@pytest.mark.parametrize("change", ["account", "range", "parser"])
def test_forged_accepted_filename_account_or_parser_fails_closed(database, change):
    name, raw = original()
    with database.session_factory() as session:
        source = stage_mybroker(session, parse_mybroker(raw, name))
        if change == "parser":
            source.parser_version = "future-parser"
        session.commit()
    if change == "account":
        name = name.replace("1234567", "7654321")
    elif change == "range":
        name = name.replace("31.01.30", "28.02.30")
    result = run(database, [(name, raw)])["documents"][0]
    assert result["binder_blockers"] == ["immutable_source_binder_mismatch"]
    assert result["statuses"]["potential_incomplete_draft"] == "blocked"


def test_unpersisted_same_original_alternative_filename_fails_closed(database):
    first = original()
    second = (first[0].replace("31.01.30", "28.02.30"), first[1])
    result = run(database, [first, second])
    assert all("original_filename_conflict" in d["binder_blockers"] for d in result["documents"])


def test_legacy_family_refused_without_guessing_new_grammar(database):
    name, raw = original(1, start=date(2025, 1, 1), end=date(2025, 1, 31))
    root = ET.fromstring(raw)
    root.set("Name", "LegacyMyBroker")
    with pytest.raises(MyBrokerError, match="^family_unsupported$"):
        run(database, [(name, ET.tostring(root))])


def test_ten_http_previews_have_no_dml_or_table_changes_or_private_logs(database, caplog):
    before = snapshot(database)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", capture)
    try:
        client = TestClient(create_app(database=database))
        for _ in range(10):
            response = client.post(
                "/api/mybroker-preflight/preview",
                files=[("files", (name, raw, "application/xml")) for name, raw in adjacent()],
            )
            assert response.status_code == 200, response.text
            assert response.json()["kind"] == "preflight"
        assert not any(
            s.lstrip()
            .upper()
            .startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"))
            for s in statements
        )
    finally:
        event.remove(database.engine, "before_cursor_execute", capture)
    assert snapshot(database) == before
    assert ACCOUNT not in caplog.text and "<" not in caplog.text
    assert client.post("/api/mybroker-preflight/apply").status_code == 404


def test_bounds_bad_intent_and_sanitized_errors(database):
    with pytest.raises(MyBrokerError, match="^preflight_batch_size_invalid$"):
        run(database, [original()] * 9)
    with pytest.raises(MyBrokerError, match="^preflight_range_too_large$"):
        run(database, [original()], requested_from=date(2000, 1, 1), requested_to=date(2030, 1, 31))
    client = TestClient(create_app(database=database))
    name, raw = original()
    for intent in ('{"reporting_month_id":1}', '{"requested_from":"invalid-private-value"}'):
        response = client.post(
            "/api/mybroker-preflight/preview", files={"files": (name, raw)}, data={"intent": intent}
        )
        assert response.status_code == 422 and "preflight_intent_invalid" in response.text
    response = client.post(
        "/api/mybroker-preflight/preview", files={"files": ("private-path.xml", b"private-source")}
    )
    assert response.status_code == 422 and "xml_invalid" in response.text
    assert "private" not in response.text


def test_repeated_file_upload_is_not_native_multiplicity(database):
    item = original(trades=True)
    result = run(database, [item, item])
    assert len(result["documents"]) == 1 and result["documents"][0]["upload_count"] == 2
    assert result["native_trade_inventory"][0]["state"] == "observed"
    assert result["conflicts"] == []


def test_missing_monthly_endpoint_is_not_observed_zero(database):
    name, raw = original(opening=None, closing_value=None)
    root = ET.fromstring(raw)
    cash = root.find(".//{MyBroker}Details[@active_name='RUB']")
    cash.attrib.pop("real_rest")
    result = run(database, [(name, ET.tostring(root))])
    month = result["calendar"][0]
    assert month["whole_month_original_state"] == "observed"
    assert month["state"] == month["endpoint_state"] == "unknown"
    assert month["blockers"] == ["month_end_eod_unavailable"]
    assert result["documents"][0]["accounts"][0]["ending"]["components"]["rub_cash"] == "unknown"
    assert result["documents"][0]["statuses"]["potential_incomplete_draft"] == "blocked"


def test_unparsed_layout_and_mapping_metadata_conflict_are_visible(database):
    name, raw = original()
    root = ET.fromstring(raw)
    root.find(".//{MyBroker}Details[@ISIN1]").set("active_type", "Облигации")
    node(root.find("{MyBroker}Trades/{MyBroker}Report"), "UnknownNativeWrapper")
    document = run(database, [(name, ET.tostring(root))])["documents"][0]
    assert "unparsed_source_rows" in document["inventory"]["syntax_blockers"]
    assert "instrument_metadata_conflict" in document["mappings"]["conflicts"]
    assert document["mappings"]["instruments"][0]["state"] == "ambiguous"
    assert document["statuses"]["potential_incomplete_draft"] == "blocked"


def test_distinct_accounts_accept_only_their_applicable_batch_bindings(database):
    from hermes_finance.services.accounts import create_account

    with database.session_factory() as session:
        account = create_account(session, name="Second synthetic account", account_type="brokerage")
        second_id = account.id
    first = original()
    root = ET.fromstring(first[1])
    for row in root.iter():
        if row.get("acc_code") == ACCOUNT:
            row.set("acc_code", "7654321-000")
    second = (first[0].replace("1234567", "7654321"), ET.tostring(root))
    bindings = [
        {"identity": alias, "hermes_id": target}
        for alias, target in (
            ("1234567", 1),
            (ACCOUNT, 1),
            ("7654321", second_id),
            ("7654321-000", second_id),
        )
    ]
    results = [
        run(database, order, account_bindings=bindings)
        for order in ([first, second], [second, first])
    ]
    assert results[0] == results[1]
    for document in results[0]["documents"]:
        assert document["mappings"]["conflicts"] == []
        assert (
            document["statuses"]["potential_incomplete_draft"]
            == "candidate_for_existing_separate_reviewed_draft_preview"
        )
        aliases = {b["identity"] for b in document["mappings"]["accounts"]}
        expected = (
            {"1234567", ACCOUNT}
            if document["document"]["filename_account"] == "1234567"
            else {"7654321", "7654321-000"}
        )
        assert aliases == expected
    for bad, code in (
        (bindings + [bindings[0]], "duplicate_account_alias"),
        (bindings + [{"identity": "UNOBSERVED", "hermes_id": 1}], "account_alias_unobserved"),
    ):
        with pytest.raises(MyBrokerError, match=f"^{code}$"):
            run(database, [first, second], account_bindings=bad)
    conflicting = [
        {**b, "hermes_id": second_id} if b["identity"] == ACCOUNT else b for b in bindings
    ]
    result = run(database, [first, second], account_bindings=conflicting)
    assert any(
        "account_mapping_conflict" in d["mappings"]["conflicts"] for d in result["documents"]
    )


def test_http_upload_never_spools_even_above_starlette_threshold(database, monkeypatch):
    import starlette.formparsers

    def no_disk(*args, **kwargs):
        raise AssertionError("preflight must not create a spooled original")

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", no_disk)
    name, raw = original()
    raw += b" " * (2 * 1024 * 1024)
    client = TestClient(create_app(database=database))
    response = client.post("/api/mybroker-preflight/preview", files={"files": (name, raw)})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("boundary", ["per_file", "aggregate", "count", "intent", "header"])
def test_http_stream_bounds_reject_before_service_or_spooling(database, monkeypatch, boundary):
    import starlette.formparsers

    import hermes_finance.api.mybroker_preflight as api

    def forbidden(*args, **kwargs):
        raise AssertionError("rejected upload must not spool or enter the service")

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", forbidden)
    monkeypatch.setattr(api, "preview_batch", forbidden)
    name, raw = original()
    files = [("files", (name, raw))]
    data = {}
    expected = 413
    if boundary == "per_file":
        monkeypatch.setattr(api, "MAX_BYTES", len(raw) - 1)
    elif boundary == "aggregate":
        monkeypatch.setattr(api, "MAX_BATCH_BYTES", len(raw) * 2 - 1)
        files *= 2
    elif boundary == "count":
        files *= 9
        expected = 422
    elif boundary == "intent":
        monkeypatch.setattr(api, "MAX_INTENT_BYTES", 3)
        data["intent"] = "{   }"
    else:
        monkeypatch.setattr(api, "MAX_HEADER_BYTES", 8)
    client = TestClient(create_app(database=database))
    response = client.post("/api/mybroker-preflight/preview", files=files, data=data)
    assert response.status_code == expected, response.text


def test_truncated_stream_and_invalid_content_type_fail_closed(database):
    client = TestClient(create_app(database=database))
    for body, content_type in (
        (b"private-body", "application/xml"),
        (
            b'--boundary\r\nContent-Disposition: form-data; name="files"; filename="private.xml"\r\n\r\nprivate',
            "multipart/form-data; boundary=boundary",
        ),
    ):
        response = client.post(
            "/api/mybroker-preflight/preview", content=body, headers={"content-type": content_type}
        )
        assert response.status_code == 422 and "preflight_multipart_invalid" in response.text
        assert "private" not in response.text


def test_settled_trade_missing_from_quiet_same_account_overlap_is_conflict(database):
    traded = original(trades=True)
    quiet = ("Брокерский 1234567 (01.01.30-28.02.30).xml", fixture(quiet=True))
    results = [run(database, order) for order in ([traded, quiet], [quiet, traded])]
    assert results[0] == results[1]
    row = results[0]["native_trade_inventory"][0]
    assert row["state"] == "conflict"
    assert row["conflicts"] == ["native_identity_missing_in_overlap"]
    assert len(row["missing_in_documents"]) == 1


@pytest.mark.parametrize("footer,money", [(True, False), (False, True), (True, True)])
def test_preflight_accepted_incomplete_draft_identity_retains_all_financial_warnings(
    database, footer, money
):
    from hermes_finance.statement_import.mybroker_identity import parse_identity

    root = ET.fromstring(draft_structure_xml(footer=footer, money=money))
    root.find(".//{MyBroker}Details[@trade_no]").set("summ_nkd", "3.50")
    root.find(".//{MyBroker}Details[@trade_no]").set("bank_tax", "2.45")
    root.find(".//{MyBroker}comment[@comment]").set("comment", "Fabricated opaque Money")
    raw = ET.tostring(root)
    frozen = parse_mybroker(raw, FILENAME)
    assert "unparsed_source_rows" in parse_identity(raw, FILENAME)["conflicts"]
    expected = parse_identity(raw, FILENAME, incomplete_draft=True)
    assert expected["conflicts"] == [] and "draft_structure" in expected
    before = snapshot(database)
    client = TestClient(create_app(database=database))
    response = client.post("/api/mybroker-preflight/preview", files={"files": (FILENAME, raw)})
    assert response.status_code == 200, response.text
    result = response.json()
    document = result["documents"][0]
    assert document["mappings"]["conflicts"] == []
    assert (
        document["statuses"]["potential_incomplete_draft"]
        == "candidate_for_existing_separate_reviewed_draft_preview"
    )
    assert document["draft_structure"] == expected["draft_structure"]
    assert document["draft_structure"]["financial_authority"] == "none"
    assert document["inventory"]["syntax_blockers"] == frozen["syntax_blockers"]
    assert "unparsed_source_rows" in document["inventory"]["syntax_blockers"]
    assert {
        "money_semantics_unsupported",
        "commission_basis_unresolved",
        "settlement_cash_missing_or_ambiguous",
    } <= set(document["inventory"]["cash_blockers"])
    assert document["inventory"]["trades"][0]["accrued_interest"] == "3.5"
    assert document["inventory"]["trades"][0]["bank_commission"] == "2.45"
    assert document["inventory"]["unsupported_money_count"] == len(frozen["money"]) == 1
    assert document["statuses"]["financial_completeness"] == result["coverage_state"] == "unknown"
    assert document["statuses"]["close_performance"] == "blocked"
    assert not result["financial_apply_available"]
    assert all(
        "unparsed_source_rows" in document["accounts"][0][side]["blockers"]
        for side in ("beginning", "ending")
    )
    assert snapshot(database) == before
    assert client.post("/api/mybroker-preflight/apply").status_code == 404


@pytest.mark.parametrize(
    "mutation", ["hidden_identity", "unknown_section", "currency", "repo", "duplicate_money"]
)
def test_preflight_incomplete_draft_proof_never_waives_suspicious_identity_or_economic_evidence(
    database, mutation
):
    root = ET.fromstring(draft_structure_xml())
    if mutation == "hidden_identity":
        root.find(".//{MyBroker}Details1").set("acc_code", "HIDDEN-SYNTHETIC-ALIAS")
    elif mutation == "unknown_section":
        node(root, "OtherSource")
    elif mutation == "currency":
        root.find(".//{MyBroker}Details[@trade_no]").set("Textbox14", "USD")
    elif mutation == "repo":
        root.find(".//{MyBroker}Details[@trade_no]").set("repo_no", "9000")
    else:
        parent = root.find(
            ".//{MyBroker}comment/{MyBroker}money_volume_begin1_Collection/{MyBroker}money_volume_begin1/{MyBroker}p_code_Collection/{MyBroker}p_code"
        )
        parent.append(deepcopy(parent[0]))
    before = snapshot(database)
    document = run(database, [(FILENAME, ET.tostring(root))])["documents"][0]
    assert document["mappings"]["conflicts"]
    assert document["statuses"]["potential_incomplete_draft"] == "blocked"
    assert "unparsed_source_rows" in document["inventory"]["syntax_blockers"]
    assert snapshot(database) == before


@pytest.mark.parametrize("case", ["partial_pair", "wide_then_month", "month_then_partial"])
def test_contiguous_reports_do_not_prove_adjacent_calendar_month_originals(database, case):
    left, right = adjacent()
    if case == "partial_pair":
        left = (left[0].replace("31.01.30", "15.01.30"), left[1])
        right = ("Брокерский 1234567 (16.01.30-31.01.30).xml", right[1])
    elif case == "wide_then_month":
        left = ("Брокерский 1234567 (01.12.29-31.01.30).xml", left[1])
    else:
        right = (right[0].replace("28.02.30", "15.02.30"), right[1])
    result = run(database, [left, right])
    assert result["seams"][0]["state"] == "equal_observations"
    assert (
        result["report_availability"][0]["adjacent_originals"]
        == "unknown_missing_adjacent_original"
    )


def test_two_complete_same_account_months_are_adjacent_even_across_year_boundary(database):
    left, right = adjacent()
    left = ("Брокерский 1234567 (01.12.30-31.12.30).xml", left[1])
    right = ("Брокерский 1234567 (01.01.31-31.01.31).xml", right[1])
    result = run(database, [right, left])
    assert result["seams"][0]["state"] == "equal_observations"
    assert result["report_availability"][0]["adjacent_originals"] == "observed"


def test_complete_months_with_different_filename_accounts_are_not_same_account_adjacent_originals(
    database,
):
    left, right = adjacent()
    # An identical native row alias cannot attest a different filename account.
    right = (right[0].replace("1234567", "7654321"), right[1])
    result = run(database, [left, right])
    assert result["seams"][0]["state"] == "equal_observations"
    assert all(
        r["adjacent_originals"] == "unknown_missing_adjacent_original"
        for r in result["report_availability"]
    )


@pytest.mark.parametrize("component", ["cash", "value"])
@pytest.mark.parametrize("left_value,right_value", [("400.001", "400.001"), ("400.001", "401.001")])
def test_http_sub_kopeck_monetary_endpoints_never_establish_equal_seam(
    database, component, left_value, right_value
):
    left, right = adjacent()
    left_root, right_root = ET.fromstring(left[1]), ET.fromstring(right[1])
    if component == "cash":
        left_root.find(".//{MyBroker}Details[@active_name='RUB']").set("real_rest", left_value)
        right_root.find(".//{MyBroker}Details[@active_name='RUB']").set("income_rest", right_value)
    else:
        left_root.find(".//{MyBroker}Details[@ISIN1]").set("real_volume", left_value)
        right_root.find(".//{MyBroker}Details[@ISIN1]").set("income_volume", right_value)
    before = snapshot(database)
    client = TestClient(create_app(database=database))
    response = client.post(
        "/api/mybroker-preflight/preview",
        files=[
            ("files", (left[0], ET.tostring(left_root))),
            ("files", (right[0], ET.tostring(right_root))),
        ],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    seam = result["seams"][0]
    comparison = seam["rub_cash"] if component == "cash" else seam["securities"][0]["value"]
    assert comparison["left"] == left_value and comparison["right"] == right_value
    assert comparison["minor_unit_state"] == "sub_kopeck_observation"
    assert comparison["delta_kopecks"] is None
    assert comparison["state"] == seam["state"] == "unknown"
    assert "monetary_endpoint_precision_invalid" in seam["blockers"]
    assert all(
        d["statuses"]["calendar_seam"] == "unknown"
        and d["statuses"]["potential_incomplete_draft"] == "blocked"
        for d in result["documents"]
    )
    assert result["financial_completeness"] == "unknown" and not result["financial_apply_available"]
    assert snapshot(database) == before


@pytest.mark.parametrize(
    "filename",
    [
        "renamed.xml",
        FILENAME.replace(".xml", " (1).xml"),
        FILENAME.replace("01.01.30-31.01.30", "01.02.30-28.02.30"),
    ],
)
def test_preflight_accepts_filename_hints_and_preserves_period_warnings(database, filename):
    _, raw = original(trades=True)
    before = snapshot(database)
    result = run(database, [(filename, raw)])
    document = result["documents"][0]["document"]
    if "01.02.30-28.02.30" in filename:
        assert (document["covered_from"], document["covered_to"]) == ("2030-02-01", "2030-02-28")
        assert document["warnings"] == ["filename_period_mismatch"]
    else:
        assert (document["covered_from"], document["covered_to"]) == ("2030-01-01", "2030-01-31")
        if filename == "renamed.xml":
            assert document["warnings"] == ["period_inferred_from_content"]
    assert result["documents"][0]["range_kind"] == "whole_month"
    assert snapshot(database) == before


def test_renamed_multiaccount_preflight_omits_empty_filename_groups(database):
    from test_statement_import_mybroker_identity import identity_xml

    from hermes_finance.persistence import Account

    root = ET.fromstring(identity_xml())
    other_alias = "7654321-000"
    root.find(".//{MyBroker}Textbox11").set("acc_code", other_alias)
    with database.session_factory() as session:
        target = session.scalar(select(Account).where(Account.account_type == "brokerage"))
        result = preview_batch(
            session,
            originals=[("renamed.xml", ET.tostring(root))],
            account_bindings=[
                {"identity": alias, "hermes_id": target.id} for alias in (ACCOUNT, other_alias)
            ],
        )
    entry = result["documents"][0]
    assert entry["document"]["filename_account"] == ""
    assert "" not in entry["document"]["source_accounts"]
    assert "source_account_conflict" not in entry["mappings"]["conflicts"]
    assert {a["source_account"] for a in entry["accounts"]} == {ACCOUNT, other_alias}
    assert result["calendar"] == result["report_availability"] == []


def investment_text(*, account="1234567", amount="10,00", future="999,00", end="31.01.2030"):
    from hermes_finance.statement_import.dto import ExtractedDocument, ExtractedPage, ExtractStatus

    return ExtractedDocument(
        ExtractStatus.OK,
        "a" * 64,
        1,
        (
            ExtractedPage(
                tuple(
                    [
                        "Инвестиционный",
                        "отчёт",
                        f"Период c 01.01.2030 по {end}",
                        f"Счёт {account} на {end} В долларах",
                        "2 090,00 ₽",
                        "",
                        "+90,00 ₽",
                        "Оценка портфеля",
                        f"на {end}",
                        f"Synthetic RU000A000000 {account}-000 Depository RUB 10  100,00  110,00  1 100,00  1 100,00  0",
                        "Денежный поток",
                        "Инструмент ISIN Дата выплаты Сумма в валюте",
                        "Акции",
                        f"Synthetic RU000A000000 RUB 20.01.2030 10  1,00  {amount}",
                        "Будущий денежный поток",
                        "Акции",
                        f"Synthetic RU000A000000 RUB 20.01.2030 10  1,00  {future}",
                    ]
                )
            ),
        ),
        None,
    )


def investment_original():
    from copy import deepcopy

    from test_statement_import_mybroker_endpoints import node

    root = ET.fromstring(native_money_xml(nkd="1.23"))
    p = root.find(".//{MyBroker}Details[@ISIN1]")
    for key, value in {
        "income_rest": "0",
        "income_volume": "0",
        "real_volume": "1100",
        "active_type": "Акции",
    }.items():
        p.set(key, value)
    node(
        root.find(".//{MyBroker}Details_Collection"),
        "Details",
        active_type="Валюта",
        active_name="RUB",
        acc_code=ACCOUNT,
        income_rest="0",
        real_rest="990",
    )
    root.find(".//{MyBroker}Details[@trade_no]").set("bank_tax", "10")
    rn = root.find(".//{MyBroker}rn")
    deposit = deepcopy(rn)
    op = deposit.find("{MyBroker}oper_type")
    op.set("oper_type", "deposit")
    op.find("{MyBroker}comment").set("comment", "")
    deposit.find(".//{MyBroker}p_code[@volume]").set("volume", "2000")
    root.find(".//{MyBroker}rn_Collection").append(deposit)
    return ET.tostring(root, encoding="utf-8")


def test_investment_pdf_selects_only_uploaded_accounts_and_actual_not_forecast():
    from hermes_finance.statement_import.investment_report import parse_investment_report

    report = parse_investment_report(investment_text(), {"1234567"})
    assert len(report.payouts) == 1 and report.payouts[0].net_kopecks == 1000
    assert report.positions[("1234567", "RU000A000000")] == ("10", 110000)
    assert report.closing == {"1234567": 209000}
    assert report.reported_pnl == {"1234567": 9000}
    foreign = parse_investment_report(
        investment_text(account="7654321", amount="invalid"), {"1234567"}
    )
    assert foreign.payouts == () and not foreign.issues


@pytest.mark.parametrize("amount", ["1,001", "-1,00", "0,00", "NaN", "Infinity"])
def test_investment_pdf_bad_actual_cell_is_explicit(amount):
    from hermes_finance.statement_import.investment_report import parse_investment_report

    report = parse_investment_report(investment_text(amount=amount), {"1234567"})
    assert not report.payouts
    assert ("1234567", "pdf_payout_row_invalid") in report.issues


@pytest.mark.parametrize(
    "narrative",
    [
        'погашение купона 4B02-806-12345-B-001P (Биржевые облигации АО "Synthetic") д.ф.10.01.30',
        'Дивиденды за 1 кв 2030 г. по акциям ПАО МКК "Synthetic" (1-01-12345-A). (Удержан налог 1 руб.)',
        'Дивиденды за 9 месяцев 2030 г. по акциям МКПАО "Synthetic 5" (1-01-12345-A). (Удержан налог 1 руб.)',
    ],
)
def test_investment_narrative_is_complete_bounded_grammar(narrative):
    from hermes_finance.statement_import.investment_money import parse_investment_money_security

    assert parse_investment_money_security(narrative) is not None
    assert parse_investment_money_security(narrative + " extra") is None
    assert parse_investment_money_security(narrative + "\n") is None


def test_investment_payout_uses_whole_registration_group_not_subset_sum():
    from dataclasses import replace

    from hermes_finance.domain.money_security import MoneySecurity
    from hermes_finance.services.source_report_preview import _payout_links
    from hermes_finance.statement_import.investment_report import parse_investment_report

    report = parse_investment_report(investment_text(amount="6,00"), {"1234567"})
    doc = {
        "filename_account": "1234567",
        "document_sha256": "b" * 64,
        "covered_from": "2030-01-01",
        "covered_to": "2030-01-31",
    }
    rows = [
        {
            "classification": "dividend",
            "security": MoneySecurity("1-01-12345-A", "Synthetic", "dividend"),
            "minor": n,
            "day": date(2030, 1, 20),
            "currency": "RUB",
            "ref": str(i),
        }
        for i, n in enumerate([100, 500])
    ]
    links, issues = _payout_links([doc], {doc["document_sha256"]: rows}, report)
    assert len(links) == 2 and not issues
    # A third row of the SAME registration cannot be silently omitted to fit the PDF.
    rows.append({**rows[0], "minor": 200, "ref": "third"})
    assert not _payout_links([doc], {doc["document_sha256"]: rows}, report)[0]
    rows.pop()
    ambiguous = replace(
        report, payouts=report.payouts + (replace(report.payouts[0], isin="RU000A000001"),)
    )
    assert not _payout_links([doc], {doc["document_sha256"]: rows}, ambiguous)[0]


def test_investment_joint_preview_cash_once_rates_and_no_writes(database, monkeypatch):
    from dataclasses import replace

    from hermes_finance.services import source_report_preview as service
    from hermes_finance.statement_import.investment_report import parse_investment_report

    # No payout in this cash-only case; the PDF actual section explicitly exists.
    report = replace(parse_investment_report(investment_text(), {"1234567"}), payouts=())
    monkeypatch.setattr(service, "extract_pdf_text_layer", lambda _: None)
    monkeypatch.setattr(service, "parse_investment_report", lambda *_: report)
    before = snapshot(database)
    first = run(
        database,
        [(FILENAME, investment_original())],
        income_report=b"synthetic pdf",
        history_from_zero=True,
    )
    result = first["source_return_preview"]
    assert not result["financial_apply_available"] and not result["close_available"]
    a = result["intervals"][0]
    assert a["pnl"]["value"] == "9000"
    assert a["instruments"][0]["pnl"]["value"] == "9000"
    assert a["instruments"][0]["components"]["buys"]["value"] == "100000"
    assert a["instruments"][0]["components"]["fees"]["value"] == "1000"
    assert a["modified_dietz"]["value"] is not None
    assert a["xirr_annualized"]["annualized"] is True
    assert a["xirr_period"]["value"] != a["xirr_annualized"]["value"]
    assert all(v == "0" for k, v in a["reconciliation"].items() if "delta_kopecks" in k)
    assert snapshot(database) == before
    second = run(
        database,
        [(FILENAME, investment_original())],
        income_report=b"synthetic pdf",
        history_from_zero=True,
    )
    assert first == second and snapshot(database) == before


def test_investment_zero_start_cannot_override_nonzero_original(database, monkeypatch):
    from hermes_finance.services import source_report_preview as service
    from hermes_finance.statement_import.investment_report import parse_investment_report

    monkeypatch.setattr(service, "extract_pdf_text_layer", lambda _: None)
    monkeypatch.setattr(
        service,
        "parse_investment_report",
        lambda *_: parse_investment_report(investment_text(), {"1234567"}),
    )
    raw = investment_original().replace(b'income_rest="0"', b'income_rest="1"', 1)
    with pytest.raises(MyBrokerError, match="zero_start_contradiction"):
        run(database, [(FILENAME, raw)], income_report=b"pdf", history_from_zero=True)


def test_investment_multipart_optional_pdf_bounds_and_duplicate(database, monkeypatch):
    from hermes_finance.services import source_report_preview as service
    from hermes_finance.statement_import.investment_report import parse_investment_report

    monkeypatch.setattr(service, "extract_pdf_text_layer", lambda _: None)
    monkeypatch.setattr(
        service,
        "parse_investment_report",
        lambda *_: parse_investment_report(investment_text(), {"1234567"}),
    )
    client = TestClient(create_app(database=database))
    files = [
        ("files", (FILENAME, investment_original())),
        ("income_report", ("synthetic.pdf", b"pdf")),
    ]
    ok = client.post("/api/mybroker-preflight/preview", files=files)
    assert ok.status_code == 200 and "source_return_preview" in ok.json()
    duplicate = client.post("/api/mybroker-preflight/preview", files=files + files[-1:])
    assert duplicate.status_code == 422
    oversized = client.post(
        "/api/mybroker-preflight/preview",
        files=files[:1] + [("income_report", ("too-big.pdf", b"x" * (8 * 1024 * 1024 + 1)))],
    )
    assert oversized.status_code == 413


def investment_case():
    from dataclasses import replace

    from hermes_finance.services import source_report_preview as service
    from hermes_finance.statement_import.investment_report import parse_investment_report

    raw = investment_original()
    doc = parse_mybroker(raw, FILENAME)
    report = replace(parse_investment_report(investment_text(), {"1234567"}), payouts=())
    return service, doc, raw, report, service._money(doc, raw)


def test_investment_repo_never_absorbs_ordinary_trade_on_same_day(monkeypatch):
    from decimal import Decimal

    service, doc, raw, report, money = investment_case()
    trades, names, primary, cancellations = service._native(doc, raw)
    ordinary = trades[0]
    for i, (quantity, amount) in enumerate([("5", "500"), ("-5", "501")]):
        t = deepcopy(ordinary)
        token = f"B{i + 1}"
        t.update(ids=[token], repo_observed=True, bank_commission="0")
        t["core"].update(quantity=quantity, trade_amount=amount)
        trades.append(t)
        primary[token] = [t]
        money.append(
            {**money[0], "minor": -50000 if i == 0 else 50100, "primary_id": token, "ref": token}
        )
    monkeypatch.setattr(service, "_native", lambda *_: (trades, names, primary, cancellations))
    doc["rub_money"][0]["ending_amount"] = "991"
    result = service._interval(doc, raw, report, money, {}, {}, True)
    instrument = result["instruments"][0]
    assert instrument["pnl"]["value"] == "9000"
    assert instrument["event_count"] == 2
    assert (
        sum(
            int(r["amount_kopecks"])
            for r in result["account_only"]
            if r["kind"] == "repo_financing"
        )
        == 100
    )
    assert not instrument["reason_codes"]
    assert Decimal(instrument["closing_quantity"]) == 10


def test_investment_anonymous_nkd_corroborates_cash_does_not_add_it_twice():
    service, doc, raw, report, money = investment_case()
    # Native T includes N; settlement principal plus a separate NKD Money equals T.
    money[0]["minor"] = -99877
    money.append(
        {
            **money[0],
            "minor": -123,
            "primary_id": None,
            "operation": "НКД по сделке",
            "narrative": "с Synthetic name never retained",
            "ref": "anonymous-nkd",
        }
    )
    # Original position/native full names are exact source authority, no substring match.
    result = service._interval(doc, raw, report, money, {}, {}, True)
    assert result["instruments"][0]["pnl"]["value"] == "9000"
    money[-1]["narrative"] += " similar"
    unknown = service._interval(doc, raw, report, money, {}, {}, True)
    assert unknown["instruments"][0]["pnl"]["value"] is None
    assert unknown["pnl"]["value"] is None


def test_investment_redemption_is_principal_with_exact_cancellation(monkeypatch):
    from dataclasses import replace
    from decimal import Decimal

    from hermes_finance.domain.money_security import MoneySecurity

    service, doc, raw, report, money = investment_case()
    trades, names, primary, _ = service._native(doc, raw)
    day = money[0]["day"]
    security = MoneySecurity("4B02-01-12345-A-001P", "АО Synthetic", "coupon")
    coupon = {
        **money[0],
        "classification": "coupon",
        "minor": 1000,
        "security": security,
        "redemption": None,
        "ref": "coupon",
    }
    redemption = {
        **coupon,
        "classification": "unknown",
        "minor": 100000,
        "redemption": security,
        "security": None,
        "ref": "redemption",
    }
    money.extend([coupon, redemption])
    monkeypatch.setattr(
        service,
        "_native",
        lambda *_: (trades, names, primary, [(ACCOUNT, "RU000A000000", day, Decimal(-10))]),
    )
    doc["positions"][0].update(actual_quantity="0", ending_value="0")
    doc["rub_money"][0]["ending_amount"] = "2000"
    report = replace(
        report,
        positions={("1234567", "RU000A000000"): ("0", 0)},
        closing={"1234567": 200000},
        reported_pnl={"1234567": 0},
    )
    r = service._interval(
        doc, raw, report, money, {"coupon": ("RU000A000000", security.reg_number)}, {}, True
    )
    s = r["instruments"][0]
    assert s["pnl"]["value"] == "0"
    assert s["components"]["redemption"]["value"] == "100000"
    assert s["components"]["coupons"]["value"] == "1000"
    assert not s["reason_codes"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ("quantity", "quantity_bridge_mismatch"),
        ("cash", "native_money_cash_bridge_mismatch"),
        ("missing_value", "economic_endpoint_unavailable"),
    ],
)
def test_investment_mismatch_withholds_full_result_preserves_unknown(change, reason):
    service, doc, raw, report, money = investment_case()
    if change == "quantity":
        doc["positions"][0]["actual_quantity"] = "11"
    elif change == "cash":
        money[0]["minor"] += 1
    else:
        doc["positions"][0]["ending_value"] = None
    r = service._interval(doc, raw, report, money, {}, {}, True)
    s = r["instruments"][0]
    assert s["pnl"]["value"] is None and s["modified_dietz"]["value"] is None
    assert reason in s["reason_codes"]


def test_investment_monthly_and_history_are_explicit_and_pdf_asof_must_match(database, monkeypatch):
    from dataclasses import replace

    service, _, raw, report, _ = investment_case()
    monkeypatch.setattr(service, "extract_pdf_text_layer", lambda _: None)
    monkeypatch.setattr(service, "parse_investment_report", lambda *_: report)
    r = run(database, [(FILENAME, raw)], income_report=b"pdf")["source_return_preview"][
        "intervals"
    ][0]
    assert r["period_kind"] == "monthly" and not r["history_from_zero"]
    monkeypatch.setattr(
        service, "parse_investment_report", lambda *_: replace(report, end=date(2030, 2, 28))
    )
    with pytest.raises(MyBrokerError, match="endpoint_scope_mismatch"):
        run(database, [(FILENAME, raw)], income_report=b"pdf")


def test_investment_saved_history_material_conflict_and_occurrence_not_source_sum(
    database, monkeypatch
):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    service, doc, raw, report, rows = investment_case()
    monkeypatch.setattr(service, "extract_pdf_text_layer", lambda _: None)
    monkeypatch.setattr(service, "parse_investment_report", lambda *_: report)
    classifications = [
        {
            "date": r["day"],
            "amount_kopecks": r["minor"],
            "currency": r["currency"],
            "operation": r["operation"],
            "narrative": r["narrative"],
            "updated_at": datetime(2030, 1, 31, tzinfo=UTC),
        }
        for r in rows
    ]
    saved = {
        "document": deepcopy(doc),
        "money_classifications": classifications,
        "head_seq": 1,
        "manifest_digest": "a" * 64,
    }
    monkeypatch.setattr(
        service,
        "_selected_sources",
        lambda *_: ([(SimpleNamespace(id=i), saved, None) for i in [1, 2]], None),
    )
    r = run(database, [(FILENAME, raw)], income_report=b"pdf")["source_return_preview"]
    c = r["comparison"][0]
    assert c["repeated_money_occurrences"] == 3 and c["unmatched_money_occurrences"] == 0
    assert c["repeated_native_trades"] == 1
    saved["document"]["trades"][0]["bank_commission"] = "11"
    changed = run(database, [(FILENAME, raw)], income_report=b"pdf")["source_return_preview"]
    assert changed["comparison"][0]["conflicting_native_trades"] == 1
    assert changed["context_fingerprint"] != r["context_fingerprint"]
    classifications[0]["updated_at"] = datetime(2030, 2, 1, tzinfo=UTC)
    refreshed = run(database, [(FILENAME, raw)], income_report=b"pdf")["source_return_preview"]
    assert refreshed["context_fingerprint"] != changed["context_fingerprint"]


def test_investment_filename_never_relabels_another_native_account():
    service, doc, raw, report, money = investment_case()
    doc["filename_account"] = "7654321"
    with pytest.raises(MyBrokerError, match="filename_native_account_conflict"):
        service._interval(doc, raw, report, money, {}, {}, True)
