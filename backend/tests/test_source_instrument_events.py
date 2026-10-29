"""Saved synthetic originals -> dated events -> existing API, with no economic writes."""

import json
import sqlite3
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal, localcontext

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_source_instrument_returns_service import BOND, by_isin, read, save
from test_source_instrument_returns_service import db as db
from test_source_money_classifications_service import DIVIDEND_SECURITY, _security_instrument
from test_source_monthly_returns_service import snapshot
from test_statement_import_broker_statement_provisional import _add_money
from test_statement_import_mybroker import ACCOUNT, ISIN

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import SourceMoneyClassification
from hermes_finance.services import security_reg_isin_mappings as mappings
from hermes_finance.services import source_intake
from hermes_finance.services.source_bond_valuation import (
    FILE_PATH_KEY,
    FILE_VERSION,
    MAX_FILE_BYTES,
    BondEndpointBinding,
    ReviewedBondValuation,
    SourceRevision,
)
from hermes_finance.services.source_instrument_returns import read_instrument_returns
from hermes_finance.services.source_money_classifications import choose_classification
from hermes_finance.source_proof_file import file_incarnation
from hermes_finance.statement_import.mybroker import NS

CASH_RETURN = "Возврат средств по дог. № 90001 от 01.01.2030. Тестов Иван Иванович. Без НДС"


@pytest.mark.parametrize("choice", [None, "unknown"])
def test_contract_return_read_rule_preserves_saved_default_and_manual_choice(db, choice):
    intake = save(db, bond=None, trades=(), extra=(("Перевод", CASH_RETURN, "-50"),))
    with db.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).where(SourceMoneyClassification.intake_id == intake)
        )
        # An old intake predating this rule; do not rewrite it during a read.
        row.classification, row.origin, row.status = "unknown", "default_rule", "assumed"
        reference = row.source_reference
        session.commit()
        if choice:
            choose_classification(session, intake, reference, choice)
    before = snapshot(db)
    result = read(db)
    analysis = by_isin(result)[ISIN].analysis
    assert analysis.pnl.value == (None if choice else 10000)
    assert ("unrecognized_money" in analysis.reason_codes) == bool(choice)
    with db.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).where(
                SourceMoneyClassification.source_reference == reference
            )
        )
        assert row.classification == "unknown"
        assert row.origin == ("user_choice" if choice else "default_rule")
    assert snapshot(db) == before


@pytest.mark.parametrize("case", ["exact", "prefix", "ambiguous"])
def test_source_scope_nkd_uses_full_issue_not_shared_stock_name(db, case):
    def mutate(root):
        root.find(".//m:Details[@ISIN1]", NS).set("active_name", "Shared Issuer")
        bond = next(r for r in root.findall(".//m:Details[@ISIN1]", NS) if r.get("ISIN1") == BOND)
        bond.set("active_name", "Shared Issuer Bond 01")
        if case == "ambiguous":
            other = deepcopy(bond)
            other.set("ISIN1", "RU000A000002")
            root.find(
                "m:Positions/m:Report/m:Tablix1/m:active_type_Collection/"
                "m:active_type/m:Details_Collection",
                NS,
            ).append(other)

    label = "Shared Issuer" if case == "prefix" else "Shared Issuer Bond 01"
    save(db, trades=(), extra=(("НКД по сделке", "c " + label, "-20"),), mutate=mutate)
    before = snapshot(db)
    result = read(db)
    stock = by_isin(result)[ISIN].analysis
    assert ("unmatched_trade_money" in stock.reason_codes) == (case != "exact")
    if case == "exact":
        (event,) = by_isin(result)[BOND].analysis.events
        assert event.isin == BOND and event.attribution_basis == "source_issue"
        assert not event.counted and event.effective_isin is None
        assert all(leg.ownership == event.event_key for leg in event.cash_legs)
        assert "unmatched_trade_money" in event.reason_codes
        assert stock.pnl.value == 10000
    else:
        assert result.unresolved_events and stock.pnl.value is None
    assert result.financial_authority == "none"
    assert snapshot(db) == before


def _repo_source_scope(root, *, duplicate=False):
    rows = root.findall(".//m:Details[@trade_no]", NS)
    for row in rows:
        row.set("trade_no", "B90001")
        row.set("repo_no", "B90002")
        row.set("comment", "репо ч.1")
    if duplicate:
        other = deepcopy(rows[0])
        other.set("isin_reg", "RU000A000002")
        root.find("m:Trades/m:Report/m:Tablix2/m:Details_Collection", NS).append(other)


def _closed_native_issue(root, *, ambiguous=False, stock_collision=False):
    row = root.find(".//m:Details[@trade_no]", NS)
    row.set("p_name", "Shared Issuer Bond 01")
    if ambiguous:
        other = deepcopy(row)
        other.set("isin_reg", "RU000A000002")
        other.set("trade_no", "90000000001\n90000000002")
        root.find("m:Trades/m:Report/m:Tablix2/m:Details_Collection", NS).append(other)
    if stock_collision:
        root.find(".//m:Details[@ISIN1]", NS).set("active_name", "Shared Issuer Bond 01")


@pytest.mark.parametrize(
    "case", ["exact", "name_missing", "prefix", "ambiguous", "position_conflict"]
)
def test_native_trade_issue_scope_without_position_is_not_money_ownership(db, case):
    label = "Shared Issuer" if case == "prefix" else "Shared Issuer Bond 01"
    save(
        db,
        bond=None,
        trades=((BOND, "1", "100", "0", "0"),),
        extra=(("НКД по сделке", "c " + label, "-20"),),
        mutate=(
            None
            if case == "name_missing"
            else lambda r: _closed_native_issue(
                r, ambiguous=case == "ambiguous", stock_collision=case == "position_conflict"
            )
        ),
    )
    before = snapshot(db)
    result = read(db)
    stock = by_isin(result)[ISIN].analysis
    if case == "exact":
        (event,) = [e for e in by_isin(result)[BOND].analysis.events if e.kind == "UNRESOLVED"]
        assert event.isin == BOND and event.attribution_basis == "source_issue"
        assert not event.counted and event.effective_isin is None
        assert event.reason_codes == ("unmatched_trade_money",)
        assert event.native_identity is None
        assert all(leg.ownership == event.event_key for leg in event.cash_legs)
        assert stock.pnl.value == 10000
        assert "unmatched_trade_money" not in stock.reason_codes
    else:
        assert stock.pnl.value is None
        assert any("unmatched_trade_money" in e.reason_codes for e in result.unresolved_events)
    assert snapshot(db) == before and result.financial_authority == "none"


@pytest.mark.parametrize("confirmed_scoped", [False, True])
def test_native_trade_issue_scope_overlap_needs_each_original_proof(db, confirmed_scoped):
    extra = (("НКД по сделке", "c Shared Issuer Bond 01", "-20"),)
    scoped = save(
        db,
        bond=None,
        trades=((BOND, "1", "100", "0", "0"),),
        extra=extra,
        mutate=_closed_native_issue,
    )
    save(db, bond=None, trades=(), extra=extra, marker="missing-closed-issue-proof")
    if confirmed_scoped:
        with db.session_factory() as session:
            row = session.scalar(
                select(SourceMoneyClassification).where(
                    SourceMoneyClassification.intake_id == scoped
                )
            )
            choose_classification(session, scoped, row.source_reference, row.classification)
    before = snapshot(db)
    result = read(db)
    (event,) = [
        e for e in result.unresolved_events if "overlap_flow_choice_conflict" in e.reason_codes
    ]
    assert event.isin is None and not event.counted and len(event.source_references) == 2
    assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert snapshot(db) == before


@pytest.mark.parametrize("fault", ["reference_digest", "native_identity", "native_ordinal"])
def test_native_trade_issue_scope_requires_current_reference_chain(db, fault):
    from hermes_finance.services.source_instrument_events import _native_trade_issue_scopes

    intake = save(
        db,
        bond=None,
        trades=((BOND, "1", "100", "0", "0"),),
        mutate=_closed_native_issue,
    )
    before = snapshot(db)
    with db.session_factory() as session:
        view = source_intake.read_intake(session, intake)
    proven = _native_trade_issue_scopes(view)
    assert {target[1] for targets in proven.values() for target in targets if target} == {BOND}
    if fault == "reference_digest":
        row = next(
            o
            for o in view["observations"]
            if o["facts"].get("native_references", {}).get("trade_no")
        )
        row["facts"]["native_references"]["acc_code"] = "9999999-000"
    elif fault == "native_identity":
        view["document"]["trades"][0]["identity"] = "synthetic-stale-native-identity"
    else:
        view["document"]["trades"][0]["ordinal"] = 1
    assert not any(
        target for targets in _native_trade_issue_scopes(view).values() for target in targets
    )
    assert snapshot(db) == before


@pytest.mark.parametrize("case", ["exact", "unknown_id", "ambiguous"])
def test_source_scope_repo_native_reference_is_not_cash_authority(db, case):
    native_id = "B99999" if case == "unknown_id" else "B90001"
    save(
        db,
        trades=((BOND, "1", "100", "0", "0"),),
        extra=(("Расчеты по сделке " + native_id, "репо ч.1 c Synthetic stock", "-100"),),
        mutate=lambda r: _repo_source_scope(r, duplicate=case == "ambiguous"),
    )
    before = snapshot(db)
    result = read(db)
    stock = by_isin(result)[ISIN].analysis
    assert ("unmatched_trade_money" in stock.reason_codes) == (case != "exact")
    if case == "exact":
        (event,) = [
            e
            for e in by_isin(result)[BOND].analysis.events
            if e.attribution_basis == "native_repo_reference"
        ]
        assert event.isin == BOND and not event.counted and event.effective_isin is None
        assert event.reason_codes == ("unmatched_trade_money",)
        assert all(leg.ownership == event.event_key for leg in event.cash_legs)
        assert stock.pnl.value == 10000
        assert all(not e.counted for e in by_isin(result)[BOND].analysis.events)
    else:
        assert stock.pnl.value is None and result.unresolved_events
    assert snapshot(db) == before


def test_source_scope_repo_inconsistent_overlap_remains_root_gap(db):
    extra = (("Расчеты по сделке B90001", "репо ч.1 c Synthetic stock", "-100"),)
    save(
        db,
        trades=((BOND, "1", "100", "0", "0"),),
        extra=extra,
        mutate=_repo_source_scope,
    )
    save(db, trades=(), extra=extra, marker="missing-native-reference")
    before = snapshot(db)
    result = read(db)
    assert "overlap_flow_choice_conflict" in by_isin(result)[ISIN].analysis.reason_codes
    assert any("overlap_flow_choice_conflict" in e.reason_codes for e in result.unresolved_events)
    assert snapshot(db) == before


@pytest.mark.parametrize("kind", ["nkd", "repo"])
@pytest.mark.parametrize("confirmed_copy", ["scoped", "missing"])
def test_source_scope_overlap_classification_confirmation_cannot_attest_identity(
    db, kind, confirmed_copy
):
    extra = (
        (("НКД по сделке", "c Synthetic bond", "-20"),)
        if kind == "nkd"
        else (("Расчеты по сделке B90001", "репо ч.1 c Synthetic stock", "-100"),)
    )
    scoped = save(
        db,
        trades=() if kind == "nkd" else ((BOND, "1", "100", "0", "0"),),
        extra=extra,
        mutate=None if kind == "nkd" else _repo_source_scope,
    )
    missing = save(db, bond=None, trades=(), extra=extra, marker="no-issue-evidence")
    intake = scoped if confirmed_copy == "scoped" else missing
    with db.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).where(SourceMoneyClassification.intake_id == intake)
        )
        choose_classification(session, intake, row.source_reference, row.classification)
    before = snapshot(db)
    result = read(db)
    assert "overlap_flow_choice_conflict" in by_isin(result)[ISIN].analysis.reason_codes
    (event,) = [
        e for e in result.unresolved_events if "overlap_flow_choice_conflict" in e.reason_codes
    ]
    assert event.isin is None and not event.counted and event.effective_isin is None
    assert len(event.source_references) == 2
    assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "reg,isin,issuer",
    [
        ("1-04-33498-E", "RU000A0JPNM1", 'ПАО "Интер РАО"'),
        ("10401000B", "RU000A0JP5V6", "Банк ВТБ (ПАО)"),
        ("1-01-04715-A", "RU0007775219", 'ПАО "МТС"'),
    ],
)
def test_registration_scope_is_identity_only_and_never_accepts_payout(db, reg, isin, issuer):
    narrative = f"Дивиденды за 2029 г. по акциям {issuer} ({reg}). (Удержан налог 13 руб.)."
    save(db, bond=None, trades=(), extra=(("Перевод", narrative, "87"),))
    before = snapshot(db)
    result = read(db)
    assert by_isin(result)[ISIN].analysis.pnl.value == 10000
    scoped = by_isin(result)[isin].analysis
    (event,) = scoped.events
    assert event.isin == isin and event.attribution_basis == "registration_scope"
    assert event.persisted_link_status == "unresolved_no_match"
    assert not event.counted and event.effective_isin is None
    assert all(leg.ownership == event.event_key for leg in event.cash_legs)
    assert "payout_link_unresolved_no_match" in event.reason_codes
    assert scoped.pnl.value is None and scoped.components["dividends"].value is None
    assert result.income[0].isin is None  # legacy projection is not silently promoted
    assert not result.reconciliation.complete
    assert snapshot(db) == before


def test_registration_scope_conflicting_explicit_crosswalk_stays_unresolved(db):
    narrative = 'Дивиденды за 2029 г. по акциям ПАО "МТС" (1-01-04715-A). (Удержан налог 13 руб.).'
    save(db, bond=None, trades=(), extra=(("Перевод", narrative, "87"),))
    with db.session_factory() as session:
        _security_instrument(session, isin=ISIN)
        session.commit()
        mappings.set_mapping(session, "1-01-04715-A", ISIN)
    before = snapshot(db)
    result = read(db)
    assert result.unresolved_events[0].isin is None
    assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert snapshot(db) == before


def test_source_scope_does_not_hide_compensation_or_account_tax(db):
    save(
        db,
        trades=(),
        extra=(
            ("НКД по сделке", "c Synthetic bond", "-20"),
            ("Перевод", "Компенсация утраченных дивидендов FOREIGN_01", "10"),
            ("НДФЛ", "Погашение обязательств по НДФЛ за 2029 год", "-5"),
        ),
    )
    before = snapshot(db)
    result = read(db)
    reasons = set(by_isin(result)[ISIN].analysis.reason_codes)
    assert {
        "unrecognized_money",
        "payout_classification_conflict",
        "unallocated_instrument_cost",
    } <= reasons
    assert "unmatched_trade_money" not in reasons
    assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert "unmatched_trade_money" in by_isin(result)[BOND].analysis.reason_codes
    assert snapshot(db) == before


@pytest.mark.parametrize("change", ["kind", "metadata", "ambiguous", "missing_old_parse"])
def test_registration_scope_never_overrides_contradictory_saved_decisions(db, change):
    narrative = "Дивиденды за 2029 г. по акциям Банк Синтетический (ПАО) (10401000B). (Удержан налог 13 руб.)."
    intake = save(db, bond=None, trades=(), extra=(("Перевод", narrative, "87"),))
    with db.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).where(SourceMoneyClassification.intake_id == intake)
        )
        if change == "kind":
            row.classification, row.instrument_link_status = "coupon", "not_parsed"
        elif change == "metadata":
            row.instrument_link_status, row.security_reg_number = "not_parsed", "1-01-99999-Z"
        elif change == "ambiguous":
            row.instrument_link_status = "unresolved_ambiguous"
        else:
            row.instrument_link_status = "not_parsed"
            row.security_reg_number = row.security_issuer = None
        session.commit()
    before = snapshot(db)
    result = read(db)
    if change == "missing_old_parse":
        (event,) = by_isin(result)["RU000A0JP5V6"].analysis.events
        assert event.attribution_basis == "registration_scope" and not event.counted
        assert event.reason_codes == ("payout_link_missing",)
        assert by_isin(result)[ISIN].analysis.pnl.value == 10000
    else:
        assert result.unresolved_events and result.unresolved_events[0].isin is None
        assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert snapshot(db) == before


def _reviewed_bond_packet(db, *, sides=("opening", "closing"), intake_id=None):
    """Synthetic trusted-caller decision, not a production acceptance API."""
    from hermes_finance.services.source_monthly_returns import _selected_sources

    with db.session_factory() as session:
        selected, native = _selected_sources(session, ACCOUNT)
        views = [v for _, v, error in selected if not error]
    sources = tuple(
        SourceRevision(
            v["id"],
            v["document_sha256"],
            v["document"]["provider"],
            v["document"]["parser"],
            v["generation"],
            v["head_seq"],
            v["manifest_digest"],
            v["covered_from"],
            v["covered_to"],
        )
        for v in views
    )
    view = next(v for v in views if v["id"] == (intake_id or views[0]["id"]))
    observation = next(
        o
        for o in view["observations"]
        if o["section"] == "positions" and o["facts"]["isin"] == BOND
    )
    return ReviewedBondValuation(
        "synthetic_independent_review",
        sources,
        tuple(
            BondEndpointBinding(
                view["id"],
                next(iter(native)),
                BOND,
                observation["facts"]["ordinal"],
                observation["locator"],
                observation["row_fingerprint"],
                side,
                date(2030, 4, 30) if side == "closing" else date(2030, 3, 31),
            )
            for side in sides
        ),
    )


def _read_reviewed_bond(db, packet):
    with db.session_factory() as session:
        return read_instrument_returns(
            session,
            source_account=ACCOUNT,
            reviewed_bond_valuation=packet,
        )


def _reviewed_bond_file(db, tmp_path):
    packet = _reviewed_bond_packet(db)
    payload = json.loads(json.dumps(asdict(packet), default=date.isoformat))
    payload.update(
        version=FILE_VERSION,
        status="accepted",
        database_incarnation=file_incarnation(db.database_path),
    )
    path = tmp_path / "synthetic-review.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, payload, packet


def test_reviewed_bond_file_reaches_ordinary_api_and_returns_then_revokes(
    db, tmp_path, monkeypatch
):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    path, payload, _ = _reviewed_bond_file(db, tmp_path)
    # Exercise the actual deployment setting and normal shared request session.
    monkeypatch.setenv("HERMES_FINANCE_REVIEWED_BOND_VALUATION_PATH", str(path))
    client = TestClient(create_app(database=db))
    before = snapshot(db)
    selection = {"scope": "source:" + ACCOUNT, "start": "2030-03-31", "end": "2030-04-30"}
    for accepted in (True, False):
        if not accepted:
            replacement = path.with_suffix(".next")
            replacement.write_text(json.dumps(payload | {"status": "revoked"}), encoding="utf-8")
            replacement.replace(path)
        response = client.get("/api/source-returns/instruments", params={"source_account": ACCOUNT})
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        result = response.json()
        bond = result["instruments"][0]
        assert bond["analysis"]["closing"]["economic_value_kopecks"] == (
            101000 if accepted else None
        )
        assert result["financial_authority"] == "none"
        assert not result["reconciliation"]["complete"]
        overview = client.get("/api/returns/overview", params=selection)
        detail = client.get("/api/returns/instrument", params=selection | {"isin": BOND})
        assert overview.status_code == detail.status_code == 200
        assert overview.json()["instruments"][0]["conditional"] is not accepted
        assert detail.json()["conditional"] is not accepted
        assert overview.headers["cache-control"] == detail.headers["cache-control"] == "no-store"
    assert snapshot(db) == before
    assert json.loads(path.read_text(encoding="utf-8")) == payload | {"status": "revoked"}


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "prepared",
        "revoked",
        "malformed",
        "duplicate_key",
        "extra_field",
        "version",
        "database",
        "relative",
        "oversize",
        "boolean_id",
        "head",
        "unreadable",
    ],
)
def test_reviewed_bond_file_failure_never_falls_back_to_packet(db, tmp_path, monkeypatch, failure):
    from pathlib import Path

    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    path, payload, packet = _reviewed_bond_file(db, tmp_path)
    if failure in {"prepared", "revoked"}:
        payload["status"] = failure
    elif failure == "version":
        payload["version"] = "unknown"
    elif failure == "database":
        payload["database_incarnation"] = "0" * 64
    elif failure == "extra_field":
        payload["automatic_acceptance"] = True
    elif failure == "boolean_id":
        payload["sources"][0]["intake_id"] = True
    elif failure == "head":
        payload["sources"][0]["head_seq"] += 2
    raw = json.dumps(payload)
    if failure == "duplicate_key":
        raw = '{"status":"revoked",' + raw[1:]
    elif failure == "malformed":
        raw = "{"
    elif failure == "oversize":
        raw = " " * (MAX_FILE_BYTES + 1)
    path.write_text(raw, encoding="utf-8")
    if failure == "missing":
        path.unlink()
    elif failure == "relative":
        path = Path(path.name)
    elif failure == "unreadable":
        original_open = Path.open

        def denied(value, *args, **kwargs):
            if value == path:
                raise PermissionError("synthetic review denied")
            return original_open(value, *args, **kwargs)

        monkeypatch.setattr(Path, "open", denied)
    before = snapshot(db)
    with db.session_factory() as session:
        session.info[FILE_PATH_KEY] = path
        result = read_instrument_returns(
            session, source_account=ACCOUNT, reviewed_bond_valuation=packet
        )
    assert result == read(db)
    assert snapshot(db) == before


def test_reviewed_bond_file_identical_database_copy_requires_new_binding(db, tmp_path):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    path, _, _ = _reviewed_bond_file(db, tmp_path)
    copied_path = tmp_path / "synthetic-restored.db"
    with (
        sqlite3.connect(str(db.database_path)) as source,
        sqlite3.connect(str(copied_path)) as target,
    ):
        source.backup(target)
    copied = create_database(copied_path)
    try:
        assert file_incarnation(copied_path) != file_incarnation(db.database_path)
        with copied.session_factory() as session:
            session.info[FILE_PATH_KEY] = path
            result = read_instrument_returns(session, source_account=ACCOUNT)
        assert by_isin(result)[BOND].analysis.closing.economic_value_kopecks is None
    finally:
        copied.engine.dispose()
    # A new application/session on the original physical DB still uses its exact binding.
    with db.session_factory() as session:
        session.info[FILE_PATH_KEY] = path
        result = read_instrument_returns(session, source_account=ACCOUNT)
    assert by_isin(result)[BOND].analysis.closing.economic_value_kopecks == 101000


@pytest.mark.parametrize("failure", ["connection_stamp", "incarnation_unavailable"])
def test_reviewed_bond_file_requires_physical_database_and_connection_stamp(
    db, tmp_path, monkeypatch, failure
):
    from hermes_finance import source_proof_file

    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    path, _, _ = _reviewed_bond_file(db, tmp_path)
    with db.session_factory() as session:
        session.info[FILE_PATH_KEY] = path
        if failure == "connection_stamp":
            session.connection().info["source_proof_incarnation"] = "0" * 64
        else:
            monkeypatch.setattr(source_proof_file, "file_incarnation", lambda _path: None)
        result = read_instrument_returns(session, source_account=ACCOUNT)
    assert by_isin(result)[BOND].analysis.closing.economic_value_kopecks is None


def test_reviewed_bond_file_cannot_be_selected_by_http_input(db, tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_FINANCE_REVIEWED_BOND_VALUATION_PATH", raising=False)
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    path, _, _ = _reviewed_bond_file(db, tmp_path)
    client = TestClient(create_app(database=db))
    response = client.get(
        "/api/source-returns/instruments",
        params={
            "source_account": ACCOUNT,
            "reviewed_bond_valuation_path": str(path),
            "accepted": "true",
        },
    )
    assert response.status_code == 200
    assert (
        response.json()["instruments"][0]["analysis"]["closing"]["economic_value_kopecks"] is None
    )


def test_reviewed_bond_endpoint_native_once_read_only_and_account_unchanged(db):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    ordinary = read(db)
    packet = _reviewed_bond_packet(db)
    before = snapshot(db)
    result = _read_reviewed_bond(db, packet)
    bond = by_isin(result)[BOND]
    for endpoint, value in ((bond.analysis.opening, 100000), (bond.analysis.closing, 101000)):
        assert endpoint.reported_value_kopecks == endpoint.economic_value_kopecks == value
        assert endpoint.accrued_interest_kopecks is None
        assert endpoint.valuation_basis == "dirty"
        assert endpoint.source_references.count("bond-basis:synthetic_independent_review") == 1
    assert bond.analysis.pnl.value == 1000
    assert bond.analysis.opening.date == date(2030, 3, 31)
    assert bond.analysis.closing.date == date(2030, 4, 30)
    assert "bond_valuation_basis_unknown" not in bond.months[0].flags
    assert result.reconciliation == ordinary.reconciliation
    assert result.authority == "provisional" and result.financial_authority == "none"
    assert snapshot(db) == before
    # Withdrawing the caller's decision supplies no basis; no process cache survives.
    assert read(db) == ordinary


@pytest.mark.parametrize("side", ["opening", "closing"])
def test_reviewed_bond_one_side_does_not_promote_other_side_or_month(db, side):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    bond = by_isin(_read_reviewed_bond(db, _reviewed_bond_packet(db, sides=(side,))))[BOND]
    assert getattr(bond.analysis, side).valuation_basis == "dirty"
    other = "opening" if side == "closing" else "closing"
    assert getattr(bond.analysis, other).economic_value_kopecks is None
    assert bond.analysis.pnl.value is None
    assert "bond_valuation_basis_unknown" in bond.months[0].flags


@pytest.mark.parametrize(
    "field,value",
    [
        ("document_sha256", "0" * 64),
        ("provider", "another_provider"),
        ("parser", "other_parser"),
        ("generation", 99),
        ("head_seq", 99),
        ("manifest_digest", "0" * 64),
        ("covered_from", "2030-04-02"),
        ("covered_to", "2030-04-29"),
        ("intake_id", 99),
    ],
)
def test_reviewed_bond_source_binding_mismatch_stays_unknown(db, field, value):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    packet = _reviewed_bond_packet(db)
    packet = replace(packet, sources=(replace(packet.sources[0], **{field: value}),))
    assert _read_reviewed_bond(db, packet) == read(db)


@pytest.mark.parametrize(
    "field,value",
    [
        ("native_account", "another_native_account"),
        ("isin", ISIN),
        ("ordinal", 999),
        ("locator", "s1/positions/999"),
        ("row_fingerprint", "0" * 64),
        ("side", "other"),
        ("valuation_date", date(2030, 4, 1)),
        ("intake_id", 999),
    ],
)
def test_reviewed_bond_row_binding_mismatch_stays_unknown(db, field, value):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    packet = _reviewed_bond_packet(db)
    packet = replace(packet, endpoints=(replace(packet.endpoints[0], **{field: value}),))
    assert _read_reviewed_bond(db, packet) == read(db)


@pytest.mark.parametrize(
    "change", ["dict", "duplicate_source", "duplicate_endpoint", "empty", "bad_ref"]
)
def test_reviewed_bond_invalid_packet_is_not_acceptance(db, change):
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    packet = _reviewed_bond_packet(db)
    if change == "dict":
        packet = {"accepted": True}
    elif change == "duplicate_source":
        packet = replace(packet, sources=packet.sources * 2)
    elif change == "duplicate_endpoint":
        packet = replace(packet, endpoints=packet.endpoints * 2)
    elif change == "empty":
        packet = replace(packet, endpoints=())
    else:
        packet = replace(packet, review_reference="arbitrary/path/to/file")
    assert _read_reviewed_bond(db, packet) == read(db)


@pytest.mark.parametrize("conflict", [False, True])
def test_reviewed_bond_overlap_checked_without_inheriting_acceptance(db, conflict):
    first = save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    old_packet = _reviewed_bond_packet(db)
    second = save(
        db,
        stock=None,
        bond=("1", "1", "1000", "1020" if conflict else "1010"),
        trades=(),
        marker="another exact original, same filename",
    )
    assert first != second
    assert _read_reviewed_bond(db, old_packet) == read(db)  # whole current set changed
    packet = _reviewed_bond_packet(db, intake_id=first)
    result = by_isin(_read_reviewed_bond(db, packet))[BOND].analysis
    if conflict:
        assert result.closing.economic_value_kopecks is None
        assert "overlapping_endpoint_conflict" in result.closing.reason_codes
    else:
        assert result.closing.economic_value_kopecks == 101000
        assert result.pnl.value == 1000
        assert len(result.closing.source_references) == 3  # two observations, one review


@pytest.mark.parametrize(
    "change",
    ["head_aba", "missing_bound", "unreadable", "inferred", "missing_row", "duplicate_row"],
)
def test_reviewed_bond_current_selection_failures_do_not_fallback(db, monkeypatch, change):
    from hermes_finance.services import source_instrument_returns as service

    first = save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=())
    save(db, stock=None, bond=("1", "1", "1000", "1010"), trades=(), marker="equal alternative")
    packet = _reviewed_bond_packet(db, intake_id=first)
    select_sources = service._selected_sources

    def changed(session, source_account):
        selected, scope = select_sources(session, source_account)
        original, view, error = selected[0]
        view = deepcopy(view)
        if change == "missing_bound":
            return selected[1:], scope
        if change == "unreadable":
            return [(original, None, "source_reader_unavailable"), *selected[1:]], scope
        if change == "head_aba":
            view["head_seq"] += 2  # identical manifest after two intervening revisions
        elif change == "inferred":
            view["document"]["warnings"] = ["period_inferred_from_content"]
        elif change == "missing_row":
            view["document"]["positions"] = []
        elif change == "duplicate_row":
            view["document"]["positions"] *= 2
        return [(original, view, error), *selected[1:]], scope

    monkeypatch.setattr(service, "_selected_sources", changed)
    result = by_isin(_read_reviewed_bond(db, packet))[BOND].analysis
    assert result.opening.economic_value_kopecks is None
    assert result.closing.economic_value_kopecks is None


@pytest.mark.parametrize("value", ["0", ""])
def test_reviewed_bond_explicit_zero_is_not_missing_value(db, value):
    save(db, stock=None, bond=("0", "0", value, value), trades=())
    result = by_isin(_read_reviewed_bond(db, _reviewed_bond_packet(db)))[BOND].analysis
    if value == "0":
        assert result.opening.economic_value_kopecks == result.closing.economic_value_kopecks == 0
    else:
        assert (
            result.opening.economic_value_kopecks is result.closing.economic_value_kopecks is None
        )


@pytest.mark.parametrize("fee", ["2", None])
def test_reviewed_bond_endpoint_does_not_double_nkd_or_clear_missing_cost(db, fee):
    save(
        db,
        stock=None,
        bond=("0", "1", "0", "1010"),
        trades=((BOND, "1", "1020", "20", fee),),
        mutate=trade_date(15, price="100", money=(("Купон", BOND, "30", 30),)),
    )
    ordinary = read(db)
    before = snapshot(db)
    result = _read_reviewed_bond(db, _reviewed_bond_packet(db))
    analysis = by_isin(result)[BOND].analysis
    assert analysis.closing.economic_value_kopecks == 101000
    assert analysis.closing.accrued_interest_kopecks is None
    assert analysis.events == by_isin(ordinary)[BOND].analysis.events
    if fee is None:
        assert analysis.pnl.value is None
        assert not analysis.coverage["costs"].complete
    else:
        assert analysis.components["buys"].value == 102200
        assert analysis.pnl.value == 1800  # 1010 - (1020 + 2) + 30; NKD only once
    assert result.reconciliation == ordinary.reconciliation
    assert snapshot(db) == before


def trade_date(day=10, *, depo=None, money=(), price="100", currency="RUB"):
    def mutate(root):
        for row in root.findall(".//m:Details[@trade_no]", NS):
            row.set("save_settlement_date", f"{day:02d}.04.2030")
            row.set("save_depo_settlement_date", f"{depo or day:02d}.04.2030")
            row.set("db_time", f"{day:02d}.04.2030 09:00:00")
            row.set("Price", price)
            row.set("curr_calc", currency)
        for operation, text, amount, posting in money:
            _add_money(root, operation, text, amount, day=f"2030-04-{posting:02d}")

    return mutate


@pytest.mark.parametrize(
    "opening,closing,qty,amount,day,expected,capital",
    [
        (("0", "10", "0", "1100"), None, "10", "1000", 10, 10000, 2000000),
        (("10", "15", "1000", "1600"), None, "5", "500", 5, 10000, 4250000),
        (("10", "15", "1000", "1600"), None, "5", "500", 25, 10000, 3250000),
        (("10", "6", "1000", "660"), None, "-4", "440", 15, 10000, 2340000),
        (("10", "0", "1000", "0"), None, "-10", "1100", 20, 10000, 1900000),
        (("0", "10", "0", "1100"), None, "10", "1000", 30, 10000, 0),
    ],
)
def test_saved_trade_contract_vectors(db, opening, closing, qty, amount, day, expected, capital):
    save(
        db,
        stock=opening,
        bond=closing,
        trades=((ISIN, qty, amount, None, "0"),),
        mutate=trade_date(day),
    )
    before = snapshot(db)
    instrument = by_isin(read(db))[ISIN]
    a = instrument.analysis
    assert a.pnl.value == expected, a.reason_codes
    assert a.modified_dietz.capital_days == capital
    if capital:
        with localcontext() as context:
            context.prec = 60
            assert a.modified_dietz.value == Decimal(expected * 30) / Decimal(capital)
    else:
        assert a.modified_dietz.value is None
    assert a.history_complete_since_acquisition == (opening[0] == "0")
    assert a.opening_date == date(2030, 3, 31) and a.closing_date == date(2030, 4, 30)
    assert a.events[0].cash_settlement_date == date(2030, 4, day)
    assert a.events[0].unit_price == 100
    assert a.events[0].attribution_basis == "native_trade_settlement"
    assert a.coverage["quantity"].complete
    assert a.pnl.status == "supported"
    assert instrument.months[0].analysis.pnl == a.pnl
    assert instrument.months[0].analysis.modified_dietz == a.modified_dietz
    assert snapshot(db) == before


def test_reinvestment_two_visible_events_and_other_isin_keeps_issuer(db):
    save(
        db,
        stock=("10", "11", "1000", "1100"),
        bond=None,
        trades=((ISIN, "1", "100", None, "0"),),
        extra=(("Дивиденды", ISIN, "100"),),
        mutate=trade_date(15),
    )
    a = by_isin(read(db))[ISIN].analysis
    assert {e.kind for e in a.events} == {"DIVIDEND", "BUY"}
    assert a.pnl.value == 10000 and a.modified_dietz.value == Decimal("0.1")
    assert a.events[0].gross_payout_kopecks is None
    # A distinct acquired security gets the BUY but not the issuer's payout.
    save(
        db,
        5,
        stock=("11", "11", "1100", "1100"),
        bond=("0", "1", "0", "100"),
        trades=((BOND, "1", "100", "0", "0"),),
        extra=(("Дивиденды", ISIN, "100"),),
        mutate=trade_date(15, price="10"),
    )
    result = by_isin(read(db))
    assert result[ISIN].months[1].analysis.components["dividends"].value == 10000
    assert result[BOND].months[1].analysis.components["dividends"].value == 0


@pytest.mark.parametrize("amount", ["1000"])
def test_bond_nkd_fee_known_components_but_unknown_endpoint_basis_only_estimate(db, amount):
    save(
        db,
        stock=None,
        bond=("0", "1", "0", "1010"),
        trades=((BOND, "1", amount, "20", "2"),),
        mutate=trade_date(15, price="98", money=(("Купон", BOND, "30", 30),)),
    )
    a = by_isin(read(db))[BOND].analysis
    assert a.components["buys"].value == 100200
    assert a.pnl.value is a.modified_dietz.value is None
    assert a.statement_estimate.pnl.value == 3800
    assert a.statement_estimate.pnl.status == "provisional"
    assert a.statement_estimate.modified_dietz.capital_days == 1503000
    assert a.statement_estimate.assumptions == ("bond_valuation_basis_unknown", "income_assumed")
    assert a.opening.economic_value_kopecks is None


@pytest.mark.parametrize("posting", [10, 12])
def test_matched_money_owns_principal_and_fee_once_on_actual_posting_date(db, posting):
    save(
        db,
        stock=("0", "10", "0", "1100"),
        bond=None,
        trades=((ISIN, "10", "1000", None, "2"),),
        mutate=trade_date(
            10,
            money=(
                ("Расчеты по сделке 10000000001", "Synthetic principal", "-1000", posting),
                ("Комиссия по сделке 10000000001", "Synthetic fee", "-2", posting),
            ),
        ),
    )
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value == 9800, a.reason_codes
    (buy,) = a.events
    assert len(buy.cash_legs) == 2
    assert all(leg.ownership.startswith("money:") for leg in buy.cash_legs)
    assert all(leg.date == date(2030, 4, posting) for leg in buy.cash_legs)
    assert a.modified_dietz.capital_days == 100200 * (30 - posting)


@pytest.mark.parametrize(
    "extra,reason",
    [
        ((("Комиссия", "ambiguous commission", "-2"),), "unallocated_instrument_cost"),
        ((("НДФЛ", "Дивиденды НДФЛ", "87"),), "payout_classification_conflict"),
        (
            (("Перевод", "Погашение облигаций Synthetic", "1000"),),
            "redemption_amortization_unsupported",
        ),
        ((("Дивиденды", "unidentified issuer", "87"),), "unattributed_income"),
    ],
)
def test_unallocated_or_misclassified_evidence_is_inspectable_not_zero(db, extra, reason):
    save(db, bond=None, trades=(), extra=extra)
    result = read(db)
    a = by_isin(result)[ISIN].analysis
    assert a.pnl.value is a.modified_dietz.value is None
    assert reason in a.reason_codes
    assert result.unresolved_events


def test_explicit_account_only_cost_is_not_allocated_and_tax_is_once(db):
    save(
        db,
        bond=None,
        trades=(),
        stock=("10", "10", "1000", "1000"),
        extra=(
            ("Дивиденды", ISIN, "100"),
            ("НДФЛ", ISIN, "-13"),
            ("Комиссия", "account maintenance", "-2"),
        ),
    )
    result = read(db)
    a = by_isin(result)[ISIN].analysis
    assert a.pnl.value == 8700
    assert a.components["taxes"].value == 1300
    assert result.account_reconciliation_events[0].cash_legs[0].account_cash_kopecks == -200


def setup_link(db):
    with db.session_factory() as session:
        instrument = _security_instrument(session, isin=ISIN)
        instrument_id = instrument.id
        session.commit()
        mappings.set_mapping(session, "1-01-99999-Z", ISIN)
    intake = save(db, bond=None, trades=(), extra=(("Перевод", DIVIDEND_SECURITY, "87"),))
    return intake, instrument_id


def test_persisted_link_revalidation_and_no_get_relink(db):
    intake, target = setup_link(db)
    before = snapshot(db)
    result = read(db)
    a = by_isin(result)[ISIN].analysis
    (payout,) = a.events
    assert payout.persisted_link_status == "linked" and payout.effective_isin == ISIN
    assert payout.gross_payout_kopecks == 18700 and payout.withheld_tax_kopecks == 10000
    assert a.pnl.value == 18700  # 100 valuation + 87 net, informational tax not subtracted
    assert a.source_references[0].parser_version != "unknown"
    assert snapshot(db) == before
    dependencies = a.source_references[0].link_dependencies
    with db.session_factory() as session:
        mappings.remove_mapping(session, "1-01-99999-Z")
    before = snapshot(db)
    result = read(db)
    assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert result.unresolved_events[0].effective_isin is None
    assert "payout_link_stale" in result.unresolved_events[0].reason_codes
    assert snapshot(db) == before
    with db.session_factory() as session:
        mappings.set_mapping(session, "1-01-99999-Z", ISIN)
    # Current read interpretation may recover; it never revives an accepted proof/receipt.
    result = read(db)
    assert by_isin(result)[ISIN].analysis.pnl.value == 18700
    assert by_isin(result)[ISIN].analysis.source_references[0].link_dependencies == dependencies
    assert result.financial_authority == "none"


def test_unresolved_saved_link_is_not_promoted_by_new_crosswalk(db):
    save(db, bond=None, trades=(), extra=(("Перевод", DIVIDEND_SECURITY, "87"),))
    with db.session_factory() as session:
        _security_instrument(session, isin=ISIN)
        session.commit()
        mappings.set_mapping(session, "1-01-99999-Z", ISIN)
    result = read(db)
    assert by_isin(result)[ISIN].analysis.pnl.value is None
    assert result.unresolved_events[0].persisted_link_status == "unresolved_no_match"


def test_payout_only_isin_has_missing_positions_and_manual_choice_preserved(db):
    with db.session_factory() as session:
        _security_instrument(session, isin="ZZ0000000011")
        session.commit()
        mappings.set_mapping(session, "1-01-99999-Z", "ZZ0000000011")
    intake = save(db, bond=None, trades=(), extra=(("Перевод", DIVIDEND_SECURITY, "87"),))
    a = by_isin(read(db))["ZZ0000000011"].analysis
    assert a.pnl.value is None and a.components["dividends"].value == 8700
    assert a.opening.quantity is a.closing.quantity is None
    with db.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).where(SourceMoneyClassification.intake_id == intake)
        )
        choose_classification(session, intake, row.source_reference, "external_deposit")
    before = snapshot(db)
    result = read(db)
    assert "payout_classification_conflict" in by_isin(result)[ISIN].analysis.reason_codes
    assert snapshot(db) == before


def test_overlap_occurrence_multiplicity_missing_conflict_and_unrelated_account(db):
    extra = (("Дивиденды", ISIN, "10"),) * 2
    save(db, bond=None, trades=(), extra=extra)
    save(
        db,
        bond=None,
        trades=(),
        extra=extra,
        marker="second",
        mutate=lambda r: r.find(".//m:Details[@ISIN1]", NS).set("active_name", "Synthetic alias"),
    )
    a = by_isin(read(db))[ISIN].analysis
    assert a.components["dividends"].value == 2000
    assert len(a.events) == 2
    save(
        db,
        bond=None,
        trades=(),
        extra=extra[:1],
        marker="third",
        mutate=lambda r: r.find(".//m:Details[@ISIN1]", NS).set("active_name", "Third alias"),
    )
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value is None and "overlap_money_occurrence_missing" in a.reason_codes


def test_same_isin_different_native_accounts_never_share_events(db):
    save(db, bond=None, trades=(), extra=(("Дивиденды", ISIN, "10"),))

    def other(root):
        for row in root.iter():
            for key in ("acc_code", "acc_code2"):
                if key in row.attrib:
                    row.set(key, "7654321-001")

    save(db, bond=None, trades=(), marker="other", extra=(("Дивиденды", ISIN, "20"),), mutate=other)
    assert by_isin(read(db, ACCOUNT))[ISIN].analysis.components["dividends"].value == 1000
    assert by_isin(read(db, "7654321-001"))[ISIN].analysis.components["dividends"].value == 2000
    assert read(db, "1234567").native_source_account is None


@pytest.mark.parametrize(
    "missing", ["save_settlement_date", "save_depo_settlement_date", "bank_tax"]
)
def test_missing_settlement_or_cost_remains_unknown(db, missing):
    def mutate(root):
        trade_date(10)(root)
        root.find(".//m:Details[@trade_no]", NS).attrib.pop(missing, None)

    save(
        db,
        bond=None,
        stock=("0", "10", "0", "1100"),
        trades=((ISIN, "10", "1000", None, "0"),),
        mutate=mutate,
    )
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value is a.modified_dietz.value is None
    assert len(a.events) == 1 and not a.events[0].counted


def test_outer_interval_supported_without_monthly_boundaries_and_selected_endpoint_validation(db):
    save(db, bond=None, trades=(), end_month=5)
    instrument = by_isin(read(db))[ISIN]
    a = instrument.analysis
    assert a.pnl.value == 10000 and a.modified_dietz.value == Decimal("0.1")
    assert a.chained_monthly.value is None
    assert not a.history_complete_since_acquisition
    assert all(row.analysis.pnl.value is None for row in instrument.months)
    with db.session_factory() as session:
        result = read_instrument_returns(
            session,
            source_account=ACCOUNT,
            isin=ISIN,
            opening_date=date(2030, 4, 1),
            closing_date=date(2030, 5, 30),
        )
    assert result.instruments[0].analysis.pnl.value is None


def test_v2_api_minor_units_decimal_fraction_legacy_and_queries(db):
    save(db, bond=None, trades=())
    before = snapshot(db)
    client = TestClient(create_app(database=db))
    query = dict(
        source_account=ACCOUNT, isin=ISIN, opening_date="2030-03-31", closing_date="2030-04-30"
    )
    response = client.get("/api/source-returns/instruments", params=query)
    assert response.status_code == 200, response.text
    row = response.json()["instruments"][0]
    assert row["analysis"]["pnl"]["value"] == 10000
    assert row["analysis"]["modified_dietz"]["value"] == "0.1"
    assert row["months"][0]["return_percent"] == "10"
    assert row["all_time"]["return_percent"] is None
    assert response.headers["cache-control"] == "no-store"
    for changes in ({"closing_date": "2030-03-31"}, {"opening_date": "bad"}, {"isin": "bad"}):
        assert (
            client.get("/api/source-returns/instruments", params=query | changes).status_code == 422
        )
    del query["opening_date"]
    assert client.get("/api/source-returns/instruments", params=query).status_code == 422
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "narrative", ["НКД по сделке 10000000001", "Накопленный купонный доход по сделке 10000000001"]
)
def test_matched_bond_money_principal_nkd_and_fee_each_have_one_owner(db, narrative):
    save(
        db,
        stock=None,
        bond=("0", "1", "0", "1010"),
        trades=((BOND, "1", "1000", "20", "2"),),
        mutate=trade_date(
            15,
            price="98",
            money=(
                ("Расчеты по сделке 10000000001", "Principal", "-980", 15),
                ("Перевод", narrative, "-20", 15),
                ("Комиссия по сделке 10000000001", "Fee", "-2", 15),
                ("Купон", BOND, "30", 30),
            ),
        ),
    )
    a = by_isin(read(db))[BOND].analysis
    assert a.statement_estimate.pnl.value == 3800, a.reason_codes
    buy = next(e for e in a.events if e.kind == "BUY")
    assert {leg.role for leg in buy.cash_legs} == {"principal", "nkd", "commission"}
    assert len({leg.ownership for leg in buy.cash_legs}) == 3


@pytest.mark.parametrize("nkd,fee", [("20", "2"), ("0", "2"), ("20", "0")])
def test_bond_buy_money_principal_keeps_native_nkd_once(db, nkd, fee):
    amount = str(Decimal("1000") + Decimal(nkd))
    save(
        db,
        stock=None,
        bond=("0", "1", "0", "1100"),
        trades=((BOND, "1", amount, nkd, fee),),
        mutate=trade_date(
            15,
            money=(
                ("Расчеты по сделке 10000000001", "Principal", "-1000", 16),
                ("Комиссия по сделке 10000000001", "Fee", str(-Decimal(fee)), 17),
            ),
        ),
    )
    before = snapshot(db)
    result = read(db)
    instrument = by_isin(result)[BOND]
    analysis = instrument.analysis
    (buy,) = analysis.events
    assert buy.counted, buy.reason_codes
    assert buy.native_total_basis == "includes_paid_nkd"
    assert buy.proof_dependency is None
    legs = {leg.role: leg for leg in buy.cash_legs}
    assert len(legs) == len(buy.cash_legs) == 3
    assert legs["principal"].account_cash_kopecks == -100000
    assert legs["nkd"].account_cash_kopecks == -int(Decimal(nkd) * 100)
    assert legs["commission"].account_cash_kopecks == -int(Decimal(fee) * 100)
    assert legs["principal"].date == date(2030, 4, 16)
    assert legs["commission"].date == date(2030, 4, 17)
    assert legs["nkd"].date == buy.cash_settlement_date == date(2030, 4, 15)
    assert legs["nkd"].ownership == buy.event_key + ":nkd"
    assert legs["nkd"].source_references == buy.source_references
    assert all(legs[role].ownership.startswith("money:") for role in ("principal", "commission"))
    cost = int((Decimal(amount) + Decimal(fee)) * 100)
    assert -sum(leg.account_cash_kopecks for leg in buy.cash_legs) == cost
    assert analysis.components["buys"].value == instrument.months[0].buys_cost_kopecks == cost
    assert analysis.statement_estimate.pnl.value == 110000 - cost
    assert analysis.statement_estimate.modified_dietz.capital_days == (
        100000 * 14 + int(Decimal(nkd) * 100) * 15 + int(Decimal(fee) * 100) * 13
    )
    assert analysis.pnl.value is analysis.modified_dietz.value is None
    assert "bond_valuation_basis_unknown" in analysis.reason_codes
    assert result.financial_authority == "none"
    assert snapshot(db) == before


@pytest.mark.parametrize("principal,fee", [("-1020", "-2"), ("-1000", "-3")])
def test_bond_buy_money_component_conflict_stays_uncounted(db, principal, fee):
    save(
        db,
        stock=None,
        bond=("0", "1", "0", "1100"),
        trades=((BOND, "1", "1020", "20", "2"),),
        mutate=trade_date(
            15,
            money=(
                ("Расчеты по сделке 10000000001", "Principal", principal, 15),
                ("Комиссия по сделке 10000000001", "Fee", fee, 15),
            ),
        ),
    )
    before = snapshot(db)
    analysis = by_isin(read(db))[BOND].analysis
    (buy,) = analysis.events
    assert not buy.counted
    assert "trade_money_cash_conflict" in buy.reason_codes
    assert analysis.pnl.value is analysis.modified_dietz.value is None
    assert analysis.statement_estimate.pnl.value is None
    assert snapshot(db) == before


@pytest.mark.parametrize("count", [1, 2])
def test_bond_buy_native_nkd_never_claims_anonymous_money(db, count):
    money = tuple(
        row
        for index in range(1, count + 1)
        for row in (
            (f"Расчеты по сделке 1000000000{index}", "Principal", "-1000", 15),
            (f"Комиссия по сделке 1000000000{index}", "Fee", "-2", 15),
        )
    ) + (("НКД по сделке", BOND, str(-20 * count), 15),)
    save(
        db,
        stock=None,
        bond=("0", str(count), "0", str(1100 * count)),
        trades=((BOND, "1", "1020", "20", "2"),) * count,
        mutate=trade_date(15, money=money),
    )
    before = snapshot(db)
    analysis = by_isin(read(db))[BOND].analysis
    buys = [event for event in analysis.events if event.kind == "BUY"]
    (orphan,) = [event for event in analysis.events if event.kind == "UNRESOLVED"]
    assert len(buys) == count and all(event.counted for event in buys)
    assert analysis.components["buys"].value == 102200 * count
    assert not orphan.counted and orphan.effective_isin is None
    assert "unmatched_trade_money" in orphan.reason_codes
    for buy in buys:
        (nkd,) = [leg for leg in buy.cash_legs if leg.role == "nkd"]
        assert nkd.ownership == buy.event_key + ":nkd"
        assert set(nkd.source_references).isdisjoint(orphan.source_references)
        assert all(leg.ownership != orphan.event_key for leg in buy.cash_legs)
    assert analysis.pnl.value is analysis.modified_dietz.value is None
    assert analysis.statement_estimate.pnl.value is None
    assert snapshot(db) == before


@pytest.mark.parametrize("missing", ["summ_nkd", "bank_tax"])
def test_bond_buy_money_does_not_fill_missing_native_components(db, missing):
    def mutate(root):
        trade_date(
            15,
            money=(
                ("Расчеты по сделке 10000000001", "Principal", "-1000", 15),
                ("Комиссия по сделке 10000000001", "Fee", "-2", 15),
            ),
        )(root)
        root.find(".//m:Details[@trade_no]", NS).attrib.pop(missing)

    save(db, stock=None, trades=((BOND, "1", "1020", "20", "2"),), mutate=mutate)
    before = snapshot(db)
    analysis = by_isin(read(db))[BOND].analysis
    (buy,) = analysis.events
    assert not buy.counted and not buy.cash_legs
    assert "trade_components_missing" in buy.reason_codes
    assert analysis.pnl.value is analysis.modified_dietz.value is None
    assert snapshot(db) == before


def test_bond_buy_mixed_legs_replay_overlap_and_current_classification(db):
    money = (
        ("Расчеты по сделке 10000000001", "Principal", "-1000", 15),
        ("Комиссия по сделке 10000000001", "Fee", "-2", 15),
    )
    options = dict(
        stock=None,
        bond=("0", "1", "0", "1100"),
        trades=((BOND, "1", "1020", "20", "2"),),
        mutate=trade_date(15, money=money),
    )
    intake = save(db, **options)
    assert save(db, **options) == intake
    save(db, **options, marker="overlap")

    def checked_read():
        before = snapshot(db)
        result = read(db)
        assert snapshot(db) == before
        return by_isin(result)[BOND].analysis

    analysis = checked_read()
    assert checked_read() == analysis
    (buy,) = analysis.events
    assert buy.counted and len(buy.source_references) == 2
    assert sum(leg.account_cash_kopecks for leg in buy.cash_legs) == -102200
    assert all(len(leg.source_references) == 2 for leg in buy.cash_legs)
    assert len({leg.ownership for leg in buy.cash_legs}) == 3
    with db.session_factory() as session:
        fee = session.scalar(
            select(SourceMoneyClassification).where(
                SourceMoneyClassification.intake_id == intake,
                SourceMoneyClassification.classification == "fee",
            )
        )
        reference = fee.source_reference
        choose_classification(session, intake, reference, "external_withdrawal")
    changed = checked_read()
    assert not changed.events[0].counted
    assert "trade_money_classification_conflict" in changed.events[0].reason_codes
    assert changed.source_references != analysis.source_references
    with db.session_factory() as session:
        choose_classification(session, intake, reference, "fee")
    assert checked_read().events[0].counted
    options["mutate"] = trade_date(15, money=money[1:])
    save(db, **options, marker="missing-principal-observation")
    incomplete = checked_read()
    assert not incomplete.events[0].counted
    assert "overlap_money_occurrence_missing" in incomplete.events[0].reason_codes
    assert incomplete.pnl.value is incomplete.modified_dietz.value is None


def test_conflicting_money_never_added_to_native_trade_total(db):
    save(
        db,
        stock=("0", "10", "0", "1100"),
        bond=None,
        trades=((ISIN, "10", "1000", None, "0"),),
        mutate=trade_date(10, money=(("Расчеты по сделке 10000000001", "Principal", "-999", 10),)),
    )
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value is None and "trade_money_cash_conflict" in a.reason_codes
    assert a.events[0].native_trade_amount_kopecks == 100000


@pytest.mark.parametrize(
    "change,reason",
    [
        ("inferred", "source_period_inferred"),
        ("depo", "cross_boundary_settlement"),
        ("pending", "trade_missing_settlement"),
        ("currency", "source_intake_currency_conflict"),
    ],
)
def test_inferred_pending_cross_boundary_and_currency_fail_closed(db, monkeypatch, change, reason):
    intake = save(
        db,
        stock=("0", "10", "0", "1100"),
        bond=None,
        trades=((ISIN, "10", "1000", None, "0"),),
        mutate=trade_date(10),
    )
    original = source_intake.read_intake

    def modified(session, intake_id):
        view = deepcopy(original(session, intake_id))
        assert intake_id == intake
        if change == "inferred":
            view["document"]["warnings"] = ["period_inferred_from_content"]
        elif change == "depo":
            view["document"]["trades"][0]["depo_settlement_date"] = "2030-05-01"
        elif change == "pending":
            view["document"]["trades"][0]["state"] = "pending"
        else:
            view["proposals"][0]["currency_assessment"]["reasons"] = [
                "source_intake_currency_conflict"
            ]
        return view

    monkeypatch.setattr(source_intake, "read_intake", modified)
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value is a.statement_estimate.pnl.value is None
    assert reason in a.reason_codes
    assert len(a.events) == 1


def test_broken_mapping_kind_and_classification_mutation_are_current_read_gaps(db):
    intake, instrument_id = setup_link(db)
    with db.session_factory() as session:
        from hermes_finance.persistence import Instrument

        instrument = session.get(Instrument, instrument_id)
        instrument.instrument_type = "bond"
        session.commit()
    result = read(db)
    assert result.unresolved_events[0].effective_isin is None
    assert "payout_link_stale" in result.unresolved_events[0].reason_codes
    with db.session_factory() as session:
        row = session.scalar(
            select(SourceMoneyClassification).where(SourceMoneyClassification.intake_id == intake)
        )
        row.amount_kopecks += 1
        session.commit()
    result = read(db)
    assert any("invalid_money_row" in e.reason_codes for e in result.unresolved_events)


@pytest.mark.parametrize("balance,residual", [("1085", 0), ("1086", 100)])
def test_account_reconciliation_counts_payout_once_and_excludes_promo(db, balance, residual):
    def mutate(root):
        row = root.find(".//m:Details[@active_type='Валюта']", NS)
        row.set("income_rest", "1000")
        row.set("real_rest", balance)

    save(
        db,
        bond=None,
        trades=(),
        stock=("10", "10", "1000", "1100"),
        mutate=mutate,
        extra=(("Дивиденды", ISIN, "87"), ("Комиссия", "account maintenance", "-2")),
    )
    r = read(db).reconciliation
    assert r.account_growth.value == 18500 + residual
    assert r.instrument_pnl.value == 18700
    assert r.account_only_result.value == -200
    assert r.residual.value == residual
    assert r.complete == (residual == 0)


def test_sold_out_missing_row_not_zero_and_trade_unknown_price_known_total(db, monkeypatch):
    save(
        db,
        stock=("10", "0", "1000", "0"),
        bond=None,
        trades=((ISIN, "-10", "1100", None, "0"),),
        mutate=trade_date(20),
    )
    original = source_intake.read_intake

    def missing_price(session, intake):
        view = deepcopy(original(session, intake))
        view["document"]["trades"][0]["core"]["price"] = None
        return view

    monkeypatch.setattr(source_intake, "read_intake", missing_price)
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value == 10000 and a.events[0].unit_price is None

    def missing_holding(session, intake):
        view = missing_price(session, intake)
        view["document"]["positions"] = []
        return view

    monkeypatch.setattr(source_intake, "read_intake", missing_holding)
    a = by_isin(read(db))[ISIN].analysis
    assert a.pnl.value is None and a.closing.quantity is None


def test_known_other_instrument_unrecognized_money_does_not_block_stock(db):
    save(
        db,
        trades=(),
        bond=("1", "1", "1000", "1000"),
        extra=(("Unsupported operation", BOND, "9"),),
    )
    instruments = by_isin(read(db))
    assert instruments[ISIN].analysis.pnl.value == 10000
    assert instruments[BOND].analysis.statement_estimate.pnl.value is None
    assert "unrecognized_money" in instruments[BOND].analysis.reason_codes


@pytest.mark.parametrize("qty,expected", [("1", 102200), ("-1", 101800)])
@pytest.mark.parametrize("face", [None, "1000", "500", "invalid"])
def test_mybroker_native_total_once_in_monthly_and_dated_read(db, qty, expected, face):
    def mutate(root):
        trade_date(15)(root)
        row = root.find(".//m:Details[@trade_no]", NS)
        row.attrib.pop("nominal")
        if face is not None:
            row.set("nominal", face)

    options = dict(
        stock=None,
        bond=("0", "1", "0", "1020") if qty == "1" else ("1", "0", "1020", "0"),
        trades=((BOND, qty, "1020", "20", "2"),),
        mutate=mutate,
    )
    intake = save(db, **options)
    # Equivalent overlapping observations and exact replay are still one event.
    assert save(db, **options) == intake
    save(db, **options, marker="equivalent-source")
    before = snapshot(db)
    result = read(db)
    row = by_isin(result)[BOND].months[0]
    analysis = by_isin(result)[BOND].analysis
    (event,) = [e for e in analysis.events if e.kind in {"BUY", "SELL"}]
    if face in (None, "1000"):
        assert (row.buys_cost_kopecks if qty == "1" else row.sells_proceeds_kopecks) == expected
        assert sum(leg.account_cash_kopecks for leg in event.cash_legs) == (
            -expected if qty == "1" else expected
        )
        assert event.native_total_basis == "includes_paid_nkd"
        assert ("trade_face_value_missing" in row.flags) == (face is None)
        assert ("trade_face_value_missing" in event.assumptions) == (face is None)
    else:
        assert row.buys_cost_kopecks is row.sells_proceeds_kopecks is None
        assert "trade_nkd_basis_unknown" in event.reason_codes
        assert not event.cash_legs
        if face == "500":
            assert "trade_nkd_basis_conflict" in event.reason_codes
    assert analysis.opening.valuation_basis == "reported_unknown"
    assert analysis.opening.economic_value_kopecks is None
    assert "bond_valuation_basis_unknown" in row.flags
    assert result.financial_authority == "none"
    assert snapshot(db) == before


@pytest.mark.parametrize("field,value", [("provider", "other"), ("parser", "mybroker-s1-v99")])
def test_mybroker_definition_requires_supported_frozen_source_scope(db, monkeypatch, field, value):
    save(db)
    original = source_intake.read_intake

    def modified(session, intake_id):
        view = deepcopy(original(session, intake_id))
        view["document"][field] = value
        return view

    monkeypatch.setattr(source_intake, "read_intake", modified)
    before = snapshot(db)
    instrument = by_isin(read(db))[BOND]
    assert instrument.months[0].buys_cost_kopecks is None
    assert "trade_nkd_basis_unknown" in instrument.months[0].flags
    (event,) = [e for e in instrument.analysis.events if e.kind == "BUY"]
    assert "trade_nkd_basis_unknown" in event.reason_codes
    assert not event.cash_legs
    assert snapshot(db) == before


@pytest.mark.parametrize("fee", [None, "2"])
def test_same_day_bonds_do_not_acquire_orphan_money_nkd_ownership(db, fee):
    save(
        db,
        stock=None,
        bond=("0", "2", "0", "2040"),
        trades=((BOND, "1", "1020", "20", fee), (BOND, "1", "1020", "20", fee)),
        mutate=trade_date(15, money=(("НКД по сделке", BOND, "-40", 15),)),
    )
    before = snapshot(db)
    result = read(db)
    instrument = by_isin(result)[BOND]
    buys = [e for e in instrument.analysis.events if e.kind == "BUY"]
    assert len(buys) == 2 and len({e.native_identity for e in buys}) == 2
    assert all(e.attribution_basis == "native_trade_settlement" for e in buys)
    assert all(not any(leg.role == "nkd" for leg in e.cash_legs) for e in buys)
    if fee is None:
        assert instrument.months[0].buys_cost_kopecks is None
        assert all("trade_components_missing" in e.reason_codes for e in buys)
    else:
        assert instrument.months[0].buys_cost_kopecks == 204400
    assert instrument.analysis.pnl.value is None  # EOD/ownership guards survive.
    assert snapshot(db) == before
