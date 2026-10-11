"""Hand-built #771 manifest fixtures; no Owner originals or identifiers."""

from __future__ import annotations

import json
from copy import deepcopy
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import OperationalError
from test_statement_import_mybroker import ACCOUNT, FILENAME, ISIN, fixture
from test_statement_import_mybroker import database as database

from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Account,
    Base,
    BrokerIdentityMapping,
    Instrument,
    MyBrokerImport,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.broker_identity_mappings import remap_mapping, revoke_mapping
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.mybroker_identity import preview_identity, stage_identity
from hermes_finance.services.mybroker_import import apply_mybroker, preview_mybroker
from hermes_finance.statement_import.mybroker import MyBrokerError, parse_mybroker
from hermes_finance.statement_import.mybroker_identity import parse_identity

BOND = "RU000A000001"


def identity_xml(*, bond=False, isin=ISIN, account=ACCOUNT):
    root = ET.fromstring(fixture())
    position = root.find(".//{MyBroker}Details[@ISIN1]")
    position.set("ISIN1", isin)
    position.set("acc_code", account)
    position.set("active_type", "Акции")
    position.set("active_name", "Fabricated stock")
    position.set("place", "Synthetic custody")
    trade = root.find(".//{MyBroker}Details[@trade_no]")
    trade.set("isin_reg", isin)
    trade.set("acc_code", account)
    trade.set("p_name", "Fabricated stock")
    trade.set("Textbox14", "RUB")
    root.find(".//{MyBroker}Textbox11").set("acc_code", account)
    if bond:
        collection = root.find(".//{MyBroker}active_type/{MyBroker}Details_Collection")
        row = deepcopy(position)
        row.set("ISIN1", BOND)
        row.set("active_type", "Облигации")
        row.set("active_name", "Fabricated bond")
        collection.append(row)
    return ET.tostring(root, encoding="utf-8")


def plan(session, xml=None, *, filename=FILENAME, bindings=None):
    return preview_identity(
        session, document=xml or identity_xml(), filename=filename, account_bindings=bindings or []
    )


def stage(session, reviewed, xml=None, *, filename=FILENAME, bindings=None):
    return stage_identity(
        session,
        document=xml or identity_xml(),
        filename=filename,
        account_bindings=bindings or [],
        confirmation_digest=reviewed["confirmation_digest"],
    )


def inventory(session):
    return {
        table.name: session.scalar(select(func.count()).select_from(table))
        for table in Base.metadata.sorted_tables
    }


def test_original_bound_preview_keeps_s1_v2_shape_and_writes_nothing(database):
    xml = identity_xml()
    frozen = parse_mybroker(xml, FILENAME)
    with database.session_factory() as session:
        before = inventory(session)
        reviewed = plan(session, xml)
        assert reviewed == plan(session, xml)
        assert reviewed["can_stage"] and not reviewed["can_apply"]
        assert reviewed["instruments"][0]["action"] == "reuse"
        assert reviewed["instruments"][0]["currency_basis"] == "existing_catalogue"
        assert reviewed["evidence"]["instruments"][0]["currency"] is None
        assert reviewed["evidence"]["source_parser"] == "mybroker-s1-v2"
        assert inventory(session) == before
    assert parse_mybroker(xml, FILENAME) == frozen
    assert "source_name" not in frozen["positions"][0]


def test_two_novel_stock_bond_proposals_need_currency_not_settlement_rub(database):
    xml = identity_xml(bond=True, isin="RU000A000002")
    with database.session_factory() as session:
        before = inventory(session)
        reviewed = plan(session, xml)
        assert not reviewed["can_stage"]
        assert reviewed["conflicts"] == []
        assert {r["instrument_type"] for r in reviewed["instruments"]} == {"stock", "bond"}
        for row in reviewed["instruments"]:
            assert row["action"] == row["mapping_action"] == "stage_create"
            assert row["currency"] is row["nominal_value_kopecks"] is row["ticker"] is None
            assert row["evidence_gaps"] == ["instrument_currency_unproven"]
        with pytest.raises(MyBrokerError, match="identity_batch_conflict"):
            stage(session, reviewed, xml)
        session.rollback()
        assert inventory(session) == before


def test_existing_inactive_usd_identity_preserves_currency_and_stages_mapping(database):
    with database.session_factory() as session:
        target = create_instrument(
            session,
            name="Trusted inactive catalogue",
            isin=BOND,
            instrument_type="bond",
            currency="USD",
            is_active=False,
        )
        original = (target.name, target.currency, target.is_active, target.nominal_value_kopecks)
        xml = identity_xml(bond=True)
        reviewed = plan(session, xml)
        assert reviewed["can_stage"]
        bond = next(r for r in reviewed["instruments"] if r["isin"] == BOND)
        assert bond["currency"] == "USD" and bond["action"] == "reuse"
        assert bond["mapping_action"] == "stage_create"
        before = inventory(session)
        staged = stage(session, reviewed, xml)
        assert staged["staged"] and session.in_transaction()
        with database.session_factory() as independent:
            assert inventory(independent) == before  # savepoint release never commits
        session.rollback()
        assert inventory(session) == before
        assert (
            target.name,
            target.currency,
            target.is_active,
            target.nominal_value_kopecks,
        ) == original


def test_future_outer_writer_can_commit_and_exact_replay_overlap_are_noop(database):
    with database.session_factory() as session:
        create_instrument(session, name="Trusted bond", isin=BOND, instrument_type="bond")
        xml = identity_xml(bond=True)
        before = inventory(session)
        result = stage(session, plan(session, xml), xml)
        session.commit()  # synthetic future outer writer; no standalone product Apply
        assert len(result["mappings"]) == 4
        accepted = inventory(session)
        assert accepted["instruments"] == before["instruments"]
        assert accepted["broker_identity_mappings"] == before["broker_identity_mappings"] + 1
        for filename in (FILENAME, "Брокерский 1234567 (15.01.30-31.01.30).xml"):
            fresh = plan(session, xml, filename=filename)
            assert all(r["action"] == r["mapping_action"] == "reuse" for r in fresh["instruments"])
            stage(session, fresh, xml, filename=filename)
            session.commit()
            assert inventory(session) == accepted


def test_same_instrument_in_two_accounts_reuses_one_global_identity(database):
    with database.session_factory() as session:
        account = create_account(
            session, name="Other synthetic brokerage", account_type="brokerage"
        )
        filename = "Брокерский 7654321 (01.01.30-31.01.30).xml"
        xml = identity_xml(account="7654321-000")
        explicit = [
            {"identity": alias, "hermes_id": account.id} for alias in ("7654321", "7654321-000")
        ]
        before = inventory(session)
        reviewed = plan(session, xml, filename=filename, bindings=explicit)
        assert reviewed["can_stage"]
        stage(session, reviewed, xml, filename=filename, bindings=explicit)
        session.commit()
        assert inventory(session)["instruments"] == before["instruments"]
        instrument_bindings = list(
            session.scalars(
                select(BrokerIdentityMapping).where(
                    BrokerIdentityMapping.subject_kind == "instrument"
                )
            )
        )
        assert len(instrument_bindings) == 1


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("active_type", None, "instrument_type_unproven"),
        ("active_type", "Фонды", "instrument_type_unsupported"),
        ("active_type", "Акции\nОблигации", "ambiguous_or_missing_field"),
        ("active_name", None, "instrument_name_unproven"),
        ("ISIN1", "not-an-isin", "instrument_isin_invalid"),
    ],
)
def test_ambiguous_or_missing_metadata_blocks_entire_batch(database, field, value, expected):
    root = ET.fromstring(identity_xml(bond=True))
    row = root.find(".//{MyBroker}Details[@ISIN1]")
    if value is None:
        row.attrib.pop(field)
    else:
        row.set(field, value)
    xml = ET.tostring(root, encoding="utf-8")
    with database.session_factory() as session:
        before = inventory(session)
        if "\n" in (value or ""):
            with pytest.raises(MyBrokerError, match=expected):
                plan(session, xml)
        else:
            reviewed = plan(session, xml)
            assert not reviewed["can_stage"]
            assert expected in reviewed["conflicts"] + [
                g["code"] for g in reviewed["evidence_gaps"]
            ]
            with pytest.raises(MyBrokerError, match="identity_batch_conflict"):
                stage(session, reviewed, xml)
            session.rollback()
        assert inventory(session) == before


def test_trade_only_never_infers_type_from_name_or_current_catalogue(database):
    root = ET.fromstring(identity_xml())
    collection = root.find(".//{MyBroker}active_type/{MyBroker}Details_Collection")
    collection.remove(collection[0])
    with database.session_factory() as session:
        reviewed = plan(session, ET.tostring(root))
        assert not reviewed["can_stage"]
        assert "instrument_type_unproven" in reviewed["instruments"][0]["evidence_gaps"]


def test_duplicate_aliases_and_inconsistent_account_are_atomic_conflicts(database):
    with database.session_factory() as session:
        account = session.scalar(select(Account))
        repeated = [{"identity": ACCOUNT, "hermes_id": account.id}] * 2
        reviewed = plan(session, bindings=repeated)
        assert "duplicate_account_alias" in reviewed["conflicts"]
        root = ET.fromstring(identity_xml())
        collection = root.find(".//{MyBroker}active_type/{MyBroker}Details_Collection")
        collection.append(deepcopy(collection[0]))
        reviewed = plan(session, ET.tostring(root))
        assert "duplicate_position_alias" in reviewed["conflicts"]
        other = create_account(session, name="Other", account_type="brokerage")
        reviewed = plan(session, bindings=[{"identity": ACCOUNT, "hermes_id": other.id}])
        assert "account_mapping_conflict" in reviewed["conflicts"]


@pytest.mark.parametrize(
    "model,field,value",
    [
        (Instrument, "currency", "USD"),
        (Instrument, "instrument_type", "bond"),
        (Account, "status", "frozen"),
        (BrokerIdentityMapping, "observed_isin", "RU000A000002"),
    ],
)
def test_catalogue_and_mapping_a_b_a_revision_retires_preview(database, model, field, value):
    with database.session_factory() as session:
        reviewed = plan(session)
        query = select(model)
        if model is BrokerIdentityMapping:
            query = query.where(model.subject_kind == "instrument")
        row = session.scalar(query)
        original = getattr(row, field)
        setattr(row, field, value)
        session.commit()
        setattr(row, field, original)
        session.commit()
        before = inventory(session)
        with pytest.raises(MyBrokerError, match="identity_preview_stale"):
            stage(session, reviewed)
        session.rollback()
        assert inventory(session) == before


def test_source_and_filename_changes_retire_preview(database):
    with database.session_factory() as session:
        reviewed = plan(session)
        changed = identity_xml().replace(b"Synthetic custody", b"Another custody")
        with pytest.raises(MyBrokerError, match="identity_preview_stale"):
            stage(session, reviewed, changed)
        session.rollback()
        with pytest.raises(MyBrokerError, match="identity_preview_stale"):
            stage(session, reviewed, filename="Брокерский 1234567 (02.01.30-31.01.30).xml")
        session.rollback()
        xml = identity_xml()
        old = preview_mybroker(session, document=xml, filename=FILENAME)
        apply_mybroker(
            session,
            document=xml,
            filename=FILENAME,
            confirmation_digest=old["confirmation_digest"],
            confirmed_range=(old["document"]["covered_from"], old["document"]["covered_to"]),
            confirmed_mappings=old["mappings"],
        )
        with pytest.raises(MyBrokerError, match="identity_preview_stale"):
            stage(session, reviewed)
        session.rollback()


def test_mid_batch_failure_rolls_back_all_mappings_without_outer_commit(database):
    with database.session_factory() as session:
        create_instrument(session, name="Trusted bond", isin=BOND, instrument_type="bond")
        other = create_account(session, name="Other", account_type="brokerage")
        xml = identity_xml(account="7654321-000", bond=True)
        filename = "Брокерский 7654321 (01.01.30-31.01.30).xml"
        explicit = [
            {"identity": alias, "hermes_id": other.id} for alias in ("7654321", "7654321-000")
        ]
        reviewed = plan(session, xml, filename=filename, bindings=explicit)
        before = inventory(session)

        def fail_second_mapping(_session, _context, _instances):
            if any(
                isinstance(row, BrokerIdentityMapping) and row.provider_identity == "7654321-000"
                for row in _session.new
            ):
                raise RuntimeError("synthetic flush failure")

        event.listen(session, "before_flush", fail_second_mapping)
        try:
            with pytest.raises(RuntimeError, match="synthetic flush failure"):
                stage(session, reviewed, xml, filename=filename, bindings=explicit)
        finally:
            event.remove(session, "before_flush", fail_second_mapping)
        assert inventory(session) == before
        session.commit()  # even an erroneous caller cannot persist a partial helper batch
        assert inventory(session) == before


def test_http_identity_preview_typed_gaps_rejects_skip_and_has_no_apply(database):
    client = TestClient(create_app(database=database))
    files = {"file": (FILENAME, identity_xml(bond=True), "application/xml")}
    response = client.post("/api/mybroker-import/identity-preview", files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["evidence_gaps"] == [{"isin": BOND, "code": "instrument_currency_unproven"}]
    assert not body["can_stage"] and not body["can_apply"]
    invalid = client.post(
        "/api/mybroker-import/identity-preview",
        files=files,
        data={"intent": json.dumps({"skipped_isins": [BOND]})},
    )
    assert invalid.status_code == 422 and "identity_intent_invalid" in invalid.text
    assert client.post("/api/mybroker-import/identity-apply", files=files).status_code in (404, 405)
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 0


def test_manifest_does_not_read_invented_position_currency_or_group_type():
    root = ET.fromstring(identity_xml(isin=BOND))
    row = root.find(".//{MyBroker}Details[@ISIN1]")
    row.set("currency", "RUB")
    row.attrib.pop("active_type")
    root.find(".//{MyBroker}active_type").set("active_type", "Облигации")
    observed = parse_identity(ET.tostring(root), FILENAME)["instruments"][0]
    assert observed["currency"] is observed["instrument_type"] is None
    assert "instrument_type_unproven" in observed["evidence_gaps"]


def test_legacy_skip_is_not_silently_corrected_by_identity_stage(database):
    xml = identity_xml()
    with database.session_factory() as session:
        old = preview_mybroker(
            session, document=xml, filename=FILENAME, skipped_isins=(ISIN,), owner_reviewed=True
        )
        apply_mybroker(
            session,
            document=xml,
            filename=FILENAME,
            confirmation_digest=old["confirmation_digest"],
            confirmed_range=(old["document"]["covered_from"], old["document"]["covered_to"]),
            confirmed_mappings=old["mappings"],
            skipped_isins=(ISIN,),
            owner_reviewed=True,
            request_id="synthetic_skip",
        )
        before = inventory(session)
        reviewed = plan(session, xml)
        assert "instrument_disposition_reconciliation_required" in reviewed["conflicts"]
        with pytest.raises(MyBrokerError, match="identity_batch_conflict"):
            stage(session, reviewed, xml)
        session.rollback()
        assert inventory(session) == before


def test_incompatible_revoked_binding_blocks_reconfirmation(database):
    with database.session_factory() as session:
        target = create_instrument(
            session, name="Other synthetic identity", instrument_type="stock", isin=BOND
        )
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "instrument")
        )
        revoke_mapping(session, mapping.id)
        mapping.hermes_instrument_id = target.id
        session.commit()
        reviewed = plan(session)
        assert "revoked_instrument_binding_conflict" in reviewed["conflicts"]
        before = inventory(session)
        with pytest.raises(MyBrokerError, match="identity_batch_conflict"):
            stage(session, reviewed)
        session.rollback()
        assert inventory(session) == before


def test_opaque_service_section_is_visible_without_granting_financial_authority(database):
    root = ET.fromstring(identity_xml())
    ET.SubElement(root.find("{MyBroker}Trades4/{MyBroker}Report"), "{MyBroker}Tablix1")
    with database.session_factory() as session:
        reviewed = plan(session, ET.tostring(root))
        assert reviewed["can_stage"]
        assert reviewed["evidence"]["source_warnings"] == ["5_UFSR_unsupported"]
        assert not reviewed["can_apply"]


def test_outer_writer_reservation_survives_staging_until_rollback(database):
    with database.session_factory() as writer, database.session_factory() as contender:
        reviewed = plan(writer)
        stage(writer, reviewed)
        row = contender.scalar(select(Instrument))
        with pytest.raises(OperationalError, match="database is locked"):
            contender.execute(
                update(Instrument)
                .where(Instrument.id == row.id)
                .values(name="Concurrent synthetic change")
            )
        contender.rollback()
        writer.rollback()
        contender.execute(
            update(Instrument)
            .where(Instrument.id == row.id)
            .values(name="Concurrent synthetic change")
        )
        contender.rollback()


def test_fresh_preview_cannot_rebind_an_already_accepted_original(database):
    xml = identity_xml()
    with database.session_factory() as session:
        old = preview_mybroker(session, document=xml, filename=FILENAME)
        apply_mybroker(
            session,
            document=xml,
            filename=FILENAME,
            confirmation_digest=old["confirmation_digest"],
            confirmed_range=(old["document"]["covered_from"], old["document"]["covered_to"]),
            confirmed_mappings=old["mappings"],
        )
        other = create_account(session, name="Other", account_type="brokerage")
        for mapping in list(
            session.scalars(
                select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "account")
            )
        ):
            remap_mapping(session, mapping.id, hermes_target_id=other.id)
        reviewed = plan(session, xml)
        assert "accepted_mapping_conflict" in reviewed["conflicts"]
        before = inventory(session)
        with pytest.raises(MyBrokerError, match="identity_batch_conflict"):
            stage(session, reviewed, xml)
        session.rollback()
        assert inventory(session) == before


def test_contradictory_trade_currency_observations_block_whole_batch(database):
    root = ET.fromstring(identity_xml(bond=True))
    root.find(".//{MyBroker}Details[@trade_no]").set("Textbox14", "USD")
    xml = ET.tostring(root)
    with database.session_factory() as session:
        create_instrument(session, name="Trusted bond", isin=BOND, instrument_type="bond")
        before = inventory(session)
        reviewed = plan(session, xml)
        assert reviewed["conflicts"] == ["trade_currency_observation_conflict"]
        assert reviewed["evidence_gaps"] == []
        assert not reviewed["can_stage"]
        assert reviewed["evidence"]["instruments"][0]["currency"] is None
        with pytest.raises(MyBrokerError, match="identity_batch_conflict"):
            stage(session, reviewed, xml)
        session.rollback()
        assert inventory(session) == before
