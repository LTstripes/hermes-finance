"""Synthetic monthly source-account estimates; no Owner sources or finance writes."""

import calendar
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
from astra_hunt_runner import CASES as ASTRA_CASES
from astra_hunt_runner import ROOT as ASTRA_ROOT
from astra_hunt_runner import replay as astra_replay
from test_statement_import_broker_statement_provisional import (
    _finite_tables,
    provisional_xml,
)
from test_statement_import_mybroker import ACCOUNT

from hermes_finance.domain.broker_statement_provisional import (
    ProvisionalAssumptions,
    ProvisionalChoice,
)
from hermes_finance.persistence import Base
from hermes_finance.services import source_intake
from hermes_finance.services.source_monthly_returns import read_monthly_returns


@pytest.fixture
def db(tmp_path, source_returns_database_factory):
    database = source_returns_database_factory(tmp_path)
    yield database
    database.engine.dispose()


def save_month(
    db,
    month=4,
    *,
    beginning="9000",
    closing="10211",
    extra=(),
    candidate_count=1,
    marker=None,
    missing_closing=False,
    money_currency=None,
    filename=None,
):
    xml = provisional_xml(
        beginning=beginning,
        closing=closing,
        extra_money=extra,
        candidate_count=candidate_count,
        missing_closing=missing_closing,
    )
    xml = (
        xml.decode()
        .replace("2030-04-", f"2030-{month:02d}-")
        .replace(".04.2030", f".{month:02d}.2030")
        .encode()
    )
    if marker or money_currency:
        root = ET.fromstring(xml)
        if marker:
            root.set("synthetic_marker", marker)
        if money_currency:
            for row in root.findall(".//{MyBroker}p_code[@volume]"):
                row.set("p_code", money_currency)
        xml = ET.tostring(root, encoding="utf-8")
    end = calendar.monthrange(2030, month)[1]
    filename = filename or f"Брокерский 1234567 (01.{month:02d}.30-{end}.{month:02d}.30).xml"
    with db.session_factory() as session:
        ack = source_intake.save_intake(
            session, document=xml, filename=filename, request_id=f"save-{month}-{marker}"
        )
    return ack["intake_id"], (xml, filename)


def read(db, originals=None, assumptions=None, source_account=ACCOUNT):
    with db.session_factory() as session:
        return read_monthly_returns(
            session, source_account=source_account, originals=originals, assumptions=assumptions
        )


def snapshot(db):
    with db.engine.connect() as connection:
        return {
            table.name: connection.exec_driver_sql(
                f'SELECT * FROM "{table.name}" ORDER BY rowid'
            ).fetchall()
            for table in Base.metadata.sorted_tables
        }


def service_structure_xml(raw, *, summary_variant=1):
    """Fabricated values on the inventoried service paths; no summary is an event."""
    from copy import deepcopy

    from test_statement_import_mybroker_endpoints import draft_structure_xml
    from test_statement_import_mybroker_metadata import metadata_xml

    n = "{MyBroker}"
    root = ET.fromstring(metadata_xml(raw))
    root.set("Textbox6", "Уполномоченное лицо")
    donor = ET.fromstring(draft_structure_xml(summary_variant=summary_variant))
    root.find(n + "Positions/" + n + "Report").append(
        deepcopy(donor.find(n + "Positions/" + n + "Report/" + n + "Tablix3"))
    )
    report = root.find(n + "Trades2/" + n + "Report")
    controls = donor.find(n + "Trades2/" + n + "Report")
    for child in controls:
        if child.tag != n + "Tablix1":
            report.append(deepcopy(child))
    table = report.find(n + "Tablix1")
    table.append(deepcopy(controls.find(n + "Tablix1/" + n + "Textbox116")))
    daily = controls.find(".//" + n + "comment")
    for group in table.findall(n + "settlement_date_Collection/" + n + "settlement_date"):
        rows = group.findall(n + "rn_Collection/" + n + "rn")
        for index, row in enumerate(rows):
            comment = row.find(n + "oper_type/" + n + "comment")
            for tag in ("Textbox95", "Textbox93"):
                display = deepcopy(daily.find(n + tag))
                if index < len(rows) - 1:
                    for scalar in display.iter():
                        for key in scalar.attrib:
                            scalar.set(key, "")
                comment.append(display)
            comment[:] = [
                comment.find(n + tag)
                for tag in ("money_volume_begin1_Collection", "Textbox95", "Textbox93", "Textbox11")
            ]
    report[:] = [
        report.find(n + tag)
        for tag in ("Tablix2", "Tablix1", "Tablix3", "Tablix5", "Tablix4", "Tablix6", "Tablix7")
    ]
    return ET.tostring(root, encoding="utf-8")


def save_service_month(db, month=4, *, mutate=None, summary_variant=1, row_account=ACCOUNT):
    raw = provisional_xml(
        beginning=str(9000 + (month - 4) * 1000),
        closing=str(10000 + (month - 4) * 1000),
        candidate_count=0,
        extra_money=(
            ("Внесено по распоряжению Клиента", "Synthetic funding", "500"),
            ("Выведено по распоряжению Клиента", "Synthetic withdrawal", "-100"),
            ("Перевод", "Погашение купона Synthetic stock", "12.34"),
            ("Перевод", "Дивиденды Synthetic stock", "5.66"),
        ),
    )
    root = ET.fromstring(service_structure_xml(raw, summary_variant=summary_variant))
    if mutate:
        mutate(root)
    raw = (
        ET.tostring(root, encoding="utf-8")
        .decode()
        .replace("2030-04-", f"2030-{month:02d}-")
        .replace(".04.2030", f".{month:02d}.2030")
        .replace(ACCOUNT, row_account)
        .encode()
    )
    end = calendar.monthrange(2030, month)[1]
    filename = f"Брокерский 1234567 (01.{month:02d}.30-{end}.{month:02d}.30) (1).xml"
    with db.session_factory() as session:
        ack = source_intake.save_intake(
            session, document=raw, filename=filename, request_id=f"service-{month}"
        )
    return ack["intake_id"], (raw, filename)


def test_filename_alias_uses_single_document_row_scope_and_does_not_write(db):
    save_month(db, candidate_count=0, extra=(("Купон", "Synthetic stock", "12.34"),))
    before = snapshot(db)
    native = read(db)
    alias = read(db, source_account="1234567")
    assert alias.months == native.months
    assert alias.flows == native.flows
    assert alias.months[0].coupons_kopecks == 1234
    assert alias.months[0].dividends_kopecks == 0
    assert not alias.gaps
    assert snapshot(db) == before


def test_filename_alias_conflicting_single_row_accounts_across_documents(db):
    save_service_month(db)
    save_service_month(db, 5, row_account="7654321-000")
    result = read(db, source_account="1234567")
    assert len(result.months) == 2
    assert "native_source_scope_ambiguous" in {gap.code for gap in result.gaps}
    for row in result.months:
        assert row.result.opening_kopecks is None
        assert row.result.contributions_kopecks is None
        assert row.coupons_kopecks is row.dividends_kopecks is None
    assert read(db).months[0].result.modified_dietz_return is not None


def test_multi_account_document_never_maps_filename_alias_or_returns_zero_income(db):
    def mutate(root):
        root.find(".//{MyBroker}Textbox11").set("acc_code", "7654321-000")

    save_service_month(db, mutate=mutate)
    for alias in (ACCOUNT, "1234567", "7654321-000"):
        result = read(db, source_account=alias)
        assert result.months[0].coupons_kopecks is None
        assert result.months[0].dividends_kopecks is None
        assert result.months[0].result.growth_kopecks is None
        assert "native_source_scope_ambiguous" in {gap.code for gap in result.gaps}
    assert read(db, source_account="1234567-001").months == ()


@pytest.mark.parametrize("summary_variant", range(4))
def test_exact_service_inventory_is_recomputed_without_changing_frozen_source(db, summary_variant):
    from hermes_finance.statement_import.mybroker_return_structure import source_return_blockers

    intake, original = save_service_month(db, summary_variant=summary_variant)
    before = snapshot(db)
    with db.session_factory() as session:
        view = source_intake.read_intake(session, intake)
        assert set(view["document"]["syntax_blockers"]) == {
            "unparsed_source_rows",
            "4_Transfers_unsupported",
            "5_UFSR_unsupported",
        }
        assert source_return_blockers(view) == set()
        assert source_return_blockers({**view, "observations": []}) == set(
            view["document"]["syntax_blockers"]
        )
    row = read(db, source_account="1234567").months[0]
    assert row.result.contributions_kopecks == 50_000
    assert row.result.withdrawals_kopecks == 10_000
    assert row.result.growth_kopecks == 60_000
    assert row.coupons_kopecks == 1234 and row.dividends_kopecks == 566
    assert row.result.modified_dietz_return is not None
    assert not row.flags
    assert snapshot(db) == before
    # Explicit re-save remains compatible with the unchanged frozen manifest.
    with db.session_factory() as session:
        source_intake.save_intake(
            session, document=original[0], filename=original[1], request_id="re-save-service"
        )
    # Re-save is intentional; the preceding reads themselves made no writes.
    after = snapshot(db)
    assert before["source_intake_observations"] == after["source_intake_observations"]


@pytest.mark.parametrize(
    "path",
    [
        "Positions/Report/Tablix3/Details1_Collection/Details1",
        "Trades2/Report/Tablix2",
        "Trades2/Report/Tablix3",
        "Trades2/Report/Tablix1/settlement_date_Collection/settlement_date/rn_Collection/rn/oper_type/comment/Textbox95",
        "Trades2/Report/Tablix1/Textbox116",
        "Trades2/Report/Tablix7",
        "Trades3/Report/Tablix1",
        "Trades4/Report/Tablix1/Details_Collection/Details",
    ],
)
@pytest.mark.parametrize("change", ["attribute", "child", "foreign_child", "text"])
def test_service_exceptions_never_hide_unknown_content(db, path, change):
    def mutate(root):
        node = root.find("/".join("{MyBroker}" + part for part in path.split("/")))
        if change == "attribute":
            node.set("unrecognized", "0")
        elif change == "text":
            node.text = "Synthetic hidden content"
        else:
            ET.SubElement(node, "{MyBroker}Details" if change == "child" else "{Other}Details")

    save_service_month(db, mutate=mutate)
    result = read(db, source_account="1234567")
    assert result.months[0].result.contributions_kopecks is None
    assert result.months[0].result.modified_dietz_return is None
    assert {"unparsed_source_rows", "4_Transfers_unsupported", "5_UFSR_unsupported"} & {
        gap.code for gap in result.gaps
    }


def test_monthly_api_three_service_reports_have_numbers_and_missing_months_stay_gaps(db):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    for month in (4, 5, 7):
        save_service_month(db, month)
    before = snapshot(db)
    client = TestClient(create_app(database=db))
    body = client.get("/api/source-returns/monthly", params={"source_account": "1234567"}).json()
    assert len(body["months"]) == 4
    fields = (
        "opening_kopecks",
        "closing_kopecks",
        "contributions_kopecks",
        "withdrawals_kopecks",
        "growth_kopecks",
        "modified_dietz_return",
        "coupons_kopecks",
        "dividends_kopecks",
    )
    for row in (body["months"][0], body["months"][1], body["months"][3]):
        assert all(row[field] is not None for field in fields)
        assert not row["flags"]
    gap = body["months"][2]
    assert all(gap[field] is None for field in fields)
    assert {"missing_endpoint", "unknown_flow", "flow_coverage_gap"} <= set(gap["flags"])
    assert body["period"]["chained_return"] is None
    assert len(body["flows"]) == 6  # summaries never duplicate the six external flows
    assert snapshot(db) == before


def test_monthly_api_three_contiguous_service_reports_chain_known_flows(db):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    for month in (4, 5, 6):
        save_service_month(db, month)
    before = snapshot(db)
    body = (
        TestClient(create_app(database=db))
        .get("/api/source-returns/monthly", params={"source_account": "1234567"})
        .json()
    )
    assert len(body["months"]) == 3
    for row in body["months"]:
        assert not row["flags"]
        assert row["contributions_kopecks"] == 50_000
        assert row["withdrawals_kopecks"] == 10_000
        assert row["growth_kopecks"] == 60_000
        assert row["modified_dietz_return"] is not None
        assert row["coupons_kopecks"] == 1234
        assert row["dividends_kopecks"] == 566
    assert body["period"]["contributions_kopecks"] == 150_000
    assert body["period"]["withdrawals_kopecks"] == 30_000
    assert body["period"]["growth_kopecks"] == 180_000
    assert body["period"]["chained_return"] is not None
    assert len(body["segments"]) == 1 and not body["segments"][0]["partial_segment"]
    assert snapshot(db) == before


@pytest.mark.parametrize("extra", [False, True])
def test_service_projection_retains_pending_rows_and_only_known_pending_captions(db, extra):
    from test_statement_import_mybroker import fixture

    from hermes_finance.statement_import.mybroker_return_structure import source_return_blockers

    def mutate(root):
        n = "{MyBroker}"
        pending = ET.fromstring(fixture(pending=True)).find(
            n + "Trades/" + n + "Report/" + n + "Tablix3"
        )
        row = pending.find(".//" + n + "Details2")
        row.attrib.update(
            p_name2="Synthetic security", Textbox16="RUB", place_name2="Synthetic place"
        )
        if extra:
            row.set("unknown_native_key", "0")
        root.find(n + "Trades/" + n + "Report").append(pending)

    intake, _ = save_service_month(db, mutate=mutate)
    with db.session_factory() as session:
        view = source_intake.read_intake(session, intake)
        assert len(view["document"]["trades"]) == 2
        assert bool(source_return_blockers(view)) is extra


@pytest.mark.parametrize(
    "change",
    [
        "summary_label",
        "currency_label",
        "duplicate",
        "order",
        "moved",
        "daily_empty",
        "daily_early_value",
        "connection_end",
    ],
)
def test_service_projection_rejects_inexact_known_shapes(db, change):
    from copy import deepcopy

    def mutate(root):
        n = "{MyBroker}"
        report = root.find(n + "Trades2/" + n + "Report")
        if change == "summary_label":
            report.find(".//" + n + "oper_group").set("oper_group", "Synthetic unsupported group")
        elif change == "currency_label":
            report.find(".//" + n + "p_code6").set("p_code6", "USD")
        elif change == "duplicate":
            report.append(deepcopy(report.find(n + "Tablix7")))
        elif change == "order":
            report[:] = list(reversed(report[:]))
        elif change == "moved":
            summary = report.find(n + "Tablix7")
            report.remove(summary)
            report.find(n + "Tablix1").append(summary)
        elif change.startswith("daily_"):
            displays = report.findall(".//" + n + "comment/" + n + "Textbox95/" + n + "Textbox83")
            displays[-1 if change == "daily_empty" else 0].set(
                "money_volume", "" if change == "daily_empty" else "1.00"
            )
        else:
            root.find(n + "Trades4/.//" + n + "Details").set("sys_end_time", "Synthetic end")

    save_service_month(db, mutate=mutate)
    row = read(db, source_account="1234567").months[0]
    assert row.result.growth_kopecks is None
    assert row.coupons_kopecks is row.dividends_kopecks is None


def test_saved_months_own_endpoints_seam_and_missing_month(db):
    april, apr = save_month(db)
    may, may_original = save_month(db, 5, beginning="11000", closing="12000", candidate_count=0)
    july, jul = save_month(
        db,
        7,
        beginning="13000",
        closing="14000",
        candidate_count=0,
        extra=(("Unknown", "Synthetic unknown", "17"),),
    )
    before = snapshot(db)
    result = read(db, {april: apr, may: may_original, july: jul})
    assert len(result.months) == 4
    a, m, missing, j = result.months
    assert a.result.opening_kopecks == 1_000_000
    assert a.result.closing_kopecks == 1_121_100
    assert a.result.contributions_kopecks == 100_000
    assert a.result.growth_kopecks == 21_100
    expected = Decimal(21100 * 30) / Decimal(1000000 * 30 + 100000 * 15)
    assert abs(a.result.modified_dietz_return - expected) < Decimal("1e-28")
    assert m.result.opening_kopecks == 1_200_000
    assert m.previous_closing_kopecks == 1_121_100
    assert "seam_mismatch" in m.flags
    assert missing.result.opening_date == date(2030, 5, 31)
    assert missing.result.missing_endpoint
    assert missing.result.modified_dietz_return is None
    assert j.result.modified_dietz_return is None
    assert "unknown_flow" in j.result.reason_codes
    assert result.period.chained_return is None
    assert result.period.growth_kopecks is None
    assert result.period.xirr_period_return is None
    assert len(result.flows) == 1 and result.flows[0].status == "assumed"
    assert result.defaults_applied == result.flows
    assert "unrecognized_money" in {gap.code for gap in result.gaps}
    assert snapshot(db) == before
    assert all(count == 0 for count in _finite_tables(db).values())


def test_saved_v1_money_is_gap_without_reattached_original(db, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(source_intake, "persist_money_classifications", lambda *args: None)
        save_month(db)
    result = read(db)
    assert result.months[0].result.opening_kopecks == 1_000_000
    assert result.flows == ()
    assert result.defaults_applied == ()
    assert "classification_missing_legacy_intake" in {gap.code for gap in result.gaps}
    assert not result.period.assumptions_used
    assert result.months[0].result.modified_dietz_return is None
    assert result.period.growth_kopecks is None


def test_explicit_existing_choices_override_defaults(db):
    intake, original = save_month(db)
    initial = read(db, {intake: original})
    reference = initial.flows[0].source_references[0]
    _, _, _, ordinal, fingerprint = reference.split(":")
    choice = ProvisionalChoice(
        requirement_id=f"candidate:{ordinal}:{fingerprint[:12]}",
        source_references=(reference,),
        choice="exclude_from_external_schedule",
    )
    assumptions = ProvisionalAssumptions(schedule_mode="explicit_empty", selections=(choice,))
    result = read(db, {intake: original}, {intake: assumptions})
    assert result.flows[0].status == "confirmed"
    assert not result.flows[0].included
    assert not result.defaults_applied
    assert result.months[0].result.contributions_kopecks == 0
    assert result.months[0].result.growth_kopecks == 121_100
    included = choice.model_copy(update={"choice": "include_as_account_inflow"})
    result = read(
        db,
        {intake: original},
        {
            intake: assumptions.model_copy(
                update={"schedule_mode": "dated", "selections": (included,)}
            )
        },
    )
    assert result.flows[0].status == "confirmed" and result.flows[0].included
    assert result.months[0].result.contributions_kopecks == 100_000


def test_overlapping_originals_deduplicate_preserving_same_report_multiplicity(db):
    one, first = save_month(db, candidate_count=2)
    two, second = save_month(db, candidate_count=2, marker="overlap")
    result = read(db, {one: first, two: second})
    assert len(result.flows) == 2
    assert all(len(flow.source_references) == 2 for flow in result.flows)
    assert result.months[0].result.contributions_kopecks == 200_000
    assert "overlap_flow_deduplicated" in {gap.code for gap in result.gaps}


def test_internal_income_and_withdrawal_classification(db):
    intake, original = save_month(
        db,
        candidate_count=0,
        extra=(
            ("Внесено по распоряжению Клиента", "Synthetic funding", "500"),
            ("Выведено по распоряжению Клиента", "Synthetic withdrawal", "-200"),
            ("Дивиденды", "Synthetic income", "30"),
        ),
    )
    result = read(db, {intake: original})
    assert [flow.amount_kopecks for flow in result.flows] == [50_000, -20_000]
    assert result.months[0].result.contributions_kopecks == 50_000
    assert result.months[0].result.withdrawals_kopecks == 20_000
    assert result.months[0].result.growth_kopecks == 91_100
    assert not result.gaps


def test_bad_original_only_blocks_its_month(db):
    april, original = save_month(db)
    may, valid = save_month(db, 5, beginning="10211", candidate_count=0)
    before = snapshot(db)
    result = read(db, {april: (b"wrong", original[1]), may: valid})
    assert result.months[0].result.missing_endpoint
    assert result.months[1].result.modified_dietz_return is not None
    assert "source_reader_unavailable" in {gap.code for gap in result.gaps}
    assert snapshot(db) == before


def test_bad_endpoint_and_other_account_never_become_zero(db):
    intake, original = save_month(db, missing_closing=True)
    result = read(db, {intake: original})
    assert result.months[0].result.closing_kopecks is None
    assert result.months[0].result.modified_dietz_return is None
    other = read(db, source_account="unrelated-native-account")
    assert other.months == ()
    assert other.period.growth_kopecks is None


def test_get_router_decimal_strings_integer_kopecks_and_gaps(db):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    save_month(db)
    before = snapshot(db)
    client = TestClient(create_app(database=db))
    response = client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["source_account"] == ACCOUNT
    assert body["financial_authority"] == "none"
    assert body["approximate"] is True
    row = body["months"][0]
    assert type(row["opening_kopecks"]) is int
    assert row["opening_kopecks"] == 1_000_000
    assert isinstance(row["modified_dietz_return"], str)
    assert isinstance(body["period"]["chained_return"], str)
    assert body["flows"][0]["amount_kopecks"] == 100_000
    assert body["flows"][0]["status"] == "assumed"
    assert not body["gaps"]
    assert snapshot(db) == before
    assert client.get("/api/source-returns/monthly").status_code == 422
    assert (
        client.get("/api/source-returns/monthly", params={"source_account": ""}).status_code == 422
    )
    empty = client.get("/api/source-returns/monthly", params={"source_account": "other"})
    assert empty.status_code == 200 and empty.json()["months"] == []


def test_api_available_rates_are_decimal_strings(db):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    save_month(db, candidate_count=0)
    body = (
        TestClient(create_app(database=db))
        .get("/api/source-returns/monthly", params={"source_account": ACCOUNT})
        .json()
    )
    assert isinstance(body["months"][0]["modified_dietz_return"], str)
    assert isinstance(body["period"]["chained_return"], str)
    assert isinstance(body["period"]["xirr_period_return"], str)
    assert Decimal(body["months"][0]["modified_dietz_return"]) == Decimal("0.1211")


def test_missing_statement_blocks_period_flows_but_preserves_independent_segments(db):
    april, apr = save_month(db, beginning="9000", closing="9000", candidate_count=0)
    june, jun = save_month(db, 6, beginning="19000", closing="19000", candidate_count=0)
    result = read(db, {april: apr, june: jun})
    assert result.months[1].result.missing_endpoint
    assert result.period.chained_return is None
    assert result.period.growth_kopecks is None
    assert result.period.contributions_kopecks is result.period.withdrawals_kopecks is None
    assert result.period.xirr_period_return is result.period.xirr_annualized_return is None
    for reasons in (result.period.growth_reason_codes, result.period.xirr_reason_codes):
        assert "flow_coverage_gap" in reasons and "unknown_flow" in reasons
    assert result.period.missing_endpoint
    assert len(result.segments) == 2
    for segment in result.segments:
        assert segment.growth_kopecks == 0
        assert segment.contributions_kopecks == segment.withdrawals_kopecks == 0
        assert segment.xirr_period_return == 0
    assert result.months[1].result.contributions_kopecks is None


def test_overlap_conflicting_endpoints_are_missing_not_arbitrarily_selected(db):
    one, first = save_month(db, candidate_count=0)
    two, second = save_month(db, candidate_count=0, marker="conflict", closing="20000")
    result = read(db, {one: first, two: second})
    assert result.months[0].result.opening_kopecks == 1_000_000
    assert result.months[0].result.closing_kopecks is None
    assert "overlapping_endpoint_conflict" in {gap.code for gap in result.gaps}


def test_bank_outgoing_and_coupon_are_not_double_counted(db):
    intake, original = save_month(db, extra=(("Перевод", "в АО Synthetic bank", "-100"),))
    result = read(db, {intake: original})
    assert result.months[0].result.contributions_kopecks == 100_000
    assert result.months[0].result.withdrawals_kopecks == 10_000
    assert {flow.classification for flow in result.flows} == {
        "external_deposit",
        "external_withdrawal",
    }


def test_seam_mismatch_chain_uses_months_own_opening(db):
    from decimal import ROUND_HALF_UP, localcontext

    april, apr = save_month(db, candidate_count=0)
    may, may_xml = save_month(db, 5, beginning="11000", closing="13000", candidate_count=0)
    result = read(db, {april: apr, may: may_xml})
    assert "seam_mismatch" in result.months[1].flags
    assert result.months[1].result.growth_kopecks == 200_000
    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_UP
        expected = (1 + result.months[0].result.modified_dietz_return) * (
            1 + Decimal(200_000) / Decimal(1_200_000)
        ) - 1
    assert result.period.chained_return == expected
    assert result.period.growth_kopecks == 400_000


def test_stale_choice_membership_is_not_confirmation(db):
    intake, original = save_month(db)
    flow = read(db, {intake: original}).flows[0]
    reference = flow.source_references[0]
    _, _, _, ordinal, fingerprint = reference.split(":")
    choice = ProvisionalChoice(
        requirement_id=f"candidate:{ordinal}:{fingerprint[:12]}",
        source_references=("wrong-reference",),
        choice="include_as_account_inflow",
    )
    assumptions = ProvisionalAssumptions(schedule_mode="dated", selections=(choice,))
    result = read(db, {intake: original}, {intake: assumptions})
    assert result.flows[0].status == "assumed"
    assert "invalid_assumption_choice" in {gap.code for gap in result.gaps}
    assert result.months[0].result.modified_dietz_return is None


def test_long_report_does_not_invent_intermediate_month_end(db):
    xml = provisional_xml(candidate_count=0)
    filename = "Брокерский 1234567 (01.04.30-30.06.30).xml"
    with db.session_factory() as session:
        source_intake.save_intake(
            session, document=xml, filename=filename, request_id="long-report"
        )
    result = read(db)
    assert len(result.months) == 3
    assert result.months[0].result.opening_kopecks == 1_000_000
    assert result.months[0].result.closing_kopecks is None
    assert result.months[1].result.opening_kopecks is None
    assert result.months[1].result.closing_kopecks is None
    assert result.months[2].result.opening_kopecks is None
    assert result.months[2].result.closing_kopecks == 1_121_100
    assert result.period.growth_kopecks == 121_100
    assert result.period.xirr_period_return is not None
    assert len(result.segments) == 1
    segment = result.segments[0]
    assert (segment.start, segment.end) == (date(2030, 3, 31), date(2030, 6, 30))
    assert segment.partial_segment
    assert segment.chained_return is None
    assert segment.chain_reason_codes == ("missing_endpoint",)
    assert {key: asdict(segment)[key] for key in asdict(result.period)} == asdict(result.period)


def test_combined_native_client_operation_uses_signed_amount(db):
    intake, original = save_month(
        db,
        candidate_count=0,
        extra=(
            ("Внесено/Выведено по распоряжению Клиента", "Synthetic inbound", "500"),
            ("Внесено/Выведено по распоряжению Клиента", "Synthetic outbound", "-200"),
        ),
    )
    result = read(db, {intake: original})
    assert result.months[0].result.contributions_kopecks == 50_000
    assert result.months[0].result.withdrawals_kopecks == 20_000
    assert {flow.status for flow in result.flows} == {"assumed"}


def test_segments_split_missing_month_and_keep_own_endpoints_and_flows(db):
    from decimal import ROUND_HALF_UP, localcontext

    april, apr = save_month(db)
    may, may_xml = save_month(db, 5, beginning="11000", closing="13000", candidate_count=0)
    july, jul = save_month(
        db,
        7,
        beginning="14000",
        closing="15000",
        candidate_count=0,
        extra=(("Выведено по распоряжению Клиента", "Synthetic withdrawal", "-500"),),
    )
    before = snapshot(db)
    result = read(db, {april: apr, may: may_xml, july: jul})
    first, second = result.segments
    assert (first.start, first.end) == (date(2030, 3, 31), date(2030, 5, 31))
    assert (second.start, second.end) == (date(2030, 6, 30), date(2030, 7, 31))
    assert first.partial_segment and second.partial_segment
    assert first.contributions_kopecks == 100_000
    assert first.withdrawals_kopecks == 0
    assert first.growth_kopecks == 300_000
    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_UP
        expected = (1 + result.months[0].result.modified_dietz_return) * (
            1 + Decimal(200_000) / Decimal(1_200_000)
        ) - 1
    assert first.chained_return == expected
    assert second.contributions_kopecks == 0
    assert second.withdrawals_kopecks == 50_000
    assert second.growth_kopecks == 150_000
    assert abs(second.chained_return - result.months[-1].result.modified_dietz_return) < Decimal(
        "1e-58"
    )
    assert all(segment.xirr_annualized_return is not None for segment in result.segments)
    assert all(segment.xirr_period_return is not None for segment in result.segments)
    assert result.period.chained_return is None
    assert snapshot(db) == before


def test_api_segments_complete_partial_endpoint_and_unknown_flows(db):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    save_month(db, candidate_count=0)
    client = TestClient(create_app(database=db))
    body = client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT}).json()
    segment = body["segments"][0]
    assert segment["start"] == "2030-03-31" and segment["end"] == "2030-04-30"
    assert segment["partial_segment"] is False
    assert type(segment["growth_kopecks"]) is int
    for field in ("chained_return", "xirr_annualized_return", "xirr_period_return"):
        assert isinstance(segment[field], str)
        assert segment[field] == body["period"][field]
    save_month(db, 5, candidate_count=0, missing_closing=True)
    body = client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT}).json()
    assert len(body["segments"]) == 1
    assert body["segments"][0]["partial_segment"] is True
    save_month(db, 6, extra=(("Unknown", "Synthetic unknown", "17"),))
    body = client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT}).json()
    assert len(body["segments"]) == 2
    segment = body["segments"][1]
    assert segment["start"] == "2030-05-31" and segment["end"] == "2030-06-30"
    assert segment["partial_segment"] is True
    for field in (
        "contributions_kopecks",
        "withdrawals_kopecks",
        "growth_kopecks",
        "chained_return",
        "xirr_annualized_return",
        "xirr_period_return",
    ):
        assert segment[field] is None
    assert "unknown_flow" in segment["chain_reason_codes"]
    empty = client.get("/api/source-returns/monthly", params={"source_account": "other"}).json()
    assert empty["segments"] == []


@pytest.mark.parametrize("failure", ["unreadable", "ambiguous"])
@pytest.mark.parametrize("coverage", ["interior", "long"])
def test_unknown_source_flows_block_covered_metrics_and_keep_independent_months(
    db, monkeypatch, failure, coverage
):
    april, apr = save_month(db, beginning="8000", candidate_count=0)
    may, may_xml = save_month(
        db,
        5,
        beginning="9211",
        closing="14211",
        candidate_count=0,
        extra=(("Внесено по распоряжению Клиента", "Synthetic funding", "5000"),),
    )
    june, jun = save_month(db, 6, beginning="14211", closing="16711", candidate_count=0)
    originals = {april: apr, may: may_xml, june: jun}
    intact = read(db, originals)
    assert intact.period.contributions_kopecks == 500_000
    assert intact.period.growth_kopecks == 371_100
    assert intact.period.xirr_period_return is not None
    if coverage == "long":
        xml = provisional_xml(beginning="8000", closing="16711", candidate_count=0)
        filename = "Брокерский 1234567 (01.04.30-30.06.30).xml"
        with db.session_factory() as session:
            ack = source_intake.save_intake(
                session, document=xml, filename=filename, request_id="long-overlap"
            )
        failed = ack["intake_id"]
        originals[failed] = (xml, filename)
        # An independent month outside the unreadable report must remain usable.
        save_month(db, 7, beginning="16711", closing="17711", candidate_count=0)
        affected = (0, 1, 2)
    else:
        failed = may
        affected = (1,)
    if failure == "unreadable":
        originals[failed] = (b"corrupt synthetic original", originals[failed][1])
        expected_gap = "source_reader_unavailable"
    else:
        from copy import deepcopy

        reader = source_intake.read_intake

        def ambiguous(session, intake_id):
            view = reader(session, intake_id)
            if intake_id == failed:
                view = deepcopy(view)
                view["document"]["positions"][0]["source_account"] = "other-synthetic-account"
            return view

        monkeypatch.setattr(source_intake, "read_intake", ambiguous)
        expected_gap = "native_source_scope_ambiguous"
    before = snapshot(db)
    result = read(db, originals)
    assert expected_gap in {gap.code for gap in result.gaps}
    for index, row in enumerate(result.months):
        if index in affected:
            assert row.result.contributions_kopecks is None
            assert row.result.withdrawals_kopecks is None
            assert row.result.growth_kopecks is None
            assert row.result.modified_dietz_return is None
            assert "unknown_flow" in row.result.reason_codes
        else:
            assert row.result.growth_kopecks is not None
            assert row.result.modified_dietz_return is not None
            assert "unknown_flow" not in row.result.reason_codes
    assert result.period.contributions_kopecks is None
    assert result.period.withdrawals_kopecks is None
    assert result.period.growth_kopecks is None
    assert result.period.chained_return is None
    assert result.period.xirr_annualized_return is None
    assert result.period.xirr_period_return is None
    for reasons in (
        result.period.chain_reason_codes,
        result.period.growth_reason_codes,
        result.period.xirr_reason_codes,
    ):
        assert "unknown_flow" in reasons
    if coverage == "long":
        (segment,) = result.segments
        assert segment.partial_segment
        for field in (
            "contributions_kopecks",
            "withdrawals_kopecks",
            "growth_kopecks",
            "chained_return",
            "xirr_annualized_return",
            "xirr_period_return",
        ):
            assert getattr(segment, field) is None
        assert "unknown_flow" in segment.growth_reason_codes
        assert "unknown_flow" in segment.xirr_reason_codes
    else:
        assert len(result.segments) == 2
        assert all(segment.growth_kopecks is not None for segment in result.segments)
        assert all(segment.xirr_period_return is not None for segment in result.segments)
    assert snapshot(db) == before


def test_unreadable_overlap_blocks_segment_even_with_available_endpoints(db):
    one, _ = save_month(db)
    two, second = save_month(db, marker="unreadable-overlap")
    save_month(db, 5, candidate_count=0)
    result = read(db, {two: (b"corrupt synthetic original", second[1])})
    assert not result.months[0].result.missing_endpoint
    assert result.months[0].result.growth_kopecks is None
    assert result.months[1].result.growth_kopecks is not None
    (segment,) = result.segments
    assert segment.growth_kopecks is None
    assert segment.contributions_kopecks is None
    assert segment.xirr_period_return is None
    assert "unknown_flow" in segment.growth_reason_codes
    assert "unknown_flow" in segment.xirr_reason_codes
    assert one != two


@pytest.mark.parametrize("unknown_flow", [False, True])
def test_api_long_report_segment_retains_outer_metrics_and_flow_blockers(db, unknown_flow):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    extra = (("Unknown", "Synthetic unknown", "17"),) if unknown_flow else ()
    xml = provisional_xml(candidate_count=0, extra_money=extra)
    with db.session_factory() as session:
        source_intake.save_intake(
            session,
            document=xml,
            filename="Брокерский 1234567 (01.04.30-30.06.30).xml",
            request_id="long-api",
        )
    before = snapshot(db)
    response = TestClient(create_app(database=db)).get(
        "/api/source-returns/monthly", params={"source_account": ACCOUNT}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    (segment,) = body["segments"]
    assert segment["partial_segment"]
    assert segment["start"] == "2030-03-31"
    assert segment["end"] == "2030-06-30"
    assert all(row["missing_endpoint"] for row in body["months"])
    assert {key: segment[key] for key in body["period"]} == body["period"]
    assert segment["chained_return"] is None
    if unknown_flow:
        for field in (
            "contributions_kopecks",
            "withdrawals_kopecks",
            "growth_kopecks",
            "xirr_annualized_return",
            "xirr_period_return",
        ):
            assert segment[field] is None
        assert "unknown_flow" in segment["growth_reason_codes"]
        assert "unknown_flow" in segment["xirr_reason_codes"]
    else:
        assert segment["contributions_kopecks"] == 0
        assert segment["growth_kopecks"] == 121_100
        assert isinstance(segment["xirr_period_return"], str)
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "operation,amount",
    [
        ("Внесено по распоряжению Клиента", "500"),
        ("Выведено по распоряжению Клиента", "-200"),
        ("Unknown", "17"),
    ],
)
def test_non_rub_money_blocks_month_period_and_segment_but_not_rub_neighbor(db, operation, amount):
    xml = ET.fromstring(
        provisional_xml(candidate_count=0, extra_money=((operation, "Synthetic USD row", amount),))
    )
    xml.findall(".//{MyBroker}p_code[@volume]")[-1].set("p_code", "USD")
    with db.session_factory() as session:
        source_intake.save_intake(
            session,
            document=ET.tostring(xml, encoding="utf-8"),
            filename="Брокерский 1234567 (01.04.30-30.04.30).xml",
            request_id="usd-money",
        )
    save_month(db, 5, beginning="10211", closing="11211", candidate_count=0)
    before = snapshot(db)
    result = read(db)
    foreign, rub = result.months
    reasons = {"currency_unsupported", "unknown_flow"}
    assert reasons <= set(foreign.flags)
    assert reasons <= set(foreign.result.reason_codes)
    for field in (
        "contributions_kopecks",
        "withdrawals_kopecks",
        "growth_kopecks",
        "modified_dietz_return",
    ):
        assert getattr(foreign.result, field) is None
    assert rub.result.contributions_kopecks == 0
    assert rub.result.growth_kopecks == 100_000
    assert rub.result.modified_dietz_return is not None
    assert not reasons.intersection(rub.flags)
    (segment,) = result.segments
    assert (segment.start, segment.end) == (date(2030, 3, 31), date(2030, 5, 31))
    for totals in (result.period, segment):
        for field in (
            "contributions_kopecks",
            "withdrawals_kopecks",
            "growth_kopecks",
            "chained_return",
            "xirr_annualized_return",
            "xirr_period_return",
        ):
            assert getattr(totals, field) is None
        for field in ("chain_reason_codes", "growth_reason_codes", "xirr_reason_codes"):
            assert reasons <= set(getattr(totals, field))
    assert not result.flows
    assert any(
        gap.code == "currency_unsupported" and gap.month == date(2030, 4, 1) for gap in result.gaps
    )
    assert snapshot(db) == before


@pytest.mark.parametrize("currency", ["RUR", " rur ", " RuB "])
def test_ruble_currency_alias_deposit_counts_as_rub_flow(db, currency):
    save_month(db, money_currency=currency)
    before = snapshot(db)
    result = read(db)
    row = result.months[0]
    assert row.result.contributions_kopecks == 100_000
    assert row.result.growth_kopecks == 21_100
    assert row.result.modified_dietz_return is not None
    assert "currency_unsupported" not in row.flags
    assert "currency_unsupported" not in {gap.code for gap in result.gaps}
    assert len(result.flows) == 1 and result.flows[0].included
    assert snapshot(db) == before
    from hermes_finance.services.source_money_classifications import choose_classification

    with db.session_factory() as session:
        intake = result.flows[0].source_references[0].split(":")[1]
        choose_classification(
            session, int(intake), result.flows[0].source_references[0], "external_deposit"
        )
    confirmed = read(db)
    assert confirmed.flows[0].status == "confirmed"
    assert confirmed.months[0].result.contributions_kopecks == 100_000


def test_currency_gap_in_one_segment_does_not_null_independent_rub_segment(db):
    save_month(db, money_currency="USD")
    # Missing May separates the source history into independent segments.
    save_month(db, 6, beginning="11000", closing="12000", candidate_count=0)
    before = snapshot(db)
    result = read(db)
    foreign, rub = result.segments
    reasons = {"currency_unsupported", "unknown_flow"}
    assert (foreign.start, foreign.end) == (date(2030, 3, 31), date(2030, 4, 30))
    assert (rub.start, rub.end) == (date(2030, 5, 31), date(2030, 6, 30))
    for field in (
        "contributions_kopecks",
        "withdrawals_kopecks",
        "growth_kopecks",
        "chained_return",
        "xirr_annualized_return",
        "xirr_period_return",
    ):
        assert getattr(foreign, field) is None
        assert getattr(rub, field) is not None
    for field in ("chain_reason_codes", "growth_reason_codes", "xirr_reason_codes"):
        assert reasons <= set(getattr(foreign, field))
        assert not reasons.intersection(getattr(rub, field))
    assert rub.contributions_kopecks == 0 and rub.withdrawals_kopecks == 0
    assert rub.growth_kopecks == 100_000
    assert snapshot(db) == before


def test_overlapping_rur_and_rub_deposits_are_one_flow(db):
    save_month(db, money_currency="RUB")
    save_month(db, money_currency=" rur ", marker="legacy-currency-copy")
    result = read(db)
    assert len(result.flows) == 1 and len(result.flows[0].source_references) == 2
    assert result.months[0].result.contributions_kopecks == 100_000
    assert not {"currency_unsupported", "invalid_money_row"}.intersection(
        gap.code for gap in result.gaps
    )


@pytest.mark.parametrize("second_start,has_gap", [(15, False), (16, True)])
def test_flow_coverage_uses_date_union_separately_from_monthly_values(db, second_start, has_gap):
    xml_root = ET.fromstring(provisional_xml(candidate_count=0))
    for index, period in enumerate(("01.04.30-14.05.30", f"{second_start}.05.30-30.06.30")):
        xml_root.set("synthetic_marker", str(index))
        xml = ET.tostring(xml_root, encoding="utf-8")
        if index:
            # Keep the synthetic activity within this source's declared interval.
            xml = (
                xml.replace(b"15.04.2030", b"20.05.2030")
                .replace(b"17.04.2030", b"20.05.2030")
                .replace(b"2030-04-15", b"2030-05-20")
            )
        with db.session_factory() as session:
            source_intake.save_intake(
                session,
                document=xml,
                filename=f"Брокерский 1234567 ({period}).xml",
                request_id=f"coverage-union-{index}",
            )
    result = read(db)
    assert result.period.missing_endpoint
    assert result.period.chained_return is None
    assert result.months[0].result.opening_kopecks is not None
    assert result.months[-1].result.closing_kopecks is not None
    if has_gap:
        assert result.period.growth_kopecks is None
        assert result.period.xirr_period_return is None
        assert result.period.contributions_kopecks is None
        assert "flow_coverage_gap" in result.period.xirr_reason_codes
        assert "flow_coverage_gap" in result.months[1].flags
    else:
        assert result.period.growth_kopecks == 121_100
        assert result.period.xirr_period_return is not None
        assert result.period.contributions_kopecks == 0
        assert "flow_coverage_gap" not in {gap.code for gap in result.gaps}


@pytest.mark.parametrize(
    ("periods", "has_gap"),
    [
        (("10.04.30-20.06.30",), False),
        (("10.04.30-14.05.30", "15.05.30-20.06.30"), False),
        (("10.04.30-14.05.30", "16.05.30-20.06.30"), True),
    ],
)
def test_partial_calendar_edges_do_not_invalidate_covered_period_flows(db, periods, has_gap):
    for index, period in enumerate(periods):
        xml = provisional_xml(candidate_count=1 if index == 0 else 0)
        if index:
            xml = (
                xml.replace(b"15.04.2030", b"20.05.2030")
                .replace(b"17.04.2030", b"20.05.2030")
                .replace(b"2030-04-15", b"2030-05-20")
            )
        with db.session_factory() as session:
            source_intake.save_intake(
                session,
                document=xml,
                filename=f"Брокерский 1234567 ({period}).xml",
                request_id=f"partial-period-{index}",
            )
    before = snapshot(db)
    result = read(db)
    assert len(result.months) == 3
    assert all(row.result.missing_endpoint for row in result.months)
    # The calendar months at both edges still lack full-month flow coverage.
    for row in (result.months[0], result.months[-1]):
        assert row.result.contributions_kopecks is None
        assert "flow_coverage_gap" in row.flags
    assert result.period.chained_return is None
    assert result.period.growth_kopecks is result.period.xirr_period_return is None
    if has_gap:
        assert result.period.contributions_kopecks is result.period.withdrawals_kopecks is None
    else:
        assert result.period.contributions_kopecks == 100_000
        assert result.period.withdrawals_kopecks == 0
    for reasons in (result.period.growth_reason_codes, result.period.xirr_reason_codes):
        assert ("flow_coverage_gap" in reasons) == has_gap
        assert ("unknown_flow" in reasons) == has_gap
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "structure,expected",
    [
        ("Transfers", "4_Transfers_unsupported"),
        ("UFSR", "5_UFSR_unsupported"),
        ("unparsed", "unparsed_source_rows"),
        ("unknown", "unknown_section"),
        ("position", "position_row_unclassified"),
    ],
)
@pytest.mark.parametrize("long_report", [False, True])
def test_financial_parser_blockers_null_only_covered_months(db, structure, expected, long_report):
    root = ET.fromstring(provisional_xml(candidate_count=0))
    if structure in {"Transfers", "UFSR"}:
        outer = "Trades3" if structure == "Transfers" else "Trades4"
        ET.SubElement(root.find(f"{{MyBroker}}{outer}/{{MyBroker}}Report"), "{MyBroker}Synthetic")
    elif structure == "unparsed":
        ET.SubElement(root.find("{MyBroker}Trades2/{MyBroker}Report"), "{MyBroker}rn")
    elif structure == "unknown":
        ET.SubElement(root, "{MyBroker}SyntheticSection")
    else:
        collection = root.find(".//{MyBroker}Details_Collection")
        ET.SubElement(collection, "{MyBroker}Details", {"acc_code": ACCOUNT})
    with db.session_factory() as session:
        ack = source_intake.save_intake(
            session,
            document=ET.tostring(root, encoding="utf-8"),
            filename=f"Брокерский 1234567 (01.04.30-{'31.05.30' if long_report else '30.04.30'}).xml",
            request_id="financial-gap",
        )
    if long_report:
        # Valid overlapping monthly statements cannot erase a bad document's uncertainty.
        save_month(db, candidate_count=0)
        save_month(db, 5, candidate_count=0)
    save_month(db, 6 if long_report else 5, candidate_count=0)
    before = snapshot(db)
    result = read(db)
    for row in result.months[:-1]:
        assert row.result.contributions_kopecks is row.result.withdrawals_kopecks is None
        assert row.result.growth_kopecks is row.result.modified_dietz_return is None
        assert {expected, "unknown_flow"} <= set(row.flags)
        assert any(
            gap.code == expected
            and gap.intake_id == ack["intake_id"]
            and gap.month == row.result.closing_date.replace(day=1)
            for gap in result.gaps
        )
    assert result.months[-1].result.modified_dietz_return is not None
    assert result.months[-1].result.growth_kopecks is not None
    affected_totals = [result.period]
    for segment in result.segments:
        if segment.start < result.months[-1].result.opening_date:
            affected_totals.append(segment)
        else:
            assert segment.growth_kopecks is not None
            assert segment.xirr_period_return is not None
    for totals in affected_totals:
        assert totals.growth_kopecks is None
        assert totals.contributions_kopecks is totals.withdrawals_kopecks is None
        assert totals.xirr_annualized_return is totals.xirr_period_return is None
        for reasons in (
            totals.growth_reason_codes,
            totals.xirr_reason_codes,
            totals.chain_reason_codes,
        ):
            assert {expected, "unknown_flow"} <= set(reasons)
    assert snapshot(db) == before


def test_non_financial_source_status_does_not_create_flow_uncertainty(db, monkeypatch):
    from copy import deepcopy

    save_month(db, candidate_count=0)
    reader = source_intake.read_intake

    def non_financial_status(session, intake_id):
        view = deepcopy(reader(session, intake_id))
        view["document"]["syntax_blockers"] = ["source_only", "review_pending"]
        return view

    monkeypatch.setattr(source_intake, "read_intake", non_financial_status)
    result = read(db)
    assert result.months[0].result.modified_dietz_return is not None
    assert result.period.growth_kopecks == 121_100
    assert result.period.xirr_period_return is not None
    assert not result.gaps


def test_service_reaggregation_withholds_two_negative_dietz_factors(db):
    for month, day, end in ((2, 27, 28), (3, 30, 31)):
        xml = (
            provisional_xml(
                beginning="100",
                closing="100",
                rub=("0", "0"),
                candidate_count=0,
                extra_money=(("Внесено по распоряжению Клиента", "Synthetic funding", "300"),),
            )
            .decode()
            .replace("2030-04-15", f"2030-{month:02d}-{day:02d}")
        )
        xml = xml.replace("2030-04-", f"2030-{month:02d}-").replace(
            ".04.2030", f".{month:02d}.2030"
        )
        with db.session_factory() as session:
            source_intake.save_intake(
                session,
                document=xml.encode(),
                filename=f"Брокерский 1234567 (01.{month:02d}.30-{end}.{month:02d}.30).xml",
                request_id=f"negative-factor-{month}",
            )
    result = read(db)
    assert all(row.result.modified_dietz_return < -1 for row in result.months)
    for totals in (result.period, *result.segments):
        assert totals.chained_return is None
        assert totals.chain_reason_codes == ("negative_dietz_factor",)
        assert totals.contributions_kopecks == 60_000
        assert totals.growth_kopecks == -60_000
        assert not totals.growth_reason_codes
        assert "negative_dietz_factor" not in totals.xirr_reason_codes


def test_service_reaggregation_allows_exact_zero_dietz_factor(db):
    xml = provisional_xml(beginning="100", closing="0", rub=("0", "0"), candidate_count=0)
    with db.session_factory() as session:
        source_intake.save_intake(
            session,
            document=xml,
            filename="Брокерский 1234567 (01.04.30-30.04.30).xml",
            request_id="zero-factor",
        )
    result = read(db)
    assert result.months[0].result.modified_dietz_return == -1
    assert result.period.chained_return == -1
    assert result.period.chain_reason_codes == ()


@pytest.fixture(scope="module")
def astra_results(tmp_path_factory, source_returns_database_factory):
    """Every XML reaches real parsing/intake/readers in a separate synthetic DB."""
    results = {}
    for case in ASTRA_CASES:
        database = source_returns_database_factory(tmp_path_factory.mktemp(case["case"]))
        try:
            results[case["case"]] = astra_replay(database, case)
        finally:
            database.engine.dispose()
    return results


@pytest.mark.parametrize("case", [case["case"] for case in ASTRA_CASES])
def test_astra_hunt_replays_every_fixture(astra_results, case):
    result = astra_results[case]
    if case == "08_missing_money":
        assert result["parser_error"] == "required_section_invalid"
        assert result["calculation"] == "not_run_parser_rejected"
        return
    assert "parser_error" not in result
    assert result["monthly"]["authority"] == "provisional"
    assert result["monthly"]["financial_authority"] == "none"
    # Source-only Save never grants accepted portfolio valuations or flow coverage.
    assert result["exact_xirr"]["annualized_rate"] is None
    assert result["exact_twrr"]["return_rate"] is None
    for metric in ("exact_xirr", "exact_twrr"):
        assert result[metric]["availability"] == "not_computable"
        assert "not_computable_scope_coverage_incomplete" in result[metric]["reason_codes"]


@pytest.mark.parametrize(
    "case,reason",
    [
        ("02_unknown", "unrecognized_money"),
        ("05_usd_deposit", "currency_unsupported"),
        ("06_fx_zero_rate", "currency_unsupported"),
        ("12_partial_month", "flow_coverage_gap"),
        ("13_negative_deposit", "invalid_external_flow"),
        ("14_zero_deposit", "invalid_external_flow"),
        ("19_partial_redemption", "unrecognized_money"),
        ("24_transfer_section", "4_Transfers_unsupported"),
    ],
)
def test_astra_hunt_existing_guards(astra_results, case, reason):
    result = astra_results[case]["monthly"]
    assert reason in {gap["code"] for gap in result["gaps"]}
    assert result["period"]["xirr_period_return"] is None
    assert result["period"]["chained_return"] is None
    assert all(row["result"]["modified_dietz_return"] is None for row in result["months"])


@pytest.mark.parametrize("case", ["01_control", "07_empty_money", "16_zero_fee"])
def test_astra_hunt_known_zero_is_not_missing(astra_results, case):
    result = astra_results[case]["monthly"]
    assert result["period"]["growth_kopecks"] == 90_000
    assert result["period"]["chained_return"] == Decimal("0.09")
    assert abs(result["period"]["xirr_period_return"] - Decimal("0.09")) < Decimal("1e-25")
    assert not result["gaps"]


def test_astra_hunt_occurrences_signs_and_unknown_identity(astra_results):
    duplicate = astra_results["10_duplicate_money"]["monthly"]
    assert len(duplicate["flows"]) == 2
    assert duplicate["period"]["contributions_kopecks"] == 20_000
    withdrawal = astra_results["15_negative_withdrawal"]["monthly"]["period"]
    assert withdrawal["withdrawals_kopecks"] == 10_000
    assert withdrawal["growth_kopecks"] == 100_000
    assert astra_results["09_empty_positions"]["monthly"]["period"]["xirr_period_return"] is None
    unknown = astra_results["20_unknown_security"]
    assert unknown["monthly"]["period"]["growth_kopecks"] == 90_000
    instrument = unknown["instruments"]["instruments"][0]
    assert instrument["instrument_type"] is None
    assert "instrument_type_unknown" in instrument["months"][0]["flags"]
    assert instrument["months"][0]["approximate"]


@pytest.mark.parametrize(
    "case,field",
    [
        ("17_nkd_buy", "buys_cost_kopecks"),
        ("18_nkd_sell", "sells_proceeds_kopecks"),
    ],
)
def test_astra_hunt_nkd_is_counted_once(astra_results, case, field):
    result = astra_results[case]
    assert result["classifications"] == ["trade_settlement"]
    assert result["monthly"]["months"][0]["coupons_kopecks"] == 0
    assert result["monthly"]["period"]["contributions_kopecks"] == 0
    instrument = result["instruments"]["instruments"][0]["months"][0]
    assert instrument[field] == 20_500  # 200 principal + 5 NKD, not +10 NKD.


def test_astra_hunt_missing_may_does_not_become_zero_flows(db):
    for case in (ASTRA_CASES[0], ASTRA_CASES[-1]):
        with db.session_factory() as session:
            source_intake.save_intake(
                session,
                document=(ASTRA_ROOT / (case["case"] + ".xml")).read_bytes(),
                filename=case["filename"],
                request_id=case["case"],
            )
    result = read(db)
    assert "flow_coverage_gap" in result.period.xirr_reason_codes
    assert result.period.xirr_period_return is None
    assert result.period.chained_return is None
    assert result.period.growth_kopecks is None
    assert result.period.contributions_kopecks is None
    assert len(result.segments) == 2
    assert all(segment.xirr_period_return is not None for segment in result.segments)


@pytest.mark.parametrize("reattached", [False, True], ids=["saved", "reattached"])
@pytest.mark.parametrize(
    "case",
    [
        "03_typo_withdrawal",
        "11_duplicate_position",
        "22_hidden_amount",
        "23_hidden_wrapper",
    ],
)
def test_astra_hunt_uncertain_import_must_withhold_returns(astra_results, case, reattached):
    result = astra_results[case]
    if "parser_error" in result:
        return  # Rejecting the unsupported/ambiguous source is also a safe resolution.
    period = result["reattached_period"] if reattached else result["monthly"]["period"]
    assert period["xirr_period_return"] is None
    assert period["xirr_annualized_return"] is None
    assert period["chained_return"] is None
    assert period["growth_kopecks"] is None
    assert period["xirr_reason_codes"]
    if not reattached:
        assert all(
            row["result"]["modified_dietz_return"] is None for row in result["monthly"]["months"]
        )
        expected = {
            "03_typo_withdrawal": "unrecognized_money",
            "11_duplicate_position": "duplicate_position",
            "22_hidden_amount": "unparsed_source_rows",
            "23_hidden_wrapper": "unparsed_source_rows",
        }[case]
        assert expected in {gap["code"] for gap in result["monthly"]["gaps"]}
        for instrument in result["instruments"]["instruments"]:
            assert all(row["total_kopecks"] is None for row in instrument["months"])
        if case == "11_duplicate_position":
            assert result["row_counts"]["positions"] == 2
            instrument = result["instruments"]["instruments"][0]["months"][0]
            assert instrument["opening_quantity"] is instrument["closing_quantity"] is None
            assert (
                instrument["opening_value_kopecks"] is instrument["closing_value_kopecks"] is None
            )
            assert "duplicate_position" in instrument["flags"]


@pytest.mark.parametrize("reattached", [False, True], ids=["saved", "reattached"])
def test_astra_hunt_account_transfer_is_external_to_account(astra_results, reattached):
    result = astra_results["04_account_transfer"]
    if "parser_error" in result:
        return
    period = result["reattached_period"] if reattached else result["monthly"]["period"]
    if period["xirr_period_return"] is None:
        assert period["xirr_reason_codes"]
        assert period["chained_return"] is None
    else:
        # Once account crossing is supported, a withdrawal explains the entire NAV change.
        assert period["withdrawals_kopecks"] == 100_000
        assert period["growth_kopecks"] == 0
        assert period["xirr_period_return"] == 0
        assert period["chained_return"] == 0


@pytest.mark.parametrize("legacy", [False, True], ids=["current", "unflagged_saved_rows"])
@pytest.mark.parametrize("overlap", [False, True])
def test_duplicate_positions_block_endpoints_even_with_clean_overlap(
    db, monkeypatch, legacy, overlap
):
    from copy import deepcopy

    root = ET.fromstring(provisional_xml(beginning="100", closing="110", candidate_count=0))
    collection = root.find(".//{MyBroker}Details_Collection")
    collection.append(deepcopy(collection.find("{MyBroker}Details[@ISIN1]")))
    with db.session_factory() as session:
        intake = source_intake.save_intake(
            session,
            document=ET.tostring(root),
            filename="Брокерский 1234567 (01.04.30-30.04.30).xml",
            request_id="duplicate-position-source",
        )["intake_id"]
    if overlap:
        save_month(db, beginning="100", closing="110", candidate_count=0, marker="clean-copy")
    if legacy:
        reader = source_intake.read_intake

        def unflagged_rows(session, intake_id):
            view = deepcopy(reader(session, intake_id))
            if intake_id == intake:
                view["document"]["endpoint_conflicts"] = []
            return view

        monkeypatch.setattr(source_intake, "read_intake", unflagged_rows)
    before = snapshot(db)
    result = read(db)
    row = result.months[0].result
    assert row.opening_kopecks is row.closing_kopecks is None
    assert row.growth_kopecks is row.modified_dietz_return is None
    assert "duplicate_position" in row.reason_codes
    assert result.period.growth_kopecks is result.period.xirr_period_return is None
    assert any(gap.code == "duplicate_position" and gap.intake_id == intake for gap in result.gaps)
    assert snapshot(db) == before


@pytest.mark.parametrize("month", [2, 4, 12])
@pytest.mark.parametrize("filename", ["renamed.xml", "Брокерский 1234567 (01.01.30-31.01.30).xml"])
def test_inferred_periods_supply_calendar_month_return_boundaries(db, month, filename):
    from datetime import timedelta

    intake, original = save_month(db, month, filename=filename)
    with db.session_factory() as session:
        view = source_intake.read_intake(session, intake)
    first = date(2030, month, 1)
    last = date(2030, month, calendar.monthrange(2030, month)[1])
    assert (view["covered_from"], view["covered_to"]) == (first.isoformat(), last.isoformat())
    assert "period_inferred_from_content" in view["document"]["warnings"]
    if filename.startswith("Брокерский"):
        assert "filename_period_mismatch" in view["document"]["warnings"]
    for attached in (None, {intake: original}):
        result = read(db, originals=attached)
        assert len(result.months) == 1
        row = result.months[0].result
        assert (row.opening_date, row.closing_date) == (first - timedelta(days=1), last)
        assert row.opening_kopecks == 1_000_000
        assert row.closing_kopecks == 1_121_100
        assert row.modified_dietz_return is not None
        assert not row.missing_endpoint


def test_cash_event_outside_filename_infers_period_without_inventing_monthly_endpoints(
    astra_results,
):
    from hermes_finance.statement_import.mybroker import parse_mybroker

    case = next(case for case in ASTRA_CASES if case["case"] == "21_outside_period")
    source = parse_mybroker((ASTRA_ROOT / (case["case"] + ".xml")).read_bytes(), case["filename"])
    assert (source["covered_from"], source["covered_to"]) == ("2030-04-01", "2030-05-31")
    assert set(source["warnings"]) == {"period_inferred_from_content", "filename_period_mismatch"}
    result = astra_results[case["case"]]
    assert "parser_error" not in result
    assert [row["result"]["closing_date"] for row in result["monthly"]["months"]] == [
        date(2030, 4, 30),
        date(2030, 5, 31),
    ]
    assert all(row["result"]["missing_endpoint"] for row in result["monthly"]["months"])
    assert "invalid_external_flow" not in {gap["code"] for gap in result["monthly"]["gaps"]}
    for period in (result["monthly"]["period"], result["reattached_period"]):
        assert period["chained_return"] is None
        assert period["xirr_period_return"] is not None
