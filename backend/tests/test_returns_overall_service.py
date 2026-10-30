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
        "_selected_sources",
        lambda session, account: (
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


def test_card_combines_supported_accounts_keeps_local_gaps_and_no_combined_rate(db, monkeypatch):
    source_fixture(monkeypatch, stale_second=True)
    view = read(db).model_dump(mode="python")
    calls = []

    def detail(session, *, scope, start, end, isin):
        calls.append(scope)

        def metric(value):
            return SimpleNamespace(value=value, status="supported", reason_codes=())

        return {
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
            )
        }

    monkeypatch.setattr(overall.returns_view, "read_detail", detail)
    with db.session_factory() as session:
        value = overall.read_instrument_card(session, ISIN, overview=view)
    assert calls == ["source:native-a"]
    assert value["summary"]["pnl"]["value"] == "100"
    assert value["summary"]["quantity"]["value"] == "0"  # sold is retained
    assert value["summary"]["rate"]["value"] is None
    assert value["summary"]["costs"]["value"] == "10"
    assert value["summary"]["valuation_and_trades"]["value"] == "90"
    assert "instrument_accounts_missing_or_excluded" in value["summary"]["pnl"]["reason_codes"]
    assert value["accounts"][1]["detail"] is None


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
