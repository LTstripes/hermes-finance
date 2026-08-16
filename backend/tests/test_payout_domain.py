from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from hermes_finance.market_data.payout import (
    PayoutCoverage,
    PayoutDomainError,
    PayoutEvent,
    PayoutEventKind,
    PayoutEventStatus,
    PayoutIdentity,
    RUB_COMPATIBLE_UNITS,
    coverage_proves_event_absence,
    normalize_exact_decimal,
    normalize_payout_date,
    provider_event_fingerprint,
    provider_fingerprint_material,
    resolve_coupon_identity,
    resolve_dividend_identity,
    resolve_redemption_identity,
)
from hermes_finance.market_data.payout_protocol import (
    PayoutFailure,
    PayoutFetchRequest,
    PayoutFetchResult,
)


def _coupon_event(**overrides: object) -> PayoutEvent:
    values: dict[str, object] = {
        "provider": "t_invest",
        "instrument_uid": "33333333-3333-3333-3333-333333333333",
        "event_kind": PayoutEventKind.COUPON,
        "identity_key": "n:11",
        "status": PayoutEventStatus.OK,
        "payment_date": date(2026, 12, 2),
        "per_unit_amount": Decimal("35.400000000"),
        "currency": "rub",
        "source_method": "GetBondCoupons",
        "provider_filter_basis": "coupon_date",
        "provider_filter_date": date(2026, 12, 2),
        "provider_status": None,
    }
    values.update(overrides)
    return PayoutEvent(**values)


def test_coupon_identity_prefers_positive_number_over_mutable_dates() -> None:
    identity = resolve_coupon_identity(
        coupon_number="11",
        coupon_start_date=date(2026, 6, 3),
        coupon_end_date=date(2026, 12, 2),
        period_is_unique=False,
    )
    changed_dates = resolve_coupon_identity(
        coupon_number=11,
        coupon_start_date=date(2026, 6, 4),
        coupon_end_date=date(2026, 12, 3),
        period_is_unique=False,
    )
    assert identity.identity_key == "n:11"
    assert changed_dates.identity_key == "n:11"


def test_coupon_identity_uses_period_only_when_explicitly_proven_unique() -> None:
    ambiguous = resolve_coupon_identity(
        coupon_number=0,
        coupon_start_date=date(2026, 6, 3),
        coupon_end_date=date(2026, 12, 2),
        period_is_unique=False,
    )
    unique = resolve_coupon_identity(
        coupon_number=None,
        coupon_start_date=date(2026, 6, 3),
        coupon_end_date=date(2026, 12, 2),
        period_is_unique=True,
    )
    assert ambiguous.status is PayoutEventStatus.AMBIGUOUS_IDENTITY
    assert ambiguous.identity_key is None
    assert unique.identity_key == "p:2026-06-03:2026-12-02"


@pytest.mark.parametrize("bad_number", [True, "1.5", "+1", "x", 1.2])
def test_coupon_identity_rejects_malformed_numbers(bad_number: object) -> None:
    with pytest.raises(PayoutDomainError):
        resolve_coupon_identity(
            coupon_number=bad_number,  # type: ignore[arg-type]
            coupon_start_date=None,
            coupon_end_date=None,
            period_is_unique=False,
        )


def test_dividend_identity_uses_stable_provider_id_then_record_date() -> None:
    provider_id = resolve_dividend_identity(
        stable_provider_event_id="evt-42",
        record_date=date(2026, 5, 4),
        record_date_is_unique=False,
    )
    natural = resolve_dividend_identity(
        stable_provider_event_id=None,
        record_date=date(2026, 5, 4),
        record_date_is_unique=True,
    )
    assert provider_id.identity_key == "id:evt-42"
    assert natural.identity_key == "r:2026-05-04"


def test_dividend_record_date_collision_is_ambiguous() -> None:
    result = resolve_dividend_identity(
        stable_provider_event_id=None,
        record_date=date(2026, 5, 4),
        record_date_is_unique=False,
    )
    assert result.status is PayoutEventStatus.AMBIGUOUS_IDENTITY
    assert result.identity_key is None


def test_redemption_identity_never_synthesizes_from_maturity_or_amount() -> None:
    preferred = resolve_redemption_identity(
        event_number=1,
        event_date=date(2041, 5, 15),
        event_date_is_unique=False,
    )
    fallback = resolve_redemption_identity(
        event_number=0,
        event_date=date(2041, 5, 15),
        event_date_is_unique=True,
    )
    ambiguous = resolve_redemption_identity(
        event_number=None,
        event_date=None,
        event_date_is_unique=False,
    )
    assert preferred.identity_key == "mty:1"
    assert fallback.identity_key == "mty-date:2041-05-15"
    assert ambiguous.status is PayoutEventStatus.AMBIGUOUS_IDENTITY


def test_provider_timestamp_is_normalized_to_moscow_date_without_inventing_missing_date() -> None:
    assert normalize_payout_date(datetime(2026, 8, 16, 22, 30, tzinfo=timezone.utc)) == date(
        2026, 8, 17
    )
    assert normalize_payout_date(None) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("35.400000000"), Decimal("35.400000000")),
        ("35.400000000", Decimal("35.400000000")),
        (35, Decimal("35")),
    ],
)
def test_exact_decimal_inputs_remain_decimal(value: object, expected: Decimal) -> None:
    assert normalize_exact_decimal(value) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [35.4, True, "NaN", "Infinity", ""])
def test_amount_normalization_rejects_float_or_non_finite_values(value: object) -> None:
    with pytest.raises(PayoutDomainError):
        normalize_exact_decimal(value)  # type: ignore[arg-type]


def test_ok_event_requires_stable_identity_payment_date_amount_and_rub() -> None:
    event = _coupon_event()
    assert event.identity == PayoutIdentity(
        provider="t_invest",
        instrument_uid="33333333-3333-3333-3333-333333333333",
        event_kind=PayoutEventKind.COUPON,
        identity_key="n:11",
    )
    assert event.currency in RUB_COMPATIBLE_UNITS

    with pytest.raises(PayoutDomainError, match="payment_date"):
        _coupon_event(payment_date=None)
    with pytest.raises(PayoutDomainError, match="per_unit_amount"):
        _coupon_event(per_unit_amount=None)


def test_missing_payment_date_can_only_be_represented_as_non_ok_state() -> None:
    tentative = _coupon_event(status=PayoutEventStatus.TENTATIVE, payment_date=None)
    assert tentative.payment_date is None
    assert tentative.status is PayoutEventStatus.TENTATIVE


def test_non_rub_event_must_be_explicitly_unsupported() -> None:
    with pytest.raises(PayoutDomainError, match="non-RUB"):
        _coupon_event(currency="usd")
    unsupported = _coupon_event(status=PayoutEventStatus.UNSUPPORTED, currency="usd")
    assert unsupported.currency == "USD"


def test_binary_float_is_rejected_even_for_unsupported_event() -> None:
    with pytest.raises(PayoutDomainError, match="binary float"):
        _coupon_event(status=PayoutEventStatus.UNSUPPORTED, per_unit_amount=35.4)


def test_ambiguous_event_cannot_expose_an_identity_key() -> None:
    with pytest.raises(PayoutDomainError, match="ambiguous"):
        _coupon_event(status=PayoutEventStatus.AMBIGUOUS_IDENTITY)
    ambiguous = _coupon_event(
        status=PayoutEventStatus.AMBIGUOUS_IDENTITY,
        identity_key=None,
        payment_date=None,
        per_unit_amount=None,
        currency=None,
    )
    assert ambiguous.identity is None


def test_provider_filter_basis_and_date_are_atomic_metadata() -> None:
    with pytest.raises(PayoutDomainError, match="present together"):
        _coupon_event(provider_filter_date=None)


def test_coverage_requires_success_structural_validity_exact_method_basis_uid_and_window() -> None:
    event = _coupon_event()
    coverage = PayoutCoverage(
        provider="t_invest",
        method="GetBondCoupons",
        instrument_uid=event.instrument_uid,
        event_kind=PayoutEventKind.COUPON,
        requested_from=date(2026, 7, 18),
        requested_to=date(2027, 9, 21),
        provider_filter_basis="coupon_date",
        successful=True,
        structurally_valid=True,
    )
    assert coverage_proves_event_absence(event, coverage)
    assert not coverage_proves_event_absence(
        event, replace(coverage, successful=False, structurally_valid=False)
    )
    assert not coverage_proves_event_absence(event, replace(coverage, structurally_valid=False))
    with pytest.raises(PayoutDomainError, match="successful fetch"):
        replace(coverage, successful=False, structurally_valid=True)
    assert not coverage_proves_event_absence(event, replace(coverage, method="GetBondEvents"))
    assert not coverage_proves_event_absence(
        event, replace(coverage, event_kind=PayoutEventKind.REDEMPTION)
    )
    assert not coverage_proves_event_absence(
        event, replace(coverage, provider_filter_basis="record_date")
    )
    assert not coverage_proves_event_absence(
        event, replace(coverage, instrument_uid="11111111-1111-1111-1111-111111111111")
    )
    assert not coverage_proves_event_absence(
        event, replace(coverage, requested_to=date(2026, 12, 1))
    )


def test_dividend_coverage_uses_record_date_not_payment_date() -> None:
    dividend = PayoutEvent(
        provider="t_invest",
        instrument_uid="11111111-1111-1111-1111-111111111111",
        event_kind=PayoutEventKind.DIVIDEND,
        identity_key="r:2026-05-04",
        status=PayoutEventStatus.OK,
        payment_date=date(2026, 5, 19),
        per_unit_amount=Decimal("278"),
        currency="rub",
        source_method="GetDividends",
        provider_filter_basis="record_date",
        provider_filter_date=date(2026, 5, 4),
    )
    coverage = PayoutCoverage(
        provider="t_invest",
        method="GetDividends",
        instrument_uid=dividend.instrument_uid,
        event_kind=PayoutEventKind.DIVIDEND,
        requested_from=date(2026, 5, 1),
        requested_to=date(2026, 5, 10),
        provider_filter_basis="record_date",
        successful=True,
        structurally_valid=True,
    )
    assert dividend.payment_date == date(2026, 5, 19)
    assert coverage_proves_event_absence(dividend, coverage)


def test_missing_inference_is_false_without_provider_filter_metadata() -> None:
    event = _coupon_event(provider_filter_basis=None, provider_filter_date=None)
    coverage = PayoutCoverage(
        provider="t_invest",
        method="GetBondCoupons",
        instrument_uid=event.instrument_uid,
        event_kind=PayoutEventKind.COUPON,
        requested_from=date(2026, 1, 1),
        requested_to=date(2027, 1, 1),
        provider_filter_basis="coupon_date",
        successful=True,
        structurally_valid=True,
    )
    assert not coverage_proves_event_absence(event, coverage)


def test_fingerprint_uses_only_material_normalized_provider_fields() -> None:
    event = _coupon_event()
    same_numeric_value = _coupon_event(per_unit_amount=Decimal("35.40"))
    assert provider_event_fingerprint(event) == provider_event_fingerprint(same_numeric_value)
    assert provider_fingerprint_material(event).per_unit_amount == "35.4"

    assert provider_event_fingerprint(event) != provider_event_fingerprint(
        _coupon_event(payment_date=date(2026, 12, 3))
    )
    assert provider_event_fingerprint(event) != provider_event_fingerprint(
        _coupon_event(per_unit_amount=Decimal("35.41"))
    )
    assert provider_event_fingerprint(event) != provider_event_fingerprint(
        _coupon_event(provider_status="cancelled")
    )


def test_fingerprint_does_not_depend_on_coverage_request_shape() -> None:
    event = _coupon_event()
    changed_coverage_metadata = _coupon_event(
        source_method="SomeEquivalentMethod",
        provider_filter_basis="different_basis",
        provider_filter_date=date(2026, 11, 1),
    )
    assert provider_event_fingerprint(event) == provider_event_fingerprint(
        changed_coverage_metadata
    )


def test_fetch_request_is_date_bounded_and_failure_statuses_are_narrow() -> None:
    request = PayoutFetchRequest(
        instrument_uid="uid-1",
        calendar_from=date(2026, 8, 1),
        calendar_to=date(2027, 8, 1),
    )
    assert request.calendar_from < request.calendar_to
    with pytest.raises(ValueError):
        PayoutFetchRequest(
            instrument_uid="uid-1",
            calendar_from=date(2027, 8, 1),
            calendar_to=date(2026, 8, 1),
        )
    with pytest.raises(ValueError):
        PayoutFailure(PayoutEventStatus.OK, "not a failure")
    assert PayoutFailure(PayoutEventStatus.UNAVAILABLE, "provider unavailable").status is (
        PayoutEventStatus.UNAVAILABLE
    )


def test_fetch_result_rejects_cross_provider_or_cross_instrument_payloads() -> None:
    event = _coupon_event()
    coverage = PayoutCoverage(
        provider="t_invest",
        method="GetBondCoupons",
        instrument_uid=event.instrument_uid,
        event_kind=PayoutEventKind.COUPON,
        requested_from=date(2026, 7, 18),
        requested_to=date(2027, 9, 21),
        provider_filter_basis="coupon_date",
        successful=True,
        structurally_valid=True,
    )
    result = PayoutFetchResult(
        provider="t_invest",
        instrument_uid=event.instrument_uid,
        events=(event,),
        coverage=(coverage,),
    )
    assert result.events == (event,)

    with pytest.raises(PayoutDomainError, match="event from another"):
        PayoutFetchResult(
            provider="other",
            instrument_uid=event.instrument_uid,
            events=(event,),
        )
    with pytest.raises(PayoutDomainError, match="coverage from another"):
        PayoutFetchResult(
            provider="t_invest",
            instrument_uid="other-uid",
            coverage=(coverage,),
        )
