import sqlite3
from datetime import date
from pathlib import Path
from threading import Event, Thread, current_thread

import pytest
from _migration_helpers import run_alembic
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    ExternalFlowClassification,
    ExternalFlowDirection,
    ExternalFlowKind,
    ExternalFlowScope,
    ExternalFlowScopeMembership,
    ExternalTransferStatus,
)
from hermes_finance.main import create_app
from hermes_finance.persistence import Account, Base
from hermes_finance.services import _guard, external_flows, transfer_reconciliation
from hermes_finance.services.accounts import create_account
from hermes_finance.services.external_flows import (
    classify_external_flow,
    create_external_flow,
    create_external_transfer_link,
    delete_external_flow,
    update_external_flow,
)
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
    delete_reporting_month,
)
from hermes_finance.services.transfer_reconciliation import (
    create_transfer_reconciliation_evidence,
    delete_transfer_reconciliation_evidence,
    list_transfer_reconciliation_evidence,
)


def _environment(tmp_path: Path) -> tuple[Session, object, int, int, int]:
    database = create_database(tmp_path / "r08-01a.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    source = create_account(session, name="Synthetic Source", account_type=AccountType.BROKERAGE)
    destination = create_account(
        session, name="Synthetic Destination", account_type=AccountType.BROKERAGE
    )
    return session, database, month.id, source.id, destination.id


def _overlap(
    database: object, first, second, entered: Event, attempting: Event, release: Event
) -> list[object]:
    results: list[object] = [None, None]

    def run(index: int, operation) -> None:
        with database.session_factory() as session:
            try:
                results[index] = operation(session)
            except Exception as error:
                session.rollback()
                results[index] = error

    first_thread = Thread(target=run, args=(0, first), name="first")
    second_thread = Thread(target=run, args=(1, second), name="second")
    try:
        first_thread.start()
        assert entered.wait(10), "first writer did not reach the protected read"
        second_thread.start()
        assert attempting.wait(10), "second writer did not attempt the reservation"
    finally:
        release.set()
        first_thread.join(10)
        if second_thread.ident is not None:
            second_thread.join(10)
    assert not first_thread.is_alive() and not second_thread.is_alive()
    return results


def _signal_competing_reservation(monkeypatch, attempting: Event) -> None:
    original = external_flows._reserve_transfer_write

    def reserve(session, **kwargs):
        if current_thread().name == "second":
            attempting.set()
        return original(session, **kwargs)

    monkeypatch.setattr(external_flows, "_reserve_transfer_write", reserve)


def _assert_link_state(session: Session, *link_ids: int) -> None:
    for link_id in link_ids:
        link = external_flows.get_external_transfer_link(session, link_id)
        legs = external_flows.transfer_link_legs(session, link_id)
        expected = "resolved" if external_flows._is_complete_transfer(legs) else "unresolved"
        assert link.status == expected
        for leg in legs:
            assert external_flows.external_flow_transfer_status(session, leg).value == expected


def _synthetic_flow(
    session: Session,
    month_id: int,
    account_id: int,
    direction: str,
    *,
    link_id: int | None = None,
):
    return create_external_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        event_date=date(2030, 5, 15),
        boundary_amount="50.00",
        direction=direction,
        kind=f"external_{direction}",
        scope_membership="stable_in_scope",
        transfer_link_id=link_id,
    )


def test_external_contribution_and_withdrawal_use_exact_explicit_boundary_semantics(
    tmp_path: Path,
) -> None:
    session, database, month_id, source_id, _ = _environment(tmp_path)
    try:
        contribution = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=source_id,
            event_date=date(2030, 5, 10),
            boundary_amount="1234.56",
            direction=ExternalFlowDirection.CONTRIBUTION,
            kind=ExternalFlowKind.EXTERNAL_CONTRIBUTION,
            scope_membership=ExternalFlowScopeMembership.STABLE_IN_SCOPE,
            source="manual",
        )
        withdrawal = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=source_id,
            event_date=date(2030, 5, 11),
            boundary_amount="12.34",
            direction=ExternalFlowDirection.WITHDRAWAL,
            kind=ExternalFlowKind.EXTERNAL_WITHDRAWAL,
            scope_membership=ExternalFlowScopeMembership.STABLE_IN_SCOPE,
            source="manual",
        )

        assert contribution.boundary_amount_kopecks == 123_456
        assert contribution.amount_kopecks == 123_456
        assert contribution.event_date == date(2030, 5, 10)
        assert contribution.direction == "contribution"
        assert contribution.kind == "external_contribution"
        assert withdrawal.boundary_amount_kopecks == 1_234
        assert (
            classify_external_flow(session, contribution.id, scope=ExternalFlowScope.PORTFOLIO)
            is ExternalFlowClassification.EXTERNAL_CONTRIBUTION
        )

        with pytest.raises(ValueError, match="must not be negative"):
            create_external_flow(
                session,
                reporting_month_id=month_id,
                account_id=source_id,
                event_date=date(2030, 5, 12),
                boundary_amount="-0.01",
                direction="contribution",
                kind="external_contribution",
            )
        with pytest.raises(ValueError, match="same movement"):
            create_external_flow(
                session,
                reporting_month_id=month_id,
                account_id=source_id,
                event_date=date(2030, 5, 12),
                boundary_amount="1.00",
                direction="withdrawal",
                kind="external_contribution",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_historical_scope_classification_does_not_follow_current_account_flag(
    tmp_path: Path,
) -> None:
    session, database, month_id, source_id, _ = _environment(tmp_path)
    try:
        asserted_flow = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=source_id,
            event_date=date(2030, 5, 10),
            boundary_amount="123.45",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        assert (
            classify_external_flow(session, asserted_flow.id, scope="portfolio")
            is ExternalFlowClassification.EXTERNAL_CONTRIBUTION
        )

        account = session.get(Account, source_id)
        assert account is not None
        account.include_in_returns = False
        session.commit()

        assert (
            classify_external_flow(session, asserted_flow.id, scope="portfolio")
            is ExternalFlowClassification.EXTERNAL_CONTRIBUTION
        )

        unasserted_flow = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=source_id,
            event_date=date(2030, 5, 11),
            boundary_amount="1.00",
            direction="contribution",
            kind="external_contribution",
        )
        assert (
            classify_external_flow(session, unasserted_flow.id, scope="portfolio")
            is ExternalFlowClassification.NOT_AUTHORITATIVE
        )
    finally:
        session.close()
        database.engine.dispose()


def test_linked_transfer_is_internal_for_portfolio_and_crosses_account_boundary(
    tmp_path: Path,
) -> None:
    session, database, month_id, source_id, destination_id = _environment(tmp_path)
    try:
        link = create_external_transfer_link(session, transfer_key="owner-transfer-1")
        source_flow = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=source_id,
            event_date=date(2030, 5, 13),
            boundary_amount="100.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
            transfer_link_id=link.id,
        )
        assert link.status == ExternalTransferStatus.UNRESOLVED.value
        assert (
            classify_external_flow(session, source_flow.id, scope="portfolio")
            is ExternalFlowClassification.UNRESOLVED
        )

        destination_flow = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=destination_id,
            event_date=date(2030, 5, 14),
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
            transfer_link_id=link.id,
        )
        session.refresh(link)
        assert link.status == ExternalTransferStatus.RESOLVED.value
        assert (
            classify_external_flow(session, source_flow.id, scope="portfolio")
            is ExternalFlowClassification.INTERNAL_TRANSFER
        )
        assert (
            classify_external_flow(session, destination_flow.id, scope="portfolio")
            is ExternalFlowClassification.INTERNAL_TRANSFER
        )
        assert (
            classify_external_flow(session, source_flow.id, scope="account", account_id=source_id)
            is ExternalFlowClassification.EXTERNAL_WITHDRAWAL
        )
        assert (
            classify_external_flow(
                session, destination_flow.id, scope="account", account_id=destination_id
            )
            is ExternalFlowClassification.EXTERNAL_CONTRIBUTION
        )
    finally:
        session.close()
        database.engine.dispose()


def test_one_sided_transfer_stays_unresolved_until_explicit_second_leg(tmp_path: Path) -> None:
    session, database, month_id, source_id, _ = _environment(tmp_path)
    try:
        link = create_external_transfer_link(session, transfer_key="owner-transfer-incomplete")
        flow = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=source_id,
            event_date=date(2030, 5, 15),
            boundary_amount="50.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
            transfer_link_id=link.id,
        )
        assert link.status == "unresolved"
        assert classify_external_flow(session, flow.id, scope="portfolio") == (
            ExternalFlowClassification.UNRESOLVED
        )
    finally:
        session.close()
        database.engine.dispose()


def test_reconciliation_evidence_locks_transfer_leg_identity(tmp_path: Path) -> None:
    session, database, month_id, source_id, destination_id = _environment(tmp_path)
    try:
        link = create_external_transfer_link(session, transfer_key="evidence-locked-link")
        old_leg = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=source_id,
            event_date=date(2030, 5, 15),
            boundary_amount="50.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
            transfer_link_id=link.id,
        )
        evidence = create_transfer_reconciliation_evidence(
            session,
            transfer_link_id=link.id,
            kind="internal_fee",
            amount="1.00",
            currency="RUB",
            source="synthetic-broker-statement",
            evidence_reference="evidence-locked-leg-1",
        )
        replacement_leg = create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=destination_id,
            event_date=date(2030, 5, 16),
            boundary_amount="49.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )

        with pytest.raises(ValueError, match="reconciliation evidence"):
            update_external_flow(session, replacement_leg.id, transfer_link_id=link.id)
        with pytest.raises(ValueError, match="reconciliation evidence"):
            update_external_flow(session, old_leg.id, account_id=destination_id)
        with pytest.raises(ValueError, match="reconciliation evidence"):
            update_external_flow(
                session,
                old_leg.id,
                direction="contribution",
                kind="external_contribution",
            )
        with pytest.raises(ValueError, match="reconciliation evidence"):
            delete_external_flow(session, old_leg.id)
        with pytest.raises(ValueError, match="reconciliation evidence"):
            delete_reporting_month(session, month_id)

        session.expire_all()
        assert session.get(type(old_leg), old_leg.id).transfer_link_id == link.id
        assert session.get(type(replacement_leg), replacement_leg.id).transfer_link_id is None
        assert session.get(type(evidence), evidence.id) is not None
        assert len(list_transfer_reconciliation_evidence(session, transfer_link_id=link.id)) == 1

        delete_transfer_reconciliation_evidence(session, evidence.id)
        update_external_flow(session, replacement_leg.id, transfer_link_id=link.id)
        session.refresh(link)
        assert link.status == "resolved"
    finally:
        session.close()
        database.engine.dispose()


def test_competing_links_cannot_both_claim_an_unlinked_flow(tmp_path: Path, monkeypatch) -> None:
    session, database, month_id, source_id, _ = _environment(tmp_path)
    first_link = create_external_transfer_link(session, transfer_key="race-first")
    second_link = create_external_transfer_link(session, transfer_key="race-second")
    flow = _synthetic_flow(session, month_id, source_id, "withdrawal")
    flow_id, first_id, second_id = flow.id, first_link.id, second_link.id
    session.close()
    entered, attempting, release = Event(), Event(), Event()
    original = external_flows._validate_new_link_leg

    def pause_after_reservation(*args, **kwargs):
        if current_thread().name == "first":
            entered.set()
            assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(external_flows, "_validate_new_link_leg", pause_after_reservation)
    _signal_competing_reservation(monkeypatch, attempting)
    try:
        first, second = _overlap(
            database,
            lambda s: update_external_flow(s, flow_id, transfer_link_id=first_id).id,
            lambda s: update_external_flow(s, flow_id, transfer_link_id=second_id).id,
            entered,
            attempting,
            release,
        )
        assert first == flow_id
        assert isinstance(second, ValueError) and "ownership changed" in str(second)
        with database.session_factory() as check:
            assert check.get(type(flow), flow_id).transfer_link_id == first_id
            _assert_link_state(check, first_id, second_id)
    finally:
        database.engine.dispose()


def test_old_pair_completion_wins_over_stale_relink(tmp_path: Path, monkeypatch) -> None:
    session, database, month_id, source_id, destination_id = _environment(tmp_path)
    old_link = create_external_transfer_link(session, transfer_key="race-old-pair")
    new_link = create_external_transfer_link(session, transfer_key="race-new-pair")
    old_leg = _synthetic_flow(session, month_id, source_id, "withdrawal", link_id=old_link.id)
    old_id, new_id, old_leg_id = old_link.id, new_link.id, old_leg.id
    session.close()
    entered, attempting, release = Event(), Event(), Event()
    original = external_flows._validate_new_link_leg

    def pause_completion(*args, **kwargs):
        if current_thread().name == "first":
            entered.set()
            assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(external_flows, "_validate_new_link_leg", pause_completion)
    _signal_competing_reservation(monkeypatch, attempting)
    try:
        first, second = _overlap(
            database,
            lambda s: (
                _synthetic_flow(s, month_id, destination_id, "contribution", link_id=old_id).id
            ),
            lambda s: update_external_flow(s, old_leg_id, transfer_link_id=new_id).id,
            entered,
            attempting,
            release,
        )
        assert isinstance(first, int)
        assert isinstance(second, ValueError) and "status changed" in str(second)
        with database.session_factory() as check:
            assert check.get(type(old_leg), old_leg_id).transfer_link_id == old_id
            _assert_link_state(check, old_id, new_id)
            assert len(external_flows.transfer_link_legs(check, old_id)) == 2
    finally:
        database.engine.dispose()


def test_relink_wins_before_old_link_receives_another_leg(tmp_path: Path, monkeypatch) -> None:
    session, database, month_id, source_id, destination_id = _environment(tmp_path)
    old_link = create_external_transfer_link(session, transfer_key="relink-first-old")
    new_link = create_external_transfer_link(session, transfer_key="relink-first-new")
    old_leg = _synthetic_flow(session, month_id, source_id, "withdrawal", link_id=old_link.id)
    old_id, new_id, old_leg_id = old_link.id, new_link.id, old_leg.id
    session.close()
    entered, attempting, release = Event(), Event(), Event()
    original_validate = external_flows._validate_new_link_leg
    original_month_guard = external_flows.require_editable_reporting_month

    def pause_relink(*args, **kwargs):
        if current_thread().name == "first":
            entered.set()
            assert release.wait(10)
        return original_validate(*args, **kwargs)

    def signal_completion(session, month_id):
        if current_thread().name == "second":
            attempting.set()
        return original_month_guard(session, month_id)

    monkeypatch.setattr(external_flows, "_validate_new_link_leg", pause_relink)
    monkeypatch.setattr(external_flows, "require_editable_reporting_month", signal_completion)
    try:
        first, second = _overlap(
            database,
            lambda s: update_external_flow(s, old_leg_id, transfer_link_id=new_id).id,
            lambda s: (
                _synthetic_flow(s, month_id, destination_id, "contribution", link_id=old_id).id
            ),
            entered,
            attempting,
            release,
        )
        assert first == old_leg_id
        assert isinstance(second, int)
        with database.session_factory() as check:
            assert check.get(type(old_leg), old_leg_id).transfer_link_id == new_id
            _assert_link_state(check, old_id, new_id)
            assert len(external_flows.transfer_link_legs(check, old_id)) == 1
            assert len(external_flows.transfer_link_legs(check, new_id)) == 1
    finally:
        database.engine.dispose()


def test_evidence_creation_wins_over_stale_relink(tmp_path: Path, monkeypatch) -> None:
    session, database, month_id, source_id, _ = _environment(tmp_path)
    old_link = create_external_transfer_link(session, transfer_key="race-evidence-old")
    new_link = create_external_transfer_link(session, transfer_key="race-evidence-new")
    old_leg = _synthetic_flow(session, month_id, source_id, "withdrawal", link_id=old_link.id)
    old_id, new_id, old_leg_id = old_link.id, new_link.id, old_leg.id
    session.close()
    entered, attempting, release = Event(), Event(), Event()
    original = transfer_reconciliation._transfer_legs

    def pause_evidence(*args, **kwargs):
        if current_thread().name == "first":
            entered.set()
            assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(transfer_reconciliation, "_transfer_legs", pause_evidence)
    _signal_competing_reservation(monkeypatch, attempting)
    try:
        first, second = _overlap(
            database,
            lambda s: (
                create_transfer_reconciliation_evidence(
                    s,
                    transfer_link_id=old_id,
                    kind="internal_fee",
                    amount="1.00",
                    currency="RUB",
                    source="synthetic",
                    evidence_reference="race-evidence",
                ).id
            ),
            lambda s: update_external_flow(s, old_leg_id, transfer_link_id=new_id).id,
            entered,
            attempting,
            release,
        )
        assert isinstance(first, int)
        assert isinstance(second, ValueError) and "reconciliation evidence" in str(second)
        with database.session_factory() as check:
            assert check.get(type(old_leg), old_leg_id).transfer_link_id == old_id
            assert len(list_transfer_reconciliation_evidence(check, transfer_link_id=old_id)) == 1
            _assert_link_state(check, old_id, new_id)
    finally:
        database.engine.dispose()


def test_evidence_creation_blocks_concurrent_bulk_leg_deletion(tmp_path: Path, monkeypatch) -> None:
    session, database, month_id, source_id, _ = _environment(tmp_path)
    link = create_external_transfer_link(session, transfer_key="race-month-evidence")
    leg = _synthetic_flow(session, month_id, source_id, "withdrawal", link_id=link.id)
    link_id, leg_id = link.id, leg.id
    session.close()
    entered, attempting, release = Event(), Event(), Event()
    original_legs = transfer_reconciliation._transfer_legs
    original_guard = _guard.require_editable_reporting_month

    def pause_evidence(*args, **kwargs):
        if current_thread().name == "first":
            entered.set()
            assert release.wait(10)
        return original_legs(*args, **kwargs)

    def signal_month_delete(session, month_id):
        if current_thread().name == "second":
            attempting.set()
        return original_guard(session, month_id)

    monkeypatch.setattr(transfer_reconciliation, "_transfer_legs", pause_evidence)
    monkeypatch.setattr(_guard, "require_editable_reporting_month", signal_month_delete)
    try:
        first, second = _overlap(
            database,
            lambda s: (
                create_transfer_reconciliation_evidence(
                    s,
                    transfer_link_id=link_id,
                    kind="internal_fee",
                    amount="1.00",
                    currency="RUB",
                    source="synthetic",
                    evidence_reference="race-month-evidence",
                ).id
            ),
            lambda s: delete_reporting_month(s, month_id),
            entered,
            attempting,
            release,
        )
        assert isinstance(first, int)
        assert isinstance(second, ValueError) and "reconciliation evidence" in str(second)
        with database.session_factory() as check:
            assert check.get(type(leg), leg_id).transfer_link_id == link_id
            assert len(list_transfer_reconciliation_evidence(check, transfer_link_id=link_id)) == 1
            _assert_link_state(check, link_id)
    finally:
        database.engine.dispose()


def test_draft_month_delete_reconciles_surviving_transfer_link(tmp_path: Path) -> None:
    session, database, month_id, source_id, destination_id = _environment(tmp_path)
    try:
        link = create_external_transfer_link(session, transfer_key="owner-transfer-delete")
        create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=source_id,
            event_date=date(2030, 5, 16),
            boundary_amount="50.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
            transfer_link_id=link.id,
        )
        create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=destination_id,
            event_date=date(2030, 5, 16),
            boundary_amount="50.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
            transfer_link_id=link.id,
        )
        assert link.status == "resolved"

        delete_reporting_month(session, month_id)
        session.refresh(link)
        assert link.status == "unresolved"
    finally:
        session.close()
        database.engine.dispose()


def test_external_flow_api_crud_and_closed_month_guard(tmp_path: Path) -> None:
    database = create_database(tmp_path / "r08-01a-api.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    month = create_reporting_month(session, year=2031, month=1, snapshot_date=date(2031, 1, 31))
    account = create_account(session, name="Synthetic API Account", account_type="brokerage")
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            created = client.post(
                "/api/external-flows",
                json={
                    "reporting_month_id": month.id,
                    "account_id": account.id,
                    "event_date": "2031-01-10",
                    "boundary_amount": {"amount": "200.01", "currency": "RUB"},
                    "direction": "contribution",
                    "kind": "external_contribution",
                    "scope_membership": "stable_in_scope",
                    "source": "manual",
                },
            )
            assert created.status_code == 201, created.text
            body = created.json()
            assert body["boundary_amount"] == {"amount": "200.01", "currency": "RUB"}
            assert body["kind"] == "external_contribution"
            assert body["scope_membership"] == "stable_in_scope"
            flow_id = body["id"]

            fractional_kopeck = client.post(
                "/api/external-flows",
                json={
                    "reporting_month_id": month.id,
                    "account_id": account.id,
                    "event_date": "2031-01-10",
                    "boundary_amount": {"amount": "200.001", "currency": "RUB"},
                    "direction": "contribution",
                    "kind": "external_contribution",
                },
            )
            assert fractional_kopeck.status_code == 422

            listed = client.get(f"/api/external-flows?month_id={month.id}")
            assert listed.status_code == 200
            assert [row["id"] for row in listed.json()] == [flow_id]

            patched = client.patch(
                f"/api/external-flows/{flow_id}",
                json={"boundary_amount": {"amount": "201.01", "currency": "RUB"}},
            )
            assert patched.status_code == 200, patched.text
            assert patched.json()["boundary_amount"]["amount"] == "201.01"

            session = database.session_factory()
            close_reporting_month(session, month.id)
            session.close()
            blocked = client.patch(
                f"/api/external-flows/{flow_id}",
                json={"notes": "must not mutate closed history"},
            )
            assert blocked.status_code == 409
            assert blocked.json()["error"]["code"] == "conflict"

            reopened = client.post(f"/api/months/{month.id}/reopen")
            assert reopened.status_code == 200, reopened.text
            deleted = client.delete(f"/api/external-flows/{flow_id}")
            assert deleted.status_code == 204
    finally:
        database.engine.dispose()


def test_transfer_link_api_crud_and_explicit_pairing(tmp_path: Path) -> None:
    database = create_database(tmp_path / "r08-01a-transfer-api.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    month = create_reporting_month(session, year=2031, month=2, snapshot_date=date(2031, 2, 28))
    source = create_account(session, name="Synthetic Transfer Source", account_type="brokerage")
    destination = create_account(
        session, name="Synthetic Transfer Destination", account_type="brokerage"
    )
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            source_flow = client.post(
                "/api/external-flows",
                json={
                    "reporting_month_id": month.id,
                    "account_id": source.id,
                    "event_date": "2031-02-10",
                    "amount": {"amount": "75.00", "currency": "RUB"},
                    "direction": "withdrawal",
                    "flow_type": "external_withdrawal",
                    "scope_membership": "stable_in_scope",
                },
            )
            destination_flow = client.post(
                "/api/external-flows",
                json={
                    "reporting_month_id": month.id,
                    "account_id": destination.id,
                    "event_date": "2031-02-11",
                    "amount": {"amount": "75.00", "currency": "RUB"},
                    "direction": "contribution",
                    "flow_type": "external_contribution",
                    "scope_membership": "stable_in_scope",
                },
            )
            assert source_flow.status_code == 201, source_flow.text
            assert destination_flow.status_code == 201, destination_flow.text
            source_id = source_flow.json()["id"]
            destination_id = destination_flow.json()["id"]

            created = client.post(
                "/api/transfer-links",
                json={
                    "transfer_key": "api-transfer-1",
                    "flow_ids": [source_id, destination_id],
                    "notes": "explicit owner linkage",
                },
            )
            assert created.status_code == 201, created.text
            link = created.json()
            assert link["status"] == "resolved"
            assert link["flow_ids"] == [source_id, destination_id]
            link_id = link["id"]

            source_after_link = client.get(f"/api/external-flows/{source_id}")
            assert source_after_link.status_code == 200
            assert source_after_link.json()["portfolio_scope_classification"] == "internal_transfer"

            renamed = client.patch(
                f"/api/transfer-links/{link_id}",
                json={"notes": "updated owner linkage"},
            )
            assert renamed.status_code == 200
            assert renamed.json()["notes"] == "updated owner linkage"

            detached = client.delete(f"/api/transfer-links/{link_id}/flows/{source_id}")
            assert detached.status_code == 200, detached.text
            assert detached.json()["status"] == "unresolved"
            assert detached.json()["flow_ids"] == [destination_id]

            detached_second = client.delete(f"/api/transfer-links/{link_id}/flows/{destination_id}")
            assert detached_second.status_code == 200
            assert detached_second.json()["flow_ids"] == []
            deleted = client.delete(f"/api/transfer-links/{link_id}")
            assert deleted.status_code == 204
    finally:
        database.engine.dispose()


def test_migration_keeps_ambiguous_legacy_rows_unclassified_and_downgrade_safe(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "r08-01a-migration.db"
    previous = run_alembic(database_path, "upgrade", "0029_statement_event_retract")
    assert previous.returncode == 0, previous.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2030,
                5,
                "2030-05-01",
                "2030-05-31",
                "2030-05-31",
                "draft",
                "manual",
                "2030-05-31 00:00:00",
                "2030-05-31 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO accounts (name, account_type, status, include_in_capital, include_in_returns) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Legacy Account", "brokerage", "active", 1, 1),
        )
        connection.execute(
            "INSERT INTO investment_cash_flows "
            "(reporting_month_id, account_id, instrument_id, flow_type, event_date, "
            "gross_amount_kopecks, tax_amount_kopecks, commission_amount_kopecks, "
            "net_amount_kopecks, currency, source, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 1, None, "deposit", "2030-05-10", 10000, 0, 0, 10000, "RUB", "legacy", None),
        )
        connection.execute(
            "INSERT INTO investment_cash_flows "
            "(reporting_month_id, account_id, instrument_id, flow_type, event_date, "
            "gross_amount_kopecks, tax_amount_kopecks, commission_amount_kopecks, "
            "net_amount_kopecks, currency, source, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                None,
                "withdrawal",
                "2030-05-11",
                20000,
                0,
                0,
                20000,
                "RUB",
                "legacy",
                None,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM external_flows").fetchone() == (0,)
        assert connection.execute(
            "SELECT flow_type, net_amount_kopecks, source FROM investment_cash_flows ORDER BY id"
        ).fetchall() == [("deposit", 10000, "legacy"), ("withdrawal", 20000, "legacy")]
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0029_statement_event_retract")
    assert downgraded.returncode == 0, downgraded.stderr
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "external_flows" not in tables
        assert "external_transfer_links" not in tables
        assert connection.execute(
            "SELECT flow_type, net_amount_kopecks FROM investment_cash_flows ORDER BY id"
        ).fetchall() == [("deposit", 10000), ("withdrawal", 20000)]
    finally:
        connection.close()


def test_migration_downgrade_refuses_to_delete_new_owner_data(tmp_path: Path) -> None:
    database_path = tmp_path / "r08-01a-migration-data.db"
    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO external_transfer_links "
            "(transfer_key, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("synthetic-transfer", "unresolved", "2030-05-01", "2030-05-01"),
        )
        connection.commit()
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0029_statement_event_retract")
    assert downgraded.returncode != 0
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM external_transfer_links").fetchone() == (1,)
    finally:
        connection.close()


def test_scope_membership_migration_preserves_existing_flows_and_downgrades_safely(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "r08-01a-scope-membership-existing.db"
    previous = run_alembic(database_path, "upgrade", "0030_external_flow_persistence")
    assert previous.returncode == 0, previous.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2032,
                1,
                "2032-01-01",
                "2032-01-31",
                "2032-01-31",
                "draft",
                "manual",
                "2032-01-31 00:00:00",
                "2032-01-31 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO accounts (name, account_type, status, include_in_capital, include_in_returns) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Existing Account", "brokerage", "active", 1, 1),
        )
        connection.execute(
            "INSERT INTO external_flows "
            "(reporting_month_id, account_id, event_date, boundary_amount_kopecks, direction, kind, "
            "currency, transfer_link_id, source, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                "2032-01-10",
                12345,
                "contribution",
                "external_contribution",
                "RUB",
                None,
                "legacy-r08-01a",
                "preserve this row",
                "2032-01-10 00:00:00",
                "2032-01-10 00:00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute(
            "SELECT boundary_amount_kopecks, direction, kind, currency, scope_membership, "
            "source, notes FROM external_flows"
        ).fetchone() == (
            12345,
            "contribution",
            "external_contribution",
            "RUB",
            "unknown",
            "legacy-r08-01a",
            "preserve this row",
        )
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0030_external_flow_persistence")
    assert downgraded.returncode == 0, downgraded.stderr
    connection = sqlite3.connect(database_path)
    try:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(external_flows)")]
        assert "scope_membership" not in columns
        assert connection.execute(
            "SELECT boundary_amount_kopecks, direction, kind, currency, source, notes "
            "FROM external_flows"
        ).fetchone() == (
            12345,
            "contribution",
            "external_contribution",
            "RUB",
            "legacy-r08-01a",
            "preserve this row",
        )
    finally:
        connection.close()


def test_scope_membership_migration_refuses_to_drop_owner_evidence(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "r08-01a-scope-membership-downgrade.db"
    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2032,
                2,
                "2032-02-01",
                "2032-02-29",
                "2032-02-29",
                "draft",
                "manual",
                "2032-02-29 00:00:00",
                "2032-02-29 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO accounts (name, account_type, status, include_in_capital, include_in_returns) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Evidence Account", "brokerage", "active", 1, 1),
        )
        connection.execute(
            "INSERT INTO external_flows "
            "(reporting_month_id, account_id, event_date, boundary_amount_kopecks, direction, kind, "
            "scope_membership, currency, transfer_link_id, source, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                "2032-02-10",
                9999,
                "withdrawal",
                "external_withdrawal",
                "stable_in_scope",
                "RUB",
                None,
                "manual",
                None,
                "2032-02-10 00:00:00",
                "2032-02-10 00:00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    downgraded = run_alembic(database_path, "downgrade", "0030_external_flow_persistence")
    assert downgraded.returncode != 0
    connection = sqlite3.connect(database_path)
    try:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0031_external_flow_scope_membership",
        )
        assert connection.execute("SELECT scope_membership FROM external_flows").fetchone() == (
            "stable_in_scope",
        )
    finally:
        connection.close()


def test_external_flow_migration_is_network_and_provider_free() -> None:
    migrations_dir = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    for filename in (
        "0030_external_flow_persistence.py",
        "0031_external_flow_scope_membership.py",
    ):
        lowered = (migrations_dir / filename).read_text(encoding="utf-8").lower()
        assert "httpx" not in lowered
        assert "urllib" not in lowered
        assert "socket" not in lowered
