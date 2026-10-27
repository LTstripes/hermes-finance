"""Synthetic presentation adapter: exact DTOs and unchanged authoritative readers."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from test_source_instrument_returns_service import BOND, save
from test_source_monthly_returns_service import snapshot
from test_statement_import_mybroker import ACCOUNT, ISIN

from hermes_finance.api.returns_view import Context, Detail, Overview
from hermes_finance.api.returns_view import router as returns_router
from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.instrument_return import Metric
from hermes_finance.persistence import BrokerIdentityMapping, Instrument
from hermes_finance.services import returns_view as view
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.source_instrument_returns import read_instrument_returns
from hermes_finance.services.source_monthly_returns import read_monthly_returns

START, END = date(2030, 3, 31), date(2030, 4, 30)
SCOPE = f"source:{ACCOUNT}"


@pytest.mark.parametrize(
    "source_name, catalogue_name, expected",
    [
        ("Source stock", "Catalogue stock", "Source stock"),
        (None, "Catalogue stock", "Catalogue stock"),
        ("", "Catalogue stock", "Catalogue stock"),
        ("  ", "Catalogue stock", "Catalogue stock"),
        (ISIN, "Catalogue stock", "Catalogue stock"),
        (f" {ISIN.lower()} ", "Catalogue stock", "Catalogue stock"),
        (None, None, ISIN),
        (None, ISIN, ISIN),
        (ISIN, "  ", ISIN),
    ],
)
def test_exact_catalogue_name_is_presentation_only(
    db, monkeypatch, source_name, catalogue_name, expected
):
    save(db, trades=(), bond=None)
    direct_read = view.read_instrument_returns

    def named(*args, **kwargs):
        result = direct_read(*args, **kwargs)
        return replace(
            result,
            instruments=tuple(replace(r, source_name=source_name) for r in result.instruments),
        )

    monkeypatch.setattr(view, "read_instrument_returns", named)
    original = api_overview(db).instruments[0].model_dump(exclude={"name"})
    if catalogue_name is not None:
        with db.session_factory() as session:
            session.add(
                Instrument(isin=ISIN, name=catalogue_name, instrument_type="stock", is_active=False)
            )
            session.commit()
    before = snapshot(db)
    result = api_overview(db).instruments[0]
    with db.session_factory() as session:
        detail = Detail.model_validate(
            view.read_detail(session, scope=SCOPE, start=START, end=END, isin=ISIN)
        )
    assert result.name == detail.name == expected
    assert result.model_dump(exclude={"name"}) == original
    assert snapshot(db) == before


def test_ambiguous_source_names_and_conflicting_alias_do_not_guess_catalogue_identity(db):
    from hermes_finance.statement_import.mybroker import NS, PROVIDER

    save(db, trades=(), bond=None)

    def other_name(root):
        root.find(".//m:Details[@ISIN1]", NS).set("active_name", "Other source name")

    save(db, trades=(), bond=None, marker="conflicting-name", mutate=other_name)
    with db.session_factory() as session:
        target = Instrument(isin=BOND, name="Wrong alias target", instrument_type="bond")
        session.add(target)
        session.flush()
        session.add(
            BrokerIdentityMapping(
                provider=PROVIDER,
                subject_kind="instrument",
                provider_identity=ISIN,
                observed_isin=ISIN,
                hermes_instrument_id=target.id,
                status="effective",
                confirmed_at=datetime.now(UTC),
            )
        )
        session.commit()
        assert (
            read_instrument_returns(session, source_account=ACCOUNT).instruments[0].source_name
            is None
        )
    before = snapshot(db)
    assert api_overview(db).instruments[0].name == ISIN
    assert snapshot(db) == before


@pytest.fixture
def db(tmp_path, source_returns_database_factory):
    database = source_returns_database_factory(tmp_path)
    yield database
    database.engine.dispose()


def overview(db, start=START, end=END, scope=SCOPE):
    with db.session_factory() as session:
        return Overview.model_validate(
            view.read_overview(session, scope=scope, start=start, end=end)
        )


def api_overview(db, start=START, end=END):
    app = FastAPI()
    app.include_router(returns_router)

    def session():
        with db.session_factory() as value:
            yield value

    app.dependency_overrides[session_for_request] = session
    with TestClient(app) as client:
        response = client.get(
            "/api/returns/overview", params={"scope": SCOPE, "start": start, "end": end}
        )
    assert response.status_code == 200, response.text
    return Overview.model_validate(response.json())


def test_api_monthly_advisory_survives_income_recomposition_without_changing_values(
    db, monkeypatch
):
    save(db, trades=(), bond=None)
    with db.session_factory() as session:
        monthly = read_monthly_returns(session, source_account=ACCOUNT)
    row = replace(
        monthly.months[0],
        result=replace(
            monthly.months[0].result,
            growth_kopecks=2700,
            modified_dietz_return=Decimal("0.027"),
            reason_codes=(),
        ),
        flags=("seam_mismatch",),
        coupons_kopecks=300,
        dividends_kopecks=200,
    )
    monkeypatch.setattr(
        view, "read_monthly_returns", lambda *a, **k: replace(monthly, months=(row,))
    )
    before = snapshot(db)
    result = api_overview(db)
    for projected in (result.selected, result.history[0]):
        assert [
            getattr(projected, key).value for key in ("pnl", "rate", "coupons", "dividends")
        ] == ["2700", "0.027", "300", "200"]
        for key in ("pnl", "rate", "coupons", "dividends"):
            assert getattr(projected, key).reason_codes == ["seam_mismatch"]
    assert snapshot(db) == before


def test_api_intervals_keep_scoped_advisories_and_income_missingness(db, monkeypatch):
    for month in (4, 5, 6):
        save(db, month, trades=(), bond=None)
    with db.session_factory() as session:
        monthly = read_monthly_returns(session, source_account=ACCOUNT)
    rows = tuple(
        replace(
            row,
            flags=flags,
            coupons_kopecks=coupons,
            dividends_kopecks=200,
            result=replace(
                row.result, reason_codes=("missing_endpoint",) if coupons is None else ()
            ),
        )
        for row, flags, coupons in zip(
            monthly.months,
            (
                ("seam_mismatch",),
                ("seam_mismatch", "missing_endpoint"),
                ("outside_period_advisory",),
            ),
            (300, None, 500),
        )
    )
    totals = dict(
        growth_kopecks=5400,
        chained_return=Decimal("0.054729"),
        growth_reason_codes=(),
        chain_reason_codes=(),
    )
    segment = SimpleNamespace(start=START, end=date(2030, 5, 31), **totals)
    monkeypatch.setattr(
        view,
        "read_monthly_returns",
        lambda *a, **k: replace(
            monthly, months=rows, period=SimpleNamespace(**totals), segments=[segment]
        ),
    )
    result = api_overview(db, end=segment.end)
    assert result.selected.pnl.value == result.all_history.pnl.value == "5400"
    assert result.selected.rate.value == result.all_history.rate.value == "0.054729"
    assert (
        result.selected.pnl.reason_codes == result.selected.rate.reason_codes == ["seam_mismatch"]
    )
    assert "outside_period_advisory" in result.all_history.pnl.reason_codes
    assert result.selected.coupons.value is None
    assert result.selected.coupons.reason_codes == [
        "seam_mismatch",
        "missing_endpoint",
        "income_interval_unavailable",
    ]
    assert result.selected.dividends.value == "400"
    assert result.selected.dividends.reason_codes == ["seam_mismatch", "missing_endpoint"]


@pytest.mark.parametrize(
    "status, expected", [("supported", "12345"), ("provisional", "12345"), ("partial", None)]
)
def test_api_fallback_is_account_reconciliation_and_instrument_method_is_unchanged(
    db, monkeypatch, status, expected
):
    save(db, trades=(), bond=None)
    direct_read = view.read_instrument_returns

    def reconcile(*args, **kwargs):
        direct = direct_read(*args, **kwargs)
        return replace(
            direct,
            reconciliation=SimpleNamespace(
                account_growth=Metric(12345, status, ("seam_mismatch",))
            ),
        )

    monkeypatch.setattr(view, "read_instrument_returns", reconcile)
    result = api_overview(db, start=date(2030, 4, 15))
    assert result.selected.pnl.value == expected
    assert result.selected.pnl.method == "source_account_reconciliation"
    assert result.selected.pnl.reason_codes == ["seam_mismatch"]
    assert result.selected.pnl.estimate and result.selected.pnl.unit == "kopecks"
    assert result.selected.period.start == date(2030, 4, 15)
    assert result.selected.rate.value is None
    assert result.selected.rate.reason_codes == ["interval_rate_unavailable"]
    assert result.instruments[0].pnl.method == "instrument_return_v2"


def test_closed_default_ignores_new_draft_and_no_closed_is_explicit(db):
    with db.session_factory() as session:
        assert Context.model_validate(view.read_context(session)).default_period is None
        april = create_reporting_month(session, year=2030, month=4, snapshot_date=END)
        april.status = "closed"  # synthetic fixture only; never invoke a real Close
        session.commit()
        create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 31))
        result = Context.model_validate(view.read_context(session))
    assert (result.default_period.start, result.default_period.end) == (START, END)


@pytest.mark.parametrize("closing, expected", [("1100", "10000"), ("900", "-10000"), ("1000", "0")])
def test_real_readers_supply_signed_stock_results_and_bond_conditional_is_separate(
    db, closing, expected
):
    save(db, stock=("10", "10", "1000", closing), bond=("2", "2", "2000", "2100"), trades=())
    before = snapshot(db)
    statements = []

    def sql(_conn, _cursor, statement, *_args):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(db.engine, "before_cursor_execute", sql)
    try:
        result = overview(db)
        with db.session_factory() as session:
            canonical = read_monthly_returns(session, source_account=ACCOUNT)
            detail = Detail.model_validate(
                view.read_detail(session, scope=SCOPE, start=START, end=END, isin=ISIN)
            )
    finally:
        event.remove(db.engine, "before_cursor_execute", sql)
    stock = next(r for r in result.instruments if r.isin == ISIN)
    bond = next(r for r in result.instruments if r.isin == BOND)
    assert stock.pnl.value == expected
    assert bond.pnl.value is None and bond.conditional
    assert result.selected.pnl.value == str(canonical.months[0].result.growth_kopecks)
    assert detail.opening_quantity == detail.closing_quantity == "10"
    assert snapshot(db) == before
    assert not {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP"}.intersection(statements)
    serialized = result.model_dump_json()
    assert all(
        key not in serialized
        for key in ("manifest_digest", "source_reference", "event_key", "events", "native_ids")
    )


def test_history_gap_does_not_become_sum_of_available_months(db):
    save(db, trades=(), stock=("10", "10", "1000", "1100"), bond=None)
    save(db, 6, trades=(), stock=("10", "10", "1200", "1300"), bond=None)
    result = overview(db)
    assert result.all_history.pnl.value is None
    assert result.history[1].pnl.value is None
    assert result.instruments[0].pnl.value == "10000"
    assert result.all_history.rate.value is None


@pytest.mark.parametrize("closing, expected", [("1180", "8000"), ("1100", "0")])
def test_available_calendar_months_are_signed_exact_separate_and_replay_invariant(
    db, closing, expected
):
    save(db, trades=(), stock=("10", "10", "1000", "1100"), bond=None)
    save(db, 6, trades=(), stock=("10", "10", "1200", closing), bond=None)
    before = snapshot(db)
    result = api_overview(db, end=date(2030, 6, 30))
    partial = result.available_months_total
    assert partial.partial and partial.pnl.value == expected
    assert (partial.covered_months, partial.total_months) == (2, 3)
    assert [p.end.month for p in partial.included] == [4, 6]
    assert [m.period.end.month for m in partial.missing] == [5]
    assert partial.missing[0].reason_codes
    assert result.all_history.pnl.value is result.all_history.rate.value is None
    assert result.selected_available_months_total == partial
    assert partial.pnl.estimate and partial.pnl.unit == "kopecks"
    assert snapshot(db) == before
    save(db, trades=(), stock=("10", "10", "1000", "1100"), bond=None, marker="replay")
    assert api_overview(db, end=date(2030, 6, 30)).available_months_total == partial
    with db.session_factory() as session:
        alias = view.read_overview(
            session, scope="source:1234567", start=START, end=date(2030, 6, 30)
        )
    assert alias["available_months_total"] == partial.model_dump()


def test_available_months_empty_zero_large_duplicate_and_partial_cells():
    end = date(2030, 6, 30)
    history = [
        {
            "period": view.bounds(START, END),
            "pnl": view.metric(900719925474099301, reasons=["seam_mismatch"]),
        },
        {"period": view.bounds(date(2030, 5, 31), end), "pnl": view.metric(-900719925474099301)},
    ]
    partial = view._available_months(history, START, end, None)
    assert partial["pnl"]["value"] == "0"
    assert partial["pnl"]["reason_codes"] == ["seam_mismatch"]
    assert view._available_months([], START, end, None)["pnl"]["value"] is None
    duplicate = view._available_months([history[0], history[0]], START, END, None)
    assert duplicate["pnl"]["value"] is None
    assert duplicate["missing"][0]["reason_codes"] == ["calendar_month_ambiguous"]
    edge = view._available_months(history, date(2030, 4, 15), end, None)
    assert edge["covered_months"] == 1
    assert edge["missing"][0]["reason_codes"] == ["partial_calendar_month"]


def test_supported_outer_interval_wins_even_with_unavailable_months(db):
    save(db, trades=(), bond=None, end_month=6)
    before = snapshot(db)
    result = api_overview(db, end=date(2030, 6, 30))
    assert any(row.pnl.value is None for row in result.history)
    assert result.all_history.pnl.value is not None
    assert result.available_months_total is None
    assert result.selected_available_months_total is None
    assert snapshot(db) == before


def test_unavailable_months_keep_null_total_and_all_original_reasons(db, monkeypatch):
    save(db, trades=(), bond=None)
    direct_read = view.read_monthly_returns

    def unavailable(*args, **kwargs):
        monthly = direct_read(*args, **kwargs)
        row = monthly.months[0]
        return replace(
            monthly,
            months=(
                replace(
                    row,
                    result=replace(
                        row.result,
                        growth_kopecks=None,
                        modified_dietz_return=None,
                        reason_codes=("unknown_flow",),
                    ),
                    flags=("seam_mismatch",),
                ),
            ),
            period=replace(
                monthly.period,
                growth_kopecks=None,
                chained_return=None,
                growth_reason_codes=("unknown_flow",),
                chain_reason_codes=("unknown_flow",),
            ),
        )

    monkeypatch.setattr(view, "read_monthly_returns", unavailable)
    result = api_overview(db)
    assert result.available_months_total.pnl.value is None
    assert result.available_months_total.covered_months == 0
    assert result.available_months_total.total_months == 1
    assert result.available_months_total.missing[0].reason_codes == [
        "unknown_flow",
        "seam_mismatch",
    ]
    assert result.all_history.pnl.reason_codes == ["unknown_flow", "seam_mismatch"]


def test_conflicting_account_label_targets_are_not_resolved_by_same_name(db):
    from hermes_finance.persistence import Account
    from hermes_finance.statement_import.mybroker import PROVIDER

    save(db, trades=(), bond=None)
    with db.session_factory() as session:
        accounts = [Account(name="Same label", account_type="brokerage") for _ in range(2)]
        session.add_all(accounts)
        session.flush()
        for alias, account in zip((ACCOUNT, "1234567"), accounts):
            session.add(
                BrokerIdentityMapping(
                    provider=PROVIDER,
                    subject_kind="account",
                    provider_identity=alias,
                    hermes_account_id=account.id,
                    status="effective",
                    confirmed_at=datetime.now(UTC),
                )
            )
        session.commit()
        context = Context.model_validate(view.read_context(session))
    assert next(a for a in context.accounts if a.id == SCOPE).label == ACCOUNT


def test_source_context_groups_only_proved_aliases_keeps_ranges_and_accepted_compatibility(db):
    from hermes_finance.persistence import Account
    from hermes_finance.statement_import.mybroker import PROVIDER

    save(db, trades=(), bond=None)
    save(db, 6, trades=(), bond=None)
    with db.session_factory() as session:
        account = Account(name="Synthetic brokerage", account_type="brokerage")
        deposit = Account(name="Synthetic deposit", account_type="deposit")
        session.add_all([account, deposit])
        session.flush()
        session.add(
            BrokerIdentityMapping(
                provider=PROVIDER,
                subject_kind="account",
                provider_identity=ACCOUNT,
                hermes_account_id=account.id,
                status="effective",
                confirmed_at=datetime.now(UTC),
            )
        )
        session.commit()
        deposit_scope = f"account:{deposit.id}"
    before = snapshot(db)
    with db.session_factory() as session:
        context = Context.model_validate(view.read_context(session))
        compatible = view.read_overview(session, scope=deposit_scope, start=START, end=END)
    sources = [a for a in context.accounts if a.basis == "statements"]
    assert len(sources) == 1 and sources[0].id == SCOPE
    assert sources[0].label == f"Synthetic brokerage · {ACCOUNT}"
    assert context.scope_aliases == {"source:1234567": SCOPE}
    assert {p.end.month for p in context.source_periods[SCOPE]} == {4, 6}
    assert any(a.id == deposit_scope and a.basis == "accepted" for a in context.accounts)
    assert compatible["selected"]["pnl"]["method"] == "PERF04A"
    assert snapshot(db) == before


@pytest.mark.parametrize("case", ["conflict", "multiple", "unreadable", "similar"])
def test_source_context_does_not_hide_unproved_or_conflicting_accounts(db, monkeypatch, case):
    from test_source_monthly_returns_service import save_service_month

    save_service_month(db)
    if case == "conflict":
        save_service_month(db, 5, row_account="7654321-000")
    elif case == "multiple":
        save_service_month(
            db,
            5,
            mutate=lambda root: root.find(".//{MyBroker}Textbox11").set("acc_code", "7654321-000"),
        )
    elif case == "similar":
        save_service_month(db, 5, row_account="1234567-001")
    else:
        reader = view._selected_sources

        def unreadable(*args, **kwargs):
            selected, native = reader(*args, **kwargs)
            return [(o, None, "source_reader_unavailable") for o, _, _ in selected], native

        monkeypatch.setattr(view, "_selected_sources", unreadable)
    before = snapshot(db)
    with db.session_factory() as session:
        context = Context.model_validate(view.read_context(session))
    sources = {a.id for a in context.accounts if a.basis == "statements"}
    assert {SCOPE, "source:1234567"} <= sources
    assert context.scope_aliases == {}
    if case == "similar":
        assert "source:1234567-001" in sources
    assert snapshot(db) == before


@pytest.mark.parametrize("reinvest", [False, True])
def test_payout_replays_are_counted_once_and_sale_is_in_universe(db, reinvest):
    kwargs = dict(
        stock=("10", "1" if reinvest else "0", "1000", "100" if reinvest else "0"),
        bond=None,
        trades=((ISIN, "-10", "1100", "0", "0"),)
        + (((ISIN, "1", "100", "0", "0"),) if reinvest else ()),
        extra=(("Дивиденды", ISIN, "20"),),
    )
    save(db, **kwargs)
    save(db, marker="duplicate-original", **kwargs)
    result = overview(db)
    with db.session_factory() as session:
        direct = read_instrument_returns(
            session, source_account=ACCOUNT, opening_date=START, closing_date=END
        )
        detail = Detail.model_validate(
            view.read_detail(session, scope=SCOPE, start=START, end=END, isin=ISIN)
        )
    assert len(result.instruments) == 1
    assert detail.closing_quantity == ("1" if reinvest else "0")
    assert result.selected.dividends.value == "2000"
    assert detail.buys.value == ("10000" if reinvest else "0")
    assert result.instruments[0].pnl.value == str(direct.instruments[0].analysis.pnl.value)
    assert len([e for e in detail.events if e.kind == "SELL"]) == 1


def test_large_money_and_decimal_remain_strings_partial_is_withheld(db, monkeypatch):
    save(db, trades=(), bond=None)
    real_read = view.read_instrument_returns

    def large(*args, **kwargs):
        result = real_read(*args, **kwargs)
        row = result.instruments[0]
        a = replace(
            row.analysis,
            pnl=Metric(900719925474099301, "supported"),
            modified_dietz=replace(
                row.analysis.modified_dietz, value=Decimal("0.10000000000000000001")
            ),
        )
        return replace(result, instruments=(replace(row, analysis=a),))

    monkeypatch.setattr(view, "read_instrument_returns", large)
    result = overview(db)
    assert result.instruments[0].pnl.value == "900719925474099301"
    assert result.instruments[0].rate.value == "0.10000000000000000001"
    assert view._instrument_metric(Metric(123, "partial"))["value"] is None


def test_invalid_scope_never_falls_back_and_accepted_reader_keeps_null(db):
    with pytest.raises(ValueError, match="returns_scope_unknown"):
        overview(db, scope="source:missing")
    result = overview(db, scope="portfolio")
    assert result.selected.pnl.value is result.selected.rate.value is None
    assert result.instruments == []
    assert result.selected.pnl.method == "PERF04A"
    assert result.selected.rate.unit == "percentage_points"


@pytest.mark.parametrize("draft_between", [False, True])
def test_accepted_history_preserves_missing_or_draft_calendar_month(db, draft_between):
    with db.session_factory() as session:
        for month, day in ((1, 31), (3, 31)):
            row = create_reporting_month(
                session, year=2030, month=month, snapshot_date=date(2030, month, day)
            )
            row.status = "closed"
            session.commit()
        if draft_between:
            create_reporting_month(session, year=2030, month=2, snapshot_date=date(2030, 2, 28))
    before = snapshot(db)
    result = overview(db, scope="portfolio")
    assert [r.period.end for r in result.history] == [
        date(2030, 1, 31),
        date(2030, 2, 28),
        date(2030, 3, 31),
    ]
    missing = result.history[1]
    assert missing.period.start == date(2030, 1, 31)
    assert missing.pnl.value is missing.rate.value is None
    assert missing.pnl.reason_codes == ["calendar_month_not_closed"]
    assert snapshot(db) == before


def test_currentness_is_reread_no_summary_cache(db):
    save(db, trades=(), bond=None)
    before = overview(db)
    save(
        db, trades=(), bond=None, stock=("10", "10", "1000", "1400"), marker="conflicting-endpoint"
    )
    after = overview(db)
    assert before.instruments[0].pnl.value is not None
    assert after.selected.pnl.value is None
