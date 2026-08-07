"""Unit tests for the pure liquid-capital calculator (no database)."""

from hermes_finance.domain import RubleAmount
from hermes_finance.domain.liquid_capital import (
    AccountAmount,
    LiquidCapitalInput,
    LiquidCapitalResult,
    calculate_liquid_capital,
)


def test_zero_input_returns_zero_result() -> None:
    result = calculate_liquid_capital(
        LiquidCapitalInput(
            cash=RubleAmount(0),
            deposits=RubleAmount(0),
            securities=RubleAmount(0),
            other_liquid_assets=RubleAmount(0),
            included_debts=RubleAmount(0),
        )
    )
    assert result.total_assets == RubleAmount(0)
    assert result.total_debts_included == RubleAmount(0)
    assert result.liquid_capital_net == RubleAmount(0)
    assert result.breakdown.cash == RubleAmount(0)
    assert result.breakdown.deposits == RubleAmount(0)
    assert result.breakdown.securities == RubleAmount(0)
    assert result.breakdown.other_liquid_assets == RubleAmount(0)
    assert result.accounts == ()


def test_sums_all_asset_classes_and_subtracts_debts() -> None:
    result = calculate_liquid_capital(
        LiquidCapitalInput(
            cash=RubleAmount(100_000),
            deposits=RubleAmount(500_000),
            securities=RubleAmount(300_000),
            other_liquid_assets=RubleAmount(50_000),
            included_debts=RubleAmount(200_000),
        )
    )
    assert result.total_assets == RubleAmount(950_000)
    assert result.total_debts_included == RubleAmount(200_000)
    assert result.liquid_capital_net == RubleAmount(750_000)


def test_other_liquid_assets_defaults_to_zero() -> None:
    result = calculate_liquid_capital(
        LiquidCapitalInput(
            cash=RubleAmount(100_000),
            deposits=RubleAmount(0),
            securities=RubleAmount(0),
            included_debts=RubleAmount(0),
        )
    )
    assert result.total_assets == RubleAmount(100_000)
    assert result.breakdown.other_liquid_assets == RubleAmount(0)


def test_negative_net_when_debts_exceed_assets() -> None:
    result = calculate_liquid_capital(
        LiquidCapitalInput(
            cash=RubleAmount(100_000),
            deposits=RubleAmount(0),
            securities=RubleAmount(0),
            included_debts=RubleAmount(350_000),
        )
    )
    assert result.liquid_capital_net == RubleAmount(-250_000)


def test_breakdown_by_class_matches_total_assets() -> None:
    result = calculate_liquid_capital(
        LiquidCapitalInput(
            cash=RubleAmount(100_000),
            deposits=RubleAmount(500_000),
            securities=RubleAmount(300_000),
            other_liquid_assets=RubleAmount(50_000),
            included_debts=RubleAmount(0),
        )
    )
    breakdown_sum = (
        result.breakdown.cash.kopecks
        + result.breakdown.deposits.kopecks
        + result.breakdown.securities.kopecks
        + result.breakdown.other_liquid_assets.kopecks
    )
    assert breakdown_sum == result.total_assets.kopecks


def test_per_account_breakdown_merges_deposit_and_securities() -> None:
    result = calculate_liquid_capital(
        LiquidCapitalInput(
            cash=RubleAmount(0),
            deposits=RubleAmount(500_000),
            securities=RubleAmount(300_000),
            included_debts=RubleAmount(0),
            deposit_accounts=(AccountAmount(account_id=1, amount=RubleAmount(500_000)),),
            securities_accounts=(
                AccountAmount(account_id=1, amount=RubleAmount(200_000)),
                AccountAmount(account_id=2, amount=RubleAmount(100_000)),
            ),
        )
    )
    accounts = dict((item.account_id, item.amount) for item in result.accounts)
    assert accounts[1] == RubleAmount(700_000)
    assert accounts[2] == RubleAmount(100_000)


def test_returns_liquid_capital_result_type() -> None:
    result = calculate_liquid_capital(
        LiquidCapitalInput(
            cash=RubleAmount(0),
            deposits=RubleAmount(0),
            securities=RubleAmount(0),
            included_debts=RubleAmount(0),
        )
    )
    assert isinstance(result, LiquidCapitalResult)
