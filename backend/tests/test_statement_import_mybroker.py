"""Entirely fabricated MyBroker syntax/lifecycle fixtures for the frozen S1 slice."""

from __future__ import annotations

import json
from datetime import date
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Base,
    ClassNoCrossingCoverage,
    InvestmentCashFlow,
    MyBrokerImport,
    ReportingMonth,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.broker_identity_mappings import confirm_mapping, revoke_mapping
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.mybroker_import import (
    apply_mybroker,
    preview_mybroker,
    read_mybroker_import,
    read_mybroker_lineage,
)
from hermes_finance.statement_import.mybroker import (
    PROVIDER,
    SCHEMA,
    SECTIONS,
    MyBrokerError,
    digest,
    parse_mybroker,
)

FILENAME = "Брокерский 1234567 (01.01.30-31.01.30).xml"
ACCOUNT = "1234567-000"
ISIN = "RU000A000000"


@pytest.mark.parametrize("pair,duplicate", [(False, False), (True, False), (True, True)])
def test_b_repo_rows_are_blocked_one_part_observations(database, pair, duplicate):
    xml = repo_fixture(pair=pair, duplicate=duplicate, mixed=True)
    with database.session_factory() as session:
        reviewed = preview(session, xml)
        assert reviewed["can_apply"]
        assert {
            "repo_semantics_unsupported",
            "trade_ids_incomplete",
            "money_semantics_unsupported",
        } <= set(reviewed["blockers"])
        rows = reviewed["document"]["trades"]
        for row in rows[:-1]:
            assert len(row["ids"]) == 1 and row["ids"][0].startswith("B")
            assert row["identity"] is None and row["repo_observed"]
            assert not row["cash_available"] and row["cash_legs"] == []
        assert rows[-1]["identity"] is not None and rows[-1]["cash_available"]
        cash = reviewed["document"]["money"][0]
        assert cash["kind"] == "unsupported" and cash["primary_id"] is None
        result = apply(session, xml, reviewed)
        reread = read_mybroker_import(session, result["import_id"])
        assert reread["document"] == reviewed["document"] == result["document"]
        assert reread["coverage_state"] == "unknown"
        assert apply(session, xml, preview(session, xml))["duplicate"]
        lineage = read_mybroker_lineage(session)
        assert len(lineage["trades"]) == 1
        assert lineage["trades"][0]["identity"] == rows[-1]["identity"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("trade_no", "B"),
        ("trade_no", "B1x"),
        ("trade_no", "b1001"),
        ("trade_no", "B1001\n1002"),
        ("trade_no", "B1001\nB1001"),
        ("trade_no", "A1001"),
        ("trade_no", "B" + "1" * 128),
        ("repo_no", None),
        ("repo_no", ""),
        ("repo_no", "1002"),
        ("repo_no", "B1001"),
        ("repo_no", "B1002\nB1003"),
        ("repo_no", "B1002x"),
        ("repo_no", "B" + "1" * 128),
        ("comment", None),
        ("comment", "репо"),
        ("comment", "репо ч.3"),
        ("comment", "репо ч.1\nрепо ч.2"),
    ],
)
def test_b_repo_refuses_malformed_or_unguarded_rows(field, value):
    root = ET.fromstring(repo_fixture())
    row = root.find(".//{MyBroker}Details[@trade_no]")
    if value is None:
        row.attrib.pop(field)
    else:
        row.set(field, value)
    with pytest.raises(MyBrokerError, match="trade_ids_ambiguous"):
        parse_mybroker(ET.tostring(root), FILENAME)


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({}, "2d53ed849c49f4489ebe0e04bce990a70a48f69c826fcb0468185318d1822d26"),
        ({"pending": True}, "82064e8e243302ebc611ae307ce282799a4ffd18c6eb84d51f77a503bf485a0b"),
        ({"missing_id": True}, "fa01f30b6488ad0d80a5def089030c3ba178976c4ded93692432033f8a0290a7"),
        ({"duplicate": True}, "359132aaa76468a46c2304c4e6c8c2788cf105e0953401de9d54dcbc17857b2f"),
        ({"quiet": True}, "4c326662c4bcda60ef6a1c3e2099ffc1e12274dc7bbd7a561eb5dbe51562b7f1"),
    ],
)
def test_s1_v2_accepted_normalization_is_byte_compatible(kwargs, expected):
    # Captured from canonical main before #736; bind the entire parsed contract.
    assert digest(parse_mybroker(fixture(**kwargs), FILENAME)) == expected


def test_b_repo_import_does_not_reinterpret_accepted_s1_v2_lineage(database):
    with database.session_factory() as session:
        original = apply(session, fixture(), preview(session, fixture()))
        stored = session.get(MyBrokerImport, original["import_id"]).normalized_json
        raw = repo_fixture(pair=True, mixed=True)
        apply(session, raw, preview(session, raw))
        assert (
            read_mybroker_import(session, original["import_id"])["document"] == original["document"]
        )
        assert apply(session, fixture(), preview(session, fixture()))["duplicate"]
        assert session.get(MyBrokerImport, original["import_id"]).normalized_json == stored


def test_b_repo_pending_shape_is_not_authorized():
    root = ET.fromstring(fixture(pending=True, primary="B1001", missing_id=True))
    row = root.find(".//{MyBroker}Details2")
    row.set("repo_no1", "B1002")
    row.set("comment", "репо ч.1")
    with pytest.raises(MyBrokerError, match="trade_ids_ambiguous"):
        parse_mybroker(ET.tostring(root), FILENAME)


def test_b_repo_http_reparse_stale_privacy_and_committed_readback(database):
    client = TestClient(create_app(database=database))
    xml = repo_fixture(pair=True, mixed=True, duplicate=True)
    files = {"file": (FILENAME, xml, "application/xml")}
    response = client.post("/api/mybroker-import/preview", files=files)
    assert response.status_code == 200, response.text
    body = response.json()
    confirmation = {
        "confirmation_digest": body["confirmation_digest"],
        "covered_from": body["document"]["covered_from"],
        "covered_to": body["document"]["covered_to"],
        "mappings": body["mappings"],
    }
    # Even a guard-only partner change is bound through the authoritative bytes.
    changed = xml.replace(b'repo_no="B1002"', b'repo_no="B1003"')
    stale = client.post(
        "/api/mybroker-import/apply",
        files={"file": (FILENAME, changed, "application/xml")},
        data={"confirmation": json.dumps(confirmation)},
    )
    assert stale.status_code == 409 and "preview_stale" in stale.text
    applied = client.post(
        "/api/mybroker-import/apply", files=files, data={"confirmation": json.dumps(confirmation)}
    )
    assert applied.status_code == 200, applied.text
    reread = client.get(f"/api/mybroker-import/{applied.json()['import_id']}")
    assert reread.status_code == 200
    assert reread.json()["document"] == applied.json()["document"] == body["document"]
    assert reread.json()["document"]["parser"] == "mybroker-s1-v2"
    for row in reread.json()["document"]["trades"][:-1]:
        assert {"repo_semantics_unsupported", "trade_ids_incomplete"} <= set(row["blockers"])
    assert reread.json()["coverage_state"] == "unknown"
    for private_text in (
        "Synthetic name never retained",
        "репо ч.1",
        "Расчеты по сделке",
        FILENAME,
    ):
        assert private_text not in reread.text
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 1
        for model in (InvestmentCashFlow, ReportingMonth):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def node(parent, tag, **attrs):
    return ET.SubElement(parent, "{MyBroker}" + tag, attrs)


def repo_fixture(*, pair=False, mixed=False, duplicate=False, money=True):
    """Fabricated #736 completed one-part REPO observations; no economic pairing."""
    from copy import deepcopy

    root = ET.fromstring(fixture(money=money, primary="B1001", missing_id=True))
    collection = root.find(
        "{MyBroker}Trades/{MyBroker}Report/{MyBroker}Tablix2/{MyBroker}Details_Collection"
    )
    row = collection.find("{MyBroker}Details")
    row.set("repo_no", "B1002")
    row.set("comment", "репо ч.1")
    if duplicate:
        collection.append(deepcopy(row))
    if pair:
        partner = deepcopy(row)
        partner.set("trade_no", "B1002")
        partner.set("repo_no", "B1001")
        partner.set("comment", "репо ч.2")
        collection.append(partner)
    if mixed:
        regular = ET.fromstring(fixture())
        collection.append(deepcopy(regular.find(".//{MyBroker}Details[@trade_no]")))
        group = root.find(".//{MyBroker}rn_Collection")
        group.append(deepcopy(regular.find(".//{MyBroker}rn")))
    return ET.tostring(root, encoding="utf-8")


def fixture(
    *,
    pending=False,
    qty="10",
    secondary="2000000001",
    missing_id=False,
    money=True,
    quiet=False,
    forward="10",
    unsupported=False,
    nkd=None,
    duplicate=False,
    primary="10000000001",
):
    root = ET.Element(
        "{MyBroker}Report",
        {
            "Name": "MyBroker",
            "Textbox5": "Отчет по сделкам и операциям (Отчет брокера)",
            "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation": SCHEMA,
        },
    )
    sections = {
        outer: node(node(root, outer), "Report", Name=name) for outer, name in SECTIONS.items()
    }
    if quiet:
        return ET.tostring(root, encoding="utf-8")
    detail = node(
        node(
            node(
                node(node(sections["Positions"], "Tablix1"), "active_type_Collection"),
                "active_type",
            ),
            "Details_Collection",
        ),
        "Details",
        acc_code=ACCOUNT,
        ISIN1=ISIN,
        real_rest="10",
        forward_rest=forward,
        active_name="Synthetic name never retained",
    )
    assert detail is not None
    table = node(sections["Trades"], "Tablix3" if pending else "Tablix2")
    collection = node(table, "Details2_Collection" if pending else "Details_Collection")
    attrs = {
        "trade_no": primary if missing_id else primary + "\r\n" + secondary,
        "db_time": "15.01.2030 9:00:00\r\n15.01.2030 9:00:00",
        "save_settlement_date": "17.01.2030",
        "save_depo_settlement_date": "17.01.2030",
        "settlement_time": "17.01.2030 10:00:00",
        "acc_code": ACCOUNT,
        "isin_reg": ISIN,
        "qty": qty,
        "Price": "100.00",
        "summ_trade": "1000.00",
        "curr_calc": "RUB",
        "bank_tax": "0",
    }
    if nkd is not None:
        attrs["summ_nkd"] = nkd
    if pending:
        renames = {
            "trade_no": "trade_no1",
            "db_time": "db_time2",
            "save_settlement_date": "save_settlement_date3",
            "save_depo_settlement_date": "save_depo_settlement_date3",
            "settlement_time": "settlement_time2",
            "acc_code": "acc_code2",
            "isin_reg": "isin_reg1",
            "qty": "qty2",
            "Price": "Price2",
            "summ_trade": "summ_trade2",
            "curr_calc": "curr_calc2",
            "bank_tax": "bank_tax2",
            "summ_nkd": "summ_nkd2",
        }
        attrs = {renames[key]: value for key, value in attrs.items()}
    node(collection, "Details2" if pending else "Details", **attrs)
    if duplicate:
        node(collection, "Details2" if pending else "Details", **attrs)
    if money and not pending:
        groups = node(node(sections["Trades2"], "Tablix1"), "settlement_date_Collection")
        group = node(groups, "settlement_date", settlement_date="2030-01-17T00:00:00")
        rn = node(node(group, "rn_Collection"), "rn", last_update="2030-01-17T10:00:00")
        op = node(rn, "oper_type", oper_type="Synthetic")
        comment = node(op, "comment", comment="Расчеты по сделке " + primary)
        node(comment, "Textbox11", acc_code=ACCOUNT)
        level = node(
            node(
                node(node(comment, "money_volume_begin1_Collection"), "money_volume_begin1"),
                "p_code_Collection",
            ),
            "p_code",
        )
        node(level, "p_code", volume="-1000.00", p_code="RUB")
    if unsupported:
        node(sections["Trades3"], "Tablix1")
    return ET.tostring(root, encoding="utf-8")


@pytest.fixture
def database(tmp_path):
    db = create_database(tmp_path / "synthetic-mybroker.db")
    Base.metadata.create_all(db.engine)
    with db.session_factory() as session:
        account = create_account(session, name="Synthetic account", account_type="brokerage")
        instrument = create_instrument(
            session, name="Synthetic security", instrument_type="stock", isin=ISIN
        )
        for identity in ("1234567", ACCOUNT):
            confirm_mapping(
                session,
                provider=PROVIDER,
                subject_kind="account",
                provider_identity=identity,
                hermes_target_id=account.id,
            )
        confirm_mapping(
            session,
            provider=PROVIDER,
            subject_kind="instrument",
            provider_identity=ISIN,
            hermes_target_id=instrument.id,
            observed_isin=ISIN,
        )
    yield db
    db.engine.dispose()


def preview(session, document, filename=FILENAME):
    return preview_mybroker(session, document=document, filename=filename)


def apply(session, document, reviewed, filename=FILENAME):
    return apply_mybroker(
        session,
        document=document,
        filename=filename,
        confirmation_digest=reviewed["confirmation_digest"],
        confirmed_range=(reviewed["document"]["covered_from"], reviewed["document"]["covered_to"]),
        confirmed_mappings=reviewed["mappings"],
    )


def include_source_account(session):
    from hermes_finance.persistence import AccountPerformanceScopeMembership, BrokerIdentityMapping

    account_id = session.scalar(
        select(BrokerIdentityMapping.hermes_account_id).where(
            BrokerIdentityMapping.provider == PROVIDER,
            BrokerIdentityMapping.provider_identity == ACCOUNT,
        )
    )
    session.add(
        AccountPerformanceScopeMembership(
            account_id=account_id, effective_from=date(2029, 1, 1), include_in_returns=True
        )
    )
    session.commit()
    return account_id


def test_exact_syntax_linewise_identity_decimal_and_no_private_text():
    result = parse_mybroker(fixture(nkd="1.23"), FILENAME)
    trade = result["trades"][0]
    assert trade["ids"] == ["10000000001", "2000000001"]
    assert trade["core"]["trade_time"] == "2030-01-15T09:00:00"
    assert trade["core"]["price"] == "100"
    assert trade["accrued_interest"] == "1.23"
    assert "Synthetic name" not in json.dumps(result)
    assert parse_mybroker(fixture(qty="-10"), FILENAME)["trades"][0]["core"]["quantity"] == "-10"
    assert parse_mybroker(fixture(missing_id=True), FILENAME)["trades"][0]["identity"] is None


@pytest.mark.parametrize(
    "filename",
    [
        "random.xml",
        "Брокерский 1234567 (31.01.30-01.01.30).xml",
        "Брокерский 1234567 (31.02.30-31.03.30).xml",
        "Брокерский 1234567 (01.01.30-31.01.30) (01.02.30-28.02.30).xml",
    ],
)
def test_filename_fails_closed(filename):
    with pytest.raises(MyBrokerError, match="filename_range_invalid"):
        parse_mybroker(fixture(), filename)


@pytest.mark.parametrize(
    "change",
    [
        "namespace",
        "schema",
        "duplicate_section",
        "missing_section",
        "decimal",
        "entity",
        "unparsed_row",
    ],
)
def test_family_and_material_rows_fail_closed(change):
    xml = fixture()
    if change == "namespace":
        xml = xml.replace(b"MyBroker", b"OtherBroker")
    elif change == "schema":
        xml = xml.replace(b"Schema=True", b"Schema=False")
    elif change == "decimal":
        xml = xml.replace(b'qty="10"', b'qty="1e1"')
    elif change == "entity":
        xml = b'<!DOCTYPE Report [<!ENTITY x "private">]>' + xml
    else:
        root = ET.fromstring(xml)
        if change == "duplicate_section":
            node(node(root, "Positions"), "Report", Name="1_Positions")
        elif change == "missing_section":
            root.remove(root.find("{MyBroker}Trades4"))
        else:
            node(root.find("{MyBroker}Positions/{MyBroker}Report"), "Details", qty="1")
        xml = ET.tostring(root)
    if change == "unparsed_row":
        assert "unparsed_source_rows" in parse_mybroker(xml, FILENAME)["syntax_blockers"]
    else:
        with pytest.raises(MyBrokerError):
            parse_mybroker(xml, FILENAME)


def test_source_only_apply_idempotency_overlap_and_authoritative_readback(database):
    xml = fixture(duplicate=True)
    with database.session_factory() as session:
        reviewed = preview(session, xml)
        assert reviewed["can_apply"]
        first = apply(session, xml, reviewed)
        reread = read_mybroker_import(session, first["import_id"])
        assert reread["document"] == first["document"]
        second = apply(session, xml, preview(session, xml))
        assert second["duplicate"] and second["import_id"] == first["import_id"]
        longer = "Брокерский 1234567 (01.01.30-28.02.30).xml"
        # Different source bytes add an occurrence, never another economic trade.
        other = fixture(qty="10.00")
        apply(session, other, preview(session, other, longer), longer)
        lineage = read_mybroker_lineage(session)
        assert len(lineage["trades"]) == 1
        assert len(lineage["source_ranges"]) == 4
        assert lineage["coverage_state"] == "unknown"
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 0
        assert session.scalar(select(func.count()).select_from(ReportingMonth)) == 0


def test_pending_to_settled_monotonic_lifecycle_and_rollback_refusal(database):
    with database.session_factory() as session:
        pending = fixture(pending=True, forward="20")
        earlier = "Брокерский 1234567 (01.01.30-16.01.30).xml"
        p = preview(session, pending, earlier)
        assert "pending_not_cash" in p["blockers"] and "endpoint_unsettled" in p["blockers"]
        apply(session, pending, p, earlier)
        settled = fixture()
        apply(session, settled, preview(session, settled))
        trades = read_mybroker_lineage(session)["trades"]
        assert len(trades) == 1 and trades[0]["state"] == "settled"
        changed_pending = fixture(pending=True, qty="10.0")
        later = "Брокерский 1234567 (01.01.30-28.02.30).xml"
        p = preview(session, changed_pending, later)
        assert "settled_to_pending_conflict" in p["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, changed_pending, p, later)
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 2


@pytest.mark.parametrize("settled_first", [False, True])
def test_source_chronology_not_upload_order_controls_enrichment(database, settled_first):
    earlier = "Брокерский 1234567 (01.01.30-16.01.30).xml"
    observations = [(fixture(pending=True), earlier), (fixture(), FILENAME)]
    if settled_first:
        observations.reverse()
    with database.session_factory() as session:
        for xml, filename in observations:
            p = preview(session, xml, filename)
            assert p["conflicts"] == []
            apply(session, xml, p, filename)
        lineage = read_mybroker_lineage(session)
        assert lineage["conflicts"] == []
        assert len(lineage["trades"]) == 1
        assert lineage["trades"][0]["state"] == "settled"
        assert lineage["trades"][0]["cash_available"]
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 2


@pytest.mark.parametrize("settled_first", [False, True])
@pytest.mark.parametrize("settled_start", ["01.01.30", "10.01.30"])
def test_same_source_endpoint_state_disagreement_conflicts_in_both_orders(
    database, settled_first, settled_start
):
    settled_filename = f"Брокерский 1234567 ({settled_start}-31.01.30).xml"
    observations = [(fixture(pending=True), FILENAME), (fixture(), settled_filename)]
    if settled_first:
        observations.reverse()
    with database.session_factory() as session:
        first, second = observations
        apply(session, first[0], preview(session, *first), first[1])
        p = preview(session, *second)
        assert "settled_to_pending_conflict" in p["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, second[0], p, second[1])
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 1


@pytest.mark.parametrize("pending_first", [False, True])
@pytest.mark.parametrize("omission_endpoint", ["16.01.30", "28.02.30"])
def test_pending_disappearance_checks_the_whole_overlapping_set(
    database, pending_first, omission_endpoint
):
    omitted = f"Брокерский 1234567 (01.01.30-{omission_endpoint}).xml"
    observations = [(fixture(pending=True), FILENAME), (fixture(quiet=True), omitted)]
    if not pending_first:
        observations.reverse()
    with database.session_factory() as session:
        first, second = observations
        apply(session, first[0], preview(session, *first), first[1])
        p = preview(session, *second)
        assert "pending_disappeared" in p["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, second[0], p, second[1])
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 1


@pytest.mark.parametrize("wide_first", [False, True])
def test_settled_overlap_enriches_cash_and_optional_evidence_without_duplicates(
    database, wide_first
):
    narrow = "Брокерский 1234567 (01.01.30-16.01.30).xml"
    partial = (
        fixture(money=False)
        .replace(b'bank_tax="0"', b"")
        .replace(b'settlement_time="17.01.2030 10:00:00"', b"")
    )
    observations = [(partial, narrow), (fixture(nkd="1.23"), FILENAME)]
    if wide_first:
        observations.reverse()
    with database.session_factory() as session:
        for xml, filename in observations:
            p = preview(session, xml, filename)
            assert p["conflicts"] == []
            apply(session, xml, p, filename)
        lineage = read_mybroker_lineage(session)
        assert lineage["conflicts"] == []
        assert len(lineage["trades"]) == 1
        trade = lineage["trades"][0]
        assert trade["bank_commission"] == "0"
        assert trade["accrued_interest"] == "1.23"
        assert trade["settlement_time"] == "2030-01-17T10:00:00"
        assert len(trade["cash_legs"]) == 1 and trade["cash_available"]
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 0


@pytest.mark.parametrize(
    "change", ["cash_amount", "cash_date", "cash_currency", "commission", "nkd"]
)
@pytest.mark.parametrize("changed_first", [False, True])
def test_contradictory_present_settled_evidence_remains_a_conflict(database, change, changed_first):
    original = fixture(nkd="1.23")
    replacements = {
        "cash_amount": (b'volume="-1000.00"', b'volume="-1001.00"'),
        "cash_date": (b"2030-01-17T00:00:00", b"2030-01-18T00:00:00"),
        "cash_currency": (b'p_code="RUB"', b'p_code="USD"'),
        "commission": (b'bank_tax="0"', b'bank_tax="1"'),
        "nkd": (b'summ_nkd="1.23"', b'summ_nkd="2"'),
    }
    changed = original.replace(*replacements[change])
    observations = [original, changed]
    if changed_first:
        observations.reverse()
    with database.session_factory() as session:
        apply(session, observations[0], preview(session, observations[0]))
        p = preview(session, observations[1])
        assert "trade_material_conflict" in p["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, observations[1], p)
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 1


def test_incomplete_primary_link_attaches_to_no_identity_less_trade(database):
    root = ET.fromstring(fixture(missing_id=True, duplicate=True))
    rows = root.findall(".//{MyBroker}Tablix2/{MyBroker}Details_Collection/{MyBroker}Details")
    rows[1].set("trade_no", "20000000002")
    xml = ET.tostring(root)
    with database.session_factory() as session:
        p = preview(session, xml)
        assert "money_link_incomplete_identity" in p["blockers"]
        assert p["document"]["money"][0]["trade_identity"] is None
        assert all(t["cash_legs"] == [] for t in p["document"]["trades"])
        imported = apply(session, xml, p)
        assert all(t["cash_legs"] == [] for t in imported["document"]["trades"])
        assert read_mybroker_lineage(session)["trades"] == []


def test_reduction_is_a_pure_function_of_the_document_set(database):
    from itertools import permutations

    from hermes_finance.services.mybroker_import import _reduce
    from hermes_finance.statement_import.mybroker import canonical

    with database.session_factory() as session:
        documents = [
            preview(session, fixture(pending=True), "Брокерский 1234567 (01.01.30-16.01.30).xml")[
                "document"
            ],
            preview(session, fixture(nkd="1.23"), "Брокерский 1234567 (01.01.30-17.01.30).xml")[
                "document"
            ],
            preview(session, fixture(money=False), FILENAME)["document"],
        ]
    before = canonical(documents)
    results = [canonical(_reduce(list(order))) for order in permutations(documents)]
    assert len(set(results)) == 1
    trades, conflicts = _reduce(documents)
    assert conflicts == []
    assert len(trades) == 1
    assert next(iter(trades.values()))["cash_available"]
    assert canonical(documents) == before


def test_source_conflict_projection_cannot_clear_a_later_class_cutoff(database):
    from hermes_finance.services.mybroker_import import _reduce, _source_affects_interval

    with database.session_factory() as session:
        pending = preview(session, fixture(pending=True))
        settled = preview(session, fixture())
    projection, conflicts = _reduce([pending["document"], settled["document"]])
    assert "settled_to_pending_conflict" in conflicts
    assert not next(iter(projection.values()))["cash_available"]
    account = next(b["hermes_id"] for b in pending["mappings"] if b["kind"] == "account")
    assert _source_affects_interval(
        pending["document"],
        pending["mappings"],
        (account,),
        date(2030, 2, 1),
        date(2030, 2, 28),
        projection,
    )
    assert not _source_affects_interval(
        pending["document"],
        pending["mappings"],
        (),
        date(2030, 2, 1),
        date(2030, 2, 28),
        projection,
    )


def test_changed_economics_and_disappearing_pending_are_conflicts(database):
    with database.session_factory() as session:
        original = fixture(pending=True)
        apply(session, original, preview(session, original))
        changed = fixture(qty="11")
        assert "immutable_trade_conflict" in preview(session, changed)["conflicts"]
        # The same explicit filename account binds the overlapping quiet report too;
        # no acc_code suffix guess is needed to detect disappearance.
        empty = fixture(quiet=True)
        assert not preview(session, empty)["document"]["positions"]
        assert "pending_disappeared" in preview(session, empty)["conflicts"]
        root = ET.fromstring(empty)
        sections = root.find("{MyBroker}Positions/{MyBroker}Report")
        row = node(
            node(
                node(node(node(sections, "Tablix1"), "active_type_Collection"), "active_type"),
                "Details_Collection",
            ),
            "Details",
            acc_code=ACCOUNT,
            ISIN1=ISIN,
            real_rest="0",
            forward_rest="0",
        )
        assert row is not None
        disappeared = ET.tostring(root)
        assert "pending_disappeared" in preview(session, disappeared)["conflicts"]


def test_different_native_ids_stay_different_and_same_hash_range_is_conflict(database):
    with database.session_factory() as session:
        original = fixture()
        apply(session, original, preview(session, original))
        other = fixture(primary="10000000002", secondary="2000000002", money=False)
        apply(session, other, preview(session, other))
        assert len(read_mybroker_lineage(session)["trades"]) == 2
        alternate = "Брокерский 1234567 (01.01.30-28.02.30).xml"
        p = preview(session, original, alternate)
        assert "document_coverage_conflict" in p["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, original, p, alternate)


def test_changed_bytes_mapping_or_reconciliation_state_rejects_whole_apply(database):
    with database.session_factory() as session:
        xml = fixture()
        p = preview(session, xml)
        with pytest.raises(MyBrokerError, match="preview_stale"):
            apply(session, fixture(qty="11"), p)
        mapping_id = next(b["mapping_id"] for b in p["mappings"] if b["identity"] == ACCOUNT)
        revoke_mapping(session, mapping_id)
        with pytest.raises(MyBrokerError, match="preview_stale"):
            apply(session, xml, p)
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 0


def test_unknowns_remain_visible_and_accepted_coverage_is_not_silently_invalidated(database):
    with database.session_factory() as session:
        include_source_account(session)
        xml = fixture(money=False, unsupported=True, missing_id=True)
        p = preview(session, xml)
        assert {
            "trade_ids_incomplete",
            "settlement_cash_missing_or_ambiguous",
            "4_Transfers_unsupported",
        } <= set(p["blockers"])
        assert p["coverage_state"] == "unknown"
        session.add(
            ClassNoCrossingCoverage(
                asset_class="stock",
                covered_from=date(2029, 12, 31),
                covered_to=date(2030, 1, 31),
                coverage_state="complete",
                provenance_kind="owner_attestation",
                material_signature="a" * 64,
                revision=1,
            )
        )
        session.commit()
        p = preview(session, xml)
        assert "accepted_class_coverage_requires_reconciliation" in p["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, xml, p)


def test_http_preview_explicit_confirmation_apply_and_reread(database):
    client = TestClient(create_app(database=database))
    xml = fixture()
    files = {"file": (FILENAME, xml, "application/xml")}
    p = client.post("/api/mybroker-import/preview", files=files)
    assert p.status_code == 200, p.text
    body = p.json()
    confirmation = {
        "confirmation_digest": body["confirmation_digest"],
        "covered_from": "2030-01-01",
        "covered_to": "2030-01-31",
        "mappings": body["mappings"],
    }
    bad = client.post(
        "/api/mybroker-import/apply",
        files=files,
        data={"confirmation": json.dumps({**confirmation, "rows": []})},
    )
    assert bad.status_code == 422
    applied = client.post(
        "/api/mybroker-import/apply", files=files, data={"confirmation": json.dumps(confirmation)}
    )
    assert applied.status_code == 200, applied.text
    reread = client.get(f"/api/mybroker-import/{applied.json()['import_id']}")
    assert reread.json()["document"] == applied.json()["document"]
    assert client.get("/api/mybroker-import/lineage").json()["coverage_state"] == "unknown"


def test_primary_only_cash_link_with_two_trade_identities_is_atomic_conflict(database):
    root = ET.fromstring(fixture(duplicate=True))
    rows = root.findall(
        ".//{MyBroker}Trades/{MyBroker}Report/{MyBroker}Tablix2/"
        "{MyBroker}Details_Collection/{MyBroker}Details"
    )
    rows[1].set("trade_no", "10000000001\r\n2000000002")
    xml = ET.tostring(root)
    with database.session_factory() as session:
        p = preview(session, xml)
        assert "money_link_ambiguous" in p["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, xml, p)
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 0


def test_new_trade_cannot_make_an_accepted_primary_cash_link_ambiguous(database):
    with database.session_factory() as session:
        original = fixture()
        apply(session, original, preview(session, original))
        other = fixture(secondary="2000000002", money=False)
        p = preview(session, other)
        assert "money_link_ambiguous" in p["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, other, p)
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 1


def test_pending_survives_old_report_range_until_explicit_settlement(database):
    from hermes_finance.services.mybroker_import import unresolved_class_source_ids

    with database.session_factory() as session:
        pending = fixture(pending=True)
        earlier = "Брокерский 1234567 (01.01.30-16.01.30).xml"
        p = preview(session, pending, earlier)
        account = next(b["hermes_id"] for b in p["mappings"] if b["kind"] == "account")
        apply(session, pending, p, earlier)
        assert unresolved_class_source_ids(session, (account,), date(2030, 2, 1), date(2030, 2, 28))
        session.rollback()
        settled = fixture()
        apply(session, settled, preview(session, settled))
        assert not unresolved_class_source_ids(
            session, (account,), date(2030, 2, 1), date(2030, 2, 28)
        )


def test_actual_settlement_crossing_cutoff_remains_blocker_beyond_report_range(database):
    from hermes_finance.services.mybroker_import import unresolved_class_source_ids

    xml = fixture().replace(b"17.01.2030", b"17.03.2030")
    with database.session_factory() as session:
        p = preview(session, xml)
        account = next(b["hermes_id"] for b in p["mappings"] if b["kind"] == "account")
        apply(session, xml, p)
        assert unresolved_class_source_ids(session, (account,), date(2030, 2, 1), date(2030, 2, 28))


@pytest.mark.parametrize("pending", [True, False])
def test_preview_surfaces_cutoff_impact_on_already_accepted_later_interval(database, pending):
    with database.session_factory() as session:
        include_source_account(session)
        session.add(
            ClassNoCrossingCoverage(
                asset_class="stock",
                covered_from=date(2030, 2, 1),
                covered_to=date(2030, 2, 28),
                coverage_state="complete",
                provenance_kind="owner_attestation",
                material_signature="a" * 64,
                revision=1,
            )
        )
        session.commit()
        xml = fixture(pending=pending).replace(b"17.01.2030", b"17.03.2030")
        p = preview(session, xml)
        assert "accepted_class_coverage_requires_reconciliation" in p["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, xml, p)
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 0


def test_concurrent_apply_reserves_writer_before_authoritative_recheck(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    xml = fixture()
    with database.session_factory() as session:
        p = preview(session, xml)
    barrier = Barrier(2)

    def attempt():
        with database.session_factory() as session:
            barrier.wait(timeout=10)
            try:
                return apply(session, xml, p)["import_id"]
            except MyBrokerError as error:
                return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))
    assert sorted(map(str, results)) == ["1", "preview_stale"]
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 1


def test_later_no_crossing_assertion_cannot_ignore_accepted_source_or_use_current_class(database):
    from hermes_finance.persistence import AccountPerformanceScopeMembership, BrokerIdentityMapping
    from hermes_finance.services.class_endpoint_eligibility import (
        class_endpoint_eligibility,
        save_no_crossing_coverage,
    )

    with database.session_factory() as session:
        xml = fixture()
        apply(session, xml, preview(session, xml))
        account_id = session.scalar(
            select(BrokerIdentityMapping.hermes_account_id).where(
                BrokerIdentityMapping.provider == PROVIDER,
                BrokerIdentityMapping.provider_identity == ACCOUNT,
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=account_id, effective_from=date(2029, 1, 1), include_in_returns=True
            )
        )
        session.commit()
        for asset_class in ("stock", "bond", "gold"):
            result = class_endpoint_eligibility(
                session,
                asset_class=asset_class,
                start_date=date(2030, 1, 1),
                end_date=date(2030, 1, 31),
            )
            assert "mybroker_class_reconciliation_required" in result["reason_codes"]
            assert result["status"] == "unavailable"
        with pytest.raises(ValueError, match="mybroker_class_reconciliation_required"):
            save_no_crossing_coverage(
                session,
                asset_class="stock",
                covered_from=date(2030, 1, 1),
                covered_to=date(2030, 1, 31),
                coverage_state="complete",
            )
