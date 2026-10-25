"""Synthetic disposable source-first broker-month runtime; never a real profile."""

import hashlib
import json
import os
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET

import httpx2
import uvicorn
from fastapi import Response
from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.broker_identity_mappings import confirm_mapping
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.reporting_months import create_reporting_month
from sqlalchemy import select


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "backend" / "tests"))
    from test_statement_import_mybroker_endpoints import (
        broker_month_alias_xml,
        broker_month_xml,
        draft_structure_xml,
        money_batch_xml,
        money_coupon_pdf,
        stock_fee_xml,
        trade_money_xml,
    )

    with TemporaryDirectory(prefix="hermes-broker-month-synthetic-") as temporary:
        database = create_database(Path(temporary) / "finance.db")
        Base.metadata.create_all(database.engine)
        with database.session_factory() as session:
            create_account(session, name="Synthetic broker", account_type="brokerage")
            create_account(session, name="Unrelated synthetic deposit", account_type="deposit")
            create_account(session, name="Synthetic structural broker", account_type="brokerage")
            create_instrument(
                session,
                name="Synthetic stock",
                instrument_type="stock",
                isin="RU000A000000",
                currency="RUB",
            )
            create_instrument(
                session,
                name="Synthetic bond",
                instrument_type="bond",
                isin="RU000A000001",
                currency="RUB",
            )
            for number, end in (
                (1, 31),
                (2, 28),
                (3, 31),
                (4, 30),
                (5, 31),
                (6, 30),
            ):
                create_reporting_month(
                    session,
                    year=2030,
                    month=number,
                    snapshot_date=date(2030, number, end),
                )
        from statement_return_seed import seed_statement_return

        with database.session_factory() as session:
            known = create_account(
                session, name="Synthetic original-first broker", account_type="iis"
            )
            for alias in ("8480000", "848-ROW-A", "848-ROW-B"):
                confirm_mapping(
                    session,
                    provider="alfa_mybroker",
                    subject_kind="account",
                    provider_identity=alias,
                    hermes_target_id=known.id,
                )
            for number, end in ((8, 31), (9, 30), (10, 31)):
                create_reporting_month(
                    session,
                    year=2030,
                    month=number,
                    snapshot_date=date(2030, number, end),
                )
            for isin, kind in (("RU000A000848", "stock"), ("RU000A000849", "bond")):
                create_instrument(
                    session,
                    name=f"Synthetic original-first {kind}",
                    instrument_type=kind,
                    isin=isin,
                    currency="RUB",
                )
        # One isolated #886 original; public metadata is fixture-only transport.
        inbox_root = ET.fromstring(broker_month_xml(bond=True, unsupported=True))
        stock = inbox_root.find(".//{MyBroker}Details[@ISIN1='RU000A000000']")
        inbox_rows = inbox_root.find(".//{MyBroker}Details_Collection")
        with database.session_factory() as session:
            inbox_account = create_account(
                session, name="Synthetic identity inbox", account_type="brokerage"
            )
            create_reporting_month(session, year=2031, month=1, snapshot_date=date(2031, 1, 31))
            for alias in ("8860000", "886-ROW"):
                confirm_mapping(
                    session,
                    provider="alfa_mybroker",
                    subject_kind="account",
                    provider_identity=alias,
                    hermes_target_id=inbox_account.id,
                )
            for index in range(12):
                isin = f"RU000A{8800 + index:06d}"
                create_instrument(
                    session,
                    name=f"Synthetic inbox stock {index}",
                    instrument_type="stock",
                    isin=isin,
                    currency="RUB",
                )
                if index:
                    row = deepcopy(stock)
                    row.set("ISIN1", isin)
                    row.set("active_name", f"Synthetic inbox stock {index}")
                    inbox_rows.append(row)
            create_instrument(
                session,
                name="Synthetic inbox pending bond",
                instrument_type="bond",
                isin=None,
                currency="RUB",
            )
        for row in inbox_root.iter():
            if "active_name" in row.attrib and row.get("ISIN1") == "RU000A000001":
                row.set("active_name", "Synthetic inbox pending bond")
        inbox_xml = (
            ET.tostring(inbox_root, encoding="utf-8")
            .replace(b"2030", b"2031")
            .replace(b"1234567-000", b"886-ROW")
            .replace(b"RU000A000000", b"RU000A008800")
            .replace(b"RU000A000001", b"RU000A008813")
            .replace(b"10000000001", b"10000000886")
            .replace(b"2000000001", b"2000000886")
        )
        from hermes_finance.services import public_security_registry as registry

        actual_lookup = registry.lookup_public

        def public_transport(request):
            if request.url.path.endswith("/securities.json"):
                data = (
                    [["SYNTH886", "RU000A008813", "stock_bonds", "corporate_bond", 1]]
                    if request.url.params.get("start") == "0"
                    else []
                )
                return httpx2.Response(
                    200,
                    json={
                        "securities": {
                            "columns": ["secid", "isin", "group", "type", "is_traded"],
                            "data": data,
                        }
                    },
                )
            fields = {
                "SECID": "SYNTH886",
                "ISIN": "RU000A008813",
                "GROUP": "stock_bonds",
                "TYPE": "corporate_bond",
                "FACEUNIT": "RUB",
                "NAME": "Synthetic official inbox bond",
            }
            return httpx2.Response(
                200,
                json={
                    "description": {
                        "columns": ["name", "value"],
                        "data": list(fields.items()),
                    }
                },
            )

        def mocked_lookup(isins, *, consent):
            with httpx2.Client(transport=httpx2.MockTransport(public_transport)) as client:
                return actual_lookup(isins, consent=consent, client=client)

        registry.lookup_public = mocked_lookup
        with database.session_factory() as session:
            for alias, kind in (("7114001", "brokerage"), ("7114002", "iis")):
                account = create_account(
                    session, name=f"Workspace synthetic {alias}", account_type=kind
                )
                for identity in (alias, alias + "-000"):
                    confirm_mapping(
                        session,
                        provider="alfa_mybroker",
                        subject_kind="account",
                        provider_identity=identity,
                        hermes_target_id=account.id,
                    )

        # Build the accepted return proof after all catalogue/account dependencies.
        seed_statement_return(database)
        app = create_app(database, static_dir=root / "frontend" / "dist")

        # All payout I/O in this disposable fixture stays in process.
        from hermes_finance.market_data.payout_protocol import PayoutFetchResult
        from hermes_finance.persistence import Instrument
        from t_invest_mapping_fixtures import accept_t_invest_mapping

        with database.session_factory() as session:
            for instrument in session.scalars(
                select(Instrument).where(Instrument.isin.in_(["RU000A000000", "RU000A000001"]))
            ):
                accept_t_invest_mapping(
                    session,
                    instrument.id,
                    f"71100000-0000-0000-0000-{instrument.id:012d}",
                    isin=instrument.isin,
                )

        class LocalPayoutProvider:
            def fetch_payouts(self, request):
                return PayoutFetchResult(
                    provider="t_invest",
                    instrument_uid=request.instrument_uid,
                    events=(),
                )

        app.state.payout_provider = LocalPayoutProvider()

        @app.get("/api/synthetic-broker-source/{kind}")
        def source(kind: str):
            if kind in {"workspace-october-a", "workspace-october-b"}:
                alias = b"7114001" if kind.endswith("a") else b"7114002"
                raw = (
                    broker_month_xml(bond=True, unsupported=False)
                    .replace(b"1234567", alias)
                    .replace(b"31.12.2029", b"30.09.2040")
                    .replace(b".01.2030", b".10.2040")
                    .replace(b"2030-01-", b"2040-10-")
                )
                return Response(raw, media_type="application/xml")
            if kind in {"month-entry-a", "month-entry-b"}:
                from test_statement_import_broker_statement_provisional import (
                    provisional_xml,
                )

                tree = ET.fromstring(provisional_xml(candidate_count=0))
                position = tree.find(".//{MyBroker}Details[@ISIN1]")
                position.set("real_rest", "10" if kind.endswith("a") else "25")
                position.set("forward_rest", position.get("real_rest"))
                bond = deepcopy(position)
                bond.attrib.update(
                    ISIN1="RU000A000001",
                    active_name="Synthetic entry bond",
                    active_type="Облигации",
                    real_rest="2",
                    forward_rest="2",
                    nominal="1000",
                )
                tree.find(".//{MyBroker}Details_Collection").append(bond)
                trade_collection = tree.find(".//{MyBroker}Trades//{MyBroker}Details_Collection")
                for row in list(trade_collection):
                    trade_collection.remove(row)
                alias = b"7113501" if kind.endswith("a") else b"7113502"
                raw = (
                    ET.tostring(tree, encoding="utf-8")
                    .replace(b"1234567", alias)
                    .replace(b"2030-04-", b"2035-09-")
                    .replace(b".04.2030", b".09.2035")
                )
                return Response(raw, media_type="application/xml")
            if kind in {"month-ui-a", "month-ui-b"}:
                from bond_source_fixture import original

                raw, _ = original("7654321" if kind == "month-ui-a" else "8765432")
                raw = raw.replace(b"2030", b"2034")
                if kind == "month-ui-b":
                    tree = ET.fromstring(raw)
                    position = tree.find(".//{MyBroker}Details[@ISIN1]")
                    unknown = deepcopy(position)
                    unknown.set("ISIN1", "RU000MONTH01")
                    unknown.set("active_name", "Synthetic unknown month bond")
                    tree.find(".//{MyBroker}Details_Collection").append(unknown)
                    raw = ET.tostring(tree, encoding="utf-8")
                return Response(raw, media_type="application/xml")
            if kind == "source-inbox":
                return Response(inbox_xml, media_type="application/xml")
            if kind in {"original-first", "session"}:
                xml = (
                    broker_month_alias_xml(bond=True, unsupported=True)
                    .replace(b".01.2030", b".08.2030")
                    .replace(b"2030-01-", b"2030-08-")
                    .replace(b"10000000001", b"10000000848")
                    .replace(b"2000000001", b"2000000848")
                    .replace(b"1234567", b"8480000")
                    .replace(b"ROW-A", b"848-ROW-A")
                    .replace(b"ROW-B", b"848-ROW-B")
                    .replace(b"RU000A000000", b"RU000A000848")
                    .replace(b"RU000A000001", b"RU000A000849")
                )
                if kind == "session":
                    xml = (
                        xml.replace(b".08.2030", b".10.2030")
                        .replace(b"2030-08-", b"2030-10-")
                        .replace(b"10000000848", b"10000000854")
                        .replace(b"2000000848", b"2000000854")
                    )
                return Response(xml, media_type="application/xml")
            if kind == "structure":
                xml = (
                    draft_structure_xml(bond=True)
                    .replace(b".01.2030", b".06.2030")
                    .replace(b"2030-01-", b"2030-06-")
                    .replace(b"10000000001", b"10000000006")
                    .replace(b"2000000001", b"2000000006")
                    .replace(b"1234567-000", b"STRUCTURE-ROW")
                )
                return Response(xml, media_type="application/xml")
            if kind == "stock-fee":
                xml = (
                    stock_fee_xml(prior_month_buy=True)
                    .replace(b"31.12.2029", b"30.04.2030")
                    .replace(b".01.2030", b".05.2030")
                    .replace(b"2030-01-", b"2030-05-")
                    .replace(b".01.30", b".05.30")
                    .replace(b"10000000001", b"10000000005")
                    .replace(b"2000000001", b"2000000005")
                )
                return Response(xml, media_type="application/xml")
            if kind == "trade-money":
                xml = (
                    trade_money_xml(prior_month_buy=True, native_linkage=True)
                    .replace(b"31.12.2029", b"31.03.2030")
                    .replace(b".01.2030", b".04.2030")
                    .replace(b"2030-01-", b"2030-04-")
                    .replace(b".01.30", b".04.30")
                    .replace(b"10000000001", b"10000000004")
                    .replace(b"2000000001", b"2000000004")
                )
                return Response(xml, media_type="application/xml")
            if kind == "money-pdf":
                return Response(money_coupon_pdf(month=3), media_type="application/pdf")
            if kind == "money":
                xml = (
                    money_batch_xml(nkd=True)
                    .replace(b".01.2030", b".03.2030")
                    .replace(b"2030-01-", b"2030-03-")
                    .replace(b".01.30", b".03.30")
                )
                return Response(xml, media_type="application/xml")
            xml = broker_month_alias_xml(bond=True, unsupported=kind == "partial")
            if kind == "partial":
                xml = (
                    xml.replace(b".01.2030", b".02.2030")
                    .replace(b"2030-01-", b"2030-02-")
                    .replace(b"10000000001", b"10000000002")
                    .replace(b"2000000001", b"2000000002")
                )
            return Response(xml, media_type="application/xml")

        # Test-only XML endpoint must precede the app's SPA catch-all.
        app.router.routes.insert(0, app.router.routes.pop())

        @app.get("/api/synthetic-broker-inventory")
        def inventory():
            # Every persisted table, including identities, source and audit rows.
            with database.engine.connect() as connection:
                rows = {
                    table.name: sorted(
                        [list(map(str, row)) for row in connection.execute(select(table))]
                    )
                    for table in Base.metadata.sorted_tables
                }
            return {
                "counts": {name: len(items) for name, items in rows.items()},
                "digest": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
                "table_digests": {
                    name: hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
                    for name, items in rows.items()
                },
            }

        app.router.routes.insert(0, app.router.routes.pop())
        from hermes_finance.services.database_admission import database_admission

        with database_admission(database.database_path):
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=int(os.environ.get("HERMES_BROKER_MONTH_TEST_PORT", "18773")),
                access_log=False,
            )
        database.engine.dispose()


if __name__ == "__main__":
    main()
