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


def basket_source(
    db, *, native=ACCOUNT, alias="1234567", closing="1100", month=4, extra=(), marker=""
):
    import calendar
    from xml.etree import ElementTree as ET

    from test_statement_import_broker_statement_provisional import provisional_xml

    from hermes_finance.services.source_intake import save_intake
    from hermes_finance.statement_import.mybroker import NS

    root = ET.fromstring(
        provisional_xml(beginning="1000", closing=closing, candidate_count=0, extra_money=extra)
    )
    root.set("marker", marker)
    trades = root.find("m:Trades/m:Report/m:Tablix2/m:Details_Collection", NS)
    for row in list(trades):
        trades.remove(row)
    raw = (
        ET.tostring(root)
        .decode()
        .replace(ACCOUNT, native)
        .replace("2030-04-", f"2030-{month:02d}-")
        .replace(".04.2030", f".{month:02d}.2030")
        .encode()
    )
    with db.session_factory() as session:
        return save_intake(
            session,
            document=raw,
            filename=f"Брокерский {alias} (01.{month:02d}.30-{calendar.monthrange(2030, month)[1]}.{month:02d}.30).xml",
            request_id=f"basket-{native}-{month}-{marker}",
        )["intake_id"]


def basket_api(db, categories="brokerage,iis,deposits,gold", start="2030-03-31", end="2030-04-30"):
    from hermes_finance.api.returns_view import Basket

    app = FastAPI()
    app.include_router(returns_router)

    def session():
        with db.session_factory() as value:
            yield value

    app.dependency_overrides[session_for_request] = session
    before = snapshot(db)
    with TestClient(app) as client:
        result = client.get(
            "/api/returns/basket", params={"categories": categories, "start": start, "end": end}
        )
    assert snapshot(db) == before
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    return Basket.model_validate(result.json())


def test_basket_native_union_loss_alias_replay_and_missing_month_are_exact_read_only(db):
    basket_source(db)
    basket_source(db, marker="replay")
    basket_source(db, month=6, closing="980")
    basket_source(db, native="7654321-000", alias="7654321", closing="900")
    before = snapshot(db)
    result = basket_api(db, end="2030-06-30")
    assert result.known_partial_subtotal_kopecks == "-2000"
    assert result.source_subtotal.covered_cells == 3
    assert result.source_subtotal.total_cells == 6
    assert len([c for c in result.components if c.basis == "statements"]) == 2
    assert result.result_kopecks is result.rate.value is None
    assert result.partial is True
    assert "calendar_month_missing" in result.source_subtotal.reason_codes
    assert snapshot(db) == before


@pytest.mark.parametrize("categories", ["brokerage", "iis", "deposits", "gold", ""])
def test_basket_single_and_empty_never_guess_historical_type_or_return(db, categories):
    basket_source(db)
    result = basket_api(db, categories)
    assert (
        result.known_partial_subtotal_kopecks is result.result_kopecks is result.rate.value is None
    )
    if categories in {"brokerage", "iis"}:
        assert "historical_brokerage_iis_type_unproven" in result.source_subtotal.reason_codes
    if not categories:
        assert result.components == []
        assert result.reason_codes == ["basket_empty_selection"]


@pytest.mark.parametrize("closing", ["1000", "9007199254740993"])
def test_basket_observed_zero_and_large_minor_units_are_strings(db, closing):
    basket_source(db, closing=closing)
    result = basket_api(db, "brokerage,iis")
    assert result.known_partial_subtotal_kopecks == str((int(closing) - 1000) * 100)
    assert result.source_subtotal.covered_cells == 1


@pytest.mark.parametrize(
    "extra",
    [
        (("Внесено по распоряжению Клиента", "Synthetic transfer in", "100"),),
        (("Выведено по распоряжению Клиента", "Synthetic transfer out", "-100"),),
        (
            ("Внесено по распоряжению Клиента", "Synthetic transfer in", "100"),
            ("Выведено по распоряжению Клиента", "Synthetic transfer out", "-100"),
        ),
    ],
)
def test_basket_external_crossings_are_withheld_even_when_net_zero(db, extra):
    basket_source(db, extra=extra)
    result = basket_api(db)
    assert result.known_partial_subtotal_kopecks is None
    assert "basket_crossing_reconciliation_unavailable" in result.source_subtotal.reason_codes


def test_basket_accepted_duplicate_and_current_type_edit_never_change_historical_money(db):
    from hermes_finance.persistence import Account
    from hermes_finance.statement_import.mybroker import PROVIDER

    basket_source(db)
    with db.session_factory() as session:
        account = Account(name="Synthetic", account_type="brokerage")
        session.add(account)
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
        identity = account.id
    result = basket_api(db, "brokerage,iis")
    assert len(result.components) == 1
    assert result.known_partial_subtotal_kopecks == "10000"
    with db.session_factory() as session:
        session.get(Account, identity).account_type = "iis"
        session.commit()
    assert basket_api(db, "brokerage,iis") == result
    assert basket_api(db, "iis").known_partial_subtotal_kopecks is None


def deposit_cell(db, *, month=4, interest=300, balance=100000, account_id=None, closed=True):
    from hermes_finance.persistence import Account, DepositSnapshot

    with db.session_factory() as session:
        if account_id is None:
            account = Account(name="Synthetic deposit", account_type="deposit")
            session.add(account)
            session.flush()
            account_id = account.id
        period = create_reporting_month(
            session, year=2030, month=month, snapshot_date=date(2030, month, 30)
        )
        session.add(
            DepositSnapshot(
                reporting_month_id=period.id,
                account_id=account_id,
                name="Placement",
                deposit_type="savings",
                balance_kopecks=balance,
                annual_rate_basis_points=1000,
                expected_monthly_interest_kopecks=9999,
                actual_interest_received_kopecks=interest,
            )
        )
        period.status = "closed" if closed else "draft"
        session.commit()
    return account_id


def test_basket_deposit_principal_expected_and_missingness_never_become_period_return(db):
    basket_source(db)
    account = deposit_cell(db, interest=300)
    deposit_cell(db, account_id=account, month=6, interest=0, balance=900000)
    result = basket_api(db, end="2030-06-30")
    assert result.known_partial_subtotal_kopecks == "10000"
    assert result.deposit_received_interest.value_kopecks == "300"
    assert result.deposit_received_interest.covered_cells == 2
    assert result.deposit_received_interest.total_cells == 3
    assert "calendar_month_missing_or_not_closed" in result.deposit_received_interest.reason_codes
    assert result.result_kopecks is None
    only = basket_api(db, "deposits", end="2030-06-30")
    assert only.known_partial_subtotal_kopecks is None
    assert only.deposit_received_interest.value_kopecks == "300"
    edge = basket_api(db, "deposits", start="2030-04-01")
    assert edge.deposit_received_interest.value_kopecks is None
    assert "partial_calendar_month" in edge.deposit_received_interest.reason_codes


def test_basket_known_source_deposit_overlap_never_counts_either(db):
    from hermes_finance.statement_import.mybroker import PROVIDER

    basket_source(db)
    account = deposit_cell(db)
    with db.session_factory() as session:
        session.add(
            BrokerIdentityMapping(
                provider=PROVIDER,
                subject_kind="account",
                provider_identity=ACCOUNT,
                hermes_account_id=account,
                status="effective",
                confirmed_at=datetime.now(UTC),
            )
        )
        session.commit()
    result = basket_api(db)
    assert (
        result.known_partial_subtotal_kopecks
        is result.deposit_received_interest.value_kopecks
        is None
    )
    assert "basket_account_identity_overlap" in result.source_subtotal.reason_codes
    assert basket_api(db, "deposits").deposit_received_interest.value_kopecks is None


@pytest.mark.parametrize("excluded", ["brokerage", "iis", "deposits", "gold"])
def test_basket_each_off_recomputes_membership_without_frontend_subtraction(db, excluded):
    basket_source(db)
    categories = ",".join(c for c in ("brokerage", "iis", "deposits", "gold") if c != excluded)
    result = basket_api(db, categories)
    assert result.known_partial_subtotal_kopecks == (
        None if excluded in {"brokerage", "iis"} else "10000"
    )
    assert excluded not in result.categories


def test_basket_transfer_pair_fee_never_looks_like_zero_union_gain(db):
    basket_source(
        db, closing="900", extra=(("Выведено по распоряжению Клиента", "Transfer A to B", "-100"),)
    )
    basket_source(
        db,
        native="7654321-000",
        alias="7654321",
        closing="1099",
        extra=(("Внесено по распоряжению Клиента", "Transfer A to B", "99"),),
    )
    result = basket_api(db, "brokerage,iis")
    assert result.known_partial_subtotal_kopecks is None
    assert result.source_subtotal.covered_cells == 0
    assert result.source_subtotal.total_cells == 2


def test_basket_raw_structural_warning_never_uses_reader_waiver_as_union_proof(db, monkeypatch):
    from hermes_finance.services import returns_basket

    basket_source(db)
    reader = returns_basket._selected_sources

    def raw_warning(*args, **kwargs):
        selected, native = reader(*args, **kwargs)
        return [
            (
                o,
                {
                    **v,
                    "document": {**v["document"], "syntax_blockers": ["4_Transfers_unsupported"]},
                },
                e,
            )
            for o, v, e in selected
        ], native

    monkeypatch.setattr(returns_basket, "_selected_sources", raw_warning)
    result = basket_api(db, "brokerage,iis")
    assert result.known_partial_subtotal_kopecks is None
    assert "basket_crossing_reconciliation_unavailable" in result.source_subtotal.reason_codes


def test_basket_two_native_accounts_mapped_to_one_accepted_account_are_not_two_addends(db):
    from hermes_finance.persistence import Account
    from hermes_finance.statement_import.mybroker import PROVIDER

    basket_source(db)
    basket_source(db, native="7654321-000", alias="7654321")
    with db.session_factory() as session:
        account = Account(name="Synthetic duplicate", account_type="brokerage")
        session.add(account)
        session.flush()
        for native in (ACCOUNT, "7654321-000"):
            session.add(
                BrokerIdentityMapping(
                    provider=PROVIDER,
                    subject_kind="account",
                    provider_identity=native,
                    hermes_account_id=account.id,
                    status="effective",
                    confirmed_at=datetime.now(UTC),
                )
            )
        session.commit()
    result = basket_api(db)
    assert result.known_partial_subtotal_kopecks is None
    assert "basket_account_identity_overlap" in result.source_subtotal.reason_codes


def test_basket_current_gold_cost_gain_is_not_period_return(db):
    from hermes_finance.persistence import Account, PositionSnapshot

    with db.session_factory() as session:
        account = Account(name="Synthetic physical asset", account_type="other")
        instrument = Instrument(name="Synthetic gold", instrument_type="gold")
        session.add_all([account, instrument])
        session.flush()
        month = create_reporting_month(session, year=2030, month=4, snapshot_date=END)
        session.add(
            PositionSnapshot(
                reporting_month_id=month.id,
                account_id=account.id,
                instrument_id=instrument.id,
                quantity=Decimal("1"),
                historical_instrument_type="gold",
                average_cost_per_unit_kopecks=10000,
                market_price_per_unit_kopecks=20000,
                market_value_kopecks=20000,
                cost_basis_kopecks=10000,
                unrealized_result_kopecks=10000,
                price_date=END,
                price_source="manual",
            )
        )
        month.status = "closed"
        session.commit()
    result = basket_api(db, "gold")
    assert (
        result.result_kopecks is result.known_partial_subtotal_kopecks is result.rate.value is None
    )
    assert result.components[0].cells[0].value_kopecks is None
    assert "physical_gold_period_evidence_unavailable" in result.components[0].cells[0].reason_codes


@pytest.mark.parametrize(
    "query",
    [
        "categories=gold,gold",
        "categories=other",
        "categories=brokerage&categories=iis",
        "start=2030-03-31&start=2030-03-30",
        "end=2030-03-31",
        "start=invalid",
    ],
)
def test_basket_api_rejects_ambiguous_selection(db, query):
    app = FastAPI()
    app.include_router(returns_router)

    def session():
        with db.session_factory() as value:
            yield value

    app.dependency_overrides[session_for_request] = session
    with TestClient(app) as client:
        assert (
            client.get(f"/api/returns/basket?start=2030-03-31&end=2030-04-30&{query}").status_code
            == 422
        )


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
