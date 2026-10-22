"""Synthetic monthly source-account estimates; no Owner sources or finance writes."""

import calendar
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
from test_statement_import_broker_statement_provisional import (
    _finite_tables,
    _free_database,
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
def db(tmp_path):
    database = _free_database(tmp_path)
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
    filename = f"Брокерский 1234567 (01.{month:02d}.30-{end}.{month:02d}.30).xml"
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
