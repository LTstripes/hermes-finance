"""Synthetic presentation adapter: exact DTOs and unchanged authoritative readers."""

from dataclasses import replace
from datetime import date
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
from hermes_finance.services import returns_view as view
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.source_instrument_returns import read_instrument_returns
from hermes_finance.services.source_monthly_returns import read_monthly_returns

START, END = date(2030, 3, 31), date(2030, 4, 30)
SCOPE = f"source:{ACCOUNT}"


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
