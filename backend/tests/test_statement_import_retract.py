"""M06-04 statement retract: provenance, financial undo, and re-import."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from _statement_pdf import build_income_report_pdf
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_statement_import_apply import (
    SYN_ISIN,
    apply,
    build_env,
    counts,
    mappings,
    preview,
    selection_from_row,
    session_for,
)

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType
from hermes_finance.main import create_app
from hermes_finance.persistence import Base, InvestmentCashFlow
from hermes_finance.services.accounts import create_account
from hermes_finance.services.applied_statement_events import (
    StatementEventStatus,
    StatementLinkMode,
    get_applied_statement_event,
    get_applied_statement_event_by_identity,
    list_applied_statement_event_revisions,
    list_applied_statement_events,
)
from hermes_finance.services.investment_cash_flows import (
    create_investment_cash_flow,
    delete_investment_cash_flow,
    list_investment_cash_flows,
)
from hermes_finance.services.reporting_months import close_reporting_month
from hermes_finance.services.statement_import_apply import (
    StatementApplyAction,
    StatementApplyItemAction,
)
from hermes_finance.services.statement_import_preparation import prepare_income_report_apply
from hermes_finance.services.statement_import_retract import (
    StatementRetractError,
    retract_applied_statement_event,
    retract_statement_backed_cash_flow,
)
from hermes_finance.statement_import import DuplicateClass
from hermes_finance.statement_import.dto import ALFA_DEPOSITORY_INCOME_PROVIDER


def _passive_total(session: Session) -> int:
    return sum(flow.net_amount_kopecks for flow in list_investment_cash_flows(session))


def test_statement_created_retract_removes_financial_effect(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        applied = apply(session, document, account_id, (selection_from_row(row),))
        assert applied.success is True
        event_id = applied.items[0].applied_statement_event_id
        flow_id = applied.items[0].investment_cash_flow_id
        assert _passive_total(session) == 1000

        result = retract_applied_statement_event(session, event_id)
        assert result.cash_flow_deleted is True
        assert result.investment_cash_flow_id is None
        assert result.link_mode == StatementLinkMode.STATEMENT_CREATED.value
        assert list_investment_cash_flows(session) == []
        assert _passive_total(session) == 0
        assert session.get(InvestmentCashFlow, flow_id) is None

        event = get_applied_statement_event(session, event_id)
        assert event.status == StatementEventStatus.RETRACTED.value
        assert event.investment_cash_flow_id is None
        assert event.retracted_at is not None
        revisions = list_applied_statement_event_revisions(session, event_id)
        assert [item.revision_kind for item in revisions] == ["apply", "retract"]
        assert revisions[0].gross_amount_kopecks == revisions[1].gross_amount_kopecks
        assert (
            get_applied_statement_event_by_identity(
                session,
                provider=ALFA_DEPOSITORY_INCOME_PROVIDER,
                natural_identity=row.natural_identity,
            )
            is None
        )
        assert counts(session) == (1, 2, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_linked_existing_retract_keeps_original_flow(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instruments = build_env(session)
        manual = create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instruments[SYN_ISIN],
            flow_type="dividend",
            event_date=date(2026, 1, 20),
            gross_amount="11.50",
            tax_amount="1.50",
            commission_amount="0.00",
            net_amount="10.00",
            source="manual",
            notes="keep me",
        )
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        linked = apply(
            session,
            document,
            account_id,
            (
                selection_from_row(
                    row,
                    action=StatementApplyAction.LINK_EXISTING,
                    existing_cash_flow_id=manual.id,
                    expected_candidate_ids=(manual.id,),
                ),
            ),
        )
        assert linked.success is True
        event_id = linked.items[0].applied_statement_event_id

        result = retract_applied_statement_event(session, event_id)
        assert result.cash_flow_deleted is False
        assert result.investment_cash_flow_id == manual.id
        session.refresh(manual)
        assert session.get(InvestmentCashFlow, manual.id) is not None
        assert manual.source == "manual"
        assert manual.notes == "keep me"
        assert manual.net_amount_kopecks == 1000
        assert _passive_total(session) == 1000
        event = get_applied_statement_event(session, event_id)
        assert event.status == StatementEventStatus.RETRACTED.value
        assert event.investment_cash_flow_id is None
    finally:
        session.close()
        database.engine.dispose()


def test_retract_closed_month_fails_closed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        applied = apply(session, document, account_id, (selection_from_row(row),))
        close_reporting_month(session, month_id)
        with pytest.raises(StatementRetractError) as error:
            retract_applied_statement_event(session, applied.items[0].applied_statement_event_id)
        assert error.value.code == "closed_month"
        assert counts(session) == (1, 1, 1)
        assert _passive_total(session) == 1000
    finally:
        session.close()
        database.engine.dispose()


def test_retract_rejects_not_statement_backed_flow(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instruments = build_env(session)
        manual = create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instruments[SYN_ISIN],
            flow_type="dividend",
            event_date=date(2026, 1, 20),
            gross_amount="11.50",
            tax_amount="1.50",
            commission_amount="0.00",
            net_amount="10.00",
            source="manual",
        )
        with pytest.raises(StatementRetractError) as error:
            retract_statement_backed_cash_flow(session, manual.id)
        assert error.value.code == "not_statement_backed"
        assert session.get(InvestmentCashFlow, manual.id) is not None
    finally:
        session.close()
        database.engine.dispose()


def test_repeated_retract_is_typed_already_retracted(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        applied = apply(session, document, account_id, (selection_from_row(row),))
        event_id = applied.items[0].applied_statement_event_id
        retract_applied_statement_event(session, event_id)
        with pytest.raises(StatementRetractError) as error:
            retract_applied_statement_event(session, event_id)
        assert error.value.code == "already_retracted"
        revisions = list_applied_statement_event_revisions(session, event_id)
        assert [item.revision_kind for item in revisions] == ["apply", "retract"]
    finally:
        session.close()
        database.engine.dispose()


def test_retract_rolls_back_on_partial_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        applied = apply(session, document, account_id, (selection_from_row(row),))
        event_id = applied.items[0].applied_statement_event_id
        original_delete = Session.delete

        def boom(self: Session, instance: object) -> None:
            if isinstance(instance, InvestmentCashFlow):
                raise RuntimeError("synthetic delete failure")
            original_delete(self, instance)

        monkeypatch.setattr(Session, "delete", boom)
        with pytest.raises(RuntimeError, match="synthetic delete failure"):
            retract_applied_statement_event(session, event_id)
        session.expire_all()
        assert counts(session) == (1, 1, 1)
        event = get_applied_statement_event(session, event_id)
        assert event.status == StatementEventStatus.ACTIVE.value
        assert event.investment_cash_flow_id is not None
        assert _passive_total(session) == 1000
    finally:
        session.close()
        database.engine.dispose()


def test_generic_delete_of_statement_created_flow_still_blocked(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        applied = apply(session, document, account_id, (selection_from_row(row),))
        with pytest.raises(IntegrityError):
            delete_investment_cash_flow(session, applied.items[0].investment_cash_flow_id)
        session.rollback()
        assert counts(session) == (1, 1, 1)
    finally:
        session.close()
        database.engine.dispose()


def test_same_identity_can_be_imported_again_after_retract(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        first = apply(session, document, account_id, (selection_from_row(row),))
        first_event_id = first.items[0].applied_statement_event_id
        retract_applied_statement_event(session, first_event_id)

        prepared = prepare_income_report_apply(
            session, document=document, account_mappings=mappings(account_id)
        )
        assert prepared.rows[0].duplicate_class is None
        second = apply(session, document, account_id, (selection_from_row(row),))
        assert second.success is True
        assert second.items[0].action is StatementApplyItemAction.CREATED
        assert second.items[0].applied_statement_event_id != first_event_id
        assert len(list_applied_statement_events(session)) == 2
        assert counts(session) == (2, 3, 1)

        again = apply(session, document, account_id, (selection_from_row(row),))
        assert again.success is True
        assert again.items[0].action is StatementApplyItemAction.UNCHANGED
        assert counts(session) == (2, 3, 1)
        prepared_dup = prepare_income_report_apply(
            session, document=document, account_mappings=mappings(account_id)
        )
        assert prepared_dup.rows[0].duplicate_class is DuplicateClass.DUPLICATE
    finally:
        session.close()
        database.engine.dispose()


def test_wrong_mapping_retract_then_correct_reimport(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, brokerage_id, _ = build_env(session)
        iis = create_account(session, name="Synthetic IIS", account_type=AccountType.IIS)
        document = build_income_report_pdf()

        wrong_row = preview(session, document, brokerage_id).rows[0]
        wrong = apply(session, document, brokerage_id, (selection_from_row(wrong_row),))
        assert wrong.success is True
        wrong_event_id = wrong.items[0].applied_statement_event_id
        wrong_flow_id = wrong.items[0].investment_cash_flow_id
        wrong_flow = session.get(InvestmentCashFlow, wrong_flow_id)
        assert wrong_flow is not None
        assert wrong_flow.account_id == brokerage_id
        assert _passive_total(session) == 1000

        retracted = retract_applied_statement_event(session, wrong_event_id)
        assert retracted.cash_flow_deleted is True
        assert list_investment_cash_flows(session) == []
        assert _passive_total(session) == 0
        assert session.get(InvestmentCashFlow, wrong_flow_id) is None

        correct_row = preview(session, document, iis.id).rows[0]
        assert correct_row.natural_identity != wrong_row.natural_identity
        assert correct_row.duplicate_class is None
        correct = apply(session, document, iis.id, (selection_from_row(correct_row),))
        assert correct.success is True
        assert correct.items[0].action is StatementApplyItemAction.CREATED
        correct_flow = list_investment_cash_flows(session)[0]
        assert correct_flow.account_id == iis.id
        assert correct_flow.net_amount_kopecks == 1000
        assert _passive_total(session) == 1000

        prepared = prepare_income_report_apply(
            session, document=document, account_mappings=mappings(iis.id)
        )
        assert prepared.rows[0].duplicate_class is DuplicateClass.DUPLICATE
        second = apply(session, document, iis.id, (selection_from_row(correct_row),))
        assert second.success is True
        assert second.items[0].action is StatementApplyItemAction.UNCHANGED
        assert second.items[0].investment_cash_flow_id == correct_flow.id
        assert len(list_investment_cash_flows(session)) == 1

        frozen = get_applied_statement_event(session, wrong_event_id)
        assert frozen.status == StatementEventStatus.RETRACTED.value
        assert frozen.account_id == brokerage_id
        assert frozen.natural_identity == wrong_row.natural_identity
    finally:
        session.close()
        database.engine.dispose()


def test_linked_existing_can_be_relinked_after_retract(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instruments = build_env(session)
        manual = create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instruments[SYN_ISIN],
            flow_type="dividend",
            event_date=date(2026, 1, 20),
            gross_amount="11.50",
            tax_amount="1.50",
            commission_amount="0.00",
            net_amount="10.00",
            source="manual",
        )
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        first = apply(
            session,
            document,
            account_id,
            (
                selection_from_row(
                    row,
                    action=StatementApplyAction.LINK_EXISTING,
                    existing_cash_flow_id=manual.id,
                    expected_candidate_ids=(manual.id,),
                ),
            ),
        )
        retract_applied_statement_event(session, first.items[0].applied_statement_event_id)
        relinked = apply(
            session,
            document,
            account_id,
            (
                selection_from_row(
                    row,
                    action=StatementApplyAction.LINK_EXISTING,
                    existing_cash_flow_id=manual.id,
                    expected_candidate_ids=(manual.id,),
                ),
            ),
        )
        assert relinked.success is True
        assert relinked.items[0].action is StatementApplyItemAction.LINKED_EXISTING
        assert relinked.items[0].investment_cash_flow_id == manual.id
        assert (
            relinked.items[0].applied_statement_event_id
            != first.items[0].applied_statement_event_id
        )
        session.refresh(manual)
        assert manual.source == "manual"
        assert _passive_total(session) == 1000
    finally:
        session.close()
        database.engine.dispose()


@pytest.fixture
def api_client(tmp_path: Path) -> Generator[tuple[TestClient, object], None, None]:
    database = create_database(tmp_path / "statement-retract-api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client, database
    finally:
        database.engine.dispose()


def _seed_statement_flow(database: object) -> tuple[int, int, int]:
    session = database.session_factory()
    try:
        month_id, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        applied = apply(session, document, account_id, (selection_from_row(row),))
        assert applied.success is True
        item = applied.items[0]
        return month_id, item.applied_statement_event_id, item.investment_cash_flow_id
    finally:
        session.close()


def test_investment_flow_api_exposes_statement_link(
    api_client: tuple[TestClient, object],
) -> None:
    client, database = api_client
    month_id, event_id, flow_id = _seed_statement_flow(database)
    listed = client.get(f"/api/investment-flows?month_id={month_id}")
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["id"] == flow_id
    assert rows[0]["source"] == ALFA_DEPOSITORY_INCOME_PROVIDER
    assert rows[0]["statement_link"] == {
        "applied_statement_event_id": event_id,
        "link_mode": "statement_created",
        "status": "active",
    }
    fetched = client.get(f"/api/investment-flows/{flow_id}")
    assert fetched.status_code == 200
    assert fetched.json()["statement_link"]["applied_statement_event_id"] == event_id


def test_statement_retract_api_removes_created_flow(
    api_client: tuple[TestClient, object],
) -> None:
    client, database = api_client
    month_id, event_id, flow_id = _seed_statement_flow(database)
    response = client.post(f"/api/statement-import/applied-events/{event_id}/retract")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cash_flow_deleted"] is True
    assert body["applied_statement_event_id"] == event_id
    listed = client.get(f"/api/investment-flows?month_id={month_id}")
    assert listed.json() == []
    missing = client.get(f"/api/investment-flows/{flow_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    repeated = client.post(f"/api/statement-import/applied-events/{event_id}/retract")
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "already_retracted"


def test_statement_retract_api_not_statement_backed(
    api_client: tuple[TestClient, object],
) -> None:
    client, database = api_client
    session = database.session_factory()
    try:
        month_id, account_id, instruments = build_env(session)
        manual = create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instruments[SYN_ISIN],
            flow_type="dividend",
            event_date=date(2026, 1, 20),
            gross_amount="11.50",
            tax_amount="1.50",
            commission_amount="0.00",
            net_amount="10.00",
            source="manual",
        )
        flow_id = manual.id
    finally:
        session.close()
    fetched = client.get(f"/api/investment-flows/{flow_id}")
    assert fetched.status_code == 200
    assert fetched.json()["statement_link"] is None
    response = client.post(f"/api/statement-import/cash-flows/{flow_id}/retract")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_statement_backed"


def test_generic_delete_api_still_returns_typed_conflict(
    api_client: tuple[TestClient, object],
) -> None:
    client, database = api_client
    _month_id, _event_id, flow_id = _seed_statement_flow(database)
    response = client.delete(f"/api/investment-flows/{flow_id}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert "integrity" in response.json()["error"]["message"].lower()
