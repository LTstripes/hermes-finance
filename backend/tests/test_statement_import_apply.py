"""R06-08 statement persistence/apply: idempotency, correction, manual link."""

from __future__ import annotations

import ast
import inspect
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from _statement_pdf import (
    build_encrypted_pdf,
    build_income_report_pdf,
    build_wrong_report_pdf,
)
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType, InvestmentCashFlowType
from hermes_finance.persistence import (
    AppliedStatementEventRevision,
    Base,
    InvestmentCashFlow,
)
from hermes_finance.services.accounts import create_account, list_accounts
from hermes_finance.services.applied_statement_events import (
    AppliedStatementEventAlreadyExistsError,
    StatementLinkMode,
    create_applied_statement_event,
    get_applied_statement_event_by_identity,
    list_applied_statement_event_revisions,
    list_applied_statement_events,
)
from hermes_finance.services.instruments import create_instrument, list_instruments
from hermes_finance.services.investment_cash_flows import (
    create_investment_cash_flow,
    list_investment_cash_flows,
    list_passive_income_cash_flows,
    update_investment_cash_flow,
)
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)
from hermes_finance.services.statement_import_apply import (
    StatementApplyAction,
    StatementApplyFailureCode,
    StatementApplyItemAction,
    StatementApplySelection,
    apply_income_report_preview,
)
from hermes_finance.services.statement_import_preparation import (
    prepare_income_report_apply,
)
from hermes_finance.statement_import import (
    AccountMappingInput,
    DuplicateClass,
    HermesAccountView,
    HermesInstrumentView,
    InstrumentMappingInput,
    RowStatus,
    preview_income_report,
)
from hermes_finance.statement_import.dto import ALFA_DEPOSITORY_INCOME_PROVIDER
from hermes_finance.statement_import.identity import document_sha256

SYN_ISIN = "RU000SYN00001"
SYN_ISIN_COUPON = "RU000SYN00002"
SYN_ISIN_REDEEM = "RU000SYN00003"
SYN_DEPO = "SYN-DEPO-001"
PRIVATE_MARKERS = (
    "40817810100000000000",
    "SYNTHETIC BANK",
    "Synthetic Equity One",
    SYN_DEPO,
    "%PDF",
)


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "statement-apply.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _row(**overrides: str) -> dict[str, str]:
    return overrides


def build_env(
    session: Session,
    *,
    year: int = 2026,
    month: int = 1,
    extra_isins: tuple[str, ...] = (),
) -> tuple[int, int, dict[str, int]]:
    reporting = create_reporting_month(
        session, year=year, month=month, snapshot_date=date(year, month, 28)
    )
    account = create_account(
        session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
    )
    instruments = {
        SYN_ISIN: create_instrument(
            session,
            name="Synthetic Equity",
            instrument_type=InstrumentType.STOCK,
            isin=SYN_ISIN,
        ).id
    }
    for isin in extra_isins:
        instruments[isin] = create_instrument(
            session,
            name=f"Synthetic {isin[-2:]}",
            instrument_type=InstrumentType.BOND,
            isin=isin,
        ).id
    return reporting.id, account.id, instruments


def views(
    session: Session,
) -> tuple[tuple[HermesAccountView, ...], tuple[HermesInstrumentView, ...]]:
    accounts = tuple(
        HermesAccountView(
            account_id=account.id,
            account_type=account.account_type,
            name=account.name,
        )
        for account in list_accounts(session)
    )
    instruments = tuple(
        HermesInstrumentView(
            instrument_id=instrument.id,
            isin=instrument.isin,
            name=instrument.name,
            ticker=instrument.ticker,
        )
        for instrument in list_instruments(session)
    )
    return accounts, instruments


def mappings(account_id: int) -> tuple[AccountMappingInput, ...]:
    return (AccountMappingInput(hermes_account_id=account_id, provider_account_ref=SYN_DEPO),)


def preview(session: Session, document: bytes, account_id: int):
    accounts, instruments = views(session)
    return preview_income_report(
        document,
        hermes_accounts=accounts,
        hermes_instruments=instruments,
        account_mappings=mappings(account_id),
    )


def selection_from_row(row, **overrides: object) -> StatementApplySelection:
    payload: dict[str, object] = {
        "natural_identity": row.natural_identity,
        "material_fingerprint": row.material_fingerprint,
        "expected_hermes_account_id": row.hermes_account_id,
        "expected_hermes_instrument_id": row.hermes_instrument_id,
    }
    payload.update(overrides)
    return StatementApplySelection(**payload)  # type: ignore[arg-type]


def apply(
    session: Session,
    document: bytes,
    account_id: int,
    selections: tuple[StatementApplySelection, ...],
    *,
    expected_document_sha256: str | None = None,
    instrument_mappings: tuple[InstrumentMappingInput, ...] = (),
):
    return apply_income_report_preview(
        session,
        document=document,
        account_mappings=mappings(account_id),
        selections=selections,
        expected_document_sha256=expected_document_sha256 or document_sha256(document),
        instrument_mappings=instrument_mappings,
    )


def prepare(session: Session, document: bytes, account_id: int):
    return prepare_income_report_apply(
        session,
        document=document,
        account_mappings=mappings(account_id),
    )


def counts(session: Session) -> tuple[int, int, int]:
    return (
        len(list_applied_statement_events(session)),
        len(list(session.scalars(select(AppliedStatementEventRevision)))),
        len(list_investment_cash_flows(session)),
    )


def sqlite_blob(database) -> str:
    path = database.database_path
    connection = sqlite3.connect(path)
    try:
        dumped = []
        for (table,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ):
            dumped.append(table)
            for row in connection.execute(f"SELECT * FROM {table}"):
                dumped.append(repr(row))
        return "\n".join(dumped)
    finally:
        connection.close()


def test_new_dividend_creates_flow_event_and_revision(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        result = apply(session, document, account_id, (selection_from_row(row),))
        assert result.success is True
        assert result.items[0].action is StatementApplyItemAction.CREATED
        assert counts(session) == (1, 1, 1)
        flow = list_investment_cash_flows(session)[0]
        assert flow.flow_type == "dividend"
        assert flow.event_date == date(2026, 1, 20)
        assert flow.gross_amount_kopecks == 1150
        assert flow.tax_amount_kopecks == 150
        assert flow.commission_amount_kopecks == 0
        assert flow.net_amount_kopecks == 1000
        assert flow.currency == "RUB"
        assert flow.source == ALFA_DEPOSITORY_INCOME_PROVIDER
        event = list_applied_statement_events(session)[0]
        assert event.natural_identity == row.natural_identity
        assert event.material_fingerprint == row.material_fingerprint
        assert event.link_mode == StatementLinkMode.STATEMENT_CREATED.value
        revision = list_applied_statement_event_revisions(session, event.id)[0]
        assert revision.revision_kind == "apply"
        assert revision.tax_available is True
        assert revision.tax_amount_kopecks == 150
        assert result.items[0].revision_id == revision.id
        assert result.items[0].investment_cash_flow_id == flow.id
    finally:
        session.close()
        database.engine.dispose()


def test_coupon_unavailable_tax_persists_zero_with_provenance_flag(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session, extra_isins=(SYN_ISIN_COUPON,))
        document = build_income_report_pdf(
            [
                _row(
                    payment_kind="погашение купона",
                    isin=SYN_ISIN_COUPON,
                    quantity="10",
                    per_unit="2,00",
                    gross="20,00",
                    tax="—",
                    tax_rate="—",
                    net="20,00",
                )
            ]
        )
        row = preview(session, document, account_id).rows[0]
        result = apply(session, document, account_id, (selection_from_row(row),))
        assert result.success is True
        flow = list_investment_cash_flows(session)[0]
        assert flow.flow_type == "coupon"
        assert flow.tax_amount_kopecks == 0
        assert flow.net_amount_kopecks == 2000
        revision = list(session.scalars(select(AppliedStatementEventRevision)))[0]
        assert revision.tax_available is False
        assert revision.tax_amount_kopecks is None
    finally:
        session.close()
        database.engine.dispose()


def test_redemption_creates_non_passive_cash_flow(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _ = build_env(session, extra_isins=(SYN_ISIN_REDEEM,))
        document = build_income_report_pdf(
            [
                _row(
                    payment_kind="полное погашение номинала",
                    isin=SYN_ISIN_REDEEM,
                    quantity="5",
                    per_unit="1000,00",
                    gross="5000,00",
                    tax="—",
                    net="5000,00",
                )
            ]
        )
        row = preview(session, document, account_id).rows[0]
        result = apply(session, document, account_id, (selection_from_row(row),))
        assert result.success is True
        flow = list_investment_cash_flows(session)[0]
        assert flow.flow_type == "redemption"
        assert flow.id not in [
            item.id for item in list_passive_income_cash_flows(session, month_id)
        ]
        assert InvestmentCashFlowType.REDEMPTION.counts_as_passive_income is False
    finally:
        session.close()
        database.engine.dispose()


def test_same_document_reimport_is_unchanged(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        first = apply(session, document, account_id, (selection_from_row(row),))
        second = apply(session, document, account_id, (selection_from_row(row),))
        assert first.success is True
        assert second.success is True
        assert second.items[0].action is StatementApplyItemAction.UNCHANGED
        assert second.items[0].revision_id is None
        assert counts(session) == (1, 1, 1)
    finally:
        session.close()
        database.engine.dispose()


def test_overlapping_document_same_identity_fingerprint_is_unchanged(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        first_pdf = build_income_report_pdf()
        second_pdf = build_income_report_pdf([_row(security_name="Overlapping Period Name")])
        assert first_pdf != second_pdf
        row = preview(session, first_pdf, account_id).rows[0]
        apply(session, first_pdf, account_id, (selection_from_row(row),))
        other = preview(session, second_pdf, account_id).rows[0]
        assert other.natural_identity == row.natural_identity
        assert other.material_fingerprint == row.material_fingerprint
        result = apply(session, second_pdf, account_id, (selection_from_row(other),))
        assert result.items[0].action is StatementApplyItemAction.UNCHANGED
        assert counts(session) == (1, 1, 1)
        event = list_applied_statement_events(session)[0]
        assert event.document_sha256 != preview(session, second_pdf, account_id).document_sha256
    finally:
        session.close()
        database.engine.dispose()


def test_fingerprint_change_is_correction_not_silent_overwrite(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        original = build_income_report_pdf()
        row = preview(session, original, account_id).rows[0]
        apply(session, original, account_id, (selection_from_row(row),))
        corrected = build_income_report_pdf(
            [
                _row(
                    per_unit="2,00",
                    gross="20,00",
                    tax="2,60",
                    net="17,40",
                )
            ]
        )
        changed = preview(session, corrected, account_id).rows[0]
        assert changed.natural_identity == row.natural_identity
        assert changed.material_fingerprint != row.material_fingerprint
        refused = apply(session, corrected, account_id, (selection_from_row(changed),))
        assert refused.success is False
        assert refused.error_code is StatementApplyFailureCode.VALIDATION_ERROR
        assert counts(session) == (1, 1, 1)
        flow = list_investment_cash_flows(session)[0]
        assert flow.gross_amount_kopecks == 1150
    finally:
        session.close()
        database.engine.dispose()


def test_explicit_revise_updates_statement_owned_flow_and_appends_revision(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        original = build_income_report_pdf()
        row = preview(session, original, account_id).rows[0]
        apply(session, original, account_id, (selection_from_row(row),))
        event = list_applied_statement_events(session)[0]
        first_revision = list_applied_statement_event_revisions(session, event.id)[0]
        corrected = build_income_report_pdf(
            [
                _row(
                    per_unit="2,00",
                    gross="20,00",
                    tax="2,60",
                    net="17,40",
                )
            ]
        )
        changed = preview(session, corrected, account_id).rows[0]
        result = apply(
            session,
            corrected,
            account_id,
            (selection_from_row(changed, action=StatementApplyAction.REVISE),),
        )
        assert result.success is True
        assert result.items[0].action is StatementApplyItemAction.REVISED
        assert counts(session) == (1, 2, 1)
        flow = list_investment_cash_flows(session)[0]
        assert flow.gross_amount_kopecks == 2000
        assert flow.tax_amount_kopecks == 260
        assert flow.net_amount_kopecks == 1740
        assert flow.id == event.investment_cash_flow_id
        refreshed = get_applied_statement_event_by_identity(
            session,
            provider=ALFA_DEPOSITORY_INCOME_PROVIDER,
            natural_identity=row.natural_identity,
        )
        assert refreshed is not None
        assert refreshed.id == event.id
        assert refreshed.material_fingerprint == changed.material_fingerprint
        revisions = list_applied_statement_event_revisions(session, event.id)
        assert revisions[0].id == first_revision.id
        assert revisions[0].gross_amount_kopecks == 1150
        assert revisions[1].revision_kind == "revise"
        assert revisions[1].gross_amount_kopecks == 2000
    finally:
        session.close()
        database.engine.dispose()


def test_correction_of_linked_manual_flow_is_conflict(tmp_path: Path) -> None:
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
        corrected = build_income_report_pdf(
            [_row(per_unit="2,00", gross="20,00", tax="2,60", net="17,40")]
        )
        changed = preview(session, corrected, account_id).rows[0]
        result = apply(
            session,
            corrected,
            account_id,
            (selection_from_row(changed, action=StatementApplyAction.REVISE),),
        )
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.MANUAL_LINK_CONFLICT
        assert counts(session) == (1, 1, 1)
        session.refresh(manual)
        assert manual.source == "manual"
        assert manual.gross_amount_kopecks == 1150
    finally:
        session.close()
        database.engine.dispose()


def test_manual_candidate_blocks_auto_create(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instruments = build_env(session)
        create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instruments[SYN_ISIN],
            flow_type="dividend",
            event_date=date(2026, 1, 20),
            gross_amount="99.00",
            tax_amount="0.00",
            commission_amount="0.00",
            net_amount="99.00",
            source="manual",
        )
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        result = apply(session, document, account_id, (selection_from_row(row),))
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.DUPLICATE_RESOLUTION_REQUIRED
        assert counts(session) == (0, 0, 1)
    finally:
        session.close()
        database.engine.dispose()


def test_link_existing_does_not_mutate_manual_row(tmp_path: Path) -> None:
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
        result = apply(
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
        assert result.success is True
        assert result.items[0].action is StatementApplyItemAction.LINKED_EXISTING
        assert result.items[0].investment_cash_flow_id == manual.id
        session.refresh(manual)
        assert manual.source == "manual"
        assert manual.notes == "keep me"
        assert manual.gross_amount_kopecks == 1150
        event = list_applied_statement_events(session)[0]
        assert event.link_mode == StatementLinkMode.LINKED_EXISTING.value
        assert event.investment_cash_flow_id == manual.id
        assert counts(session) == (1, 1, 1)
    finally:
        session.close()
        database.engine.dispose()


def test_create_separate_keeps_manual_and_adds_provider_row(tmp_path: Path) -> None:
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
            gross_amount="99.00",
            tax_amount="0.00",
            commission_amount="0.00",
            net_amount="99.00",
            source="manual",
        )
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        result = apply(
            session,
            document,
            account_id,
            (
                selection_from_row(
                    row,
                    action=StatementApplyAction.CREATE_SEPARATE,
                    expected_candidate_ids=(manual.id,),
                ),
            ),
        )
        assert result.success is True
        assert result.items[0].action is StatementApplyItemAction.CREATED
        assert counts(session) == (1, 1, 2)
        session.refresh(manual)
        assert manual.source == "manual"
        assert manual.gross_amount_kopecks == 9900
        created = session.get(InvestmentCashFlow, result.items[0].investment_cash_flow_id)
        assert created is not None
        assert created.source == ALFA_DEPOSITORY_INCOME_PROVIDER
        assert created.id != manual.id
    finally:
        session.close()
        database.engine.dispose()


def test_multiple_manual_candidates_never_auto_picked(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instruments = build_env(session)
        first = create_investment_cash_flow(
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
        second = create_investment_cash_flow(
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
            source="excel_migration",
        )
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        auto = apply(session, document, account_id, (selection_from_row(row),))
        assert auto.error_code is StatementApplyFailureCode.DUPLICATE_RESOLUTION_REQUIRED
        picked = apply(
            session,
            document,
            account_id,
            (
                selection_from_row(
                    row,
                    action=StatementApplyAction.LINK_EXISTING,
                    existing_cash_flow_id=second.id,
                    expected_candidate_ids=(first.id, second.id),
                ),
            ),
        )
        assert picked.success is True
        assert picked.items[0].investment_cash_flow_id == second.id
        assert counts(session) == (1, 1, 2)
    finally:
        session.close()
        database.engine.dispose()


def test_selected_target_change_is_preview_changed(tmp_path: Path) -> None:
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
        session.delete(manual)
        session.commit()
        result = apply(
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
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.PREVIEW_CHANGED
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_document_material_change_is_preview_changed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        original = build_income_report_pdf()
        row = preview(session, original, account_id).rows[0]
        changed = build_income_report_pdf(
            [_row(per_unit="2,00", gross="20,00", tax="2,60", net="17,40")]
        )
        result = apply(session, changed, account_id, (selection_from_row(row),))
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.PREVIEW_CHANGED
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_unmatched_and_malformed_rows_cannot_apply(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        unmatched = apply(
            session,
            build_income_report_pdf(),
            account_id + 99,
            (
                StatementApplySelection(
                    natural_identity="missing|dividend|RU000SYN00001|2026-01-15",
                    material_fingerprint="a" * 64,
                    expected_hermes_account_id=account_id,
                    expected_hermes_instrument_id=1,
                ),
            ),
        )
        assert unmatched.error_code is StatementApplyFailureCode.PREVIEW_CHANGED
        encrypted = build_encrypted_pdf()
        malformed = apply_income_report_preview(
            session,
            document=encrypted,
            account_mappings=mappings(account_id),
            expected_document_sha256=document_sha256(encrypted),
            selections=(
                StatementApplySelection(
                    natural_identity="x",
                    material_fingerprint="b" * 64,
                    expected_hermes_account_id=account_id,
                    expected_hermes_instrument_id=1,
                ),
            ),
        )
        assert malformed.error_code is StatementApplyFailureCode.MALFORMED_OR_UNSUPPORTED_REPORT
        wrong_pdf = build_wrong_report_pdf()
        wrong = apply_income_report_preview(
            session,
            document=wrong_pdf,
            account_mappings=mappings(account_id),
            expected_document_sha256=document_sha256(wrong_pdf),
            selections=(
                StatementApplySelection(
                    natural_identity="x",
                    material_fingerprint="c" * 64,
                    expected_hermes_account_id=account_id,
                    expected_hermes_instrument_id=1,
                ),
            ),
        )
        assert wrong.error_code is StatementApplyFailureCode.MALFORMED_OR_UNSUPPORTED_REPORT
        unsupported = build_income_report_pdf([_row(payment_kind="комиссия депозитария")])
        unsupported_result = apply(
            session,
            unsupported,
            account_id,
            (
                StatementApplySelection(
                    natural_identity="missing",
                    material_fingerprint="d" * 64,
                    expected_hermes_account_id=account_id,
                    expected_hermes_instrument_id=1,
                ),
            ),
        )
        assert unsupported_result.error_code in {
            StatementApplyFailureCode.MALFORMED_OR_UNSUPPORTED_REPORT,
            StatementApplyFailureCode.PREVIEW_CHANGED,
            StatementApplyFailureCode.VALIDATION_ERROR,
        }
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_missing_reporting_month_does_not_auto_create(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = create_account(
            session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
        )
        create_instrument(
            session,
            name="Synthetic Equity",
            instrument_type=InstrumentType.STOCK,
            isin=SYN_ISIN,
        )
        document = build_income_report_pdf()
        row = preview(session, document, account.id).rows[0]
        result = apply(session, document, account.id, (selection_from_row(row),))
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.MISSING_REPORTING_MONTH
        assert counts(session) == (0, 0, 0)
        assert list_accounts(session)  # month was not invented; account remains
    finally:
        session.close()
        database.engine.dispose()


def test_closed_month_rejects_with_zero_writes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _ = build_env(session)
        close_reporting_month(session, month_id)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        result = apply(session, document, account_id, (selection_from_row(row),))
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.CLOSED_MONTH
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_closed_month_rejects_idempotent_reimport(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        first = apply(session, document, account_id, (selection_from_row(row),))
        assert first.success is True
        event = list_applied_statement_events(session)[0]
        revision = list_applied_statement_event_revisions(session, event.id)[0]
        flow = list_investment_cash_flows(session)[0]
        before = (
            event.material_fingerprint,
            event.document_sha256,
            event.updated_at,
            event.investment_cash_flow_id,
            event.link_mode,
            revision.id,
            revision.revision_kind,
            revision.gross_amount_kopecks,
            revision.applied_at,
            flow.gross_amount_kopecks,
            flow.net_amount_kopecks,
            flow.source,
            flow.event_date,
            flow.reporting_month_id,
        )
        close_reporting_month(session, month_id)
        result = apply(session, document, account_id, (selection_from_row(row),))
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.CLOSED_MONTH
        assert result.items == ()
        assert counts(session) == (1, 1, 1)
        session.refresh(event)
        session.refresh(revision)
        session.refresh(flow)
        assert (
            event.material_fingerprint,
            event.document_sha256,
            event.updated_at,
            event.investment_cash_flow_id,
            event.link_mode,
            revision.id,
            revision.revision_kind,
            revision.gross_amount_kopecks,
            revision.applied_at,
            flow.gross_amount_kopecks,
            flow.net_amount_kopecks,
            flow.source,
            flow.event_date,
            flow.reporting_month_id,
        ) == before
    finally:
        session.close()
        database.engine.dispose()


def test_spanning_months_fail_atomically_when_one_month_is_invalid(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        january_id, account_id, _ = build_env(session, extra_isins=(SYN_ISIN_COUPON,))
        february = create_reporting_month(
            session, year=2026, month=2, snapshot_date=date(2026, 2, 28)
        )
        close_reporting_month(session, february.id)
        document = build_income_report_pdf(
            [
                _row(),
                _row(
                    payment_kind="погашение купона",
                    isin=SYN_ISIN_COUPON,
                    quantity="10",
                    per_unit="2,00",
                    gross="20,00",
                    tax="—",
                    net="20,00",
                    record_date="15.02.2026",
                    payment_date="20.02.2026",
                ),
            ]
        )
        rows = preview(session, document, account_id).rows
        result = apply(
            session,
            document,
            account_id,
            (selection_from_row(rows[0]), selection_from_row(rows[1])),
        )
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.CLOSED_MONTH
        assert counts(session) == (0, 0, 0)
        assert january_id > 0
    finally:
        session.close()
        database.engine.dispose()


def test_second_row_failure_rolls_back_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hermes_finance.services import statement_import_apply as module

    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session, extra_isins=(SYN_ISIN_COUPON,))
        document = build_income_report_pdf(
            [
                _row(),
                _row(
                    payment_kind="погашение купона",
                    isin=SYN_ISIN_COUPON,
                    quantity="10",
                    per_unit="2,00",
                    gross="20,00",
                    tax="—",
                    net="20,00",
                ),
            ]
        )
        rows = preview(session, document, account_id).rows
        original = module.create_applied_statement_event
        call_count = 0

        def fail_second(*args: object, **kwargs: object):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("synthetic second-row persistence failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(module, "create_applied_statement_event", fail_second)
        result = apply(
            session,
            document,
            account_id,
            (selection_from_row(rows[0]), selection_from_row(rows[1])),
        )
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.PERSISTENCE_ERROR
        assert result.items == ()
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_uniqueness_prevents_duplicate_current_identities(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instruments = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        apply(session, document, account_id, (selection_from_row(row),))
        other = create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instruments[SYN_ISIN],
            flow_type="dividend",
            event_date=date(2026, 1, 21),
            gross_amount="1.00",
            tax_amount="0.00",
            commission_amount="0.00",
            net_amount="1.00",
            source="manual",
        )
        with pytest.raises(AppliedStatementEventAlreadyExistsError):
            create_applied_statement_event(
                session,
                provider=ALFA_DEPOSITORY_INCOME_PROVIDER,
                account_id=account_id,
                instrument_id=instruments[SYN_ISIN],
                event_kind="dividend",
                isin=SYN_ISIN,
                record_date=date(2026, 1, 15),
                natural_identity=row.natural_identity,
                material_fingerprint=row.material_fingerprint,
                investment_cash_flow_id=other.id,
                document_sha256="a" * 64,
                link_mode=StatementLinkMode.STATEMENT_CREATED,
                event_date=date(2026, 1, 20),
                quantity=Decimal("10"),
                per_unit=Decimal("1.15"),
                gross_amount_kopecks=1150,
                gross_currency="RUB",
                tax_available=True,
                tax_amount_kopecks=150,
                tax_rate=Decimal("13"),
                net_amount_kopecks=1000,
                net_currency="RUB",
            )
        session.rollback()
        assert len(list_applied_statement_events(session)) == 1
    finally:
        session.close()
        database.engine.dispose()


def test_exact_decimal_values_have_no_float_drift(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        apply(session, document, account_id, (selection_from_row(row),))
        flow = list_investment_cash_flows(session)[0]
        revision = list(session.scalars(select(AppliedStatementEventRevision)))[0]
        assert flow.gross_amount_kopecks == 1150
        assert isinstance(flow.gross_amount_kopecks, int)
        assert revision.quantity == "10.00000000"
        assert revision.per_unit == "1.15000000"
        assert "." in revision.per_unit
        assert "1.149999" not in revision.per_unit
    finally:
        session.close()
        database.engine.dispose()


def test_private_pdf_and_account_refs_are_absent_from_persistence(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        result = apply(session, document, account_id, (selection_from_row(row),))
        assert result.success is True
        dumped = sqlite_blob(database)
        for marker in PRIVATE_MARKERS:
            assert marker not in dumped
        assert SYN_ISIN in dumped
        message = repr(result)
        for marker in PRIVATE_MARKERS:
            assert marker not in message
    finally:
        session.close()
        database.engine.dispose()


def test_incompatible_link_existing_is_rejected(tmp_path: Path) -> None:
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
            gross_amount="50.00",
            tax_amount="0.00",
            commission_amount="0.00",
            net_amount="50.00",
            source="manual",
        )
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        result = apply(
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
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.VALIDATION_ERROR
        assert counts(session) == (0, 0, 1)
        session.refresh(manual)
        assert manual.source == "manual"
        assert manual.gross_amount_kopecks == 5000
    finally:
        session.close()
        database.engine.dispose()


def test_apply_modules_have_no_network_ocr_or_alfa_live_imports() -> None:
    files = [
        Path(inspect.getfile(apply_income_report_preview)).resolve(),
        Path(inspect.getfile(create_applied_statement_event)).resolve(),
    ]
    forbidden_modules = {
        "hermes_finance.broker_data.alfa_pro.adapter",
        "hermes_finance.alfa_pro_probe",
        "httpx",
        "httpx2",
        "requests",
        "pytesseract",
        "easyocr",
        "pdf2image",
        "ocrmypdf",
    }
    forbidden_tokens = (
        "ClientOperationEntity",
        "pytesseract",
        "easyocr",
        "ocrmypdf",
    )
    for path in files:
        source = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in source
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden_modules
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in forbidden_modules
                assert not any(
                    node.module == name or node.module.startswith(f"{name}.")
                    for name in forbidden_modules
                )


def test_reviewed_instrument_target_mismatch_is_preview_changed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, instruments = build_env(session)
        other = create_instrument(
            session,
            name="Synthetic Twin Without ISIN",
            instrument_type=InstrumentType.STOCK,
        )
        document = build_income_report_pdf()
        reviewed = preview_income_report(
            document,
            hermes_accounts=views(session)[0],
            hermes_instruments=views(session)[1],
            account_mappings=mappings(account_id),
            instrument_mappings=(
                InstrumentMappingInput(
                    hermes_instrument_id=instruments[SYN_ISIN],
                    isin=SYN_ISIN,
                ),
            ),
        )
        row = reviewed.rows[0]
        assert row.hermes_instrument_id == instruments[SYN_ISIN]
        result = apply(
            session,
            document,
            account_id,
            (selection_from_row(row),),
            expected_document_sha256=reviewed.document_sha256,
            instrument_mappings=(
                InstrumentMappingInput(hermes_instrument_id=other.id, isin=SYN_ISIN),
            ),
        )
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.PREVIEW_CHANGED
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_reviewed_document_sha_mismatch_is_preview_changed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session, extra_isins=(SYN_ISIN_COUPON,))
        pdf_a = build_income_report_pdf()
        pdf_b = build_income_report_pdf(
            [
                _row(),
                _row(
                    payment_kind="погашение купона",
                    isin=SYN_ISIN_COUPON,
                    quantity="10",
                    per_unit="2,00",
                    gross="20,00",
                    tax="—",
                    net="20,00",
                ),
            ]
        )
        assert document_sha256(pdf_a) != document_sha256(pdf_b)
        reviewed = preview(session, pdf_a, account_id)
        row_a = reviewed.rows[0]
        row_b = preview(session, pdf_b, account_id).rows[0]
        assert row_a.natural_identity == row_b.natural_identity
        assert row_a.material_fingerprint == row_b.material_fingerprint
        result = apply(
            session,
            pdf_b,
            account_id,
            (selection_from_row(row_a),),
            expected_document_sha256=reviewed.document_sha256,
        )
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.PREVIEW_CHANGED
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_statement_created_amount_drift_is_preview_changed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        created = apply(session, document, account_id, (selection_from_row(row),))
        assert created.success is True
        flow_id = created.items[0].investment_cash_flow_id
        update_investment_cash_flow(
            session,
            flow_id,
            gross_amount="20.00",
            tax_amount="1.50",
            net_amount="18.50",
        )
        result = apply(session, document, account_id, (selection_from_row(row),))
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.PREVIEW_CHANGED
        assert counts(session) == (1, 1, 1)
        flow = session.get(InvestmentCashFlow, flow_id)
        assert flow is not None
        assert flow.gross_amount_kopecks == 2000
        assert flow.net_amount_kopecks == 1850
        assert flow.source == ALFA_DEPOSITORY_INCOME_PROVIDER
    finally:
        session.close()
        database.engine.dispose()


def test_statement_created_instrument_type_source_drift_is_preview_changed(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        other = create_instrument(
            session,
            name="Drifted Instrument",
            instrument_type=InstrumentType.BOND,
        )
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        created = apply(session, document, account_id, (selection_from_row(row),))
        flow_id = created.items[0].investment_cash_flow_id
        update_investment_cash_flow(
            session,
            flow_id,
            instrument_id=other.id,
            flow_type="coupon",
            source="manual",
        )
        result = apply(session, document, account_id, (selection_from_row(row),))
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.PREVIEW_CHANGED
        assert counts(session) == (1, 1, 1)
        flow = session.get(InvestmentCashFlow, flow_id)
        assert flow is not None
        assert flow.instrument_id == other.id
        assert flow.flow_type == "coupon"
        assert flow.source == "manual"
        assert flow.gross_amount_kopecks == 1150
    finally:
        session.close()
        database.engine.dispose()


def test_linked_existing_owner_drift_is_not_silent_unchanged(tmp_path: Path) -> None:
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
        update_investment_cash_flow(
            session,
            manual.id,
            gross_amount="50.00",
            tax_amount="0.00",
            net_amount="50.00",
        )
        result = apply(session, document, account_id, (selection_from_row(row),))
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.PREVIEW_CHANGED
        assert result.items == ()
        assert counts(session) == (1, 1, 1)
        session.refresh(manual)
        assert manual.source == "manual"
        assert manual.gross_amount_kopecks == 5000
        assert manual.net_amount_kopecks == 5000
    finally:
        session.close()
        database.engine.dispose()


def test_closed_source_month_blocks_cross_month_correction(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        january_id, account_id, _ = build_env(session)
        create_reporting_month(session, year=2026, month=2, snapshot_date=date(2026, 2, 28))
        original = build_income_report_pdf()
        row = preview(session, original, account_id).rows[0]
        created = apply(session, original, account_id, (selection_from_row(row),))
        assert created.success is True
        close_reporting_month(session, january_id)
        corrected = build_income_report_pdf([_row(payment_date="20.02.2026")])
        changed = preview(session, corrected, account_id).rows[0]
        assert changed.natural_identity == row.natural_identity
        assert changed.material_fingerprint != row.material_fingerprint
        result = apply(
            session,
            corrected,
            account_id,
            (selection_from_row(changed, action=StatementApplyAction.REVISE),),
        )
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.CLOSED_MONTH
        assert counts(session) == (1, 1, 1)
        flow = list_investment_cash_flows(session)[0]
        assert flow.event_date == date(2026, 1, 20)
        assert flow.reporting_month_id == january_id
        revision = list(session.scalars(select(AppliedStatementEventRevision)))[0]
        assert revision.revision_kind == "apply"
        assert revision.event_date == date(2026, 1, 20)
    finally:
        session.close()
        database.engine.dispose()


def test_preparation_without_candidate_is_read_only_and_exposes_review_evidence(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    statements: list[str] = []

    def record_write(*args: object) -> None:
        statement = args[2]
        if isinstance(statement, str) and statement.lstrip().upper().startswith(
            ("INSERT", "UPDATE", "DELETE")
        ):
            statements.append(statement)

    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        event.listen(database.engine, "before_cursor_execute", record_write)
        prepared = prepare(session, document, account_id)
        event.remove(database.engine, "before_cursor_execute", record_write)
        row = prepared.rows[0]
        assert prepared.document_sha256 == document_sha256(document)
        assert row.expected_candidate_ids == ()
        assert row.candidates == ()
        assert row.natural_identity is not None
        assert row.material_fingerprint is not None
        assert row.expected_hermes_account_id == account_id
        assert row.expected_hermes_instrument_id is not None
        assert not hasattr(row, "provider_account_ref")
        assert statements == []
        assert counts(session) == (0, 0, 0)
    finally:
        if event.contains(database.engine, "before_cursor_execute", record_write):
            event.remove(database.engine, "before_cursor_execute", record_write)
        session.close()
        database.engine.dispose()


def test_preparation_one_candidate_builds_complete_apply_selection(tmp_path: Path) -> None:
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
        prepared = prepare(session, document, account_id)
        row = prepared.rows[0]
        assert row.expected_candidate_ids == (manual.id,)
        candidate = row.candidates[0]
        assert candidate.investment_cash_flow_id == manual.id
        assert candidate.gross_amount_kopecks == 1150
        assert candidate.tax_amount_kopecks == 150
        assert candidate.net_amount_kopecks == 1000
        selection = row.to_apply_selection(
            action=StatementApplyAction.LINK_EXISTING,
            existing_cash_flow_id=candidate.investment_cash_flow_id,
        )
        assert isinstance(selection, StatementApplySelection)
        result = apply(session, document, account_id, (selection,))
        assert result.success is True
        assert result.items[0].action is StatementApplyItemAction.LINKED_EXISTING
        assert result.items[0].investment_cash_flow_id == manual.id
    finally:
        session.close()
        database.engine.dispose()


def test_preparation_preserves_duplicate_classification(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        row = preview(session, document, account_id).rows[0]
        assert row.duplicate_class is None
        assert apply(session, document, account_id, (selection_from_row(row),)).success is True
        prepared = prepare(session, document, account_id)
        assert prepared.rows[0].duplicate_class is DuplicateClass.DUPLICATE
    finally:
        session.close()
        database.engine.dispose()


def test_preparation_preserves_correction_classification(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        original = build_income_report_pdf()
        row = preview(session, original, account_id).rows[0]
        assert apply(session, original, account_id, (selection_from_row(row),)).success is True
        corrected = build_income_report_pdf(
            [_row(per_unit="2,00", gross="20,00", tax="2,60", net="17,40")]
        )
        prepared = prepare(session, corrected, account_id)
        assert prepared.rows[0].duplicate_class is DuplicateClass.CORRECTION
    finally:
        session.close()
        database.engine.dispose()


def test_preparation_multiple_candidates_are_deterministic(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instruments = build_env(session)
        first = create_investment_cash_flow(
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
        second = create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instruments[SYN_ISIN],
            flow_type="dividend",
            event_date=date(2026, 1, 20),
            gross_amount="99.00",
            tax_amount="0.00",
            commission_amount="0.00",
            net_amount="99.00",
            source="excel_migration",
        )
        prepared = prepare(session, build_income_report_pdf(), account_id)
        assert prepared.rows[0].expected_candidate_ids == (first.id, second.id)
        assert tuple(
            candidate.investment_cash_flow_id for candidate in prepared.rows[0].candidates
        ) == (first.id, second.id)
    finally:
        session.close()
        database.engine.dispose()


def test_preparation_excludes_already_linked_cash_flow_candidates(tmp_path: Path) -> None:
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
        original = build_income_report_pdf()
        original_row = prepare(session, original, account_id).rows[0]
        selection = original_row.to_apply_selection(
            action=StatementApplyAction.LINK_EXISTING,
            existing_cash_flow_id=manual.id,
        )
        assert isinstance(selection, StatementApplySelection)
        assert apply(session, original, account_id, (selection,)).success is True
        distinct_identity = build_income_report_pdf([_row(record_date="16.01.2026")])
        prepared = prepare(session, distinct_identity, account_id)
        assert prepared.rows[0].expected_candidate_ids == ()
        assert prepared.rows[0].candidates == ()
    finally:
        session.close()
        database.engine.dispose()


def test_ambiguous_preparation_row_cannot_build_apply_selection(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf([_row(), _row()])
        prepared = prepare(session, document, account_id)
        row = prepared.rows[0]
        assert row.status is RowStatus.AMBIGUOUS
        assert row.natural_identity is not None
        assert row.expected_hermes_account_id is not None
        assert row.expected_hermes_instrument_id is not None
        with pytest.raises(ValueError, match="only a matched"):
            row.to_apply_selection()
    finally:
        session.close()
        database.engine.dispose()


def test_fresh_ambiguous_instrument_state_is_preview_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, database = session_for(tmp_path)
    try:
        _, account_id, _ = build_env(session)
        document = build_income_report_pdf()
        reviewed = preview(session, document, account_id)
        row = reviewed.rows[0]
        assert row.status is RowStatus.MATCHED
        from hermes_finance.services import statement_import_apply

        original_instrument_views = statement_import_apply._instrument_views
        monkeypatch.setattr(
            statement_import_apply,
            "_instrument_views",
            lambda current_session: (
                original_instrument_views(current_session)
                + (
                    HermesInstrumentView(
                        instrument_id=999,
                        isin=SYN_ISIN.lower(),
                        name="Synthetic duplicate ISIN",
                    ),
                )
            ),
        )
        result = apply(session, document, account_id, (selection_from_row(row),))
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.PREVIEW_CHANGED
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_duplicate_link_existing_target_fails_before_staging(tmp_path: Path) -> None:
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
        document = build_income_report_pdf(
            [_row(record_date="15.01.2026"), _row(record_date="16.01.2026")]
        )
        rows = preview(session, document, account_id).rows
        assert len({row.natural_identity for row in rows}) == 2
        result = apply(
            session,
            document,
            account_id,
            (
                selection_from_row(
                    rows[0],
                    action=StatementApplyAction.LINK_EXISTING,
                    existing_cash_flow_id=manual.id,
                    expected_candidate_ids=(manual.id,),
                ),
                selection_from_row(
                    rows[1],
                    action=StatementApplyAction.LINK_EXISTING,
                    existing_cash_flow_id=manual.id,
                    expected_candidate_ids=(manual.id,),
                ),
            ),
        )
        assert result.success is False
        assert result.error_code is StatementApplyFailureCode.VALIDATION_ERROR
        assert result.error_code is not StatementApplyFailureCode.PERSISTENCE_ERROR
        assert counts(session) == (0, 0, 1)
        session.refresh(manual)
        assert manual.source == "manual"
        assert manual.gross_amount_kopecks == 1150
    finally:
        session.close()
        database.engine.dispose()
