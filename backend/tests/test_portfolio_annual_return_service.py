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


@pytest.mark.parametrize(
    "gap", [None, "stale", "missing_flow", "nonzero_opening", "transfer", "total_mismatch"]
)
def test_source_adapter_requires_current_complete_from_zero_evidence(monkeypatch, gap):
    from types import SimpleNamespace

    from hermes_finance.services import portfolio_annual_return as service

    proof = {
        "proof_id": 1,
        "history_from_zero": True,
        "covered_from": str(START),
        "covered_to": str(END),
        "status": "current",
        "interval": {
            "pnl": {"value": "1000"},
            "opening_kopecks": "0",
            "closing_kopecks": "11000",
            "contributions_kopecks": "10000",
            "withdrawals_kopecks": "0",
            "external_flows": [
                {"date": str(START), "amount_kopecks": "10000", "status": "confirmed"}
            ],
        },
    }
    if gap == "stale":
        proof["status"] = "stale"
    if gap == "missing_flow":
        del proof["interval"]["external_flows"]
    if gap == "nonzero_opening":
        proof["interval"]["opening_kopecks"] = "1"
    if gap == "total_mismatch":
        proof["interval"]["contributions_kopecks"] = "10001"
    monkeypatch.setattr(
        service.source_investment_proofs, "read_account_summaries", lambda *a, **kw: [proof]
    )
    monkeypatch.setattr(service.source_investment_proofs, "read_reports", lambda *a, **kw: [proof])
    monkeypatch.setattr(
        service, "read_monthly_for_card_history", lambda *a, **kw: SimpleNamespace(months=[])
    )
    selected = (
        [(None, {"document": {"money": [{"date": str(START)}]}, "money_classifications": []}, None)]
        if gap != "transfer"
        else [
            (
                None,
                {
                    "document": {"money": [{"date": str(START)}]},
                    "money_classifications": [
                        {
                            "classification": "internal_transfer",
                            "operation": "internal transfer",
                            "narrative": "unpaired",
                        }
                    ],
                },
                None,
            )
        ]
    )
    monkeypatch.setattr(service, "_source_read_inputs", lambda *a: (selected, None))
    h = service._history(
        None, SimpleNamespace(id=1), {"scope": "source:SYNTH", "valuation_date": str(END)}
    )
    result = calculate([h])
    if gap is None:
        assert Decimal(result["rate"]["value"]) == pytest.approx(Decimal("0.1"))
    else:
        assert result["rate"]["value"] is result["pnl"]["value"] is None
