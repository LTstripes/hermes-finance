from __future__ import annotations

import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from hermes_finance.domain import InstrumentType
from hermes_finance.market_data.dto import (
    T_INVEST_PROVIDER,
    DiscoverCandidate,
    DiscoverResult,
    MarketIdentity,
    QuoteStatus,
)
from hermes_finance.market_data.payout import PayoutEventKind, PayoutEventStatus
from hermes_finance.market_data.payout_protocol import PayoutFetchRequest
from hermes_finance.market_data.t_invest import _AuthUnavailable
from hermes_finance.market_data.t_invest_payout import TInvestPayoutProvider

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "t_invest" / "official_payout_shape.json"
_BOND_UID = "33333333-3333-3333-3333-333333333333"
_STOCK_UID = "11111111-1111-1111-1111-111111111111"


def _fixture() -> dict[str, object]:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


class _FakeClient:
    def __init__(
        self,
        kind: InstrumentType,
        payloads: dict[str, object],
        *,
        bond_flags: dict[str, object] | None = None,
    ) -> None:
        self.kind = kind
        self.payloads = payloads
        self.bond_flags = {
            "floatingCouponFlag": False,
            "amortizationFlag": False,
            "perpetualFlag": False,
            **(bond_flags or {}),
        }
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.discover_calls: list[str] = []

    def discover_candidates(
        self,
        *,
        query: str | None = None,
        provider_instrument_id: str | None = None,
        isin: str | None = None,
    ) -> DiscoverResult:
        del query, isin
        assert provider_instrument_id is not None
        self.discover_calls.append(provider_instrument_id)
        return DiscoverResult(
            status=QuoteStatus.OK,
            candidates=(
                DiscoverCandidate(
                    identity=MarketIdentity(
                        provider=T_INVEST_PROVIDER,
                        provider_instrument_id=provider_instrument_id,
                        provider_venue_id=None,
                    ),
                    instrument_kind=self.kind,
                ),
            ),
        )

    def _bond_by_uid(self, uid: str) -> dict[str, object]:
        assert uid == _BOND_UID
        return copy.deepcopy(self.bond_flags)

    def request_payout_method(self, method: str, body: dict[str, object]) -> dict[str, object]:
        self.calls.append((method, copy.deepcopy(body)))
        value = self.payloads[method]
        if isinstance(value, Exception):
            raise value
        assert isinstance(value, dict)
        return copy.deepcopy(value)


def _bond_client(
    *,
    coupons: object | None = None,
    events: object | None = None,
    bond_flags: dict[str, object] | None = None,
) -> _FakeClient:
    fixture = _fixture()
    bond = fixture["ordinary_bond"]
    assert isinstance(bond, dict)
    return _FakeClient(
        InstrumentType.BOND,
        {
            "GetBondCoupons": coupons if coupons is not None else bond["GetBondCoupons"],
            "GetBondEvents": events if events is not None else bond["GetBondEventsMty"],
        },
        bond_flags=bond_flags,
    )


def _stock_client(dividends: object | None = None) -> _FakeClient:
    fixture = _fixture()
    stock = fixture["stock"]
    assert isinstance(stock, dict)
    return _FakeClient(
        InstrumentType.STOCK,
        {"GetDividends": dividends if dividends is not None else stock["GetDividends"]},
    )


def test_bond_fixture_maps_coupon_and_mty_without_cpn_double_import() -> None:
    client = _bond_client()
    result = TInvestPayoutProvider(client).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_BOND_UID,
            calendar_from=date(2026, 7, 1),
            calendar_to=date(2041, 5, 15),
        )
    )

    assert result.failures == ()
    assert [(event.event_kind, event.identity_key) for event in result.events] == [
        (PayoutEventKind.COUPON, "n:11"),
        (PayoutEventKind.COUPON, "n:12"),
        (PayoutEventKind.REDEMPTION, "mty:1"),
    ]
    assert [event.per_unit_amount for event in result.events] == [
        Decimal("35.400000000"),
        Decimal("35.400000000"),
        Decimal("1000"),
    ]
    assert all(event.currency == "RUB" for event in result.events)
    assert [method for method, _ in client.calls] == ["GetBondCoupons", "GetBondEvents"]
    assert client.calls[1][1]["type"] == "EVENT_TYPE_MTY"
    assert "EVENT_TYPE_CPN" not in repr(client.calls)

    coupon_coverage, redemption_coverage = result.coverage
    assert coupon_coverage.event_kind is PayoutEventKind.COUPON
    assert coupon_coverage.provider_filter_basis == "coupon_date"
    assert coupon_coverage.successful and coupon_coverage.structurally_valid
    assert redemption_coverage.event_kind is PayoutEventKind.REDEMPTION
    assert redemption_coverage.provider_filter_basis == "event_date"
    assert redemption_coverage.successful and redemption_coverage.structurally_valid


def test_empty_mty_does_not_synthesize_redemption_from_reference_maturity() -> None:
    client = _bond_client(coupons={"events": []}, events={"events": []})
    result = TInvestPayoutProvider(client).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_BOND_UID,
            calendar_from=date(2041, 5, 1),
            calendar_to=date(2041, 5, 31),
        )
    )
    assert result.events == ()
    assert result.failures == ()
    assert all(item.structurally_valid for item in result.coverage)


def test_floating_bond_coupon_is_conservatively_tentative_even_with_positive_amount() -> None:
    client = _bond_client(
        events={"events": []},
        bond_flags={"floatingCouponFlag": True},
    )
    result = TInvestPayoutProvider(client).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_BOND_UID,
            calendar_from=date(2026, 7, 1),
            calendar_to=date(2027, 7, 1),
        )
    )
    coupons = [event for event in result.events if event.event_kind is PayoutEventKind.COUPON]
    assert coupons
    assert all(event.status is PayoutEventStatus.TENTATIVE for event in coupons)


def test_amortizing_or_multiple_mty_remains_tentative() -> None:
    fixture = _fixture()
    bond = fixture["ordinary_bond"]
    assert isinstance(bond, dict)
    source = bond["GetBondEventsMty"]
    assert isinstance(source, dict)
    rows = source["events"]
    assert isinstance(rows, list)
    first = copy.deepcopy(rows[0])
    second = copy.deepcopy(rows[0])
    assert isinstance(first, dict) and isinstance(second, dict)
    second["eventNumber"] = 2
    second["eventDate"] = "2041-06-15T00:00:00Z"
    second["payDate"] = "2041-06-15T00:00:00Z"

    amortizing = _bond_client(
        coupons={"events": []},
        events={"events": [first]},
        bond_flags={"amortizationFlag": True},
    )
    amortizing_result = TInvestPayoutProvider(amortizing).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_BOND_UID,
            calendar_from=date(2041, 5, 1),
            calendar_to=date(2041, 6, 30),
        )
    )
    assert amortizing_result.events[0].status is PayoutEventStatus.TENTATIVE

    multiple = _bond_client(coupons={"events": []}, events={"events": [first, second]})
    multiple_result = TInvestPayoutProvider(multiple).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_BOND_UID,
            calendar_from=date(2041, 5, 1),
            calendar_to=date(2041, 6, 30),
        )
    )
    assert len(multiple_result.events) == 2
    assert all(event.status is PayoutEventStatus.TENTATIVE for event in multiple_result.events)


def test_missing_mty_pay_date_is_tentative_and_not_replaced_by_event_date() -> None:
    fixture = _fixture()
    bond = fixture["ordinary_bond"]
    assert isinstance(bond, dict)
    source = bond["GetBondEventsMty"]
    assert isinstance(source, dict)
    rows = source["events"]
    assert isinstance(rows, list)
    row = copy.deepcopy(rows[0])
    assert isinstance(row, dict)
    row.pop("payDate")
    client = _bond_client(coupons={"events": []}, events={"events": [row]})
    result = TInvestPayoutProvider(client).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_BOND_UID,
            calendar_from=date(2041, 5, 1),
            calendar_to=date(2041, 5, 31),
        )
    )
    assert result.events[0].status is PayoutEventStatus.TENTATIVE
    assert result.events[0].payment_date is None
    assert result.events[0].provider_filter_date == date(2041, 5, 15)


def test_dividend_fixture_uses_payment_date_for_calendar_and_record_date_for_coverage() -> None:
    client = _stock_client()
    result = TInvestPayoutProvider(client).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_STOCK_UID,
            calendar_from=date(2026, 5, 1),
            calendar_to=date(2026, 5, 31),
        )
    )

    assert result.failures == ()
    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_kind is PayoutEventKind.DIVIDEND
    assert event.identity_key == "r:2026-05-04"
    assert event.payment_date == date(2026, 5, 19)
    assert event.provider_filter_date == date(2026, 5, 4)
    assert event.provider_filter_basis == "record_date"
    assert event.per_unit_amount == Decimal("278")
    assert event.status is PayoutEventStatus.OK

    coverage = result.coverage[0]
    assert coverage.requested_from < date(2026, 5, 1)
    assert coverage.requested_to > date(2026, 5, 31)
    assert coverage.provider_filter_basis == "record_date"
    assert coverage.event_kind is PayoutEventKind.DIVIDEND
    assert [method for method, _ in client.calls] == ["GetDividends"]


def test_missing_dividend_payment_date_is_tentative_and_never_invented() -> None:
    fixture = _fixture()
    stock = fixture["stock"]
    assert isinstance(stock, dict)
    payload = copy.deepcopy(stock["GetDividends"])
    assert isinstance(payload, dict)
    rows = payload["dividends"]
    assert isinstance(rows, list)
    row = copy.deepcopy(rows[0])
    assert isinstance(row, dict)
    row.pop("paymentDate")
    client = _stock_client({"dividends": [row]})

    result = TInvestPayoutProvider(client).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_STOCK_UID,
            calendar_from=date(2026, 5, 1),
            calendar_to=date(2026, 5, 31),
        )
    )
    assert result.failures == ()
    assert len(result.events) == 1
    event = result.events[0]
    assert event.status is PayoutEventStatus.TENTATIVE
    assert event.payment_date is None
    assert event.identity_key == "r:2026-05-04"


def test_dividend_record_date_collision_stays_ambiguous() -> None:
    fixture = _fixture()
    stock = fixture["stock"]
    assert isinstance(stock, dict)
    source = stock["GetDividends"]
    assert isinstance(source, dict)
    rows = source["dividends"]
    assert isinstance(rows, list)
    first = copy.deepcopy(rows[0])
    second = copy.deepcopy(rows[0])
    assert isinstance(first, dict) and isinstance(second, dict)
    second["dividendNet"] = {"units": "279", "nano": 0, "currency": "rub"}
    client = _stock_client({"dividends": [first, second]})

    result = TInvestPayoutProvider(client).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_STOCK_UID,
            calendar_from=date(2026, 5, 1),
            calendar_to=date(2026, 5, 31),
        )
    )
    assert len(result.events) == 2
    assert all(event.status is PayoutEventStatus.AMBIGUOUS_IDENTITY for event in result.events)
    assert all(event.identity_key is None for event in result.events)


def test_empty_list_is_valid_coverage_but_malformed_shape_is_not() -> None:
    empty = _stock_client({"dividends": []})
    empty_result = TInvestPayoutProvider(empty).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_STOCK_UID,
            calendar_from=date(2031, 8, 1),
            calendar_to=date(2031, 10, 31),
        )
    )
    assert empty_result.events == ()
    assert empty_result.failures == ()
    assert empty_result.coverage[0].successful
    assert empty_result.coverage[0].structurally_valid

    malformed = _stock_client({"dividends": {}})
    malformed_result = TInvestPayoutProvider(malformed).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_STOCK_UID,
            calendar_from=date(2031, 8, 1),
            calendar_to=date(2031, 10, 31),
        )
    )
    assert malformed_result.events == ()
    assert len(malformed_result.failures) == 1
    assert malformed_result.coverage[0].successful
    assert not malformed_result.coverage[0].structurally_valid


def test_zero_coupon_is_tentative_and_non_rub_coupon_is_unsupported() -> None:
    fixture = _fixture()
    bond = fixture["ordinary_bond"]
    assert isinstance(bond, dict)
    source = bond["GetBondCoupons"]
    assert isinstance(source, dict)
    rows = source["events"]
    assert isinstance(rows, list)
    zero = copy.deepcopy(rows[0])
    foreign = copy.deepcopy(rows[1])
    assert isinstance(zero, dict) and isinstance(foreign, dict)
    zero["payOneBond"] = {"units": "0", "nano": 0, "currency": "rub"}
    foreign["payOneBond"] = {"units": "35", "nano": 0, "currency": "usd"}
    client = _bond_client(coupons={"events": [zero, foreign]}, events={"events": []})

    result = TInvestPayoutProvider(client).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_BOND_UID,
            calendar_from=date(2026, 7, 1),
            calendar_to=date(2027, 7, 1),
        )
    )
    assert [event.status for event in result.events] == [
        PayoutEventStatus.TENTATIVE,
        PayoutEventStatus.UNSUPPORTED,
    ]
    assert result.events[0].per_unit_amount == Decimal("0")
    assert result.events[1].currency == "USD"


def test_cancelled_dividend_signal_is_preserved_but_not_interpreted_as_final_lifecycle() -> None:
    fixture = _fixture()
    stock = fixture["stock"]
    assert isinstance(stock, dict)
    source = stock["GetDividends"]
    assert isinstance(source, dict)
    rows = source["dividends"]
    assert isinstance(rows, list)
    row = copy.deepcopy(rows[0])
    assert isinstance(row, dict)
    row["dividendType"] = "Cancelled"
    client = _stock_client({"dividends": [row]})

    result = TInvestPayoutProvider(client).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_STOCK_UID,
            calendar_from=date(2026, 5, 1),
            calendar_to=date(2026, 5, 31),
        )
    )
    assert result.events[0].status is PayoutEventStatus.TENTATIVE
    assert result.events[0].provider_status == "Cancelled"


def test_malformed_row_keeps_valid_rows_but_disables_missing_inference_coverage() -> None:
    fixture = _fixture()
    bond = fixture["ordinary_bond"]
    assert isinstance(bond, dict)
    source = bond["GetBondCoupons"]
    assert isinstance(source, dict)
    rows = source["events"]
    assert isinstance(rows, list)
    client = _bond_client(
        coupons={"events": [copy.deepcopy(rows[0]), "bad"]},
        events={"events": []},
    )

    result = TInvestPayoutProvider(client).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_BOND_UID,
            calendar_from=date(2026, 7, 1),
            calendar_to=date(2026, 12, 31),
        )
    )
    coupons = [event for event in result.events if event.event_kind is PayoutEventKind.COUPON]
    assert len(coupons) == 1
    assert len(result.failures) == 1
    coupon_coverage = next(
        item for item in result.coverage if item.event_kind is PayoutEventKind.COUPON
    )
    assert coupon_coverage.successful
    assert not coupon_coverage.structurally_valid


def test_auth_failure_is_sanitized_and_marks_unsuccessful_coverage() -> None:
    client = _bond_client(coupons=_AuthUnavailable(), events={"events": []})
    result = TInvestPayoutProvider(client).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_BOND_UID,
            calendar_from=date(2026, 7, 1),
            calendar_to=date(2026, 12, 31),
        )
    )
    assert result.failures[0].status is PayoutEventStatus.UNAVAILABLE
    assert "token" in result.failures[0].message.lower()
    coupon_coverage = next(
        item for item in result.coverage if item.event_kind is PayoutEventKind.COUPON
    )
    assert not coupon_coverage.successful
    assert not coupon_coverage.structurally_valid


def test_invalid_uid_fails_before_discovery_or_payout_calls() -> None:
    client = _stock_client({"dividends": []})
    result = TInvestPayoutProvider(client).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid="not-a-uuid",
            calendar_from=date(2026, 5, 1),
            calendar_to=date(2026, 5, 31),
        )
    )
    assert result.failures[0].status is PayoutEventStatus.ERROR
    assert client.discover_calls == []
    assert client.calls == []
