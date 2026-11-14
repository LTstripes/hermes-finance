"""Synthetic B9 scope, capital duration, source authority and cash signs."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest

from hermes_finance.services.portfolio_annual_return import Flow, History, calculate

START = date(2030, 1, 1)
END = START + timedelta(days=365)


def history(*, account_id=1, closing=11000, flows=None, **kwargs):
    return History(
        account_id,
        f"source:SYNTH-{account_id}",
        START,
        END,
        closing,
        tuple(flows if flows is not None else [Flow(START, 10000, account_id)]),
        **kwargs,
    )


def test_one_year_xirr_and_independent_manual_recalculation():
    result = calculate([history()])
    assert Decimal(result["rate"]["value"]) == pytest.approx(Decimal("0.1"))
    assert result["pnl"]["value"] == "1000"
    assert Decimal(result["weighted_holding_days"]) == 365
    with localcontext() as ctx:
        ctx.prec = 60
        rate = Decimal(result["rate"]["value"])
        assert abs(-Decimal(10000) + Decimal(11000) / (1 + rate)) < Decimal("1e-20")


def test_old_token_contribution_does_not_make_new_capital_a_year_old():
    value = history(flows=[Flow(START, 1, 1), Flow(END - timedelta(days=10), 9999, 1)])
    result = calculate([value])
    assert result["rate"]["value"] is None
    assert result["rate"]["reason_codes"] == ["overall_short_holding"]
    assert Decimal(result["weighted_holding_days"]) < 11
    assert result["pnl"]["value"] == "1000"  # P&L does not depend on annual eligibility.


def test_eligibility_compares_unrounded_duration():
    value = history(flows=[Flow(START, 999999, 1), Flow(START + timedelta(days=1), 1, 1)])
    assert calculate([value])["rate"]["value"] is None


def test_withdrawn_coupon_is_a_receipt_and_not_a_second_contribution():
    # All cash income retained inside the account is represented in closing.
    retained = history(closing=12100)
    # An income withdrawal to the bank is a positive investor receipt.
    withdrawn = history(closing=11000, flows=[Flow(START, 10000, 1), Flow(END, -1100, 1)])
    left, right = calculate([retained]), calculate([withdrawn])
    assert left["rate"]["value"] == right["rate"]["value"]
    assert left["pnl"]["value"] == right["pnl"]["value"] == "2100"


def test_fifo_withdrawals_keep_completed_capital_in_duration():
    value = history(
        closing=9000, flows=[Flow(START, 10000, 1), Flow(START + timedelta(days=100), -2000, 1)]
    )
    result = calculate([value])
    assert Decimal(result["weighted_holding_days"]) == 312
    assert result["rate"]["reason_codes"] == ["overall_short_holding"]
    assert result["pnl"]["value"] == "1000"


def test_explicit_internal_pair_is_excluded_from_portfolio_and_kept_for_account():
    a = history(
        closing=6600,
        flows=[Flow(START, 10000, 1), Flow(START + timedelta(days=100), -4000, 1, "transfer-1")],
    )
    b = history(
        account_id=2, closing=4400, flows=[Flow(START + timedelta(days=100), 4000, 2, "transfer-1")]
    )
    result = calculate([a, b])
    assert Decimal(result["rate"]["value"]) == pytest.approx(Decimal("0.1"))
    assert Decimal(result["weighted_holding_days"]) == 365
    assert result["pnl"]["value"] == "1000"
    assert calculate([b])["rate"]["reason_codes"] == ["overall_short_holding"]


@pytest.mark.parametrize("change", ["missing", "date", "amount", "account"])
def test_unpaired_or_conflicting_internal_transfer_never_yields_partial_xirr(change):
    a = history(flows=[Flow(START, 10000, 1), Flow(START + timedelta(days=10), -2000, 1, "pair")])
    other = Flow(START + timedelta(days=10), 2000, 2, "pair")
    if change == "date":
        other = replace(other, day=other.day + timedelta(days=1))
    if change == "amount":
        other = replace(other, amount=1999)
    if change == "account":
        other = replace(other, account_id=1)
    b = history(account_id=2, flows=[] if change == "missing" else [other])
    value = calculate([a, b])
    assert value["rate"]["value"] is value["pnl"]["value"] is None
    assert "overall_internal_transfer_unproven" in value["rate"]["reason_codes"]


@pytest.mark.parametrize(
    "reason",
    [
        "overall_source_proof_stale",
        "overall_external_flows_incomplete",
        "overall_inception_unproven",
    ],
)
def test_incomplete_account_blocks_whole_scope(reason):
    value = calculate([history(), history(account_id=2, reasons=(reason,))])
    assert value["rate"]["value"] is value["pnl"]["value"] is None
    assert reason in value["rate"]["reason_codes"]
    assert value["weighted_holding_days"] is None


def test_missing_or_different_valuation_date_blocks_total():
    for other in (
        history(account_id=2, closing=None),
        replace(history(account_id=2), valuation_date=END - timedelta(days=1)),
    ):
        value = calculate([history(), other])
        assert value["rate"]["value"] is value["pnl"]["value"] is None
        assert "overall_valuation_unavailable" in value["rate"]["reason_codes"]


def test_known_zero_pnl_and_rate_are_preserved():
    value = calculate([history(closing=10000)])
    assert value["pnl"]["value"] == "0"
    assert Decimal(value["rate"]["value"]) == 0


def test_no_accounts_is_unknown_not_zero():
    value = calculate([])
    assert value["rate"]["value"] is value["pnl"]["value"] is None


@pytest.fixture
def native_evidence(monkeypatch):
    """Synthetic retained native operands, with shared classification/total readers."""
    from types import SimpleNamespace

    from hermes_finance.services import portfolio_annual_evidence as evidence
    from hermes_finance.services import portfolio_annual_return as service
    from hermes_finance.services.source_monthly_returns import SourceReturnFlow

    document = {
        "money": [{"date": str(START)}],
        "positions": [],
        "rub_money": [
            {
                "source_account": "SYNTH",
                "currency": "RUB",
                "beginning_amount": "0",
                "ending_amount": "110",
            }
        ],
        "endpoint_basis": {"beginning_value": "previous_day_eod", "ending_value": "covered_to_eod"},
    }
    view = {
        "id": 1,
        "covered_from": str(START),
        "covered_to": str(END),
        "document": document,
        "money_classifications": [],
    }
    selected = [(SimpleNamespace(id=1), view, None)]
    state = SimpleNamespace(
        selected=selected,
        view=view,
        cancellations={},
        redemptions={},
        blockers=set(),
        gaps=[],
        rows=[
            (
                ("deposit", 0),
                SourceReturnFlow(
                    START, 10000, "assumed", True, ("money:1:deposit",), "external_deposit"
                ),
            )
        ],
    )
    monkeypatch.setattr(service, "_source_read_inputs", lambda *a: (state.selected, {"SYNTH"}))
    monkeypatch.setattr(evidence, "canonical_payout_groups", lambda *a: {})
    monkeypatch.setattr(evidence, "source_blockers", lambda *a: set(state.blockers))
    monkeypatch.setattr(evidence, "bound_import", lambda *a: None)
    monkeypatch.setattr(evidence, "resolve_proof", lambda *a: (state.cancellations, {}))
    monkeypatch.setattr(evidence, "_redemptions", lambda *a: state.redemptions)
    monkeypatch.setattr(evidence, "_inception_attested", lambda *a: True)

    def money(session, view, choices, gaps, **kwargs):
        gaps.extend(state.gaps)
        return [
            (key, flow)
            for key, flow in state.rows
            if any(ref.startswith(f"money:{view['id']}:") for ref in flow.source_references)
        ]

    monkeypatch.setattr(evidence, "_money", money)
    state.read = lambda: service._history(
        None, SimpleNamespace(id=1), {"scope": "source:SYNTH", "valuation_date": str(END)}
    )

    def add(
        amount,
        *,
        classification="unknown",
        operation="unrecognized",
        origin="default_rule",
        status="assumed",
    ):
        ref = "money:1:extra"
        state.rows.append(
            (
                ("extra", 0),
                SourceReturnFlow(
                    START,
                    amount,
                    status,
                    classification.startswith("external_"),
                    (ref,),
                    classification,
                ),
            )
        )
        view["money_classifications"].append(
            {
                "source_reference": ref,
                "operation": operation,
                "narrative": "Synthetic",
                "origin": origin,
                "status": status,
                "classification": classification,
            }
        )
        return ref

    state.add = add
    return state


def test_native_history_needs_no_legacy_economic_operands(native_evidence):
    value = calculate([native_evidence.read()])
    assert Decimal(value["rate"]["value"]) == pytest.approx(Decimal("0.1"))
    assert value["pnl"]["value"] == "1000"
    assert not value["rate"]["estimate"]


@pytest.mark.parametrize("amount", [1, -1, 9999, -9999])
def test_small_unknown_is_an_explicit_estimate_not_an_unreported_zero(native_evidence, amount):
    native_evidence.add(amount)
    value = calculate([native_evidence.read()])
    assert value["rate"]["value"] is not None
    assert value["rate"]["estimate"] and value["pnl"]["estimate"]
    assert value["rate"]["reason_codes"] == ["overall_small_unknown_assumed_internal"]


@pytest.mark.parametrize("amount", [10000, -10000, 200000])
def test_unknown_material_flow_stays_unknown(native_evidence, amount):
    native_evidence.add(amount)
    value = calculate([native_evidence.read()])
    assert value["rate"]["value"] is value["pnl"]["value"] is None
    assert "overall_external_flows_incomplete" in value["rate"]["reason_codes"]
    assert "overall_valuation_unavailable" not in value["rate"]["reason_codes"]


@pytest.mark.parametrize(
    "operation,amount",
    [("НДФЛ", -1), ("Комиссия", -20000), ("Купон", 20000), ("Проценты на остаток", 20000)],
)
def test_explicit_internal_source_operation_is_not_an_external_flow(
    native_evidence, operation, amount
):
    native_evidence.add(amount, operation=operation)
    h = native_evidence.read()
    assert len(h.flows) == 1
    assert not h.estimates and not h.reasons
    assert calculate([h])["pnl"]["value"] == "1000"


def test_confirmed_unknown_is_not_overridden_by_a_default_rule(native_evidence):
    native_evidence.add(10, operation="Купон", origin="user_choice", status="confirmed")
    assert native_evidence.read().estimates == ("overall_small_unknown_assumed_internal",)


def test_source_dividend_compensation_is_internal_without_instrument_attribution(native_evidence):
    native_evidence.add(25000, operation="Перевод")
    native_evidence.view["money_classifications"][-1]["narrative"] = (
        "Компенсация утраченных дивидендов по акциям SYNTH_1 дата фиксации реестра 01/01/2030."
    )
    h = native_evidence.read()
    assert not h.estimates and not h.reasons and len(h.flows) == 1


def test_invalid_decimal_is_unavailable_instead_of_an_http_failure(native_evidence):
    native_evidence.view["document"]["rub_money"][0]["beginning_amount"] = "invalid"
    value = calculate([native_evidence.read()])
    assert value["pnl"]["value"] is value["rate"]["value"] is None


def test_valuation_dates_must_agree_across_all_native_accounts():
    result = calculate(
        [history(), replace(history(account_id=2), valuation_date=END + timedelta(days=1))]
    )
    assert result["rate"]["value"] is result["pnl"]["value"] is None


@pytest.mark.parametrize(
    "classification,amount", [("external_deposit", 10000), ("external_withdrawal", -1000)]
)
def test_known_source_cash_directions_are_kept(native_evidence, classification, amount):
    native_evidence.add(amount, classification=classification)
    h = native_evidence.read()
    assert len(h.flows) == 2 and h.flows[1].amount == amount
    assert not h.estimates and not h.reasons


@pytest.mark.parametrize(
    "gap",
    [
        "nonzero",
        "missing_quantity",
        "missing_cash",
        "inferred_period",
        "unsupported",
        "source_error",
        "overlap_missing",
        "currency",
        "valuation",
    ],
)
def test_native_evidence_preserves_material_gaps(native_evidence, gap):
    state = native_evidence
    if gap == "nonzero":
        state.view["document"]["rub_money"][0]["beginning_amount"] = "1"
    elif gap == "missing_quantity":
        state.view["document"]["positions"] = [
            {
                "source_account": "SYNTH",
                "isin": "ZZ0000000001",
                "beginning_actual_quantity": None,
                "actual_quantity": "0",
                "beginning_value": "0",
                "ending_value": "0",
            }
        ]
    elif gap == "missing_cash":
        state.view["document"]["rub_money"][0]["beginning_amount"] = None
    elif gap == "inferred_period":
        state.view["document"]["warnings"] = ["period_inferred_from_content"]
    elif gap == "unsupported":
        state.blockers.add("unparsed_source_rows")
    elif gap == "source_error":
        state.selected.append((None, None, "source_reader_unavailable"))
    elif gap == "overlap_missing":
        state.selected.append((None, {**state.view, "id": 2}, None))
    elif gap == "currency":
        state.view["document"]["rub_money"][0]["currency"] = "USD"
    elif gap == "valuation":
        state.view["document"]["rub_money"][0]["ending_amount"] = None
    value = calculate([state.read()])
    assert value["pnl"]["value"] is value["rate"]["value"] is None


@pytest.mark.parametrize("proven", [True, False])
def test_clean_recognized_redemption_is_internal_only_with_exact_source_cash(
    native_evidence, monkeypatch, proven
):
    from types import SimpleNamespace

    from hermes_finance.services import source_redemption_evidence

    state = native_evidence
    ref = state.add(200000)
    state.cancellations = {1: (START.replace(day=1),)}
    if proven:
        state.redemptions[ref] = SimpleNamespace(
            event_key="redeemed",
            event_date=START,
            cash_legs=[SimpleNamespace(account_cash_kopecks=200000)],
        )
    monkeypatch.setattr(
        source_redemption_evidence, "_single_transfer", lambda *a: {"synthetic": "exact"}
    )
    h = state.read()
    value = calculate([h])
    if proven:
        assert len(h.flows) == 1 and not h.reasons and not h.estimates
        assert Decimal(value["rate"]["value"]) == pytest.approx(Decimal("0.1"))
    else:
        assert value["rate"]["value"] is value["pnl"]["value"] is None


def test_withdrawal_beyond_principal_does_not_invent_a_capital_lot():
    # The extra kopeck is withdrawn income: principal 10000 was held one day.
    h = history(flows=[Flow(START, 10000, 1), Flow(START + timedelta(days=1), -10001, 1)])
    value = calculate([h])
    assert Decimal(value["weighted_holding_days"]) == 1
    assert "overall_holding_period_unknown" not in value["rate"]["reason_codes"]


def test_persisted_native_history_preserves_unattested_inception_and_does_not_write(
    tmp_path, source_returns_database_factory, monkeypatch
):
    from test_source_monthly_returns_service import snapshot
    from test_statement_import_broker_statement_provisional import provisional_xml
    from test_statement_import_mybroker import ACCOUNT

    from hermes_finance.services import source_intake, source_investment_proofs
    from hermes_finance.services.portfolio_annual_evidence import read_native_history
    from hermes_finance.services.source_monthly_returns import (
        _source_read_inputs,
        source_read_snapshot,
    )

    db = source_returns_database_factory(tmp_path)
    try:
        xml = provisional_xml(
            beginning="0", beginning_quantity="0", closing="10211", rub=("0", "1000")
        )
        with db.session_factory() as session:
            source_intake.save_intake(
                session,
                document=xml,
                filename="Брокерский 1234567 (01.04.30-30.04.30).xml",
                request_id="synthetic-native-inception",
            )
        before = snapshot(db)

        def forbidden(*a, **k):
            raise AssertionError("native evidence must not revive an investment proof")

        monkeypatch.setattr(source_investment_proofs, "read_account_summaries", forbidden)
        monkeypatch.setattr(source_investment_proofs, "read_reports", forbidden)
        with db.session_factory() as session, source_read_snapshot(session):
            selected, native = _source_read_inputs(session, ACCOUNT)
            first, end, closing, flows, reasons, estimates = read_native_history(
                session, ACCOUNT, selected, native
            )
        assert first == date(2030, 4, 15)
        assert end == date(2030, 4, 30)
        assert closing == 1121100
        assert flows == ((date(2030, 4, 15), 100000),)
        assert reasons == {"overall_inception_unproven"} and not estimates
        assert snapshot(db) == before
    finally:
        db.engine.dispose()


@pytest.mark.parametrize(
    "change", [None, "seal", "identity", "nonzero", "first_before", "declaration"]
)
def test_inception_declaration_is_sealed_bound_and_not_a_balance_guess(monkeypatch, change):
    from types import SimpleNamespace

    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.portfolio_annual_evidence import _inception_attested

    plan = {
        "version": proofs.VERSION,
        "source_account": "SYNTH",
        "native_account": "SYNTH",
        "covered_from": str(START),
        "covered_to": str(END),
        "from_zero": change != "declaration",
        "intake_id": 1,
        "source_sha256": "synthetic-digest",
        "report": {},
        "native": {},
        "dependency": "old-economics-are-not-current",
    }
    row = SimpleNamespace(native_account="SYNTH", dependency_digest=proofs._evidence_digest(plan))
    if change == "seal":
        row.dependency_digest = "changed"
    view = {
        "id": 1,
        "covered_from": str(START),
        "covered_to": str(END),
        "document_sha256": "changed" if change == "identity" else "synthetic-digest",
        "document": {
            "positions": [],
            "rub_money": [
                {"currency": "RUB", "beginning_amount": "1" if change == "nonzero" else "0"}
            ],
        },
    }
    monkeypatch.setattr(proofs, "_report_rows", lambda *a: [(row, plan)])
    first = START - timedelta(days=1) if change == "first_before" else START
    assert _inception_attested(None, "SYNTH", [view], first) == (change is None)
