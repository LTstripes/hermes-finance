"""Pure domain liquid-capital calculator (framework-independent).

Implements MASTER_SPEC §10.1:

    liquid_assets =
        cash_balances
      + deposit_balances
      + securities_market_value
      + other_liquid_assets

    liquid_capital_net = liquid_assets - credit_card_debt - other_included_debts

Property and mortgage never enter ``liquid_capital_net``.
All money values use :class:`~hermes_finance.domain.values.RubleAmount`
(integer kopecks); binary ``float`` is never used.
"""

from __future__ import annotations

from dataclasses import dataclass

from hermes_finance.domain.values import RubleAmount


@dataclass(frozen=True, slots=True)
class AccountAmount:
    """A single account's contribution to liquid assets."""

    account_id: int
    amount: RubleAmount


@dataclass(frozen=True, slots=True)
class LinkedPairReadModel:
    """Presentation facts for one linked liquid account and credit-card debt.

    The account and debt amounts are already part of the canonical liquid
    capital totals.  ``net_contribution`` is therefore an attribution value
    for this pair, not an additional liquid-capital adjustment.
    """

    debt_id: int
    debt_name: str
    debt_type: str
    debt_balance: RubleAmount
    account_id: int
    account_name: str
    account_type: str
    account_balance: RubleAmount

    @property
    def net_contribution(self) -> RubleAmount:
        """Return the pair's economic contribution ``A - D`` exactly."""
        return RubleAmount(self.account_balance.kopecks - self.debt_balance.kopecks)


@dataclass(frozen=True, slots=True)
class LiquidCapitalClassBreakdown:
    """Breakdown of liquid assets by asset class."""

    cash: RubleAmount
    deposits: RubleAmount
    securities: RubleAmount
    other_liquid_assets: RubleAmount


@dataclass(frozen=True, slots=True)
class LiquidCapitalInput:
    """Pure-domain input for the liquid-capital calculator.

    All amounts are integer kopecks via :class:`RubleAmount`.
    ``other_liquid_assets`` defaults to zero because no separate
    table models it in the MVP; the field exists so future asset
    classes can plug in without changing the calculator signature.
    """

    cash: RubleAmount
    deposits: RubleAmount
    securities: RubleAmount
    included_debts: RubleAmount
    other_liquid_assets: RubleAmount = RubleAmount(0)
    deposit_accounts: tuple[AccountAmount, ...] = ()
    securities_accounts: tuple[AccountAmount, ...] = ()


@dataclass(frozen=True, slots=True)
class LiquidCapitalResult:
    """Pure-domain output of the liquid-capital calculator."""

    total_assets: RubleAmount
    total_debts_included: RubleAmount
    liquid_capital_net: RubleAmount
    breakdown: LiquidCapitalClassBreakdown
    accounts: tuple[AccountAmount, ...] = ()
    linked_pairs: tuple[LinkedPairReadModel, ...] = ()

    @property
    def linked_pair_assets(self) -> RubleAmount:
        """Return gross account-side amounts for linked pairs."""
        return RubleAmount(sum(item.account_balance.kopecks for item in self.linked_pairs))

    @property
    def linked_pair_debts(self) -> RubleAmount:
        """Return debt-side amounts for linked pairs without re-subtracting them."""
        return RubleAmount(sum(item.debt_balance.kopecks for item in self.linked_pairs))

    @property
    def linked_pair_net_contribution(self) -> RubleAmount:
        """Return the presentation-only sum of pair contributions ``A - D``."""
        return RubleAmount(sum(item.net_contribution.kopecks for item in self.linked_pairs))


def calculate_liquid_capital(input_data: LiquidCapitalInput) -> LiquidCapitalResult:
    """Calculate liquid capital from pure-domain input.

    No division, no float.  Zero data produces zero totals.
    A negative ``liquid_capital_net`` is allowed (debts exceed assets).
    """
    breakdown = LiquidCapitalClassBreakdown(
        cash=input_data.cash,
        deposits=input_data.deposits,
        securities=input_data.securities,
        other_liquid_assets=input_data.other_liquid_assets,
    )

    total_assets = RubleAmount(
        input_data.cash.kopecks
        + input_data.deposits.kopecks
        + input_data.securities.kopecks
        + input_data.other_liquid_assets.kopecks
    )

    liquid_capital_net = RubleAmount(total_assets.kopecks - input_data.included_debts.kopecks)

    # Merge per-account amounts (deposits + securities) by account_id.
    merged: dict[int, int] = {}
    for item in input_data.deposit_accounts:
        merged[item.account_id] = merged.get(item.account_id, 0) + item.amount.kopecks
    for item in input_data.securities_accounts:
        merged[item.account_id] = merged.get(item.account_id, 0) + item.amount.kopecks
    accounts = tuple(
        AccountAmount(account_id=aid, amount=RubleAmount(kop))
        for aid, kop in sorted(merged.items())
    )

    return LiquidCapitalResult(
        total_assets=total_assets,
        total_debts_included=input_data.included_debts,
        liquid_capital_net=liquid_capital_net,
        breakdown=breakdown,
        accounts=accounts,
    )
