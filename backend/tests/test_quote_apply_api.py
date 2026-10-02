"""API tests for R04-06 selective quote apply."""

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from hermes_finance.database import create_database
from hermes_finance.domain import InstrumentType
from hermes_finance.main import create_app
from hermes_finance.market_data.dto import (
    T_INVEST_PROVIDER,
    DiscoverCandidate,
    DiscoverResult,
    MarketIdentity,
    QuoteKind,
    QuoteResult,
    QuoteStatus,
    QuoteSuccess,
    RawPriceBasis,
    market_identity_key,
)
from hermes_finance.persistence import (
    Base,
    Instrument,
    InstrumentMarketMapping,
    PositionQuoteProvenance,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.quote_preview_evidence import (
    QuotePreviewEvidenceError,
    QuotePreviewEvidenceStore,
)

TODAY = date(2026, 8, 13)
FETCHED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
STOCK_UID = "11111111-1111-1111-1111-111111111111"
STOCK_IDENTITY = MarketIdentity(
    provider=T_INVEST_PROVIDER,
    provider_instrument_id=STOCK_UID,
    provider_venue_id=None,
)


class ScriptedProvider:
    def __init__(self, quotes: dict[tuple[str, str, str | None], QuoteResult]) -> None:
        self.quotes = quotes
        self.fetch_calls = []

    def discover_candidates(self, **kwargs: object) -> DiscoverResult:
        return DiscoverResult(
            status=QuoteStatus.OK,
            candidates=(
                DiscoverCandidate(identity=STOCK_IDENTITY, instrument_kind=InstrumentType.STOCK),
            ),
        )

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
        self.fetch_calls.append((identity, target_date))
        return self.quotes[market_identity_key(identity)]

    def fetch_quotes(self, items: list[tuple[MarketIdentity, date]]) -> list[QuoteResult]:
        return [self.fetch_quote(identity, target_date) for identity, target_date in items]


def _success(
    identity: MarketIdentity, kopecks: int, status: QuoteStatus = QuoteStatus.OK
) -> QuoteSuccess:
    return QuoteSuccess(
        identity=identity,
        instrument_kind=InstrumentType.STOCK,
        raw_price="215.50",
        raw_price_basis=RawPriceBasis.CASH_PER_UNIT,
        proposed_price_kopecks=kopecks,
        price_date=TODAY,
        quote_kind=QuoteKind.HISTORY,
        fetched_at_utc=FETCHED_AT,
        freshness_status=status,
    )


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "quote_apply_api.db")
    Base.metadata.create_all(database.engine)
    provider = ScriptedProvider(
        {market_identity_key(STOCK_IDENTITY): _success(STOCK_IDENTITY, 21550)}
    )
    application = create_app(database, market_data_provider=provider)
    application.state.quote_preview_clock = lambda: TODAY
    try:
        with TestClient(application) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def _month(client: TestClient) -> dict:
    created = client.post(
        "/api/months", json={"year": 2026, "month": 8, "snapshot_date": "2026-08-31"}
    )
    assert created.status_code == 201
    return created.json()


def _setup_position(client: TestClient) -> tuple[dict, dict]:
    month = _month(client)
    account = client.post("/api/accounts", json={"name": "Broker", "account_type": "brokerage"})
    assert account.status_code == 201
    instrument = client.post(
        "/api/instruments", json={"name": "T Stock", "instrument_type": "stock"}
    )
    assert instrument.status_code == 201
    mapped = client.put(
        f"/api/instruments/{instrument.json()['id']}/market-mapping",
        params={"verify": "true"},
        json={
            "provider": T_INVEST_PROVIDER,
            "provider_instrument_id": STOCK_UID,
            "provider_venue_id": None,
        },
    )
    assert mapped.status_code == 200
    position = client.post(
        "/api/positions",
        json={
            "reporting_month_id": month["id"],
            "account_id": account.json()["id"],
            "instrument_id": instrument.json()["id"],
            "quantity": "10",
            "average_cost_per_unit": _rub("200.00"),
            "market_price_per_unit": _rub("200.00"),
            "accrued_interest": _rub("15.00"),
            "price_date": "2026-08-01",
            "price_source": "manual",
        },
    )
    assert position.status_code == 201
    return month, position.json()


def _apply_body(position_id: int, *, amount: str = "215.50", accept_stale: bool = False) -> dict:
    return {
        "rows": [
            {
                "position_snapshot_id": position_id,
                "accept_stale": accept_stale,
                "expected_market_price_per_unit": _rub(amount),
                "expected_price_date": "2026-08-13",
                "expected_identity": {
                    "provider": T_INVEST_PROVIDER,
                    "provider_instrument_id": STOCK_UID,
                    "provider_venue_id": None,
                },
                "expected_quote_kind": "history",
            }
        ]
    }


def test_apply_ok_row(client: TestClient) -> None:
    month, position = _setup_position(client)
    response = client.post(
        f"/api/months/{month['id']}/quote-apply", json=_apply_body(position["id"])
    )
    assert response.status_code == 200
    body = response.json()
    assert body["applied_count"] == 1
    assert body["rows"][0]["price_source"] == "t_invest"
    assert body["rows"][0]["market_price_per_unit"] == _rub("215.50")
    assert body["rows"][0]["accrued_interest"] == _rub("15.00")
    listed = client.get(f"/api/positions?month_id={month['id']}")
    assert listed.json()[0]["price_source"] == "t_invest"


def test_apply_preview_changed_is_conflict(client: TestClient) -> None:
    month, position = _setup_position(client)
    response = client.post(
        f"/api/months/{month['id']}/quote-apply",
        json=_apply_body(position["id"], amount="200.00"),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "preview_changed"
    listed = client.get(f"/api/positions?month_id={month['id']}")
    assert listed.json()[0]["price_source"] == "manual"


def test_apply_closed_month_is_conflict(client: TestClient) -> None:
    month, position = _setup_position(client)
    closed = client.post(f"/api/months/{month['id']}/close")
    assert closed.status_code == 200
    response = client.post(
        f"/api/months/{month['id']}/quote-apply", json=_apply_body(position["id"])
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_generic_position_api_rejects_fake_t_invest(client: TestClient) -> None:
    month, position = _setup_position(client)
    extra = client.post(
        "/api/instruments", json={"name": "Other Stock", "instrument_type": "stock"}
    )
    assert extra.status_code == 201
    created = client.post(
        "/api/positions",
        json={
            "reporting_month_id": month["id"],
            "account_id": position["account_id"],
            "instrument_id": extra.json()["id"],
            "quantity": "1",
            "average_cost_per_unit": _rub("10.00"),
            "market_price_per_unit": _rub("10.00"),
            "price_date": "2026-08-01",
            "price_source": "t_invest",
        },
    )
    assert created.status_code == 422
    patched = client.patch(
        f"/api/positions/{position['id']}",
        json={"price_source": "t_invest"},
        headers={"If-Match": position["updated_at"]},
    )
    assert patched.status_code == 422


def test_generic_patch_on_applied_t_invest_snapshot(client: TestClient) -> None:
    month, position = _setup_position(client)
    applied = client.post(
        f"/api/months/{month['id']}/quote-apply", json=_apply_body(position["id"])
    )
    assert applied.status_code == 200
    listed = client.get(f"/api/positions?month_id={month['id']}")
    current = listed.json()[0]
    qty = client.patch(
        f"/api/positions/{current['id']}",
        json={"quantity": "11"},
        headers={"If-Match": current["updated_at"]},
    )
    assert qty.status_code == 200
    assert qty.json()["price_source"] == "t_invest"
    assert qty.json()["market_price_per_unit"] == _rub("215.50")

    keep_t_invest = client.patch(
        f"/api/positions/{current['id']}",
        json={"market_price_per_unit": _rub("250.00"), "price_source": "t_invest"},
        headers={"If-Match": qty.json()["updated_at"]},
    )
    assert keep_t_invest.status_code == 422

    manual = client.patch(
        f"/api/positions/{current['id']}",
        json={"market_price_per_unit": _rub("250.00"), "price_source": "manual"},
        headers={"If-Match": qty.json()["updated_at"]},
    )
    assert manual.status_code == 200
    assert manual.json()["price_source"] == "manual"
    assert manual.json()["market_price_per_unit"] == _rub("250.00")


def _live_preview(client: TestClient, month: dict, position: dict) -> dict:
    provider = client.app.state.market_data_provider
    provider.quotes[market_identity_key(STOCK_IDENTITY)] = replace(
        _success(STOCK_IDENTITY, 21550), quote_kind=QuoteKind.LAST
    )
    response = client.post(f"/api/months/{month['id']}/quote-preview")
    assert response.status_code == 200
    body = _apply_body(position["id"])
    body["preview_id"] = response.json()["preview_id"]
    assert body["preview_id"]
    body["rows"][0]["expected_quote_kind"] = "last"
    return body


def _unchanged(client: TestClient, month: dict) -> None:
    rows = client.get(f"/api/positions?month_id={month['id']}").json()
    assert all(row["price_source"] == "manual" for row in rows)
    with client.app.state.database.session_factory() as session:
        assert list(session.scalars(select(PositionQuoteProvenance))) == []


def test_current_last_uses_preview_observation_once_with_distinct_provenance(
    client: TestClient,
) -> None:
    month, position = _setup_position(client)
    body = _live_preview(client, month, position)
    provider = client.app.state.market_data_provider
    calls = len(provider.fetch_calls)
    provider.quotes[market_identity_key(STOCK_IDENTITY)] = replace(
        _success(STOCK_IDENTITY, 25000), quote_kind=QuoteKind.LAST
    )
    applied = client.post(f"/api/months/{month['id']}/quote-apply", json=body)
    assert applied.status_code == 200
    assert applied.json()["rows"][0]["market_price_per_unit"] == _rub("215.50")
    assert applied.json()["rows"][0]["accrued_interest"] == _rub("15.00")
    assert len(provider.fetch_calls) == calls
    replay = client.post(f"/api/months/{month['id']}/quote-apply", json=body)
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "preview_evidence_invalid"
    with client.app.state.database.session_factory() as session:
        provenance = list(session.scalars(select(PositionQuoteProvenance)))
        assert len(provenance) == 1
        assert provenance[0].fetched_at_utc.replace(tzinfo=timezone.utc) == FETCHED_AT
        assert provenance[0].applied_at_utc != provenance[0].fetched_at_utc
        assert provenance[0].raw_price == "215.50"


@pytest.mark.parametrize(
    "field", ["money", "date", "provider", "identity", "venue", "kind", "missing_kind"]
)
def test_live_evidence_rejects_tampered_browser_guards(client: TestClient, field: str) -> None:
    month, position = _setup_position(client)
    body = _live_preview(client, month, position)
    row = body["rows"][0]
    if field == "money":
        row["expected_market_price_per_unit"] = _rub("250.00")
    elif field == "date":
        row["expected_price_date"] = "2026-08-12"
    elif field in {"provider", "identity", "venue"}:
        key = {
            "provider": "provider",
            "identity": "provider_instrument_id",
            "venue": "provider_venue_id",
        }[field]
        row["expected_identity"][key] = "tampered"
    elif field == "kind":
        row["expected_quote_kind"] = "history"
    else:
        del row["expected_quote_kind"]
    response = client.post(f"/api/months/{month['id']}/quote-apply", json=body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "preview_changed"
    _unchanged(client, month)
    assert client.post(f"/api/months/{month['id']}/quote-apply", json=body).status_code == 409


@pytest.mark.parametrize(
    "reason", ["missing", "unknown", "superseded", "restart", "foreign_month", "expiry", "midnight"]
)
def test_evidence_unavailable_requires_explicit_preview(client: TestClient, reason: str) -> None:
    elapsed = [10.0]
    client.app.state.quote_preview_evidence = QuotePreviewEvidenceStore(lambda: elapsed[0])
    month, position = _setup_position(client)
    body = _live_preview(client, month, position)
    if reason == "missing":
        del body["preview_id"]
    elif reason == "unknown":
        body["preview_id"] = "foreign-runtime"
    elif reason == "superseded":
        client.post(f"/api/months/{month['id']}/quote-preview")
    elif reason == "restart":
        client.app.state.quote_preview_evidence = QuotePreviewEvidenceStore(lambda: elapsed[0])
    elif reason == "foreign_month":
        other = client.post(
            "/api/months", json={"year": 2026, "month": 7, "snapshot_date": "2026-07-31"}
        ).json()
        body["preview_id"] = client.post(f"/api/months/{other['id']}/quote-preview").json()[
            "preview_id"
        ]
    elif reason == "expiry":
        elapsed[0] += 120
    else:
        client.app.state.quote_preview_clock = lambda: date(2026, 8, 14)
    response = client.post(f"/api/months/{month['id']}/quote-apply", json=body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "preview_evidence_invalid"
    _unchanged(client, month)


@pytest.mark.parametrize(
    "change",
    ["quantity", "nkd", "account", "mapping", "excluded", "instrument", "month", "deleted"],
)
def test_live_evidence_revalidates_exact_local_context(client: TestClient, change: str) -> None:
    month, position = _setup_position(client)
    body = _live_preview(client, month, position)
    with client.app.state.database.session_factory() as session:
        if change == "mapping":
            session.execute(
                update(InstrumentMarketMapping).values(provider_instrument_id="changed")
            )
        elif change == "excluded":
            session.execute(update(InstrumentMarketMapping).values(excluded=True))
        elif change == "instrument":
            session.execute(update(Instrument).values(nominal_value_kopecks=100000))
        elif change == "month":
            session.execute(update(ReportingMonth).values(snapshot_date=date(2026, 8, 12)))
        elif change == "deleted":
            session.delete(session.get(PositionSnapshot, position["id"]))
        else:
            values = {
                "quantity": {"quantity": "11"},
                "nkd": {"accrued_interest_kopecks": 1700},
                "account": {"account_id": position["account_id"] + 1},
            }
            if change == "account":
                account = client.post(
                    "/api/accounts", json={"name": "Second", "account_type": "brokerage"}
                ).json()
                values["account"]["account_id"] = account["id"]
            session.execute(update(PositionSnapshot).values(**values[change]))
        session.commit()
    response = client.post(f"/api/months/{month['id']}/quote-apply", json=body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "preview_evidence_invalid"
    _unchanged(client, month)


def test_live_evidence_closed_guard(client: TestClient) -> None:
    month, position = _setup_position(client)
    body = _live_preview(client, month, position)
    assert client.post(f"/api/months/{month['id']}/close").status_code == 200
    response = client.post(f"/api/months/{month['id']}/quote-apply", json=body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    _unchanged(client, month)


def test_concurrent_claim_has_exactly_one_winner(client: TestClient) -> None:
    month, position = _setup_position(client)
    body = _live_preview(client, month, position)
    store = client.app.state.quote_preview_evidence

    def claim() -> bool:
        try:
            store.claim(month["id"], body["preview_id"], TODAY)
            return True
        except QuotePreviewEvidenceError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: claim(), range(2))) == [False, True]


def test_concurrent_http_apply_mutates_once(client: TestClient) -> None:
    month, position = _setup_position(client)
    body = _live_preview(client, month, position)
    with ThreadPoolExecutor(max_workers=2) as executor:
        replies = list(
            executor.map(
                lambda _: client.post(f"/api/months/{month['id']}/quote-apply", json=body), range(2)
            )
        )
    assert sorted(reply.status_code for reply in replies) == [200, 409]
    with client.app.state.database.session_factory() as session:
        assert len(list(session.scalars(select(PositionQuoteProvenance)))) == 1


def test_context_is_reread_while_competing_writer_is_blocked(
    client: TestClient, monkeypatch
) -> None:
    from hermes_finance.services import quote_apply

    month, position = _setup_position(client)
    body = _live_preview(client, month, position)
    original = quote_apply.capture_context
    observed = []

    def capture(session, month_id):
        with client.app.state.database.engine.connect() as competitor:
            competitor.exec_driver_sql("PRAGMA busy_timeout=0")
            with pytest.raises(OperationalError, match="locked"):
                competitor.execute(
                    update(ReportingMonth)
                    .where(ReportingMonth.id == month_id)
                    .values(status="closed")
                )
        observed.append(True)
        return original(session, month_id)

    monkeypatch.setattr(quote_apply, "capture_context", capture)
    assert client.post(f"/api/months/{month['id']}/quote-apply", json=body).status_code == 200
    assert observed == [True]


def test_new_live_preview_appends_without_rewriting_first_observation(client: TestClient) -> None:
    month, position = _setup_position(client)
    body = _live_preview(client, month, position)
    assert client.post(f"/api/months/{month['id']}/quote-apply", json=body).status_code == 200
    with client.app.state.database.session_factory() as session:
        before = tuple(session.execute(select(PositionQuoteProvenance.__table__)).one())
    body = _live_preview(client, month, position)
    client.app.state.market_data_provider.quotes[market_identity_key(STOCK_IDENTITY)] = replace(
        _success(STOCK_IDENTITY, 30000), quote_kind=QuoteKind.LAST
    )
    assert client.post(f"/api/months/{month['id']}/quote-apply", json=body).status_code == 200
    with client.app.state.database.session_factory() as session:
        rows = session.execute(
            select(PositionQuoteProvenance.__table__).order_by(PositionQuoteProvenance.id)
        ).all()
        assert len(rows) == 2
        assert tuple(rows[0]) == before


@pytest.mark.parametrize("mode", ["history", "stale", "historical"])
def test_non_frozen_rows_keep_strict_refetch(client: TestClient, mode: str) -> None:
    month, position = _setup_position(client)
    provider = client.app.state.market_data_provider
    quote = _success(STOCK_IDENTITY, 21550)
    body = _apply_body(position["id"], accept_stale=mode == "stale")
    if mode == "stale":
        quote = replace(quote, freshness_status=QuoteStatus.STALE, quote_kind=QuoteKind.LAST)
        body["rows"][0]["expected_quote_kind"] = "last"
    elif mode == "historical":
        with client.app.state.database.session_factory() as session:
            session.execute(update(ReportingMonth).values(snapshot_date=date(2026, 8, 12)))
            session.commit()
        quote = replace(quote, price_date=date(2026, 8, 12))
        body["rows"][0]["expected_price_date"] = "2026-08-12"
    provider.quotes[market_identity_key(STOCK_IDENTITY)] = quote
    body["preview_id"] = client.post(f"/api/months/{month['id']}/quote-preview").json()[
        "preview_id"
    ]
    provider.quotes[market_identity_key(STOCK_IDENTITY)] = replace(
        quote, proposed_price_kopecks=22000
    )
    before = len(provider.fetch_calls)
    response = client.post(f"/api/months/{month['id']}/quote-apply", json=body)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "preview_changed"
    assert len(provider.fetch_calls) == before + 1
    _unchanged(client, month)


@pytest.mark.parametrize("failure", [None, "conflict", "expiry", "midnight", "commit"])
def test_mixed_last_history_selected_set_is_atomic(
    client: TestClient, monkeypatch, failure: str | None
) -> None:
    elapsed = [1.0]
    client.app.state.quote_preview_evidence = QuotePreviewEvidenceStore(lambda: elapsed[0])
    month, first = _setup_position(client)
    second_identity = MarketIdentity(
        T_INVEST_PROVIDER, "22222222-2222-2222-2222-222222222222", None
    )
    provider = client.app.state.market_data_provider
    instrument = client.post(
        "/api/instruments", json={"name": "Second", "instrument_type": "stock"}
    ).json()
    with client.app.state.database.session_factory() as session:
        session.add(
            InstrumentMarketMapping(
                instrument_id=instrument["id"],
                provider=T_INVEST_PROVIDER,
                provider_instrument_id=second_identity.provider_instrument_id,
                excluded=False,
            )
        )
        session.commit()
    second = client.post(
        "/api/positions",
        json={
            "reporting_month_id": month["id"],
            "account_id": first["account_id"],
            "instrument_id": instrument["id"],
            "quantity": "1",
            "average_cost_per_unit": _rub("200.00"),
            "market_price_per_unit": _rub("200.00"),
            "price_date": "2026-08-01",
            "price_source": "manual",
        },
    ).json()
    provider.quotes[market_identity_key(second_identity)] = _success(second_identity, 21550)
    body = _live_preview(client, month, first)
    second_row = _apply_body(second["id"])["rows"][0]
    second_row["expected_identity"]["provider_instrument_id"] = (
        second_identity.provider_instrument_id
    )
    body["rows"].append(second_row)
    before = len(provider.fetch_calls)
    provider.quotes[market_identity_key(STOCK_IDENTITY)] = replace(
        _success(STOCK_IDENTITY, 30000), quote_kind=QuoteKind.LAST
    )
    if failure == "conflict":
        provider.quotes[market_identity_key(second_identity)] = _success(second_identity, 25000)
    original_fetch = provider.fetch_quotes

    def fetch(items):
        if failure == "expiry":
            elapsed[0] += 120
        elif failure == "midnight":
            client.app.state.quote_preview_clock = lambda: date(2026, 8, 14)
        return original_fetch(items)

    monkeypatch.setattr(provider, "fetch_quotes", fetch)
    if failure == "commit":
        from sqlalchemy.orm import Session

        def broken_commit(self):
            self.flush()
            raise RuntimeError("synthetic commit failure")

        monkeypatch.setattr(Session, "commit", broken_commit)
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            client.post(f"/api/months/{month['id']}/quote-apply", json=body)
    else:
        response = client.post(f"/api/months/{month['id']}/quote-apply", json=body)
        assert response.status_code == (200 if failure is None else 409)
    assert provider.fetch_calls[before:] == [(second_identity, TODAY)]
    if failure:
        _unchanged(client, month)
    else:
        assert response.json()["applied_count"] == 2
        assert all(
            row["market_price_per_unit"] == _rub("215.50") for row in response.json()["rows"]
        )


@pytest.mark.parametrize("mode", ["slow", "midnight"])
def test_preview_lifetime_starts_before_provider_fetch(
    client: TestClient, monkeypatch, mode: str
) -> None:
    elapsed = [1.0]
    client.app.state.quote_preview_evidence = QuotePreviewEvidenceStore(lambda: elapsed[0])
    month, _ = _setup_position(client)
    provider = client.app.state.market_data_provider
    original = provider.fetch_quotes

    def fetch(items):
        if mode == "slow":
            elapsed[0] += 120
        else:
            client.app.state.quote_preview_clock = lambda: date(2026, 8, 14)
        return original(items)

    monkeypatch.setattr(provider, "fetch_quotes", fetch)
    preview = client.post(f"/api/months/{month['id']}/quote-preview")
    assert preview.status_code == 200
    assert preview.json()["preview_id"] is None
    _unchanged(client, month)


@pytest.mark.parametrize("elapsed", [119.999, 120.0, -1.0])
def test_monotonic_lifetime_boundary(client: TestClient, elapsed: float) -> None:
    time = [10.0]
    client.app.state.quote_preview_evidence = QuotePreviewEvidenceStore(lambda: time[0])
    month, position = _setup_position(client)
    body = _live_preview(client, month, position)
    time[0] += elapsed
    response = client.post(f"/api/months/{month['id']}/quote-apply", json=body)
    assert response.status_code == (200 if 0 <= elapsed < 120 else 409)


def test_slow_competing_preview_cannot_republish_superseded_evidence(client: TestClient) -> None:
    from hermes_finance.services.quote_preview import preview_market_quotes
    from hermes_finance.services.quote_preview_evidence import capture_context

    month, position = _setup_position(client)
    store = client.app.state.quote_preview_evidence
    older = store.begin(month["id"], TODAY)
    with client.app.state.database.session_factory() as session:
        context = capture_context(session, month["id"])
        preview = preview_market_quotes(
            session, month["id"], provider=client.app.state.market_data_provider, today=TODAY
        )
    body = _live_preview(client, month, position)
    assert store.publish(older, context, preview, TODAY) is None
    assert client.post(f"/api/months/{month['id']}/quote-apply", json=body).status_code == 200
