"""Synthetic saved statements -> existing provider -> conservative reconciliation."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from t_invest_mapping_fixtures import accept_t_invest_mapping
from test_source_instrument_returns_service import db as db
from test_source_instrument_returns_service import save
from test_source_monthly_returns_service import snapshot
from test_statement_import_mybroker import ACCOUNT, ISIN

from hermes_finance.main import create_app
from hermes_finance.market_data.dto import T_INVEST_PROVIDER
from hermes_finance.market_data.payout import PayoutEvent, PayoutEventKind, PayoutEventStatus
from hermes_finance.market_data.payout_protocol import PayoutFetchResult
from hermes_finance.persistence import PositionSnapshot
from hermes_finance.services.instruments import create_instrument

UID = "44444444-4444-4444-4444-444444444444"
PATH = "/api/source-returns/payout-preview"
PAYLOAD = {"source_account": ACCOUNT, "isin": ISIN, "as_of": "2030-04-30"}
BASES = "/api/source-returns/quantity-bases"


def quantity_bases(client, **patch):
    return client.get(
        BASES,
        params={"source_account": ACCOUNT, "isin": ISIN, "on_or_before": "2030-10-31", **patch},
    )


def test_quantity_discovery_is_local_read_only_and_does_not_invent_october_eod(db):
    client, provider = environment(db, quantity="2.500000000000000001")
    save(db, month=9, stock=("3", "3", "300", "300"), bond=None, trades=())
    save(db, month=11, stock=("4", "4", "400", "400"), bond=None, trades=())
    before = snapshot(db)
    writes = []

    def inspect(conn, cursor, sql, *args):
        if sql.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}:
            writes.append(sql)

    event.listen(db.engine, "before_cursor_execute", inspect)
    try:
        response = quantity_bases(client)
        assert response.status_code == 200, response.text
        data = response.json()
        assert response.headers["cache-control"] == "no-store"
        assert data["financial_authority"] == "none"
        assert data["native_source_account"] == ACCOUNT
        assert [(b["as_of"], b["quantity"]) for b in data["bases"]] == [
            ("2030-09-30", "3"),
            ("2030-04-30", "2.500000000000000001"),
        ]
        assert all(b["quantity_references"] for b in data["bases"])
        assert quantity_bases(client).json() == data
        assert snapshot(db) == before and writes == []
        assert provider.requests == []
        october = client.post(PATH, json={**PAYLOAD, "as_of": "2030-10-31"}).json()
        assert october["quantity"] is None and october["rows"] == []
        assert provider.requests == []
    finally:
        event.remove(db.engine, "before_cursor_execute", inspect)


def test_quantity_discovery_keeps_scope_conflicts_mapping_and_zero(db):
    client, provider = environment(db, quantity="0", mapping=False)
    data = quantity_bases(client).json()
    assert data["bases"][0]["quantity"] == "0"
    assert "exact_t_invest_mapping_required" in data["bases"][0]["reason_codes"]
    assert quantity_bases(client, source_account="other-native").json()["bases"] == []
    assert quantity_bases(client, isin="RU000A000001").json()["bases"] == []
    save(db, stock=("1", "1", "100", "100"), bond=None, trades=(), marker="conflict")
    basis = quantity_bases(client).json()["bases"][0]
    assert basis["quantity"] is None
    assert "overlapping_quantity_conflict" in basis["reason_codes"]
    assert provider.requests == []


def test_quantity_discovery_bonds_reuses_guarded_preview_quantity(db):
    from test_source_instrument_returns_service import BOND

    save(db, stock=None, bond=("2.5", "2.5", "2000", "2000"), trades=())
    with db.session_factory() as session:
        bond = create_instrument(session, name="Synthetic bond", instrument_type="bond", isin=BOND)
        accept_t_invest_mapping(session, bond.id, UID, isin=BOND)
    app = create_app(database=db)
    app.state.payout_provider = Provider()
    client = TestClient(app)
    basis = quantity_bases(client, isin=BOND).json()["bases"][0]
    assert app.state.payout_provider.requests == []
    preview = client.post(PATH, json={**PAYLOAD, "isin": BOND}).json()
    assert basis["quantity"] == preview["quantity"] == "2.5"
    assert basis["reason_codes"] == preview["reason_codes"]
    assert len(app.state.payout_provider.requests) == 1


def payout(day=date(2030, 5, 20), key="dividend:1", amount="1.2345"):
    return PayoutEvent(
        provider=T_INVEST_PROVIDER,
        instrument_uid=UID,
        event_kind=PayoutEventKind.DIVIDEND,
        identity_key=key,
        status=PayoutEventStatus.OK,
        payment_date=day,
        per_unit_amount=Decimal(amount),
        currency="RUB",
        source_method="GetDividends",
        provider_filter_basis="record_date",
        provider_filter_date=day,
    )


class Provider:
    def __init__(self, events=None, callback=None):
        self.events = (payout(),) if events is None else events
        self.requests = []
        self.callback = callback

    def fetch_payouts(self, request):
        self.requests.append(request)
        if self.callback:
            self.callback()
        return PayoutFetchResult(provider=T_INVEST_PROVIDER, instrument_uid=UID, events=self.events)


def environment(db, *, quantity="10", extra=(), mapping=True, mutate=None, provider=None):
    save(
        db,
        stock=(quantity, quantity, "1000", "1000"),
        bond=None,
        trades=(),
        extra=extra,
        mutate=mutate,
    )
    with db.session_factory() as session:
        stock = create_instrument(
            session, name="Synthetic stock", instrument_type="stock", isin=ISIN
        )
        if mapping:
            accept_t_invest_mapping(session, stock.id, UID, isin=ISIN)
    app = create_app(database=db)
    app.state.payout_provider = provider or Provider()
    return TestClient(app), app.state.payout_provider


def test_saved_source_quantity_no_finance_authority_replay_reload_and_no_dml(db):
    client, provider = environment(db)
    before = snapshot(db)
    writes = []

    def inspect(conn, cursor, sql, *args):
        if sql.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}:
            writes.append(sql)

    event.listen(db.engine, "before_cursor_execute", inspect)
    try:
        result = client.post(PATH, json=PAYLOAD)
        assert result.status_code == 200, result.text
        data = result.json()
        assert data["quantity"] == "10"
        assert data["financial_authority"] == "none"
        assert data["authority"] == "provisional"
        assert data["native_source_account"] == ACCOUNT
        assert data["reason_codes"] == []
        assert data["rows"][0]["announced_amount_kopecks"] == "1235"
        assert data["rows"][0]["countable_future"]
        assert not data["rows"][0]["personal_tax_known"]
        assert data["source_references"][0]["original_digest"]
        assert data["quantity_references"]
        assert result.headers["cache-control"] == "no-store"
        assert client.post(PATH, json=PAYLOAD).json() == data
        reloaded = create_app(database=db)
        reloaded.state.payout_provider = provider
        assert TestClient(reloaded).post(PATH, json=PAYLOAD).json() == data
        assert snapshot(db) == before
        assert writes == []
        with db.session_factory() as session:
            assert list(session.scalars(select(PositionSnapshot))) == []
        assert provider.requests[0].instrument_uid == UID
        assert provider.requests[0].calendar_to == date(2031, 4, 29)
    finally:
        event.remove(db.engine, "before_cursor_execute", inspect)


@pytest.mark.parametrize("quantity", ["0", "2.5"])
def test_zero_and_fractional_quantity_are_not_unknown(db, quantity):
    client, _ = environment(db, quantity=quantity)
    data = client.post(PATH, json=PAYLOAD).json()
    assert Decimal(data["quantity"]) == Decimal(quantity)
    assert data["rows"][0]["announced_amount_kopecks"] == ("0" if quantity == "0" else "309")


@pytest.mark.parametrize(
    "payload",
    [
        {**PAYLOAD, "source_account": "other-native-account"},
        {**PAYLOAD, "as_of": "2030-05-31"},
        {**PAYLOAD, "isin": "RU000A000001"},
    ],
)
def test_missing_scope_date_or_security_never_borrows_quantity(db, payload):
    client, provider = environment(db)
    data = client.post(PATH, json=payload).json()
    assert data["quantity"] is None
    assert data["rows"] == [] and provider.requests == []
    assert data["reason_codes"]


def test_no_mapping_does_not_call_provider_or_create_registry(db):
    client, provider = environment(db, mapping=False)
    data = client.post(PATH, json=PAYLOAD).json()
    assert data["quantity"] == "10"
    assert "exact_t_invest_mapping_required" in data["reason_codes"]
    assert data["rows"] == [] and provider.requests == []


def test_overlapping_conflicting_endpoint_is_unknown_not_sum_or_latest(db):
    client, provider = environment(db)
    save(db, stock=("11", "11", "1000", "1000"), bond=None, trades=(), marker="conflict")
    data = client.post(PATH, json=PAYLOAD).json()
    assert data["quantity"] is None
    assert "overlapping_quantity_conflict" in data["reason_codes"]
    assert not provider.requests


def test_actual_dividend_is_single_source_event_and_not_second_future_payment(db):
    provider = Provider(events=(payout(date(2030, 4, 15)), payout(key="dividend:2")))
    client, _ = environment(db, extra=(("Дивиденды", ISIN, "100"),), provider=provider)
    data = client.post(PATH, json=PAYLOAD).json()
    assert len(data["actuals"]) == 1
    assert data["actuals"][0]["net_payout_kopecks"] == "10000"
    assert data["rows"][0]["status"] == "possible_paid"
    assert data["rows"][0]["actual_event_keys"] == [data["actuals"][0]["event_key"]]
    assert not data["rows"][0]["countable_future"]
    # Assumed income cannot settle a provider identity or assert gross=net.
    assert data["rows"][1]["status"] == "reconciliation_required"
    assert not data["rows"][1]["countable_future"]


def test_duplicate_provider_identity_cannot_count_twice(db):
    client, _ = environment(db, provider=Provider(events=(payout(), payout(amount="2"))))
    data = client.post(PATH, json=PAYLOAD).json()
    assert all(r["status"] == "ambiguous_identity" for r in data["rows"])
    assert not any(r["countable_future"] for r in data["rows"])


def test_context_changed_during_provider_io_returns_409(db):
    client, _ = environment(
        db,
        provider=Provider(
            callback=lambda: save(
                db, stock=("11", "11", "1000", "1000"), bond=None, trades=(), marker="during-fetch"
            )
        ),
    )
    response = client.post(PATH, json=PAYLOAD)
    assert response.status_code == 409, response.text


def test_provider_failure_is_sanitized_and_unknown_not_empty_success(db):
    class Failed(Provider):
        def fetch_payouts(self, request):
            raise RuntimeError("TOKEN=private")

    client, _ = environment(db, provider=Failed())
    response = client.post(PATH, json=PAYLOAD)
    assert response.status_code == 200
    assert response.json()["failures"] == ["error"]
    assert response.json()["rows"] == []
    assert "private" not in response.text


def test_overlapping_same_statement_facts_are_not_two_quantities_or_two_payouts(db):
    extra = (("Дивиденды", ISIN, "100"),)
    client, _ = environment(db, extra=extra)
    save(
        db, stock=("10", "10", "1000", "1000"), bond=None, trades=(), extra=extra, marker="overlap"
    )
    data = client.post(PATH, json=PAYLOAD).json()
    assert data["quantity"] == "10"
    assert len(data["quantity_references"]) == 2
    assert len(data["actuals"]) == 1
    assert len(data["actuals"][0]["source_references"]) == 2


def test_unsettled_endpoint_does_not_supply_a_quantity(db):
    from hermes_finance.statement_import.mybroker import NS

    def unsettled(root):
        root.find(".//m:Details[@ISIN1]", NS).set("forward_rest", "11")

    client, provider = environment(db, mutate=unsettled)
    data = client.post(PATH, json=PAYLOAD).json()
    assert data["quantity"] is None and "endpoint_unsettled" in data["reason_codes"]
    assert not provider.requests


def test_future_horizon_and_unknown_amount_never_count(db):
    from dataclasses import replace

    events = (
        payout(date(2031, 5, 1)),
        replace(payout(key="unknown"), status=PayoutEventStatus.TENTATIVE, per_unit_amount=None),
    )
    client, _ = environment(db, provider=Provider(events=events))
    data = client.post(PATH, json=PAYLOAD).json()
    assert [r["status"] for r in data["rows"]] == ["outside_horizon", "tentative"]
    assert data["rows"][1]["announced_amount_kopecks"] is None
    assert not any(r["countable_future"] for r in data["rows"])


def test_bond_uses_quantity_without_inventing_dirty_value_or_tax(db):
    from test_source_instrument_returns_service import BOND

    save(db, stock=None, bond=("2", "2", "2000", "2000"), trades=())
    with db.session_factory() as session:
        bond = create_instrument(session, name="Synthetic bond", instrument_type="bond", isin=BOND)
        accept_t_invest_mapping(session, bond.id, UID, isin=BOND)
    from dataclasses import replace

    app = create_app(database=db)
    app.state.payout_provider = Provider(
        events=(replace(payout(), event_kind=PayoutEventKind.COUPON),)
    )
    data = TestClient(app).post(PATH, json={**PAYLOAD, "isin": BOND}).json()
    assert data["quantity"] == "2"
    assert data["rows"][0]["announced_amount_kopecks"] == "247"
    assert data["rows"][0]["personal_tax_known"] is False
    assert data["financial_authority"] == "none"


def test_later_saved_actual_suppresses_future_for_older_quantity_date(db):
    client, _ = environment(db, provider=Provider(events=(payout(date(2030, 5, 15)),)))
    later = save(
        db,
        5,
        stock=("10", "10", "1000", "1000"),
        bond=None,
        trades=(),
        extra=(("Дивиденды", ISIN, "100"),),
    )
    data = client.post(PATH, json=PAYLOAD).json()
    assert data["as_of"] == "2030-04-30" and data["quantity"] == "10"
    assert data["actuals"][0]["event_date"] == "2030-05-15"
    assert any(s["intake_id"] == later for s in data["source_references"])
    assert data["rows"][0]["status"] == "possible_paid"
    assert not data["rows"][0]["countable_future"]


def test_minor_units_above_js_safe_integer_are_exact_strings(db):
    client, _ = environment(db, provider=Provider(events=(payout(amount="9007199254740.993"),)))
    data = client.post(PATH, json=PAYLOAD).json()
    assert data["rows"][0]["announced_amount_kopecks"] == "9007199254740993"
    assert data["rows"][0]["countable_future"]


def test_actual_minor_units_also_use_exact_transport(db):
    client, _ = environment(db, extra=(("Дивиденды", ISIN, "90071992547409.93"),))
    data = client.post(PATH, json=PAYLOAD).json()
    assert data["actuals"][0]["net_payout_kopecks"] == "9007199254740993"
    assert data["actuals"][0]["gross_payout_kopecks"] is None
    assert data["actuals"][0]["withheld_tax_kopecks"] is None
