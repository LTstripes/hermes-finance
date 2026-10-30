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
        value = Overall.model_validate(overall.read_overall(session))
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

    monkeypatch.setattr(overall.source_investment_proofs, "read_reports", reports)
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
