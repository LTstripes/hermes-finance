"""Synthetic parity/currentness checks for the presentation read optimizations."""

import json
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import date
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import event, select
from test_returns_view_service import END, SCOPE, START, basket_source
from test_source_instrument_returns_service import save
from test_source_monthly_returns_service import snapshot
from test_statement_import_mybroker import ACCOUNT
from test_statement_import_mybroker_preflight import investment_case, saved_investment_preview

from hermes_finance.persistence import SourceMoneyClassification, SourceReturnProof
from hermes_finance.services import returns_view, source_intake
from hermes_finance.services import source_investment_proofs as proofs
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.source_money_classifications import choose_classification
from hermes_finance.services.source_monthly_returns import (
    _selected_sources,
    source_read_snapshot,
)


@pytest.fixture
def db(tmp_path, source_returns_database_factory):
    database = source_returns_database_factory(tmp_path)
    yield database
    database.engine.dispose()


PROOF_START, PROOF_END = date(2029, 12, 31), date(2030, 1, 31)


def test_proved_scope_map_reuses_only_one_snapshot_and_returns_owned_maps(db, monkeypatch):
    basket_source(db)
    original = returns_view._selected_sources
    calls = []

    def selected(session, account, **kwargs):
        calls.append(account)
        return original(session, account, **kwargs)

    monkeypatch.setattr(returns_view, "_selected_sources", selected)
    with db.session_factory() as session:
        with source_read_snapshot(session):
            first = returns_view._source_scopes(session)
            assert first["1234567"] == ACCOUNT
            captured = len(calls)
            first["1234567"] = "caller-mutation"
            second = returns_view._source_scopes(session)
            assert second["1234567"] == ACCOUNT
            assert len(calls) == captured
        assert "returns_source_scope_reads" not in session.info
        with source_read_snapshot(session):
            assert returns_view._source_scopes(session)["1234567"] == ACCOUNT
        assert len(calls) > captured
    basket_source(db, native="7654321-000", alias="7654321")
    with db.session_factory() as session, source_read_snapshot(session):
        actual = returns_view._source_scopes(session)
        assert actual["7654321"] == "7654321-000"
        assert actual["1234567"] == ACCOUNT


def test_payout_heads_reused_only_within_snapshot_and_are_owned(db, monkeypatch):
    from hermes_finance.services import broker_money, source_return_evidence

    calls = []

    def latest(_session):
        calls.append(1)
        return {"key": {"value": len(calls)}}

    monkeypatch.setattr(broker_money, "latest_proofs", latest)
    with db.session_factory() as session:
        with source_read_snapshot(session):
            first = source_return_evidence._payout_money_heads(session)
            first["key"]["value"] = 99
            assert source_return_evidence._payout_money_heads(session)["key"]["value"] == 1
            assert len(calls) == 1
        with source_read_snapshot(session):
            assert source_return_evidence._payout_money_heads(session)["key"]["value"] == 2
        assert len(calls) == 2


def test_failed_scope_read_does_not_leave_reusable_state(db, monkeypatch):
    basket_source(db)
    original = returns_view._selected_sources

    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic source read failed")

    with db.session_factory() as session:
        with monkeypatch.context() as patch:
            patch.setattr(returns_view, "_selected_sources", unavailable)
            with pytest.raises(RuntimeError, match="synthetic source read failed"):
                with source_read_snapshot(session):
                    returns_view._source_scopes(session)
        assert "returns_source_scope_reads" not in session.info
        monkeypatch.setattr(returns_view, "_selected_sources", original)
        with source_read_snapshot(session):
            assert returns_view._source_scopes(session)["1234567"] == ACCOUNT


def test_identity_projection_never_replaces_or_exposes_cached_financial_view(db):
    basket_source(db)
    with db.session_factory() as session, source_read_snapshot(session):
        projected, native = _selected_sources(session, ACCOUNT, identity_only=True)
        assert native == {ACCOUNT}
        descriptor = projected[0][1]
        assert set(descriptor) == {"document", "native_scope"}
        assert descriptor["native_scope"] == frozenset({ACCOUNT})
        assert set(descriptor["document"]) == {"filename_account"}
        descriptor["document"]["filename_account"] = "caller-mutation"
        complete, actual = _selected_sources(session, ACCOUNT)
        assert actual == native
        assert complete[0][1]["document"]["filename_account"] == "1234567"
        assert "money" in complete[0][1]["document"]
        complete[0][1]["document"]["filename_account"] = "other-mutation"
        again, _ = _selected_sources(session, ACCOUNT, identity_only=True)
        assert again[0][1]["document"]["filename_account"] == "1234567"
        with pytest.raises(ValueError, match="only a read-only source selection"):
            _selected_sources(session, ACCOUNT, reserved=True, identity_only=True)


def _saved_investment(db, monkeypatch):
    persistence = saved_investment_preview(db, monkeypatch)["persistence"]
    with db.session_factory() as session:
        proofs.confirm(
            session,
            **{k: persistence[k] for k in ("form_token", "preview_digest")},
            request_id="read-efficiency-proof",
        )


def test_clean_ui_and_ai_use_current_exact_investment_proof_with_fee_mismatch(db, monkeypatch):
    from datetime import UTC, datetime

    import test_statement_import_mybroker_preflight as fixture_module
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app
    from hermes_finance.services.ai_financial_review import assemble_ai_financial_review
    from hermes_finance.services.clean_instrument_return import read_clean_overview

    original = fixture_module.investment_original

    def with_different_fee():
        root = ET.fromstring(original())
        root.find(".//{MyBroker}Details[@trade_no]").set("summ_nkd", "0")
        for row in root.findall(".//{MyBroker}rn"):
            operation = row.find("{MyBroker}oper_type")
            if operation.get("oper_type", "").startswith("Комиссия по сделке"):
                row.find(".//{MyBroker}p_code[@volume]").set("volume", "-11.00")
        return ET.tostring(root, encoding="utf-8")

    monkeypatch.setattr(fixture_module, "investment_original", with_different_fee)
    _saved_investment(db, monkeypatch)
    with db.session_factory() as session:
        create_reporting_month(session, year=2030, month=1, snapshot_date=PROOF_END)
    before = snapshot(db)
    with db.session_factory() as session:
        from hermes_finance.services.source_instrument_returns import read_instrument_returns

        source = read_instrument_returns(
            session,
            source_account=ACCOUNT,
            opening_date=PROOF_START,
            closing_date=PROOF_END,
            available_period=True,
        )
        analysis = source.instruments[0].analysis
        assert analysis.events[0].native_trade_amount_kopecks is not None, (
            analysis.events,
            analysis.reason_codes,
            analysis.coverage,
        )
        assert getattr(analysis.coverage, "fee_only_bridge", False), (
            analysis.reason_codes,
            analysis.coverage,
            source.instruments[0].instrument_type,
        )
        assert source.instruments[0].instrument_type == "stock", source.instruments[0]
        from hermes_finance.services.clean_instrument_return import project_clean_analysis

        direct = project_clean_analysis(analysis, "RU000A000000", instrument_type="stock")
        assert direct.pnl.value == 10000, (direct, analysis)
        clean = read_clean_overview(session)
        assert clean["accounts"][0]["period"] == {"start": PROOF_START, "end": PROOF_END}, clean[
            "accounts"
        ][0]["period"]
        row = clean["accounts"][0]["result"]["instruments"][0]
        assert row["buys"]["value"] == "100000", row
        assert row["pnl"]["value"] == "10000"
        ai = assemble_ai_financial_review(
            session,
            generated_at=datetime(2030, 2, 1, tzinfo=UTC),
            evaluated_on=date(2030, 2, 1),
        )
        ai_row = ai["sections"]["clean_returns"]["data"]["accounts"][0]["instruments"][0]
        assert ai_row["pnl"]["value"] == "10000"
    response = TestClient(create_app(database=db)).get(
        "/api/returns/overall?include_instrument_summaries=true"
    )
    assert response.status_code == 200
    assert response.json()["instruments"][0]["accounts"][0]["pnl"]["value"] == "10000"
    assert snapshot(db) == before


def test_available_period_without_dates_keeps_native_reader(db, monkeypatch):
    from hermes_finance.services.source_instrument_returns import read_instrument_returns

    _saved_investment(db, monkeypatch)

    def unexpected_proof(*args, **kwargs):
        pytest.fail("an unbounded available period must not select the latest investment proof")

    monkeypatch.setattr(proofs, "instrument_result", unexpected_proof)
    with db.session_factory() as session:
        assert read_instrument_returns(session, source_account=ACCOUNT, available_period=True)


def test_clean_exact_period_does_not_drop_other_overlapping_source_instruments(db, monkeypatch):
    from hermes_finance.services.clean_instrument_return import read_clean_overview

    _saved_investment(db, monkeypatch)
    save(db, month=1, stock=None, bond=("0", "1", "0", "1100"), trades=(), marker="second")
    with db.session_factory() as session:
        overview = read_clean_overview(session)
    isins = {
        row["isin"] for account in overview["accounts"] for row in account["result"]["instruments"]
    }
    assert {"RU000A000000", "RU000A000001"} <= isins


def test_empty_exact_proof_does_not_hide_available_native_instrument(db, monkeypatch):
    from hermes_finance.services.source_instrument_returns import (
        SourceInstrumentReturns,
        read_instrument_returns,
    )

    _saved_investment(db, monkeypatch)
    monkeypatch.setattr(
        proofs,
        "instrument_result",
        lambda *args, **kwargs: SourceInstrumentReturns(ACCOUNT, (), (), ()),
    )
    with db.session_factory() as session:
        result = read_instrument_returns(
            session,
            source_account=ACCOUNT,
            opening_date=PROOF_START,
            closing_date=PROOF_END,
            available_period=True,
        )
    assert any(row.isin == "RU000A000000" for row in result.instruments)


def test_stale_exact_proof_keeps_available_native_observations(db, monkeypatch):
    from hermes_finance.services.source_instrument_returns import read_instrument_returns

    _saved_investment(db, monkeypatch)
    with db.session_factory() as session:
        classification = session.scalar(
            select(SourceMoneyClassification).order_by(SourceMoneyClassification.id)
        )
        classification.classification = (
            "unknown" if classification.classification != "unknown" else "fee"
        )
        session.commit()
    with db.session_factory() as session:
        assert proofs.read_reports(session, source_account=ACCOUNT)[0]["status"] == "stale"
        result = read_instrument_returns(
            session,
            source_account=ACCOUNT,
            opening_date=PROOF_START,
            closing_date=PROOF_END,
            available_period=True,
        )
    row = next(row for row in result.instruments if row.isin == "RU000A000000")
    assert "investment_proof_stale" not in row.analysis.reason_codes


def test_backup_copy_stale_proof_preserves_observed_clean_components(db, monkeypatch, tmp_path):
    from shutil import copyfile

    import test_statement_import_mybroker_preflight as fixture_module
    from fastapi.testclient import TestClient

    from hermes_finance.database import create_database
    from hermes_finance.main import create_app
    from hermes_finance.services.clean_instrument_return import read_clean_account

    original = fixture_module.investment_original

    def stock_without_nkd():
        root = ET.fromstring(original())
        root.find(".//{MyBroker}Details[@trade_no]").set("summ_nkd", "0")
        return ET.tostring(root, encoding="utf-8")

    monkeypatch.setattr(fixture_module, "investment_original", stock_without_nkd)
    _saved_investment(db, monkeypatch)
    with db.session_factory() as session:
        create_reporting_month(session, year=2030, month=1, snapshot_date=PROOF_END)
    db.engine.dispose()
    copy_path = tmp_path / "synthetic-backup-copy.sqlite3"
    copyfile(db.database_path, copy_path)
    copied = create_database(copy_path)
    try:
        before = snapshot(copied)
        before_bytes = copy_path.read_bytes()
        with copied.session_factory() as session:
            assert proofs.read_reports(session, source_account=ACCOUNT)[0]["status"] == "stale"
            clean = read_clean_account(
                session,
                ACCOUNT,
                PROOF_START,
                PROOF_END,
                isin="RU000A000000",
                include_purchases=True,
            )
        row = clean["instruments"][0]
        assert row["buys"]["value"] == "100000", row
        assert row["closing_value"]["value"] == "110000", row
        assert row["pnl"]["value"] == "10000", row
        with TestClient(create_app(copied)) as client:
            response = client.get("/api/returns/instrument-card", params={"isin": "RU000A000000"})
            ai = client.get("/api/export/ai-financial-review/json")
        assert response.status_code == 200
        assert ai.status_code == 200
        account = response.json()["accounts"][0]
        ai_account = ai.json()["sections"]["clean_returns"]["data"]["accounts"][0]
        assert account["clean"]["buys"]["value"] == "100000"
        assert account["clean"]["closing_value"]["value"] == "110000"
        assert account["ai_account_ref"] == ai_account["account_ref"]
        assert account["period"] == ai_account["period"]
        assert ai_account["instruments"][0]["buys"]["value"] == "100000"
        assert snapshot(copied) == before
        assert copy_path.read_bytes() == before_bytes
    finally:
        copied.engine.dispose()


@pytest.mark.parametrize(
    "revision",
    [
        "source_investment_semantics_v3",
        "source_investment_semantics_v18",
        "source_investment_semantics_v19",
        "source_investment_semantics_v20",
        "source_investment_semantics_v21",
    ],
)
def test_previous_proof_remains_current_only_with_exact_unchanged_dependencies(
    db, monkeypatch, revision
):
    with monkeypatch.context() as previous:
        previous.setattr(proofs, "SEMANTICS_REVISION", revision)
        _saved_investment(db, previous)
        with db.session_factory() as session:
            old = proofs.read_reports(session, source_account=ACCOUNT)[0]
    before = snapshot(db)
    with db.session_factory() as session:
        current = proofs.read_reports(session, source_account=ACCOUNT)[0]
    assert old["status"] == current["status"] == "current"
    assert old["interval"] == current["interval"]
    assert snapshot(db) == before
    with db.session_factory() as session:
        selected, _ = _selected_sources(session, ACCOUNT)
        view = selected[0][1]
        decision = view["money_classifications"][0]
        intake_id = view["id"]
    with db.session_factory() as writer:
        choose_classification(writer, intake_id, decision["source_reference"], "fee")
    with db.session_factory() as session:
        changed = proofs.read_reports(session, source_account=ACCOUNT)[0]
    assert changed["status"] == "stale"
    assert "investment_proof_dependencies_changed" in changed["reason_codes"]


def _append_stale_proof(db, *, other_period=False):
    # Deliberately invalid synthetic append: a latest stale row must never expose
    # an older proof's numbers, nor affect an independently selected interval.
    with db.session_factory() as session:
        original = session.scalar(select(SourceReturnProof))
        values = {
            column.name: getattr(original, column.name)
            for column in SourceReturnProof.__table__.columns
            if column.name != "id"
        }
        plan = json.loads(original.evidence_json)
        if other_period:
            plan["covered_to"] = "2030-02-28"
        values.update(
            request_id="read-efficiency-stale",
            dependency_digest="0" * 64,
            evidence_json=json.dumps(plan),
        )
        row = SourceReturnProof(**values)
        session.add(row)
        session.commit()
        return row.id


def test_context_reads_only_saved_proof_metadata_even_when_latest_proof_is_stale(db, monkeypatch):
    _saved_investment(db, monkeypatch)
    latest = _append_stale_proof(db)
    before = snapshot(db)

    def unexpected(*args, **kwargs):
        raise AssertionError("navigation derived numeric proof/currentness")

    with monkeypatch.context() as patch:
        patch.setattr(proofs, "_derive", unexpected)
        with db.session_factory() as session:
            headers = proofs.read_report_headers(session, source_account=ACCOUNT)
            context = returns_view.read_context(session)
    assert headers == [
        {
            "proof_id": latest,
            "source_account": "1234567",
            "covered_from": "2030-01-01",
            "covered_to": "2030-01-31",
            "history_from_zero": True,
        }
    ]
    assert returns_view.bounds(PROOF_START, PROOF_END) in context["source_periods"][SCOPE]
    with db.session_factory() as session:
        numeric = proofs.read_reports(session, source_account=ACCOUNT)
    assert len(numeric) == 1 and numeric[0]["proof_id"] == latest
    assert numeric[0]["status"] == "stale" and numeric[0]["interval"] is None
    assert snapshot(db) == before


def test_detail_derives_only_exact_period_and_matches_unfiltered_proof_reader(db, monkeypatch):
    _saved_investment(db, monkeypatch)
    unrelated = _append_stale_proof(db, other_period=True)
    before = snapshot(db)
    derive = proofs._derive
    calls = Counter()

    def counted(session, row, plan, **kwargs):
        calls[row.id] += 1
        return derive(session, row, plan, **kwargs)

    monkeypatch.setattr(proofs, "_derive", counted)
    with db.session_factory() as session:
        selected = returns_view.read_detail(
            session, scope=SCOPE, start=PROOF_START, end=PROOF_END, isin="RU000A000000"
        )
    assert len(calls) == 1 and sum(calls.values()) == 1 and unrelated not in calls
    reports = proofs.read_reports

    def unfiltered(*args, **kwargs):
        kwargs.pop("opening_date", None)
        kwargs.pop("closing_date", None)
        kwargs.pop("requested_isin", None)
        return reports(*args, **kwargs)

    monkeypatch.setattr(proofs, "read_reports", unfiltered)
    calls.clear()
    with db.session_factory() as session:
        baseline = returns_view.read_detail(
            session, scope=SCOPE, start=PROOF_START, end=PROOF_END, isin="RU000A000000"
        )
    assert selected == baseline
    assert len(calls) == 2 and set(calls.values()) == {1} and unrelated in calls
    assert snapshot(db) == before


def test_overview_reuses_proof_once_and_snapshots_revalidate_without_mutable_leaks(db, monkeypatch):
    _saved_investment(db, monkeypatch)
    derive = proofs._derive
    calls = Counter()

    def counted(session, row, plan, **kwargs):
        calls[row.id] += 1
        return derive(session, row, plan, **kwargs)

    monkeypatch.setattr(proofs, "_derive", counted)
    with db.session_factory() as session:
        result = returns_view.read_overview(session, scope=SCOPE, start=PROOF_START, end=PROOF_END)
        assert result["selected"]["pnl"]["value"] == "9000"
        assert list(calls.values()) == [1]
        with source_read_snapshot(session):
            captured = {}
            first = proofs.read_reports(session, source_account=ACCOUNT, analyses=captured)
            proof_id = first[0]["proof_id"]
            first[0]["interval"]["pnl"]["value"] = "-999"
            captured[proof_id].clear()
            again = {}
            current = proofs.read_reports(
                session,
                source_account=ACCOUNT,
                analyses=again,
                opening_date=PROOF_START,
                closing_date=PROOF_END,
            )
            assert current[0]["interval"]["pnl"]["value"] == "9000"
            assert again[proof_id]
            assert list(calls.values()) == [2]
        row = session.scalar(
            select(SourceMoneyClassification).order_by(SourceMoneyClassification.id)
        )
        row.classification = "unknown" if row.classification != "unknown" else "fee"
        session.commit()
        stale = returns_view.read_detail(
            session, scope=SCOPE, start=PROOF_START, end=PROOF_END, isin="RU000A000000"
        )
        assert stale["pnl"]["value"] is None and stale["rate"]["value"] is None
        assert "investment_proof_stale" in stale["reason_codes"]
        assert list(calls.values()) == [3]


def _many_instrument_case(count=4):
    service, document, raw, report, money = investment_case()
    trade, position = document["trades"][0], document["positions"][0]
    _, names, _, cancellations = service._native(document, raw)
    trades, positions, monies = [], [], []
    for index in range(count):
        isin = f"RU{index:010d}"
        ids = {value: f"{index + 1}{value}" for value in trade["ids"]}
        copied = deepcopy(trade)
        copied["core"]["isin"] = isin
        copied["ids"] = [ids[value] for value in trade["ids"]]
        trades.append(copied)
        positions.append({**position, "isin": isin})
        for row in money:
            copied = {**row, "ref": f"{index}:{row['ref']}"}
            for key in ("primary_id", "native_token"):
                if copied.get(key) in ids:
                    copied[key] = ids[copied[key]]
            for previous, current in ids.items():
                copied["operation"] = copied["operation"].replace(previous, current)
            monies.append(copied)
    document["trades"], document["positions"] = trades, positions
    document["rub_money"][0]["ending_amount"] = str(990 * count)
    report = replace(
        report,
        closing={"1234567": 209000 * count},
        reported_pnl={"1234567": 9000 * count},
        positions={("1234567", p["isin"]): ("10", 110000) for p in positions},
    )
    native = {"names": names, "cancellations": cancellations, "unresolved": []}
    return service, document, report, monies, native


def test_instrument_projection_preserves_account_controls_and_selected_analysis(monkeypatch):
    service, document, report, money, native = _many_instrument_case()
    original_rates = service._rates
    calls = []

    def rates(*args, **kwargs):
        calls.append(1)
        return original_rates(*args, **kwargs)

    monkeypatch.setattr(service, "_rates", rates)
    full_analyses, projected_analyses = {}, {}
    full = service._interval(
        document,
        None,
        report,
        money,
        {},
        {},
        True,
        native_evidence=native,
        analyses=full_analyses,
    )
    assert len(calls) == 5  # Four instrument schedules and the full account.
    calls.clear()
    selected_isin = document["positions"][0]["isin"]
    projected = service._interval(
        document,
        None,
        report,
        money,
        {},
        {},
        True,
        native_evidence=native,
        analyses=projected_analyses,
        requested_isin=selected_isin,
    )
    assert len(calls) == 2
    assert projected_analyses == {selected_isin: full_analyses[selected_isin]}
    assert projected == {
        **full,
        "instruments": [p for p in full["instruments"] if p["isin"] == selected_isin],
    }
    assert projected["pnl"]["value"] == "36000"
    # An unrelated duplicate source position remains a whole-source refusal.
    document["positions"].append(document["positions"][-1])
    with pytest.raises(ValueError, match="source_return_duplicate_position"):
        service._interval(
            document,
            None,
            report,
            money,
            {},
            {},
            True,
            native_evidence=native,
            requested_isin=selected_isin,
        )


def test_targeted_proof_cache_cannot_seed_a_complete_read(db, monkeypatch):
    _saved_investment(db, monkeypatch)
    derive = proofs._derive
    requests = []

    def counted(*args, **kwargs):
        requests.append(kwargs.get("requested_isin"))
        return derive(*args, **kwargs)

    monkeypatch.setattr(proofs, "_derive", counted)
    with db.session_factory() as session:
        with source_read_snapshot(session):
            projected = proofs.read_reports(
                session, source_account=ACCOUNT, requested_isin="RU0000000001"
            )
            assert projected[0]["interval"]["instruments"] == []
            full = proofs.read_reports(session, source_account=ACCOUNT)
            assert full[0]["interval"]["instruments"]
            projected_again = proofs.read_reports(
                session, source_account=ACCOUNT, requested_isin="RU0000000001"
            )
            assert projected_again == projected
            assert requests == ["RU0000000001", None]


@pytest.mark.parametrize("conflict", [False, True])
def test_summary_defers_only_xirr_preserving_all_economics_and_controls(monkeypatch, conflict):
    service, document, report, money, native = _many_instrument_case()
    if conflict:
        document["rub_money"][0]["ending_amount"] = "1"
    chain = service.calculate_monthly_return_chain
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return chain(*args, **kwargs)

    monkeypatch.setattr(service, "calculate_monthly_return_chain", counted)
    full_analyses, summary_analyses = {}, {}
    full = service._interval(
        document,
        None,
        report,
        money,
        {},
        {},
        True,
        native_evidence=native,
        analyses=full_analyses,
    )
    assert len(calls) == 5
    calls.clear()
    summary = service._interval(
        document,
        None,
        report,
        money,
        {},
        {},
        True,
        native_evidence=native,
        analyses=summary_analyses,
        include_xirr=False,
    )
    assert calls == []
    assert summary == service._defer_xirr(deepcopy(full))
    assert summary_analyses == full_analyses
    assert ("source_control_mismatch" in summary["reason_codes"]) == conflict
    for row in (summary, *summary["instruments"]):
        for field in ("xirr_annualized", "xirr_period"):
            assert row[field]["value"] is None
            assert row[field]["status"] == "unavailable"
            assert row[field]["reason_codes"] == ["not_requested"]
    money[-1]["source_account"] = "7654321-000"
    with pytest.raises(ValueError, match="source_return_money_account_conflict"):
        service._interval(
            document,
            None,
            report,
            money,
            {},
            {},
            True,
            native_evidence=native,
            include_xirr=False,
        )


def test_summary_cache_never_populates_full_reads_and_is_revalidated(db, monkeypatch):
    _saved_investment(db, monkeypatch)
    derive = proofs._derive
    requests = []

    def counted(*args, **kwargs):
        requests.append(kwargs.get("include_xirr", True))
        return derive(*args, **kwargs)

    monkeypatch.setattr(proofs, "_derive", counted)
    with db.session_factory() as session:
        with source_read_snapshot(session):
            captured = {}
            summary = proofs.read_report_summaries(
                session, source_account=ACCOUNT, analyses=captured
            )
            assert captured and summary[0]["interval"]["pnl"]["value"] == "9000"
            assert summary[0]["interval"]["xirr_annualized"]["reason_codes"] == ["not_requested"]
            assert proofs.read_report_display_names(
                session, source_account=ACCOUNT, proof_id=summary[0]["proof_id"]
            )
            assert requests == [False]
            full = proofs.read_reports(session, source_account=ACCOUNT)
            assert full[0]["interval"]["xirr_annualized"]["value"] is not None
            assert requests == [False, True]
            summary[0]["interval"]["pnl"]["value"] = "-999"
            assert (
                proofs.read_report_summaries(session, source_account=ACCOUNT)[0]["interval"]["pnl"][
                    "value"
                ]
                == "9000"
            )
        with source_read_snapshot(session):
            full = proofs.read_reports(session, source_account=ACCOUNT)
            from_full = proofs.read_report_summaries(session, source_account=ACCOUNT)
            assert from_full == [{**full[0], "interval": service_summary(full[0]["interval"])}]
            assert requests == [False, True, True]
        row = session.scalar(
            select(SourceMoneyClassification).order_by(SourceMoneyClassification.id)
        )
        row.classification = "unknown" if row.classification != "unknown" else "fee"
        session.commit()
        stale = proofs.read_report_summaries(session, source_account=ACCOUNT)[0]
        assert stale["status"] == "stale" and stale["interval"] is None
        assert requests == [False, True, True, False]


def service_summary(interval):
    from hermes_finance.services.source_report_preview import _defer_xirr

    return _defer_xirr(deepcopy(interval))


def test_native_display_names_keep_exact_identity_and_ambiguity_without_affecting_attribution():
    service, document, raw, _, _ = investment_case()
    root = ET.fromstring(raw)
    position = root.find(".//{MyBroker}Details[@ISIN1]")
    trade = root.find(".//{MyBroker}Details[@trade_no]")
    position.set("active_name", " Exact position label ")
    trade.set("p_name", "Exact trade label")
    foreign = deepcopy(position)
    foreign.set("acc_code", "7654321-000")
    foreign.set("active_name", "Unrelated account label")
    position.append(foreign)
    oversized = deepcopy(position)
    oversized.remove(oversized[0])
    oversized.set("active_name", "x" * 257)
    position.append(oversized)
    changed = ET.tostring(root)
    metadata = {}
    baseline = service._native(document, changed)
    assert service._native(document, changed, display_names=metadata) == baseline
    assert metadata == {"RU000A000000": {"Exact position label", "Exact trade label"}}


def test_saved_display_names_require_current_exact_proof_and_reuse_snapshot(db, monkeypatch):
    _saved_investment(db, monkeypatch)
    derive = proofs._derive
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return derive(*args, **kwargs)

    monkeypatch.setattr(proofs, "_derive", counted)
    with db.session_factory() as session:
        with source_read_snapshot(session):
            current = proofs.read_reports(session, source_account=ACCOUNT)[0]
            metadata = proofs.read_report_display_names(
                session, source_account=ACCOUNT, proof_id=current["proof_id"]
            )
            assert metadata["RU000A000000"]
            assert all(len(label) <= 256 for label in metadata["RU000A000000"])
            assert len(calls) == 1
            assert (
                proofs.read_report_display_names(
                    session, source_account="7654321-000", proof_id=current["proof_id"]
                )
                == {}
            )
    stale_id = _append_stale_proof(db)
    with db.session_factory() as session:
        assert (
            proofs.read_report_display_names(session, source_account=ACCOUNT, proof_id=stale_id)
            == {}
        )
        assert (
            proofs.read_report_display_names(
                session, source_account=ACCOUNT, proof_id=current["proof_id"]
            )
            == {}
        )


def test_legacy_proof_without_display_metadata_still_validates_without_inventing_names(
    db, monkeypatch
):
    _saved_investment(db, monkeypatch)
    # A new synthetic row models the old envelope shape. No existing evidence
    # is rewritten; its content digest binds the deliberately absent metadata.
    with db.session_factory() as session:
        original = session.scalar(select(SourceReturnProof))
        values = {
            column.name: getattr(original, column.name)
            for column in SourceReturnProof.__table__.columns
            if column.name != "id"
        }
        plan = json.loads(original.evidence_json)
        plan["native"].pop("display_names")
        plan["report"].pop("display_names", None)
        values.update(
            request_id="read-efficiency-legacy",
            dependency_digest=proofs._evidence_digest(plan),
            evidence_json=json.dumps(plan),
        )
        session.add(SourceReturnProof(**values))
        session.commit()
    with db.session_factory() as session:
        with source_read_snapshot(session):
            current = proofs.read_reports(session, source_account=ACCOUNT)[0]
            assert current["status"] == "current"
            assert current["interval"]["pnl"]["value"] == "9000"
            assert (
                proofs.read_report_display_names(
                    session, source_account=ACCOUNT, proof_id=current["proof_id"]
                )
                == {}
            )


def _named_investment(
    db, monkeypatch, *, source_labels=(), pdf_labels=(), covered_to=None, sold=False
):
    import test_statement_import_mybroker_preflight as preflight

    from hermes_finance.services import source_instrument_returns as instruments
    from hermes_finance.statement_import.mybroker import parse_mybroker

    service, _, raw, report, _ = investment_case()
    root = ET.fromstring(raw)
    for node, attribute, label in (
        (
            root.find(".//{MyBroker}Details[@trade_no]"),
            "p_name",
            source_labels[0] if source_labels else None,
        ),
        (
            root.find(".//{MyBroker}Details[@ISIN1]"),
            "active_name",
            source_labels[-1] if source_labels else None,
        ),
    ):
        if label is None:
            node.attrib.pop(attribute, None)
        else:
            node.set(attribute, label)
    if sold:
        trade = root.find(".//{MyBroker}Details[@trade_no]")
        sell = deepcopy(trade)
        sell.set("trade_no", "10000000002\r\n2000000002")
        sell.set("qty", "-10")
        sell.set("summ_trade", "1100.00")
        sell.set("Price", "110.00")
        sell.set("bank_tax", "0")
        sell.set("summ_nkd", "0")
        if source_labels:
            sell.set("p_name", source_labels[-1])
        for key in (
            "db_time",
            "save_settlement_date",
            "save_depo_settlement_date",
            "settlement_time",
        ):
            sell.set(key, sell.get(key).replace(".01.2030", ".02.2030"))
        for parent in root.iter():
            if trade in list(parent):
                parent.append(sell)
                break
        cash = root.find(".//{MyBroker}Details[@active_name='RUB']")
        cash.set("real_rest", "2090")
        position = root.find(".//{MyBroker}Details[@ISIN1]")
        for parent in root.iter():
            if position in list(parent):
                parent.remove(position)
                break
        settlement = deepcopy(root.find(".//{MyBroker}rn"))
        settlement.set("last_update", settlement.get("last_update").replace("-01-", "-02-"))
        operation = settlement.find("{MyBroker}oper_type")
        operation.set("oper_type", operation.get("oper_type").replace("10000000001", "10000000002"))
        settlement.find(".//{MyBroker}p_code[@volume]").set("volume", "1100.00")
        settlement_group = ET.SubElement(
            root.find(".//{MyBroker}settlement_date_Collection"),
            "{MyBroker}settlement_date",
            {"settlement_date": "2030-02-17T00:00:00"},
        )
        ET.SubElement(settlement_group, "{MyBroker}rn_Collection").append(settlement)
        report = replace(
            report, positions={}, closed_isins=frozenset({("1234567", "RU000A000000")})
        )
    raw = ET.tostring(root)
    if covered_to is not None:
        raw = raw.replace(b"2030-01-31", str(covered_to).encode()).replace(
            b"31.01.2030", covered_to.strftime("%d.%m.%Y").encode()
        )
        monkeypatch.setattr(
            preflight,
            "FILENAME",
            preflight.FILENAME.replace("31.01.30", covered_to.strftime("%d.%m.%y")),
        )
        report = replace(report, end=covered_to)
    document = parse_mybroker(raw, preflight.FILENAME)
    report = replace(
        report, display_names=tuple(("1234567", "RU000A000000", label) for label in pdf_labels)
    )
    monkeypatch.setattr(
        preflight,
        "investment_case",
        lambda: (service, document, raw, report, service._money(document, raw)),
    )
    # Model a source-only saved view whose S1 proposals have no security names.
    # The native/PDF display metadata must supply names independently of them.
    identities = instruments._identities

    def unnamed(views):
        metadata = identities(views)
        for values in metadata.values():
            values["names"].clear()
        return metadata

    monkeypatch.setattr(instruments, "_identities", unnamed)
    _saved_investment(db, monkeypatch)
    return unnamed


def test_card_history_defers_only_unused_proof_xirr_without_changing_response(db, monkeypatch):
    from hermes_finance.services import returns_overall, source_monthly_returns

    _named_investment(db, monkeypatch, source_labels=("Synthetic title",))
    save(db, 2)
    before = snapshot(db)
    original = proofs._derive
    calls = []

    def counted(*args, **kwargs):
        calls.append(kwargs.get("include_xirr"))
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(proofs, "_derive", counted)
        patch.setattr(
            source_monthly_returns,
            "read_monthly_for_card_history",
            source_monthly_returns.read_monthly_returns,
        )
        with db.session_factory() as session:
            baseline = returns_overall.read_instrument_card(session, "RU000A000000")
        baseline_calls = list(calls)
    calls.clear()
    with monkeypatch.context() as patch:
        patch.setattr(proofs, "_derive", counted)
        with db.session_factory() as session:
            candidate = returns_overall.read_instrument_card(session, "RU000A000000")
        candidate_calls = list(calls)
    assert candidate == baseline
    assert baseline_calls.count(True) > candidate_calls.count(True)
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "source_labels,pdf_labels,expected",
    [
        (("Exact XML title",), ("Different PDF wording",), "Exact XML title"),
        ((), ("Exact PDF title",), "Exact PDF title"),
        (("XML first", "XML second"), ("Exact PDF title",), "Exact PDF title"),
        (("XML first", "XML second"), ("PDF first", "PDF second"), None),
        (("RU000A000000",), ("Exact PDF title",), "Exact PDF title"),
    ],
)
def test_verified_names_reach_source_reader_account_overview_and_detail(
    db, monkeypatch, source_labels, pdf_labels, expected
):
    from hermes_finance.services.source_instrument_returns import read_instrument_returns

    _named_investment(db, monkeypatch, source_labels=source_labels, pdf_labels=pdf_labels)
    before = snapshot(db)
    with db.session_factory() as session:
        source = read_instrument_returns(session, source_account=ACCOUNT)
        overview = returns_view.read_overview(
            session, scope=SCOPE, start=PROOF_START, end=PROOF_END
        )
        detail = returns_view.read_detail(
            session, scope=SCOPE, start=PROOF_START, end=PROOF_END, isin="RU000A000000"
        )
    assert source.instruments[0].source_name == expected
    assert source.to_dict()["instruments"][0]["source_name"] == expected
    assert overview["instruments"][0]["name"] == detail["name"] == (expected or "RU000A000000")
    assert detail["pnl"]["value"] == "9000"
    assert snapshot(db) == before


def test_display_candidates_are_scoped_current_and_do_not_repeat_detail_xirr(db, monkeypatch):
    from hermes_finance.services import source_report_preview as preview
    from hermes_finance.services.source_instrument_returns import read_instrument_returns

    _named_investment(
        db, monkeypatch, source_labels=("Exact XML title",), pdf_labels=("PDF title",)
    )
    chain, derive = preview.calculate_monthly_return_chain, proofs._derive
    calls, derivations = [], []

    def counted(*args, **kwargs):
        calls.append(1)
        return chain(*args, **kwargs)

    def derived(*args, **kwargs):
        derivations.append(1)
        return derive(*args, **kwargs)

    monkeypatch.setattr(preview, "calculate_monthly_return_chain", counted)
    monkeypatch.setattr(proofs, "_derive", derived)
    with db.session_factory() as session:
        detail = returns_view.read_detail(
            session, scope=SCOPE, start=PROOF_START, end=PROOF_END, isin="RU000A000000"
        )
        assert detail["name"] == "Exact XML title"
        assert len(calls) == 2 and len(derivations) == 1
        source = read_instrument_returns(session, source_account=ACCOUNT)
        assert source.instruments[0].source_name == "Exact XML title"
        assert len(calls) == 4 and len(derivations) == 2
        proof = proofs.read_report_summaries(session, source_account=ACCOUNT)[0]
        assert proofs.read_report_display_candidates(
            session, source_account="7654321-000", proof_id=proof["proof_id"]
        ) == {"source": {}, "pdf": {}}
    stale = _append_stale_proof(db)
    with db.session_factory() as session:
        assert proofs.read_report_display_candidates(
            session, source_account=ACCOUNT, proof_id=stale
        ) == {"source": {}, "pdf": {}}
        assert proofs.read_report_display_candidates(
            session, source_account=ACCOUNT, proof_id=proof["proof_id"]
        ) == {"source": {}, "pdf": {}}
        detail = returns_view.read_detail(
            session, scope=SCOPE, start=PROOF_START, end=PROOF_END, isin="RU000A000000"
        )
        assert detail["name"] == "RU000A000000" and detail["pnl"]["value"] is None


def test_catalogue_is_exact_display_fallback_and_never_becomes_source_name(db, monkeypatch):
    from hermes_finance.persistence import Instrument
    from hermes_finance.services.source_instrument_returns import read_instrument_returns

    _named_investment(
        db,
        monkeypatch,
        source_labels=("XML first", "XML second"),
        pdf_labels=("PDF first", "PDF second"),
    )
    with db.session_factory() as session:
        session.add_all(
            [
                Instrument(
                    name="Exact catalogue title", instrument_type="stock", isin="RU000A000000"
                ),
                Instrument(
                    name="Unrelated catalogue title", instrument_type="stock", isin="RU000A000001"
                ),
            ]
        )
        session.commit()
    before = snapshot(db)
    with db.session_factory() as session:
        source = read_instrument_returns(session, source_account=ACCOUNT)
        detail = returns_view.read_detail(
            session, scope=SCOPE, start=PROOF_START, end=PROOF_END, isin="RU000A000000"
        )
        overview = returns_view.read_overview(
            session, scope=SCOPE, start=PROOF_START, end=PROOF_END
        )
    assert source.instruments[0].source_name is None
    assert detail["name"] == overview["instruments"][0]["name"] == "Exact catalogue title"
    assert detail["pnl"]["value"] == "9000" and snapshot(db) == before


def test_pdf_security_display_labels_only_use_valid_selected_actual_rows():
    from test_statement_import_mybroker_preflight import investment_text

    from hermes_finance.statement_import.investment_report import parse_investment_report

    text = investment_text()
    parsed = parse_investment_report(text, {"1234567"})
    assert parsed.display_names == (("1234567", "RU000A000000", "Synthetic"),)
    foreign = parse_investment_report(investment_text(account="7654321"), {"1234567"})
    assert foreign.display_names == ()
    # Change only the future-flow label; it never becomes retained metadata.
    page = text.pages[0]
    lines = list(page.lines)
    lines[-1] = lines[-1].replace("Synthetic", "Future-only title")
    changed = replace(text, pages=(replace(page, lines=tuple(lines)),))
    assert parse_investment_report(changed, {"1234567"}).display_names == parsed.display_names
    # Malformed selected actual rows do not leak a name from a failed grammar.
    bad_lines = [line.replace("Synthetic", "x" * 257) for line in page.lines]
    oversized = replace(text, pages=(replace(page, lines=tuple(bad_lines)),))
    assert parse_investment_report(oversized, {"1234567"}).display_names == ()
    encoded = proofs._report(
        replace(
            parsed,
            display_names=parsed.display_names + (("7654321", "RU000A000000", "Foreign title"),),
        ),
        "1234567",
    )
    assert encoded["display_names"] == [["1234567", "RU000A000000", "Synthetic"]]
    assert proofs._restore_report(encoded).display_names == parsed.display_names
    missing = proofs._restore_report({**encoded, "display_names": None})
    assert missing.display_names == ()
    assert replace(missing, display_names=parsed.display_names) == parsed


def test_exact_verified_source_title_reaches_existing_screen_and_source_api_routes(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from hermes_finance.api.returns_overall import router as overall_router
    from hermes_finance.api.returns_view import router as view_router
    from hermes_finance.api.settings import session_for_request
    from hermes_finance.api.source_instrument_returns import router as source_router
    from hermes_finance.services import returns_overall

    unnamed = _named_investment(
        db, monkeypatch, source_labels=("Exact XML title",), pdf_labels=("Different PDF title",)
    )
    monkeypatch.setattr(returns_overall, "_identities", unnamed)
    app = FastAPI()
    for router in (overall_router, view_router, source_router):
        app.include_router(router)

    def session():
        with db.session_factory() as value:
            yield value

    app.dependency_overrides[session_for_request] = session
    before = snapshot(db)
    query = {"scope": SCOPE, "start": str(PROOF_START), "end": str(PROOF_END)}
    with TestClient(app) as client:
        overall = client.get("/api/returns/overall")
        overview = client.get("/api/returns/overview", params=query)
        detail = client.get("/api/returns/instrument", params={**query, "isin": "RU000A000000"})
        source = client.get("/api/source-returns/instruments", params={"source_account": ACCOUNT})
    for result in (overall, overview, detail, source):
        assert result.status_code == 200, result.text
        assert result.headers["cache-control"] == "no-store"
    assert overall.json()["instruments"][0]["name"] == "Exact XML title"
    assert overview.json()["instruments"][0]["name"] == detail.json()["name"] == "Exact XML title"
    assert source.json()["instruments"][0]["source_name"] == "Exact XML title"
    assert snapshot(db) == before


@pytest.mark.parametrize("fault", [None, "cash_control", "unknown_money", "quantity"])
def test_account_index_preserves_full_account_economics_controls_and_isin_candidates(fault):
    service, document, report, money, native = _many_instrument_case()
    if fault == "cash_control":
        document["rub_money"][0]["ending_amount"] = "1"
    elif fault == "unknown_money":
        money.append({**money[-1], "classification": "unknown", "ref": "unknown-guard"})
    elif fault == "quantity":
        document["positions"][-1]["actual_quantity"] = "99"
    full_analyses, index_analyses = {}, {}
    full = service._interval(
        document,
        None,
        report,
        money,
        {},
        {},
        True,
        native_evidence=native,
        analyses=full_analyses,
        include_xirr=False,
    )
    index = service._interval(
        document,
        None,
        report,
        money,
        {},
        {},
        True,
        native_evidence=native,
        analyses=index_analyses,
        include_xirr=False,
        include_instruments=False,
    )
    assert index == _expected_account_index(full)
    assert len(full_analyses) == 4 and index_analyses == {}


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("duplicate_position", "source_return_duplicate_position"),
        ("cash_ownership", "duplicate cash ownership"),
        ("foreign_money", "source_return_money_account_conflict"),
    ],
)
def test_account_index_keeps_whole_security_refusals_even_when_filtering(fault, reason):
    service, document, report, money, native = _many_instrument_case()
    if fault == "duplicate_position":
        document["positions"].append(document["positions"][-1])
    elif fault == "cash_ownership":
        money.append(money[-3])
    else:
        money[-1]["source_account"] = "7654321-000"
    for include_instruments in (True, False):
        with pytest.raises(ValueError, match=reason):
            service._interval(
                document,
                None,
                report,
                money,
                {},
                {},
                True,
                native_evidence=native,
                include_xirr=False,
                include_instruments=include_instruments,
                requested_isin=document["positions"][0]["isin"],
            )


def test_account_index_constructs_no_instrument_projection_or_xirr(monkeypatch):
    service, document, report, money, native = _many_instrument_case(27)
    analysis, rates, metric = service.InstrumentAnalysis, service._rates, service._metric
    counts = Counter()

    def analysed(*args, **kwargs):
        counts["analyses"] += 1
        return analysis(*args, **kwargs)

    def rated(*args, **kwargs):
        counts["rates"] += 1
        return rates(*args, **kwargs)

    def measured(*args, **kwargs):
        counts["metrics"] += 1
        return metric(*args, **kwargs)

    def unexpected(*args, **kwargs):
        raise AssertionError("account summary computed XIRR")

    monkeypatch.setattr(service, "InstrumentAnalysis", analysed)
    monkeypatch.setattr(service, "_rates", rated)
    monkeypatch.setattr(service, "_metric", measured)
    monkeypatch.setattr(service, "calculate_monthly_return_chain", unexpected)
    full = service._interval(
        document,
        None,
        report,
        money,
        {},
        {},
        True,
        native_evidence=native,
        analyses={},
        include_xirr=False,
    )
    assert counts["analyses"] == 27 and counts["rates"] == 28
    full_metrics = counts["metrics"]
    counts.clear()
    index = service._interval(
        document,
        None,
        report,
        money,
        {},
        {},
        True,
        native_evidence=native,
        analyses={},
        include_xirr=False,
        include_instruments=False,
    )
    assert counts["analyses"] == 0 and counts["rates"] == 1
    assert counts["metrics"] < full_metrics
    account_metrics = counts["metrics"]
    counts.clear()
    _, small_document, small_report, small_money, small_native = _many_instrument_case(4)
    service._interval(
        small_document,
        None,
        small_report,
        small_money,
        {},
        {},
        True,
        native_evidence=small_native,
        analyses={},
        include_xirr=False,
        include_instruments=False,
    )
    assert counts["metrics"] == account_metrics  # No per-instrument display metric construction.
    assert index == _expected_account_index(full)


def test_account_index_cache_never_seeds_instrument_summary_or_detail_and_names_stay_lazy(
    db, monkeypatch
):
    _named_investment(db, monkeypatch, source_labels=("Exact XML title",))
    derive = proofs._derive
    requests = []

    def counted(*args, **kwargs):
        requests.append((kwargs["include_xirr"], kwargs["include_instruments"]))
        return derive(*args, **kwargs)

    monkeypatch.setattr(proofs, "_derive", counted)
    with db.session_factory() as session:
        with source_read_snapshot(session):
            index = proofs.read_account_summaries(session, source_account=ACCOUNT)
            assert index[0]["interval"]["instruments"] == [{"isin": "RU000A000000"}]
            assert index[0]["interval"]["pnl"]["value"] == "9000"
            assert proofs.read_report_display_candidates(
                session, source_account=ACCOUNT, proof_id=index[0]["proof_id"]
            )["source"] == {"RU000A000000": ("Exact XML title",)}
            assert requests == [(False, False)]
            index[0]["interval"]["instruments"][0]["isin"] = "RU0000000001"
            assert proofs.read_account_summaries(session, source_account=ACCOUNT)[0]["interval"][
                "instruments"
            ] == [{"isin": "RU000A000000"}]
            captured = {}
            full_summary = proofs.read_report_summaries(
                session, source_account=ACCOUNT, analyses=captured
            )
            assert captured[full_summary[0]["proof_id"]]
            assert "pnl" in full_summary[0]["interval"]["instruments"][0]
            assert requests == [(False, False), (False, True)]
            detail = returns_view.read_detail(
                session, scope=SCOPE, start=PROOF_START, end=PROOF_END, isin="RU000A000000"
            )
            assert detail["name"] == "Exact XML title" and detail["pnl"]["value"] == "9000"
            assert requests == [(False, False), (False, True), (True, True)]
        with source_read_snapshot(session):
            full = proofs.read_reports(session, source_account=ACCOUNT)
            before = len(requests)
            projected = proofs.read_account_summaries(
                session,
                source_account=ACCOUNT,
                opening_date=PROOF_START,
                closing_date=PROOF_END,
                requested_isin="RU000A000000",
            )
            assert projected[0]["interval"]["instruments"] == [{"isin": "RU000A000000"}]
            assert "pnl" in full[0]["interval"]["instruments"][0]
            assert len(requests) == before
        row = session.scalar(
            select(SourceMoneyClassification).order_by(SourceMoneyClassification.id)
        )
        row.classification = "unknown" if row.classification != "unknown" else "fee"
        session.commit()
        stale = proofs.read_account_summaries(session, source_account=ACCOUNT)[0]
        assert stale["status"] == "stale" and stale["interval"] is None


@pytest.mark.parametrize(
    "labels,expected",
    [
        (("Sold security title",), "Sold security title"),
        (("First XML title", "Second XML title"), "RU000A000000"),
    ],
)
def test_long_history_sold_isin_labels_short_month_only_as_metadata_without_xirr(
    db, monkeypatch, labels, expected
):
    from hermes_finance.persistence import Instrument
    from hermes_finance.services import source_report_preview as preview

    _named_investment(
        db,
        monkeypatch,
        source_labels=labels,
        covered_to=date(2030, 3, 31),
        sold=True,
    )
    start, end = date(2030, 1, 31), date(2030, 2, 28)
    with db.session_factory() as session:
        history = proofs.read_account_summaries(session, source_account=ACCOUNT)[0]
        assert history["interval"]["instruments"] == [{"isin": "RU000A000000"}]
        assert history["interval"]["pnl"]["value"] == "9000", history["interval"]
        assert (
            proofs.read_reports(
                session, source_account=ACCOUNT, opening_date=start, closing_date=end
            )
            == []
        )
        assert session.scalar(select(Instrument)) is None
    before = snapshot(db)
    chain = preview.calculate_monthly_return_chain

    def unexpected(*args, **kwargs):
        raise AssertionError("subinterval name fallback computed XIRR")

    monkeypatch.setattr(preview, "calculate_monthly_return_chain", unexpected)
    with monkeypatch.context() as baseline_patch:
        baseline_patch.setattr(
            proofs, "read_latest_display_candidates", lambda *a, **k: {"source": {}, "pdf": {}}
        )
        with db.session_factory() as session:
            baseline = returns_view.read_detail(
                session, scope=SCOPE, start=start, end=end, isin="RU000A000000"
            )
    with db.session_factory() as session:
        detail = returns_view.read_detail(
            session, scope=SCOPE, start=start, end=end, isin="RU000A000000"
        )
    assert baseline["name"] == "RU000A000000" and detail["name"] == expected
    assert detail["analysis"].opening_date == start and detail["analysis"].closing_date == end
    assert {k: v for k, v in detail.items() if k != "name"} == {
        k: v for k, v in baseline.items() if k != "name"
    }
    assert snapshot(db) == before
    counts = []

    def counted(*args, **kwargs):
        counts.append(1)
        return chain(*args, **kwargs)

    with monkeypatch.context() as baseline_patch:
        baseline_patch.setattr(
            proofs, "read_latest_display_candidates", lambda *a, **k: {"source": {}, "pdf": {}}
        )
        baseline_patch.setattr(preview, "calculate_monthly_return_chain", counted)
        with db.session_factory() as session:
            baseline_overview = returns_view.read_overview(
                session, scope=SCOPE, start=start, end=end
            )
    baseline_calls = len(counts)
    counts.clear()
    with monkeypatch.context() as actual_patch:
        actual_patch.setattr(preview, "calculate_monthly_return_chain", counted)
        with db.session_factory() as session:
            overview = returns_view.read_overview(session, scope=SCOPE, start=start, end=end)
    assert len(counts) == baseline_calls  # Existing whole-history work only; no name-induced XIRR.
    assert overview["instruments"][0]["name"] == expected
    for value in (baseline_overview, overview):
        for row in value["instruments"]:
            row.pop("name")
    assert overview == baseline_overview
    _append_stale_proof(db)
    with db.session_factory() as session:
        stale = returns_view.read_detail(
            session, scope=SCOPE, start=start, end=end, isin="RU000A000000"
        )
    assert stale["name"] == "RU000A000000"


def _expected_account_index(full):
    return {
        **{
            key: value
            for key, value in full.items()
            if key
            not in {
                "external_flows",
                "account_only",
                "exceptions",
                "unallocated_payouts",
            }
        },
        "instruments": [{"isin": row["isin"]} for row in full["instruments"]],
    }


def test_all_accounts_cache_projects_only_exact_selected_account_rows(db, monkeypatch):
    _named_investment(db, monkeypatch, source_labels=("Exact XML title",))
    with db.session_factory() as session:
        original = session.scalar(select(SourceReturnProof))
        original_id = original.id
        values = {
            column.name: getattr(original, column.name)
            for column in SourceReturnProof.__table__.columns
            if column.name != "id"
        }
        plan = json.loads(original.evidence_json)
        plan.update(source_account="7654321", native_account="7654321-000")
        values.update(
            source_account="7654321",
            native_account="7654321-000",
            request_id="index-foreign",
            evidence_json=json.dumps(plan),
            dependency_digest=proofs._evidence_digest(plan),
        )
        session.add(SourceReturnProof(**values))
        session.commit()
    derive = proofs._derive
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return derive(*args, **kwargs)

    monkeypatch.setattr(proofs, "_derive", counted)
    with db.session_factory() as session:
        with source_read_snapshot(session):
            all_reports = proofs.read_reports(session)
            assert len(all_reports) == 2 and len(calls) == 2
            selected = proofs.read_account_summaries(session, source_account=ACCOUNT)
            assert [row["proof_id"] for row in selected] == [original_id]
            assert (
                selected[0]["status"] == "current"
                and selected[0]["interval"]["pnl"]["value"] == "9000"
            )
            captured = {}
            alias = proofs.read_reports(session, source_account="1234567", analyses=captured)
            assert [row["proof_id"] for row in alias] == [original_id]
            assert set(captured) == {original_id} and captured[original_id]
            assert proofs.read_report_display_candidates(
                session, source_account=ACCOUNT, proof_id=original_id
            )["source"]
            assert len(calls) == 2


def test_all_accounts_cache_requires_complete_canonical_scoped_selection(db, monkeypatch):
    _saved_investment(db, monkeypatch)
    with db.session_factory() as session:
        original = session.scalar(select(SourceReturnProof))
        original_id = original.id
        values = {
            column.name: getattr(original, column.name)
            for column in SourceReturnProof.__table__.columns
            if column.name != "id"
        }
        # A deliberately inconsistent synthetic row demonstrates why global
        # cache scope cannot be inferred from display/source aliases alone.
        values.update(source_account="different-row-alias", request_id="index-coverage-gap")
        copy = SourceReturnProof(**values)
        session.add(copy)
        session.commit()
        newer_id = copy.id
    derive = proofs._derive
    calls = []

    def counted(session, row, *args, **kwargs):
        calls.append(row.id)
        return derive(session, row, *args, **kwargs)

    monkeypatch.setattr(proofs, "_derive", counted)
    with db.session_factory() as session:
        with source_read_snapshot(session):
            global_reports = proofs.read_reports(session)
            assert [row["proof_id"] for row in global_reports] == [newer_id]
            scoped = proofs.read_account_summaries(session, source_account="1234567")
            assert [row["proof_id"] for row in scoped] == [original_id]
            assert calls == [newer_id, original_id]


def test_source_views_are_verified_once_per_snapshot_and_never_shared_mutably(db, monkeypatch):
    basket_source(db)
    basket_source(db, month=5)
    original = source_intake._view
    calls = Counter()

    def counted(session, row, **kwargs):
        calls[row.id] += 1
        return original(session, row, **kwargs)

    monkeypatch.setattr(source_intake, "_view", counted)
    with db.session_factory() as session:
        returns_view.read_context(session)
        assert sorted(calls.values()) == [1, 1]
        returns_view.read_context(session)
        assert sorted(calls.values()) == [2, 2]
        with source_read_snapshot(session):
            first, _ = _selected_sources(session, ACCOUNT)
            first[0][1]["document"]["positions"].clear()
            again, _ = _selected_sources(session, ACCOUNT)
            assert again[0][1]["document"]["positions"]
        assert sorted(calls.values()) == [3, 3]


def test_failed_snapshot_drops_memo_and_later_reader_failure_is_visible(db, monkeypatch):
    basket_source(db)
    with db.session_factory() as session:
        with pytest.raises(RuntimeError, match="abort"):
            with source_read_snapshot(session):
                selected, _ = _selected_sources(session, ACCOUNT)
                assert selected[0][1] is not None
                raise RuntimeError("abort")

        def unavailable(*args, **kwargs):
            raise ValueError("changed source")

        monkeypatch.setattr(source_intake, "_view", unavailable)
        with source_read_snapshot(session):
            selected, _ = _selected_sources(session, ACCOUNT)
            assert selected[0][1:] == (None, "source_reader_unavailable")


def test_reused_session_revalidates_changed_classification_between_reads(db):
    intake_id = basket_source(db, extra=(("Synthetic payment", "Synthetic receipt", "100"),))
    with db.session_factory() as session:
        with source_read_snapshot(session):
            selected, _ = _selected_sources(session, ACCOUNT)
            previous = selected[0][1]["money_classifications"][0]
            assert previous["classification"] != "fee"
        # A supported source-only decision in the disposable test DB changes a
        # dependency. The old verified view must not survive into another GET.
        with db.session_factory() as writer:
            choose_classification(writer, intake_id, previous["source_reference"], "fee")
        with source_read_snapshot(session):
            changed, _ = _selected_sources(session, ACCOUNT)
            current = changed[0][1]["money_classifications"][0]
            assert current["classification"] == "fee"
            assert current["origin"] == "user_choice"


@pytest.mark.parametrize("bond", [None, ("2", "3", "2000", "3150")])
def test_selected_overview_and_detail_equal_full_history_reader(db, monkeypatch, bond):
    save(db, bond=bond)
    save(db, 5, bond=bond)
    before = snapshot(db)

    def read():
        with db.session_factory() as session:
            overview = returns_view.read_overview(session, scope=SCOPE, start=START, end=END)
            details = [
                returns_view.read_detail(
                    session, scope=SCOPE, start=START, end=END, isin=row["isin"]
                )
                for row in overview["instruments"]
            ]
        return overview, details

    selected = read()
    instrument_reader = returns_view.read_instrument_returns

    def with_history(*args, **kwargs):
        return instrument_reader(*args, **{**kwargs, "include_monthly_history": True})

    monkeypatch.setattr(returns_view, "read_instrument_returns", with_history)
    assert read() == selected
    assert snapshot(db) == before


def test_accepted_scope_does_not_decode_source_journal(db, monkeypatch):
    basket_source(db)

    def unexpected(*args, **kwargs):
        raise AssertionError("accepted scope decoded an unrelated source")

    monkeypatch.setattr(source_intake, "_view", unexpected)
    with db.session_factory() as session:
        result = returns_view.read_overview(session, scope="portfolio", start=START, end=END)
    assert result["selected"]["pnl"]["method"] == "PERF04A"


def test_month_journal_keeps_only_bound_or_calendar_overlapping_unbound_sources(db, monkeypatch):
    april = basket_source(db, month=4)
    may = basket_source(db, month=5)
    with db.session_factory() as session:
        month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 31))
        month_id = month.id
        session.commit()
    with db.session_factory() as session:
        assert {v["id"] for v in source_intake.list_intakes(session)} == {april, may}
        assert [v["id"] for v in source_intake.list_intakes(session, month_id, True)] == [may]

    read = source_intake._view

    def bound(session, row, **kwargs):
        value = read(session, row, **kwargs)
        if row.id == april:
            value["state"]["reporting_month_id"] = month_id
        return value

    monkeypatch.setattr(source_intake, "_view", bound)
    with db.session_factory() as session:
        assert {v["id"] for v in source_intake.list_intakes(session, month_id, True)} == {
            april,
            may,
        }


def test_identity_revision_is_shared_only_within_one_committed_snapshot(db, monkeypatch):
    from unittest.mock import Mock

    from hermes_finance.database import coherent_read_snapshot
    from hermes_finance.persistence import Account
    from hermes_finance.services import mybroker_identity

    build = Mock(wraps=mybroker_identity._build_revision)
    monkeypatch.setattr(mybroker_identity, "_build_revision", build)
    with db.session_factory() as session:
        with coherent_read_snapshot(session):
            first = mybroker_identity._revision(session)
            assert mybroker_identity._revision(session) == first
            assert build.call_count == 1
        with db.session_factory() as writer:
            writer.add(Account(name="Synthetic added account", account_type="brokerage"))
            writer.commit()
        with coherent_read_snapshot(session):
            assert mybroker_identity._revision(session) != first
            assert build.call_count == 2


@pytest.mark.parametrize("reader", ["account", "overall", "income", "card", "overview", "detail"])
def test_clean_account_queries_do_not_scale_with_instruments(
    tmp_path, source_returns_database_factory, reader
):
    from hermes_finance.services.clean_instrument_return import read_clean_account
    from hermes_finance.services.returns_overall import (
        read_clean_income,
        read_clean_instrument_card,
        read_clean_overall,
    )
    from hermes_finance.statement_import.mybroker import NS

    counts = []
    query_shapes = []
    for size in (1, 12):
        directory = tmp_path / str(size)
        directory.mkdir()
        database = source_returns_database_factory(directory)

        def instruments(root):
            collection = root.find(
                "m:Positions/m:Report/m:Tablix1/m:active_type_Collection/"
                "m:active_type/m:Details_Collection",
                NS,
            )
            template = deepcopy(collection[0])
            collection.clear()
            for index in range(size):
                row = deepcopy(template)
                row.set("ISIN1", f"RU{index:010d}")
                row.set("active_name", f"Synthetic instrument {index}")
                collection.append(row)

        save(database, bond=None, trades=(), mutate=instruments)
        statements = []

        def query(*args):
            statements.append(args[2])

        event.listen(database.engine, "before_cursor_execute", query)
        try:
            with database.session_factory() as session, source_read_snapshot(session):
                if reader == "account":
                    result = read_clean_account(
                        session, ACCOUNT, START, END, include_purchases=True
                    )
                    assert len(result["instruments"]) == size
                elif reader == "overall":
                    result = read_clean_overall(session, include_instrument_details=True)
                    assert len(result["instruments"]) == size
                elif reader == "income":
                    result = read_clean_income(session, kind="coupon")
                    assert len(result["instruments"]) == size
                elif reader == "card":
                    assert read_clean_instrument_card(session, "RU0000000000")["accounts"]
                elif reader == "overview":
                    result = returns_view.read_clean_source_overview(
                        session, scope=SCOPE, start=START, end=END
                    )
                    assert len(result["instruments"]) == size
                else:
                    assert (
                        returns_view.read_clean_source_detail(
                            session, scope=SCOPE, start=START, end=END, isin="RU0000000000"
                        )["isin"]
                        == "RU0000000000"
                    )
            counts.append(len(statements))
            query_shapes.append(Counter(statements))
        finally:
            event.remove(database.engine, "before_cursor_execute", query)
            database.engine.dispose()
    assert counts[0] == counts[1], (counts, query_shapes[1] - query_shapes[0])


def test_money_ownership_inventory_is_batched_owned_and_revalidated(db, monkeypatch):
    from hermes_finance.persistence import BrokerMonthApply
    from hermes_finance.services import broker_money_ownership as ownership

    statements = []

    def query(*args):
        statements.append(args[2])

    event.listen(db.engine, "before_cursor_execute", query)
    try:
        with db.session_factory() as session, source_read_snapshot(session):
            for ordinal in range(12):
                assert (
                    ownership.owners(
                        session, [{"import_id": 1, "section": "money", "ordinal": ordinal}]
                    )
                    == []
                )
            for table in (
                "broker_money_occurrence_owners",
                "historical_owner_flow_occurrences",
                "executed_trade_occurrences",
                BrokerMonthApply.__tablename__,
            ):
                assert sum(f"FROM {table}" in sql for sql in statements) == 1
    finally:
        event.remove(db.engine, "before_cursor_execute", query)

    calls = []
    rows = [
        {"key": [1, "money", ordinal], "role": "coupon", "target_id": ordinal}
        for ordinal in (2, 1, 2)
    ]

    def inventory(_session, **_selection):
        calls.append(1)
        return deepcopy(rows)

    monkeypatch.setattr(ownership, "_owner_inventory", inventory)
    selected = [{"import_id": 1, "section": "money", "ordinal": n} for n in (1, 2)]
    with db.session_factory() as session:
        with source_read_snapshot(session):
            value = ownership.owners(session, selected)
            assert value == rows  # Preserve duplicates and original cross-table order.
            value[0]["key"].clear()
            assert ownership.owners(session, selected) == rows
            assert len(calls) == 1
            rows[0]["role"] = "dividend"
            assert ownership.owners(session, selected)[0]["role"] == "coupon"
        with source_read_snapshot(session):
            assert ownership.owners(session, selected) == rows
            assert len(calls) == 2
        ownership.owners(session, selected)
        ownership.owners(session, selected)
        assert len(calls) == 4  # Ordinary sessions never reuse the inventory.


def test_trade_checks_share_money_inventory_without_exposing_cash_proof(db, monkeypatch):
    from types import SimpleNamespace

    from hermes_finance.services import broker_money, broker_trade_money, returns_read_inputs

    calls = []

    def latest(_session):
        calls.append(1)
        return {
            ("trade", identity): (None, {}, {"cash_proof": {"identity": identity}})
            for identity in range(12)
        }

    monkeypatch.setattr(broker_money, "latest_proofs", latest)
    monkeypatch.setattr(broker_money, "proof_blockers", lambda *a: [])
    monkeypatch.setattr(returns_read_inputs, "executed_trade", lambda s, i: SimpleNamespace(id=i))
    with db.session_factory() as session:
        with source_read_snapshot(session):
            for identity in range(12):
                result = broker_trade_money.effective_proof(session, identity)
                assert result == {"identity": identity}
                result["identity"] = -1
                assert broker_trade_money.effective_proof(session, identity) == {
                    "identity": identity
                }
            assert len(calls) == 1
        with source_read_snapshot(session):
            broker_trade_money.effective_proof(session, 0)
            assert len(calls) == 2
        broker_trade_money.effective_proof(session, 0)
        broker_trade_money.effective_proof(session, 0)
        assert len(calls) == 4


def test_clean_overall_omits_only_replaced_legacy_instrument_work(db, monkeypatch):
    from hermes_finance.api.returns_overall import Overall
    from hermes_finance.services import returns_overall

    _named_investment(db, monkeypatch, source_labels=("Synthetic title",))
    save(db, 2)
    read = returns_overall.read_overall

    def full(session, **kwargs):
        return read(session, **{**kwargs, "native_instruments": True})

    with monkeypatch.context() as patch:
        patch.setattr(returns_overall, "read_overall", full)
        with db.session_factory() as session:
            baseline = Overall.model_validate(
                returns_overall.read_clean_overall(session, include_instrument_details=True)
            ).model_dump_json()
    with db.session_factory() as session:
        candidate = Overall.model_validate(
            returns_overall.read_clean_overall(session, include_instrument_details=True)
        ).model_dump_json()
    assert candidate == baseline


def test_clean_card_matches_full_legacy_index(db, monkeypatch):
    from test_statement_import_mybroker import ISIN

    from hermes_finance.api.returns_overall import InstrumentCard
    from hermes_finance.services import returns_overall

    save(db)
    read = returns_overall._source_accounts

    def full(session, **kwargs):
        return read(session, **{**kwargs, "requested_isin": None})

    with monkeypatch.context() as patch:
        patch.setattr(returns_overall, "_source_accounts", full)
        with db.session_factory() as session:
            baseline = InstrumentCard.model_validate(
                returns_overall.read_clean_instrument_card(session, ISIN)
            ).model_dump_json(exclude_unset=True)
    with db.session_factory() as session:
        candidate = InstrumentCard.model_validate(
            returns_overall.read_clean_instrument_card(session, ISIN)
        ).model_dump_json(exclude_unset=True)
    assert candidate == baseline


def test_instrument_preparation_reused_across_periods_without_exposing_mutable_state(
    db, monkeypatch
):
    from hermes_finance.services import source_instrument_returns as reader

    save(db)
    save(db, 5)
    prepare = reader._prepare_instrument_inputs
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return prepare(*args, **kwargs)

    monkeypatch.setattr(reader, "_prepare_instrument_inputs", counted)

    def read(session, start, end):
        return reader.read_instrument_returns(
            session,
            source_account=ACCOUNT,
            opening_date=start,
            closing_date=end,
            include_monthly_history=False,
            clean_projection=True,
        )

    with db.session_factory() as session:
        with source_read_snapshot(session):
            first = read(session, START, END)
            expected = deepcopy(first)
            first.instruments[0].analysis.coverage.clear()
            assert read(session, START, END) == expected
            later = read(session, END, date(2030, 5, 31))
            assert len(calls) == 1
        assert "returns_source_scope_reads" not in session.info
        # No source memo exists outside the protected source-read lifetime.
        assert read(session, START, END) == expected
        assert read(session, END, date(2030, 5, 31)) == later
        assert len(calls) == 3


def test_source_money_memo_preserves_gaps_and_rejects_changed_view(db):
    from hermes_finance.services.source_monthly_returns import _money

    basket_source(db, extra=(("Synthetic cash", "Synthetic receipt", "100"),))
    with db.session_factory() as session, source_read_snapshot(session):
        selected, _ = _selected_sources(session, ACCOUNT)
        view = selected[0][1]
        gaps = []
        expected = _money(session, view, None, gaps)
        again = []
        assert _money(session, view, None, again) == expected
        assert again == gaps
        # A modified consumer projection cannot borrow the original's result.
        view["document"]["money"][0]["amount"] = "999999"
        changed_gaps = []
        changed = _money(session, view, None, changed_gaps)
        assert (changed, changed_gaps) != (expected, gaps)


def test_compiled_attribution_keeps_whole_tokens_precedence_ambiguity_and_new_identities():
    from hermes_finance.services.source_instrument_returns import _attribute, _attribute_reader

    identities = {
        "synthetic-a": {"identifiers": {"RU000A000001"}, "names": {"Synthetic issue"}},
        "synthetic-b": {"identifiers": {"RU000A000002"}, "names": {"Synthetic issue"}},
    }
    reader = _attribute_reader(identities)
    texts = (
        "RU000A000001",
        "ru000a000001",
        "xRU000A000001",
        "RU000A000001suffix",
        "Synthetic   ISSUE",
        "RU000A000001 Synthetic issue",
        "RU000A000001 RU000A000002",
        "New identity",
        "no match",
    )
    for text in texts * 2:
        assert reader(text) == _attribute(text, identities)
    identities["synthetic-c"] = {"identifiers": {"NEW-ID"}, "names": {"New identity"}}
    identities["synthetic-a"]["names"].add("Added label")
    for text in (*texts, "NEW-ID", "Added label"):
        assert reader(text) == _attribute(text, identities)


def test_xirr_reuses_exact_inputs_only_inside_source_snapshot(db, monkeypatch):
    import importlib

    solver = importlib.import_module("hermes_finance.domain.xirr")
    original = solver._calculate_normalised_xirr
    calls = []

    def counted(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(solver, "_calculate_normalised_xirr", counted)
    flows = (
        solver.XirrCashFlow(date(2030, 1, 1), -10000),
        solver.XirrCashFlow(date(2031, 1, 1), 11000),
    )
    with db.session_factory() as session:
        with source_read_snapshot(session):
            first = solver.calculate_xirr(flows)
            with source_read_snapshot(session):
                assert solver.calculate_xirr(reversed(flows)) == first
            assert len(calls) == 1
            solver.calculate_xirr(flows, max_iterations=1)
            assert len(calls) == 2
            solver.calculate_xirr((flows[0], replace(flows[1], amount_kopecks=12000)))
            assert len(calls) == 3
        assert solver._READ_RESULTS.get() is None
        with pytest.raises(RuntimeError), source_read_snapshot(session):
            assert solver.calculate_xirr(flows) == first
            raise RuntimeError("failed read")
        assert solver._READ_RESULTS.get() is None
        assert solver.calculate_xirr(flows) == first
        assert len(calls) == 5


def test_monthly_card_history_cache_returns_owned_results(db, monkeypatch):
    from hermes_finance.services import source_monthly_returns as monthly

    calls = []

    def read(_session, **kwargs):
        calls.append(kwargs)
        return {"values": [len(calls)]}

    monkeypatch.setattr(monthly, "_read_monthly_returns", read)
    with db.session_factory() as session:
        with source_read_snapshot(session):
            first = monthly.read_monthly_for_card_history(session, source_account="synthetic")
            first["values"].append(99)
            assert monthly.read_monthly_for_card_history(session, source_account="synthetic") == {
                "values": [1]
            }
            monthly.read_monthly_for_card_history(session, source_account="other")
            assert len(calls) == 2
        assert monthly.read_monthly_for_card_history(session, source_account="synthetic") == {
            "values": [3]
        }


def test_inventory_projection_still_checks_each_fingerprint(db, monkeypatch):
    from hermes_finance.persistence import SourceIntakeOriginal
    from hermes_finance.statement_import.mybroker import MyBrokerError

    basket_source(db)
    with db.session_factory() as session:
        intake_id = session.scalar(select(SourceIntakeOriginal.id))
        before = source_intake.read_intake(session, intake_id)
        original_digest = source_intake.digest
        facts = before["observations"][0]["facts"]

        def corrupted(value):
            return "invalid" if value == facts else original_digest(value)

        monkeypatch.setattr(source_intake, "digest", corrupted)
        with pytest.raises(MyBrokerError, match="source_intake_inventory_invalid"):
            source_intake.read_intake(session, intake_id)


@pytest.mark.parametrize(
    "statement",
    [
        "append-source",
        "UPDATE position_snapshots SET quantity = quantity + 1",
        "UPDATE reporting_months SET status = 'draft'",
        "UPDATE accounts SET name = 'Changed synthetic account'",
        "UPDATE accounts SET include_in_capital = 0",
        "UPDATE accounts SET include_in_returns = 0",
        "UPDATE position_snapshots SET market_value_kopecks = market_value_kopecks + 1",
        "UPDATE position_snapshots SET cost_basis_kopecks = cost_basis_kopecks + 1",
        "UPDATE deposit_snapshots SET actual_interest_received_kopecks = 17",
        "DELETE FROM deposit_snapshots",
    ],
)
def test_content_cache_sees_committed_sql_writes_in_every_input_family(db, statement):
    # Direct SQL deliberately bypasses ORM hooks: the cache proves all committed
    # pages, including source facts, gold/position valuation and inclusion flags.
    from test_returns_overall_service import component_rows

    from hermes_finance.api.read_cache import cached_read_endpoint
    from hermes_finance.persistence import Base

    component_rows(db)
    basket_source(db)
    calls = []

    @cached_read_endpoint
    def read_all(session):
        calls.append(1)
        return {
            table.name: [
                tuple(row)
                for row in session.connection().exec_driver_sql(
                    f'SELECT * FROM "{table.name}" ORDER BY rowid'
                )
            ]
            for table in Base.metadata.sorted_tables
        }

    with db.session_factory() as session:
        before = read_all(session)
        assert read_all(session) == before
        assert len(calls) == 1
    if statement == "append-source":
        basket_source(db, marker="new-source")
    else:
        with db.engine.begin() as connection:
            assert connection.exec_driver_sql(statement).rowcount > 0
    with db.session_factory() as session:
        after = read_all(session)
        assert after != before
        assert len(calls) == 2
        assert read_all(session) == after
        assert len(calls) == 2
        after.clear()
        assert read_all(session)


def test_content_cache_wal_commit_rollback_and_external_file(db, tmp_path):
    from hermes_finance.api.read_cache import cached_read_endpoint
    from hermes_finance.database import ReadSnapshotMutationError
    from hermes_finance.persistence import Account

    with db.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    with db.session_factory() as writer:
        writer.add(Account(name="Synthetic", account_type="other"))
        writer.commit()
    valuation = tmp_path / "valuation.json"
    valuation.write_text("one")
    calls = []

    @cached_read_endpoint
    def read_account(session):
        calls.append(1)
        return session.scalar(select(Account.name)), valuation.read_text()

    with db.session_factory() as session:
        session.info["reviewed_bond_valuation_path"] = valuation
        assert read_account(session) == ("Synthetic", "one")
        assert read_account(session) == ("Synthetic", "one")
        assert len(calls) == 1
        with db.session_factory() as writer:
            writer.get(Account, 1).name = "Rolled back"
            writer.flush()
            writer.rollback()
        assert read_account(session) == ("Synthetic", "one")
        with db.session_factory() as writer:
            writer.get(Account, 1).name = "Committed"
            writer.commit()
        assert read_account(session) == ("Committed", "one")
        # Same length/mtime is insufficient; the content hash must change.
        import os

        previous = valuation.stat()
        valuation.write_text("two")
        os.utime(valuation, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        assert read_account(session) == ("Committed", "two")
        valuation.unlink()
        with pytest.raises(FileNotFoundError):
            read_account(session)
        session.add(Account(name="Pending", account_type="other"))
        with pytest.raises(ReadSnapshotMutationError):
            read_account(session)


def test_content_cache_is_bounded_and_never_caches_errors(db, monkeypatch):
    from hermes_finance.api import read_cache

    monkeypatch.setattr(read_cache, "MAX_ENTRIES", 2)
    monkeypatch.setattr(read_cache, "_entries", __import__("collections").OrderedDict())
    monkeypatch.setattr(read_cache, "_size", 0)
    calls = []

    @read_cache.cached_read_endpoint
    def read_value(session, number):
        calls.append(number)
        if number < 0:
            raise ValueError("unavailable")
        return {"value": number, "unknown": None, "zero": 0}

    with db.session_factory() as session:
        for number in (1, 2, 3):
            assert read_value(session, number)["value"] == number
        assert len(read_cache._entries) == 2
        assert read_cache._size <= read_cache.MAX_CACHE_BYTES
        read_value(session, 1)
        assert calls == [1, 2, 3, 1]
        for _ in range(2):
            with pytest.raises(ValueError, match="unavailable"):
                read_value(session, -1)
        assert calls[-2:] == [-1, -1]


def test_content_cache_pins_wal_snapshot_during_concurrent_commit(db):
    from hermes_finance.api.read_cache import cached_read_endpoint
    from hermes_finance.persistence import Account

    with db.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    with db.session_factory() as writer:
        writer.add(Account(name="Before", account_type="other"))
        writer.commit()
    calls = []

    @cached_read_endpoint
    def read_account(session):
        calls.append(1)
        before = session.scalar(select(Account.name))
        if len(calls) == 1:
            with db.engine.begin() as writer:
                writer.exec_driver_sql("UPDATE accounts SET name = 'After'")
        return before, session.scalar(select(Account.name))

    with db.session_factory() as session:
        assert read_account(session) == ("Before", "Before")
        assert read_account(session) == ("After", "After")
        assert read_account(session) == ("After", "After")
        assert len(calls) == 2


def test_content_cache_replaced_identical_database_cannot_reuse_old_entry(db, tmp_path):
    import os
    import shutil

    from hermes_finance.api.read_cache import cached_read_endpoint

    calls = []

    @cached_read_endpoint
    def read_value(session):
        calls.append(1)
        return session.connection().exec_driver_sql("SELECT count(*) FROM accounts").scalar()

    with db.session_factory() as session:
        assert read_value(session) == 0
        assert read_value(session) == 0
    db.engine.dispose()
    replacement = tmp_path / "replacement.db"
    shutil.copyfile(db.database_path, replacement)
    os.replace(replacement, db.database_path)
    with db.session_factory() as session:
        assert read_value(session) == 0
        assert len(calls) == 2


def test_content_cache_never_publishes_a_read_rejected_by_snapshot_cleanup(db):
    from hermes_finance.api.read_cache import cached_read_endpoint
    from hermes_finance.database import ReadSnapshotMutationError
    from hermes_finance.persistence import Account

    calls = []

    @cached_read_endpoint
    def read_value(session):
        calls.append(1)
        if len(calls) == 1:
            session.add(Account(name="Rejected write", account_type="other"))
            return "must not be cached"
        return "fresh read"

    with db.session_factory() as session:
        with pytest.raises(ReadSnapshotMutationError):
            read_value(session)
        assert read_value(session) == "fresh read"
        assert read_value(session) == "fresh read"
        assert len(calls) == 2


def test_endpoint_scope_verifies_sources_once_across_separate_nested_readers(db, monkeypatch):
    from hermes_finance.api.read_cache import cached_read_endpoint

    basket_source(db)
    original = source_intake.read_intake
    calls = []

    def verified(session, original_id):
        calls.append(original_id)
        return original(session, original_id)

    monkeypatch.setattr(source_intake, "read_intake", verified)

    @cached_read_endpoint
    def composed(session, selection):
        with source_read_snapshot(session):
            first = returns_view._source_scopes(session)
        with source_read_snapshot(session):
            second = returns_view._source_scopes(session)
        assert first == second
        return first

    with db.session_factory() as session:
        first = composed(session, 1)
        assert calls and all(count == 1 for count in Counter(calls).values())
        assert "returns_source_scope_reads" not in session.info
        calls.clear()
        assert composed(session, 2) == first
        assert calls and all(count == 1 for count in Counter(calls).values())
