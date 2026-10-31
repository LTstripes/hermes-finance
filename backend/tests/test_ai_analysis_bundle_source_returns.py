"""Synthetic source/export parity, currentness, dates, precision and privacy."""

import copy
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from sqlalchemy import select
from test_statement_import_mybroker import ACCOUNT
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_preflight import (
    investment_case,
    saved_investment_preview,
    snapshot,
)

from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Account,
    Instrument,
    PositionSnapshot,
    SourceMoneyClassification,
)
from hermes_finance.services import ai_review_payloads, returns_overall
from hermes_finance.services import ai_source_returns as adapter
from hermes_finance.services import source_investment_proofs as proofs
from hermes_finance.services.ai_financial_review import (
    assemble_ai_financial_review,
    canonical_json,
    validate_ai_financial_review,
)
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.returns_view import read_detail, read_overview

pytestmark = [pytest.mark.import_export, pytest.mark.ci_integrations]
START, END = date(2029, 12, 31), date(2030, 1, 31)
SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2] / "docs/schemas/ai_financial_review.schema.json"
    ).read_text(encoding="utf-8")
)


def _save(database, monkeypatch):
    preview = saved_investment_preview(database, monkeypatch)["persistence"]
    with database.session_factory() as session:
        proofs.confirm(
            session,
            **{k: preview[k] for k in ("form_token", "preview_digest")},
            request_id="ai-proof",
        )
    return preview


def _section(session, as_of=END):
    return adapter.source_returns_section(session, as_of_date=as_of, reporting_period=(2030, 1))


def _first(section):
    return section["data"]["accounts"][0]["intervals"][0]


def test_versioned_referenced_download_preserves_legacy_default_and_read_only_facts(
    database, monkeypatch
):
    from hermes_finance.api import ai_financial_review as api

    _save(database, monkeypatch)
    with database.session_factory() as session:
        create_reporting_month(session, year=2030, month=1, snapshot_date=END)
    monkeypatch.setattr(api, "moscow_today", lambda _request: date(2030, 2, 1))
    params = {"generated_at": "2030-02-01T00:00:00Z"}
    before = snapshot(database)
    with TestClient(create_app(database)) as client:
        previous = client.get("/api/export/ai-financial-review", params=params)
        assert previous.status_code == 200, previous.text
        assert previous.json()["schema_version"] == "1.5.0"
        current = client.get(
            "/api/export/ai-financial-review/json", params={**params, "format_version": "2.0.0"}
        )
        assert current.status_code == 200, current.text
        assert current.json()["schema_version"] == "2.0.0"
        assert ai_review_payloads.expand_source_payloads(current.json()) == previous.json()
        assert current.headers["cache-control"] == "no-store"
        assert "attachment;" in current.headers["content-disposition"]
        assert (
            client.get(
                "/api/export/ai-financial-review/json", params={"format_version": "9.0.0"}
            ).status_code
            == 422
        )
    assert snapshot(database) == before


def test_saved_source_round_trip_api_detail_parity_and_read_only(database, monkeypatch):
    _save(database, monkeypatch)
    with database.session_factory() as session:
        create_reporting_month(session, year=2030, month=1, snapshot_date=END)
    before = snapshot(database)
    with database.session_factory() as session:
        report = assemble_ai_financial_review(
            session, generated_at=datetime(2030, 2, 1, tzinfo=UTC), evaluated_on=date(2030, 2, 1)
        )
        exported = report["sections"]["source_returns"]
        current = report["sections"]["returns_overall"]["data"]
        interval = _first(exported)
        instrument = interval["instruments"][0]
        ordinary = proofs.read_reports(session, source_account=ACCOUNT)[0]["interval"]
        view = read_overview(session, scope=f"source:{ACCOUNT}", start=START, end=END)
        detail = read_detail(
            session, scope=f"source:{ACCOUNT}", start=START, end=END, isin=instrument["isin"]
        )
        overview = returns_overall.read_overall(session, include_instrument_details=True)
        card = returns_overall.read_instrument_card(session, instrument["isin"], overview=overview)
    assert report["schema_version"] == "1.5.0"
    assert current["scope"] == "current_available_history_not_limited_to_selected_month"
    assert current["mixed_result"]["known_result"] == adapter._overall_metric(
        overview["mixed_result"]["known_result"]
    )
    for key in ("coupon_income", "dividend_income"):
        assert current[key]["known_total"] == adapter._overall_metric(overview[key]["known_total"])
        assert current[key]["accounts"][0]["source_account_ref"] == "source-account-1"
    current_card = current["instruments"][0]
    assert current_card["isin"] == card["isin"]
    assert current_card["summary"]["valuation_dates"] == [
        day.isoformat() if isinstance(day, date) else day
        for day in card["summary"]["valuation_dates"]
    ]
    for key in ("pnl", "rate", "coupons", "dividends", "redemption", "costs", "taxes"):
        assert current_card["summary"][key] == adapter._overall_metric(card["summary"][key])
    current_account = current_card["accounts"][0]
    assert current_account["proof_status"] == "current"
    assert current_account["source_interval_ref"] == interval["ref"]
    assert current_account["detail"]["opening_quantity"] == detail["opening_quantity"]
    assert current_account["detail"]["analysis"]["metrics"] == instrument["metrics"]
    assert interval["opening_date"] == str(START) and interval["closing_date"] == str(END)
    assert interval["account"]["metrics"]["pnl"]["value"]["amount"] == "90.00"
    assert Decimal(instrument["metrics"]["pnl"]["value"]["amount"]) * 100 == Decimal(
        view["instruments"][0]["pnl"]["value"]
    )
    for name in ("modified_dietz", "xirr_annualized", "xirr_period"):
        m = instrument["metrics"][name]
        with localcontext() as context:
            context.prec = 100
            assert Decimal(m["value"]) == Decimal(ordinary["instruments"][0][name]["value"]) * 100
        assert m["reason_codes"] == ordinary["instruments"][0][name]["reason_codes"]
    assert instrument["metrics"]["xirr_annualized"]["annualized"]
    assert not instrument["metrics"]["xirr_period"]["annualized"]
    assert instrument["opening"]["quantity"] == detail["opening_quantity"]
    assert instrument["closing"]["quantity"] == detail["closing_quantity"]
    assert instrument["components"]["buys"]["value"]["amount"] == "1000.00"
    assert instrument["components"]["fees"]["value"]["amount"] == "10.00"
    assert instrument["components"]["coupons"]["value"]["amount"] == "0.00"
    assert instrument["events"] and any(e["cash_legs"] for e in instrument["events"])
    account = exported["data"]["accounts"][0]
    assert account["financial_account_ref"] is None  # even with effective broker mappings
    assert account["all_history_ref"] == account["selected_month"]["interval_ref"]
    assert account["monthly_history_refs"] == [account["all_history_ref"]]
    validate_ai_financial_review(json.loads(canonical_json(report)))
    with TestClient(create_app(database)) as client:
        response = client.get(
            "/api/export/ai-financial-review/json",
            params={"generated_at": "2030-02-01T00:00:00Z", "evaluated_on": "2030-02-01"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["sections"]["source_returns"] == exported
        assert response.json()["sections"]["returns_overall"]["data"] == current
        ordinary_card = client.get(
            "/api/returns/instrument-card", params={"isin": instrument["isin"]}
        )
        assert ordinary_card.status_code == 200, ordinary_card.text
        assert ordinary_card.json()["summary"]["pnl"]["value"] == card["summary"]["pnl"]["value"]
    wire = json.dumps({"history": exported, "current": current})
    for forbidden in (
        ACCOUNT,
        "1234567",
        "proof_id",
        "intake_id",
        "sha256",
        "native_source_account",
        "source_references",
        "document",
        "event_key",
        "canonical_account_id",
        "account_id",
        "instrument_id",
    ):
        assert forbidden not in wire
    assert snapshot(database) == before


@pytest.mark.parametrize("aba", [False, True])
def test_latest_stale_scope_never_revives_numeric_month_or_history(database, monkeypatch, aba):
    _save(database, monkeypatch)
    with database.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).order_by(SourceMoneyClassification.id)
        )
        old = row.classification
        row.classification = "unknown" if old != "unknown" else "fee"
        session.commit()
        if aba:
            row.classification = old
            session.commit()
    with database.session_factory() as session:
        refs = {}
        section = adapter.source_returns_section(
            session, as_of_date=END, reporting_period=(2030, 1), source_account_refs=refs
        )
        current = adapter.returns_overall_section(
            session, source_account_refs=refs, source_section=section
        )["data"]
    row = _first(section)
    assert row["currentness"] == "stale" and row["reason_codes"]
    assert row["account"] is None and row["instruments"] == []
    account = section["data"]["accounts"][0]
    assert account["all_history_ref"] == row["ref"]
    assert account["selected_month"]["interval_ref"] == row["ref"]
    assert current["source_accounts"][0]["proof_status"] == "stale"
    assert current["mixed_result"]["known_result"]["value"] is None
    assert current["coupon_income"]["known_total"]["value"] is None
    assert current["dividend_income"]["known_total"]["value"] is None
    assert all(a["detail"] is None for i in current["instruments"] for a in i["accounts"])


def test_current_available_history_is_not_limited_to_selected_month_or_as_of(database, monkeypatch):
    _save(database, monkeypatch)
    with database.session_factory() as session:
        create_reporting_month(session, year=2029, month=12, snapshot_date=START)
    before = snapshot(database)
    with database.session_factory() as session:
        report = assemble_ai_financial_review(
            session, generated_at=datetime(2030, 2, 1, tzinfo=UTC), evaluated_on=date(2030, 2, 1)
        )
    history = report["sections"]["source_returns"]["data"]
    current = report["sections"]["returns_overall"]["data"]
    assert history["as_of_date"] == "2029-12-31"
    assert history["accounts"][0]["all_history_ref"] is None
    assert current["source_accounts"][0]["period"]["end"] == str(END)
    assert current["source_accounts"][0]["result"]["pnl"]["value"]["amount"] == "90.00"
    account = current["instruments"][0]["accounts"][0]
    assert account["source_interval_ref"] is None
    assert account["detail"]["analysis"]["metrics"]["xirr_annualized"]["value"] is not None
    assert account["detail"]["analysis"]["metrics"]["xirr_period"]["value"] is not None
    assert snapshot(database) == before


def test_complete_export_reuses_source_derivation_and_discards_snapshot_cache(
    database, monkeypatch
):
    from hermes_finance.services.source_monthly_returns import (
        _SOURCE_INVESTMENT_READS,
        source_read_snapshot,
    )

    _save(database, monkeypatch)
    with database.session_factory() as session:
        create_reporting_month(session, year=2030, month=1, snapshot_date=END)
    original = proofs._derive
    calls = []

    def derive(*args, **kwargs):
        calls.append(args[1].id)
        return original(*args, **kwargs)

    monkeypatch.setattr(proofs, "_derive", derive)
    with database.session_factory() as session:
        with source_read_snapshot(session):
            _section(session)
        baseline = len(calls)
        assert _SOURCE_INVESTMENT_READS not in session.info
    calls.clear()
    with database.session_factory() as session:
        report = assemble_ai_financial_review(
            session, generated_at=datetime(2030, 2, 1, tzinfo=UTC), evaluated_on=date(2030, 2, 1)
        )
        assert _SOURCE_INVESTMENT_READS not in session.info
    assert report["sections"]["returns_overall"]["data"]["instruments"][0]["accounts"][0]["detail"]
    assert len(calls) == baseline


def test_saved_gold_projection_keeps_observation_date_cost_result_and_privacy(database):
    with database.session_factory() as session:
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=END)
        account = Account(name="private-account-424242", account_type="other")
        instrument = Instrument(name="Synthetic saved gold", instrument_type="gold")
        session.add_all([account, instrument])
        session.flush()
        session.add(
            PositionSnapshot(
                reporting_month_id=month.id,
                account_id=account.id,
                instrument_id=instrument.id,
                quantity=Decimal("2"),
                average_cost_per_unit_kopecks=5000,
                market_price_per_unit_kopecks=7450,
                market_value_kopecks=14900,
                cost_basis_kopecks=10000,
                unrealized_result_kopecks=4900,
                price_date=date(2030, 1, 29),
                manual_adjustment=False,
            )
        )
        month.status = "closed"
        session.commit()
    before = snapshot(database)
    with database.session_factory() as session:
        section = adapter.returns_overall_section(
            session, source_account_refs={}, source_section={"data": None}
        )
        ordinary = returns_overall.read_overall(session, include_instrument_details=True)
    gold = section["data"]["gold"]
    saved = gold["snapshots"][0]
    assert saved["date"] == "2030-01-29" and Decimal(saved["quantity"]) == Decimal("2")
    for name in ("market_value", "cost_basis", "unrealized_result", "cost_return"):
        assert saved[name] == adapter._overall_metric(ordinary["gold"]["snapshots"][0][name])
    assert Decimal(saved["cost_return"]["value"]) == Decimal("49")
    assert gold["period_result"]["value"] is None
    wire = json.dumps(section)
    for forbidden in (
        "private-account-424242",
        "account_id",
        "instrument_id",
        "cost_basis_kopecks",
    ):
        assert forbidden not in wire
    assert snapshot(database) == before


def test_current_and_history_keep_one_snapshot_when_proof_changes_between_sections(
    database, monkeypatch
):
    from hermes_finance.services import ai_financial_review as review

    _save(database, monkeypatch)
    with database.session_factory() as session:
        create_reporting_month(session, year=2030, month=1, snapshot_date=END)
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one() == "wal"
    original = review.source_returns_section
    written = False

    def interleaved(*args, **kwargs):
        nonlocal written
        section = original(*args, **kwargs)
        if not written:
            written = True
            with database.session_factory() as writer:
                row = writer.scalar(
                    select(SourceMoneyClassification).order_by(SourceMoneyClassification.id)
                )
                row.classification = "unknown" if row.classification != "unknown" else "fee"
                writer.commit()
        return section

    monkeypatch.setattr(review, "source_returns_section", interleaved)
    with database.session_factory() as session:
        report = assemble_ai_financial_review(
            session, generated_at=datetime(2030, 2, 1, tzinfo=UTC), evaluated_on=date(2030, 2, 1)
        )
    assert written and _first(report["sections"]["source_returns"])["currentness"] == "current"
    assert (
        report["sections"]["returns_overall"]["data"]["source_accounts"][0]["proof_status"]
        == "current"
    )
    with database.session_factory() as session:
        fresh = assemble_ai_financial_review(
            session, generated_at=datetime(2030, 2, 1, tzinfo=UTC), evaluated_on=date(2030, 2, 1)
        )
    assert _first(fresh["sections"]["source_returns"])["currentness"] == "stale"
    assert (
        fresh["sections"]["returns_overall"]["data"]["source_accounts"][0]["proof_status"]
        == "stale"
    )


def _derived(doc, raw, report, money, *, from_zero=True):
    service, *_ = investment_case()
    analyses = {}
    interval = service._interval(doc, raw, report, money, {}, {}, from_zero, analyses=analyses)
    proof = {
        "proof_id": 99,
        "source_account": "private-999",
        "covered_from": doc["covered_from"],
        "covered_to": doc["covered_to"],
        "history_from_zero": from_zero,
        "status": "current",
        "reason_codes": [],
        "interval": interval,
    }
    return proof, analyses


def test_sold_position_zero_is_preserved_and_not_filtered_by_current_holdings():
    _, doc, raw, report, money = investment_case()
    doc["positions"][0].update(
        beginning_actual_quantity="10",
        actual_quantity="0",
        beginning_value="1000",
        ending_value=None,
    )
    doc["trades"][0]["core"]["quantity"] = "-10"
    money[0]["minor"] = 100000
    report = replace(report, positions={("1234567", "RU000A000000"): ("0", 0)})
    proof, analyses = _derived(doc, raw, report, money, from_zero=False)
    row = adapter._proof_interval(proof, analyses, {})["instruments"][0]
    assert row["closing"]["quantity"] == "0"
    assert row["closing"]["economic_value"]["amount"] == "0.00"
    assert row["metrics"]["pnl"]["value"]["amount"] == "-10.00"
    assert row["components"]["sells"]["value"]["amount"] == "1000.00"
    assert any(e["kind"] == "SELL" for e in row["events"])


def test_known_coupon_survives_missing_valuation_and_bad_other_instrument():
    from hermes_finance.domain.instrument_return import CashLeg, InstrumentEvent, Metric

    _, doc, raw, report, money = investment_case()
    proof, analyses = _derived(doc, raw, report, money)
    isin = next(iter(analyses))
    good = adapter._proof_interval(proof, analyses, {})["instruments"][0]
    broken = analyses[isin]
    payout = InstrumentEvent(
        event_key="private",
        provider="private",
        native_source_account="private-999",
        isin="RU000A000001",
        kind="COUPON",
        source_references=(),
        event_date=date(2030, 1, 20),
        net_payout_kopecks=12000,
        cash_legs=(CashLeg("coupon", date(2030, 1, 20), 12000, -12000, (), "private"),),
    )
    broken = replace(
        broken,
        closing=replace(broken.closing, economic_value_kopecks=None),
        pnl=Metric(None, "unavailable", ("economic_endpoint_unavailable",)),
        components={**broken.components, "coupons": Metric(12000, "supported")},
        events=(payout,),
    )
    bad = adapter._instrument("RU000A000001", {}, broken)
    assert bad["metrics"]["pnl"]["value"] is None
    assert bad["components"]["coupons"]["value"]["amount"] == "120.00"
    assert bad["events"][0]["net_payout"]["amount"] == "120.00"
    assert good["metrics"]["pnl"]["value"]["amount"] == "90.00"


def test_full_history_does_not_require_months_and_future_proof_is_excluded(database, monkeypatch):
    _, doc, raw, report, money = investment_case()
    proof, analyses = _derived(doc, raw, report, money)
    proof.update(covered_from="2028-01-01", covered_to="2030-01-31")
    proof["interval"].update(opening_date="2027-12-31", closing_date="2030-01-31")
    future = {**proof, "proof_id": 100, "covered_to": "2031-01-31"}

    def reports(session, **kwargs):
        kwargs["analyses"][99] = analyses
        return [future, proof]

    monkeypatch.setattr(adapter.source_investment_proofs, "read_reports", reports)
    monkeypatch.setattr(adapter, "_source_scopes", lambda s: {})
    monkeypatch.setattr(adapter, "_selected_sources", lambda *a: ([], None))
    monkeypatch.setattr(
        adapter, "read_monthly_returns", lambda *a, **kw: SimpleNamespace(months=())
    )
    with database.session_factory() as session:
        section = _section(session)
    account = section["data"]["accounts"][0]
    assert len(account["intervals"]) == 1
    assert account["all_history_ref"] is not None
    assert account["monthly_history_refs"] == []
    assert account["selected_month"]["interval_ref"] is None
    assert _first(section)["account"]["metrics"]["pnl"]["value"]["amount"] == "90.00"


def test_exact_units_large_values_precision_and_strict_privacy_schema():
    assert adapter._money(900719925474099399)["amount"] == "9007199254740993.99"
    assert adapter._percent("0.12345678901234567890123456789") == "12.345678901234567890123456789"
    assert adapter._percent("0") == "0" and adapter._percent(None) is None
    fixture = json.loads(
        (
            Path(__file__).resolve().parents[2] / "docs/schemas/ai_financial_review.synthetic.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(SCHEMA, format_checker=FormatChecker()).validate(fixture)
    extra = copy.deepcopy(fixture)
    extra["sections"]["source_returns"]["data"]["accounts"][0]["native_account"] = "private-999"
    with pytest.raises(ValidationError):
        Draft202012Validator(SCHEMA).validate(extra)
    for key in ("account_id", "instrument_id", "scope", "proof_id", "path", "raw_proof"):
        extra = copy.deepcopy(fixture)
        extra["sections"]["returns_overall"]["data"][key] = "private-999"
        with pytest.raises(ValidationError):
            Draft202012Validator(SCHEMA).validate(extra)
    for path, key in (
        (("source_accounts", 0), "account_id"),
        (("mixed_result", "components", 0), "id"),
        (("instruments", 0, "accounts", 0), "canonical_account_id"),
        (("instruments", 0, "accounts", 0, "detail", "analysis", "events", 0), "event_key"),
    ):
        extra = copy.deepcopy(fixture)
        target = extra["sections"]["returns_overall"]["data"]
        for component in path:
            target = target[component]
        target[key] = "private-999"
        with pytest.raises(ValidationError):
            Draft202012Validator(SCHEMA).validate(extra)


def test_current_returns_metric_preserves_exact_zero_unknown_units_and_methods():
    from hermes_finance.services.returns_view import metric

    assert adapter._overall_metric(metric(900719925474099399))["value"]["amount"] == (
        "9007199254740993.99"
    )
    assert adapter._overall_metric(metric(0))["value"]["amount"] == "0.00"
    unknown = adapter._overall_metric(metric(reasons=("source_missing",), estimate=False))
    assert unknown["value"] is None and unknown["reason_codes"] == ["source_missing"]
    assert not unknown["approximate"]
    rate = adapter._overall_metric(
        metric("0.12345678901234567890123456789", unit="fraction", method="modified_dietz")
    )
    assert rate["value"] == "12.345678901234567890123456789"
    assert rate["method"] == "modified_dietz" and rate["unit"] == "percent"
    with pytest.raises(ValueError, match="unit_unsupported"):
        adapter._overall_metric(metric("1", unit="unapproved_unit"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (Decimal("0E-12"), "0.000000000000"),
        ("-0E-9", "-0.000000000"),
        ("8E+4", "80000"),
        ("3.125E-18", "0.000000000000000003125"),
        (
            Decimal("7.123456789012345678901234567890123456789"),
            "7.123456789012345678901234567890123456789",
        ),
    ],
)
def test_quantity_representation_is_fixed_point_exact_and_nullable(value, expected):
    with localcontext() as context:
        context.prec = 4
        assert adapter.decimal_quantity(value) == expected
    if value is not None:
        assert Decimal(expected) == Decimal(value)
        assert "e" not in expected.lower()
    with pytest.raises(TypeError, match="exact decimal"):
        adapter.decimal_quantity(0.25)


def test_opaque_source_blocker_aliases_are_exact_and_not_a_general_sanitizer():
    from hermes_finance.services import ai_financial_review as review

    original = ["4_Transfers_unsupported", "5_UFSR_unsupported", "economic_endpoint_unavailable"]
    expected = [
        "economic_endpoint_unavailable",
        "source_4_transfers_unsupported",
        "source_5_ufsr_unsupported",
    ]
    assert adapter._reasons(original) == expected
    assert review._reason_codes(original) == expected
    assert original == [
        "4_Transfers_unsupported",
        "5_UFSR_unsupported",
        "economic_endpoint_unavailable",
    ]
    warnings = review._remap_warnings(
        [
            {
                "code": code,
                "scope": "sections.source_returns",
                "severity": "warning",
                "message": "Synthetic source limitation",
            }
            for code in original
        ],
        extra=[],
    )
    assert sorted(row["code"] for row in warnings) == expected
    metric = adapter._metric(reasons=original)
    assert metric["value"] is None and metric["status"] == "unavailable"
    assert metric["reason_codes"] == expected
    assert adapter._reasons(["6_Unregistered_unsupported"]) == ["6_Unregistered_unsupported"]
    validator = Draft202012Validator({"$defs": SCHEMA["$defs"], "$ref": "#/$defs/reason_codes"})
    validator.validate(expected)
    with pytest.raises(ValidationError):
        validator.validate(adapter._reasons(["6_Unregistered_unsupported"]))


def test_source_analysis_allows_scientific_zero_without_losing_unsupported_reasons():
    _, doc, raw, report, money = investment_case()
    _, analyses = _derived(doc, raw, report, money)
    original = next(iter(analyses.values()))
    reasons = ("4_Transfers_unsupported", "5_UFSR_unsupported")
    analysis = replace(
        original,
        opening=replace(original.opening, quantity=Decimal("0E-12"), reason_codes=reasons),
        closing=replace(original.closing, quantity=Decimal("4.250000000000000000000000000001")),
        events=tuple(
            replace(e, quantity_delta=Decimal("0E-12"), reason_codes=reasons)
            for e in original.events
        ),
        coverage={
            key: replace(value, complete=False, reason_codes=reasons)
            for key, value in original.coverage.items()
        },
        pnl=replace(original.pnl, value=None, status="unavailable", reason_codes=reasons),
        reason_codes=reasons,
    )
    exported = adapter._instrument("RU000A000007", {"name": "Synthetic decimal security"}, analysis)
    Draft202012Validator(
        {"$defs": SCHEMA["$defs"], "$ref": "#/$defs/source_instrument"},
        format_checker=FormatChecker(),
    ).validate(exported)
    assert exported["opening"]["quantity"] == "0.000000000000"
    assert exported["closing"]["quantity"] == "4.250000000000000000000000000001"
    assert exported["metrics"]["pnl"]["value"] is None
    assert exported["metrics"]["pnl"]["status"] == "unavailable"
    expected = ["source_4_transfers_unsupported", "source_5_ufsr_unsupported"]
    assert exported["reason_codes"] == expected
    assert exported["opening"]["reason_codes"] == expected
    assert all(
        row["reason_codes"] == expected and not row["complete"]
        for row in exported["coverage"].values()
    )
    assert all(
        row["quantity_delta"] == "0.000000000000" and row["reason_codes"] == expected
        for row in exported["events"]
    )
    assert original.opening.quantity == Decimal("0")


def test_current_card_fixed_point_quantities_keep_null_and_money_units(database, monkeypatch):
    _save(database, monkeypatch)
    with database.session_factory() as session:
        overview = returns_overall.read_overall(session, include_instrument_details=True)
        raw = returns_overall.read_instrument_card(
            session, overview["instruments"][0]["isin"], overview=overview
        )
    raw["summary"]["quantity"]["value"] = "0E-12"
    raw["summary"]["quantity"]["reason_codes"] = ["4_Transfers_unsupported", "5_UFSR_unsupported"]
    row = raw["accounts"][0]
    row["detail"]["opening_quantity"] = "0E-12"
    row["detail"]["closing_quantity"] = None
    row["reason_codes"] = ["4_Transfers_unsupported", "5_UFSR_unsupported"]
    before = copy.deepcopy(raw)
    exported = adapter._overall_card(raw, {row["scope"]: "source-account-1"}, {}, {})
    Draft202012Validator(
        {"$defs": SCHEMA["$defs"], "$ref": "#/$defs/returns_instrument_card"},
        format_checker=FormatChecker(),
    ).validate(exported)
    assert exported["summary"]["quantity"]["value"] == "0.000000000000"
    assert exported["accounts"][0]["detail"]["opening_quantity"] == "0.000000000000"
    assert exported["accounts"][0]["detail"]["closing_quantity"] is None
    assert exported["accounts"][0]["reason_codes"] == [
        "source_4_transfers_unsupported",
        "source_5_ufsr_unsupported",
    ]
    assert exported["summary"]["pnl"] == adapter._overall_metric(raw["summary"]["pnl"])
    assert raw == before


@pytest.mark.parametrize("quantity", [None, "0E-12", "5E+3"])
def test_existing_portfolio_quantity_uses_exact_fixed_point_representation(monkeypatch, quantity):
    from hermes_finance.services import ai_financial_review as review

    for name in ("list_position_snapshots", "list_deposit_snapshots", "list_cash_balances"):
        monkeypatch.setattr(review, name, lambda _: [])
    data, notes = review._portfolio_data(
        None,
        {"data": {"accounts": [], "instruments": [], "items": [{"quantity": quantity}]}},
        {"cash_balances": [], "deposits": [], "valuation_freshness": {}},
        {},
        account_ref_by_id={},
        instrument_ref_by_id={},
        current_month_id=17,
    )
    actual = data["positions"][0]["quantity"]
    assert actual is None if quantity is None else Decimal(actual) == Decimal(quantity)
    assert actual is None or "e" not in actual.lower()
    assert notes == []


def test_gold_quantity_slots_and_independent_reasons_are_schema_safe():
    from hermes_finance.services.returns_view import metric

    history = _gold_history_fixture()
    history["declaration"]["current_quantity"] = "4E+0"
    history["events"][0]["grams"] = "6E+0"
    history["events"][1]["grams"] = "2E+0"
    history["valuation"]["quantity"] = "4E+0"
    history["result"]["calculated_quantity"] = None
    history["result"]["declared_calculated_quantity"] = "4E+0"
    original_reasons = ["4_Transfers_unsupported", "5_UFSR_unsupported"]
    history["reason_codes"] = original_reasons
    for name in (
        "reason_codes",
        "total_reason_codes",
        "realized_reason_codes",
        "unrealized_reason_codes",
        "decomposition_reason_codes",
    ):
        history["result"][name] = original_reasons
    raw = {
        "snapshots": [
            {
                "account_id": 40,
                "instrument_id": 90,
                "label": "Synthetic decimal gold",
                "date": END,
                "quantity": "0E-12",
                "market_value": metric(0),
                "cost_basis": metric(0),
                "unrealized_result": metric(),
                "cost_return": metric(unit="fraction"),
            }
        ],
        "period_result": metric(reasons=original_reasons),
        "reason_codes": original_reasons,
    }
    before = copy.deepcopy((raw, history))
    exported = adapter._overall_gold(raw, [history])
    Draft202012Validator(
        {"$defs": SCHEMA["$defs"], "$ref": "#/$defs/returns_gold"}, format_checker=FormatChecker()
    ).validate(exported)
    item = exported["histories"][0]
    assert exported["snapshots"][0]["quantity"] == "0.000000000000"
    assert item["declaration"]["current_quantity"] == item["valuation"]["quantity"] == "4"
    assert [row["grams"] for row in item["events"]] == ["6", "2"]
    assert item["revisions"][0]["declaration"]["current_quantity"] == "4"
    assert item["result"]["calculated_quantity"] is None
    assert item["result"]["declared_calculated_quantity"] == "4"
    expected = ["source_4_transfers_unsupported", "source_5_ufsr_unsupported"]
    assert all(
        item["result"][name] == expected
        for name in (
            "reason_codes",
            "total_reason_codes",
            "realized_reason_codes",
            "unrealized_reason_codes",
            "decomposition_reason_codes",
        )
    )
    assert exported["period_result"]["value"] is None
    assert (raw, history) == before


def _gold_history_fixture():
    events = [
        {
            "event_id": "private-buy",
            "event_date": "2030-01-03",
            "side": "BUY",
            "grams": "6",
            "amount_basis": "actual",
            "amount_kopecks": "30000",
            "unit_price_rub": None,
            "fee_state": "known_zero",
            "separate_fee_kopecks": "0",
        },
        {
            "event_id": "private-sell",
            "event_date": "2030-01-16",
            "side": "SELL",
            "grams": "2",
            "amount_basis": "derived_unit_price",
            "amount_kopecks": "14000",
            "unit_price_rub": "70",
            "fee_state": "known",
            "separate_fee_kopecks": "100",
        },
    ]
    declaration = {
        "contract_version": "owner_manual_gold_history_v1",
        "account_id": 40,
        "instrument_id": 90,
        "covered_from": "2030-01-01",
        "covered_to": "2030-01-31",
        "complete": True,
        "zero_start": True,
        "current_quantity": "4",
        "current_quantity_date": "2030-01-31",
        "provenance_reference": "D:\\private\\gold-notes",
        "change_reason": "private audit text",
        "events": events,
    }
    return {
        "contract_version": "owner_manual_gold_history_v1",
        "source_kind": "owner_manual_gold_history",
        "authority": "owner_attestation",
        "history_id": 70,
        "revision": 1,
        "account_id": 40,
        "instrument_id": 90,
        "currentness": "current",
        "declaration": declaration,
        "events": events,
        "events_loaded": True,
        "valuation": {
            "snapshot_id": 80,
            "date": "2030-01-29",
            "price_date": "2030-01-29",
            "snapshot_date": "2030-01-31",
            "quantity": "4",
            "market_value_kopecks": "26000",
            "price_source": "manual",
            "month_status": "closed",
            "provisional": False,
        },
        "result": {
            "total_result_kopecks": "9900",
            "realized_result_kopecks": "3900",
            "unrealized_result_kopecks": "6000",
            "remaining_cost_kopecks": "20000",
            "buy_amount_kopecks": "30000",
            "sale_amount_kopecks": "14000",
            "separate_fees_kopecks": "100",
            "net_sales_kopecks": "13900",
            "calculated_quantity": "4",
            "declared_calculated_quantity": "4",
            "as_of_date": "2030-01-29",
            "valuation_kopecks": "26000",
            "valuation_date": "2030-01-29",
            "valuation_basis": "saved_snapshot_quote",
            "valuation_provisional": False,
            "period": {"covered_from": "2030-01-01", "covered_to": "2030-01-29"},
            "amount_basis": "derived",
            "tax_treatment": "not_provided",
            "method": "owner_gold_complete_from_zero",
            "reason_codes": [],
            "total_reason_codes": [],
            "realized_reason_codes": [],
            "unrealized_reason_codes": [],
            "decomposition_reason_codes": [],
        },
        "reason_codes": [],
        "revisions": [
            {"revision": 1, "declaration": declaration, "accepted_at": "2030-02-01T00:00:00Z"}
        ],
    }


def test_full_gold_history_allowlist_preserves_basis_dates_fees_and_revision_refs():
    raw = _gold_history_fixture()
    baseline = copy.deepcopy(raw)
    exported = adapter._gold_history(
        raw, 1, {40: "returns-gold-account-1"}, {90: "returns-gold-instrument-1"}
    )
    assert raw == baseline
    assert exported["result"]["total_result"]["amount"] == "99.00"
    assert exported["result"]["valuation_date"] == "2030-01-29"
    assert exported["declaration"]["current_quantity_date"] == "2030-01-31"
    assert exported["events"][1]["amount_basis"] == "derived_unit_price"
    assert exported["events"][1]["separate_fee"]["amount"] == "1.00"
    assert exported["events"][0]["ref"] == exported["revisions"][0]["events"][0]["ref"]
    assert exported["result"]["tax_treatment"] == "not_provided"
    validator = Draft202012Validator(
        {"$defs": SCHEMA["$defs"], "$ref": "#/$defs/returns_gold_history"},
        format_checker=FormatChecker(),
    )
    validator.validate(exported)
    wire = json.dumps(exported)
    for forbidden in (
        "history_id",
        "account_id",
        "instrument_id",
        "snapshot_id",
        "event_id",
        "private-buy",
        "private-sell",
        "provenance_reference",
        "change_reason",
        "accepted_at",
        "private audit",
        "private\\\\gold-notes",
    ):
        assert forbidden not in wire
    for key in ("history_id", "account_id", "instrument_id", "provenance_reference", "request_id"):
        private = copy.deepcopy(exported)
        private[key] = "private-999"
        with pytest.raises(ValidationError):
            validator.validate(private)
    raw["valuation"] = None
    raw["result"].update(
        total_result_kopecks=None,
        unrealized_result_kopecks=None,
        as_of_date="2030-01-31",
        valuation_date=None,
        valuation_basis=None,
        valuation_provisional=None,
        period={"covered_from": "2030-01-01", "covered_to": "2030-01-31"},
        reason_codes=["gold_saved_valuation_unavailable"],
        total_reason_codes=["gold_saved_valuation_unavailable"],
        unrealized_reason_codes=["gold_saved_valuation_unavailable"],
    )
    partial = adapter._gold_history(
        raw, 1, {40: "returns-gold-account-1"}, {90: "returns-gold-instrument-1"}
    )
    validator.validate(partial)
    assert partial["result"]["total_result"] is None
    assert partial["result"]["unrealized_result"] is None
    assert partial["result"]["realized_result"]["amount"] == "39.00"
    assert partial["result"]["realized_reason_codes"] == []
    assert partial["result"]["as_of_date"] == "2030-01-31"
    assert partial["result"]["valuation_date"] is None
    raw["events_loaded"] = False
    with pytest.raises(ValueError, match="events_not_loaded"):
        adapter._gold_history(
            raw, 1, {40: "returns-gold-account-1"}, {90: "returns-gold-instrument-1"}
        )


def _save_manual_gold(database, *, quote=True, draft=False, unknown_fee=False):
    from hermes_finance.services.owner_manual_gold_history import (
        apply_gold_history,
        preview_gold_history,
    )

    with database.session_factory() as session:
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=END)
        account = Account(name="private-gold-account-424242", account_type="other")
        instrument = Instrument(name="Synthetic history gold", instrument_type="gold")
        session.add_all([account, instrument])
        session.flush()
        if quote:
            session.add(
                PositionSnapshot(
                    reporting_month_id=month.id,
                    account_id=account.id,
                    instrument_id=instrument.id,
                    quantity=Decimal("4"),
                    average_cost_per_unit_kopecks=5000,
                    market_price_per_unit_kopecks=6500,
                    market_value_kopecks=26000,
                    cost_basis_kopecks=20000,
                    unrealized_result_kopecks=6000,
                    price_date=date(2030, 1, 29),
                    manual_adjustment=False,
                )
            )
        month.status = "draft" if draft else "closed"
        account_id, instrument_id = account.id, instrument.id
        session.commit()
    intent = {
        "account_id": account_id,
        "instrument_id": instrument_id,
        "expected_revision": 0,
        "covered_from": "2030-01-01",
        "covered_to": "2030-01-31",
        "complete": True,
        "zero_start": True,
        "current_quantity": "4",
        "current_quantity_date": "2030-01-31",
        "provenance_reference": "D:\\private\\synthetic-history",
        "events": [
            {
                "event_id": "private-buy",
                "event_date": "2030-01-03",
                "side": "BUY",
                "grams": "6",
                "amount_basis": "actual",
                "amount_rub": "300.00",
                "fee_state": "unknown" if unknown_fee else "known_zero",
            },
            {
                "event_id": "private-sell",
                "event_date": "2030-01-16",
                "side": "SELL",
                "grams": "2",
                "amount_basis": "derived_unit_price",
                "unit_price_rub": "70.00",
                "fee_state": "known",
                "fee_rub": "1.00",
            },
        ],
    }
    with database.session_factory() as session:
        preview = preview_gold_history(session, intent)
        apply_gold_history(
            session,
            {
                **intent,
                "confirmation_digest": preview["confirmation_digest"],
                "request_id": "ai-synthetic-gold",
            },
        )
    return intent


@pytest.mark.parametrize("mode", ["closed", "draft", "missing_quote", "unknown_fee"])
def test_current_export_gold_history_matches_shared_producer_and_keeps_local_gaps(database, mode):
    from hermes_finance.services.owner_manual_gold_history import read_gold_histories

    _save_manual_gold(
        database,
        quote=mode != "missing_quote",
        draft=mode == "draft",
        unknown_fee=mode == "unknown_fee",
    )
    before = snapshot(database)
    with database.session_factory() as session:
        report = assemble_ai_financial_review(
            session, generated_at=datetime(2030, 2, 1, tzinfo=UTC), evaluated_on=date(2030, 2, 1)
        )
        producer = read_gold_histories(session)[0]
        ordinary = returns_overall.read_overall(session)
    current = report["sections"]["returns_overall"]["data"]
    history = current["gold"]["histories"][0]
    assert history["authority"] == "owner_attestation" and history["events_loaded"]
    assert len(history["events"]) == len(producer["events"]) == 2
    assert history["declaration"]["complete"] and history["declaration"]["zero_start"]
    for name in (
        "total_result",
        "realized_result",
        "unrealized_result",
        "remaining_cost",
        "buy_amount",
        "sale_amount",
        "separate_fees",
        "net_sales",
        "valuation",
    ):
        assert history["result"][name] == adapter._money(producer["result"][name + "_kopecks"])
    for name in (
        "as_of_date",
        "valuation_date",
        "valuation_basis",
        "valuation_provisional",
        "total_reason_codes",
        "realized_reason_codes",
        "unrealized_reason_codes",
    ):
        assert history["result"][name] == producer["result"][name]
    assert current["mixed_result"]["known_result"] == adapter._overall_metric(
        ordinary["mixed_result"]["known_result"]
    )
    if mode in {"closed", "draft"}:
        assert history["result"]["total_result"]["amount"] == "99.00"
        assert history["valuation"]["date"] == "2030-01-29"
        assert history["valuation"]["snapshot_date"] == "2030-01-31"
        assert history["valuation"]["provisional"] == (mode == "draft")
        assert current["mixed_result"]["known_result"]["value"]["amount"] == "99.00"
    if mode == "missing_quote":
        assert history["result"]["total_result"] is None
        assert history["result"]["unrealized_result"] is None
        assert history["result"]["realized_result"]["amount"] == "39.00"
        assert history["result"]["as_of_date"] == "2030-01-31"
        assert history["result"]["valuation_date"] is None
    if mode == "unknown_fee":
        assert history["events"][0]["separate_fee"] is None
        assert history["result"]["total_result"] is None
        assert history["result"]["net_sales"]["amount"] == "139.00"
    wire = json.dumps(current)
    for forbidden in (
        "private-gold-account-424242",
        "private-buy",
        "private-sell",
        "history_id",
        "account_id",
        "instrument_id",
        "snapshot_id",
        "event_id",
        "provenance_reference",
        "synthetic-history",
        "confirmation_digest",
        "request_id",
    ):
        assert forbidden not in wire
    validate_ai_financial_review(report)
    assert snapshot(database) == before


def test_monthly_reader_fallback_schema_and_partial_cutoff(database, monkeypatch):
    # Save only XML, without a confirmed investment-PDF proof.
    saved_investment_preview(database, monkeypatch)
    with database.session_factory() as session:
        section = _section(session)
        partial = _section(session, date(2030, 1, 20))
    row = _first(section)
    assert row["source_contract"] == "source_monthly_returns/instrument_return_v2"
    assert row["account"]["metrics"]["xirr_annualized"]["value"] is None
    assert row["account"]["detail_status"] == "account_only_not_projected"
    assert row["instruments"]
    Draft202012Validator(
        {"$defs": SCHEMA["$defs"], "$ref": "#/$defs/source_returns_section"},
        format_checker=FormatChecker(),
    ).validate(section)
    account = partial["data"]["accounts"][0]
    assert not account["selected_month"]["complete_calendar_month"]
    assert account["selected_month"]["through_date"] == "2030-01-20"
    assert account["selected_month"]["interval_ref"] is None
    assert account["monthly_history_refs"] == []


def test_producer_local_bad_instrument_retains_known_coupon_and_good_neighbor():
    from hermes_finance.domain.money_security import MoneySecurity

    service, doc, raw, report, money = investment_case()
    bad_isin = "RU000A000001"
    position = {
        **doc["positions"][0],
        "isin": bad_isin,
        "beginning_actual_quantity": "0",
        "actual_quantity": "1",
        "beginning_value": "0",
        "ending_value": None,
    }
    doc["positions"].append(position)
    report = replace(report, positions={**report.positions, ("1234567", bad_isin): ("1", None)})
    coupon = {
        **money[0],
        "ref": "synthetic-coupon",
        "minor": 12000,
        "classification": "coupon",
        "security": MoneySecurity("1-01-12345-A", "Synthetic", "coupon"),
    }
    money.append(coupon)
    analyses = {}
    raw_interval = service._interval(
        doc,
        raw,
        report,
        money,
        {coupon["ref"]: (bad_isin, "1-01-12345-A")},
        {},
        True,
        analyses=analyses,
    )
    proof = {
        "covered_from": doc["covered_from"],
        "covered_to": doc["covered_to"],
        "history_from_zero": True,
        "status": "current",
        "reason_codes": [],
        "interval": raw_interval,
    }
    rows = adapter._proof_interval(proof, analyses, {})["instruments"]
    good, bad = rows
    assert good["metrics"]["pnl"]["value"]["amount"] == "90.00"
    assert bad["metrics"]["pnl"]["value"] is None
    assert bad["components"]["coupons"]["value"]["amount"] == "120.00"
    assert bad["components"]["coupons"]["status"] in {"supported", "provisional"}
    assert (
        next(e for e in bad["events"] if e["kind"] == "COUPON")["net_payout"]["amount"] == "120.00"
    )


def test_snapshot_proof_derivation_is_bounded_copy_isolated_and_discarded(database, monkeypatch):
    from calendar import monthrange
    from datetime import timedelta

    from hermes_finance.services.source_instrument_returns import read_instrument_returns
    from hermes_finance.services.source_monthly_returns import (
        _SOURCE_INVESTMENT_READS,
        source_read_snapshot,
    )

    _save(database, monkeypatch)
    original = proofs._derive
    calls = []

    def derive(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(proofs, "_derive", derive)
    with database.session_factory() as session:
        with source_read_snapshot(session):
            first = proofs.read_reports(session, source_account=ACCOUNT)
            first[0]["interval"]["pnl"]["value"] = "-999"
            for month in range(1, 13):
                day = date(2030, month, 1)
                read_instrument_returns(
                    session,
                    source_account=ACCOUNT,
                    opening_date=day - timedelta(days=1),
                    closing_date=day.replace(day=monthrange(2030, month)[1]),
                    include_monthly_history=False,
                )
            captured = {}
            again = proofs.read_reports(session, source_account=ACCOUNT, analyses=captured)
            assert again[0]["interval"]["pnl"]["value"] == "9000"
            assert captured
            assert len(calls) == 1
        assert _SOURCE_INVESTMENT_READS not in session.info
        row = session.scalar(
            select(SourceMoneyClassification).order_by(SourceMoneyClassification.id)
        )
        row.classification = "unknown" if row.classification != "unknown" else "fee"
        session.commit()
        fresh = proofs.read_reports(session, source_account=ACCOUNT)
        assert fresh[0]["status"] == "stale" and fresh[0]["interval"] is None
        assert len(calls) == 2
        with pytest.raises(RuntimeError, match="synthetic exit"):
            with source_read_snapshot(session):
                proofs.read_reports(session, source_account=ACCOUNT)
                raise RuntimeError("synthetic exit")
        assert _SOURCE_INVESTMENT_READS not in session.info


def test_all_history_same_end_uses_ordinary_latest_proof_tiebreak(database, monkeypatch):
    from datetime import timedelta

    _, doc, raw, report, money = investment_case()
    proof, original = _derived(doc, raw, report, money)
    older = copy.deepcopy(proof)
    older.update(proof_id=1, covered_from="2028-01-01")
    older["interval"]["opening_date"] = "2027-12-31"
    newer = copy.deepcopy(proof)
    newer.update(proof_id=2, covered_from="2029-01-01")
    newer["interval"]["opening_date"] = "2028-12-31"
    captured = {}
    for p in (older, newer):
        start = date.fromisoformat(p["covered_from"]) - timedelta(days=1)
        captured[p["proof_id"]] = {
            isin: replace(
                a,
                opening_date=start,
                opening=replace(a.opening, date=start),
                history_start=start + timedelta(days=1),
            )
            for isin, a in original.items()
        }

    def reports(session, **kwargs):
        kwargs["analyses"].update(copy.deepcopy(captured))
        return [newer, older]

    monkeypatch.setattr(proofs, "read_reports", reports)
    monkeypatch.setattr(adapter, "_source_scopes", lambda s: {})
    monkeypatch.setattr(adapter, "_selected_sources", lambda *a: ([], None))
    monkeypatch.setattr(
        adapter, "read_monthly_returns", lambda *a, **kw: SimpleNamespace(months=())
    )
    with database.session_factory() as session:
        section = _section(session)
        ordinary = proofs.instrument_result(session, "private-999", [], None, None, None)
    account = section["data"]["accounts"][0]
    chosen = next(i for i in account["intervals"] if i["ref"] == account["all_history_ref"])
    assert (
        chosen["opening_date"] == str(ordinary.instruments[0].analysis.opening_date) == "2028-12-31"
    )


def test_event_cash_eligibility_at_both_boundaries_preserves_producer_result():
    from hermes_finance.domain.instrument_return import (
        CashLeg,
        InstrumentEvent,
        calculate_economics,
    )

    _, doc, raw, report, money = investment_case()
    _, analyses = _derived(doc, raw, report, money)
    a = next(iter(analyses.values()))
    late = InstrumentEvent(
        event_key="late-private",
        provider="private",
        native_source_account="private",
        isin="RU000A000000",
        kind="BUY",
        source_references=(),
        event_date=END,
        cash_settlement_date=date(2030, 2, 1),
        depository_settlement_date=END,
        quantity_delta=Decimal(1),
        native_trade_amount_kopecks=100000,
        cash_legs=(CashLeg("trade", date(2030, 2, 1), -100000, 100000, (), "late"),),
        reason_codes=("cross_boundary_settlement",),
    )
    early = replace(
        late,
        event_key="early-private",
        event_date=date(2030, 1, 2),
        cash_settlement_date=date(2030, 1, 2),
        depository_settlement_date=date(2030, 1, 2),
        cash_legs=(
            CashLeg("commission", START, -1000, 1000, (), "earlier"),
            CashLeg("trade", date(2030, 1, 2), -50000, 50000, (), "inside"),
        ),
    )
    components, pnl, known, dietz, estimate = calculate_economics(
        a.opening, a.closing, (late, early), a.coverage
    )
    a = replace(
        a,
        events=(late, early),
        components=components,
        pnl=pnl,
        known_subtotal=known,
        modified_dietz=dietz,
        statement_estimate=estimate,
    )
    exported = adapter._instrument("RU000A000000", {}, a)
    early_row, late_row = exported["events"]
    assert late_row["producer_eligible"] and not late_row["counted"]
    assert late_row["cash_date"] == "2030-02-01" and late_row["trade_amount"] is None
    assert late_row["cash_legs"][0]["account_cash"] is None
    assert not late_row["cash_legs"][0]["included_in_interval"]
    assert early_row["counted"] and early_row["cash_scope"] == "cross_boundary"
    assert early_row["cash_legs"][0]["account_cash"] is None
    assert not early_row["cash_legs"][0]["included_in_interval"]
    assert early_row["cash_legs"][1]["account_cash"]["amount"] == "-500.00"
    assert early_row["cash_legs"][1]["included_in_interval"]
    assert exported["metrics"]["pnl"]["value"] == adapter._money(pnl.value)
    assert pnl.value == 60000  # 1100 endpoint minus the sole in-window 500 purchase
