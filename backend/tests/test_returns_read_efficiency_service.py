"""Synthetic parity/currentness checks for the presentation read optimizations."""

import json
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import date
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import select
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


def _saved_investment(db, monkeypatch):
    persistence = saved_investment_preview(db, monkeypatch)["persistence"]
    with db.session_factory() as session:
        proofs.confirm(
            session,
            **{k: persistence[k] for k in ("form_token", "preview_digest")},
            request_id="read-efficiency-proof",
        )


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
