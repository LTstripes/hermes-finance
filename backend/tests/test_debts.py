from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, DebtType, RubleAmount
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import (
    create_account,
    delete_account,
    get_account,
    update_account,
)
from hermes_finance.services.cash import (
    CashBalanceNotFoundError,
    create_cash_balance,
    delete_cash_balance,
    get_cash_balance,
    update_cash_balance,
)
from hermes_finance.services.debts import (
    DebtAccountLinkConflictError,
    DebtNotFoundError,
    create_debt,
    delete_debt,
    get_debt,
    link_debt_to_account,
    list_debts,
    list_linked_debts,
    total_debts,
    total_included_debts,
    unlink_debt_from_account,
    update_debt,
)
from hermes_finance.services.deposits import (
    DepositSnapshotNotFoundError,
    create_deposit_snapshot,
    delete_deposit_snapshot,
    get_deposit_snapshot,
)
from hermes_finance.services.linked_pairs import LinkedPairBalanceEvidenceConflictError
from hermes_finance.services.liquid_capital import liquid_capital_for_month
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
    reopen_reporting_month,
)


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "debts.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(session: Session) -> tuple[int, int]:
    first = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    second = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 12))
    return first.id, second.id


def test_credit_card_is_included_in_liquid_capital_deduction(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        create_debt(
            session,
            reporting_month_id=first_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Card",
            current_balance="25000.00",
        )
        create_debt(
            session,
            reporting_month_id=first_id,
            debt_type=DebtType.OTHER,
            name="Synthetic Loan",
            current_balance="50000.00",
            include_in_liquid_capital=False,
        )
        assert total_debts(session, first_id) == RubleAmount(7_500_000)
        assert total_included_debts(session, first_id) == RubleAmount(2_500_000)
    finally:
        session.close()
        database.engine.dispose()


def test_debt_totals_are_scoped_to_month(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, second_id = build_environment(session)
        create_debt(
            session,
            reporting_month_id=first_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Card",
            current_balance="25000.00",
        )
        create_debt(
            session,
            reporting_month_id=second_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Card",
            current_balance="1000.00",
        )
        assert total_included_debts(session, first_id) == RubleAmount(2_500_000)
        assert total_included_debts(session, second_id) == RubleAmount(100_000)
    finally:
        session.close()
        database.engine.dispose()


def test_debt_crud_updates_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        debt = create_debt(
            session,
            reporting_month_id=first_id,
            debt_type=DebtType.OTHER,
            name="  Synthetic Loan  ",
            current_balance="100000.00",
            notes="synthetic note",
        )
        assert debt.name == "Synthetic Loan"
        updated = update_debt(
            session,
            debt.id,
            current_balance="90000.00",
            include_in_liquid_capital=False,
        )
        assert updated.current_balance_kopecks == 9_000_000
        assert updated.include_in_liquid_capital is False
        assert len(list_debts(session)) == 1
        delete_debt(session, debt.id)
        with pytest.raises(DebtNotFoundError):
            get_debt(session, debt.id)
    finally:
        session.close()
        database.engine.dispose()


def test_debt_validation_rejects_bad_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        with pytest.raises(ValueError, match="must not be empty"):
            create_debt(
                session,
                reporting_month_id=first_id,
                debt_type=DebtType.CREDIT_CARD,
                name="  ",
                current_balance="1.00",
            )
        with pytest.raises(ValueError, match="unsupported debt type"):
            create_debt(
                session,
                reporting_month_id=first_id,
                debt_type="mortgage",
                name="Synthetic",
                current_balance="1.00",
            )
        with pytest.raises(ValueError, match="must not be negative"):
            create_debt(
                session,
                reporting_month_id=first_id,
                debt_type=DebtType.CREDIT_CARD,
                name="Synthetic",
                current_balance="-1.00",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_debt_rate_zero_is_distinct_from_unknown(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        unknown = create_debt(
            session,
            reporting_month_id=first_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Unknown Rate Card",
            current_balance="10000.00",
        )
        assert unknown.annual_rate_basis_points is None
        zero = create_debt(
            session,
            reporting_month_id=first_id,
            debt_type=DebtType.OTHER,
            name="Zero Rate Loan",
            current_balance="50000.00",
            annual_rate="0",
        )
        assert zero.annual_rate_basis_points == 0
        rated = update_debt(session, unknown.id, annual_rate="19.90")
        assert rated.annual_rate_basis_points == 1990
        cleared = update_debt(session, rated.id, annual_rate=None)
        assert cleared.annual_rate_basis_points is None
        # Omitted nullable fields keep their stored value.
        kept = update_debt(session, zero.id, name="Zero Rate Loan Renamed")
        assert kept.annual_rate_basis_points == 0
    finally:
        session.close()
        database.engine.dispose()


def test_debt_due_and_end_dates_stay_separate(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        debt = create_debt(
            session,
            reporting_month_id=first_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Dated Card",
            current_balance="10000.00",
            next_due_date=date(2030, 5, 20),
            contract_end_date=date(2032, 5, 20),
        )
        assert debt.next_due_date == date(2030, 5, 20)
        assert debt.contract_end_date == date(2032, 5, 20)
        updated = update_debt(session, debt.id, next_due_date=None)
        assert updated.next_due_date is None
        assert updated.contract_end_date == date(2032, 5, 20)
    finally:
        session.close()
        database.engine.dispose()


def test_debt_rate_rejects_negative(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        with pytest.raises(ValueError, match="must not be negative"):
            create_debt(
                session,
                reporting_month_id=first_id,
                debt_type=DebtType.CREDIT_CARD,
                name="Synthetic",
                current_balance="1.00",
                annual_rate="-0.5",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_failed_multi_field_debt_update_does_not_mutate_reused_session(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        debt = create_debt(
            session,
            reporting_month_id=build_environment(session)[0],
            debt_type=DebtType.OTHER,
            name="Synthetic Original Debt",
            current_balance="1000.00",
            annual_rate="12.50",
        )

        with pytest.raises(ValueError, match="API percentage rate"):
            update_debt(
                session,
                debt.id,
                name="Should Not Persist",
                annual_rate="not-a-rate",
            )

        assert debt.name == "Synthetic Original Debt"
        assert debt.annual_rate_basis_points == 1250
        assert not session.is_modified(debt, include_collections=False)
        assert debt not in session.dirty

        # A reused session must not flush any partial update from the rejected call.
        assert next(row for row in list_debts(session) if row.id == debt.id).name == (
            "Synthetic Original Debt"
        )
        session.commit()
        session.expire(debt)
        persisted = get_debt(session, debt.id)
        assert persisted.name == "Synthetic Original Debt"
        assert persisted.annual_rate_basis_points == 1250
    finally:
        session.close()
        database.engine.dispose()


def test_link_change_unlink_is_month_local_and_account_side_is_derived(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, second_id = build_environment(session)
        cash = create_account(session, name="Synthetic Cash", account_type=AccountType.CASH)
        deposit = create_account(
            session,
            name="Synthetic Deposit",
            account_type=AccountType.DEPOSIT,
        )
        excluded_deposit = create_account(
            session,
            name="Synthetic Excluded Deposit",
            account_type=AccountType.DEPOSIT,
            include_in_capital=False,
        )
        create_cash_balance(
            session,
            reporting_month_id=first_id,
            account_id=cash.id,
            name="Synthetic Cash Balance",
            amount="0.00",
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=first_id,
            account_id=deposit.id,
            name="Synthetic Deposit Snapshot",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        debt = create_debt(
            session,
            reporting_month_id=first_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Card",
            current_balance="25000.00",
        )

        linked = link_debt_to_account(session, debt.id, cash.id)
        assert linked.linked_account_id == cash.id
        assert cash.include_in_capital is True
        assert deposit.include_in_capital is True
        assert [row.id for row in list_linked_debts(session, cash.id)] == [debt.id]
        assert list_linked_debts(session, cash.id, reporting_month_id=second_id) == []

        with pytest.raises(ValueError, match="included in capital"):
            link_debt_to_account(session, debt.id, excluded_deposit.id)
        assert get_debt(session, debt.id).linked_account_id == cash.id

        changed = link_debt_to_account(session, debt.id, deposit.id)
        assert changed.linked_account_id == deposit.id
        assert list_linked_debts(session, cash.id) == []
        assert [row.id for row in list_linked_debts(session, deposit.id)] == [debt.id]

        unlinked = unlink_debt_from_account(session, debt.id)
        assert unlinked.linked_account_id is None
        assert list_linked_debts(session, deposit.id) == []
    finally:
        session.close()
        database.engine.dispose()


def test_link_requires_month_local_balance_evidence_and_accepts_explicit_zero(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, _ = build_environment(session)
        cash = create_account(session, name="Synthetic Empty Cash", account_type=AccountType.CASH)
        cash_debt = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Cash Card",
            current_balance="100.00",
        )

        with pytest.raises(
            LinkedPairBalanceEvidenceConflictError,
            match="must have an included cash or deposit fact",
        ):
            link_debt_to_account(session, cash_debt.id, cash.id)
        assert get_debt(session, cash_debt.id).linked_account_id is None

        create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=cash.id,
            name="Synthetic Explicit Zero Cash",
            amount="0.00",
        )
        assert link_debt_to_account(session, cash_debt.id, cash.id).linked_account_id == cash.id

        deposit = create_account(
            session,
            name="Synthetic Zero Deposit",
            account_type=AccountType.DEPOSIT,
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=deposit.id,
            name="Synthetic Explicit Zero Deposit",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        deposit_debt = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Deposit Card",
            current_balance="200.00",
        )
        assert (
            link_debt_to_account(session, deposit_debt.id, deposit.id).linked_account_id
            == deposit.id
        )
    finally:
        session.close()
        database.engine.dispose()


def test_linked_pair_rejects_removing_last_cash_fact_for_each_transition(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, _ = build_environment(session)
        cash = create_account(session, name="Synthetic Linked Cash", account_type=AccountType.CASH)
        other_cash = create_account(
            session,
            name="Synthetic Other Cash",
            account_type=AccountType.CASH,
        )
        balance = create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=cash.id,
            name="Synthetic Last Cash Fact",
            amount="0.00",
        )
        debt = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Linked Card",
            current_balance="300.00",
        )
        link_debt_to_account(session, debt.id, cash.id)

        expected = pytest.raises(
            LinkedPairBalanceEvidenceConflictError,
            match="must retain an included cash or deposit fact",
        )
        with expected:
            delete_cash_balance(session, balance.id)
        assert get_cash_balance(session, balance.id).account_id == cash.id

        with pytest.raises(
            LinkedPairBalanceEvidenceConflictError,
            match="must retain an included cash or deposit fact",
        ):
            update_cash_balance(session, balance.id, account_id=other_cash.id)
        assert get_cash_balance(session, balance.id).account_id == cash.id

        with pytest.raises(
            LinkedPairBalanceEvidenceConflictError,
            match="must retain an included cash or deposit fact",
        ):
            update_cash_balance(session, balance.id, account_id=None)
        assert get_cash_balance(session, balance.id).account_id == cash.id

        with pytest.raises(
            LinkedPairBalanceEvidenceConflictError,
            match="must retain an included cash or deposit fact",
        ):
            update_cash_balance(session, balance.id, include_in_capital=False)
        persisted = get_cash_balance(session, balance.id)
        assert persisted.account_id == cash.id
        assert persisted.include_in_capital is True
    finally:
        session.close()
        database.engine.dispose()


def test_removing_one_of_several_qualifying_cash_facts_remains_allowed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, _ = build_environment(session)
        cash = create_account(
            session, name="Synthetic Multi-Fact Cash", account_type=AccountType.CASH
        )
        first = create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=cash.id,
            name="Synthetic Cash Fact A",
            amount="0.00",
        )
        second = create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=cash.id,
            name="Synthetic Cash Fact B",
            amount="0.00",
        )
        debt = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Multi-Fact Card",
            current_balance="300.00",
        )
        link_debt_to_account(session, debt.id, cash.id)

        delete_cash_balance(session, first.id)

        with pytest.raises(CashBalanceNotFoundError):
            get_cash_balance(session, first.id)
        assert get_cash_balance(session, second.id).account_id == cash.id
        assert get_debt(session, debt.id).linked_account_id == cash.id
    finally:
        session.close()
        database.engine.dispose()


def test_linked_pair_rejects_deleting_last_deposit_fact(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, _ = build_environment(session)
        deposit = create_account(
            session,
            name="Synthetic Linked Deposit",
            account_type=AccountType.DEPOSIT,
        )
        first = create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=deposit.id,
            name="Synthetic Deposit Fact A",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        second = create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=deposit.id,
            name="Synthetic Deposit Fact B",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        debt = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Deposit Card",
            current_balance="300.00",
        )
        link_debt_to_account(session, debt.id, deposit.id)

        delete_deposit_snapshot(session, first.id)
        with pytest.raises(DepositSnapshotNotFoundError):
            get_deposit_snapshot(session, first.id)

        with pytest.raises(
            LinkedPairBalanceEvidenceConflictError,
            match="must retain an included cash or deposit fact",
        ):
            delete_deposit_snapshot(session, second.id)
        assert get_deposit_snapshot(session, second.id).account_id == deposit.id
    finally:
        session.close()
        database.engine.dispose()


def test_link_rejects_ineligible_debt_account_and_excluded_debt(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, _ = build_environment(session)
        cash = create_account(session, name="Synthetic Cash", account_type=AccountType.CASH)
        brokerage = create_account(
            session,
            name="Synthetic Brokerage",
            account_type=AccountType.BROKERAGE,
        )
        other = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.OTHER,
            name="Synthetic Loan",
            current_balance="1000.00",
        )
        excluded = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Excluded Card",
            current_balance="1000.00",
            include_in_liquid_capital=False,
        )
        eligible = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Card",
            current_balance="1000.00",
        )
        create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=cash.id,
            name="Synthetic Cash Balance",
            amount="0.00",
        )

        with pytest.raises(ValueError, match="only credit_card"):
            link_debt_to_account(session, other.id, cash.id)
        with pytest.raises(ValueError, match="already be included"):
            link_debt_to_account(session, excluded.id, cash.id)
        with pytest.raises(ValueError, match="cash, deposit, or savings"):
            link_debt_to_account(session, eligible.id, brokerage.id)

        assert get_debt(session, other.id).linked_account_id is None
        assert get_debt(session, excluded.id).linked_account_id is None
        assert get_debt(session, eligible.id).linked_account_id is None
    finally:
        session.close()
        database.engine.dispose()


def test_link_rejects_duplicate_and_prevents_orphaning_account(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, _ = build_environment(session)
        cash = create_account(session, name="Synthetic Cash", account_type=AccountType.CASH)
        first = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic First Card",
            current_balance="1000.00",
        )
        second = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Second Card",
            current_balance="2000.00",
        )
        create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=cash.id,
            name="Synthetic Cash Balance",
            amount="0.00",
        )
        link_debt_to_account(session, first.id, cash.id)

        with pytest.raises(DebtAccountLinkConflictError, match="already linked"):
            link_debt_to_account(session, second.id, cash.id)
        with pytest.raises(ValueError, match="cannot change"):
            update_account(
                session,
                cash.id,
                name="Should Not Persist",
                account_type=AccountType.BROKERAGE,
            )
        with pytest.raises(ValueError, match="remain included"):
            update_debt(
                session,
                first.id,
                current_balance="999.00",
                include_in_liquid_capital=False,
            )
        with pytest.raises(ValueError, match="remain a credit_card"):
            update_debt(session, first.id, name="Should Not Persist", debt_type=DebtType.OTHER)
        with pytest.raises(ValueError, match="cannot be deleted"):
            delete_account(session, cash.id)

        assert cash.account_type == AccountType.CASH.value
        assert cash.name == "Synthetic Cash"
        assert get_debt(session, first.id).linked_account_id == cash.id
        assert get_debt(session, first.id).current_balance_kopecks == 100_000
        assert get_debt(session, second.id).linked_account_id is None
    finally:
        session.close()
        database.engine.dispose()


def test_linked_account_cannot_be_excluded_from_capital(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, _ = build_environment(session)
        deposit = create_account(
            session,
            name="Synthetic Linked Deposit",
            account_type=AccountType.DEPOSIT,
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=deposit.id,
            name="Synthetic Deposit Snapshot",
            deposit_type="deposit",
            balance="10000.00",
            annual_rate="0",
        )
        debt = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Linked Card",
            current_balance="3000.00",
        )
        link_debt_to_account(session, debt.id, deposit.id)
        before = liquid_capital_for_month(session, month_id)

        with pytest.raises(ValueError, match="remain included in capital"):
            update_account(session, deposit.id, include_in_capital=False)

        assert get_account(session, deposit.id).include_in_capital is True
        assert get_debt(session, debt.id).linked_account_id == deposit.id
        after = liquid_capital_for_month(session, month_id)
        assert after.total_assets == before.total_assets
        assert after.total_debts_included == before.total_debts_included
        assert after.liquid_capital_net == before.liquid_capital_net
    finally:
        session.close()
        database.engine.dispose()


def test_link_and_unlink_obey_closed_month_and_reopen(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, _ = build_environment(session)
        cash = create_account(session, name="Synthetic Cash", account_type=AccountType.CASH)
        deposit = create_account(
            session,
            name="Synthetic Deposit",
            account_type=AccountType.DEPOSIT,
        )
        create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=cash.id,
            name="Synthetic Cash Balance",
            amount="0.00",
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=deposit.id,
            name="Synthetic Deposit Snapshot",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        debt = create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Card",
            current_balance="1000.00",
        )
        link_debt_to_account(session, debt.id, cash.id)
        close_reporting_month(session, month_id)

        with pytest.raises(ValueError, match="reopened"):
            link_debt_to_account(session, debt.id, deposit.id)
        with pytest.raises(ValueError, match="reopened"):
            unlink_debt_from_account(session, debt.id)

        reopen_reporting_month(session, month_id)
        changed = link_debt_to_account(session, debt.id, deposit.id)
        assert changed.linked_account_id == deposit.id
        unlink_debt_from_account(session, debt.id)
        assert get_debt(session, debt.id).linked_account_id is None
    finally:
        session.close()
        database.engine.dispose()
