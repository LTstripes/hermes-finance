from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest

from hermes_finance.domain import InstrumentType, RubleAmount
from hermes_finance.market_data import (
    MOEX_ISS_PROVIDER,
    MarketIdentity,
    MoexIssClient,
    QuoteFailure,
    QuoteKind,
    QuoteStatus,
    QuoteSuccess,
    RawPriceBasis,
)
from hermes_finance.market_data.iss_parse import (
    decimal_from_external,
    load_iss_json,
    parse_iss_payload,
    row_text,
)
from hermes_finance.market_data.normalize import (
    convert_to_kopecks,
    current_last_price_date,
    is_rub_compatible,
)

FIXTURES = Path(__file__).parent / "fixtures" / "moex_iss"
TODAY = date(2026, 8, 13)
FETCHED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)

STOCK = MarketIdentity(
    provider=MOEX_ISS_PROVIDER,
    engine="stock",
    market="shares",
    boardid="TQBR",
    secid="SYNTHS",
    isin="RU000SYNTH01",
)
FUND = MarketIdentity(
    provider=MOEX_ISS_PROVIDER,
    engine="stock",
    market="shares",
    boardid="TQTF",
    secid="SYNTHF",
    isin="RU000SYNTH02",
)
BOND = MarketIdentity(
    provider=MOEX_ISS_PROVIDER,
    engine="stock",
    market="bonds",
    boardid="TQCB",
    secid="SYNTHB",
    isin="RU000SYNTH03",
)
BOND_CASH = MarketIdentity(
    provider=MOEX_ISS_PROVIDER,
    engine="stock",
    market="bonds",
    boardid="TQCB",
    secid="SYNTHR",
    isin="RU000SYNTH04",
)


def _table(columns: list[str], *rows: list[object]) -> dict[str, object]:
    return {"columns": columns, "data": [list(row) for row in rows]}


def _description(*pairs: tuple[str, str]) -> dict[str, object]:
    return _table(["name", "title", "value"], *[[name, name, value] for name, value in pairs])


def _security_payload(
    *,
    secid: str,
    kind_pairs: list[tuple[str, str]],
    boards: list[list[object]],
) -> dict[str, object]:
    return {
        "description": _description(*kind_pairs),
        "boards": _table(["secid", "boardid", "engine", "market", "currencyid"], *boards),
    }


def _market_payload(
    identity: MarketIdentity,
    *,
    last: object | None,
    last_date: str | None,
    face_value: object = "1",
    face_unit: str = "SUR",
    quote_basis: str | None = "R",
    currency: str = "SUR",
) -> dict[str, object]:
    return {
        "securities": _table(
            ["SECID", "BOARDID", "FACEVALUE", "FACEUNIT", "QUOTEBASIS", "CURRENCYID"],
            [identity.secid, identity.boardid, face_value, face_unit, quote_basis, currency],
        ),
        "marketdata": _table(
            ["SECID", "BOARDID", "LAST", "TIME", "SYSTIME"],
            [
                identity.secid,
                identity.boardid,
                last,
                "18:39:59",
                f"{last_date or '2026-08-14'} 00:05:01",
            ],
        ),
    }


def _history_payload(identity: MarketIdentity, *rows: tuple[str, object]) -> dict[str, object]:
    return {
        "history": _table(
            ["TRADEDATE", "SECID", "BOARDID", "CLOSE", "LASTPRICE", "LEGALCLOSEPRICE"],
            *[
                [trade_date, identity.secid, identity.boardid, price, price, price]
                for trade_date, price in rows
            ],
        )
    }


STOCK_DETAILS = _security_payload(
    secid="SYNTHS",
    kind_pairs=[
        ("ISIN", "RU000SYNTH01"),
        ("TYPE", "common_share"),
        ("GROUP", "stock_shares"),
        ("FACEUNIT", "SUR"),
    ],
    boards=[["SYNTHS", "TQBR", "stock", "shares", "SUR"]],
)
FUND_DETAILS = _security_payload(
    secid="SYNTHF",
    kind_pairs=[
        ("ISIN", "RU000SYNTH02"),
        ("TYPE", "etf_ppif"),
        ("GROUP", "stock_etf"),
        ("FACEUNIT", "SUR"),
    ],
    boards=[["SYNTHF", "TQTF", "stock", "shares", "SUR"]],
)
BOND_DETAILS = _security_payload(
    secid="SYNTHB",
    kind_pairs=[
        ("ISIN", "RU000SYNTH03"),
        ("TYPE", "exchange_bond"),
        ("GROUP", "stock_bonds"),
        ("FACEVALUE", "1000"),
        ("FACEUNIT", "RUB"),
        ("QUOTEBASIS", "F"),
    ],
    boards=[["SYNTHB", "TQCB", "stock", "bonds", "RUB"]],
)
BOND_CASH_DETAILS = _security_payload(
    secid="SYNTHR",
    kind_pairs=[
        ("ISIN", "RU000SYNTH04"),
        ("TYPE", "exchange_bond"),
        ("GROUP", "stock_bonds"),
        ("FACEVALUE", "1000"),
        ("FACEUNIT", "RUB"),
        ("QUOTEBASIS", "R"),
    ],
    boards=[["SYNTHR", "TQCB", "stock", "bonds", "RUB"]],
)


class IssStub:
    def __init__(self) -> None:
        self.payloads: dict[str, object] = {}
        self.errors: dict[str, Exception] = {}
        self.status_codes: dict[str, int] = {}

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path in self.errors:
            raise self.errors[path]
        if path in self.status_codes:
            return httpx2.Response(self.status_codes[path], text="upstream error")
        payload = self.payloads.get(path)
        if payload is None:
            return httpx2.Response(404, text="{}")
        return httpx2.Response(200, json=payload)


def _client(stub: IssStub, *, today: date = TODAY) -> MoexIssClient:
    http = httpx2.Client(
        transport=httpx2.MockTransport(stub),
        base_url="https://iss.moex.com",
    )
    return MoexIssClient(client=http, clock=lambda: today, utcnow=lambda: FETCHED_AT)


def _put_identity(
    stub: IssStub,
    identity: MarketIdentity,
    details: dict[str, object],
    market: dict[str, object],
    history: dict[str, object] | None = None,
) -> None:
    stub.payloads[f"/iss/securities/{identity.secid}.json"] = details
    stub.payloads[
        f"/iss/engines/{identity.engine}/markets/{identity.market}"
        f"/boards/{identity.boardid}/securities/{identity.secid}.json"
    ] = market
    stub.payloads[
        f"/iss/history/engines/{identity.engine}/markets/{identity.market}"
        f"/boards/{identity.boardid}/securities/{identity.secid}.json"
    ] = history or {"history": _table(["TRADEDATE", "CLOSE"])}


def test_iss_parser_maps_rows_by_column_name_not_position() -> None:
    payload = load_iss_json((FIXTURES / "shuffled_securities.json").read_text(encoding="utf-8"))
    rows = parse_iss_payload(payload)["securities"]

    assert len(rows) == 1
    assert row_text(rows[0], "SECID") == "SYNTHS"
    assert row_text(rows[0], "BOARDID") == "TQBR"
    assert row_text(rows[0], "QUOTEBASIS") == "R"
    assert list(rows[0].keys())[0] == "FACEUNIT"


def test_decimal_from_external_converts_float_only_via_text() -> None:
    amount = decimal_from_external(97.25, name="LAST")

    assert amount == Decimal("97.25")
    assert (
        convert_to_kopecks(
            raw_price=amount,
            basis=RawPriceBasis.PERCENT_OF_FACE,
            face_value=Decimal("1000"),
            currency_unit="RUB",
            shares_schema_cash_default=False,
        )
        == 97250
    )


def test_convert_to_kopecks_rejects_binary_float() -> None:
    with pytest.raises(TypeError, match="float"):
        convert_to_kopecks(
            raw_price=97.25,  # type: ignore[arg-type]
            basis=RawPriceBasis.PERCENT_OF_FACE,
            face_value=Decimal("1000"),
            currency_unit="RUB",
            shares_schema_cash_default=False,
        )


def test_current_last_price_date_is_moscow_session_not_systime() -> None:
    assert current_last_price_date(session_date=TODAY, target_date=TODAY) == TODAY
    assert current_last_price_date(session_date=date(2026, 8, 14), target_date=TODAY) is None


def test_sur_and_rur_are_accepted_rub_compatible_units() -> None:
    assert is_rub_compatible("SUR")
    assert is_rub_compatible("rur")
    assert is_rub_compatible("RUB")
    assert not is_rub_compatible("USD")
    for unit in ("SUR", "RUR"):
        assert (
            convert_to_kopecks(
                raw_price=Decimal("10.00"),
                basis=RawPriceBasis.CASH_PER_UNIT,
                face_value=None,
                currency_unit=unit,
                shares_schema_cash_default=False,
            )
            == 1000
        )


def test_current_last_uses_documented_shares_marketdata_without_trade_date() -> None:
    payload = load_iss_json(
        (FIXTURES / "shares_marketdata_current.json").read_text(encoding="utf-8")
    )
    marketdata_columns = payload["marketdata"]["columns"]
    assert "TRADEDATE" not in marketdata_columns
    assert "LASTTRADEDATE" not in marketdata_columns
    assert "LAST" in marketdata_columns
    assert "TIME" in marketdata_columns
    assert "SYSTIME" in marketdata_columns

    stub = IssStub()
    stub.payloads[f"/iss/securities/{STOCK.secid}.json"] = STOCK_DETAILS
    stub.payloads[
        f"/iss/engines/{STOCK.engine}/markets/{STOCK.market}"
        f"/boards/{STOCK.boardid}/securities/{STOCK.secid}.json"
    ] = payload
    with _client(stub) as client:
        result = client.fetch_quote(STOCK, TODAY)

    assert isinstance(result, QuoteSuccess)
    assert result.quote_kind is QuoteKind.LAST
    assert result.proposed_price_kopecks == 12345
    assert result.price_date == TODAY
    assert result.price_date != date(2026, 8, 14)


def test_stock_cash_per_unit_quote_to_exact_kopecks() -> None:
    stub = IssStub()
    _put_identity(
        stub,
        STOCK,
        STOCK_DETAILS,
        _market_payload(STOCK, last="123.45", last_date="2026-08-13"),
    )
    with _client(stub) as client:
        result = client.fetch_quote(STOCK, TODAY)

    assert isinstance(result, QuoteSuccess)
    assert result.instrument_kind is InstrumentType.STOCK
    assert result.raw_price_basis is RawPriceBasis.CASH_PER_UNIT
    assert result.proposed_price_kopecks == 12345
    assert result.price_date == TODAY
    assert result.quote_kind is QuoteKind.LAST
    assert result.freshness_status is QuoteStatus.OK
    assert RubleAmount(result.proposed_price_kopecks).to_api() == "123.45"


def test_fetch_quote_accepts_rur_currency_unit() -> None:
    stub = IssStub()
    _put_identity(
        stub,
        STOCK,
        STOCK_DETAILS,
        _market_payload(
            STOCK,
            last="11.00",
            last_date="2026-08-13",
            face_unit="RUR",
            currency="RUR",
        ),
    )
    with _client(stub) as client:
        result = client.fetch_quote(STOCK, TODAY)

    assert isinstance(result, QuoteSuccess)
    assert result.proposed_price_kopecks == 1100


def test_fund_cash_per_unit_quote_to_exact_kopecks() -> None:
    stub = IssStub()
    _put_identity(
        stub,
        FUND,
        FUND_DETAILS,
        _market_payload(FUND, last="10.50", last_date="2026-08-13"),
    )
    with _client(stub) as client:
        result = client.fetch_quote(FUND, TODAY)

    assert isinstance(result, QuoteSuccess)
    assert result.instrument_kind is InstrumentType.FUND
    assert result.proposed_price_kopecks == 1050
    assert result.freshness_status is QuoteStatus.OK


def test_bond_percent_of_face_converts_with_decimal_half_up() -> None:
    stub = IssStub()
    _put_identity(
        stub,
        BOND,
        BOND_DETAILS,
        _market_payload(
            BOND,
            last="97.25",
            last_date="2026-08-13",
            face_value="1000.00",
            face_unit="RUB",
            quote_basis="F",
            currency="RUB",
        ),
    )
    with _client(stub) as client:
        result = client.fetch_quote(BOND, TODAY)

    assert isinstance(result, QuoteSuccess)
    assert result.instrument_kind is InstrumentType.BOND
    assert result.raw_price_basis is RawPriceBasis.PERCENT_OF_FACE
    assert result.raw_price == "97.25"
    assert result.proposed_price_kopecks == 97250


def test_bond_cash_basis_skips_percent_conversion() -> None:
    stub = IssStub()
    _put_identity(
        stub,
        BOND_CASH,
        BOND_CASH_DETAILS,
        _market_payload(
            BOND_CASH,
            last="972.50",
            last_date="2026-08-13",
            face_value="1000.00",
            face_unit="RUB",
            quote_basis="R",
            currency="RUB",
        ),
    )
    with _client(stub) as client:
        result = client.fetch_quote(BOND_CASH, TODAY)

    assert isinstance(result, QuoteSuccess)
    assert result.raw_price_basis is RawPriceBasis.CASH_PER_UNIT
    assert result.proposed_price_kopecks == 97250


def test_missing_current_last_uses_prior_history_not_newer_than_target() -> None:
    stub = IssStub()
    _put_identity(
        stub,
        STOCK,
        STOCK_DETAILS,
        _market_payload(STOCK, last=None, last_date=None),
        _history_payload(STOCK, ("2026-08-12", "120.00"), ("2026-08-14", "999.00")),
    )
    with _client(stub) as client:
        result = client.fetch_quote(STOCK, TODAY)

    assert isinstance(result, QuoteSuccess)
    assert result.quote_kind is QuoteKind.HISTORY
    assert result.price_date == date(2026, 8, 12)
    assert result.proposed_price_kopecks == 12000
    assert result.freshness_status is QuoteStatus.OK


def test_weekend_gap_within_seven_days_is_usable_with_actual_price_date() -> None:
    target = date(2026, 8, 10)
    stub = IssStub()
    _put_identity(
        stub,
        STOCK,
        STOCK_DETAILS,
        _market_payload(STOCK, last=None, last_date=None),
        _history_payload(STOCK, ("2026-08-07", "101.00")),
    )
    with _client(stub) as client:
        result = client.fetch_quote(STOCK, target)

    assert isinstance(result, QuoteSuccess)
    assert result.price_date == date(2026, 8, 7)
    assert result.proposed_price_kopecks == 10100
    assert result.freshness_status is QuoteStatus.OK


def test_eight_to_thirty_day_gap_is_stale_proposal() -> None:
    stub = IssStub()
    _put_identity(
        stub,
        STOCK,
        STOCK_DETAILS,
        _market_payload(STOCK, last=None, last_date=None),
        _history_payload(STOCK, ("2026-08-03", "99.10")),
    )
    with _client(stub) as client:
        result = client.fetch_quote(STOCK, TODAY)

    assert isinstance(result, QuoteSuccess)
    assert result.price_date == date(2026, 8, 3)
    assert (TODAY - result.price_date).days == 10
    assert result.freshness_status is QuoteStatus.STALE
    assert result.status is QuoteStatus.STALE


def test_no_valid_quote_within_30_days_is_unavailable() -> None:
    stub = IssStub()
    _put_identity(
        stub,
        STOCK,
        STOCK_DETAILS,
        _market_payload(STOCK, last=None, last_date=None),
        _history_payload(STOCK, ("2026-07-01", "80.00")),
    )
    with _client(stub) as client:
        result = client.fetch_quote(STOCK, TODAY)

    assert isinstance(result, QuoteFailure)
    assert result.status is QuoteStatus.UNAVAILABLE


def test_isin_mismatch_hard_rejects_candidate() -> None:
    stub = IssStub()
    stub.payloads["/iss/securities.json"] = {
        "securities": _table(
            ["secid", "isin", "type", "group"],
            ["SYNTHS", "RU000SYNTH01", "common_share", "stock_shares"],
        )
    }
    stub.payloads["/iss/securities/SYNTHS.json"] = STOCK_DETAILS
    with _client(stub) as client:
        result = client.discover_candidates(isin="RU000OTHER99")

    assert result.status is QuoteStatus.UNAVAILABLE
    assert result.candidates == ()
    assert len(result.rejected) == 1
    assert result.rejected[0].candidate_isin == "RU000SYNTH01"
    assert result.rejected[0].expected_isin == "RU000OTHER99"
    assert result.rejected[0].reason == "isin_mismatch"


def test_discover_filters_non_rub_boards_before_ambiguity() -> None:
    stub = IssStub()
    stub.payloads["/iss/securities/SYNTHS.json"] = _security_payload(
        secid="SYNTHS",
        kind_pairs=[
            ("ISIN", "RU000SYNTH01"),
            ("TYPE", "common_share"),
            ("GROUP", "stock_shares"),
            ("FACEUNIT", "SUR"),
        ],
        boards=[
            ["SYNTHS", "TQBR", "stock", "shares", "SUR"],
            ["SYNTHS", "FQBR", "stock", "shares", "USD"],
        ],
    )
    with _client(stub) as client:
        result = client.discover_candidates(secid="SYNTHS")

    assert result.status is QuoteStatus.OK
    assert len(result.candidates) == 1
    assert result.candidates[0].identity.boardid == "TQBR"
    assert result.candidates[0].identity.engine == "stock"
    assert result.candidates[0].identity.market == "shares"


def test_discover_bond_f_rub_currency_usd_faceunit_is_unsupported() -> None:
    stub = IssStub()
    stub.payloads["/iss/securities/SYNTHB.json"] = {
        "description": _description(
            ("ISIN", "RU000SYNTH03"),
            ("TYPE", "exchange_bond"),
            ("GROUP", "stock_bonds"),
            ("QUOTEBASIS", "F"),
            ("FACEUNIT", "USD"),
        ),
        "boards": _table(
            ["secid", "boardid", "engine", "market", "currencyid"],
            ["SYNTHB", "TQCB", "stock", "bonds", "RUB"],
        ),
    }
    with _client(stub) as client:
        result = client.discover_candidates(secid="SYNTHB")

    assert result.status is QuoteStatus.UNSUPPORTED
    assert result.candidates == ()


def test_discover_bond_f_filters_incompatible_faceunit_before_ambiguity() -> None:
    stub = IssStub()
    stub.payloads["/iss/securities/SYNTHB.json"] = {
        "description": _description(
            ("ISIN", "RU000SYNTH03"),
            ("TYPE", "exchange_bond"),
            ("GROUP", "stock_bonds"),
            ("QUOTEBASIS", "F"),
        ),
        "boards": _table(
            ["secid", "boardid", "engine", "market", "currencyid", "faceunit"],
            ["SYNTHB", "TQCB", "stock", "bonds", "RUB", "RUB"],
            ["SYNTHB", "TQOD", "stock", "bonds", "RUB", "USD"],
        ),
    }
    with _client(stub) as client:
        result = client.discover_candidates(secid="SYNTHB")

    assert result.status is QuoteStatus.OK
    assert len(result.candidates) == 1
    assert result.candidates[0].identity.boardid == "TQCB"


def test_discover_accepts_rur_as_rub_compatible() -> None:
    stub = IssStub()
    stub.payloads["/iss/securities/SYNTHS.json"] = _security_payload(
        secid="SYNTHS",
        kind_pairs=[
            ("ISIN", "RU000SYNTH01"),
            ("TYPE", "common_share"),
            ("GROUP", "stock_shares"),
            ("FACEUNIT", "RUR"),
        ],
        boards=[["SYNTHS", "TQBR", "stock", "shares", "RUR"]],
    )
    with _client(stub) as client:
        result = client.discover_candidates(secid="SYNTHS")

    assert result.status is QuoteStatus.OK
    assert len(result.candidates) == 1
    assert result.candidates[0].identity.boardid == "TQBR"


def test_ambiguous_boards_are_not_silently_selected() -> None:
    stub = IssStub()
    stub.payloads["/iss/securities/SYNTHS.json"] = _security_payload(
        secid="SYNTHS",
        kind_pairs=[
            ("ISIN", "RU000SYNTH01"),
            ("TYPE", "common_share"),
            ("GROUP", "stock_shares"),
        ],
        boards=[
            ["SYNTHS", "TQBR", "stock", "shares", "SUR"],
            ["SYNTHS", "TQTF", "stock", "shares", "SUR"],
        ],
    )
    with _client(stub) as client:
        result = client.discover_candidates(secid="SYNTHS")

    assert result.status is QuoteStatus.AMBIGUOUS
    assert {item.identity.boardid for item in result.candidates} == {"TQBR", "TQTF"}
    assert all(item.identity.secid == "SYNTHS" for item in result.candidates)


def test_unsupported_non_rub_semantics() -> None:
    stub = IssStub()
    usd = MarketIdentity(
        provider=MOEX_ISS_PROVIDER,
        engine="stock",
        market="shares",
        boardid="FQBR",
        secid="SYNTHX",
    )
    details = _security_payload(
        secid="SYNTHX",
        kind_pairs=[
            ("TYPE", "common_share"),
            ("GROUP", "stock_shares"),
            ("FACEUNIT", "USD"),
        ],
        boards=[["SYNTHX", "FQBR", "stock", "shares", "USD"]],
    )
    _put_identity(
        stub,
        usd,
        details,
        _market_payload(
            usd,
            last="10.00",
            last_date="2026-08-13",
            face_unit="USD",
            currency="USD",
        ),
    )
    with _client(stub) as client:
        result = client.fetch_quote(usd, TODAY)

    assert isinstance(result, QuoteFailure)
    assert result.status is QuoteStatus.UNSUPPORTED


def test_malformed_non_positive_quote() -> None:
    stub = IssStub()
    _put_identity(
        stub,
        STOCK,
        STOCK_DETAILS,
        _market_payload(STOCK, last="-1", last_date="2026-08-13"),
        _history_payload(STOCK, ("2026-08-12", "0")),
    )
    with _client(stub) as client:
        result = client.fetch_quote(STOCK, TODAY)

    assert isinstance(result, QuoteFailure)
    assert result.status is QuoteStatus.MALFORMED_RESPONSE


def test_timeout_is_deterministic_network_error() -> None:
    stub = IssStub()
    stub.errors["/iss/securities/SYNTHS.json"] = httpx2.ReadTimeout("timed out")
    with _client(stub) as client:
        result = client.fetch_quote(STOCK, TODAY)

    assert isinstance(result, QuoteFailure)
    assert result.status is QuoteStatus.NETWORK_ERROR


def test_partial_batch_keeps_successful_rows() -> None:
    stub = IssStub()
    _put_identity(
        stub,
        STOCK,
        STOCK_DETAILS,
        _market_payload(STOCK, last="50.00", last_date="2026-08-13"),
    )
    _put_identity(
        stub,
        FUND,
        FUND_DETAILS,
        _market_payload(FUND, last="8.00", last_date="2026-08-13"),
    )
    stub.errors[
        f"/iss/engines/{FUND.engine}/markets/{FUND.market}"
        f"/boards/{FUND.boardid}/securities/{FUND.secid}.json"
    ] = httpx2.ConnectError("offline")

    with _client(stub) as client:
        results = client.fetch_quotes([(STOCK, TODAY), (FUND, TODAY)])

    assert isinstance(results[0], QuoteSuccess)
    assert results[0].proposed_price_kopecks == 5000
    assert isinstance(results[1], QuoteFailure)
    assert results[1].status is QuoteStatus.NETWORK_ERROR
    assert len(results) == 2
