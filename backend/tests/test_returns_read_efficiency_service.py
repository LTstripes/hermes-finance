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


def test_proved_scope_map_reuses_only_one_snapshot_and_returns_owned_maps(db, monkeypatch):
    basket_source(db)
    original = returns_view._selected_sources
    calls = []

    def selected(session, account):
        calls.append(account)
        return original(session, account)

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
