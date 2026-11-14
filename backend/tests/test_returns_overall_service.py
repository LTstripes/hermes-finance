"""Synthetic all-history composition; no union-rate or financial-write claims."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_source_monthly_returns_service import snapshot

from hermes_finance.api.returns_overall import Overall, router
from hermes_finance.api.settings import session_for_request
from hermes_finance.persistence import (
    Account,
    BrokerIdentityMapping,
    DepositSnapshot,
    Instrument,
    PositionSnapshot,
)
from hermes_finance.services import returns_overall as overall
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.statement_import.mybroker import PROVIDER

ISIN = "RU000A000001"
START, END = date(2030, 3, 31), date(2030, 4, 30)


@pytest.fixture
def db(tmp_path, source_returns_database_factory):
    value = source_returns_database_factory(tmp_path)
    yield value
    value.engine.dispose()


def read(db):
    before = snapshot(db)
    with db.session_factory() as session:
        value = Overall.model_validate(
            overall.read_overall(session, include_instrument_details=True)
        )
    assert snapshot(db) == before
    return value


def component_rows(db, *, cost=10000, market=12500, result=2500, interest=0, same_account=False):
    with db.session_factory() as session:
        account = Account(name="Synthetic savings", account_type="savings")
        gold_account = Account(name="Synthetic metal", account_type="other")
        instrument = Instrument(name="Synthetic gold", instrument_type="gold")
        session.add_all([account, gold_account, instrument])
        session.flush()
        for month_number, status in [(4, "closed"), (5, "draft")]:
            month = create_reporting_month(
                session,
                year=2030,
                month=month_number,
                snapshot_date=date(2030, month_number, 30 if month_number == 4 else 31),
            )
            session.add(
                DepositSnapshot(
                    reporting_month_id=month.id,
                    account_id=account.id,
                    name="Synthetic placement",
                    deposit_type="savings",
                    balance_kopecks=999999,
                    annual_rate_basis_points=1800,
                    expected_monthly_interest_kopecks=100,
                    actual_interest_received_kopecks=interest if status == "closed" else 999,
                )
            )
            session.add(
                PositionSnapshot(
                    reporting_month_id=month.id,
                    account_id=account.id if same_account else gold_account.id,
                    instrument_id=instrument.id,
                    quantity=Decimal("10"),
                    average_cost_per_unit_kopecks=cost // 10,
                    market_price_per_unit_kopecks=market // 10,
                    market_value_kopecks=market if status == "closed" else 999999,
                    cost_basis_kopecks=cost,
                    unrealized_result_kopecks=result,
                    price_date=month.period_end,
                    manual_adjustment=False,
                )
            )
            month.status = status
        session.commit()


def test_empty_overall_is_get_only_no_store_and_not_zero(db):
    app = FastAPI()
    app.include_router(router)

    def session():
        with db.session_factory() as value:
            yield value

    app.dependency_overrides[session_for_request] = session
    before = snapshot(db)
    with TestClient(app) as client:
        response = client.get("/api/returns/overall")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    value = Overall.model_validate(response.json())
    assert value.overall.pnl.value is value.overall.rate.value is None
    assert value.annual_return is not None
    assert value.annual_return.portfolio.rate.value is None
    assert "overall_accounts_missing" in value.overall.rate.reason_codes
    assert value.deposits.interest.value is None
    assert value.source_accounts == value.instruments == value.gold.snapshots == []
    assert snapshot(db) == before


def test_known_zero_receipt_survives_missing_union_and_excludes_draft(db):
    component_rows(db)
    value = read(db)
    assert value.deposits.interest.value == "0"
    assert value.deposits.partial
    assert [p.status for p in value.deposits.periods] == ["closed", "draft"]
    assert "draft_deposit_interest_excluded" in value.deposits.reason_codes
    assert value.overall.pnl.value is value.overall.rate.value is None


def test_latest_closed_gold_preserves_saved_amounts_and_cost_based_fraction(db):
    component_rows(db)
    value = read(db)
    gold = value.gold.snapshots[0]
    assert gold.date == END
    assert (gold.market_value.value, gold.cost_basis.value, gold.unrealized_result.value) == (
        "12500",
        "10000",
        "2500",
    )
    assert gold.cost_return.value == "0.25"
    assert gold.cost_return.method == "saved_unrealized_over_cost"
    assert "historical_gold_classification_unproven" in gold.cost_return.reason_codes
    assert value.gold.period_result.value is None


@pytest.mark.parametrize(("cost", "market", "result"), [(0, 2500, 2500), (10000, 12500, 999)])
def test_unknown_or_conflicting_gold_cost_never_fabricates_percent(db, cost, market, result):
    component_rows(db, cost=cost, market=market, result=result)
    value = read(db)
    assert value.gold.snapshots[0].cost_return.value is None
    assert value.gold.snapshots[0].market_value.value == str(market)
    assert value.deposits.interest.value == "0"


def source_fixture(monkeypatch, *, stale_second=False, absent_second=False):
    accounts = ["native-a", "native-b"]
    monkeypatch.setattr(
        overall.returns_view,
        "_source_scopes",
        lambda session: {"alias-a": "native-a", "native-a": "native-a", "native-b": "native-b"},
    )
    monkeypatch.setattr(
        overall.returns_view,
        "_accounts",
        lambda session, canonical: (
            [
                {"id": f"source:{a}", "label": f"Synthetic {a}", "basis": "statements"}
                for a in accounts
            ]
            + [{"id": "account:42", "label": "Same accepted account", "basis": "accepted"}]
        ),
    )
    monkeypatch.setattr(
        overall,
        "_source_read_inputs",
        lambda session, account, **_selection: (
            [
                (
                    None,
                    {
                        "document": {"positions": [], "trades": [{"core": {"isin": ISIN}}]},
                        "proposals": [],
                    },
                    None,
                )
            ],
            {account},
        ),
    )
    monkeypatch.setattr(
        "hermes_finance.services.source_monthly_returns._selected_sources",
        overall._source_read_inputs,
    )
    calls = []

    def reports(session, *, source_account, analyses):
        calls.append(source_account)
        second = source_account == accounts[1]
        if second and absent_second:
            return []
        identity = 2 if second else 1
        start = START if not second else date(2030, 4, 9)

        def metric(value):
            return SimpleNamespace(status="supported", value=value, reason_codes=())

        analyses[identity] = {
            ISIN: SimpleNamespace(
                opening_date=start,
                closing_date=END,
                opening=SimpleNamespace(date=start, reported_value_kopecks=1000),
                closing=SimpleNamespace(date=END, reported_value_kopecks=1100),
                contract_version="instrument_return_v2",
                pnl=metric(100 if not second else -50),
                modified_dietz=metric(Decimal("0.1")),
                components={"coupons": metric(25), "dividends": metric(0)},
                statement_estimate=SimpleNamespace(pnl=metric(None)),
            )
        }
        return [
            {
                "proof_id": identity,
                "covered_from": str(start + timedelta(days=1)),
                "covered_to": str(END),
                "history_from_zero": True,
                "status": "stale" if second and stale_second else "current",
                "reason_codes": ["investment_proof_dependencies_changed"]
                if second and stale_second
                else [],
                "interval": None
                if second and stale_second
                else {
                    "reason_codes": [],
                    "opening_kopecks": "1000",
                    "closing_kopecks": "1100",
                    "pnl": {"value": "100" if not second else "-50"},
                    "modified_dietz": {"value": "0.1"},
                    "coupons_kopecks": "25",
                    "dividends_kopecks": "0",
                    "income_reason_codes": {},
                },
            }
        ]

    monkeypatch.setattr(overall.source_investment_proofs, "read_report_summaries", reports)
    monkeypatch.setattr(
        overall.source_investment_proofs,
        "read_report_display_candidates",
        lambda *a, **k: {"source": {}, "pdf": {}},
    )
    return calls


def test_same_isin_sold_and_multiple_accounts_are_kept_without_double_count_or_rate_sum(
    db, monkeypatch
):
    calls = source_fixture(monkeypatch)
    value = read(db)
    assert calls == ["native-a", "native-b"]
    assert len(value.source_accounts) == 2
    assert len(value.instruments) == 1
    rows = value.instruments[0].accounts
    assert [r.pnl.value for r in rows] == ["100", "-50"]
    assert rows[0].period != rows[1].period
    assert [r.rate.value for r in rows] == ["0.1", "0.1"]
    assert value.overall.pnl.value is value.overall.rate.value is None
    assert value.instruments[0].name == ISIN
    mixed = value.mixed_result
    assert mixed.known_result.value == "50"  # no instrument/payout/accepted-ledger additions
    assert mixed.rate.value is None
    assert mixed.selected_component_count == mixed.included_component_count == 2
    assert all(c.authority == "source_only" for c in mixed.components)


@pytest.mark.parametrize("absent", [False, True])
def test_unavailable_account_cannot_revive_captured_values_or_hide_known_sibling(
    db, monkeypatch, absent
):
    source_fixture(monkeypatch, stale_second=not absent, absent_second=absent)
    value = read(db)
    rows = value.instruments[0].accounts
    assert rows[0].pnl.value == "100"
    assert rows[1].pnl.value is rows[1].rate.value is rows[1].coupons.value is None
    assert value.source_accounts[1].proof_status == ("absent" if absent else "stale")
    assert rows[1].period is None if absent else rows[1].period is not None


def test_exact_catalogue_name_is_presentation_metadata_without_identity_or_money_changes(
    db, monkeypatch
):
    source_fixture(monkeypatch)
    with db.session_factory() as session:
        session.add(Instrument(name="Synthetic exact title", instrument_type="stock", isin=ISIN))
        session.commit()
    value = read(db)
    assert value.instruments[0].name == "Synthetic exact title"
    assert len(value.instruments[0].accounts) == 2
    assert value.instruments[0].accounts[0].pnl.value == "100"

    app = FastAPI()
    app.include_router(router)

    def session():
        with db.session_factory() as current:
            yield current

    app.dependency_overrides[session_for_request] = session
    with TestClient(app) as client:
        response = client.get("/api/returns/overall?basis=legacy")
    assert response.status_code == 200
    # The HTTP overview must carry the server short name, not a null that the
    # UI renders as an unnamed security.
    assert response.json()["instruments"][0]["short_name"] == "Synthetic exact title"


def identity_mappings(db, *, shared=False, cover_deposit=False):
    with db.session_factory() as session:
        a = Account(name="Synthetic broker A", account_type="brokerage")
        b = Account(name="Synthetic broker B", account_type="iis")
        session.add_all([a, b])
        session.flush()
        ids = [1 if cover_deposit else a.id, a.id if shared else b.id]
        for native, account_id in zip(["native-a", "native-b"], ids):
            session.add(
                BrokerIdentityMapping(
                    provider=PROVIDER,
                    subject_kind="account",
                    provider_identity=native,
                    hermes_account_id=account_id,
                    status="effective",
                    confirmed_at=datetime(2030, 5, 1, tzinfo=UTC),
                )
            )
        session.commit()


def test_available_snapshot_components_excluded_only_when_overlap_unproven(db, monkeypatch):
    component_rows(db, interest=250)
    source_fixture(monkeypatch)
    value = read(db)
    mixed = value.mixed_result
    assert mixed.known_result.value == "50"
    assert mixed.available_component_count == 4
    assert mixed.included_component_count == 2
    excluded = [c for c in mixed.components if not c.included]
    assert {c.category for c in excluded} == {"deposits", "gold"}
    assert all(c.exclusion_reason == "source_snapshot_overlap_unproven" for c in excluded)
    assert value.deposits.interest.value == "250"  # available, never silently discarded
    assert value.gold.snapshots[0].unrealized_result.value == "2500"


def test_proved_disjoint_components_can_sum_different_horizons_without_portfolio_rate(
    db, monkeypatch
):
    component_rows(db, interest=250)
    source_fixture(monkeypatch)
    identity_mappings(db)
    mixed = read(db).mixed_result
    assert mixed.known_result.value == "2800"
    assert mixed.included_component_count == 4
    assert mixed.rate.value is None
    assert "unknown_components_may_reduce_result" in mixed.reason_codes
    assert mixed.components[-1].interval is None
    assert mixed.components[-1].valuation_date == END


def test_conflicting_account_mapping_is_visible_and_not_a_numeric_fallback(db, monkeypatch):
    component_rows(db, interest=250)
    source_fixture(monkeypatch)
    identity_mappings(db, shared=True)
    mixed = read(db).mixed_result
    sources = [c for c in mixed.components if c.authority == "source_only"]
    assert all(c.available and not c.included and c.coverage.status == "conflict" for c in sources)
    assert all(c.exclusion_reason == "source_account_identity_mapping_conflict" for c in sources)
    assert mixed.known_result.value == "2750"


def test_source_already_covers_snapshot_account_so_interest_is_not_added_twice(db, monkeypatch):
    component_rows(db, interest=250)
    source_fixture(monkeypatch)
    identity_mappings(db, cover_deposit=True)
    mixed = read(db).mixed_result
    deposit = next(c for c in mixed.components if c.category == "deposits")
    assert deposit.available and not deposit.included
    assert deposit.exclusion_reason == "snapshot_account_already_covered_by_source"
    assert mixed.known_result.value == "2550"


def test_negative_known_component_is_not_dropped_or_promoted_to_profit_floor(db):
    component_rows(db, market=9500, result=-500)
    value = read(db)
    assert value.mixed_result.known_result.value == "-500"
    assert value.overall.pnl.value is value.overall.rate.value is None
    assert value.gold.period_result.value is None


def test_shared_account_across_snapshot_models_needs_disjointness_evidence(db):
    component_rows(db, interest=250, same_account=True)
    value = read(db)
    mixed = value.mixed_result
    assert mixed.available_component_count == 2
    assert mixed.included_component_count == 0
    assert mixed.known_result.value is None
    assert all(
        c.exclusion_reason == "canonical_snapshot_overlap_unproven" for c in mixed.components
    )
    assert value.deposits.interest.value == "250"
    assert value.gold.snapshots[0].unrealized_result.value == "2500"


def test_verified_source_display_metadata_names_sold_security_without_catalogue_write(
    db, monkeypatch
):
    source_fixture(monkeypatch)
    monkeypatch.setattr(
        overall.source_investment_proofs,
        "read_report_display_candidates",
        lambda *a, **k: {"source": {ISIN: ("Synthetic original title",)}, "pdf": {}},
    )
    value = read(db)
    assert value.instruments[0].name == "Synthetic original title"
    with db.session_factory() as session:
        assert session.query(Instrument).count() == 0


def test_real_synthetic_proof_overall_uses_one_summary_derivation_and_stale_never_falls_back(
    db, monkeypatch
):
    from test_returns_read_efficiency_service import _append_stale_proof, _saved_investment

    proofs = overall.source_investment_proofs
    _saved_investment(db, monkeypatch)
    derive = proofs._derive
    calls = []

    def observed(*args, **kwargs):
        calls.append(kwargs)
        return derive(*args, **kwargs)

    monkeypatch.setattr(proofs, "_derive", observed)
    value = read(db)
    assert len(calls) == 1 and calls[0]["include_xirr"] is False
    assert value.source_accounts[0].proof_status == "current"
    assert value.mixed_result.known_result.value == value.source_accounts[0].result.pnl.value
    assert value.mixed_result.known_result.value is not None
    assert value.instruments
    _append_stale_proof(db)
    value = read(db)
    assert value.source_accounts[0].proof_status == "stale"
    assert value.mixed_result.known_result.value is None
    assert value.instruments and all(
        pair.pnl.value is None for pair in value.instruments[0].accounts
    )


def test_default_index_does_not_request_instrument_analyses_or_detail(db, monkeypatch):
    source_fixture(monkeypatch)
    full = overall.source_investment_proofs.read_report_summaries

    def account_only(session, *, source_account):
        rows = full(session, source_account=source_account, analyses={})
        for row in rows:
            row["interval"]["instruments"] = [{"isin": ISIN}]
        return rows

    monkeypatch.setattr(
        overall.source_investment_proofs, "read_account_summaries", account_only, raising=False
    )
    monkeypatch.setattr(
        overall.source_investment_proofs,
        "read_report_summaries",
        lambda *a, **k: pytest.fail("hidden full instrument derivation"),
    )
    monkeypatch.setattr(
        overall.returns_view, "read_detail", lambda *a, **k: pytest.fail("hidden detail fetch")
    )
    with db.session_factory() as session:
        value = Overall.model_validate(overall.read_overall(session))
    assert value.mixed_result.known_result.value == "50"
    assert value.coupon_income.known_total.value == "50"
    assert value.dividend_income.known_total.value == "0"
    assert len(value.instruments) == 1
    assert all(not row.details_loaded for row in value.instruments[0].accounts)
    assert all(
        "instrument_details_not_requested" in row.pnl.reason_codes
        for row in value.instruments[0].accounts
    )


def test_explicit_http_summary_matches_existing_producer_without_cards_or_xirr(db, monkeypatch):
    from test_returns_read_efficiency_service import _saved_investment

    _saved_investment(db, monkeypatch)
    proofs = overall.source_investment_proofs
    derive, calls = proofs._derive, []

    def observed(*args, **kwargs):
        calls.append(kwargs)
        return derive(*args, **kwargs)

    monkeypatch.setattr(proofs, "_derive", observed)
    monkeypatch.setattr(
        overall.returns_view, "read_detail", lambda *a, **k: pytest.fail("hidden card detail")
    )
    expected = read(db)
    calls.clear()
    app = FastAPI()
    app.include_router(router)

    def session():
        with db.session_factory() as value:
            yield value

    app.dependency_overrides[session_for_request] = session
    before = snapshot(db)
    with TestClient(app) as client:
        response = client.get("/api/returns/overall?include_instrument_summaries=true&basis=legacy")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    value = Overall.model_validate(response.json())
    # HTTP adds the presentation short name and the isolated B9 projection.
    # Every pre-existing field outside the two authorized metrics stays equal.
    assert all(row.short_name for row in value.instruments)
    assert value.annual_return is not None
    assert value.overall.pnl == value.annual_return.portfolio.pnl
    assert value.overall.rate == value.annual_return.portfolio.rate
    projected = value.model_dump()
    projected["annual_return"] = None
    projected["overall"]["pnl"] = expected.overall.pnl.model_dump()
    projected["overall"]["rate"] = expected.overall.rate.model_dump()
    projected["instruments"] = [{**row, "short_name": None} for row in projected["instruments"]]
    assert projected == expected.model_dump()
    assert value.instruments
    assert all(pair.details_loaded for row in value.instruments for pair in row.accounts)
    assert any(pair.pnl.value is not None for row in value.instruments for pair in row.accounts)
    assert len(calls) == 1
    assert calls[0]["include_xirr"] is False and calls[0]["include_instruments"] is True
    assert all(
        set(pair)
        == {
            "native_period",
            "conditional_pnl",
            "conditional_rate",
            "scope",
            "label",
            "canonical_account_id",
            "account_link",
            "valuation_date",
            "details_loaded",
            "period",
            "pnl",
            "rate",
            "coupons",
            "dividends",
        }
        for row in response.json()["instruments"]
        for pair in row["accounts"]
    )  # Summaries contain no analysis/events/card DTO.
    assert snapshot(db) == before


@pytest.mark.parametrize("query", ["", "?include_instrument_summaries=false"])
def test_http_default_keeps_index_projection(db, monkeypatch, query):
    app = FastAPI()
    app.include_router(router)
    calls = []

    def read_projection(session, **kwargs):
        calls.append(kwargs)
        return overall.read_clean_overall(session, **kwargs)

    monkeypatch.setattr("hermes_finance.api.returns_overall.read_clean_overall", read_projection)

    def session():
        with db.session_factory() as value:
            yield value

    app.dependency_overrides[session_for_request] = session
    with TestClient(app) as client:
        response = client.get(f"/api/returns/overall{query}")
    assert response.status_code == 200
    assert calls == [{"include_instrument_details": False}]


@pytest.mark.parametrize(
    "query",
    [
        "include_instrument_summaries=true&include_instrument_summaries=false",
        "include_instrument_summaries=true&include_instrument_summaries=true",
        "include_instrument_summaries=1",
        "include_instrument_summaries=yes",
        "include_instrument_summaries=TRUE",
        "include_instrument_summaries=",
    ],
)
def test_http_summary_projection_rejects_ambiguous_or_nonliteral_selection(db, monkeypatch, query):
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr(
        "hermes_finance.api.returns_overall.read_overall",
        lambda *a, **k: pytest.fail("invalid projection reached reader"),
    )

    def session():
        with db.session_factory() as value:
            yield value

    app.dependency_overrides[session_for_request] = session
    with TestClient(app) as client:
        response = client.get(f"/api/returns/overall?{query}")
    assert response.status_code == 422


@pytest.mark.parametrize("basis", ["source", "pdf"])
def test_display_basis_resolves_sold_instrument_without_financial_writes(db, monkeypatch, basis):
    source_fixture(monkeypatch)
    candidates = {"source": {}, "pdf": {}}
    candidates[basis] = {ISIN: ("Synthetic verified metadata",)}
    monkeypatch.setattr(
        overall.source_investment_proofs,
        "read_report_display_candidates",
        lambda *a, **k: candidates,
    )
    value = read(db)
    assert value.instruments[0].name == "Synthetic verified metadata"
    assert value.mixed_result.known_result.value == "50"


@pytest.mark.parametrize("conflicting", [False, True])
def test_lazy_income_uses_actual_cash_legs_not_forecast_or_repeated_event(
    db, monkeypatch, conflicting
):
    from hermes_finance.domain.instrument_return import CashLeg, InstrumentEvent

    source_fixture(monkeypatch)
    reports = overall.source_investment_proofs.read_report_summaries

    def with_events(*args, **kwargs):
        rows = reports(*args, **kwargs)
        for analyses in kwargs["analyses"].values():
            analysis = analyses[ISIN]
            cash = CashLeg("income", END, 25, -25, ("synthetic",), "confirmed")
            event = InstrumentEvent(
                event_key="same-operation",
                provider=PROVIDER,
                native_source_account=kwargs["source_account"],
                isin=ISIN,
                kind="COUPON",
                source_references=("synthetic",),
                event_date=END,
                cash_legs=(cash,),
                net_payout_kopecks=999999,
            )
            from dataclasses import replace

            duplicate = (
                replace(
                    event, cash_legs=(CashLeg("income", END, 26, -26, ("other",), "confirmed"),)
                )
                if conflicting
                else event
            )
            analysis.events = (
                event,
                duplicate,
                replace(event, event_key="forecast", counted=False),
                replace(event, event_key="principal", kind="REDEMPTION"),
            )
            analysis.components["coupons"].status = "partial"
            analysis.components["coupons"].reason_codes = ("other_payout_unattributed",)
        return rows

    monkeypatch.setattr(overall.source_investment_proofs, "read_report_summaries", with_events)
    before = snapshot(db)
    with db.session_factory() as session:
        result = overall.read_income(session, kind="coupon")
    assert result["summary"]["known_total"]["value"] == "50"
    assert len(result["events"]) == (0 if conflicting else 2)
    assert [row["amount"]["value"] for row in result["events"]] == (
        [] if conflicting else ["25", "25"]
    )
    if conflicting:
        assert "income_event_identity_conflict" in result["reason_codes"]
        assert "known_account_income_not_fully_attributed" in result["reason_codes"]
    assert result["instruments"][0]["amount"]["value"] == "50"
    assert "other_payout_unattributed" in result["instruments"][0]["amount"]["reason_codes"]
    assert snapshot(db) == before


@pytest.mark.parametrize("kind", ["coupon", "dividend"])
@pytest.mark.parametrize(
    "conflict,count,expected", [(True, 2, None), (False, 2, "5000"), (True, 1, "2500")]
)
def test_clean_income_does_not_sum_conflicting_source_accounts(
    db, monkeypatch, kind, conflict, count, expected
):
    from hermes_finance.services import clean_instrument_return, source_instrument_returns

    period = {"start": date(2030, 3, 31), "end": date(2030, 4, 30)}
    scopes = ["source:native-a", "source:native-b"][:count]
    part = {"value": "2500", "status": "supported", "reason_codes": [], "assumptions": []}
    accounts = [
        {
            "scope": scope,
            "label": scope,
            "period": period,
            "result": {
                "instruments": [
                    {"isin": ISIN, "name": "Synthetic", "coupons": part, "dividends": part}
                ]
            },
        }
        for scope in scopes
    ]
    monkeypatch.setattr(
        clean_instrument_return, "read_clean_overview", lambda *a, **k: {"accounts": accounts}
    )
    monkeypatch.setattr(
        overall,
        "read_clean_overall",
        lambda *a, **k: {
            "coupon_income": {
                "known_total": overall.returns_view.metric(),
                "partial": True,
                "selected_accounts": count,
                "included_accounts": count,
                "accounts": [],
                "reason_codes": [],
            },
            "dividend_income": {
                "known_total": overall.returns_view.metric(),
                "partial": True,
                "selected_accounts": count,
                "included_accounts": count,
                "accounts": [],
                "reason_codes": [],
            },
            "mixed_result": {
                "components": [
                    {"id": scope, "coverage": {"status": "conflict" if conflict else "partial"}}
                    for scope in scopes
                ]
            },
        },
    )
    monkeypatch.setattr(
        source_instrument_returns,
        "read_instrument_returns",
        lambda *a, **k: SimpleNamespace(instruments=[]),
    )
    with db.session_factory() as session:
        result = overall.read_clean_income(session, kind=kind)
    item = result["instruments"][0]
    assert [row["amount"]["value"] for row in item["accounts"]] == ["2500"] * count
    assert item["amount"]["value"] == expected
    if conflict and count > 1:
        assert "source_account_identity_mapping_conflict" in item["amount"]["reason_codes"]
    app = FastAPI()
    app.include_router(router)

    def session():
        with db.session_factory() as value:
            yield value

    app.dependency_overrides[session_for_request] = session
    response = TestClient(app).get("/api/returns/income", params={"kind": kind})
    assert response.status_code == 200, response.text
    assert response.json()["contract_version"] == "returns_income_v2"
    assert response.json()["instruments"][0]["amount"]["value"] == expected


def test_card_combines_supported_accounts_keeps_local_gaps_and_no_combined_rate(db, monkeypatch):
    source_fixture(monkeypatch, stale_second=True)
    view = read(db).model_dump(mode="python")
    calls = []

    def detail(session, *, scope, start, end, isin):
        calls.append(scope)

        def metric(value):
            return SimpleNamespace(value=value, status="supported", reason_codes=())

        return {
            "valuation_date": end,
            "analysis": SimpleNamespace(
                closing=SimpleNamespace(
                    quantity=Decimal("0"), date=end, reported_value_kopecks=0, reason_codes=()
                ),
                pnl=metric(100),
                components={
                    name: metric(value)
                    for name, value in {
                        "coupons": 25,
                        "dividends": 0,
                        "valuation_and_trades": 90,
                        "fees": 10,
                        "taxes": 5,
                        "redemption": 0,
                    }.items()
                },
            ),
        }

    monkeypatch.setattr(overall.returns_view, "read_detail", detail)
    with db.session_factory() as session:
        value = overall.read_instrument_card(session, ISIN, overview=view)
        monkeypatch.setattr(
            overall,
            "_source_accounts",
            lambda session, **kwargs: (view["source_accounts"], view["instruments"], {}),
        )
        monkeypatch.setattr(overall, "read_overall", lambda *args, **kwargs: pytest.fail("unused"))
        assert overall.read_instrument_card(session, ISIN) == value
    assert calls == ["source:native-a", "source:native-a"]
    assert value["summary"]["pnl"]["value"] == "100"
    assert value["summary"]["quantity"]["value"] == "0"  # sold is retained
    assert value["summary"]["rate"]["value"] is None
    assert value["summary"]["costs"]["value"] == "10"
    assert value["summary"]["valuation_and_trades"]["value"] == "90"
    assert "instrument_accounts_missing_or_excluded" in value["summary"]["pnl"]["reason_codes"]
    assert value["accounts"][1]["detail"] is None


def test_card_ai_reference_counts_sources_without_the_instrument(db, monkeypatch):
    from hermes_finance.services import clean_instrument_return

    period = {"start": date(2030, 3, 31), "end": date(2030, 4, 30)}
    metric = {"value": "0", "status": "supported", "reason_codes": (), "assumptions": ()}
    item = {
        "isin": ISIN,
        "name": "synthetic",
        "closing_date": period["end"],
        **{
            name: metric
            for name in (
                "known_result",
                "coupons",
                "dividends",
                "payouts",
                "valuation_and_trades",
                "redemption",
                "closing_value",
            )
        },
    }
    clean = {
        "contract_version": "clean_returns_overview_v1",
        "accounts": [
            {"scope": "source:first", "period": period, "result": {"instruments": [], "gaps": []}},
            {
                "scope": "source:second",
                "period": period,
                "result": {"instruments": [item], "gaps": []},
            },
        ],
    }
    card = {
        "isin": ISIN,
        "summary": {},
        "accounts": [
            {
                "scope": "source:second",
                "period": period,
                "canonical_account_id": None,
                "detail": {"period": period},
                "exclusion_reason": None,
            }
        ],
    }
    monkeypatch.setattr(overall, "read_instrument_card", lambda *a, **k: card)
    monkeypatch.setattr(clean_instrument_return, "read_clean_overview", lambda *a, **k: clean)
    monkeypatch.setattr(overall.returns_view, "apply_clean_detail", lambda detail, item: detail)
    with db.session_factory() as session:
        selected = overall.read_clean_instrument_card(session, ISIN)
    exported = clean_instrument_return.clean_export_data(clean)
    assert selected["accounts"][0]["ai_account_ref"] == "source-account-2"
    assert exported["accounts"][1]["account_ref"] == "source-account-2"
    assert exported["accounts"][0]["instruments"] == []


def test_card_conflicting_mapping_does_not_fetch_or_sum_ambiguous_accounts(db, monkeypatch):
    source_fixture(monkeypatch)
    identity_mappings(db, shared=True)
    view = read(db).model_dump(mode="python")
    monkeypatch.setattr(
        overall.returns_view,
        "read_detail",
        lambda *a, **k: pytest.fail("ambiguous identity must not fetch detail"),
    )
    with db.session_factory() as session:
        value = overall.read_instrument_card(session, ISIN, overview=view)
    assert value["summary"]["pnl"]["value"] is None
    assert not any(row["included"] for row in value["accounts"])
    assert all(
        row["exclusion_reason"] == "source_account_identity_mapping_conflict"
        for row in value["accounts"]
    )


@pytest.mark.parametrize("conflict", [True, False])
def test_clean_card_keeps_scope_operations_and_does_not_sum_mapping_conflicts(
    db, monkeypatch, conflict
):
    from copy import deepcopy

    from hermes_finance.services import clean_instrument_return

    period = {"start": date(2030, 3, 31), "end": date(2030, 4, 30)}
    earlier = {"start": date(2030, 4, 1), "end": date(2030, 4, 30)}
    scopes = ["source:native-a", "source:native-b"] if conflict else ["source:native-a"]
    metric = {"value": 100, "status": "supported", "reason_codes": (), "assumptions": ()}
    item = {
        "isin": ISIN,
        "closing_date": period["end"],
        **{
            name: metric
            for name in (
                "known_result",
                "coupons",
                "dividends",
                "payouts",
                "valuation_and_trades",
                "redemption",
                "closing_value",
            )
        },
    }
    card = {
        "summary": {},
        "accounts": [
            {
                "scope": scope,
                "period": earlier,
                "canonical_account_id": None,
                "detail": None if conflict else {"period": earlier},
                "exclusion_reason": "source_account_identity_mapping_conflict"
                if conflict
                else None,
            }
            for scope in scopes
        ],
    }
    monkeypatch.setattr(overall, "read_instrument_card", lambda *a, **k: deepcopy(card))
    monkeypatch.setattr(
        clean_instrument_return,
        "read_clean_overview",
        lambda *a, **k: {
            "accounts": [
                {"scope": scope, "period": period, "result": {"instruments": [item]}}
                for scope in scopes
            ]
        },
    )
    calls = []

    def detail(session, *, scope, start, end, isin, native_period, clean_projection):
        assert clean_projection is True
        calls.append((scope, start, end, native_period))
        return {"period": {"start": start, "end": end}, "events": ["synthetic"]}

    monkeypatch.setattr(overall.returns_view, "read_detail", detail)
    monkeypatch.setattr(overall.returns_view, "apply_clean_detail", lambda value, clean: value)
    with db.session_factory() as session:
        result = overall.read_clean_instrument_card(session, ISIN)
    assert len(calls) == len(scopes)
    assert all(row["detail"]["events"] == ["synthetic"] for row in result["accounts"])
    assert result["summary"]["pnl"]["value"] == (None if conflict else "100")


@pytest.mark.parametrize(
    "blocker", [None, "assumption", "extra_reason", "wrong_period", "wrong_source"]
)
def test_card_known_source_only_components_require_current_exact_native_proof(
    db, monkeypatch, blocker
):
    source_fixture(monkeypatch)
    view = read(db).model_dump(mode="python")

    def detail(session, *, scope, start, end, isin):
        def metric(value):
            return SimpleNamespace(
                value=value,
                status="provisional",
                reason_codes=("source_sections_not_financially_accepted",)
                + (("missing_economic_endpoint",) if blocker == "extra_reason" else ()),
                assumptions=("estimated_cash",) if blocker == "assumption" else (),
            )

        return {
            "valuation_date": end,
            "analysis": SimpleNamespace(
                opening_date=date(2020, 1, 1) if blocker == "wrong_period" else start,
                closing_date=end,
                assumptions=("source_only_xml_pdf",) if blocker != "wrong_source" else (),
                closing=SimpleNamespace(
                    quantity=Decimal("3"), date=end, reported_value_kopecks=900, reason_codes=()
                ),
                pnl=metric(140),
                components={
                    name: metric(value)
                    for name, value in {
                        "coupons": 35,
                        "dividends": 15,
                        "valuation_and_trades": 100,
                        "fees": 10,
                        "taxes": 0,
                        "redemption": 0,
                    }.items()
                },
            ),
        }

    monkeypatch.setattr(overall.returns_view, "read_detail", detail)
    with db.session_factory() as session:
        card = overall.read_instrument_card(session, ISIN, overview=view)
    assert card["summary"]["pnl"]["value"] == ("280" if blocker is None else None)
    assert card["summary"]["coupons"]["value"] == ("70" if blocker is None else None)
    assert card["summary"]["dividends"]["value"] == ("30" if blocker is None else None)
    assert card["summary"]["rate"]["value"] is None
    assert (
        "combined_rate_periods_and_flows_not_proven"
        not in card["summary"]["quantity"]["reason_codes"]
    )


def test_income_isin_sum_retains_current_source_only_authority_without_promoting_estimates(
    db, monkeypatch
):
    source_fixture(monkeypatch)
    original = overall.source_investment_proofs.read_report_summaries

    def source_only(session, **kwargs):
        reports = original(session, **kwargs)
        for values in kwargs["analyses"].values():
            for analysis in values.values():
                analysis.assumptions = ("source_only_xml_pdf",)
                analysis.events = ()
                item = analysis.components["coupons"]
                item.status = "provisional"
                item.reason_codes = ("source_sections_not_financially_accepted",)
                item.assumptions = ()
        return reports

    monkeypatch.setattr(overall.source_investment_proofs, "read_report_summaries", source_only)
    with db.session_factory() as session:
        income = overall.read_income(session, kind="coupon")
    assert income["instruments"][0]["amount"]["value"] == "50"
    assert "known_account_income_not_fully_attributed" in income["reason_codes"]


def test_income_keeps_known_unattributed_operations_without_inventing_an_isin(db, monkeypatch):
    from hermes_finance.domain.instrument_return import CashLeg, InstrumentEvent

    source_fixture(monkeypatch)
    reports = overall.source_investment_proofs.read_report_summaries

    def with_unallocated(*args, **kwargs):
        rows = reports(*args, **kwargs)
        observed = rows[0]["interval"]
        observed["coupons_kopecks"] = "35"
        base = {
            "reference": "native-unallocated-1",
            "date": END,
            "currency": "RUB",
            "amount_kopecks": "5",
            "classification": "coupon",
        }
        observed["exceptions"] = [
            base,
            dict(base),
            {**base, "reference": "native-unallocated-2"},
            {**base, "reference": "foreign", "currency": "USD"},
            {**base, "reference": "cost", "classification": "fee"},
            {**base, "reference": "outside", "date": START},
        ]
        for analyses in kwargs["analyses"].values():
            analyses[ISIN].events = (
                InstrumentEvent(
                    event_key="attributed",
                    provider=PROVIDER,
                    native_source_account=kwargs["source_account"],
                    isin=ISIN,
                    kind="COUPON",
                    source_references=(),
                    event_date=END,
                    cash_legs=(CashLeg("income", END, 25, -25, (), "confirmed"),),
                ),
            )
        return rows

    monkeypatch.setattr(overall.source_investment_proofs, "read_report_summaries", with_unallocated)
    with db.session_factory() as session:
        value = overall.read_income(session, kind="coupon")
    assert value["summary"]["known_total"]["value"] == "70"
    assert value["instruments"][0]["amount"]["value"] == "50"
    unknown = [row for row in value["events"] if row["isin"] is None]
    assert len(unknown) == 4  # distinct same-date/amount operations, each account once
    assert all(row["name"] is None and row["amount"]["value"] == "5" for row in unknown)
    assert "known_account_income_not_fully_attributed" not in value["reason_codes"]


def test_real_synthetic_card_and_income_get_are_exact_read_only(db, monkeypatch):
    from test_returns_read_efficiency_service import _saved_investment

    _saved_investment(db, monkeypatch)
    app = FastAPI()
    app.include_router(router)

    def session():
        with db.session_factory() as value:
            yield value

    app.dependency_overrides[session_for_request] = session
    before = snapshot(db)
    with db.session_factory() as value:
        isin = overall.read_overall(value, include_instrument_details=True)["instruments"][0][
            "isin"
        ]
    with TestClient(app) as client:
        response = client.get("/api/returns/instrument-card", params={"isin": isin})
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert (
            response.json()["accounts"][0]["detail"]["analysis"]["contract_version"]
            == "instrument_return_v2"
        )
        assert client.get("/api/returns/income?kind=coupon").status_code == 200
        assert client.get("/api/returns/income?kind=forecast").status_code == 422
        assert client.get("/api/returns/income?kind=coupon&kind=dividend").status_code == 422
        assert client.get("/api/returns/instrument-card?isin=wrong").status_code == 422
        assert (
            client.get(f"/api/returns/instrument-card?isin={isin}&isin={isin}").status_code == 422
        )
    assert snapshot(db) == before


def test_clean_card_returns_no_sale_purchase_contributions_from_same_source(db):
    from test_source_instrument_returns_service import save

    save(
        db,
        stock=("0", "2", "0", "300"),
        bond=None,
        trades=(("RU000A000000", "1", "100", "0", "3"), ("RU000A000000", "1", "200", "0", "7")),
    )
    app = FastAPI()
    app.include_router(router)

    def session():
        with db.session_factory() as value:
            yield value

    app.dependency_overrides[session_for_request] = session
    before = snapshot(db)
    with TestClient(app) as client:
        response = client.get("/api/returns/instrument-card", params={"isin": "RU000A000000"})
        assert response.status_code == 200, response.text
        rows = response.json()["accounts"][0]["purchases"]
        assert rows is not None, response.json()["accounts"][0]["clean"]
        assert [row["cost_kopecks"] for row in rows] == ["10000", "20000"]
        assert [row["price_result_kopecks"] for row in rows] == ["5000", "-5000"]
    assert snapshot(db) == before


def test_position_comparison_api_matches_card_without_changing_export_projection(db):
    from test_source_instrument_returns_service import save

    from hermes_finance.services.clean_instrument_return import (
        clean_export_data,
        read_clean_overview,
    )

    isin = "RU000A000000"
    save(db, stock=("0", "1", "0", "120"), bond=None, trades=((isin, "1", "100", "0", "3"),))
    before = snapshot(db)
    app = FastAPI()
    app.include_router(router)

    def session():
        with db.session_factory() as value:
            yield value

    app.dependency_overrides[session_for_request] = session
    with TestClient(app) as client:
        response = client.get("/api/returns/overall")
        assert response.status_code == 200, response.text
        pair = next(row for row in response.json()["instruments"] if row["isin"] == isin)[
            "accounts"
        ][0]
        response = client.get("/api/returns/instrument-card", params={"isin": isin})
        assert response.status_code == 200, response.text
        card = response.json()
        clean = card["accounts"][0]["clean"]
    for field in ("simple_return", "xirr", "modified_dietz"):
        assert pair[field] == clean[field]
    assert clean["simple_return"]["value"] == "0.2"
    assert clean["realized_result"]["value"] == "0"
    assert clean["unrealized_result"]["value"] == "2000"
    assert pair["realized_result"]["value"] == "0"
    assert pair["is_open"] is True
    assert pair["current_value"]["value"] == "12000"
    assert card["aggregate"]["simple_return"]["value"] == "0.2"
    assert card["aggregate"]["pnl"]["value"] == "2000"
    assert clean["simple_return"]["invested_kopecks"] == "10000"
    assert clean["simple_return"]["start_date"] == "2030-04-15"
    assert clean["simple_return"]["end_date"] == "2030-04-30"
    assert clean["xirr"]["holding_days"] == 15
    assert clean["xirr"]["weighted_holding_days"] == "15.00"
    assert clean["xirr"]["eligibility_basis"] == "capital_weighted_holding_days"
    assert clean["xirr"]["value"] is None
    assert clean["xirr"]["reason_codes"] == ["short_holding"]
    assert clean["modified_dietz"]["for_position_comparison"] is False
    assert pair["rate"]["for_position_comparison"] is False
    assert card["summary"]["rate"]["for_position_comparison"] is False
    with db.session_factory() as value:
        exported = clean_export_data(read_clean_overview(value))
    old = exported["accounts"][0]["instruments"][0]
    assert "simple_return" not in old and "xirr" not in old
    assert set(old["modified_dietz"]) == {"value", "status", "reason_codes", "assumptions"}
    assert snapshot(db) == before


def test_clean_card_fifo_sale_matches_clean_instrument_result(db):
    from test_source_instrument_returns_service import save

    isin = "RU000A000000"

    def ordered(root):
        for index, row in enumerate(root.findall(".//{MyBroker}Details[@trade_no]"), 9):
            stamp = f"15.04.2030 {index}:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")

    save(
        db,
        stock=("0", "1", "0", "150"),
        bond=None,
        trades=(
            (isin, "1", "100", "0", "3"),
            (isin, "1", "200", "0", "7"),
            (isin, "-1", "180", "0", "9"),
        ),
        mutate=ordered,
    )
    with db.session_factory() as session:
        card = overall.read_clean_instrument_card(session, isin)
    account = card["accounts"][0]
    rows = account["purchases"]
    assert [row["price_result_kopecks"] for row in rows] == ["8000", "-5000"]
    assert [row["return_fraction"] for row in rows] == ["0.8", "-0.25"]
    assert sum(int(row["price_result_kopecks"]) for row in rows) == int(
        account["clean"]["valuation_and_trades"]["value"]
    )


def test_clean_card_closed_fifo_purchase_survives_missing_open_valuation(db):
    from test_source_instrument_returns_service import save

    isin = "RU000A000000"

    def ordered_without_valuation(root):
        for index, row in enumerate(root.findall(".//{MyBroker}Details[@trade_no]"), 9):
            stamp = f"15.04.2030 {index}:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
        root.find(".//{MyBroker}Details[@ISIN1]").attrib.pop("real_volume", None)

    save(
        db,
        stock=("0", "1", "0", "150"),
        bond=None,
        trades=(
            (isin, "1", "100", "0", "3"),
            (isin, "-1", "180", "0", "9"),
            (isin, "1", "200", "0", "7"),
        ),
        mutate=ordered_without_valuation,
    )
    with db.session_factory() as session:
        card = overall.read_clean_instrument_card(session, isin)
    account = card["accounts"][0]
    rows = account["purchases"]
    assert rows[0]["price_result_kopecks"] == "8000" and rows[0]["return_fraction"] == "0.8"
    assert rows[1]["cost_kopecks"] == "20000" and rows[1]["value_kopecks"] is None
    assert rows[1]["price_result_kopecks"] is None


def test_clean_card_blank_nkd_keeps_the_later_bond_purchase(db):
    from test_source_instrument_returns_service import save

    isin = "RU000A000001"

    def ordered_with_missing_buy_amount(root):
        rows = root.findall(".//{MyBroker}Details[@trade_no]")
        for index, (row, price) in enumerate(zip(rows, ("10", "18", "20"), strict=True), 9):
            stamp = f"15.04.2030 {index}:00:00"
            row.set("db_time", f"{stamp}\n{stamp}")
            row.set("Price", price)
        rows[-1].attrib.pop("summ_nkd", None)
        rows[-1].attrib.pop("nominal", None)

    save(
        db,
        stock=None,
        bond=("0", "1", "0", "150"),
        trades=(
            (isin, "1", "100", "0", "3"),
            (isin, "-1", "180", "0", "9"),
            (isin, "1", "200", "0", "7"),
        ),
        mutate=ordered_with_missing_buy_amount,
    )
    with db.session_factory() as session:
        card = overall.read_clean_instrument_card(session, isin)
    rows = card["accounts"][0]["purchases"]
    assert rows[0]["price_result_kopecks"] == "8000" and rows[0]["return_fraction"] == "0.8"
    assert rows[1]["cost_kopecks"] == "20000" and rows[1]["price_result_kopecks"] == "-5000"


def _manual_gold(db):
    from hermes_finance.services.owner_manual_gold_history import (
        apply_gold_history,
        preview_gold_history,
    )

    component_rows(db)
    with db.session_factory() as session:
        position = session.query(PositionSnapshot).order_by(PositionSnapshot.id).first()
        payload = {
            "account_id": position.account_id,
            "instrument_id": position.instrument_id,
            "expected_revision": 0,
            "covered_from": "2030-03-01",
            "covered_to": str(END),
            "complete": True,
            "zero_start": True,
            "current_quantity": "10",
            "current_quantity_date": str(END),
            "provenance_reference": "synthetic-only",
            "events": [
                {
                    "event_id": "synthetic-buy",
                    "event_date": "2030-03-03",
                    "side": "BUY",
                    "grams": "12",
                    "amount_basis": "actual",
                    "amount_rub": "120.00",
                    "fee_state": "known_zero",
                },
                {
                    "event_id": "synthetic-sale",
                    "event_date": "2030-04-04",
                    "side": "SELL",
                    "grams": "2",
                    "amount_basis": "actual",
                    "amount_rub": "40.00",
                    "fee_state": "known_zero",
                },
            ],
        }
        preview = preview_gold_history(session, payload)
        apply_gold_history(
            session,
            {
                **payload,
                "confirmation_digest": preview["confirmation_digest"],
                "request_id": "synthetic-root-gold",
            },
        )


def test_manual_gold_total_replaces_unrealized_addend_and_overview_has_no_hidden_history(db):
    _manual_gold(db)
    value = read(db)
    history = value.gold.histories[0]
    assert history.total_result.value == "4500"
    assert history.realized_result.value == "2000"
    assert history.unrealized_result.value == "2500"
    assert history.valuation_date == END
    gold = [row for row in value.mixed_result.components if row.category == "gold"]
    assert len(gold) == 1
    assert gold[0].authority == "owner_attestation"
    assert gold[0].amount.value == "4500"
    assert value.mixed_result.known_result.value == "4500"  # no +2500 snapshot or sale proceeds
    assert value.gold.snapshots[0].unrealized_result.value == "2500"  # explanation remains visible
    wire = str(history.model_dump())
    assert "synthetic-root-gold" not in wire and "synthetic-buy" not in wire
    assert "provenance_reference" not in wire


def test_manual_gold_missing_valuation_keeps_realized_but_no_total_or_numeric_fallback(db):
    _manual_gold(db)
    with db.session_factory() as session:
        session.query(PositionSnapshot).delete()
        session.commit()
    value = read(db)
    history = value.gold.histories[0]
    assert history.realized_result.value == "2000"
    assert history.total_result.value is history.unrealized_result.value is None
    assert "gold_saved_valuation_unavailable" not in history.realized_result.reason_codes
    assert "gold_saved_valuation_unavailable" in history.total_result.reason_codes
    assert history.valuation_date is None
    gold = [row for row in value.mixed_result.components if row.category == "gold"]
    assert len(gold) == 1 and not gold[0].included
    assert gold[0].amount.value is None


def test_draft_only_gold_has_exact_metadata_target_without_promoting_financial_values(db):
    component_rows(db)
    with db.session_factory() as session:
        closed = session.query(PositionSnapshot).order_by(PositionSnapshot.id).first()
        ids = (closed.account_id, closed.instrument_id)
        session.delete(closed)  # synthetic missing old observation; only DRAFT remains
        session.commit()
    value = read(db)
    assert value.gold.snapshots == value.gold.histories == []
    assert [(t.account_id, t.instrument_id) for t in value.gold.targets] == [ids]
    assert value.gold.period_result.value is None
    assert not any(row.category == "gold" for row in value.mixed_result.components)
    assert set(value.gold.targets[0].model_dump()) == {"account_id", "instrument_id", "label"}


def test_gold_target_requires_exact_gold_rub_catalogue_type(db):
    component_rows(db)
    with db.session_factory() as session:
        instrument = session.query(Instrument).one()
        instrument.currency = "USD"
        session.commit()
    assert read(db).gold.targets == []


def test_owner_coupon_total_uses_native_accounts_once_not_instrument_or_monthly_explanations(
    db, monkeypatch
):
    calls = source_fixture(monkeypatch)
    value = read(db)
    coupon = value.coupon_income
    assert coupon.known_total.value == "50"
    assert calls == ["native-a", "native-b"]
    assert coupon.selected_accounts == coupon.included_accounts == 2
    assert coupon.partial and "coupon_account_history_periods_differ" in coupon.reason_codes
    assert value.mixed_result.known_result.value == "50"
    assert all(pair.canonical_account_id is None for pair in value.instruments[0].accounts)


def test_known_coupon_income_is_independent_of_unavailable_account_pnl_and_valuation(
    db, monkeypatch
):
    source_fixture(monkeypatch)
    original = overall.source_investment_proofs.read_report_summaries

    def without_account_result(*args, **kwargs):
        rows = original(*args, **kwargs)
        for row in rows:
            row["interval"]["pnl"]["value"] = None
            row["interval"]["modified_dietz"]["value"] = None
        return rows

    monkeypatch.setattr(
        overall.source_investment_proofs, "read_report_summaries", without_account_result
    )
    value = read(db)
    assert value.mixed_result.known_result.value is None
    assert value.coupon_income.known_total.value == "50"
    assert value.coupon_income.included_accounts == 2


def test_stale_coupon_account_does_not_revive_old_value_or_hide_known_sibling(db, monkeypatch):
    source_fixture(monkeypatch, stale_second=True)
    coupon = read(db).coupon_income
    assert coupon.known_total.value == "25"
    assert (coupon.selected_accounts, coupon.included_accounts) == (2, 1)
    assert coupon.accounts[1].amount.value is None
    assert coupon.accounts[1].exclusion_reason == "current_coupon_history_unavailable"


@pytest.mark.parametrize(
    ("amount", "expected", "included"),
    [("0", "0", 2), (None, None, 0), ("900719925474099301", "1801439850948198602", 2)],
)
def test_coupon_zero_unknown_and_large_integer_amounts_keep_distinct_meanings(
    db, monkeypatch, amount, expected, included
):
    source_fixture(monkeypatch)
    original = overall.source_investment_proofs.read_report_summaries

    def observed(*args, **kwargs):
        rows = original(*args, **kwargs)
        for row in rows:
            row["interval"]["coupons_kopecks"] = amount
        return rows

    monkeypatch.setattr(overall.source_investment_proofs, "read_report_summaries", observed)
    coupon = read(db).coupon_income
    assert coupon.known_total.value == expected
    assert coupon.included_accounts == included


@pytest.mark.parametrize("conflict", [False, True])
def test_navigation_and_coupon_conflicts_use_exact_accepted_identity_not_labels(
    db, monkeypatch, conflict
):
    source_fixture(monkeypatch)
    identity_mappings(db, shared=conflict)
    value = read(db)
    ids = [pair.canonical_account_id for pair in value.instruments[0].accounts]
    if conflict:
        assert ids == [None, None]
        assert value.coupon_income.known_total.value is None
        assert all(
            row.amount.value == "25" and not row.included for row in value.coupon_income.accounts
        )
        assert all(
            row.exclusion_reason == "source_account_identity_mapping_conflict"
            for row in value.coupon_income.accounts
        )
    else:
        assert ids == [1, 2]
        assert value.coupon_income.known_total.value == "50"


def _snapshot_checker():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "returns_snapshot_check", Path(__file__).parents[1] / "scripts/returns_snapshot_check.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_check_refuses_repository_output(db):
    checker = _snapshot_checker()
    with pytest.raises(ValueError, match="outside"):
        checker.validate_paths(db.database_path, checker.REPOSITORY / "private-output")


def test_snapshot_check_source_unchanged_and_comparison(db, tmp_path, monkeypatch, capsys):
    import hashlib
    import json

    from test_source_instrument_returns_service import save

    checker = _snapshot_checker()
    save(
        db,
        stock=("0", "2", "0", "300"),
        bond=None,
        trades=(("RU000A000000", "1", "100", "0", "3"), ("RU000A000000", "1", "200", "0", "7")),
    )
    # Synthetic artifacts stay in pytest's repository-local basetemp; production
    # validation is tested separately above, with an isolated synthetic boundary here.
    monkeypatch.setattr(checker, "REPOSITORY", tmp_path / "synthetic-repository")
    path = db.database_path
    before = (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).digest())
    result = checker.run(path, tmp_path / "first")
    assert result["totals"]["purchases_with_result"] == 2
    assert result["totals"]["rows_with_full_result"] == 1
    assert result["totals"]["open_positions_with_full_result"] == 1
    assert before == (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).digest())
    assert not list((tmp_path / "first").glob("*.sqlite"))
    console = capsys.readouterr().out
    assert "RU000A" not in console
    assert "5000" not in console
    previous = json.loads(json.dumps(result))
    previous["rows"][0]["full_result"] = False
    previous["rows"][0]["purchases_with_result"] = 0
    previous_path = tmp_path / "previous.json"
    previous_path.write_text(json.dumps(previous), encoding="utf-8")
    checker.run(path, tmp_path / "second", compare=previous_path, keep_copy=True)
    console = capsys.readouterr().out
    assert "full_result: False -> True" in console
    assert "purchases_with_result: 0 -> 2" in console
    assert "rows_with_full_result" not in console
    assert len(list((tmp_path / "second").glob("*.sqlite"))) == 1
    assert checker.differences(result, result) == []
    assert "True -> False" in checker.differences(result, previous)[0]


def test_home_summary_matches_full_projection_without_rates_or_position_decomposition(
    db, monkeypatch
):
    from test_returns_view_service import basket_source

    from hermes_finance.services import position_results
    from hermes_finance.services.returns_home import read_home_summary, summarize_home

    basket_source(db)
    component_rows(db)
    with db.session_factory() as session:
        full = overall.read_clean_overall(session, include_instrument_details=True)
    expected = summarize_home(full)

    def unnecessary(*args, **kwargs):
        raise AssertionError("Home must not build position decomposition or aggregate rates")

    monkeypatch.setattr(position_results, "position_results", unnecessary)
    monkeypatch.setattr(position_results, "aggregate_positions", unnecessary)
    with db.session_factory() as session:
        assert read_home_summary(session) == expected


def test_home_summary_counts_unknown_zero_and_ranks_only_common_periods():
    from hermes_finance.services.returns_home import summarize_home

    def metric(value, reasons=()):
        return {
            "value": value,
            "reason_codes": list(reasons),
            "estimate": False,
            "unit": "kopecks",
            "method": "clean_instrument_return_v1",
        }

    data = {"mixed_result": {"components": []}, "instruments": []}
    values = ["9007199254740993", "20", "15", "10", "-1", "-2", "-3", "-4", "0", None, "99"]
    for i, value in enumerate(values):
        data["instruments"].append(
            {
                "isin": str(i),
                "name": "Synthetic instrument",
                "accounts": [
                    {
                        "scope": "source:SYNTH",
                        "label": "Synthetic",
                        "account_link": None,
                        "native_period": True,
                        "details_loaded": True,
                        "period": {"start": START, "end": END},
                        "pnl": metric(value, ["clean_partial_result"] if i == 10 else []),
                    }
                ],
            }
        )
    result = summarize_home(data)
    assert (result["positive"], result["negative"], result["unknown"], result["unchanged"]) == (
        4,
        4,
        2,
        1,
    )
    assert [row["pnl"]["value"] for row in result["ranked"]] == [
        "9007199254740993",
        "20",
        "15",
        "-4",
        "-3",
        "-2",
    ]
    assert result["result"]["amount"]["value"] is None
    data["instruments"][0]["accounts"][0]["period"] = {"start": END, "end": date(2030, 5, 31)}
    result = summarize_home(data)
    assert result["mixed_periods"] and result["ranked"] == []
