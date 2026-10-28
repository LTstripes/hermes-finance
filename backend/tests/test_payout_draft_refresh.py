"""Synthetic XML -> accepted DRAFT -> explicit, durable provider forecasts."""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_statement_import_mybroker import ACCOUNT, FILENAME, ISIN
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import (
    _all_month_tables,
    _broker_month_apply,
    _broker_month_preview,
    _broker_month_setup,
    broker_month_xml,
)
from test_statement_import_payout_reconciliation import settlement as settlement

from hermes_finance.domain import InstrumentType
from hermes_finance.main import create_app
from hermes_finance.market_data.dto import (
    DiscoverCandidate,
    DiscoverResult,
    MarketIdentity,
    QuoteStatus,
)
from hermes_finance.market_data.payout import PayoutEvent, PayoutEventKind, PayoutEventStatus
from hermes_finance.market_data.payout_protocol import PayoutFetchResult
from hermes_finance.persistence import (
    AppliedPayoutRevision,
    AppliedProviderPayout,
    PositionSnapshot,
)

UID = "44444444-4444-4444-4444-444444444444"


class Provider:
    def __init__(self):
        self.discovery = []
        self.requests = []
        self.amount = Decimal("2.50")
        self.payment = date(2030, 2, 15)
        self.on_fetch = None
        self.fail = False
        self.ambiguous = False
        self.events = None

    def discover_candidates(self, **kwargs):
        self.discovery.append(kwargs)
        candidate = DiscoverCandidate(
            identity=MarketIdentity("t_invest", UID, None, ISIN),
            instrument_kind=InstrumentType.STOCK,
            verified_isin=ISIN,
            currency="RUB",
        )
        return DiscoverResult(
            QuoteStatus.AMBIGUOUS if self.ambiguous else QuoteStatus.OK,
            candidates=(candidate, candidate) if self.ambiguous else (candidate,),
        )

    def fetch_payouts(self, request):
        self.requests.append(request)
        if self.on_fetch:
            self.on_fetch(len(self.requests))
        if self.fail:
            raise RuntimeError("TOKEN=must-not-be-returned")
        event = PayoutEvent(
            provider="t_invest",
            instrument_uid=request.instrument_uid,
            event_kind=PayoutEventKind.DIVIDEND,
            identity_key="id:synthetic-event",
            status=PayoutEventStatus.OK,
            payment_date=self.payment,
            per_unit_amount=self.amount,
            currency="RUB",
            source_method="GetDividends",
            provider_filter_basis="record_date",
            provider_filter_date=date(2030, 2, 1),
        )
        return PayoutFetchResult(
            provider="t_invest",
            instrument_uid=request.instrument_uid,
            events=(event,) if self.events is None else self.events(event),
        )


def setup(database, provider, xml=None):
    scope = _broker_month_setup(database)
    client = TestClient(
        create_app(database=database, market_data_provider=provider, payout_provider=provider)
    )
    xml = broker_month_xml() if xml is None else xml
    intake = client.post(
        "/api/broker-months/intakes",
        files={"file": (FILENAME, xml, "application/xml")},
        data={"intent": json.dumps({"request_id": "source-save"})},
    )
    assert intake.status_code == 200, intake.text
    assert client.get(f"/api/broker-months/intakes/{intake.json()['intake_id']}").status_code == 200
    assert (
        client.get(f"/api/months/{scope['reporting_month_id']}/draft-payouts").json()[
            "eligible_positions"
        ]
        == 0
    )
    preview = _broker_month_preview(client, scope, xml)
    assert preview["can_apply"], preview
    ack = _broker_month_apply(client, scope, preview, xml)
    assert ack.status_code == 200, ack.text
    assert client.get("/api/broker-months/synthetic-batch").json()["bookkeeping_ready"]
    return client, scope["reporting_month_id"]


def refresh(client, month):
    context = client.get(f"/api/months/{month}/draft-payouts")
    assert context.status_code == 200, context.text
    response = client.post(
        f"/api/months/{month}/draft-payouts/refresh",
        json={"context_digest": context.json()["context_digest"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def calendar(client, month):
    response = client.get(f"/api/payouts/calendar?month_id={month}&forecast_version=v1")
    assert response.status_code == 200, response.text
    return [i for m in response.json() for i in m["items"]]


def test_draft_refresh_discovery_revision_replay_and_get_only_reload(database):
    provider = Provider()
    client, month = setup(database, provider)
    before = _all_month_tables(database)
    assert refresh(client, month)["summary"]["updated"] == 1
    assert provider.discovery[0] == {"isin": ISIN, "instrument_kind": InstrumentType.STOCK}
    assert provider.discovery[1] == {"provider_instrument_id": UID, "isin": ISIN}
    assert [(r.calendar_from, r.calendar_to) for r in provider.requests] == [
        (date(2030, 1, 31), date(2031, 1, 30))
    ] * 2
    rows = calendar(client, month)
    assert rows[0]["expected_net_amount"] == {"amount": "25.00", "currency": "RUB"}
    assert refresh(client, month)["summary"]["unchanged"] == 1
    provider.amount = Decimal("3.00")
    provider.payment = date(2030, 2, 16)
    assert refresh(client, month)["summary"]["updated"] == 1
    with database.session_factory() as session:
        revisions = list(
            session.scalars(select(AppliedPayoutRevision).order_by(AppliedPayoutRevision.id))
        )
        assert [r.total_amount_kopecks for r in revisions] == [2500, 3000]
        assert len(list(session.scalars(select(AppliedProviderPayout)))) == 1
    calls = len(provider.requests), len(provider.discovery)
    saved = _all_month_tables(database)
    for _ in range(2):
        assert client.get(f"/api/months/{month}/draft-payouts").status_code == 200
        assert calendar(client, month)[0]["expected_date"] == "2030-02-16"
    assert calls == (len(provider.requests), len(provider.discovery))
    assert _all_month_tables(database) == saved
    for table, content in before.items():
        if table not in {
            "instrument_market_mappings",
            "applied_provider_payouts",
            "applied_payout_revisions",
        }:
            assert saved[table] == content, table


@pytest.mark.parametrize("when", [1, 2])
def test_source_quantity_change_during_fetch_blocks_write(database, when):
    provider = Provider()
    client, month = setup(database, provider)

    def change(call):
        if call == when:
            with database.session_factory() as session:
                position = session.scalar(select(PositionSnapshot))
                position.quantity = Decimal("12")
                session.commit()

    provider.on_fetch = change
    result = refresh(client, month)
    assert result["summary"]["updated"] == 0
    assert result["items"][0]["reason_codes"] in (["draft_changed"], ["preview_changed"])
    assert calendar(client, month) == []


@pytest.mark.parametrize("case", ["ambiguous", "failure", "duplicate", "empty"])
def test_provider_exceptions_are_bounded_and_never_write_actuals(database, case):
    provider = Provider()
    client, month = setup(database, provider)
    provider.ambiguous = case == "ambiguous"
    provider.fail = case == "failure"
    if case == "duplicate":
        provider.events = lambda event: (event, replace(event, per_unit_amount=Decimal("9")))
    if case == "empty":
        provider.events = lambda event: ()
    result = refresh(client, month)
    assert result["summary"]["updated"] == 0
    assert "TOKEN" not in str(result)
    assert calendar(client, month) == []
    assert not _all_month_tables(database)["investment_cash_flows"]


def second_account(database, client, month):
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.broker_identity_mappings import confirm_mapping

    with database.session_factory() as session:
        account = create_account(session, name="Synthetic IIS", account_type="iis")
        account_id = account.id
        for alias in ("7654321", "7654321-000"):
            confirm_mapping(
                session,
                provider="alfa_mybroker",
                subject_kind="account",
                provider_identity=alias,
                hermes_target_id=account_id,
            )
    # Identical ISIN, native trade ID and amounts in a different account; opening
    # and closing quantity change together, preserving the exact inventory control.
    xml = (
        broker_month_xml()
        .decode()
        .replace(ACCOUNT, "7654321-000")
        .replace('income_rest="8"', 'income_rest="18"')
        .replace('real_rest="10"', 'real_rest="20"')
        .replace('forward_rest="10"', 'forward_rest="20"')
        .encode()
    )
    filename = FILENAME.replace("1234567", "7654321")
    scope = {"reporting_month_id": month, "account_id": account_id}
    preview = _broker_month_preview(client, scope, xml, filename=filename)
    response = _broker_month_apply(
        client, scope, preview, xml, request_id="second-account", filename=filename
    )
    assert response.status_code == 200, response.text
    assert response.json()["bookkeeping_ready"], response.json()
    return account_id


def test_two_accounts_keep_quantity_identity_partial_failure_and_next_click(database):
    provider = Provider()
    client, month = setup(database, provider)
    account_b = second_account(database, client, month)

    def fail_second(call):
        if call == 3:
            raise RuntimeError("synthetic interrupted second group")

    provider.on_fetch = fail_second
    result = refresh(client, month)
    assert result["summary"] == {
        "updated": 1,
        "unchanged": 0,
        "unsupported": 0,
        "needs_review": 0,
        "error": 1,
    }
    assert len(calendar(client, month)) == 1
    provider.on_fetch = None
    assert refresh(client, month)["summary"]["updated"] == 1
    rows = calendar(client, month)
    assert {(r["account_id"], r["expected_net_amount"]["amount"]) for r in rows} == {
        (1, "25.00"),
        (account_b, "50.00"),
    }
    assert refresh(client, month)["summary"]["unchanged"] == 2
    with database.session_factory() as session:
        assert len(list(session.scalars(select(AppliedPayoutRevision)))) == 2


def test_lost_ack_fresh_get_then_new_click_is_idempotent(database, monkeypatch):
    from hermes_finance.services import draft_payouts

    provider = Provider()
    client, month = setup(database, provider)
    original = draft_payouts.refresh

    def lose_ack(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic lost HTTP ACK after commits")

    monkeypatch.setattr(draft_payouts, "refresh", lose_ack)
    context = client.get(f"/api/months/{month}/draft-payouts").json()
    with pytest.raises(RuntimeError, match="lost HTTP ACK"):
        client.post(
            f"/api/months/{month}/draft-payouts/refresh",
            json={"context_digest": context["context_digest"]},
        )
    calls = len(provider.requests)
    assert len(calendar(client, month)) == 1
    assert len(provider.requests) == calls
    monkeypatch.setattr(draft_payouts, "refresh", original)
    assert refresh(client, month)["summary"]["unchanged"] == 1


@pytest.mark.parametrize("when", [1, 2])
def test_provider_mapping_aba_during_network_rejects_old_context(database, when):
    from hermes_finance.services.instrument_mappings import (
        clear_instrument_mapping_exclusion,
        exclude_instrument_mapping,
    )

    provider = Provider()
    client, month = setup(database, provider)

    def aba(call):
        if call == when:
            with database.session_factory() as session:
                exclude_instrument_mapping(session, 1)
                clear_instrument_mapping_exclusion(session, 1)

    provider.on_fetch = aba
    assert refresh(client, month)["summary"]["updated"] == 0
    assert calendar(client, month) == []


def test_closed_stale_get_and_manual_duplicate_never_coerce_eligibility(database):
    from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
    from hermes_finance.services.reporting_months import close_reporting_month

    provider = Provider()
    client, month = setup(database, provider)
    context = client.get(f"/api/months/{month}/draft-payouts").json()
    with database.session_factory() as session:
        create_expected_cash_flow(
            session,
            reporting_month_id=month,
            account_id=1,
            instrument_id=1,
            flow_type="dividend",
            expected_date=provider.payment,
            gross_amount="25.00",
            expected_tax_amount="0",
            expected_net_amount="25.00",
            source="synthetic",
            source_as_of_date=date(2030, 1, 31),
            forecast_version="v1",
        )
    stale = client.post(
        f"/api/months/{month}/draft-payouts/refresh",
        json={"context_digest": context["context_digest"]},
    )
    assert stale.status_code == 409
    assert provider.requests == [] and provider.discovery == []
    assert refresh(client, month)["summary"]["needs_review"] == 1
    with database.session_factory() as session:
        close_reporting_month(session, month)
    context = client.get(f"/api/months/{month}/draft-payouts").json()
    assert context["eligible_positions"] == 0
    before = len(provider.requests)
    assert (
        client.post(
            f"/api/months/{month}/draft-payouts/refresh",
            json={"context_digest": context["context_digest"]},
        ).status_code
        == 409
    )
    assert len(provider.requests) == before


@pytest.mark.parametrize("detail", [None, "RU000A000001", "USD"])
def test_discovery_requires_independent_exact_isin_kind_and_currency(database, detail):
    provider = Provider()
    discover = provider.discover_candidates

    def incomplete(**kwargs):
        result = discover(**kwargs)
        candidate = replace(
            result.candidates[0],
            verified_isin=ISIN if detail == "USD" else detail,
            currency="USD" if detail == "USD" else "RUB",
        )
        return replace(result, candidates=(candidate,))

    provider.discover_candidates = incomplete
    client, month = setup(database, provider)
    before = _all_month_tables(database)
    assert refresh(client, month)["summary"]["needs_review"] == 1
    assert provider.requests == []
    assert _all_month_tables(database) == before


@pytest.mark.parametrize("when", [1, 2])
def test_identity_registry_aba_during_discovery_or_uid_verification(database, when):
    from hermes_finance.persistence import BrokerIdentityMapping
    from hermes_finance.services.broker_identity_mappings import confirm_mapping, revoke_mapping

    provider = Provider()
    client, month = setup(database, provider)
    original = provider.discover_candidates

    def changed(**kwargs):
        result = original(**kwargs)
        if len(provider.discovery) == when:
            # A revoke/restore of the same identity advances the source journal.
            with database.session_factory() as session:
                row = session.scalar(
                    select(BrokerIdentityMapping).where(
                        BrokerIdentityMapping.provider_identity == ACCOUNT
                    )
                )
                revoke_mapping(session, row.id)
                confirm_mapping(
                    session,
                    provider="alfa_mybroker",
                    subject_kind="account",
                    provider_identity=ACCOUNT,
                    hermes_target_id=1,
                )
        return result

    provider.discover_candidates = changed
    assert refresh(client, month)["summary"]["updated"] == 0
    assert provider.requests == []
    assert not _all_month_tables(database)["instrument_market_mappings"]


def test_sold_out_source_creates_no_positive_position_or_provider_request(database):
    provider = Provider()
    xml = (
        broker_month_xml()
        .replace(b'real_rest="10"', b'real_rest="0"')
        .replace(b'forward_rest="10"', b'forward_rest="0"')
        .replace(b'real_volume="1000.00"', b'real_volume="0"')
        .replace(b'qty="2"', b'qty="-8"')
        .replace(b'summ_trade="1000.00"', b'summ_trade="800.00"')
        .replace(b'volume="-1000.00"', b'volume="800.00"')
        .replace(b'real_rest="400.00"', b'real_rest="2200.00"')
    )
    client, month = setup(database, provider, xml)
    assert refresh(client, month)["items"] == []
    assert provider.requests == [] and provider.discovery == []


def test_missing_month_is_404_without_provider_io(database):
    provider = Provider()
    client = TestClient(
        create_app(database=database, market_data_provider=provider, payout_provider=provider)
    )
    assert client.get("/api/months/999/draft-payouts").status_code == 404
    assert (
        client.post(
            "/api/months/999/draft-payouts/refresh", json={"context_digest": "a" * 64}
        ).status_code
        == 404
    )
    assert provider.requests == [] and provider.discovery == []


@pytest.mark.parametrize("case", ["empty", "error", "quantity", "partial"])
def test_later_incomplete_response_or_changed_position_never_erases_saved_rows(database, case):
    provider = Provider()
    client, month = setup(database, provider)
    assert refresh(client, month)["summary"]["updated"] == 1
    before = _all_month_tables(database)
    if case == "empty":
        provider.events = lambda event: ()
    elif case == "error":
        provider.fail = True
    elif case == "partial":
        provider.amount = Decimal("3")
        provider.events = lambda event: (
            event,
            replace(
                event,
                identity_key="id:incomplete",
                payment_date=None,
                status=PayoutEventStatus.UNAVAILABLE,
            ),
        )
    else:
        with database.session_factory() as session:
            position = session.scalar(select(PositionSnapshot))
            position.quantity = Decimal("12")
            session.commit()
    result = refresh(client, month)
    saved = _all_month_tables(database)
    assert result["summary"]["needs_review"] + result["summary"]["error"] > 0
    for table in (
        "investment_cash_flows",
        "expected_cash_flows",
        "applied_provider_payouts",
        "applied_payout_revisions",
    ):
        if case == "partial" and table in {"applied_provider_payouts", "applied_payout_revisions"}:
            continue
        assert saved[table] == before[table], table
    if case == "partial":
        assert result["summary"]["updated"] == 1
        assert len(calendar(client, month)) == 1
    else:
        assert result["summary"]["updated"] == 0


def test_existing_970_paid_and_retired_actual_links_survive_refresh(database, settlement):
    from test_statement_import_payout_reconciliation import accept, create_provider_forecast

    from hermes_finance.persistence import InvestmentCashFlow

    client, intent = settlement
    provider = Provider()
    provider.payment = date(2030, 2, 1)
    provider.ambiguous = True  # Unrelated unmapped stock stays a manual exception.
    provider.events = lambda event: (
        replace(event, event_kind=PayoutEventKind.COUPON, identity_key="n:1"),
    )
    client.app.state.market_data_provider = provider
    client.app.state.payout_provider = provider
    with database.session_factory() as session:
        actual = session.get(InvestmentCashFlow, intent["investment_cash_flow_id"])
        app_id = create_provider_forecast(session, actual)
    intent = {**intent, "applied_payout_id": app_id}
    paid, _ = accept(client, intent, "draft-paid", provider_key="n:1")
    month = intent["reporting_month_id"]
    before = _all_month_tables(database)
    result = refresh(client, month)
    assert result["summary"]["updated"] == 0
    assert len(provider.requests) == 1
    assert _all_month_tables(database) == before
    assert client.get("/api/broker-months/draft-paid").json()["relations"][0]["state"] == "paid"
    accept(
        client,
        {**intent, "operation": "retire", "predecessor_id": paid["relations"][0]["id"]},
        "draft-retired",
        provider_key="n:1",
    )
    before = _all_month_tables(database)
    result = refresh(client, month)
    assert result["summary"]["updated"] == 0
    assert "actual_payout_review_required" in str(result)
    assert _all_month_tables(database) == before
    assert client.get("/api/broker-months/draft-paid").json()["relations"][0]["state"] == "retired"
