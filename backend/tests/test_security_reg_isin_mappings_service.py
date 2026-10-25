"""Invented identifiers only; owner crosswalk persistence and offline attribution."""

from datetime import date

import pytest
from sqlalchemy import select
from test_source_money_classifications_service import (
    DIVIDEND_SECURITY,
    _security_instrument,
    _security_mapping,
    saved_rows,
)
from test_source_monthly_returns_service import db as db
from test_source_monthly_returns_service import save_month, snapshot

from hermes_finance.domain.money_security import parse_money_security
from hermes_finance.persistence import ReportingMonth, SecurityRegIsinMapping
from hermes_finance.services import security_reg_isin_mappings as mappings
from hermes_finance.services.money_instrument_links import MoneyInstrumentResolver

REG = "1-01-99999-Z"
ISIN = "ZZ0000000011"
OTHER_ISIN = "ZZ0000000022"


def test_csv_import_normalizes_upserts_and_is_idempotent(db, tmp_path):
    path = tmp_path / "invented-mappings.csv"
    path.write_text(
        f'reg_number,isin,note\n {REG.lower()} ,{ISIN.lower()},"Synthetic, note"\n'
        f'{REG},{ISIN},"Synthetic, note"\n',
        encoding="utf-8-sig",
    )
    with db.session_factory() as session:
        assert mappings.import_csv(session, path) == {"processed": 1, "changed": 1}
        before = mappings.list_mappings(session)
        assert before[0]["reg_number"] == REG
        assert before[0]["isin"] == ISIN
        assert before[0]["note"] == "Synthetic, note"
        assert mappings.import_csv(session, path) == {"processed": 1, "changed": 0}
        assert mappings.list_mappings(session) == before
        updated = mappings.set_mapping(session, REG.lower(), OTHER_ISIN, " replacement ")
        assert updated["id"] == before[0]["id"]
        assert updated["created_at"] == before[0]["created_at"]
        assert updated["updated_at"] > before[0]["updated_at"]
        assert (updated["isin"], updated["note"]) == (OTHER_ISIN, "replacement")
        assert mappings.set_mapping(session, REG, OTHER_ISIN, "replacement") == updated
        assert mappings.remove_mapping(session, REG.lower()) == {"removed": True}
        assert mappings.remove_mapping(session, REG) == {"removed": False}
        assert mappings.list_mappings(session) == []


@pytest.mark.parametrize(
    "body,reason",
    [
        ("isin,reg_number,note\n", "csv_header_invalid"),
        (f"reg_number,isin,note\n{REG},{ISIN}\n", "csv_row_invalid"),
        (f"reg_number,isin,note\n{REG},{ISIN},,extra\n", "csv_row_invalid"),
        (f"reg_number,isin,note\ninvalid,{ISIN},\n", "reg_number_invalid"),
        (f"reg_number,isin,note\n{REG},ZZ123,\n", "isin_invalid"),
        (f"reg_number,isin,note\n{REG},Z10000000011,\n", "isin_invalid"),
        (f"reg_number,isin,note\n{REG},ZZ000000001Z,\n", "isin_invalid"),
        (f"reg_number,isin,note\n{REG},ZZ00000000!1,\n", "isin_invalid"),
        (
            f"reg_number,isin,note\n{REG},{ISIN},\n{REG.lower()},{OTHER_ISIN},\n",
            "csv_duplicate_conflict",
        ),
    ],
)
def test_invalid_csv_keeps_all_existing_data(db, tmp_path, body, reason):
    with db.session_factory() as session:
        mappings.set_mapping(session, REG, ISIN, "Synthetic retained")
    before = snapshot(db)
    path = tmp_path / "invalid.csv"
    path.write_text(body, encoding="utf-8")
    with db.session_factory() as session, pytest.raises(ValueError, match=reason):
        mappings.import_csv(session, path)
    assert snapshot(db) == before


def test_csv_failure_after_flushed_upsert_rolls_back_whole_import(db, tmp_path, monkeypatch):
    path = tmp_path / "invented.csv"
    path.write_text(
        f"reg_number,isin,note\n{REG},{ISIN},\n4B02-09-99999-Z-001P,{OTHER_ISIN},\n",
        encoding="utf-8",
    )
    original_upsert = mappings._upsert

    def failing_upsert(session, *values):
        result = original_upsert(session, *values)
        if values[0] != REG:
            raise RuntimeError("synthetic failure after flush")
        return result

    monkeypatch.setattr(mappings, "_upsert", failing_upsert)
    before = snapshot(db)
    with db.session_factory() as session, pytest.raises(RuntimeError, match="synthetic failure"):
        mappings.import_csv(session, path)
    assert snapshot(db) == before


@pytest.mark.parametrize("reg,isin", [("", ISIN), (" \t", ISIN), ("bad", ISIN), (REG, "")])
def test_set_rejects_invalid_values_before_writing(db, reg, isin):
    before = snapshot(db)
    with db.session_factory() as session, pytest.raises(ValueError):
        mappings.set_mapping(session, reg, isin)
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("catalog", "linked"),
        ("observed", "linked"),
        ("both_same_target", "linked"),
        ("none", "unresolved_no_match"),
        ("revoked", "unresolved_no_match"),
        ("other_provider", "unresolved_no_match"),
        ("catalog_collision", "unresolved_ambiguous"),
        ("observed_collision", "unresolved_ambiguous"),
        ("conflict", "unresolved_ambiguous"),
        ("direct_reg_conflict", "unresolved_ambiguous"),
    ],
)
def test_owner_crosswalk_resolves_only_unique_nonconflicting_targets(db, mode, expected):
    with db.session_factory() as session:
        target = _security_instrument(
            session,
            isin=ISIN if mode in {"catalog", "both_same_target", "catalog_collision"} else None,
        )
        if mode in {"observed", "both_same_target", "revoked", "other_provider", "conflict"}:
            if mode == "conflict":
                target.isin = OTHER_ISIN
            _security_mapping(
                session,
                target,
                "SYNTHETIC-ALIAS",
                isin=ISIN,
                status="revoked" if mode == "revoked" else "effective",
                provider="synthetic_other" if mode == "other_provider" else "alfa_mybroker",
            )
        if mode in {"catalog_collision", "observed_collision", "direct_reg_conflict"}:
            if mode == "observed_collision":
                _security_mapping(session, target, "SYNTHETIC-FIRST", isin=ISIN)
            second = _security_instrument(
                session,
                name="АО Другая синтетика",
                isin=ISIN.lower() if mode == "catalog_collision" else None,
            )
            if mode != "catalog_collision":
                _security_mapping(
                    session,
                    second,
                    REG if mode == "direct_reg_conflict" else "SYNTHETIC-SECOND",
                    isin=OTHER_ISIN if mode == "direct_reg_conflict" else ISIN,
                )
                if mode == "direct_reg_conflict":
                    target.isin = ISIN
        session.commit()
        instrument_id = target.id
        security = parse_money_security(DIVIDEND_SECURITY)
        if mode == "catalog":
            # Names and a catalog ISIN alone cannot invent a registration crosswalk.
            assert MoneyInstrumentResolver(session).resolve(security) == (
                None,
                "unresolved_no_match",
            )
        mappings.set_mapping(session, REG.lower(), ISIN.lower())
        assert MoneyInstrumentResolver(session).resolve(security) == (
            instrument_id if expected == "linked" else None,
            expected,
        )


def test_owner_crosswalk_cannot_link_only_through_contradictory_registration_alias(db):
    with db.session_factory() as session:
        target = _security_instrument(session, isin=OTHER_ISIN)
        _security_mapping(session, target, REG, isin=OTHER_ISIN)
        session.commit()
        mappings.set_mapping(session, REG, ISIN)
        assert MoneyInstrumentResolver(session).resolve(
            parse_money_security(DIVIDEND_SECURITY)
        ) == (
            None,
            "unresolved_ambiguous",
        )


def test_other_crosswalk_rows_do_not_supply_reverse_registration_candidates(db):
    with db.session_factory() as session:
        target = _security_instrument(session)
        _security_mapping(session, target, "1-02-99999-Z")
        session.commit()
        mappings.set_mapping(session, "1-02-99999-Z", ISIN)
        mappings.set_mapping(session, REG, ISIN)
        assert MoneyInstrumentResolver(session).resolve(
            parse_money_security(DIVIDEND_SECURITY)
        ) == (
            None,
            "unresolved_no_match",
        )


def test_relink_updates_only_derived_fields_and_preserves_manual_decisions(db):
    from hermes_finance.services.source_money_classifications import choose_classification

    with db.session_factory() as session:
        target = _security_instrument(session, isin=ISIN)
        target_id = target.id
        session.commit()
    intake, _ = save_month(
        db,
        candidate_count=0,
        extra=(("Перевод", DIVIDEND_SECURITY, "12.34"), ("Перевод", "Synthetic refund", "-5")),
    )
    row = saved_rows(db, intake)[0]
    with db.session_factory() as session:
        choose_classification(session, intake, row.source_reference, "dividend")
        mappings.set_mapping(session, REG, ISIN)
    original = saved_rows(db, intake)
    before = snapshot(db)
    with db.session_factory() as session:
        assert mappings.relink(session) == {"processed": 2, "changed": 1, "skipped_closed": 0}
    after = snapshot(db)
    # Derived classification changes also retire source-return evidence. Only
    # its nonce may advance; proof records and all financial tables stay equal.
    changed_tables = {"source_intake_money_classifications", "source_return_proof_dependencies"}
    assert {k: v for k, v in before.items() if k not in changed_tables} == {
        k: v for k, v in after.items() if k not in changed_tables
    }
    assert (
        after["source_return_proof_dependencies"][:-1] == before["source_return_proof_dependencies"]
    )
    assert len(after["source_return_proof_dependencies"]) == (
        len(before["source_return_proof_dependencies"]) + 1
    )
    linked = saved_rows(db, intake)
    assert linked[0].instrument_id == target_id
    for previous, current in zip(original, linked, strict=True):
        assert (
            current.id,
            current.classification,
            current.origin,
            current.status,
            current.created_at,
            current.updated_at,
        ) == (
            previous.id,
            previous.classification,
            previous.origin,
            previous.status,
            previous.created_at,
            previous.updated_at,
        )
    with db.session_factory() as session:
        assert mappings.relink(session)["changed"] == 0
    assert snapshot(db) == after
    with db.session_factory() as session:
        mappings.remove_mapping(session, REG)
        mappings.relink(session)
    unlinked = saved_rows(db, intake)[0]
    assert (unlinked.instrument_id, unlinked.instrument_link_status) == (
        None,
        "unresolved_no_match",
    )
    assert unlinked.updated_at == original[0].updated_at


def test_relink_skips_closed_bound_month_until_reopened(db):
    from test_statement_import_broker_statement_provisional import FILENAME_APRIL, provisional_xml

    from hermes_finance.services import source_intake
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.reporting_months import (
        create_reporting_month,
        reopen_reporting_month,
    )

    with db.session_factory() as session:
        account = create_account(session, name="Synthetic brokerage", account_type="brokerage")
        month = create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 30))
        target = _security_instrument(session, isin=ISIN)
        target_id, month_id = target.id, month.id
        session.commit()
        ack = source_intake.save_intake(
            session,
            document=provisional_xml(
                candidate_count=0, extra_money=(("Перевод", DIVIDEND_SECURITY, "12.34"),)
            ),
            filename=FILENAME_APRIL,
            request_id="synthetic-closed-relink",
            account_id=account.id,
            reporting_month_id=month_id,
        )
        session.get(ReportingMonth, month_id).status = "closed"
        session.commit()
        mappings.set_mapping(session, REG, ISIN)
    before = snapshot(db)
    with db.session_factory() as session:
        assert mappings.relink(session) == {"processed": 0, "changed": 0, "skipped_closed": 1}
    assert snapshot(db) == before
    with db.session_factory() as session:
        reopen_reporting_month(session, month_id)
        assert mappings.relink(session)["changed"] == 1
    assert saved_rows(db, ack["intake_id"])[0].instrument_id == target_id


def test_relink_failure_rolls_back_all_link_changes(db, monkeypatch):
    with db.session_factory() as session:
        _security_instrument(session, isin=ISIN)
        session.commit()
        mappings.set_mapping(session, REG, ISIN)
    intake, _ = save_month(
        db,
        candidate_count=0,
        extra=(("Перевод", DIVIDEND_SECURITY, "12.34"), ("Перевод", DIVIDEND_SECURITY, "1")),
    )
    with db.session_factory() as session:
        mappings.remove_mapping(session, REG)
    original_apply = mappings.apply_money_instrument_link
    calls = 0

    def failing_apply(row, resolver):
        nonlocal calls
        original_apply(row, resolver)
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic relink failure")

    before = snapshot(db)
    monkeypatch.setattr(mappings, "apply_money_instrument_link", failing_apply)
    with (
        db.session_factory() as session,
        pytest.raises(RuntimeError, match="synthetic relink failure"),
    ):
        mappings.relink(session)
    assert snapshot(db) == before
    assert all(row.instrument_link_status == "linked" for row in saved_rows(db, intake))


def test_upload_new_save_and_classification_put_use_current_owner_crosswalk(db):
    from hermes_finance.services import source_intake
    from hermes_finance.services.source_money_classifications import choose_classification

    with db.session_factory() as session:
        target = _security_instrument(session, isin=ISIN)
        target_id = target.id
        session.commit()
        mappings.set_mapping(session, REG, ISIN)
    intake, (raw, filename) = save_month(
        db, candidate_count=0, extra=(("Перевод", DIVIDEND_SECURITY, "12.34"),)
    )
    row = saved_rows(db, intake)[0]
    assert row.instrument_id == target_id
    with db.session_factory() as session:
        mappings.set_mapping(session, REG, OTHER_ISIN)
        chosen = choose_classification(session, intake, row.source_reference, "dividend")
        assert chosen["instrument_link_status"] == "unresolved_no_match"
        mappings.set_mapping(session, REG, ISIN)
        source_intake.save_intake(
            session, document=raw, filename=filename, request_id="refresh-owner-crosswalk"
        )
    refreshed = saved_rows(db, intake)[0]
    assert refreshed.instrument_id == target_id
    assert refreshed.origin == "user_choice"
    assert refreshed.updated_at.isoformat() == chosen["updated_at"].replace(tzinfo=None).isoformat()


def test_mapping_model_enforces_storage_constraints(db):
    from datetime import UTC, datetime

    from sqlalchemy.exc import IntegrityError

    for reg, isin in [(REG.lower(), ISIN), (REG, ISIN.lower()), (REG, "ZZ000000001Z")]:
        with db.session_factory() as session, pytest.raises(IntegrityError):
            session.add(
                SecurityRegIsinMapping(
                    reg_number=reg,
                    isin=isin,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
            session.commit()
    with db.session_factory() as session:
        assert list(session.scalars(select(SecurityRegIsinMapping))) == []
