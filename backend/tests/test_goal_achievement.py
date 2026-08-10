from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from hermes_finance.database import create_database
from hermes_finance.domain import GoalType, RubleAmount
from hermes_finance.domain.goal_achievement import (
    GOAL_ACHIEVEMENT_METHOD_VERSION,
    calculate_goal_achievement_forecast,
)
from hermes_finance.persistence import Base
from hermes_finance.services.goal_achievement import build_goal_achievement_summary
from hermes_finance.services.goals import create_goal
from hermes_finance.services.reporting_months import create_reporting_month

REPORTING_DATE = date(2030, 5, 12)


def test_supported_forecast_below_target_is_not_projectable_with_exact_gap_and_progress() -> None:
    result = calculate_goal_achievement_forecast(
        goal_id=7,
        reporting_month_id=11,
        as_of_date=REPORTING_DATE,
        current_value=RubleAmount(12_345_67),
        target_value=RubleAmount(100_000_00),
        source_forecast_version="v2",
        is_approximate=True,
        warnings=("upstream warning",),
    )

    assert result.method_version == GOAL_ACHIEVEMENT_METHOD_VERSION == "goal_achievement_v1"
    assert result.status == "not_projectable"
    assert result.reason_code == "no_trajectory_model"
    assert result.current_value == RubleAmount(12_345_67)
    assert result.remaining_amount == RubleAmount(87_654_33)
    assert result.progress_pct == Decimal("12.35")
    assert result.estimated_achievement_date is None
    assert result.source_forecast_version == "v2"
    assert result.is_approximate is True
    assert result.warnings == ("upstream warning",)


def test_supported_forecast_at_or_above_target_is_achieved_at_snapshot() -> None:
    result = calculate_goal_achievement_forecast(
        goal_id=7,
        reporting_month_id=11,
        as_of_date=REPORTING_DATE,
        current_value=RubleAmount(100_000_01),
        target_value=RubleAmount(100_000_00),
        source_forecast_version=None,
    )

    assert result.status == "achieved"
    assert result.reason_code is None
    assert result.remaining_amount == RubleAmount(0)
    assert result.progress_pct == Decimal("100.00")
    assert result.estimated_achievement_date == REPORTING_DATE


def test_zero_target_is_achieved_without_percentage() -> None:
    result = calculate_goal_achievement_forecast(
        goal_id=7,
        reporting_month_id=11,
        as_of_date=REPORTING_DATE,
        current_value=RubleAmount(0),
        target_value=RubleAmount(0),
        source_forecast_version=None,
    )

    assert result.status == "achieved"
    assert result.progress_pct is None
    assert result.remaining_amount == RubleAmount(0)


def test_percentage_uses_decimal_round_half_up_to_two_places() -> None:
    result = calculate_goal_achievement_forecast(
        goal_id=7,
        reporting_month_id=11,
        as_of_date=REPORTING_DATE,
        current_value=RubleAmount(3),
        target_value=RubleAmount(20_000),
        source_forecast_version=None,
    )

    assert result.progress_pct == Decimal("0.02")
    assert str(result.progress_pct) == "0.02"


def test_summary_reuses_each_supported_source_metric_once_and_skips_inactive_and_unsupported(
    tmp_path, monkeypatch
) -> None:
    database = create_database(tmp_path / "goal-achievement.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    try:
        month = create_reporting_month(session, year=2030, month=5, snapshot_date=REPORTING_DATE)
        passive = create_goal(
            session,
            name="Passive A",
            goal_type=GoalType.PASSIVE_INCOME,
            target_value=RubleAmount(100_000_00),
            calculation_mode="monthly_net_passive_income",
        )
        passive_b = create_goal(
            session,
            name="Passive B",
            goal_type=GoalType.PASSIVE_INCOME,
            target_value=RubleAmount(200_000_00),
            calculation_mode="monthly_net_passive_income",
        )
        capital = create_goal(
            session,
            name="Capital",
            goal_type=GoalType.CAPITAL,
            target_value=RubleAmount(50_000_00),
            calculation_mode="liquid_capital_net",
        )
        capital_below = create_goal(
            session,
            name="Capital below",
            goal_type=GoalType.CAPITAL,
            target_value=RubleAmount(100_000_00),
            target_date=date(2099, 1, 1),
            calculation_mode="liquid_capital_net",
        )
        inactive = create_goal(
            session,
            name="Inactive",
            goal_type=GoalType.CAPITAL,
            target_value=RubleAmount(1),
            calculation_mode="liquid_capital_net",
            is_active=False,
        )
        unsupported = create_goal(
            session,
            name="Coverage",
            goal_type=GoalType.EXPENSE_COVERAGE,
            target_value=RubleAmount(1),
            calculation_mode="anything",
        )
        passive_calls = 0
        capital_calls = 0

        def fake_passive(*args):
            nonlocal passive_calls
            passive_calls += 1
            return SimpleNamespace(
                monthly_total=RubleAmount(120_000_00),
                is_approximate=True,
                warnings=("forecast warning",),
            )

        def fake_capital(*args):
            nonlocal capital_calls
            capital_calls += 1
            return SimpleNamespace(liquid_capital_net=RubleAmount(60_000_00))

        monkeypatch.setattr(
            "hermes_finance.services.goal_achievement.forecast_passive_income", fake_passive
        )
        monkeypatch.setattr(
            "hermes_finance.services.goal_achievement.liquid_capital_for_month", fake_capital
        )

        items = build_goal_achievement_summary(
            session, month.id, include_inactive=True, forecast_version="custom-v2"
        )
        by_id = {item.goal.id: item for item in items}

        assert passive_calls == 1
        assert capital_calls == 1
        assert by_id[passive.id].achievement_forecast.current_value == RubleAmount(120_000_00)
        assert by_id[passive_b.id].achievement_forecast.current_value == RubleAmount(120_000_00)
        assert by_id[passive.id].achievement_forecast.source_forecast_version == "custom-v2"
        assert by_id[passive.id].achievement_forecast.warnings == ("forecast warning",)
        assert by_id[passive.id].achievement_forecast.progress_pct == Decimal("120.00")
        assert by_id[passive.id].achievement_forecast.remaining_amount == RubleAmount(0)
        assert by_id[passive.id].achievement_forecast.status == "achieved"
        assert by_id[passive_b.id].achievement_forecast.progress_pct == Decimal("60.00")
        assert by_id[passive_b.id].achievement_forecast.remaining_amount == RubleAmount(80_000_00)
        assert by_id[passive_b.id].achievement_forecast.estimated_achievement_date is None
        assert by_id[capital.id].achievement_forecast.current_value == RubleAmount(60_000_00)
        assert by_id[capital.id].achievement_forecast.source_forecast_version is None
        assert by_id[capital.id].achievement_forecast.status == "achieved"
        assert by_id[capital_below.id].achievement_forecast.status == "not_projectable"
        assert by_id[capital_below.id].achievement_forecast.reason_code == "no_trajectory_model"
        assert by_id[capital_below.id].achievement_forecast.estimated_achievement_date is None
        assert by_id[inactive.id].achievement_forecast.status == "inactive"
        assert by_id[inactive.id].achievement_forecast.current_value is None
        assert by_id[unsupported.id].achievement_forecast.reason_code == "unsupported_goal_type"
    finally:
        session.close()
        database.engine.dispose()


def test_wrong_mode_is_unsupported_without_calculator(monkeypatch, tmp_path) -> None:
    database = create_database(tmp_path / "wrong-mode.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    try:
        month = create_reporting_month(session, year=2030, month=5, snapshot_date=REPORTING_DATE)
        goal = create_goal(
            session,
            name="Wrong mode",
            goal_type=GoalType.CAPITAL,
            target_value=RubleAmount(1),
            calculation_mode="capital_total",
        )
        monkeypatch.setattr(
            "hermes_finance.services.goal_achievement.liquid_capital_for_month",
            lambda *_: pytest.fail("calculator must not run for unsupported mode"),
        )
        item = build_goal_achievement_summary(session, month.id)[0]
        assert item.goal.id == goal.id
        assert item.achievement_forecast.reason_code == "unsupported_calculation_mode"
    finally:
        session.close()
        database.engine.dispose()


def test_passive_wrong_mode_is_unsupported_without_calculator(monkeypatch, tmp_path) -> None:
    database = create_database(tmp_path / "wrong-passive-mode.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    try:
        month = create_reporting_month(session, year=2030, month=5, snapshot_date=REPORTING_DATE)
        create_goal(
            session,
            name="Wrong passive mode",
            goal_type=GoalType.PASSIVE_INCOME,
            target_value=RubleAmount(1),
            calculation_mode="passive_total",
        )
        monkeypatch.setattr(
            "hermes_finance.services.goal_achievement.forecast_passive_income",
            lambda *_: pytest.fail("calculator must not run for unsupported mode"),
        )
        result = build_goal_achievement_summary(session, month.id)[0].achievement_forecast
        assert result.reason_code == "unsupported_calculation_mode"
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    "goal_type",
    [GoalType.EXPENSE_COVERAGE, GoalType.MORTGAGE_COVERAGE, GoalType.OTHER],
)
def test_unsupported_goal_types_are_reported_without_calculator(
    goal_type, monkeypatch, tmp_path
) -> None:
    database = create_database(tmp_path / f"unsupported-{goal_type}.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    try:
        month = create_reporting_month(session, year=2030, month=5, snapshot_date=REPORTING_DATE)
        create_goal(
            session,
            name=f"Unsupported {goal_type}",
            goal_type=goal_type,
            target_value=RubleAmount(1),
            calculation_mode="anything",
        )
        monkeypatch.setattr(
            "hermes_finance.services.goal_achievement.forecast_passive_income",
            lambda *_: pytest.fail("passive calculator must not run for unsupported type"),
        )
        monkeypatch.setattr(
            "hermes_finance.services.goal_achievement.liquid_capital_for_month",
            lambda *_: pytest.fail("capital calculator must not run for unsupported type"),
        )
        result = build_goal_achievement_summary(session, month.id)[0].achievement_forecast
        assert result.status == "unsupported"
        assert result.reason_code == "unsupported_goal_type"
        assert result.current_value is None
        assert result.remaining_amount is None
        assert result.progress_pct is None
    finally:
        session.close()
        database.engine.dispose()
