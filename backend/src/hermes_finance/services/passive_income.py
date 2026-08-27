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
- Only ``IncomeType.OTHER`` may be marked as passive income; salary, bonus,
  side income and cashback are never passive-income sources.
- Generic investment ``INTEREST`` on non-deposit accounts contributes to
  ``other_capital_income``; deposit/savings interest comes only from snapshots.
- Reads are allowed on closed months (B19-R2 guard is for writes only).

Income entries contribute to ``other_capital_income`` only when
``income_type == OTHER`` and ``include_in_passive_income=True``.  The read path
also ignores legacy-invalid active-income rows that still carry a passive flag.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

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


def passive_income_for_months(
    session: Session, reporting_month_ids: Iterable[int]
) -> dict[int, PassiveIncomeResult]:
    """Assemble passive-income results for several months with set-based reads.

    The three source queries mirror ``passive_income_for_month`` exactly.
    Rows are grouped in memory only to feed the unchanged passive-income
    calculator; no persisted or materialized result is introduced.
    """
    month_ids = tuple(dict.fromkeys(reporting_month_ids))
    if not month_ids:
        return {}

    deposit_rows = session.execute(
        select(
            DepositSnapshot.reporting_month_id,
            DepositSnapshot.id,
            DepositSnapshot.account_id,
            DepositSnapshot.actual_interest_received_kopecks,
        )
        .where(DepositSnapshot.reporting_month_id.in_(month_ids))
        .where(DepositSnapshot.actual_interest_received_kopecks > 0)
        .order_by(DepositSnapshot.reporting_month_id, DepositSnapshot.id)
    ).all()
    flow_rows = session.execute(
        select(
            InvestmentCashFlow.reporting_month_id,
            InvestmentCashFlow.id,
            InvestmentCashFlow.flow_type,
            InvestmentCashFlow.account_id,
            InvestmentCashFlow.instrument_id,
            InvestmentCashFlow.net_amount_kopecks,
            Account.account_type,
        )
        .join(Account, InvestmentCashFlow.account_id == Account.id)
        .where(InvestmentCashFlow.reporting_month_id.in_(month_ids))
        .order_by(InvestmentCashFlow.reporting_month_id, InvestmentCashFlow.id)
    ).all()
    income_rows = session.execute(
        select(
            IncomeEntry.reporting_month_id,
            IncomeEntry.id,
            IncomeEntry.income_type,
            IncomeEntry.net_amount_kopecks,
        )
        .where(IncomeEntry.reporting_month_id.in_(month_ids))
        .where(IncomeEntry.income_type == "other")
        .where(IncomeEntry.include_in_passive_income.is_(True))
        .order_by(IncomeEntry.reporting_month_id, IncomeEntry.id)
    ).all()

    sources_by_month: dict[int, list[PassiveIncomeSource]] = defaultdict(list)
    bucket_totals_by_month: dict[int, dict[PassiveIncomeSourceBucket, int]] = {
        month_id: {
            PassiveIncomeSourceBucket.DEPOSIT_INTEREST: 0,
            PassiveIncomeSourceBucket.BOND_COUPONS: 0,
            PassiveIncomeSourceBucket.DIVIDENDS: 0,
            PassiveIncomeSourceBucket.OTHER_CAPITAL_INCOME: 0,
        }
        for month_id in month_ids
    }

    for month_id, _snap_id, account_id, interest_kop in deposit_rows:
        kop = int(interest_kop or 0)
        bucket_totals_by_month[month_id][PassiveIncomeSourceBucket.DEPOSIT_INTEREST] += kop
        sources_by_month[month_id].append(
            PassiveIncomeSource(
                bucket=PassiveIncomeSourceBucket.DEPOSIT_INTEREST,
                source_type="deposit_snapshot",
                account_id=account_id,
                amount=RubleAmount(kop),
            )
        )

    for (
        month_id,
        _flow_id,
        flow_type_str,
        account_id,
        instrument_id,
        net_kop,
        account_type,
    ) in flow_rows:
        if flow_type_str == "interest" and account_type in {"deposit", "savings"}:
            continue
        counts, bucket = classify_flow_type(flow_type_str)
        if not counts or bucket is None:
            continue
        kop = int(net_kop or 0)
        bucket_totals_by_month[month_id][bucket] += kop
        sources_by_month[month_id].append(
            PassiveIncomeSource(
                bucket=bucket,
                source_type="investment_cash_flow",
                account_id=account_id,
                instrument_id=instrument_id,
                amount=RubleAmount(kop),
            )
        )

    for month_id, _entry_id, _income_type_str, net_kop in income_rows:
        kop = int(net_kop or 0)
        bucket = PassiveIncomeSourceBucket.OTHER_CAPITAL_INCOME
        bucket_totals_by_month[month_id][bucket] += kop
        sources_by_month[month_id].append(
            PassiveIncomeSource(
                bucket=bucket,
                source_type="income_entry",
                amount=RubleAmount(kop),
            )
        )

    return {
        month_id: calculate_passive_income(
            PassiveIncomeInput(
                deposit_interest=RubleAmount(
                    bucket_totals_by_month[month_id][PassiveIncomeSourceBucket.DEPOSIT_INTEREST]
                ),
                bond_coupons=RubleAmount(
                    bucket_totals_by_month[month_id][PassiveIncomeSourceBucket.BOND_COUPONS]
                ),
                dividends=RubleAmount(
                    bucket_totals_by_month[month_id][PassiveIncomeSourceBucket.DIVIDENDS]
                ),
                other_capital_income=RubleAmount(
                    bucket_totals_by_month[month_id][PassiveIncomeSourceBucket.OTHER_CAPITAL_INCOME]
                ),
                sources=tuple(sources_by_month[month_id]),
            )
        )
        for month_id in month_ids
    }
