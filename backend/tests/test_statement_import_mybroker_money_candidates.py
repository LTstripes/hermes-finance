"""Fabricated originals only; diagnostic reads cannot write or clear S1 blockers."""

import json
from dataclasses import asdict
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import event, select
from test_statement_import_mybroker import (
    ACCOUNT,
    FILENAME,
    apply,
    fixture,
    node,
    preview,
)
from test_statement_import_mybroker import (
    database as synthetic_database,
)

from hermes_finance.persistence import Account, BrokerIdentityMapping, MyBrokerImport
from hermes_finance.services.broker_identity_mappings import revoke_mapping
from hermes_finance.services.mybroker_money_candidates import ADAPTER, read_money_candidates
from hermes_finance.statement_import.mybroker import NS, MyBrokerError, canonical, digest

COUPON = "погашение купона SYNTHETIC-TOKEN (облигации Synthetic issuer) д.ф.16.01.2030"
CASH_IN = "из АО Synthetic bank"

database = synthetic_database


def original(*, coupons=("1000.00", "2000.00"), extra=False, pending=False, opaque=False):
    root = ET.fromstring(fixture(pending=pending, unsupported=opaque))
    report = root.find("m:Trades2/m:Report", NS)
    groups = report.find("m:Tablix1/m:settlement_date_Collection", NS)
    if groups is None:
        groups = node(node(report, "Tablix1"), "settlement_date_Collection")
        group = node(groups, "settlement_date", settlement_date="2030-01-17T00:00:00")
        collection = node(group, "rn_Collection")
    else:
        collection = groups.find("m:settlement_date/m:rn_Collection", NS)

    def cash(operation, narrative, *amounts):
        rn = node(collection, "rn", last_update="2030-01-17T10:00:00")
        comment = node(node(rn, "oper_type", oper_type=operation), "comment", comment=narrative)
        node(comment, "Textbox11", acc_code=ACCOUNT)
        level = node(
            node(
                node(node(comment, "money_volume_begin1_Collection"), "money_volume_begin1"),
                "p_code_Collection",
            ),
            "p_code",
        )
        for amount in amounts:
            node(level, "p_code", volume=amount, p_code="RUB")

    if not pending:
        cash("Synthetic", "Комиссия по сделке 10000000001", "-10.00")
    cash("Перевод", COUPON, *coupons)  # multiple leaves in ONE rn, never one occurrence
    cash("Перевод", CASH_IN, "50000.00")
    cash("НКД по сделке", "Synthetic NKD text without a native trade id", "-125.50")
    if extra:
        cash("Перевод", "Synthetic unsupported dividend", "15.00")
        node(report, "Tablix7")  # unapproved summary shape must remain an S1 blocker
    return ET.tostring(root, encoding="utf-8")


def accept(db, xml, filename=FILENAME):
    with db.session_factory() as session:
        result = apply(session, xml, preview(session, xml, filename), filename)
        account_id = session.scalar(select(Account.id))
    return result["import_id"], account_id


def read(db, import_id, account_id, xml, filename=FILENAME):
    with db.session_factory() as session:
        return read_money_candidates(
            session, import_id=import_id, document=xml, filename=filename, account_id=account_id
        )


def test_exact_six_leaf_inventory_ten_zero_write_reads_and_s1_receipt_parity(database):
    xml = original()
    import_id, account_id = accept(database, xml)
    with database.session_factory() as session:
        source = session.get(MyBrokerImport, import_id)
        before = (source.normalized_json, source.mappings_json, source.confirmation_digest)
        plan_before = preview(session, xml)

    def forbid_write(_connection, _cursor, statement, _parameters, _context, _many):
        assert statement.split()[0].upper() not in {
            "INSERT",
            "UPDATE",
            "DELETE",
            "REPLACE",
            "CREATE",
            "ALTER",
            "DROP",
        }

    event.listen(database.engine, "before_cursor_execute", forbid_write)
    try:
        results = [read(database, import_id, account_id, xml) for _ in range(10)]
    finally:
        event.remove(database.engine, "before_cursor_execute", forbid_write)
    result = results[0]
    assert all(r == result for r in results)
    assert result.adapter == ADAPTER
    assert len(result.observations) == 6
    assert [r.s1_kind for r in result.observations] == ["settlement", "commission"] + [
        "unsupported"
    ] * 4
    assert [r.candidate_kind for r in result.observations] == [
        "unsupported",
        "unsupported",
        "coupon_paid_candidate",
        "coupon_paid_candidate",
        "account_cash_in_candidate",
        "trade_paid_nkd_candidate",
    ]
    assert result.source_subtotals == {
        "coupon_paid_candidate": "3000",
        "account_cash_in_candidate": "50000",
        "trade_paid_nkd_candidate": "-125.5",
    }
    assert [r.amount_minor for r in result.observations] == [
        -100000,
        -1000,
        100000,
        200000,
        5000000,
        -12550,
    ]
    assert all(
        r.authority == "unproven" and r.economic_event_id is None and r.instrument_id is None
        for r in result.observations
    )
    assert result.observations[-1].trade_identity is None
    assert result.observations[0].trade_identity is not None
    assert result.coverage_state == "unknown" and not result.financial_apply_available
    assert {
        "summary_proof_unavailable",
        "money_semantics_unsupported",
        "instrument_link_unproven",
        "portfolio_externality_unproven",
        "trade_link_unproven",
        "paid_nkd_basis_unproven",
    } <= set(result.exceptions)
    assert len({r.locator for r in result.observations}) == 6
    with database.session_factory() as session:
        source = session.get(MyBrokerImport, import_id)
        assert before == (source.normalized_json, source.mappings_json, source.confirmation_digest)
        assert preview(session, xml) == plan_before
        stored = json.loads(source.normalized_json)
        assert [r.occurrence.row_fingerprint for r in result.observations] == [
            digest(r) for r in stored["money"]
        ]
    serialized = canonical(asdict(result))
    for text in (
        COUPON,
        CASH_IN,
        "Synthetic issuer",
        "Synthetic bank",
        "SYNTHETIC-TOKEN",
        "Synthetic NKD text",
        FILENAME,
    ):
        assert text not in serialized


def test_repeated_identical_leaves_seventh_exception_pending_and_opaque_are_retained(database):
    xml = original(coupons=("1000", "1000"), extra=True, opaque=True)
    import_id, account_id = accept(database, xml)
    result = read(database, import_id, account_id, xml)
    assert len(result.observations) == 7
    coupons = [r for r in result.observations if r.candidate_kind == "coupon_paid_candidate"]
    assert len(coupons) == 2 and coupons[0].occurrence != coupons[1].occurrence
    assert all("same_report_multiplicity" in r.reasons for r in coupons)
    assert Decimal(result.source_subtotals["coupon_paid_candidate"]) == 2000
    assert result.observations[-1].candidate_kind == "unsupported"
    assert {"unparsed_source_rows", "4_Transfers_unsupported", "source_pattern_unproven"} <= set(
        result.exceptions
    )


def test_pending_blockers_remain_with_visible_unproven_candidates(database):
    pending_xml = original(pending=True)
    pending_id, account_id = accept(database, pending_xml)
    pending_result = read(database, pending_id, account_id, pending_xml)
    assert "pending_not_cash" in pending_result.exceptions


@pytest.mark.parametrize(
    "amount,currency,posted,reason",
    [
        ("0.001", "RUB", "2030-01-17T00:00:00", "fractional_kopecks"),
        ("0", "RUB", "2030-01-17T00:00:00", "zero_amount"),
        ("92233720368547758.08", "RUB", "2030-01-17T00:00:00", "amount_overflow"),
        (
            "99999999999999999999999999999999999999.99",
            "RUB",
            "2030-01-17T00:00:00",
            "amount_overflow",
        ),
        ("1000", "USD", "2030-01-17T00:00:00", "currency_unsupported"),
        ("1000", "RUB", "2030-02-17T00:00:00", "posted_date_outside_range"),
        ("-1000", "RUB", "2030-01-17T00:00:00", "candidate_direction_invalid"),
    ],
)
def test_invalid_amount_currency_date_cannot_be_candidate(
    database, amount, currency, posted, reason
):
    root = ET.fromstring(original(coupons=(amount,)))
    coupon = root.find(f".//m:comment[@comment='{COUPON}']", NS)
    coupon.find(".//m:p_code[@volume]", NS).set("p_code", currency)
    root.find(".//m:settlement_date", NS).set("settlement_date", posted)
    xml = ET.tostring(root)
    import_id, account_id = accept(database, xml)
    result = read(database, import_id, account_id, xml)
    row = result.observations[2]
    assert row.candidate_kind == "unsupported" and reason in row.reasons
    assert "coupon_paid_candidate" not in result.source_subtotals


@pytest.mark.parametrize(
    "operation,narrative",
    [
        ("перевод", COUPON),
        ("Other", COUPON),
        ("Перевод", "prefix " + COUPON),
        ("Перевод", COUPON + " suffix"),
        ("Перевод", COUPON.replace("16.01.2030", "31.02.2030")),
        ("Перевод", "погашение купона "),
        ("Перевод", "из АО "),
        ("Перевод", "Synthetic dividend"),
        ("НКД по сделке 10000000001", "Synthetic"),
    ],
)
def test_no_substring_synonym_dividend_or_invented_nkd_id(database, operation, narrative):
    root = ET.fromstring(original(coupons=("1000",)))
    op = root.find(f".//m:oper_type/m:comment[@comment='{COUPON}']/..", NS)
    op.set("oper_type", operation)
    op.find("m:comment", NS).set("comment", narrative)
    xml = ET.tostring(root)
    import_id, account_id = accept(database, xml)
    row = read(database, import_id, account_id, xml).observations[2]
    assert row.candidate_kind == "unsupported" and "source_pattern_unproven" in row.reasons


@pytest.mark.parametrize(
    "field,value",
    [
        ("ordinal", 99),
        ("amount", "999"),
        ("source_account", "9999999"),
        ("currency", "USD"),
        ("date", "2030-01-19"),
    ],
)
def test_mismatched_saved_s1_occurrence_refuses_original_interpretation(database, field, value):
    xml = original()
    import_id, account_id = accept(database, xml)
    with database.session_factory() as session:
        source = session.get(MyBrokerImport, import_id)
        stored = json.loads(source.normalized_json)
        stored["money"][2][field] = value
        source.normalized_json = canonical(stored)
        session.commit()
    with pytest.raises(MyBrokerError, match="^money_original_s1_mismatch$"):
        read(database, import_id, account_id, xml)


def test_changed_original_wrong_range_and_malformed_original_are_sanitized(database):
    xml = original()
    import_id, account_id = accept(database, xml)
    for changed, filename, code in [
        (
            xml.replace(b"SYNTHETIC-TOKEN", b"CHANGED-PRIVATE-TOKEN"),
            FILENAME,
            "money_original_s1_mismatch",
        ),
        (xml, FILENAME.replace("01.01.30", "02.01.30"), "money_original_s1_mismatch"),
        (b"<broken Synthetic-private-text", FILENAME, "xml_invalid"),
        (xml.replace(b"MyBroker", b"OtherNamespace"), FILENAME, "family_unsupported"),
    ]:
        with pytest.raises(MyBrokerError) as error:
            read(database, import_id, account_id, changed, filename)
        assert str(error.value) == code


def test_mapping_withdrawal_does_not_hide_candidates_or_overlap_inventory(database):
    xml = original()
    import_id, account_id = accept(database, xml)
    with database.session_factory() as session:
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(BrokerIdentityMapping.provider_identity == ACCOUNT)
        )
        revoke_mapping(session, mapping.id)
    result = read(database, import_id, account_id, xml)
    assert len(result.observations) == 6
    assert all(r.candidate_kind == "unsupported" for r in result.observations)
    assert "row_account_binding_unproven" in result.exceptions


def test_full_overlap_inventory_and_missing_competing_occurrence_no_economic_sum(database):
    xml = original()
    import_id, account_id = accept(database, xml)
    overlapping = original(coupons=("1000",))
    other_id, _ = accept(database, overlapping)
    result = read(database, import_id, account_id, xml)
    assert len(result.observations) == 6 and len(result.overlapping_sources) == 1
    overlap = result.overlapping_sources[0]
    assert overlap.import_id == other_id and len(overlap.occurrences) == 5
    assert len(result.observations[2].competing_occurrences) == 1
    assert "overlapping_source_event_missing" in result.observations[3].reasons
    assert result.source_subtotals["coupon_paid_candidate"] == "3000"
    assert all(r.economic_event_id is None for r in result.observations)


def test_settlement_precedence_cannot_be_overridden_by_candidate_operation(database):
    root = ET.fromstring(original())
    op = root.find(".//m:oper_type", NS)
    op.set("oper_type", "НКД по сделке")
    xml = ET.tostring(root)
    import_id, account_id = accept(database, xml)
    row = read(database, import_id, account_id, xml).observations[0]
    assert row.s1_kind == "settlement" and row.candidate_kind == "unsupported"
    assert row.trade_identity is not None


@pytest.mark.parametrize("alias", [ACCOUNT, "1234567"])
def test_each_account_alias_must_keep_its_accepted_binding(database, alias):
    xml = original()
    import_id, account_id = accept(database, xml)
    with database.session_factory() as session:
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(BrokerIdentityMapping.provider_identity == alias)
        )
        revoke_mapping(session, mapping.id)
    result = read(database, import_id, account_id, xml)
    assert all(r.candidate_kind == "unsupported" for r in result.observations)
    expected = (
        "row_account_binding_unproven" if alias == ACCOUNT else "filename_account_binding_unproven"
    )
    assert expected in result.exceptions


def test_positive_nkd_and_wrong_selected_account_remain_unsupported(database):
    root = ET.fromstring(original())
    op = root.find(".//m:oper_type[@oper_type='НКД по сделке']", NS)
    op.find(".//m:p_code[@volume]", NS).set("volume", "125.50")
    xml = ET.tostring(root)
    import_id, account_id = accept(database, xml)
    result = read(database, import_id, account_id, xml)
    assert result.observations[-1].candidate_kind == "unsupported"
    assert "candidate_direction_invalid" in result.observations[-1].reasons
    wrong = read(database, import_id, -1, xml)
    assert "selected_account_unavailable" in wrong.exceptions
    assert all(r.candidate_kind == "unsupported" for r in wrong.observations)


@pytest.mark.parametrize(
    "amount,minor", [("92233720368547758.07", 2**63 - 1), ("-92233720368547758.08", -(2**63))]
)
def test_exact_signed_64_bit_bounds_do_not_round(database, amount, minor):
    root = ET.fromstring(original(coupons=(amount,)))
    if minor < 0:
        root.find(f".//m:comment[@comment='{COUPON}']/..", NS).set("oper_type", "НКД по сделке")
    xml = ET.tostring(root)
    import_id, account_id = accept(database, xml)
    row = read(database, import_id, account_id, xml).observations[2]
    assert row.amount_minor == minor and row.candidate_kind != "unsupported"
