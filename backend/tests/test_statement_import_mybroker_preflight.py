"""Fabricated original batches only; no Owner sources or reconstructed EOD."""

from collections import Counter
from copy import deepcopy
from datetime import date
from decimal import Decimal
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
from hermes_finance.services import source_report_preview as service
from hermes_finance.services.mybroker_import import stage_mybroker
from hermes_finance.services.mybroker_preflight import _difference, preview_batch
from hermes_finance.statement_import.mybroker import MyBrokerError, canonical, parse_mybroker


@pytest.mark.parametrize("mutual", [True, False])
def test_repo_zero_net_quantity_requires_reciprocal_pair_evidence(mutual):
    def leg(own, partner, marker, quantity, day):
        return {
            "ids": [own],
            "repo_observed": True,
            "repo_partner": partner,
            "repo_leg": marker,
            "settlement_date": f"2030-01-{day:02d}",
            "depo_settlement_date": f"2030-01-{day:02d}",
            "core": {
                "source_account": "synthetic",
                "isin": "RU000A000000",
                "currency": "RUB",
                "quantity": quantity,
                "trade_time": f"2030-01-{day:02d}T09:00:00",
            },
        }

    legs = [
        leg("B10001", "B10002", "репо ч.1", "1", 10),
        leg(
            "B10002" if mutual else "B20001",
            "B10001" if mutual else "B20002",
            "репо ч.2" if mutual else "репо ч.1",
            "-1",
            20,
        ),
    ]
    assert sum(Decimal(t["core"]["quantity"]) for t in legs) == 0
    blockers = service._repo_pair_blockers(legs, date(2029, 12, 31), date(2030, 1, 31))
    assert bool(blockers) != mutual
    if not mutual:
        assert "repo_pair_unproven" in blockers
    else:
        assert "repo_position_open_at_boundary" in service._repo_pair_blockers(
            legs, date(2030, 1, 15), date(2030, 1, 31)
        )


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
    # With a built frontend the GET-only SPA fallback yields 405; neither case
    # exposes a preflight apply operation.
    assert client.post("/api/mybroker-preflight/apply").status_code in {404, 405}


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
    assert client.post("/api/mybroker-preflight/apply").status_code in {404, 405}


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
    assert ("1234567", "RU000A000000", "pdf_payout_row_invalid") in report.instrument_issues


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


@pytest.mark.parametrize(
    "principal, fee, cash_day, expected",
    [
        (-100000, -1100, None, 10000),
        (-200000, -1100, None, None),
        (-100000, -1100, date(2030, 1, 6), None),
        (-100000, -1000, None, 10000),
    ],
)
def test_clean_investment_report_fee_conflict_requires_proven_principal_and_date(
    principal, fee, cash_day, expected
):
    from hermes_finance.services.clean_instrument_return import project_clean_analysis

    service, doc, raw, report, money = investment_case()
    doc["trades"][0]["accrued_interest"] = "0"
    money[0]["minor"] = principal
    money[1]["minor"] = fee
    if cash_day:
        money[0]["date"] = cash_day.isoformat()
        money[0]["day"] = cash_day
    analyses = {}
    service._interval(doc, raw, report, money, {}, {}, True, analyses=analyses)
    analysis = analyses["RU000A000000"]
    result = project_clean_analysis(analysis, "RU000A000000", instrument_type="stock")
    assert result.pnl.value == expected
    assert result.buys.value == (100000 if expected is not None else None)
    if fee == -1100:
        assert "native_money_cash_bridge_mismatch" in analysis.reason_codes
        from dataclasses import asdict

        from pydantic import TypeAdapter

        from hermes_finance.domain.instrument_return import InstrumentAnalysis

        assert "clean_fee_only_bridge_proven" not in asdict(analysis)
        assert (
            "clean_fee_only_bridge_proven"
            not in TypeAdapter(InstrumentAnalysis).json_schema()["properties"]
        )


@pytest.mark.parametrize(
    "classification,expected", [("fee", 10000), ("tax", 10000), ("unknown", None)]
)
def test_clean_investment_report_unlinked_cost_is_not_an_unlinked_principal(
    classification, expected
):
    from hermes_finance.services.clean_instrument_return import project_clean_analysis

    service, doc, raw, report, money = investment_case()
    doc["trades"][0]["accrued_interest"] = "0"
    money.append(
        {
            **money[1],
            "minor": 100,
            "classification": classification,
            "kind": classification,
            "operation": "Synthetic cost",
            "ref": "synthetic-cost",
            "primary_id": None,
        }
    )
    if classification == "unknown":
        money.append({**money[-1], "classification": "fee", "kind": "fee", "ref": "synthetic-fee"})
    analyses = {}
    service._interval(doc, raw, report, money, {}, {}, True, analyses=analyses)
    analysis = analyses["RU000A000000"]
    result = project_clean_analysis(analysis, "RU000A000000", instrument_type="stock")
    assert "unresolved_account_cash_attribution" in analysis.reason_codes
    assert result.pnl.value == expected


def test_clean_investment_report_unaccepted_structure_shows_only_partial_known_result():
    from dataclasses import replace

    from hermes_finance.domain.instrument_return import CashLeg, InstrumentEvent
    from hermes_finance.services.clean_instrument_return import project_clean_analysis

    service, doc, raw, report, money = investment_case()
    doc["trades"][0]["accrued_interest"] = "0"
    doc["syntax_blockers"] = ["synthetic_unknown_structure"]
    analyses = {}
    service._interval(doc, raw, report, money, {}, {}, True, analyses=analyses)
    result = project_clean_analysis(
        analyses["RU000A000000"], "RU000A000000", instrument_type="stock"
    )
    assert result.known_result.value is None
    assert result.valuation_and_trades.value is None
    assert result.buys.value == 100000
    assert "source_sections_not_financially_accepted" in result.known_result.reason_codes
    assert result.pnl.value is None and result.modified_dietz.value is None
    observed = InstrumentEvent(
        event_key="synthetic-coupon",
        provider="synthetic",
        native_source_account="1234567-000",
        isin="RU000A000000",
        kind="COUPON",
        source_references=("synthetic-coupon",),
        event_date=date(2030, 1, 20),
        cash_legs=(
            CashLeg(
                "coupon",
                date(2030, 1, 20),
                12000,
                -12000,
                ("synthetic-coupon",),
                "synthetic-coupon",
            ),
        ),
    )
    analysis = analyses["RU000A000000"]
    paid = project_clean_analysis(
        replace(analysis, events=(*analysis.events, observed)),
        "RU000A000000",
        instrument_type="stock",
    )
    assert paid.known_result.value == 12000 and paid.known_result.status == "partial"
    assert paid.valuation_and_trades.value is None and paid.pnl.value is None


@pytest.mark.parametrize("second_principal, expected", [(-100000, 20000), (-200000, None)])
def test_clean_investment_report_two_same_day_trades_require_each_principal(
    second_principal, expected
):
    from dataclasses import replace

    from hermes_finance.services.clean_instrument_return import project_clean_analysis

    service, doc, raw, report, money = investment_case()
    _, names, _, cancellations = service._native(doc, raw)
    first = doc["trades"][0]
    first["accrued_interest"] = "0"
    second = deepcopy(first)
    second["ids"] = ["10000000002", "20000000002"]
    second["identity"] = service.digest(
        [service.PROVIDER, second["core"]["source_account"], second["ids"]]
    )
    doc["trades"].append(second)
    doc["positions"][0].update(actual_quantity="20", ending_value="2200")
    report = replace(report, positions={("1234567", "RU000A000000"): ("20", 220000)})
    money[1]["minor"] = -1100
    for index, amount in ((0, second_principal), (1, -1000)):
        row = deepcopy(money[index])
        row.update(minor=amount, ref=f"second-{index}", primary_id="10000000002")
        row["operation"] = row["operation"].replace("10000000001", "10000000002")
        money.append(row)
    analyses = {}
    native_evidence = {
        "names": names,
        "cancellations": [(a, i, d.isoformat(), str(q)) for a, i, d, q in cancellations],
        "unresolved": [],
    }
    service._interval(
        doc, raw, report, money, {}, {}, True, analyses=analyses, native_evidence=native_evidence
    )
    result = project_clean_analysis(
        analyses["RU000A000000"], "RU000A000000", instrument_type="stock"
    )
    assert result.pnl.value == expected


@pytest.mark.parametrize(
    "quantity,value,available",
    [
        ("0", None, True),
        (None, None, False),
        ("1", None, False),
        ("0", "1", False),
    ],
)
def test_mature_account_zero_position_is_not_missing_quantity(quantity, value, available):
    service, doc, raw, report, money = investment_case()
    doc["rub_money"][0]["beginning_amount"] = "1000"
    position = doc["positions"][0]
    position["beginning_actual_quantity"] = quantity
    position["beginning_value"] = value
    result = service._interval(doc, raw, report, money, {}, {}, False)
    instrument = result["instruments"][0]
    assert (instrument["pnl"]["value"] is not None) == available
    if available:
        assert instrument["opening_kopecks"] == "0"
        assert instrument["pnl"]["value"] == "9000"
    if quantity == "0" and value == "1":
        assert "zero_quantity_value_conflict" in instrument["reason_codes"]


def test_zero_closing_quantity_requires_no_contradictory_value():
    from dataclasses import replace

    service, doc, raw, report, money = investment_case()
    # A held position sold entirely during an interval on a mature account.
    position = doc["positions"][0]
    position.update(
        beginning_actual_quantity="10",
        actual_quantity="0",
        beginning_value="1000",
        ending_value=None,
    )
    trade = doc["trades"][0]
    trade["core"]["quantity"] = "-10"
    money[0]["minor"] = 100000
    report = replace(report, positions={("1234567", "RU000A000000"): ("0", 0)})
    analyses = {}
    result = service._interval(doc, raw, report, money, {}, {}, False, analyses=analyses)
    instrument = result["instruments"][0]
    assert instrument["closing_kopecks"] == "0"
    assert instrument["pnl"]["value"] == "-1000"
    sale = next(e for e in analyses["RU000A000000"].events if e.kind == "SELL")
    assert sale.effective_isin == sale.isin and sale.persisted_link_status is None
    assert sale.classification_origin == "native_money_group_bridge"
    position["ending_value"] = "1"
    conflict = service._interval(doc, raw, report, money, {}, {}, False)["instruments"][0]
    assert conflict["pnl"]["value"] is None
    assert "zero_quantity_value_conflict" in conflict["reason_codes"]
    position.update(actual_quantity=None, ending_value=None)
    unknown = service._interval(doc, raw, report, money, {}, {}, False)["instruments"][0]
    assert unknown["closing_kopecks"] is None and unknown["pnl"]["value"] is None


def test_pdf_position_failure_remains_local_after_proof_serialization():
    from dataclasses import replace

    from hermes_finance.services.source_investment_proofs import _report, _restore_report
    from hermes_finance.statement_import.investment_report import parse_investment_report

    text = investment_text()
    page = text.pages[0]
    lines = list(page.lines)
    position_index = next(i for i, line in enumerate(lines) if "1234567-000" in line)
    lines[position_index] = lines[position_index].replace("1 100,00", "invalid")
    bad = parse_investment_report(
        replace(text, pages=(replace(page, lines=tuple(lines)),)), {"1234567"}
    )
    assert bad.instrument_issues == (("1234567", "RU000A000000", "pdf_position_invalid"),)
    restored = _restore_report(_report(bad, "1234567"))
    assert restored.instrument_issues == bad.instrument_issues
    service, doc, raw, report, money = investment_case()
    foreign = replace(
        report, instrument_issues=(("1234567", "RU000A000001", "pdf_position_invalid"),)
    )
    assert (
        service._interval(doc, raw, foreign, money, {}, {}, True)["instruments"][0]["pnl"]["value"]
        == "9000"
    )
    global_error = replace(report, issues=(("1234567", "pdf_position_invalid"),))
    assert (
        service._interval(doc, raw, global_error, money, {}, {}, True)["instruments"][0]["pnl"][
            "value"
        ]
        is None
    )


def test_known_payout_keeps_own_coverage_and_effective_identity_without_valuation():
    from hermes_finance.domain.money_security import MoneySecurity

    service, doc, raw, report, money = investment_case()
    coupon = {
        **money[0],
        "ref": "synthetic-coupon",
        "minor": 1000,
        "classification": "coupon",
        "security": MoneySecurity("1-01-12345-A", "Synthetic", "coupon"),
    }
    money.append(coupon)
    doc["positions"][0]["ending_value"] = None
    analyses = {}
    result = service._interval(
        doc,
        raw,
        report,
        money,
        {coupon["ref"]: ("RU000A000000", "1-01-12345-A")},
        {},
        True,
        analyses=analyses,
    )
    a = analyses["RU000A000000"]
    assert a.pnl.value is None and not a.coverage["valuation"].complete
    assert a.coverage["payouts"].complete and a.components["coupons"].value == 1000
    assert a.components["coupons"].status in {"supported", "provisional"}
    assert "economic_endpoint_unavailable" not in a.components["coupons"].reason_codes
    assert all(e.effective_isin == e.isin and e.persisted_link_status is None for e in a.events)
    payout = next(e for e in a.events if e.kind == "COUPON")
    assert payout.net_payout_kopecks == 1000 and payout.classification_status == "confirmed"
    assert result["instruments"][0]["xirr_period"]["value"] is None
    # Unknown-scope faults must still leave the observed payout partial.
    report = replace_report_issue(report)
    service._interval(
        doc,
        raw,
        report,
        money,
        {coupon["ref"]: ("RU000A000000", "1-01-12345-A")},
        {},
        True,
        analyses=analyses,
    )
    assert not analyses["RU000A000000"].coverage["payouts"].complete
    assert analyses["RU000A000000"].components["coupons"].status == "partial"


def replace_report_issue(report):
    from dataclasses import replace

    return replace(report, issues=(("1234567", "unknown_source_fault"),))


@pytest.mark.parametrize("section", ["position", "payout"])
def test_pdf_unidentified_or_multi_identity_financial_row_stays_account_wide(section):
    from dataclasses import replace

    from hermes_finance.statement_import.investment_report import parse_investment_report

    for identity in ("Unknown security", "RU000A000000 RU000A000001"):
        text = investment_text()
        lines = list(text.pages[0].lines)
        index = next(
            i
            for i, line in enumerate(lines)
            if ("1234567-000" in line if section == "position" else "RUB 20.01.2030" in line)
        )
        lines[index] = lines[index].replace("RU000A000000", identity)
        report = parse_investment_report(
            replace(text, pages=(replace(text.pages[0], lines=tuple(lines)),)), {"1234567"}
        )
        code = "pdf_position_invalid" if section == "position" else "pdf_payout_row_invalid"
        assert ("1234567", code) in report.issues
        assert not report.instrument_issues


@pytest.mark.parametrize("amount,valid", [("1 000,00", True), ("invalid", False)])
def test_pdf_typed_ruble_cash_position_is_not_an_unidentified_security(amount, valid):
    from dataclasses import replace

    from hermes_finance.statement_import.investment_report import parse_investment_report

    text = investment_text()
    lines = list(text.pages[0].lines)
    index = next(i for i, line in enumerate(lines) if "1234567-000" in line)
    lines.insert(index, f"Российский рубль  1234567-000  RUB  {amount}  1 000,00  0,00  0,0%")
    report = parse_investment_report(
        replace(text, pages=(replace(text.pages[0], lines=tuple(lines)),)), {"1234567"}
    )
    assert (("1234567", "pdf_position_invalid") not in report.issues) == valid
    assert not report.instrument_issues


def saved_investment_preview(database, monkeypatch):
    from hermes_finance.services import source_intake

    service, _, raw, report, _ = investment_case()
    monkeypatch.setattr(service, "extract_pdf_text_layer", lambda _: None)
    monkeypatch.setattr(service, "parse_investment_report", lambda *_: report)
    with database.session_factory() as session:
        source_intake.save_intake(
            session, document=raw, filename=FILENAME, request_id="investment-xml"
        )
    result = run(database, [(FILENAME, raw)], income_report=b"pdf", history_from_zero=True)[
        "source_return_preview"
    ]
    return result


def save_semantics_proof(database, monkeypatch, revision, request_id):
    """Issue synthetic evidence under a chosen semantics revision."""
    from hermes_finance.services import source_investment_proofs as proofs

    with monkeypatch.context() as patch:
        patch.setattr(proofs, "SEMANTICS_REVISION", revision)
        preview = saved_investment_preview(database, patch)
        intent = {k: preview["persistence"][k] for k in ("form_token", "preview_digest")}
        with database.session_factory() as session:
            ack = proofs.confirm(session, **intent, request_id=request_id, replace_existing=True)
            assert ack["current"]
            reports = proofs.read_reports(session)
    return reports


@pytest.mark.parametrize(
    "kind, expected",
    [
        ("normal", "ee4cd0b5f1c1cdb7c689edd4aed1443df652309f0bd338f2396a9e616db0a4ee"),
        ("fee_mismatch", "27dd011a3d49472eebb979c4efcb3ba810e3e50f58afc2d14b84119667602230"),
        ("positive_fee", "1d48667ffe25572cd266e3bcac2f5351602a181f0ae5f7b08711947d784cfbce"),
        ("positive_tax", "c78eaa82175022145253689ac064e9e35cc30056e777f5d6e4e7364300c7b77d"),
    ],
)
def test_v10_retains_v9_legacy_interval_fixture(kind, expected):
    import hashlib
    import json

    service, doc, raw, report, money = investment_case()
    doc["trades"][0]["accrued_interest"] = "0"
    if kind == "fee_mismatch":
        money[1]["minor"] = -1100
    elif kind == "positive_fee":
        money[1]["minor"] = 100
    elif kind == "positive_tax":
        money.append(
            {
                **money[1],
                "minor": 100,
                "classification": "tax",
                "kind": "tax",
                "operation": "Налог",
                "ref": "synthetic-tax",
                "primary_id": None,
            }
        )
    result = service._interval(doc, raw, report, money, {}, {}, True)
    encoded = json.dumps(
        result, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")
    ).encode()
    assert hashlib.sha256(encoded).hexdigest() == expected


def test_v10_reads_unchanged_v9_receipt_without_writes(database, monkeypatch):
    from hermes_finance.services import source_investment_proofs as proofs

    original = save_semantics_proof(
        database, monkeypatch, "source_investment_semantics_v9", "v9-receipt"
    )
    before = snapshot(database)
    before_bytes = database.database_path.read_bytes()
    with database.session_factory() as session:
        current = proofs.read_reports(session)
        assert current == original
        assert proofs.request_status(session, "v9-receipt")["current"]
    assert snapshot(database) == before
    assert database.database_path.read_bytes() == before_bytes


def test_investment_semantics_ignores_unrelated_module_changes_without_writes(
    database, monkeypatch
):
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.returns_view import read_overview
    from hermes_finance.services.source_instrument_returns import read_instrument_returns

    original = save_semantics_proof(
        database, monkeypatch, proofs.SEMANTICS_REVISION, "metadata-original"
    )
    from hermes_finance import __version__ as version

    monkeypatch.setattr("hermes_finance.__version__", version + ".synthetic")
    # Any package traversal/read would reproduce the release-coupled regression.
    from pathlib import Path

    monkeypatch.setattr(Path, "rglob", lambda *_: pytest.fail("proof reads traversed package code"))
    before = snapshot(database)
    before_bytes = database.database_path.read_bytes()
    statements = []

    def observe(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(database.engine, "before_cursor_execute", observe)
    try:
        proofs.FORMS.entries.clear()
        with database.session_factory() as session:
            assert proofs.read_reports(session) == original
            assert proofs.request_status(session, "metadata-original")["current"]
            result = read_instrument_returns(session, source_account=ACCOUNT)
            assert result.instruments[0].analysis.pnl.value == 9000
            assert result.instruments[0].analysis.modified_dietz.value is not None
            view = read_overview(
                session, scope=f"source:{ACCOUNT}", start=date(2029, 12, 31), end=date(2030, 1, 31)
            )
            assert view["selected"]["pnl"]["value"] == "9000"
            assert view["instruments"][0]["pnl"]["value"] == "9000"
    finally:
        event.remove(database.engine, "before_cursor_execute", observe)
    assert not {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"} & set(
        statements
    )
    assert snapshot(database) == before
    assert database.database_path.read_bytes() == before_bytes


@pytest.mark.parametrize(
    "predecessor",
    ["52873e49d0a0655af1a96e6be1631c522bbca00e76ee9bd8ef09bfb5fe9ddb9e", "f" * 64],
)
def test_investment_semantics_rejects_legacy_digest(database, monkeypatch, predecessor):
    from hermes_finance.services import source_investment_proofs as proofs

    save_semantics_proof(database, monkeypatch, predecessor, "unknown-code")
    before = snapshot(database)
    with database.session_factory() as session:
        report = proofs.read_reports(session)[0]
        assert report["status"] == "stale" and report["interval"] is None
        assert report["reason_codes"] == ["investment_proof_dependencies_changed"]
    assert snapshot(database) == before


@pytest.mark.parametrize(
    "old_code",
    [
        "source_investment_semantics_v8",
        "source_investment_semantics_v7",
        "source_investment_semantics_v6",
        "source_investment_semantics_v2",
        "0ed93cadf12fe53bbc1a51bf7d29b7ba583b25962539412efa1802db254d7a81",
    ],
)
def test_gift_v3_compatibility_preserves_exact_old_proof_without_gift(
    database, monkeypatch, old_code
):
    from hermes_finance.services import source_investment_proofs as proofs

    original = save_semantics_proof(database, monkeypatch, old_code, "old-no-gift")
    before = snapshot(database)
    with database.session_factory() as session:
        assert proofs.read_reports(session) == original
    assert snapshot(database) == before
    # All old dependency operands remain authoritative; change a captured row.
    from hermes_finance.persistence import SourceMoneyClassification

    with database.session_factory() as session:
        captured = session.scalar(select(SourceMoneyClassification))
        captured.classification = "unknown"
        session.commit()
    with database.session_factory() as session:
        report = proofs.read_reports(session)[0]
        assert report["status"] == "stale"
        assert report["reason_codes"] == ["investment_proof_dependencies_changed"]


@pytest.mark.parametrize(
    "revision,expected",
    [
        ("source_investment_semantics_v9", "current"),
        ("source_investment_semantics_v8", "current"),
        ("source_investment_semantics_v7", "stale"),
    ],
)
def test_v9_compatibility_preserves_v8_even_when_older_cost_scope_is_incompatible(
    database, monkeypatch, revision, expected
):
    from hermes_finance.services import source_investment_proofs as proofs

    save_semantics_proof(database, monkeypatch, revision, "old-cost-scope")
    before = snapshot(database)
    monkeypatch.setattr(proofs, "_old_cost_meaning_unchanged", lambda _: False)
    with database.session_factory() as session:
        report = proofs.read_reports(session)[0]
        assert report["status"] == expected
    assert snapshot(database) == before


def test_new_intersecting_original_stales_proof_without_rewriting_decision(database, monkeypatch):
    from hermes_finance.persistence import SourceReturnProof
    from hermes_finance.services import source_intake
    from hermes_finance.services import source_investment_proofs as proofs

    save_semantics_proof(database, monkeypatch, "source_investment_semantics_v7", "old-v7")
    with database.session_factory() as session:
        row = session.scalar(select(SourceReturnProof))
        original = (row.id, row.evidence_json, row.dependency_digest)
        root = ET.fromstring(investment_original())
        root.set("synthetic_marker", "new-intersecting-original")
        source_intake.save_intake(
            session, document=ET.tostring(root), filename=FILENAME, request_id="extra-original"
        )
    before = snapshot(database)
    with database.session_factory() as session:
        assert proofs.read_reports(session)[0]["status"] == "stale"
        row = session.scalar(select(SourceReturnProof))
        assert (row.id, row.evidence_json, row.dependency_digest) == original
    assert snapshot(database) == before


def test_investment_semantics_revision_change_stales_saved_proof(database, monkeypatch):
    from hermes_finance.services import source_investment_proofs as proofs

    original = save_semantics_proof(database, monkeypatch, proofs.SEMANTICS_REVISION, "new-code")
    before = snapshot(database)
    with database.session_factory() as session:
        assert proofs.read_reports(session) == original
    with monkeypatch.context() as patch:
        patch.setattr(proofs, "SEMANTICS_REVISION", "source_investment_semantics_changed")
        with database.session_factory() as session:
            report = proofs.read_reports(session)[0]
            assert report["status"] == "stale" and report["interval"] is None
            assert report["reason_codes"] == ["investment_proof_dependencies_changed"]
            assert not proofs.request_status(session, "new-code")["current"]
    assert snapshot(database) == before


@pytest.mark.parametrize(
    "old_revision", ["source_investment_semantics_previous", "source_investment_semantics_v9"]
)
def test_investment_semantics_does_not_admit_pending_old_writer_form(
    database, monkeypatch, old_revision
):
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.source_return_proofs import ProofError

    with monkeypatch.context() as patch:
        patch.setattr(proofs, "SEMANTICS_REVISION", old_revision)
        preview = saved_investment_preview(database, patch)["persistence"]
    before = snapshot(database)
    with database.session_factory() as session:
        with pytest.raises(ProofError, match="investment_proof_dependencies_changed"):
            proofs.confirm(
                session,
                **{k: preview[k] for k in ("form_token", "preview_digest")},
                request_id="old-pending-form",
            )
    assert snapshot(database) == before


def test_investment_semantics_latest_stale_proof_has_no_older_compatible_fallback(
    database, monkeypatch
):
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.returns_view import read_overview

    original = save_semantics_proof(
        database, monkeypatch, proofs.SEMANTICS_REVISION, "old-compatible"
    )
    latest = save_semantics_proof(database, monkeypatch, "f" * 64, "latest-unknown")
    assert latest[0]["proof_id"] != original[0]["proof_id"]
    before = snapshot(database)
    with database.session_factory() as session:
        reports = proofs.read_reports(session)
        assert len(reports) == 1 and reports[0]["proof_id"] == latest[0]["proof_id"]
        assert reports[0]["status"] == "stale" and reports[0]["interval"] is None
        view = read_overview(
            session, scope=f"source:{ACCOUNT}", start=date(2029, 12, 31), end=date(2030, 1, 31)
        )
        assert view["selected"]["pnl"]["value"] is None
    assert snapshot(database) == before


@pytest.mark.parametrize("operation", ["copy", "replace"])
@pytest.mark.parametrize("legacy", [False, True, "v9"])
def test_investment_semantics_preserves_physical_database_binding(
    database, monkeypatch, tmp_path, operation, legacy
):
    from shutil import copyfile

    from hermes_finance.database import create_database
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.source_proof_file import file_incarnation

    save_semantics_proof(
        database,
        monkeypatch,
        "source_investment_semantics_v9"
        if legacy == "v9"
        else proofs._GIFT_COMPAT_CODES[1]
        if legacy
        else proofs.SEMANTICS_REVISION,
        "physical-original",
    )
    with database.session_factory() as session:
        assert proofs.request_status(session, "physical-original")["current"]
    before = snapshot(database)
    identity = file_incarnation(database.database_path)
    database.engine.dispose()
    destination = tmp_path / "synthetic-replacement.db"
    copyfile(database.database_path, destination)
    if operation == "replace":
        destination.replace(database.database_path)
        destination = database.database_path
    assert file_incarnation(destination) != identity
    replacement = create_database(destination)
    try:
        with replacement.session_factory() as session:
            report = proofs.read_reports(session)[0]
            assert report["status"] == "stale" and report["interval"] is None
        assert snapshot(replacement) == before
    finally:
        replacement.engine.dispose()


def test_investment_persistent_save_repeat_reload_and_ordinary_readers(database, monkeypatch):
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.returns_view import read_overview
    from hermes_finance.services.source_instrument_returns import read_instrument_returns

    preview = saved_investment_preview(database, monkeypatch)
    persistence = preview["persistence"]
    assert persistence["available"], persistence
    before = snapshot(database)
    intent = {k: persistence[k] for k in ("form_token", "preview_digest")}
    with database.session_factory() as session:
        ack = proofs.confirm(session, **intent, request_id="investment-proof")
    assert ack["current"] and not ack["replay"]
    after = snapshot(database)
    assert {name for name in before if before[name] != after[name]} == {"source_return_proofs"}
    with database.session_factory() as session:
        assert proofs.confirm(session, **intent, request_id="investment-proof")["replay"]
    # A fresh session/process-bound form registry is not needed for reads.
    proofs.FORMS.entries.clear()
    with database.session_factory() as session:
        reports = proofs.read_reports(session, source_account="1234567")
        assert reports[0]["status"] == "current", reports
        assert reports[0]["interval"] == preview["intervals"][0]
        assert proofs.request_status(session, "investment-proof")["current"]
        result = read_instrument_returns(session, source_account=ACCOUNT)
        assert result.instruments[0].analysis.pnl.value == 9000
        assert result.instruments[0].analysis.modified_dietz.value is not None
        view = read_overview(
            session, scope=f"source:{ACCOUNT}", start=date(2029, 12, 31), end=date(2030, 1, 31)
        )
        assert view["selected"]["pnl"]["value"] == "9000"
        assert view["selected"]["coupons"]["value"] == "0"
        assert view["selected"]["dividends"]["value"] == "0"
        assert view["instruments"][0]["pnl"]["value"] == "9000"
    assert snapshot(database) == after
    repeated = run(
        database, [(FILENAME, investment_original())], income_report=b"pdf", history_from_zero=True
    )["source_return_preview"]
    assert repeated["persistence"]["reason_codes"] == ["investment_proof_already_saved"]


@pytest.mark.parametrize("mutation", ["classification", "aba", "overlap"])
@pytest.mark.parametrize("legacy", [False, True])
def test_investment_persistent_currentness_no_fallback(database, monkeypatch, mutation, legacy):
    from hermes_finance.persistence import SourceMoneyClassification
    from hermes_finance.services import source_intake
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.source_instrument_returns import read_instrument_returns

    save_semantics_proof(
        database,
        monkeypatch,
        proofs._GIFT_COMPAT_CODES[1] if legacy else proofs.SEMANTICS_REVISION,
        "proof-currentness",
    )
    if mutation == "overlap":
        root = ET.fromstring(investment_original())
        root.set("synthetic", "overlap")
        raw = ET.tostring(root, encoding="utf-8")
        with database.session_factory() as session:
            source_intake.save_intake(
                session, document=raw, filename=FILENAME, request_id="overlap"
            )
    else:
        with database.session_factory() as session:
            row = session.scalar(
                select(SourceMoneyClassification).order_by(SourceMoneyClassification.id)
            )
            old = row.classification
            row.classification = "unknown" if old != "unknown" else "fee"
            session.commit()
            if mutation == "aba":
                row.classification = old
                session.commit()
    with database.session_factory() as session:
        report = proofs.read_reports(session)[0]
        assert report["status"] == "stale" and report["interval"] is None
        from hermes_finance.services.returns_view import read_overview

        overview = read_overview(
            session, scope=f"source:{ACCOUNT}", start=date(2029, 12, 31), end=date(2030, 1, 31)
        )
        assert overview["selected"]["coupons"]["value"] is None
        assert overview["selected"]["dividends"]["value"] is None
        result = read_instrument_returns(session, source_account=ACCOUNT)
        assert all(
            r.analysis.pnl.value is None and r.analysis.modified_dietz.value is None
            for r in result.instruments
        )


def test_investment_persistent_duplicate_save_and_future_month_do_not_retire_history(
    database, monkeypatch
):
    from hermes_finance.services import source_intake
    from hermes_finance.services import source_investment_proofs as proofs

    preview = saved_investment_preview(database, monkeypatch)["persistence"]
    with database.session_factory() as session:
        proofs.confirm(
            session,
            **{k: preview[k] for k in ("form_token", "preview_digest")},
            request_id="proof-stable",
        )
        source_intake.save_intake(
            session, document=investment_original(), filename=FILENAME, request_id="xml-repeat"
        )
        assert proofs.read_reports(session)[0]["status"] == "current"
    raw = investment_original().replace(b"2030-01-", b"2030-02-").replace(b".01.2030", b".02.2030")
    with database.session_factory() as session:
        source_intake.save_intake(
            session,
            document=raw,
            filename="Брокерский 1234567 (01.02.30-28.02.30).xml",
            request_id="future-month",
        )
        assert proofs.read_reports(session)[0]["status"] == "current"


def test_investment_persistent_replacement_requires_explicit_preview_confirmation(
    database, monkeypatch
):
    from dataclasses import replace

    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.source_return_proofs import ProofError

    first = saved_investment_preview(database, monkeypatch)["persistence"]
    with database.session_factory() as session:
        proofs.confirm(
            session,
            **{k: first[k] for k in ("form_token", "preview_digest")},
            request_id="proof-original",
        )
    service, _, _, report, _ = investment_case()
    monkeypatch.setattr(
        service, "parse_investment_report", lambda *_: replace(report, sha256="e" * 64)
    )
    second = run(
        database,
        [(FILENAME, investment_original())],
        income_report=b"changed pdf",
        history_from_zero=True,
    )["source_return_preview"]["persistence"]
    assert len(second["replacements"]) == 1
    before = snapshot(database)
    with database.session_factory() as session:
        with pytest.raises(ProofError, match="replacement_not_confirmed"):
            proofs.confirm(
                session,
                **{k: second[k] for k in ("form_token", "preview_digest")},
                request_id="replacement-denied",
            )
    assert snapshot(database) == before
    third = run(
        database,
        [(FILENAME, investment_original())],
        income_report=b"changed pdf",
        history_from_zero=True,
    )["source_return_preview"]["persistence"]
    with database.session_factory() as session:
        ack = proofs.confirm(
            session,
            **{k: third[k] for k in ("form_token", "preview_digest")},
            request_id="replacement",
            replace_existing=True,
        )
        assert ack["current"]
        assert len(proofs.read_reports(session)) == 1
    assert (
        len(snapshot(database)["source_return_proofs"]) == len(before["source_return_proofs"]) + 1
    )


def test_investment_same_native_id_in_pending_section_is_not_material_execution_conflict():
    from hermes_finance.services.source_report_preview import _trade_comparison_key

    _, doc, _, _, _ = investment_case()
    completed = doc["trades"][0]
    pending = {**completed, "section": "pending", "state": "pending"}
    assert _trade_comparison_key(completed) != _trade_comparison_key(pending)


def test_investment_request_underscore_is_a_literal_prefix(database, monkeypatch):
    from hermes_finance.persistence import SourceReturnProof
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.source_return_proofs import ProofError

    preview = saved_investment_preview(database, monkeypatch)["persistence"]
    with database.session_factory() as session:
        proofs.confirm(
            session,
            **{k: preview[k] for k in ("form_token", "preview_digest")},
            request_id="probeXone",
        )
        with pytest.raises(ProofError, match="request_not_found"):
            proofs.request_status(session, "probe_one")
        # Same issued plan, deliberately different literal request ID. It must
        # reach form validation, not conflict with the unrelated existing ID.
        with pytest.raises(ProofError, match="form_expired"):
            proofs.confirm(
                session,
                **{k: preview[k] for k in ("form_token", "preview_digest")},
                request_id="probe_one",
            )
        assert len(list(session.scalars(select(SourceReturnProof)))) == 1


def test_investment_persistent_api_requires_exact_ack_and_boolean_attestation(
    database, monkeypatch
):
    saved_investment_preview(database, monkeypatch)
    client = TestClient(create_app(database=database))
    result = client.post(
        "/api/mybroker-preflight/preview",
        files=[
            ("files", (FILENAME, investment_original())),
            ("income_report", ("synthetic.pdf", b"pdf")),
        ],
        data={"intent": '{"history_from_zero":true}'},
    )
    assert result.status_code == 200
    first = result.json()["source_return_preview"]["persistence"]
    payload = {
        **{k: first[k] for k in ("form_token", "preview_digest")},
        "request_id": "api-proof",
        "attested": "true",
    }
    assert (
        client.post("/api/source-returns/investment-reports/confirm", json=payload).status_code
        == 422
    )
    payload["attested"] = True
    saved = client.post("/api/source-returns/investment-reports/confirm", json=payload)
    assert saved.status_code == 200 and saved.json()["current"], saved.text
    read = client.get("/api/source-returns/investment-reports/requests/api-proof")
    assert read.status_code == 200 and read.json()["preview_digest"] == first["preview_digest"]
    assert (
        client.get("/api/source-returns/investment-reports?source_account=" + ACCOUNT).json()[
            "reports"
        ][0]["status"]
        == "current"
    )
    ordinary = client.get("/api/source-returns/monthly?source_account=" + ACCOUNT).json()
    assert ordinary["months"][0]["growth_kopecks"] == 9000
    assert ordinary["period"]["growth_kopecks"] == 9000


@pytest.mark.parametrize("pending", [False, True, "other"])
def test_investment_repo_never_absorbs_ordinary_trade_on_same_day(monkeypatch, pending):
    from decimal import Decimal

    from hermes_finance.services.clean_instrument_return import project_clean_analysis

    service, doc, raw, report, money = investment_case()
    trades, names, primary, cancellations = service._native(doc, raw)
    ordinary = trades[0]
    for i, (quantity, amount) in enumerate([("5", "500"), ("-5", "501")]):
        t = deepcopy(ordinary)
        token = f"B{i + 1}"
        t.update(
            ids=[token],
            repo_observed=True,
            bank_commission="0",
            repo_partner="B2" if i == 0 else "B1",
            repo_leg=f"репо ч.{i + 1}",
        )
        t["core"].update(quantity=quantity, trade_amount=amount)
        trades.append(t)
        primary[token] = [t]
        money.append(
            {**money[0], "minor": -50000 if i == 0 else 50100, "primary_id": token, "ref": token}
        )
    monkeypatch.setattr(
        service, "_native", lambda *_, **__: (trades, names, primary, cancellations)
    )
    doc["rub_money"][0]["ending_amount"] = "991"
    if pending:
        pending_trade = {
            **deepcopy(ordinary),
            "section": "pending",
            "state": "pending",
            "repo_observed": True,
        }
        if pending == "other":
            pending_trade["core"]["isin"] = "RU000A000001"
        doc["trades"].append(pending_trade)
    analyses = {}
    result = service._interval(doc, raw, report, money, {}, {}, True, analyses=analyses)
    instrument = result["instruments"][0]
    assert instrument["pnl"]["value"] == (None if pending is True else "9000")
    if pending:
        assert result["pnl"]["value"] is None
        assert "repo_position_open_at_boundary" in result["reason_codes"]
    assert instrument["event_count"] == 2
    assert (
        sum(
            int(r["amount_kopecks"])
            for r in result["account_only"]
            if r["kind"] == "repo_financing"
        )
        == 100
    )
    assert instrument["reason_codes"] == (
        ["repo_position_open_at_boundary"] if pending is True else []
    )
    if pending == "other":
        other = next(item for item in result["instruments"] if item["isin"] == "RU000A000001")
        assert other["pnl"]["value"] is None
        assert "repo_position_open_at_boundary" in other["reason_codes"]
    assert Decimal(instrument["closing_quantity"]) == 10
    clean = project_clean_analysis(
        analyses[instrument["isin"]], instrument["isin"], instrument_type="stock"
    )
    if pending is not True:
        # This original-bound fixture has grouped Money without a unique native
        # principal disclosure. It must not be relabelled as a clean trade.
        assert clean.pnl.value is None
        # The endpoint value alone is not a return when the purchase amount
        # is unavailable; known independent components remain separately exposed.
        assert clean.known_result.status == "unavailable"
        assert clean.known_result.value is None


@pytest.mark.parametrize("target", ["RU000A000000", "RU000A000001"])
def test_pending_only_repo_withholds_own_issue_without_hiding_known_sibling(target):
    service, doc, raw, report, money = investment_case()
    pending = {
        **deepcopy(doc["trades"][0]),
        "section": "pending",
        "state": "pending",
        "repo_observed": True,
    }
    pending["core"]["isin"] = target
    doc["trades"].append(pending)
    result = service._interval(doc, raw, report, money, {}, {}, True)
    by_isin = {item["isin"]: item for item in result["instruments"]}
    assert by_isin[target]["pnl"]["value"] is None
    assert "repo_position_open_at_boundary" in by_isin[target]["reason_codes"]
    if target != "RU000A000000":
        assert by_isin["RU000A000000"]["pnl"]["value"] == "9000"
    assert result["pnl"]["value"] is None


def test_repo_pairs_keep_account_wide_duplicate_b_owner_across_issues(monkeypatch):
    from dataclasses import replace

    service, doc, raw, report, money = investment_case()
    trades, names, primary, cancellations = service._native(doc, raw)
    ordinary = trades[0]
    other_isin = "RU000A000001"
    other_position = {
        **doc["positions"][0],
        "isin": other_isin,
        "actual_quantity": "0",
        "ending_value": "0",
    }
    doc["positions"].append(other_position)
    report = replace(report, positions={**report.positions, ("1234567", other_isin): ("0", 0)})
    for isin, partner, day in (
        (ordinary["core"]["isin"], "B2", "2030-01-10"),
        (other_isin, "B3", "2030-01-20"),
    ):
        for own, peer, quantity, amount, marker, cash in (
            ("B1", partner, "5", "500", "репо ч.1", -50000),
            (partner, "B1", "-5", "501", "репо ч.2", 50100),
        ):
            trade = {
                **deepcopy(ordinary),
                "ids": [own],
                "repo_observed": True,
                "repo_partner": peer,
                "repo_leg": marker,
                "bank_commission": "0",
                "settlement_date": day,
                "depo_settlement_date": day,
            }
            trade["core"].update(
                isin=isin, quantity=quantity, trade_amount=amount, trade_time=day + "T09:00:00"
            )
            trades.append(trade)
            primary[own].append(trade)
            money.append(
                {
                    **money[0],
                    "minor": cash,
                    "day": date.fromisoformat(day),
                    "date": day,
                    "primary_id": own,
                    "ref": isin + own,
                }
            )
    monkeypatch.setattr(
        service, "_native", lambda *_, **__: (trades, names, primary, cancellations)
    )
    doc["rub_money"][0]["ending_amount"] = "992"
    result = service._interval(doc, raw, report, money, {}, {}, True)
    for instrument in result["instruments"]:
        assert instrument["pnl"]["value"] is None
        assert "repo_pair_unproven" in instrument["reason_codes"]
    assert result["pnl"]["value"] is None


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
        lambda *_, **__: (trades, names, primary, [(ACCOUNT, "RU000A000000", day, Decimal(-10))]),
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
        lambda *_: (
            [(SimpleNamespace(id=i, document_sha256=str(i) * 64), saved, None) for i in [1, 2]],
            None,
        ),
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


def test_investment_unmatched_internal_income_is_not_zero_instrument_income():
    from dataclasses import replace

    from hermes_finance.domain.money_security import MoneySecurity

    service, doc, raw, report, money = investment_case()
    money.append(
        {
            **money[0],
            "classification": "dividend",
            "minor": 1000,
            "security": MoneySecurity("1-01-12345-A", "Synthetic", "dividend"),
            "redemption": None,
            "ref": "unresolved-dividend",
        }
    )
    doc["rub_money"][0]["ending_amount"] = "1000"
    report = replace(report, closing={"1234567": 210000}, reported_pnl={"1234567": 10000})
    links, issues = service._payout_links([doc], {doc["document_sha256"]: money}, report)
    r = service._interval(doc, raw, report, money, links, issues, True)
    assert r["pnl"]["value"] == "10000"  # internal income attribution does not erase account growth
    assert r["reconciliation"]["pdf_pnl_delta_kopecks"] == "0"
    s = r["instruments"][0]
    assert s["pnl"]["value"] is None and s["known_subtotal"]["value"] == "9000"
    assert s["known_subtotal"]["status"] == "partial"
    assert s["components"]["dividends"]["value"] is None
    assert all(
        s[key]["value"] is None for key in ("modified_dietz", "xirr_period", "xirr_annualized")
    )
    assert "unresolved_account_payout_attribution" in s["reason_codes"]


def test_investment_opposite_unknown_custody_movements_cannot_prove_flow_completeness():
    from test_statement_import_mybroker_endpoints import node

    service, _, raw, report, _ = investment_case()
    root = ET.fromstring(raw)
    wrapper = root.find("{MyBroker}Trades3/{MyBroker}Report")
    collection = node(node(wrapper, "Tablix1"), "Details_Collection")
    for day, qty in [(5, "-1"), (25, "1")]:
        node(
            collection,
            "Details",
            acc_code=ACCOUNT,
            p_name="Synthetic / RU000A000000",
            settlement_date=f"2030-01-{day:02d}T00:00:00",
            qty=qty,
            oper_type="Перевод",
            comment_new="Unsupported custody movement",
        )
    raw = ET.tostring(root, encoding="utf-8")
    doc = parse_mybroker(raw, FILENAME)
    r = service._interval(doc, raw, report, service._money(doc, raw), {}, {}, True)
    assert len(r["unresolved_movements"]) == 2
    assert r["pnl"]["value"] is None and r["known_subtotal"]["value"] == "9000"
    assert all(
        r[key]["value"] is None for key in ("modified_dietz", "xirr_period", "xirr_annualized")
    )
    s = r["instruments"][0]
    assert s["pnl"]["value"] is None and s["known_subtotal"]["value"] == "9000"
    assert "unresolved_native_security_movement" in s["reason_codes"]
    assert "4_Transfers_unsupported" in r["source_advisories"]


@pytest.mark.parametrize(
    "change,expected",
    [
        ("supported", 0),
        ("other_comment", 1),
        ("nonfinite", 1),
        ("unknown_auxiliary", 1),
        ("wrapper_sibling", 1),
        ("foreign", 0),
    ],
)
def test_investment_movement_guard_is_exact_and_keeps_supported_metadata(change, expected):
    from decimal import Decimal

    from test_statement_import_mybroker_endpoints import node

    service, _, raw, _, _ = investment_case()
    root = ET.fromstring(raw)
    collection = node(
        node(root.find("{MyBroker}Trades3/{MyBroker}Report"), "Tablix1"), "Details_Collection"
    )
    row = node(
        collection,
        "Details",
        acc_code=ACCOUNT,
        p_name="Synthetic\r\nRU000A000000",
        settlement_date="2030-01-17T00:00:00",
        qty="-10",
        oper_type="Перевод",
        comment_new="Аннулирование выпуска SYNTHETIC1.",
    )
    aux = node(
        node(root.find("{MyBroker}Trades4/{MyBroker}Report"), "Tablix1"), "Details_Collection"
    )
    metadata = node(aux, "Details", sys_start_time="01.01.2030 00:00", sys_end_time="-")
    if change == "other_comment":
        row.set("comment_new", "Unsupported")
    if change == "nonfinite":
        row.set("qty", "sNaN")
    if change == "unknown_auxiliary":
        metadata.set("qty", "1")
    if change == "wrapper_sibling":
        node(root.find("{MyBroker}Trades4"), "OpaqueFinancialRow", amount="100")
    if change == "foreign":
        row.set("acc_code", "7654321-000")
        row.set("comment_new", "Unknown foreign transfer")
    unresolved = service._unresolved_movements(
        ET.tostring(root), ACCOUNT, [(ACCOUNT, "RU000A000000", date(2030, 1, 17), Decimal(-10))]
    )
    assert len(unresolved) == expected


# Exact-reference trade disclosure uses fabricated original rows only.
START, END = date(2029, 12, 31), date(2030, 1, 31)
ISIN = "RU000A000000"


def disclosure_case():
    _, document, raw, report, money = investment_case()
    trade = document["trades"][0]
    row = next(row for row in money if row["classification"] == "trade_settlement")
    token = service._money_trade_token(row)
    return document, raw, report, money, trade, row, token


def disclose(trade, row, token, *, candidates=None, count=1):
    return service._trade_disclosure(
        row,
        {token: [trade] if candidates is None else candidates},
        Counter({token: count}),
        account=trade["core"]["source_account"],
        isin=ISIN,
        currency="RUB",
        start=START,
        end=END,
    )


@pytest.mark.parametrize("restored", [False, True])
def test_exact_trade_enriches_one_settlement_without_changing_cash_or_results(
    restored, monkeypatch
):
    document, raw, report, money, trade, row, _ = disclosure_case()
    native = None
    if restored:
        _, names, _, cancellations = service._native(document, raw)
        native = {
            "names": {k: sorted(v) for k, v in names.items()},
            "cancellations": [[a, i, str(d), str(q)] for a, i, d, q in cancellations],
            "unresolved": service._unresolved_movements(raw, row["source_account"], cancellations),
        }
    analyses = {}
    result = service._interval(
        document, raw, report, money, {}, {}, True, analyses=analyses, native_evidence=native
    )
    analysis = analyses[ISIN]
    buy = next(event for event in analysis.events if event.kind == "BUY")
    assert buy.native_identity == trade["identity"]
    assert buy.native_ids == tuple(trade["ids"])
    assert buy.quantity_delta == Decimal(trade["core"]["quantity"])
    assert buy.unit_price == Decimal(trade["core"]["price"])
    assert buy.trade_time == trade["core"]["trade_time"]
    assert buy.cash_settlement_date.isoformat() == trade["settlement_date"]
    assert buy.depository_settlement_date.isoformat() == trade["depo_settlement_date"]
    assert buy.native_trade_amount_kopecks == service._minor(trade["core"]["trade_amount"])
    assert buy.accrued_interest_kopecks == service._minor(trade["accrued_interest"])
    assert buy.commission_kopecks == service._minor(trade["bank_commission"])
    assert buy.price_unit == "UNKNOWN" and buy.native_total_basis is None
    assert buy.face_value is None and buy.proof_dependency is None
    assert buy.source_references == (row["ref"],)
    assert len(buy.cash_legs) == 1
    assert buy.cash_legs[0].account_cash_kopecks == row["minor"]
    fee = next(event for event in analysis.events if event.kind == "FEE")
    assert fee.quantity_delta is None and fee.native_trade_amount_kopecks is None
    assert fee.commission_kopecks is None
    monkeypatch.setattr(service, "_trade_disclosure", lambda *args, **kwargs: {})
    original_analyses = {}
    original = service._interval(
        document,
        raw,
        report,
        money,
        {},
        {},
        True,
        analyses=original_analyses,
        native_evidence=native,
    )
    assert result == original
    original_analysis = original_analyses[ISIN]
    assert analysis.components == original_analysis.components
    assert analysis.pnl == original_analysis.pnl
    assert analysis.modified_dietz == original_analysis.modified_dietz
    assert analysis.coverage == original_analysis.coverage
    assert len(analysis.events) == len(original_analysis.events)
    assert [event.cash_legs for event in analysis.events] == [
        event.cash_legs for event in original_analysis.events
    ]


@pytest.mark.parametrize(
    "change",
    [
        "identity",
        "isin",
        "currency",
        "direction",
        "cash_date",
        "depo_missing",
        "depo_outside",
        "pending",
        "unsettled",
        "repo",
        "token_conflict",
        "missing_token",
    ],
)
def test_disclosure_requires_exact_native_identity_and_compatible_settlement(change):
    _, _, _, _, trade, row, token = disclosure_case()
    if change == "identity":
        trade["identity"] = "different-native-identity"
    elif change in {"isin", "currency"}:
        trade["core"][change] = "RU000A000001" if change == "isin" else "USD"
    elif change == "direction":
        trade["core"]["quantity"] = "-10"
    elif change == "cash_date":
        trade["settlement_date"] = "2030-01-21"
    elif change == "depo_missing":
        trade["depo_settlement_date"] = None
    elif change == "depo_outside":
        trade["depo_settlement_date"] = "2030-02-01"
    elif change == "pending":
        trade["section"] = "pending"
    elif change == "unsettled":
        trade["state"] = "pending"
    elif change == "repo":
        trade["repo_observed"] = True
    elif change == "token_conflict":
        row["native_token"] = token
        row["primary_id"] = "9999999"
    else:
        row.update(native_token=None, primary_id=None, operation="unlinked")
    assert disclose(trade, row, token) == {}


def test_wrong_account_does_not_receive_metadata():
    _, _, _, _, trade, row, token = disclosure_case()
    other = deepcopy(trade)
    other["core"]["source_account"] = "7654321-000"
    assert disclose(trade, row, token, candidates=[other]) == {}


@pytest.mark.parametrize("conflicting", [False, True])
def test_repeated_or_conflicting_native_reference_is_unknown(conflicting):
    _, _, _, _, trade, row, token = disclosure_case()
    other = deepcopy(trade)
    if conflicting:
        other["core"]["quantity"] = "11"
    assert disclose(trade, row, token, candidates=[trade, other]) == {}


def test_multiple_principal_occurrences_never_repeat_or_distribute_trade_metadata():
    document, raw, report, money, _, row, _ = disclosure_case()
    duplicate = dict(row, ref="synthetic-second-principal")
    row["minor"] //= 2
    duplicate["minor"] -= row["minor"]
    money.append(duplicate)
    analyses = {}
    service._interval(document, raw, report, money, {}, {}, True, analyses=analyses)
    buys = [event for event in analyses[ISIN].events if event.kind == "BUY"]
    assert len(buys) == 2
    assert all(event.quantity_delta is None for event in buys)
    assert all(event.native_trade_amount_kopecks is None for event in buys)


def test_cash_bridge_conflict_keeps_native_disclosure_unknown():
    document, raw, report, money, _, row, _ = disclosure_case()
    row["minor"] -= 1
    analyses = {}
    service._interval(document, raw, report, money, {}, {}, True, analyses=analyses)
    buy = next(event for event in analyses[ISIN].events if event.kind == "BUY")
    assert buy.quantity_delta is None and buy.native_identity is None


def test_sell_uses_exact_signed_quantity_and_source_amount():
    _, _, _, _, trade, row, token = disclosure_case()
    trade["core"]["quantity"] = "-10"
    row["minor"] = abs(row["minor"])
    result = disclose(trade, row, token)
    assert result["quantity_delta"] == Decimal("-10")
    assert result["native_trade_amount_kopecks"] == service._minor(trade["core"]["trade_amount"])


def test_disclosure_operation_reference_fallback_and_conflicting_reference():
    _, _, _, _, trade, row, token = disclosure_case()
    row["operation"] = f"Расчеты по сделке {token}"
    row["primary_id"] = None
    assert disclose(trade, row, token)["native_identity"] == trade["identity"]
    row["primary_id"] = token
    row["operation"] = "Расчеты по сделке 999999999"
    assert disclose(trade, row, token) == {}


def test_disclosure_preserves_decimal_lexemes_and_missing_costs():
    _, _, _, _, trade, row, token = disclosure_case()
    trade["core"]["quantity"] = "0.123456789012345678901234567890123456789"
    trade["core"]["price"] = "123.123456789012345678901234567890123456789"
    trade["accrued_interest"] = None
    trade["bank_commission"] = None
    result = disclose(trade, row, token)
    assert str(result["quantity_delta"]) == trade["core"]["quantity"]
    assert str(result["unit_price"]) == trade["core"]["price"]
    assert result["accrued_interest_kopecks"] is None
    assert result["commission_kopecks"] is None


@pytest.mark.parametrize("revision", ["source_investment_semantics_v6", None])
def test_reviewed_legacy_proof_read_transition_preserves_economics_and_evidence(
    database, monkeypatch, revision
):
    from hermes_finance.services import source_investment_proofs as proofs

    original = save_semantics_proof(
        database, monkeypatch, revision or proofs._GIFT_COMPAT_CODES[1], "reviewed-legacy"
    )
    before = snapshot(database)
    before_bytes = database.database_path.read_bytes()
    with database.session_factory() as session:
        assert proofs.read_reports(session) == original
        assert proofs.request_status(session, "reviewed-legacy")["current"]
        from hermes_finance.services.source_monthly_returns import (
            read_monthly_result,
            read_monthly_returns,
        )

        complete = read_monthly_returns(session, source_account=ACCOUNT)
        for row in complete.months:
            assert (
                read_monthly_result(
                    session,
                    source_account=ACCOUNT,
                    opening_date=row.result.opening_date,
                    closing_date=row.result.closing_date,
                )
                == row.result
            )
    assert snapshot(database) == before
    assert database.database_path.read_bytes() == before_bytes
    with monkeypatch.context() as patch:
        patch.setattr(proofs, "SEMANTICS_REVISION", "source_investment_semantics_future")
        with database.session_factory() as session:
            assert proofs.read_reports(session)[0]["status"] == "stale"


@pytest.mark.parametrize("revision", ["source_investment_semantics_v6", None])
def test_reviewed_legacy_transition_never_admits_pending_writer(database, monkeypatch, revision):
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.source_return_proofs import ProofError

    with monkeypatch.context() as patch:
        patch.setattr(proofs, "SEMANTICS_REVISION", revision or proofs._GIFT_COMPAT_CODES[1])
        preview = saved_investment_preview(database, patch)["persistence"]
    before = snapshot(database)
    with database.session_factory() as session:
        with pytest.raises(ProofError, match="investment_proof_dependencies_changed"):
            proofs.confirm(
                session,
                **{k: preview[k] for k in ("form_token", "preview_digest")},
                request_id="legacy-pending",
            )
    assert snapshot(database) == before


@pytest.mark.parametrize("stale_newer_alias", [True, False])
def test_bounded_month_retains_full_reader_fold_for_proof_aliases(
    database, monkeypatch, stale_newer_alias
):
    import json

    from hermes_finance.persistence import SourceReturnProof
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.source_monthly_returns import (
        read_monthly_result,
        read_monthly_returns,
    )

    save_semantics_proof(database, monkeypatch, proofs.SEMANTICS_REVISION, "native-proof")
    with database.session_factory() as session:
        original = session.scalar(
            select(SourceReturnProof).where(SourceReturnProof.proof_version == proofs.VERSION)
        )
        plan = json.loads(original.evidence_json)
        alias = deepcopy(plan)
        alias["source_account"] = ACCOUNT if plan["source_account"] != ACCOUNT else "1234567"
        dependency, _, _ = proofs._snapshot(
            session,
            alias["source_account"],
            date.fromisoformat(alias["covered_from"]),
            date.fromisoformat(alias["covered_to"]),
        )
        alias["dependency"] = "f" * 64 if stale_newer_alias else dependency

        def append(evidence, request_id):
            session.add(
                SourceReturnProof(
                    source_account=evidence["source_account"],
                    native_account=original.native_account,
                    request_id=request_id,
                    request_fingerprint="a" * 64,
                    proof_version=proofs.VERSION,
                    dependency_digest=proofs._evidence_digest(evidence),
                    evidence_json=proofs._json(evidence),
                    confirmed_at=original.confirmed_at,
                )
            )
            session.flush()

        if not stale_newer_alias:
            stale = {**plan, "dependency": "f" * 64}
            append(stale, "stale-base-proof")
        append(alias, "alias-proof")
        session.commit()
    before = snapshot(database)
    with database.session_factory() as session:
        reports = proofs.read_reports(session, source_account=ACCOUNT)
        assert len(reports) == 2
        assert {report["status"] for report in reports} == {"current", "stale"}
        full = read_monthly_returns(session, source_account=ACCOUNT)
        row = full.months[0].result
        bounded = read_monthly_result(
            session,
            source_account=ACCOUNT,
            opening_date=row.opening_date,
            closing_date=row.closing_date,
        )
        assert bounded == row
    assert snapshot(database) == before
