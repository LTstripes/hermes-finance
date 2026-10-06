"""Private-free H0 acceptance vectors over real synthetic S1/S2 entrypoints."""

import json
from datetime import date
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from test_statement_import_executed_trades import accept_source, identity, mutate, promote
from test_statement_import_mybroker import ACCOUNT, ISIN, fixture, include_source_account
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import endpoint_xml, positions_only

from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Account,
    Base,
    BrokerIdentityMapping,
    CashBalance,
    MyBrokerImport,
    ReportingMonth,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.broker_identity_mappings import revoke_mapping
from hermes_finance.services.historical_reconstruction import preview_historical_reconstruction
from hermes_finance.statement_import.mybroker import MyBrokerError, canonical


def inventory(session, ids=None, start=date(2029, 12, 31), end=date(2030, 3, 31)):
    return preview_historical_reconstruction(
        session, account_ids=ids or [1], requested_from=start, requested_to=end
    )


def all_tables(session):
    return {
        table.name: [tuple(row) for row in session.execute(select(table))]
        for table in Base.metadata.sorted_tables
    }


def endpoint(report, side, import_id=None):
    return next(
        s
        for s in report["accounts"][0]["endpoints"]
        if s["side"] == side and (import_id is None or s["import_id"] == import_id)
    )


def test_earliest_event_separate_from_execution_and_wide_report_not_interior_endpoints(database):
    with database.session_factory() as session:
        include_source_account(session)
        first = accept_source(session, fixture())
        later = mutate(
            fixture(primary="10000000002"),
            db_time="15.02.2030 9:00:00",
            save_settlement_date="17.02.2030",
            save_depo_settlement_date="17.02.2030",
        )
        second = accept_source(session, later, "Брокерский 1234567 (01.01.30-31.03.30).xml")
        promote(session, [identity(second)])
        before = all_tables(session)
        report = inventory(session)
        account = report["accounts"][0]
        assert account["earliest_observed_source_event"] == "2030-01-15"
        assert account["earliest_accepted_canonical_execution"] == "2030-02-15"
        assert [s["cutoff"] for s in account["endpoints"]] == [
            "2029-12-31",
            "2030-01-31",
            "2029-12-31",
            "2030-03-31",
        ]
        assert account["month_end_inventory"][2]["cutoff"] == "2030-02-28"
        assert account["month_end_inventory"][2]["source_sides"] == []
        assert account["source_range_gaps"] == [{"from": "2029-12-31", "to": "2029-12-31"}]
        assert account["source_range_overlaps"][0]["import_ids"] == [
            first["import_id"],
            second["import_id"],
        ]
        assert report["coverage_state"] == "unknown"
        assert account["availability"]["account_portfolio_xirr"] == "not_evaluated"
        assert all_tables(session) == before


def test_beginning_missing_does_not_hide_ending_and_explicit_cash_zero_is_only_observation(
    database,
):
    with database.session_factory() as session:
        include_source_account(session)
        xml = positions_only(endpoint_xml(beginning=None, rub_amounts=(None, "0")))
        root = ET.fromstring(xml)
        root.find(".//{MyBroker}Details").attrib.pop("income_volume")
        accept_source(session, ET.tostring(root))
        report = inventory(session)
        opening, closing = endpoint(report, "beginning"), endpoint(report, "ending")
        assert opening["components"]["rub_cash"] == "unknown"
        assert "endpoint_value_unavailable" in opening["blockers"]
        assert "endpoint_quantity_unavailable" in opening["blockers"]
        assert closing["observation_state"] == "observed"
        assert closing["components"]["rub_cash"] == "observed_zero"
        assert closing["blockers"] == []
        assert closing["complete_endpoint_state"] == "unknown"
        assert not closing["financial_apply_available"]


def test_quiet_and_other_broker_account_remain_unknown_no_current_membership_fallback(database):
    with database.session_factory() as session:
        accept_source(session, fixture(quiet=True))
        other = create_account(session, name="Synthetic other broker", account_type="brokerage")
        report = inventory(session, [1, other.id])
        quiet, missing = report["accounts"]
        assert quiet["availability"]["event_history"] == "quiet_unknown"
        assert quiet["earliest_observed_source_event"] is None
        assert quiet["earliest_accepted_canonical_execution"] is None
        assert all(s["observation_state"] == "unknown" for s in quiet["endpoints"])
        assert "historical_membership_unknown" in quiet["blockers"]
        assert "accepted_source_unavailable" in missing["blockers"]
        assert missing["availability"]["financial_coverage"] == "unknown"


@pytest.mark.parametrize("kind", ["pending", "forward", "cash_date", "custody_date"])
def test_cutoff_exposure_is_independent_and_never_promoted(database, kind):
    with database.session_factory() as session:
        include_source_account(session)
        if kind == "forward":
            xml = positions_only(endpoint_xml(forward="11"))
            reason = "forward_exposure_at_cutoff"
        elif kind == "pending":
            xml, reason = fixture(pending=True), "pending_at_cutoff"
        else:
            field = "save_settlement_date" if kind == "cash_date" else "save_depo_settlement_date"
            xml = mutate(fixture(money=False), **{field: "03.02.2030"})
            reason = "settlement_crosses_cutoff"
        accept_source(session, xml)
        report = inventory(session)
        assert reason in endpoint(report, "ending")["blockers"]
        assert not report["financial_apply_available"]


def test_source_settled_cannot_relax_accepted_pending_until_canonical_enrichment(database):
    with database.session_factory() as session:
        include_source_account(session)
        pending = accept_source(session, fixture(pending=True))
        promote(session, [identity(pending)])
        accept_source(session, fixture(), "Брокерский 1234567 (01.01.30-28.02.30).xml")
        later = accept_source(
            session, fixture(quiet=True), "Брокерский 1234567 (01.03.30-31.03.30).xml"
        )
        report = inventory(session)
        assert "pending_at_cutoff" in endpoint(report, "ending", later["import_id"])["blockers"]
        old_digest = report["preview_digest"]
        promote(session, [identity(pending)])
        reread = inventory(session)
        assert "pending_at_cutoff" not in endpoint(reread, "ending", later["import_id"])["blockers"]
        assert reread["preview_digest"] != old_digest


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("repo", "repo_semantics_unsupported"),
        ("transfers", "4_Transfers_unsupported"),
        ("incomplete", "trade_ids_incomplete"),
        ("currency", "currency_unsupported"),
        ("unknown", "unparsed_source_rows"),
    ],
)
def test_unsupported_source_visible_without_s2_promotion(database, kind, reason):
    with database.session_factory() as session:
        xml = fixture(missing_id=kind == "incomplete", unsupported=kind == "transfers")
        if kind in ("repo", "currency"):
            xml = mutate(
                xml, **({"repo_no": "synthetic"} if kind == "repo" else {"curr_calc": "USD"})
            )
        if kind == "unknown":
            root = ET.fromstring(xml)
            ET.SubElement(root.find(".//{MyBroker}Positions/{MyBroker}Report"), "{MyBroker}Unknown")
            xml = ET.tostring(root)
        accept_source(session, xml)
        report = inventory(session)
        a = report["accounts"][0]
        assert reason in a["blockers"] or any(
            reason in op["blockers"] for op in a["candidate_operations"]
        )
        assert a["canonical_executions"] == []
        assert not report["financial_apply_available"]


def test_accepted_month_facts_and_closed_state_are_reported_unchanged_and_reread(database):
    with database.session_factory() as session:
        include_source_account(session)
        accept_source(
            session, positions_only(endpoint_xml()), "Брокерский 1234567 (01.01.30-31.03.30).xml"
        )
        month = ReportingMonth(
            year=2030,
            month=3,
            period_start=date(2030, 3, 1),
            period_end=date(2030, 3, 31),
            snapshot_date=date(2030, 3, 31),
            status="closed",
        )
        session.add(month)
        session.flush()
        session.add(
            CashBalance(
                reporting_month_id=month.id,
                account_id=1,
                name="Synthetic cash",
                amount_kopecks=987654321,
            )
        )
        session.commit()
        before = all_tables(session)
        report = inventory(session)
        assert report["accounts"][0]["hermes_month_overlap"] == [
            {
                "month_id": month.id,
                "status": "closed",
                "snapshot_date": "2030-03-31",
                "fact_categories": ["cash_balances"],
                "source_range_overlap": True,
                "operation": "inspect_overlap_requires_reconciliation",
            }
        ]
        assert all_tables(session) == before
        with database.session_factory() as writer:
            writer.get(ReportingMonth, month.id).status = "draft"
            writer.commit()
        reread = inventory(session)
        assert reread["accounts"][0]["hermes_month_overlap"][0]["status"] == "draft"
        assert reread["preview_digest"] != report["preview_digest"]


def test_mapping_and_membership_changes_visible_in_reused_session(database):
    with database.session_factory() as session:
        accept_source(session, positions_only(endpoint_xml()))
        before = inventory(session)
        with database.session_factory() as writer:
            include_source_account(writer)
        member = inventory(session)
        assert member["preview_digest"] != before["preview_digest"]
        assert "historical_membership_unknown" not in endpoint(member, "ending")["blockers"]
        with database.session_factory() as writer:
            mapping = writer.scalar(
                select(BrokerIdentityMapping).where(BrokerIdentityMapping.provider_identity == ISIN)
            )
            revoke_mapping(writer, mapping.id, reason="synthetic")
        changed = inventory(session)
        assert changed["preview_digest"] != member["preview_digest"]
        assert "instrument_mapping_changed_or_missing" in endpoint(changed, "ending")["blockers"]
        # Current account inclusion cannot replace historical membership.
        with database.session_factory() as writer:
            writer.get(Account, 1).include_in_returns = False
            writer.commit()
        assert endpoint(inventory(session), "ending")["historical_membership"] is True


def test_prior_eod_leap_day_and_midmonth_not_month_end(database):
    with database.session_factory() as session:
        accept_source(
            session, positions_only(endpoint_xml()), "Брокерский 1234567 (01.03.32-15.03.32).xml"
        )
        report = inventory(session, start=date(2032, 3, 1), end=date(2032, 3, 31))
        assert endpoint(report, "beginning")["cutoff"] == "2032-02-29"
        assert endpoint(report, "ending")["cutoff"] == "2032-03-15"
        assert report["accounts"][0]["month_end_inventory"][0]["source_sides"] == []


def test_http_privacy_no_mutation_no_normalized_client_authority(database, monkeypatch):
    with database.session_factory() as session:
        accept_source(session, endpoint_xml())
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())

    event.listen(database.engine, "before_cursor_execute", record)
    # No provider/network entry point is needed for persisted inventory.
    import socket

    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("network call"))
    with TestClient(create_app(database=database)) as client:
        request = {"account_ids": [1], "requested_from": "2030-01-01", "requested_to": "2030-03-31"}
        response = client.post("/api/historical-reconstruction/preview", json=request)
        assert response.status_code == 200
        encoded = json.dumps(response.json())
        for private in (
            ACCOUNT,
            ISIN,
            "1234567",
            "10000000001",
            "Synthetic name",
            "1000",
            "800",
            "500",
            "XML",
        ):
            # Digests are opaque; assert against complete JSON string/scalar tokens.
            assert f'"{private}"' not in encoded
        for key in (
            "quantity",
            "price",
            "amount",
            "core",
            "bindings",
            "source_account",
            "normalized_json",
        ):
            assert f'"{key}":' not in encoded
        assert not set(statements) & {"INSERT", "UPDATE", "DELETE", "REPLACE"}
        assert (
            client.post(
                "/api/historical-reconstruction/preview", json={**request, "rows": []}
            ).status_code
            == 422
        )
        assert client.post("/api/historical-reconstruction/apply", json=request).status_code == 404
        for invalid in ([1, 1], [-1], [999]):
            assert (
                client.post(
                    "/api/historical-reconstruction/preview",
                    json={**request, "account_ids": invalid},
                ).status_code
                == 422
            )
    event.remove(database.engine, "before_cursor_execute", record)


def test_legacy_v1_visible_but_no_endpoint_reinterpretation(database):
    with database.session_factory() as session:
        source = accept_source(session, fixture(quiet=True))
        row = session.get(MyBrokerImport, source["import_id"])
        document = json.loads(row.normalized_json)
        document["parser"] = row.parser_version = "mybroker-s1-v1"
        for key in ("rub_money", "endpoint_basis", "endpoint_blockers", "endpoint_conflicts"):
            document.pop(key)
        row.normalized_json = canonical(document)
        session.commit()
        report = inventory(session)
        assert "legacy_endpoint_evidence_unavailable" in endpoint(report, "ending")["blockers"]
        assert endpoint(report, "ending")["observation_state"] == "unknown"


def test_invalid_service_selection_is_sanitized(database):
    with database.session_factory() as session:
        with pytest.raises(MyBrokerError, match="selection_invalid"):
            inventory(session, start=date(2030, 3, 31), end=date(2030, 1, 1))
