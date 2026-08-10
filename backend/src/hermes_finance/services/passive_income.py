"""ORM application service for actual net passive income (C02).

Loads persisted rows for a reporting month, maps them into the pure
domain calculator input, and returns the domain result DTO.  No API,
no Pydantic, no React.

Implements MASTER_SPEC §10.4:

    actual_net_passive_income =
        deposit_interest_net
      + bond_coupons_net
      + dividends_net
      + other_capital_income_net

Key invariants (wiki §7):
- Deposit actual interest comes ONLY from ``deposit_snapshots.actual_interest_received``.
- ``net_amount`` already includes tax/commission; never subtract them again.
- Cashback is never passive income.
- Reads are allowed on closed months (B19-R2 guard is for writes only).

Income entries (IncomeEntry) with ``include_in_passive_income=True`` and
``income_type != CASHBACK`` contribute to ``other_capital_income``.
SALARY/BONUS/SIDE_INCOME/OTHER do not fit the deposit-interest, bond-coupon
or dividend buckets, so they fall into the fourth bucket per MASTER_SPEC.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain.passive_income import (
    PassiveIncomeInput,
    PassiveIncomeResult,
    PassiveIncomeSource,
    PassiveIncomeSourceBucket,
    calculate_passive_income,
    classify_flow_type,
)
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import Account, DepositSnapshot, IncomeEntry, InvestmentCashFlow


def passive_income_for_month(session: Session, reporting_month_id: int) -> PassiveIncomeResult:
    """Assemble passive-income input from the database and calculate."""
    sources: list[PassiveIncomeSource] = []

    # --- Deposit interest: only from deposit_snapshots.actual_interest_received ---
    deposit_rows = session.execute(
        select(
            DepositSnapshot.id,
            DepositSnapshot.account_id,
            DepositSnapshot.actual_interest_received_kopecks,
        ).where(
            DepositSnapshot.reporting_month_id == reporting_month_id,
            DepositSnapshot.actual_interest_received_kopecks > 0,
        )
    ).all()

    deposit_interest_kopecks = 0
    for snap_id, account_id, interest_kop in deposit_rows:
        kop = int(interest_kop or 0)
        deposit_interest_kopecks += kop
        sources.append(
            PassiveIncomeSource(
                bucket=PassiveIncomeSourceBucket.DEPOSIT_INTEREST,
                source_type="deposit_snapshot",
                account_id=account_id,
                amount=RubleAmount(kop),
            )
        )

    # --- Investment cash flows: INTEREST/COUPON/DIVIDEND/OTHER counted, rest excluded ---
    flow_rows = session.execute(
        select(
            InvestmentCashFlow.flow_type,
            InvestmentCashFlow.account_id,
            InvestmentCashFlow.instrument_id,
            InvestmentCashFlow.net_amount_kopecks,
            Account.account_type,
        )
        .join(Account, InvestmentCashFlow.account_id == Account.id)
        .where(InvestmentCashFlow.reporting_month_id == reporting_month_id)
    ).all()

    bucket_totals: dict[PassiveIncomeSourceBucket, int] = {
        PassiveIncomeSourceBucket.DEPOSIT_INTEREST: 0,
        PassiveIncomeSourceBucket.BOND_COUPONS: 0,
        PassiveIncomeSourceBucket.DIVIDENDS: 0,
        PassiveIncomeSourceBucket.OTHER_CAPITAL_INCOME: 0,
    }

    for flow_type_str, account_id, instrument_id, net_kop, account_type in flow_rows:
        if flow_type_str == "interest" and account_type in {"deposit", "savings"}:
            continue
        counts, bucket = classify_flow_type(flow_type_str)
        if not counts or bucket is None:
            continue
        kop = int(net_kop or 0)
        bucket_totals[bucket] += kop
        sources.append(
            PassiveIncomeSource(
                bucket=bucket,
                source_type="investment_cash_flow",
                account_id=account_id,
                instrument_id=instrument_id,
                amount=RubleAmount(kop),
            )
        )

    # --- Income entries: only OTHER with include_in_passive_income=True ---
    income_rows = session.execute(
        select(
            IncomeEntry.id,
            IncomeEntry.income_type,
            IncomeEntry.net_amount_kopecks,
        ).where(
            IncomeEntry.reporting_month_id == reporting_month_id,
            IncomeEntry.income_type == "other",
            IncomeEntry.include_in_passive_income.is_(True),
        )
    ).all()

    for entry_id, income_type_str, net_kop in income_rows:
        kop = int(net_kop or 0)
        bucket_totals[PassiveIncomeSourceBucket.OTHER_CAPITAL_INCOME] += kop
        sources.append(
            PassiveIncomeSource(
                bucket=PassiveIncomeSourceBucket.OTHER_CAPITAL_INCOME,
                source_type="income_entry",
                amount=RubleAmount(kop),
            )
        )

    deposit_interest = RubleAmount(deposit_interest_kopecks)
    bond_coupons = RubleAmount(bucket_totals[PassiveIncomeSourceBucket.BOND_COUPONS])
    dividends = RubleAmount(bucket_totals[PassiveIncomeSourceBucket.DIVIDENDS])
    other_capital_income = RubleAmount(
        bucket_totals[PassiveIncomeSourceBucket.OTHER_CAPITAL_INCOME]
    )

    return calculate_passive_income(
        PassiveIncomeInput(
            deposit_interest=deposit_interest,
            bond_coupons=bond_coupons,
            dividends=dividends,
            other_capital_income=other_capital_income,
            sources=tuple(sources),
        )
    )
