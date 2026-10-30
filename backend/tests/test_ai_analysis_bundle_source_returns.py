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
from hermes_finance.persistence import SourceMoneyClassification
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
        interval = _first(exported)
        instrument = interval["instruments"][0]
        ordinary = proofs.read_reports(session, source_account=ACCOUNT)[0]["interval"]
        view = read_overview(session, scope=f"source:{ACCOUNT}", start=START, end=END)
        detail = read_detail(
            session, scope=f"source:{ACCOUNT}", start=START, end=END, isin=instrument["isin"]
        )
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
    wire = json.dumps(exported)
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
        section = _section(session)
    row = _first(section)
    assert row["currentness"] == "stale" and row["reason_codes"]
    assert row["account"] is None and row["instruments"] == []
    account = section["data"]["accounts"][0]
    assert account["all_history_ref"] == row["ref"]
    assert account["selected_month"]["interval_ref"] == row["ref"]


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
