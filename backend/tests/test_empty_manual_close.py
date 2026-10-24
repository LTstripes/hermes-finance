"""Synthetic #952 financial-presence, command, writer and audit acceptance."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from test_statement_import_mybroker import database as database

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    Base,
    CashBalance,
    Debt,
    DepositSnapshot,
    ExpenseEntry,
    ExternalFlow,
    IncomeEntry,
    InKindMovement,
    Instrument,
    IntentionalEmptyCloseReceipt,
    InvestmentCashFlow,
    MonthlyComment,
    PlannedBudgetLine,
    PositionSnapshot,
    PropertySnapshot,
    ReportingMonth,
    SavingAllocation,
)
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.close_readiness import build_close_readiness
from hermes_finance.services.intentional_empty_close import (
    IntentionalEmptyCloseCommand,
    close_intentionally_empty_month,
    read_intentional_empty_close,
)
from hermes_finance.services.month_actual_facts import has_month_actual_facts
from hermes_finance.services.month_clone import clone_reporting_month
from hermes_finance.services.reporting_months import (
    CloseGuardError,
    close_reporting_month,
    create_reporting_month,
    delete_reporting_month,
    reopen_reporting_month,
    update_reporting_month,
)

DAY = date(2030, 1, 31)


def clone_templates(session, family="all", amount=12345):
    source = month_for(session)
    if family in {"all", "income"}:
        session.add(
            IncomeEntry(
                reporting_month_id=source.id,
                income_type="salary",
                name="Salary settings",
                gross_amount_kopecks=amount,
                tax_amount_kopecks=0,
                net_amount_kopecks=amount,
                is_recurring=True,
                received_at=None,
            )
        )
    if family in {"all", "expense"}:
        session.add(
            ExpenseEntry(
                reporting_month_id=source.id,
                category="Recurring expense",
                amount_kopecks=amount,
                expense_type="mandatory",
                is_recurring=True,
            )
        )
    if family in {"all", "saving"}:
        session.add(
            SavingAllocation(
                reporting_month_id=source.id,
                destination="Planned saving",
                amount_kopecks=amount,
            )
        )
    session.commit()
    return clone_reporting_month(
        session,
        source.id,
        target_year=2030,
        target_month=2,
        snapshot_date=date(2030, 2, 28),
    )


@pytest.mark.parametrize("family", ["all", "income", "expense", "saving"])
@pytest.mark.parametrize("amount", [0, 12345])
def test_real_clone_templates_block_readiness_and_authoritative_close(db, family, amount):
    with db.session_factory() as session:
        target = clone_templates(session, family, amount)
        target_id = target.id
        assert not has_month_actual_facts(session, target)
        assert not build_close_readiness(session, target_id, today=date(2030, 2, 28)).can_close
        with pytest.raises(CloseGuardError) as error:
            close_reporting_month(session, target_id)
        assert error.value.code == "empty_manual_month"
    with TestClient(create_app(db)) as client:
        readiness = client.get(f"/api/months/{target_id}/close-readiness").json()
        assert not readiness["can_close"]
        assert "empty_manual_month" in [item["code"] for item in readiness["items"]]
        workflow = client.get(f"/api/months/{target_id}/close-workflow").json()
        assert not workflow["readiness"]["can_close"]
        blocked = client.post(f"/api/months/{target_id}/close")
        assert blocked.status_code == 422
        assert blocked.json()["error"]["code"] == "empty_manual_month"
    with db.session_factory() as session:
        assert session.get(ReportingMonth, target_id).status == "draft"


@pytest.mark.parametrize("family", ["income", "expense", "saving"])
@pytest.mark.parametrize("amount", ["0.00", "123.45"])
def test_clone_requires_explicit_amount_confirmation_including_unchanged_and_zero(
    db, family, amount
):
    from hermes_finance.services.expenses import update_expense_entry, update_saving_allocation
    from hermes_finance.services.incomes import update_income_entry

    model, update_row = {
        "income": (IncomeEntry, update_income_entry),
        "expense": (ExpenseEntry, update_expense_entry),
        "saving": (SavingAllocation, update_saving_allocation),
    }[family]
    with db.session_factory() as session:
        target = clone_templates(session)
        row = session.scalar(select(model).where(model.reporting_month_id == target.id))
        update_row(session, row.id, notes="A note does not confirm an amount")
        assert not has_month_actual_facts(session, target)
        update_row(session, row.id)
        assert not has_month_actual_facts(session, target)
        changes = (
            {"gross_amount": amount, "tax_amount": "0.00", "net_amount": amount}
            if family == "income"
            else {"amount": amount}
        )
        update_row(session, row.id, **changes)
        session.expire_all()
        assert has_month_actual_facts(session, target)
        assert build_close_readiness(session, target.id, today=date(2030, 2, 28)).can_close
        # Confirmation belongs to this period only; re-clone retires it.
        following = clone_reporting_month(
            session,
            target.id,
            target_year=2030,
            target_month=3,
            snapshot_date=date(2030, 3, 31),
        )
        assert not has_month_actual_facts(session, following)
        assert close_reporting_month(session, target.id).status == "closed"


@pytest.fixture
def db(tmp_path):
    database = create_database(tmp_path / "synthetic-empty-close.db")
    Base.metadata.create_all(database.engine)
    yield database
    database.engine.dispose()


@pytest.mark.parametrize("family", ["income", "expense", "saving"])
def test_fresh_salary_expense_saving_zero_and_null_salary_date_are_actuals(db, family):
    from hermes_finance.services.expenses import create_expense_entry, create_saving_allocation
    from hermes_finance.services.incomes import create_income_entry

    with db.session_factory() as session:
        month = month_for(session)
        if family == "income":
            row = create_income_entry(
                session,
                reporting_month_id=month.id,
                income_type="salary",
                name="Explicit zero",
                gross_amount="0.00",
                tax_amount="0.00",
                net_amount="0.00",
                is_recurring=True,
                received_at=None,
            )
        elif family == "expense":
            row = create_expense_entry(
                session,
                reporting_month_id=month.id,
                category="Explicit zero",
                amount="0.00",
                expense_type="mandatory",
                is_recurring=True,
            )
        else:
            row = create_saving_allocation(
                session,
                reporting_month_id=month.id,
                destination="Explicit zero",
                amount="0.00",
            )
        assert row.actual_fact_origin == "saved_actual_v1"
        assert has_month_actual_facts(session, month)
        assert close_reporting_month(session, month.id).status == "closed"


@pytest.mark.parametrize("family", ["income", "expense", "saving"])
def test_http_clone_confirmation_requires_amount_and_preserves_zero(db, family):
    model, path, field = {
        "income": (IncomeEntry, "incomes", "net_amount"),
        "expense": (ExpenseEntry, "expenses", "amount"),
        "saving": (SavingAllocation, "savings", "amount"),
    }[family]
    with db.session_factory() as session:
        month = clone_templates(session, family)
        month_id = month.id
        row_id = session.scalar(select(model.id).where(model.reporting_month_id == month_id))
    with TestClient(create_app(db)) as client:
        url = f"/api/{path}/{row_id}"
        note = client.patch(url, json={"notes": "Still a template"})
        assert note.status_code == 200, note.text
        assert not client.get(f"/api/months/{month_id}/close-readiness").json()["can_close"]
        invalid = client.patch(url, json={field: {"amount": "-1.00", "currency": "RUB"}})
        assert invalid.status_code == 422
        assert not client.get(f"/api/months/{month_id}/close-readiness").json()["can_close"]
        confirmed = client.patch(url, json={field: {"amount": "0.00", "currency": "RUB"}})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()[field]["amount"] == "0.00"
        assert client.get(f"/api/months/{month_id}/close-readiness").json()["can_close"]
        assert client.post(f"/api/months/{month_id}/close").status_code == 200


def month_for(session):
    return create_reporting_month(session, year=2030, month=1, snapshot_date=DAY)


def command_for(session, reporting_month, request_id="intent-1", **changes):
    option = build_close_readiness(session, reporting_month.id, today=DAY).intentional_empty_close
    assert option is not None
    return IntentionalEmptyCloseCommand.model_validate(
        {
            **{k: v for k, v in option.items() if k != "eligible"},
            "request_id": request_id,
            "reason": "Intentionally no recorded financial facts",
            **changes,
        }
    )


def economic_counts(session):
    # Capture all economic AND non-economic tables, not just the tested allowlist.
    return {
        table.name: session.scalar(select(func.count()).select_from(table))
        for table in Base.metadata.sorted_tables
        if table.name not in {"intentional_empty_close_receipts"}
    }


def add_family(session, month, family, amount=0):
    account = Account(name="Synthetic account", account_type="brokerage")
    instrument = Instrument(name="Synthetic stock", instrument_type="stock", currency="RUB")
    session.add_all([account, instrument])
    session.flush()
    shared = {"reporting_month_id": month.id}
    rows = {
        "cash": lambda: CashBalance(**shared, name="Explicit cash", amount_kopecks=amount),
        "deposit": lambda: DepositSnapshot(
            **shared,
            account_id=account.id,
            name="Deposit",
            deposit_type="deposit",
            balance_kopecks=amount,
            annual_rate_basis_points=0,
            expected_monthly_interest_kopecks=0,
        ),
        "position": lambda: PositionSnapshot(
            **shared,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=1,
            average_cost_per_unit_kopecks=0,
            market_price_per_unit_kopecks=0,
            market_value_kopecks=amount,
            cost_basis_kopecks=0,
            unrealized_result_kopecks=0,
            price_date=DAY,
            price_source="manual",
        ),
        "income": lambda: IncomeEntry(
            **shared,
            income_type="other",
            name="Income",
            gross_amount_kopecks=amount,
            tax_amount_kopecks=0,
            net_amount_kopecks=amount,
        ),
        "expense": lambda: ExpenseEntry(
            **shared, category="Expense", amount_kopecks=amount, expense_type="other"
        ),
        "saving": lambda: SavingAllocation(**shared, destination="Saving", amount_kopecks=amount),
        "debt": lambda: Debt(
            **shared, name="Debt", debt_type="credit_card", current_balance_kopecks=amount
        ),
        "property": lambda: PropertySnapshot(
            **shared,
            name="Property",
            estimated_value_kopecks=amount,
            mortgage_balance_kopecks=0,
            monthly_payment_kopecks=0,
        ),
        "investment": lambda: InvestmentCashFlow(
            **shared,
            account_id=account.id,
            flow_type="other",
            event_date=DAY,
            gross_amount_kopecks=amount,
            tax_amount_kopecks=0,
            commission_amount_kopecks=0,
            net_amount_kopecks=amount,
            source="manual",
        ),
        "external": lambda: ExternalFlow(
            **shared,
            account_id=account.id,
            event_date=DAY,
            kind="external_contribution",
            direction="contribution",
            boundary_amount_kopecks=amount,
            currency="RUB",
            source="manual",
        ),
        "in_kind": lambda: InKindMovement(
            **shared,
            event_date=DAY,
            movement_kind="external_in",
            destination_account_id=account.id,
            quantity=None,
            provenance_kind="manual",
        ),
    }
    if family == "valuation":
        from hermes_finance.services.external_flows import create_external_flow
        from hermes_finance.services.valuation_boundaries import create_observed_valuation_point
        from hermes_finance.services.valuation_material_signature import (
            material_signature_for_boundary,
        )

        # A sanctioned point needs an actual boundary in this same month. This
        # case covers their valid combined presence, not a standalone point.
        session.add(
            AccountPerformanceScopeMembership(
                account_id=account.id,
                effective_from=date(2030, 1, 1),
                effective_to=DAY,
                include_in_returns=True,
            )
        )
        session.commit()
        boundary = create_external_flow(
            session,
            **shared,
            account_id=account.id,
            event_date=DAY,
            kind="external_contribution",
            direction="contribution",
            boundary_amount="0.00",
        )
        signature = material_signature_for_boundary(
            session,
            scope="account",
            account_id=account.id,
            external_flow_id=boundary.id,
            boundary_group_id=None,
        )
        assert signature is not None
        return create_observed_valuation_point(
            session,
            **shared,
            scope="account",
            account_id=account.id,
            observed_date=DAY,
            total_value=f"{amount // 100}.{amount % 100:02d}",
            performance_currency="RUB",
            coverage="unknown",
            quality="unknown",
            provenance_kind="manual",
            relation="pre_external_flow",
            external_flow_id=boundary.id,
            expected_material_signature=signature,
        )
    else:
        row = rows[family]()
    session.add(row)
    session.commit()
    return row


@pytest.mark.parametrize(
    "family",
    [
        "cash",
        "deposit",
        "position",
        "income",
        "expense",
        "saving",
        "debt",
        "property",
        "investment",
        "external",
        "in_kind",
        "valuation",
    ],
)
@pytest.mark.parametrize("amount", [0, 12345])
@pytest.mark.parametrize("transport", ["service", "http"])
def test_each_actual_family_is_month_scoped_and_explicit_zero_counts(db, family, amount, transport):
    with db.session_factory() as session:
        month = month_for(session)
        row = add_family(session, month, family, amount)
        assert has_month_actual_facts(session, month)
        readiness = build_close_readiness(session, month.id, today=DAY)
        assert readiness.can_close
        assert readiness.intentional_empty_close is None
        if transport == "service":
            assert close_reporting_month(session, month.id).status == "closed"
        else:
            with TestClient(create_app(db)) as client:
                result = client.post(f"/api/months/{month.id}/close")
                assert result.status_code == 200, result.text
                assert result.json()["status"] == "closed"
        session.refresh(row)
        assert row.reporting_month_id == month.id
        # Neither another period's facts nor global catalogue can fill March.
        march = create_reporting_month(session, year=2030, month=3, snapshot_date=date(2030, 3, 31))
        assert not has_month_actual_facts(session, march)


def test_empty_header_notes_plan_catalogue_forecast_and_source_journal_are_not_actuals(db):
    from test_statement_import_mybroker import FILENAME, fixture

    from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
    from hermes_finance.services.source_intake import save_intake

    with db.session_factory() as session:
        month = month_for(session)
        account = Account(name="Catalogue only", account_type="brokerage")
        instrument = Instrument(name="Catalogue stock", instrument_type="stock", currency="RUB")
        session.add_all(
            [
                account,
                instrument,
                MonthlyComment(reporting_month_id=month.id, position=1, text="Only a note"),
                PlannedBudgetLine(
                    reporting_month_id=month.id,
                    category="Plan",
                    expense_type="other",
                    planned_amount_kopecks=0,
                ),
            ]
        )
        session.commit()
        create_expected_cash_flow(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=instrument.id,
            flow_type="dividend",
            expected_date=DAY,
            gross_amount="123.00",
            source="manual",
            source_as_of_date=DAY,
            forecast_version="v1",
        )
        save_intake(session, document=fixture(), filename=FILENAME, request_id="journal-only")
        before = economic_counts(session)
        assert not has_month_actual_facts(session, month)
        with pytest.raises(CloseGuardError) as error:
            close_reporting_month(session, month.id)
        assert error.value.code == "empty_manual_month"
        assert economic_counts(session) == before
        session.refresh(month)
        assert month.status == "draft"


def test_net_zero_postings_are_presence_not_a_zero_total(db):
    with db.session_factory() as session:
        month = month_for(session)
        row = add_family(session, month, "investment", 100)
        session.add(
            InvestmentCashFlow(
                reporting_month_id=month.id,
                account_id=row.account_id,
                flow_type="other",
                event_date=DAY,
                gross_amount_kopecks=0,
                tax_amount_kopecks=0,
                commission_amount_kopecks=100,
                net_amount_kopecks=-100,
                source="manual",
            )
        )
        session.commit()
        assert session.scalar(select(func.sum(InvestmentCashFlow.net_amount_kopecks))) == 0
        assert close_reporting_month(session, month.id).status == "closed"


def test_intentional_success_lost_ack_replay_audit_no_economic_rows(db):
    with db.session_factory() as session:
        month = month_for(session)
        command = command_for(session, month)
        before = economic_counts(session)
        receipt = close_intentionally_empty_month(session, month.id, command)
        assert receipt.reason == command.reason
        assert receipt.expected_identity == command.expected_identity
        assert receipt.closed_at is not None
        assert economic_counts(session) == before
        assert session.get(ReportingMonth, month.id).status == "closed"
        assert read_intentional_empty_close(session, month.id, command.request_id).id == receipt.id
        assert close_intentionally_empty_month(session, month.id, command).id == receipt.id
        assert session.scalar(select(func.count()).select_from(IntentionalEmptyCloseReceipt)) == 1
        assert not has_month_actual_facts(session, month)
        for sql in [
            "UPDATE intentional_empty_close_receipts SET reason='rewritten'",
            "DELETE FROM intentional_empty_close_receipts",
        ]:
            with pytest.raises(IntegrityError, match="immutable"):
                session.execute(text(sql))
            session.rollback()


@pytest.mark.parametrize(
    "change",
    [
        {"month_id": 999},
        {"year": 2031},
        {"month": 2},
        {"snapshot_date": date(2030, 2, 1)},
        {"expected_identity": "0" * 64},
    ],
)
def test_wrong_confirmation_identity_is_atomic(db, change):
    with db.session_factory() as session:
        month = month_for(session)
        command = command_for(session, month, **change)
        with pytest.raises(CloseGuardError) as error:
            close_intentionally_empty_month(session, month.id, command)
        assert error.value.code == "empty_close_identity_changed"
        assert month.status == "draft"
        assert session.scalar(select(func.count()).select_from(IntentionalEmptyCloseReceipt)) == 0


def test_new_fact_and_header_aba_retire_confirmation(db):
    with db.session_factory() as session:
        month = month_for(session)
        command = command_for(session, month)
        create_cash_balance(session, reporting_month_id=month.id, name="Saved zero", amount="0.00")
        with pytest.raises(CloseGuardError) as error:
            close_intentionally_empty_month(session, month.id, command)
        assert error.value.code == "empty_close_facts_present"
        assert month.status == "draft"
        session.execute(text("DELETE FROM cash_balances"))
        session.commit()
        update_reporting_month(session, month.id, snapshot_date=date(2030, 2, 1))
        update_reporting_month(session, month.id, snapshot_date=DAY)
        with pytest.raises(CloseGuardError) as error:
            close_intentionally_empty_month(session, month.id, command)
        assert error.value.code == "empty_close_identity_changed"


def test_reopen_clone_delete_cannot_inherit_consent_but_receipt_survives(db):
    with db.session_factory() as session:
        month = month_for(session)
        command = command_for(session, month)
        receipt = close_intentionally_empty_month(session, month.id, command)
        clone = clone_reporting_month(
            session, month.id, target_year=2030, target_month=2, snapshot_date=date(2030, 2, 28)
        )
        assert clone.status == "draft" and not has_month_actual_facts(session, clone)
        reopened = reopen_reporting_month(session, month.id)
        assert not build_close_readiness(session, reopened.id, today=DAY).can_close
        assert close_intentionally_empty_month(session, month.id, command).id == receipt.id
        assert reopened.status == "draft"  # replay ACK never executes Close again
        stale = command.model_copy(update={"request_id": "new-key"})
        with pytest.raises(CloseGuardError, match="identity changed"):
            close_intentionally_empty_month(session, month.id, stale)
        with pytest.raises(CloseGuardError):
            close_intentionally_empty_month(session, clone.id, stale)
        with pytest.raises(CloseGuardError):
            close_reporting_month(session, reopened.id)
        delete_reporting_month(session, reopened.id)
        assert read_intentional_empty_close(session, month.id, command.request_id).id == receipt.id


def test_legacy_closed_and_non_manual_are_unchanged(db):
    with db.session_factory() as session:
        month = month_for(session)
        month.status = "closed"  # historical CLOSED, not a new bypass path
        session.commit()
        assert close_reporting_month(session, month.id).status == "closed"
        assert build_close_readiness(session, month.id, today=DAY).intentional_empty_close is None
        legacy = create_reporting_month(
            session, year=2030, month=2, snapshot_date=date(2030, 2, 28), source="excel_migration"
        )
        assert close_reporting_month(session, legacy.id).status == "closed"


def test_other_guards_rechecked_inside_writer(db, monkeypatch):
    from hermes_finance.services import broker_months

    with db.session_factory() as session:
        month = month_for(session)
        command = command_for(session, month)

        def source_blocker(candidate_session, month_id):
            assert candidate_session.connection().connection.driver_connection.in_transaction
            assert month_id == month.id
            return (("source_receipt_changed", "Source receipt changed"),)

        monkeypatch.setattr(broker_months, "broker_month_close_blockers", source_blocker)
        assert not build_close_readiness(session, month.id, today=DAY).intentional_empty_close[
            "eligible"
        ]
        with pytest.raises(CloseGuardError) as error:
            close_intentionally_empty_month(session, month.id, command)
        assert error.value.code == "source_receipt_changed"
        assert month.status == "draft"
        assert session.scalar(select(func.count()).select_from(IntentionalEmptyCloseReceipt)) == 0


def test_duplicate_concurrent_command_has_one_audit(db):
    with db.session_factory() as session:
        month = month_for(session)
        month_id = month.id
        command = command_for(session, month)

    def execute():
        with db.session_factory() as session:
            return close_intentionally_empty_month(session, month_id, command).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: execute(), range(2)))
    assert results[0] == results[1]
    with db.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(IntentionalEmptyCloseReceipt)) == 1


def test_close_reservation_wins_and_child_cannot_write_after_close(db, monkeypatch):
    from hermes_finance.services import month_actual_facts
    from hermes_finance.services.reporting_months import ClosedReportingMonthError

    reserved, release, child_started = Event(), Event(), Event()
    with db.session_factory() as session:
        month = month_for(session)
        month_id = month.id
        command = command_for(session, month)
    original = month_actual_facts.has_month_actual_facts

    def pause_inside_writer(session, candidate):
        assert session.connection().connection.driver_connection.in_transaction
        reserved.set()
        assert release.wait(10)
        return original(session, candidate)

    monkeypatch.setattr(month_actual_facts, "has_month_actual_facts", pause_inside_writer)

    def closer():
        with db.session_factory() as session:
            return close_intentionally_empty_month(session, month_id, command).id

    def child():
        with db.session_factory() as session:
            child_started.set()
            with pytest.raises(ClosedReportingMonthError):
                create_cash_balance(
                    session, reporting_month_id=month_id, name="Too late", amount="0.00"
                )

    with ThreadPoolExecutor(max_workers=2) as pool:
        close = pool.submit(closer)
        assert reserved.wait(10)
        write = pool.submit(child)
        assert child_started.wait(10)
        release.set()
        assert close.result(timeout=15) > 0
        write.result(timeout=15)
    with db.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CashBalance)) == 0


@pytest.mark.parametrize("family", ["trade", "endpoint", "owner_flow"])
def test_accepted_canonical_source_actuals_count_only_while_current(database, family):
    from hermes_finance.persistence import BrokerIdentityMapping
    from hermes_finance.services.broker_identity_mappings import revoke_mapping

    with database.session_factory() as session:
        month = month_for(session)
        assert not has_month_actual_facts(session, month)
        if family == "trade":
            from test_statement_import_executed_trades import accept_source, identity, promote

            source = accept_source(session)
            assert not has_month_actual_facts(session, month)  # accepted S1 alone isn't S2
            promote(session, [identity(source)])
        elif family == "endpoint":
            from test_statement_import_historical_endpoints import accept, attest, setup_source

            intent, _ = setup_source(session)
            assert not has_month_actual_facts(session, month)
            accept(session, attest(session, intent))
        else:
            from test_statement_import_historical_owner_flows import accept, attest, source

            intent = source(session)
            assert not has_month_actual_facts(session, month)
            accept(session, attest(session, intent))
        assert has_month_actual_facts(session, month)
        assert build_close_readiness(session, month.id, today=DAY).can_close
        # No promoted cash/position/financial row was invented by the predicate.
        for model in (CashBalance, PositionSnapshot, IncomeEntry, InvestmentCashFlow):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        if family == "trade":
            from hermes_finance.persistence import ExecutedTradeRevision

            current = session.scalar(select(ExecutedTradeRevision))
            values = {
                column.name: getattr(current, column.name)
                for column in current.__table__.columns
                if column.name not in {"id", "revision", "acceptance_state"}
            }
            session.add(
                ExecutedTradeRevision(
                    **values, revision=current.revision + 1, acceptance_state="retracted"
                )
            )
            session.commit()
        else:
            mapping = session.scalar(
                select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "account")
            )
            revoke_mapping(session, mapping.id, reason="Synthetic dependency retirement")
        assert not has_month_actual_facts(session, month)


def test_real_source_obligation_blocks_intentional_close_and_http(database):
    from test_statement_import_mybroker import FILENAME, fixture

    from hermes_finance.services.source_intake import PENDING, save_intake

    with database.session_factory() as session:
        month = month_for(session)
        command = command_for(session, month)
        save_intake(
            session,
            document=fixture(),
            filename=FILENAME,
            request_id="bound-source",
            account_id=1,
            reporting_month_id=month.id,
        )
        readiness = build_close_readiness(session, month.id, today=DAY)
        assert not readiness.can_close
        assert not readiness.intentional_empty_close["eligible"]
        assert PENDING in [item.code for item in readiness.items]
        before = economic_counts(session)
        with pytest.raises(CloseGuardError) as error:
            close_intentionally_empty_month(session, month.id, command)
        assert error.value.code != "empty_manual_month"
        with TestClient(create_app(database)) as client:
            response = client.post(
                f"/api/months/{month.id}/close-intentionally-empty",
                json=command.model_dump(mode="json"),
            )
            assert response.status_code == 422
        assert economic_counts(session) == before
        assert session.scalar(select(func.count()).select_from(IntentionalEmptyCloseReceipt)) == 0


def test_unsaved_fact_cannot_satisfy_close(db):
    with db.session_factory() as session:
        month = month_for(session)
        session.add(CashBalance(reporting_month_id=month.id, name="Unsaved", amount_kopecks=0))
        with pytest.raises(CloseGuardError) as error:
            close_reporting_month(session, month.id)
        assert error.value.code == "close_pending_mutations"
        assert session.scalar(select(func.count()).select_from(CashBalance)) == 0


@pytest.mark.parametrize("intentional", [False, True])
def test_fact_writer_wins_before_close_reservation(db, intentional):
    reserved, release = Event(), Event()
    with db.session_factory() as session:
        month = month_for(session)
        month_id = month.id
        command = command_for(session, month)

    def writer():
        with db.session_factory() as session:
            session.execute(
                text("UPDATE reporting_months SET status=status WHERE id=:id"), {"id": month_id}
            )
            session.add(
                CashBalance(reporting_month_id=month_id, name="Concurrent zero", amount_kopecks=0)
            )
            session.flush()
            reserved.set()
            assert release.wait(10)
            session.commit()

    def closer():
        with db.session_factory() as session:
            # Prime identity map before the competing commit.
            session.get(ReportingMonth, month_id)
            if intentional:
                with pytest.raises(CloseGuardError) as error:
                    close_intentionally_empty_month(session, month_id, command)
                return error.value.code
            return close_reporting_month(session, month_id).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        write = pool.submit(writer)
        assert reserved.wait(10)
        close = pool.submit(closer)
        release.set()
        write.result(timeout=15)
        assert close.result(timeout=15) == (
            "empty_close_facts_present" if intentional else "closed"
        )


def test_http_matrix_typed_errors_readonly_workflow_and_lost_ack(db, monkeypatch):
    import socket

    with db.session_factory() as session:
        month = month_for(session)
        month_id = month.id
        before = economic_counts(session)
    monkeypatch.setattr(
        socket, "create_connection", lambda *a, **k: pytest.fail("network forbidden")
    )
    app = create_app(db)
    with TestClient(app) as client:
        readiness = client.get(f"/api/months/{month_id}/close-readiness").json()
        assert not readiness["can_close"]
        option = readiness["intentional_empty_close"]
        assert option["eligible"]
        workflow = client.get(f"/api/months/{month_id}/close-workflow").json()
        assert not workflow["readiness"]["can_close"]
        assert "empty_manual_month" in workflow["readiness"]["reason_codes"]
        blocked = client.post(f"/api/months/{month_id}/close")
        assert (
            blocked.status_code == 422 and blocked.json()["error"]["code"] == "empty_manual_month"
        )
        payload = {k: v for k, v in option.items() if k != "eligible"} | {
            "reason": "Intentionally empty",
            "request_id": "http-1",
        }
        for change in [
            {"reason": ""},
            {"reason": "   "},
            {"reason": None},
            {"command": "allow_empty"},
            {"allow_empty": True},
            {"month_id": True},
            {"policy_version": "old"},
        ]:
            assert (
                client.post(
                    f"/api/months/{month_id}/close-intentionally-empty", json=payload | change
                ).status_code
                == 422
            )
        wrong = client.post(
            f"/api/months/{month_id}/close-intentionally-empty", json=payload | {"year": 2031}
        )
        assert (
            wrong.status_code == 409
            and wrong.json()["error"]["code"] == "empty_close_identity_changed"
        )
        ack = client.post(f"/api/months/{month_id}/close-intentionally-empty", json=payload)
        assert ack.status_code == 200, ack.text
        receipt = client.get(f"/api/months/{month_id}/intentional-empty-close-receipts/http-1")
        assert receipt.json() == ack.json()
        assert (
            client.post(f"/api/months/{month_id}/close-intentionally-empty", json=payload).json()
            == ack.json()
        )
        conflict = client.post(
            f"/api/months/{month_id}/close-intentionally-empty",
            json=payload | {"reason": "Different intent"},
        )
        assert conflict.status_code == 409
        assert (
            client.get(
                f"/api/months/{month_id + 1}/intentional-empty-close-receipts/http-1"
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"/api/months/{month_id}/intentional-empty-close-receipts/unknown"
            ).status_code
            == 404
        )
    with db.session_factory() as session:
        assert economic_counts(session) == before
        assert session.scalar(select(func.count()).select_from(IntentionalEmptyCloseReceipt)) == 1


def test_http_restore_epoch_retires_uncommitted_confirmation(db):
    with db.session_factory() as session:
        month_id = month_for(session).id
    with TestClient(create_app(db)) as client:
        option = client.get(f"/api/months/{month_id}/close-readiness").json()[
            "intentional_empty_close"
        ]
        payload = {k: v for k, v in option.items() if k != "eligible"} | {
            "reason": "Synthetic empty",
            "request_id": "restore-stale",
        }
        with db.maintenance.restore():
            pass  # synthetic restore admission epoch, no physical DB replacement
        stale = client.post(f"/api/months/{month_id}/close-intentionally-empty", json=payload)
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "empty_close_identity_changed"
        fresh = client.get(f"/api/months/{month_id}/close-readiness").json()[
            "intentional_empty_close"
        ]
        assert fresh["expected_identity"] != option["expected_identity"]
