"""Materialize FrozenScenarioBase — the single DB read phase.

Scenario evaluation must never read the database after this capture returns.
The materializer composes canonical read models exactly once:

- selected ReportingMonth identity and status;
- cash / deposit / position / debt facts of the selected month;
- active capital Goals;
- canonical merged payout calendar window mapped into forecast expected flows;
- actual dividend history over closed months (forecast dividend component);
- the canonical R07-05 cash-flow ladder base.

No writes, no network, no provider refresh, no transaction isolation changes.
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import select

from hermes_finance.domain import RubleAmount
from hermes_finance.domain.cash_flows import ExpectedCashFlowType
from hermes_finance.domain.reporting import ReportingMonthStatus
from hermes_finance.domain.scenario_frozen_base import (
    FrozenCash,
    FrozenDebt,
    FrozenDeposit,
    FrozenDividendMonth,
    FrozenExpectedFlow,
    FrozenForecastInputs,
    FrozenGoal,
    FrozenLadder,
    FrozenLadderMonth,
    FrozenPosition,
    FrozenScenarioBase,
    FrozenUpcomingWindow,
    FrozenWindowEvent,
    compute_frozen_base_fingerprint,
)
from hermes_finance.persistence import (
    APP_SETTINGS_ID,
    Account,
    AppSettings,
    CashBalance,
    Debt,
    DepositSnapshot,
    Goal,
    Instrument,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.cash_flow_ladder import build_cash_flow_ladder
from hermes_finance.services.passive_income import passive_income_for_months
from hermes_finance.services.payout_calendar import merged_payout_calendar
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError
from hermes_finance.services.settings import parse_passive_income_history_start_month


def _capture_stage_merged_payout_calendar(session, *, reporting_month_id, forecast_version):
    """Capture-stage indirection for the merged payout calendar read.

    Exists so tests can hook a mutation between capture stages; production
    behavior is the plain canonical read model.
    """
    return merged_payout_calendar(
        session, reporting_month_id=reporting_month_id, forecast_version=forecast_version
    )


def _capture_stage_passive_income_for_months(session, month_ids):
    """Capture-stage indirection for the actual passive-income history read."""
    return passive_income_for_months(session, month_ids)


def _capture_stage_build_cash_flow_ladder(session, *, reporting_month_id, forecast_version):
    """Capture-stage indirection for the R07-05 ladder base read."""
    return build_cash_flow_ladder(
        session, reporting_month_id=reporting_month_id, forecast_version=forecast_version
    )


def _coerce_window(window) -> FrozenUpcomingWindow:
    return FrozenUpcomingWindow(
        days=window.days,
        from_date=window.from_date,
        to_date=window.to_date,
        passive_income_kopecks=window.passive_income.kopecks,
        redemption_principal_kopecks=window.redemption_principal.kopecks,
        total_cash_flow_kopecks=window.total_cash_flow.kopecks,
        events=tuple(
            FrozenWindowEvent(
                expected_date=event.expected_date,
                flow_type=event.flow_type,
                component=event.component,
                account_id=event.account_id,
                instrument_id=event.instrument_id,
                expected_net_amount_kopecks=event.expected_net_amount.kopecks,
                is_approximate=bool(event.is_approximate),
                source_kind=str(event.source_kind.value),
                source_id=int(event.source_id),
            )
            for event in window.items
        ),
    )


def _frozen_ladder(ladder) -> FrozenLadder:
    return FrozenLadder(
        as_of_date=ladder.as_of_date,
        forecast_version=ladder.forecast_version,
        months=tuple(
            FrozenLadderMonth(
                year=item.year,
                month=item.month,
                coupon_kopecks=item.coupon.kopecks,
                dividend_kopecks=item.dividend.kopecks,
                deposit_interest_kopecks=item.deposit_interest.kopecks,
                other_capital_income_kopecks=item.other_capital_income.kopecks,
                redemption_principal_kopecks=item.redemption_principal.kopecks,
                passive_income_kopecks=item.passive_income.kopecks,
                total_cash_flow_kopecks=item.total_cash_flow.kopecks,
                is_approximate=bool(item.is_approximate),
            )
            for item in ladder.months
        ),
        upcoming_14_days=_coerce_window(ladder.upcoming_14_days),
        upcoming_30_days=_coerce_window(ladder.upcoming_30_days),
    )


def materialize_frozen_base(
    session,
    reporting_month_id: int,
    *,
    forecast_version: str = "v1",
) -> FrozenScenarioBase:
    """Read the selected month once and freeze all semantic inputs."""
    version = forecast_version.strip() or "v1"

    with session.no_autoflush:
        month = session.get(ReportingMonth, reporting_month_id)
        if month is None:
            raise ReportingMonthNotFoundError(f"reporting month {reporting_month_id} was not found")

        cash_rows = list(
            session.scalars(
                select(CashBalance)
                .where(CashBalance.reporting_month_id == reporting_month_id)
                .order_by(CashBalance.id)
            )
        )
        deposit_rows = list(
            session.execute(
                select(DepositSnapshot, Account.name, Account.include_in_capital)
                .join(Account, DepositSnapshot.account_id == Account.id)
                .where(DepositSnapshot.reporting_month_id == reporting_month_id)
                .order_by(DepositSnapshot.id)
            ).all()
        )
        pos_rows = list(
            session.execute(
                select(PositionSnapshot, Instrument.name, Instrument.instrument_type)
                .join(Instrument, PositionSnapshot.instrument_id == Instrument.id)
                .where(PositionSnapshot.reporting_month_id == reporting_month_id)
                .order_by(PositionSnapshot.id)
            ).all()
        )
        debt_rows = list(
            session.scalars(
                select(Debt).where(Debt.reporting_month_id == reporting_month_id).order_by(Debt.id)
            )
        )
        all_goals = list(session.scalars(select(Goal).order_by(Goal.id)).all())
        capital_goals = [
            goal
            for goal in all_goals
            if goal.is_active
            and goal.goal_type == "capital"
            and goal.calculation_mode == "liquid_capital_net"
        ]

        account_names: dict[int, str] = {}
        instrument_names: dict[int, str] = {}
        account_include_flags: dict[int, bool] = {}
        for account in session.scalars(select(Account).order_by(Account.id)).all():
            account_names[account.id] = account.name
            account_include_flags[account.id] = bool(account.include_in_capital)
        for instrument in session.scalars(select(Instrument).order_by(Instrument.id)).all():
            instrument_names[instrument.id] = instrument.name

        # --- canonical forecast inputs (merged calendar window + actual dividends) ---
        merged_months = _capture_stage_merged_payout_calendar(
            session,
            reporting_month_id=reporting_month_id,
            forecast_version=version,
        )
        expected_flows: list[FrozenExpectedFlow] = []
        for calendar_month in merged_months:
            for flow in calendar_month.items:
                # Mirror canonical forecast assembly: redemption rows are
                # skipped early; dividend rows are kept so the pure
                # calculator's ignore-branch and is_approximate stay intact.
                if ExpectedCashFlowType(str(flow.flow_type)) is ExpectedCashFlowType.REDEMPTION:
                    continue
                expected_flows.append(
                    FrozenExpectedFlow(
                        flow_type=str(flow.flow_type),
                        net_amount_kopecks=int(flow.expected_net_amount.kopecks),
                        is_approximate=bool(flow.is_approximate),
                    )
                )

        # Deposit monthly-interest sum derives from the deposit rows already
        # captured in this same materialization phase (no second DB read of
        # the deposit table — a later re-read could observe a different DB
        # state and mix snapshots inside one evaluation).
        deposit_monthly_sum = (
            sum(snapshot.expected_monthly_interest_kopecks for snapshot, _n, _i in deposit_rows)
            if deposit_rows
            else None
        )

        closed_months = session.execute(
            select(ReportingMonth.id, ReportingMonth.year, ReportingMonth.month)
            .where(ReportingMonth.status == ReportingMonthStatus.CLOSED.value)
            .order_by(ReportingMonth.year, ReportingMonth.month)
        ).all()
        results_by_month = _capture_stage_passive_income_for_months(
            session, [month_id for month_id, _, _ in closed_months]
        )
        dividend_months: list[FrozenDividendMonth] = []
        for month_id, year, month_number in closed_months:
            result = results_by_month[month_id]
            dividend_months.append(
                FrozenDividendMonth(
                    year=year, month=month_number, amount_kopecks=result.breakdown.dividends.kopecks
                )
            )

        settings = session.scalar(select(AppSettings).where(AppSettings.id == APP_SETTINGS_ID))
        history_start_month = parse_passive_income_history_start_month(
            settings.passive_income_history_start_month if settings is not None else None
        )

        # --- canonical ladder base ---
        ladder = _capture_stage_build_cash_flow_ladder(
            session, reporting_month_id=reporting_month_id, forecast_version=version
        )
        # Keep the ladder on the SAME captured snapshot as the deposit rows:
        # the ladder service re-reads DepositSnapshot internally, which could
        # observe a later DB state than the already-frozen deposit facts.
        # The captured monthly interest sum is authoritative here; replacing
        # the flat deposit_interest component (and the derived passive/total
        # sums) makes the frozen ladder internally consistent even if a
        # concurrent commit lands between capture stages. The upcoming
        # windows never contain deposit rows (undated estimates), so they
        # stay untouched.
        if deposit_rows:
            frozen_deposit_monthly = sum(
                snapshot.expected_monthly_interest_kopecks for snapshot, _n, _i in deposit_rows
            )
        else:
            frozen_deposit_monthly = 0
        reconciled_months = []
        for item in ladder.months:
            deposit_component = item.deposit_interest.kopecks
            if deposit_component != frozen_deposit_monthly:
                passive = item.passive_income.kopecks - deposit_component + frozen_deposit_monthly
                total = passive + item.redemption_principal.kopecks
                item = replace(
                    item,
                    deposit_interest=RubleAmount(frozen_deposit_monthly),
                    passive_income=RubleAmount(passive),
                    total_cash_flow=RubleAmount(total),
                )
            reconciled_months.append(item)
        ladder = replace(ladder, months=tuple(reconciled_months))

    # ---- assemble immutable frozen facts (no further reads) ----
    frozen_cash = tuple(
        FrozenCash(
            id=row.id,
            account_id=row.account_id,
            name=row.name,
            amount_kopecks=row.amount_kopecks,
            currency=row.currency,
            include_in_capital=bool(row.include_in_capital),
        )
        for row in sorted(cash_rows, key=lambda item: item.id)
    )
    frozen_deposits = tuple(
        FrozenDeposit(
            id=snapshot.id,
            account_id=snapshot.account_id,
            name=snapshot.name,
            deposit_type=snapshot.deposit_type,
            balance_kopecks=snapshot.balance_kopecks,
            annual_rate_basis_points=snapshot.annual_rate_basis_points,
            expected_monthly_interest_kopecks=snapshot.expected_monthly_interest_kopecks,
            include_in_capital=bool(include_in_capital),
        )
        for snapshot, _name, include_in_capital in sorted(deposit_rows, key=lambda item: item[0].id)
    )
    frozen_positions = tuple(
        FrozenPosition(
            id=snapshot.id,
            account_id=snapshot.account_id,
            instrument_id=snapshot.instrument_id,
            instrument_type=instrument_type,
            market_value_kopecks=snapshot.market_value_kopecks,
            include_in_capital=bool(account_include_flags.get(snapshot.account_id, True)),
        )
        for snapshot, _instrument_name, instrument_type in sorted(
            pos_rows, key=lambda item: item[0].id
        )
    )
    frozen_debts = tuple(
        FrozenDebt(
            id=debt.id,
            balance_kopecks=debt.current_balance_kopecks,
            include_in_liquid_capital=bool(debt.include_in_liquid_capital),
        )
        for debt in sorted(debt_rows, key=lambda item: item.id)
    )
    frozen_goals = tuple(
        FrozenGoal(
            id=goal.id,
            target_kopecks=goal.target_value_kopecks,
            is_active=bool(goal.is_active),
            goal_type=goal.goal_type,
            calculation_mode=goal.calculation_mode,
        )
        for goal in sorted(capital_goals, key=lambda item: item.id)
    )
    forecast_inputs = FrozenForecastInputs(
        expected_flows=tuple(expected_flows),
        dividend_months=tuple(dividend_months),
        history_start_month=history_start_month,
        deposit_snapshot_monthly_interest_kopecks=deposit_monthly_sum,
    )
    frozen_ladder = _frozen_ladder(ladder)

    reporting_month_dict = {
        "id": month.id,
        "year": month.year,
        "month": month.month,
        "snapshot_date": month.snapshot_date.isoformat(),
        "status": month.status,
    }
    cash_dicts = [
        {
            "id": row.id,
            "account_id": row.account_id,
            "amount_kopecks": row.amount_kopecks,
            "currency": row.currency,
            "include_in_capital": bool(row.include_in_capital),
        }
        for row in sorted(cash_rows, key=lambda item: item.id)
    ]
    deposit_dicts = [
        {
            "id": snapshot.id,
            "account_id": snapshot.account_id,
            "deposit_type": snapshot.deposit_type,
            "balance_kopecks": snapshot.balance_kopecks,
            "annual_rate_basis_points": snapshot.annual_rate_basis_points,
            "expected_monthly_interest_kopecks": snapshot.expected_monthly_interest_kopecks,
            "include_in_capital": bool(include_in_capital),
        }
        for snapshot, _name, include_in_capital in sorted(deposit_rows, key=lambda item: item[0].id)
    ]
    position_dicts = [
        {
            "id": snapshot.id,
            "account_id": snapshot.account_id,
            "instrument_id": snapshot.instrument_id,
            "instrument_type": instrument_type,
            "market_value_kopecks": snapshot.market_value_kopecks,
            "include_in_capital": bool(account_include_flags.get(snapshot.account_id, True)),
        }
        for snapshot, _instrument_name, instrument_type in sorted(
            pos_rows, key=lambda item: item[0].id
        )
    ]
    debt_dicts = [
        {
            "id": debt.id,
            "balance_kopecks": debt.current_balance_kopecks,
            "include_in_liquid_capital": bool(debt.include_in_liquid_capital),
        }
        for debt in sorted(debt_rows, key=lambda item: item.id)
    ]
    goal_dicts = [
        {
            "id": goal.id,
            "target_kopecks": goal.target_value_kopecks,
            "is_active": bool(goal.is_active),
            "goal_type": goal.goal_type,
            "calculation_mode": goal.calculation_mode,
        }
        for goal in sorted(capital_goals, key=lambda item: item.id)
    ]
    forecast_dict = {
        "expected_flows": [
            {
                "flow_type": flow.flow_type,
                "net_amount_kopecks": flow.net_amount_kopecks,
                "is_approximate": flow.is_approximate,
            }
            for flow in forecast_inputs.expected_flows
        ],
        "dividend_months": [
            {"year": item.year, "month": item.month, "amount_kopecks": item.amount_kopecks}
            for item in forecast_inputs.dividend_months
        ],
        "history_start_month": (
            f"{history_start_month[0]:04d}-{history_start_month[1]:02d}"
            if history_start_month is not None
            else None
        ),
        "deposit_snapshot_monthly_interest_kopecks": deposit_monthly_sum,
    }
    ladder_dicts = [
        {
            "year": item.year,
            "month": item.month,
            "coupon_kopecks": item.coupon_kopecks,
            "dividend_kopecks": item.dividend_kopecks,
            "deposit_interest_kopecks": item.deposit_interest_kopecks,
            "other_capital_income_kopecks": item.other_capital_income_kopecks,
            "redemption_principal_kopecks": item.redemption_principal_kopecks,
            "is_approximate": item.is_approximate,
        }
        for item in frozen_ladder.months
    ]
    base_fingerprint = compute_frozen_base_fingerprint(
        reporting_month=reporting_month_dict,
        cash=cash_dicts,
        deposits=deposit_dicts,
        positions=position_dicts,
        debts=debt_dicts,
        goals=goal_dicts,
        forecast=forecast_dict,
        ladder_months=ladder_dicts,
    )

    return FrozenScenarioBase(
        reporting_month_id=month.id,
        year=month.year,
        month=month.month,
        snapshot_date=month.snapshot_date,
        status=month.status,
        reporting_currency="RUB",
        cash=frozen_cash,
        deposits=frozen_deposits,
        positions=frozen_positions,
        debts=frozen_debts,
        capital_goals=frozen_goals,
        account_names=tuple(sorted(account_names.items())),
        instrument_names=tuple(sorted(instrument_names.items())),
        forecast=forecast_inputs,
        ladder=frozen_ladder,
        base_fingerprint=base_fingerprint,
    )
