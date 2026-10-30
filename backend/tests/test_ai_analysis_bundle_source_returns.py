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
from hermes_finance.services import ai_source_returns as adapter
from hermes_finance.services import returns_overall
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
        create_reporting_month(session, year=2030, month=1, snapshot_date=END)
    before = snapshot(database)
    with database.session_factory() as session:
        report = assemble_ai_financial_review(
            session, generated_at=datetime(2030, 2, 1, tzinfo=UTC), evaluated_on=date(2030, 1, 15)
        )
    history = report["sections"]["source_returns"]["data"]
    current = report["sections"]["returns_overall"]["data"]
    assert history["as_of_date"] == "2030-01-15"
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
    assert saved["date"] == "2030-01-29" and saved["quantity"] == "2"
    for name in ("market_value", "cost_basis", "unrealized_result", "cost_return"):
        assert saved[name] == adapter._overall_metric(ordinary["gold"]["snapshots"][0][name])
    assert saved["cost_return"]["value"] == "49.00"
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
