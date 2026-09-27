"""#489: linked-pair balance evidence must survive competing removals.

Deterministic interleaving (Event barriers), not sleeps. Competing operations
that would leave a surviving linked debt without qualifying month-local
balance evidence serialize on the #485 SQLite writer reservation acquired
inside ``ensure_linked_pair_balance_evidence_survives``. Exactly one remover
may commit; the loser raises ``LinkedPairBalanceEvidenceConflictError``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Event

import pytest
from sqlalchemy.orm import Session

import hermes_finance.services.cash as cash_service
import hermes_finance.services.deposits as deposits_service
import hermes_finance.services.linked_pairs as linked_pairs_service
from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, DebtType, DepositType
from hermes_finance.persistence import Base, CashBalance, DepositSnapshot, ReportingMonth
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import (
    create_cash_balance,
    delete_cash_balance,
    update_cash_balance,
)
from hermes_finance.services.debts import create_debt, link_debt_to_account
from hermes_finance.services.deposits import (
    create_deposit_snapshot,
    delete_deposit_snapshot,
)
from hermes_finance.services.linked_pairs import (
    LinkedPairBalanceEvidenceConflictError,
    linked_pairs_for_month,
)
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "linked-pair-evidence.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _seed_linked_cash_and_deposit(session: Session) -> tuple[object, CashBalance, DepositSnapshot]:
    month = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 15))
    account = create_account(session, name="Synthetic Linked Cash", account_type=AccountType.CASH)
    cash = create_cash_balance(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        name="Synthetic Cash Fact",
        amount="100.00",
    )
    deposit = create_deposit_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        name="Synthetic Deposit Fact",
        deposit_type=DepositType.DEPOSIT,
        balance="200.00",
        annual_rate="10.00",
    )
    debt = create_debt(
        session,
        reporting_month_id=month.id,
        debt_type=DebtType.CREDIT_CARD,
        name="Synthetic Linked Card",
        current_balance="50.00",
    )
    link_debt_to_account(session, debt.id, account.id)
    return month, cash, deposit


def _seed_two_linked_cash_facts(session: Session) -> tuple[object, CashBalance, CashBalance]:
    month = create_reporting_month(session, year=2030, month=7, snapshot_date=date(2030, 7, 15))
    account = create_account(session, name="Synthetic Multi Cash", account_type=AccountType.CASH)
    first = create_cash_balance(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        name="Synthetic Cash Fact A",
        amount="10.00",
    )
    second = create_cash_balance(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        name="Synthetic Cash Fact B",
        amount="20.00",
    )
    debt = create_debt(
        session,
        reporting_month_id=month.id,
        debt_type=DebtType.CREDIT_CARD,
        name="Synthetic Multi Card",
        current_balance="5.00",
    )
    link_debt_to_account(session, debt.id, account.id)
    return month, first, second


def _assert_linked_pair_readable(session: Session, month_id: int) -> None:
    session.expire_all()
    pairs = linked_pairs_for_month(session, month_id)
    assert len(pairs) == 1
    assert pairs[0].account_id is not None


def _patch_paused_ensure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_modules: tuple[object, ...],
    reached: Event,
    release: Event,
) -> None:
    original = linked_pairs_service.ensure_linked_pair_balance_evidence_survives

    def paused(session: Session, *args: object, **kwargs: object) -> None:
        original(session, *args, **kwargs)
        reached.set()
        assert release.wait(10)

    for module in target_modules:
        monkeypatch.setattr(module, "ensure_linked_pair_balance_evidence_survives", paused)


def test_cash_delete_vs_deposit_delete_one_winner_keeps_linked_pair_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, database = session_for(tmp_path)
    reached = Event()
    release = Event()
    try:
        month, cash, deposit = _seed_linked_cash_and_deposit(session)
        month_id = month.id
        cash_id = cash.id
        deposit_id = deposit.id
        _patch_paused_ensure(
            monkeypatch,
            target_modules=(cash_service,),
            reached=reached,
            release=release,
        )

        outcomes: dict[str, str] = {}

        def remove_cash() -> None:
            with database.session_factory() as child:
                try:
                    delete_cash_balance(child, cash_id)
                    outcomes["cash"] = "ok"
                except LinkedPairBalanceEvidenceConflictError:
                    outcomes["cash"] = "conflict"

        def remove_deposit() -> None:
            with database.session_factory() as child:
                try:
                    delete_deposit_snapshot(child, deposit_id)
                    outcomes["dep"] = "ok"
                except LinkedPairBalanceEvidenceConflictError:
                    outcomes["dep"] = "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(remove_cash)
            assert reached.wait(10)
            second = executor.submit(remove_deposit)
            release.set()
            first.result(timeout=15)
            second.result(timeout=15)

        assert outcomes == {"cash": "ok", "dep": "conflict"}
        _assert_linked_pair_readable(session, month_id)
        assert session.get(CashBalance, cash_id) is None
        assert session.get(DepositSnapshot, deposit_id) is not None
    finally:
        session.close()
        database.engine.dispose()


def test_cash_delete_vs_cash_delete_one_winner_keeps_linked_pair_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, database = session_for(tmp_path)
    reached = Event()
    release = Event()
    try:
        month, first_row, second_row = _seed_two_linked_cash_facts(session)
        month_id = month.id
        first_id = first_row.id
        second_id = second_row.id
        original = linked_pairs_service.ensure_linked_pair_balance_evidence_survives
        paused_once = Event()

        def paused(sess: Session, *args: object, **kwargs: object) -> None:
            original(sess, *args, **kwargs)
            if paused_once.is_set():
                return
            paused_once.set()
            reached.set()
            assert release.wait(10)

        monkeypatch.setattr(cash_service, "ensure_linked_pair_balance_evidence_survives", paused)

        outcomes: dict[int, str] = {}

        def remove(balance_id: int) -> None:
            with database.session_factory() as child:
                try:
                    delete_cash_balance(child, balance_id)
                    outcomes[balance_id] = "ok"
                except LinkedPairBalanceEvidenceConflictError:
                    outcomes[balance_id] = "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(remove, first_id)
            assert reached.wait(10)
            future_b = executor.submit(remove, second_id)
            release.set()
            future_a.result(timeout=15)
            future_b.result(timeout=15)

        assert set(outcomes.values()) == {"ok", "conflict"}
        assert list(outcomes.values()).count("ok") == 1
        _assert_linked_pair_readable(session, month_id)
        remaining = [
            session.get(CashBalance, first_id),
            session.get(CashBalance, second_id),
        ]
        assert sum(row is not None for row in remaining) == 1
    finally:
        session.close()
        database.engine.dispose()


def test_cash_delete_vs_exclude_update_one_winner_keeps_linked_pair_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, database = session_for(tmp_path)
    reached = Event()
    release = Event()
    try:
        month, first_row, second_row = _seed_two_linked_cash_facts(session)
        month_id = month.id
        first_id = first_row.id
        second_id = second_row.id
        _patch_paused_ensure(
            monkeypatch,
            target_modules=(cash_service,),
            reached=reached,
            release=release,
        )

        outcomes: dict[str, str] = {}

        def remove() -> None:
            with database.session_factory() as child:
                try:
                    delete_cash_balance(child, first_id)
                    outcomes["delete"] = "ok"
                except LinkedPairBalanceEvidenceConflictError:
                    outcomes["delete"] = "conflict"

        def exclude() -> None:
            with database.session_factory() as child:
                try:
                    update_cash_balance(child, second_id, include_in_capital=False)
                    outcomes["exclude"] = "ok"
                except LinkedPairBalanceEvidenceConflictError:
                    outcomes["exclude"] = "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_delete = executor.submit(remove)
            assert reached.wait(10)
            future_exclude = executor.submit(exclude)
            release.set()
            future_delete.result(timeout=15)
            future_exclude.result(timeout=15)

        assert outcomes == {"delete": "ok", "exclude": "conflict"}
        _assert_linked_pair_readable(session, month_id)
        assert session.get(CashBalance, first_id) is None
        persisted = session.get(CashBalance, second_id)
        assert persisted is not None
        assert persisted.include_in_capital is True
    finally:
        session.close()
        database.engine.dispose()


def test_evidence_guard_serializes_even_if_caller_skips_month_writable_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Protect the invariant inside ensure_, not only via caller ordering."""
    session, database = session_for(tmp_path)
    reached = Event()
    release = Event()
    try:
        month, cash, deposit = _seed_linked_cash_and_deposit(session)
        month_id = month.id
        cash_id = cash.id
        deposit_id = deposit.id

        def select_only_month(_session: Session, child: object) -> ReportingMonth:
            reporting_month = _session.get(ReportingMonth, child.reporting_month_id)
            assert reporting_month is not None
            return reporting_month

        monkeypatch.setattr(cash_service, "require_editable_child_month", select_only_month)
        monkeypatch.setattr(deposits_service, "require_editable_child_month", select_only_month)
        _patch_paused_ensure(
            monkeypatch,
            target_modules=(cash_service,),
            reached=reached,
            release=release,
        )

        outcomes: dict[str, str] = {}

        def remove_cash() -> None:
            with database.session_factory() as child:
                try:
                    delete_cash_balance(child, cash_id)
                    outcomes["cash"] = "ok"
                except LinkedPairBalanceEvidenceConflictError:
                    outcomes["cash"] = "conflict"

        def remove_deposit() -> None:
            with database.session_factory() as child:
                try:
                    delete_deposit_snapshot(child, deposit_id)
                    outcomes["dep"] = "ok"
                except LinkedPairBalanceEvidenceConflictError:
                    outcomes["dep"] = "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(remove_cash)
            assert reached.wait(10)
            second = executor.submit(remove_deposit)
            release.set()
            first.result(timeout=15)
            second.result(timeout=15)

        assert outcomes == {"cash": "ok", "dep": "conflict"}
        _assert_linked_pair_readable(session, month_id)
    finally:
        session.close()
        database.engine.dispose()


def test_sequential_last_fact_removal_conflicts_and_keeps_read_valid(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month, cash, deposit = _seed_linked_cash_and_deposit(session)
        month_id = month.id
        cash_id = cash.id
        deposit_id = deposit.id
        delete_cash_balance(session, cash_id)
        _assert_linked_pair_readable(session, month_id)
        with pytest.raises(LinkedPairBalanceEvidenceConflictError):
            delete_deposit_snapshot(session, deposit_id)
        _assert_linked_pair_readable(session, month_id)
        assert session.get(DepositSnapshot, deposit_id) is not None
    finally:
        session.close()
        database.engine.dispose()
