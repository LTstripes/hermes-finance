from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from hermes_finance.market_data import (
    IsinMismatchError,
    MarketDataStatus,
    MarketIdentity,
    MoexIssClient,
    MoexQuoteKind,
    RawPriceBasis,
    parse_candidate_payload,
    parse_iss_table,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def table(columns: list[str], rows: list[list[object]]) -> dict[str, object]:
    return {"columns": columns, "data": rows}


def market_payload(*, last: object = "123.45", trade_date: str = "2026-08-13") -> dict[str, object]:
    return {
        "marketdata": table(
            ["SECID", "BOARDID", "LAST", "TRADEDATE", "CURRENCYID"],
            [["SYN", "TQBR", last, trade_date, "RUB"]],
        )
    }


def history_payload(rows: list[list[object]], *, bond: bool = False) -> dict[str, object]:
    columns = ["SECID", "BOARDID", "TRADEDATE", "LASTPRICE" if bond else "CLOSE", "CURRENCYID"]
    return {"history": table(columns, rows)}


def identity(
    kind: str = "stock", *, basis: str | None = "R", face: str | None = None
) -> MarketIdentity:
    return MarketIdentity(
        provider="moex_iss",
        engine="stock",
        market="bonds" if kind == "bond" else "shares",
        boardid="TQBR" if kind != "bond" else "TQCB",
        secid="SYN",
        instrument_kind=kind,
        isin="RU000SYNTH01",
        quote_basis=basis,
        quote_currency="RUB",
        face_value=Decimal(face) if face else None,
        face_currency="RUB" if face else None,
    )


class FakeTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[str, float]] = []

    def __call__(self, url: str, timeout: float) -> object:
        self.calls.append((url, timeout))
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response


def client(*responses: object, max_concurrency: int = 2) -> tuple[MoexIssClient, FakeTransport]:
    transport = FakeTransport(list(responses))
    return (
        MoexIssClient(
            transport=transport,
            max_concurrency=max_concurrency,
            clock=lambda: NOW,
        ),
        transport,
    )


def test_iss_parser_uses_column_names_and_rejects_wrong_width() -> None:
    assert parse_iss_table({"quote": table(["B", "A"], [[2, 1]])}, "quote") == [{"B": 2, "A": 1}]
    with pytest.raises(Exception, match="wrong width"):
        parse_iss_table({"quote": table(["A"], [[1, 2]])}, "quote")


def test_stock_and_fund_are_exact_rub_per_unit_kopecks() -> None:
    stock_client, _ = client(market_payload(last="123.456"))
    fund_client, _ = client(market_payload(last="9.995"))
    stock = stock_client.fetch_quote(identity("stock"), date(2026, 8, 13), now=NOW)
    fund = fund_client.fetch_quote(identity("fund"), date(2026, 8, 13), now=NOW)
    assert (stock.status, stock.proposed_price_kopecks) == (MarketDataStatus.OK, 12_346)
    assert (fund.status, fund.proposed_price_kopecks) == (MarketDataStatus.OK, 1_000)


def test_bond_percent_of_face_uses_decimal_round_half_up() -> None:
    moex, _ = client(
        {
            "marketdata": table(
                ["SECID", "BOARDID", "LAST", "TRADEDATE", "QUOTEBASIS", "FACEVALUE", "FACEUNIT"],
                [["SYN", "TQCB", "97.25", "2026-08-13", "F", "1000.00", "RUB"]],
            )
        }
    )
    result = moex.fetch_quote(
        identity("bond", basis="F", face="1000.00"), date(2026, 8, 13), now=NOW
    )
    assert (result.raw_price_basis, result.proposed_price_kopecks) == (
        RawPriceBasis.PERCENT_OF_FACE,
        97_250,
    )


def test_bond_cash_basis_does_not_apply_face_conversion() -> None:
    moex, _ = client(
        {
            "marketdata": table(
                ["SECID", "BOARDID", "LAST", "TRADEDATE", "QUOTEBASIS", "CURRENCYID"],
                [["SYN", "TQCB", "972.50", "2026-08-13", "R", "RUB"]],
            )
        }
    )
    result = moex.fetch_quote(
        identity("bond", basis="R", face="1000.00"), date(2026, 8, 13), now=NOW
    )
    assert (result.raw_price_basis, result.proposed_price_kopecks) == (
        RawPriceBasis.CASH_PER_UNIT,
        97_250,
    )


def test_missing_current_last_falls_back_to_prior_valid_result() -> None:
    moex, _ = client(
        market_payload(last=None),
        history_payload([["SYN", "TQBR", "2026-08-12", "123.45", "RUB"]]),
    )
    result = moex.fetch_quote(identity(), date(2026, 8, 13), now=NOW)
    assert (result.status, result.quote_kind, result.price_date) == (
        MarketDataStatus.OK,
        MoexQuoteKind.HISTORICAL_RESULT,
        date(2026, 8, 12),
    )


@pytest.mark.parametrize(
    ("trade_date", "expected"),
    [("2026-08-07", MarketDataStatus.OK), ("2026-08-01", MarketDataStatus.STALE)],
)
def test_freshness_uses_actual_prior_trade_date(
    trade_date: str, expected: MarketDataStatus
) -> None:
    moex, _ = client(market_payload(last="100", trade_date=trade_date))
    result = moex.fetch_quote(identity(), date(2026, 8, 13), now=NOW)
    assert (result.status, result.price_date) == (expected, date.fromisoformat(trade_date))


def test_no_valid_quote_in_30_days_is_unavailable() -> None:
    moex, _ = client(market_payload(last=None), history_payload([]))
    result = moex.fetch_quote(identity(), date(2026, 8, 13), now=NOW)
    assert result.status == MarketDataStatus.UNAVAILABLE
    assert result.proposed_price_kopecks is None


def test_isin_mismatch_is_hard_rejection() -> None:
    payload = {
        "securities": table(["SECID", "ISIN"], [["SYN", "RU000OTHER01"]]),
        "boards": table(
            ["SECID", "BOARDID", "ENGINE", "MARKET"], [["SYN", "TQBR", "stock", "shares"]]
        ),
    }
    with pytest.raises(IsinMismatchError):
        parse_candidate_payload(payload, expected_isin="RU000SYNTH01")


def test_ambiguous_boards_are_preserved() -> None:
    payload = {
        "securities": table(["SECID", "ISIN", "CURRENCYID"], [["SYN", "RU000SYNTH01", "RUB"]]),
        "boards": table(
            ["SECID", "BOARDID", "ENGINE", "MARKET"],
            [["SYN", "TQBR", "stock", "shares"], ["SYN", "TQTF", "stock", "shares"]],
        ),
    }
    result = parse_candidate_payload(payload)
    assert (result.status, [candidate.boardid for candidate in result.candidates]) == (
        MarketDataStatus.AMBIGUOUS,
        ["TQBR", "TQTF"],
    )


def test_unsupported_non_rub_and_malformed_quotes() -> None:
    non_rub, _ = client(
        {
            "marketdata": table(
                ["SECID", "BOARDID", "LAST", "TRADEDATE", "CURRENCYID"],
                [["SYN", "TQBR", "10", "2026-08-13", "USD"]],
            )
        }
    )
    malformed, _ = client(market_payload(last="0"))
    assert (
        non_rub.fetch_quote(identity(), date(2026, 8, 13), now=NOW).status
        == MarketDataStatus.UNSUPPORTED
    )
    assert (
        malformed.fetch_quote(identity(), date(2026, 8, 13), now=NOW).status
        == MarketDataStatus.MALFORMED_RESPONSE
    )


def test_timeout_becomes_deterministic_network_error() -> None:
    moex, transport = client(TimeoutError("synthetic timeout"))
    result = moex.fetch_quote(identity(), date(2026, 8, 13), now=NOW)
    assert result.status == MarketDataStatus.NETWORK_ERROR
    assert transport.calls and transport.calls[0][1] <= 7.0


def test_partial_batch_keeps_success_when_another_identity_fails() -> None:
    moex, _ = client(
        market_payload(last="10"), TimeoutError("synthetic timeout"), max_concurrency=1
    )
    result = moex.fetch_quotes([identity(), identity("fund")], date(2026, 8, 13), now=NOW)
    assert [item.status for item in result.results] == [
        MarketDataStatus.OK,
        MarketDataStatus.NETWORK_ERROR,
    ]
