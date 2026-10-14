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
from test_statement_import_mybroker_endpoints import broker_month_xml, node

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
    assert response.status_code == 422 and "filename_range_invalid" in response.text
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
