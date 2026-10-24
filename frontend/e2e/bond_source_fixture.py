"""Synthetic two-account source bonds. Normal services seed; HTTP viewing is read-only."""

import hashlib
import os
import sys
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET

import uvicorn
from fastapi.responses import JSONResponse

ISIN = "RU000A000001"
REG = "4B02-01-00001-A-001P"
N = "{MyBroker}"


def original(account, *, trade=False, adverse=False, long=False):
    from test_source_monthly_returns_service import service_structure_xml
    from test_statement_import_broker_statement_provisional import provisional_xml

    month = "06" if adverse else "05"
    coupon = "70" if trade or adverse else "30"
    raw = provisional_xml(
        candidate_count=0,
        extra_money=(
            (
                "Перевод",
                f'погашение купона {REG} (облигации ПАО "Синтетика") д.ф.14.{month}.30',
                coupon,
            ),
        ),
    )
    root = ET.fromstring(raw)
    position = root.find(f".//{N}Details[@ISIN1]")
    position.attrib.update(
        ISIN1=ISIN,
        active_type="Облигации",
        active_name="Синтетическая облигация",
        income_rest="8" if adverse else "7" if trade else "2",
        real_rest="9" if adverse else "8" if trade else "2",
        forward_rest="9" if adverse else "8" if trade else "2",
        income_volume="8010" if adverse else "7000" if trade else "2000",
        real_volume="9000" if adverse else "8010" if trade else "2010",
    )
    collection = root.find(f"{N}Trades/{N}Report/{N}Tablix2/{N}Details_Collection")
    row = collection[0]
    if trade or adverse:
        row.attrib.update(
            isin_reg=ISIN,
            trade_no="10000000001\n2000000001" if trade else "10000000002\n2000000002",
            qty="1",
            Price="100",
            summ_trade="1000",
            summ_nkd="20",
            bank_tax="5",
            nominal="1000",
        )
        if adverse:
            row.attrib.pop("summ_nkd")
    else:
        collection.remove(row)
    root = ET.fromstring(service_structure_xml(ET.tostring(root)))
    root.find(
        f"{N}Positions/{N}Report/{N}Tablix3/{N}Details1_Collection/{N}Details1"
    ).set("fTOPAY", "1.00" if long else "0.00")
    for node in root.iter():
        for key, value in list(node.attrib.items()):
            if key.startswith("acc_code"):
                node.set(key, account + "-000")
            else:
                node.set(
                    key,
                    value.replace("2030-04-", f"2030-{month}-").replace(
                        ".04.2030", f".{month}.2030"
                    ),
                )
    filename = f"Брокерский {account} (01.{'04' if long else month}.30-{'30' if adverse else '31'}.{month}.30).xml"
    return ET.tostring(root, encoding="utf-8"), filename


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "backend/tests"))
    from hermes_finance.main import create_app
    from hermes_finance.market_data.dto import T_INVEST_PROVIDER
    from hermes_finance.market_data.payout import (
        PayoutEvent,
        PayoutEventKind,
        PayoutEventStatus,
    )
    from hermes_finance.market_data.payout_protocol import PayoutFetchResult
    from hermes_finance.services import security_reg_isin_mappings as crosswalk
    from hermes_finance.services.comments import create_monthly_comment
    from hermes_finance.services.instruments import create_instrument
    from hermes_finance.services.reporting_months import create_reporting_month
    from hermes_finance.services.source_intake import save_intake
    from t_invest_mapping_fixtures import accept_t_invest_mapping
    from test_source_monthly_returns_service import snapshot
    from test_statement_import_broker_statement_provisional import (
        _free_database,
        provisional_xml,
    )

    with TemporaryDirectory(prefix="hermes-bond-source-synthetic-") as temporary:
        database = _free_database(Path(temporary))
        with database.session_factory() as session:
            bond = create_instrument(
                session,
                name="Синтетическая облигация",
                instrument_type="bond",
                isin=ISIN,
            )
            crosswalk.set_mapping(session, REG, ISIN, "synthetic test bridge")
            accept_t_invest_mapping(
                session, bond.id, "44444444-4444-4444-4444-444444444444", isin=ISIN
            )
            stock = create_instrument(
                session,
                name="Синтетическая акция месяца",
                instrument_type="stock",
                isin="RU000MONTH02",
            )
            accept_t_invest_mapping(
                session,
                stock.id,
                "55555555-5555-5555-5555-555555555555",
                isin=stock.isin,
            )
            month = create_reporting_month(
                session, year=2030, month=5, snapshot_date=date(2030, 6, 1)
            )
            create_monthly_comment(
                session,
                reporting_month_id=month.id,
                text="Protected synthetic Month comment",
            )
        for i, (account, kwargs) in enumerate(
            [
                ("7654321", {}),
                ("8765432", {"trade": True}),
                ("8765432", {"trade": True, "long": True}),
                ("8765432", {"adverse": True}),
            ]
        ):
            raw, filename = original(account, **kwargs)
            with database.session_factory() as session:
                save_intake(
                    session, document=raw, filename=filename, request_id=f"bond-{i}"
                )
                save_intake(
                    session, document=raw, filename=filename, request_id=f"bond-{i}"
                )
        # Two separate source scopes for Month: a supported stock interval,
        # bond conditional/NULL results, and a later saved actual on account B.
        for account, later in (
            ("2222222", False),
            ("3333333", False),
            ("3333333", True),
        ):
            month_number = "06" if later else "05"
            extra = [
                (
                    "Перевод",
                    f'погашение купона {REG} (облигации ПАО "Синтетика") д.ф.14.{month_number}.30',
                    "30",
                )
            ]
            if later:
                extra.append(("Дивиденды", "RU000MONTH02", "12.34"))
            raw = provisional_xml(candidate_count=0, extra_money=tuple(extra))
            tree = ET.fromstring(raw)
            stock_row = tree.find(f".//{N}Details[@ISIN1]")
            stock_row.attrib.update(
                ISIN1="RU000MONTH02",
                active_type="Акции",
                active_name="Синтетическая акция месяца",
                income_rest="10" if account == "2222222" else "5",
                real_rest="10" if account == "2222222" else "5",
                forward_rest="10" if account == "2222222" else "5",
                income_volume="1100" if later else "1000",
                real_volume="1200" if later else "1100",
            )
            bond_row = deepcopy(stock_row)
            bond_row.attrib.update(
                ISIN1=ISIN,
                active_type="Облигации",
                active_name="Синтетическая облигация",
                income_rest="2",
                real_rest="2",
                forward_rest="2",
                income_volume="2010" if later else "2000",
                real_volume="2020" if later else "2010",
            )
            tree.find(f".//{N}Details_Collection").append(bond_row)
            trades = tree.find(f"{N}Trades/{N}Report/{N}Tablix2/{N}Details_Collection")
            for row in list(trades):
                trades.remove(row)
            for node in tree.iter():
                for key, value in list(node.attrib.items()):
                    if key.startswith("acc_code"):
                        node.set(key, account + "-000")
                    else:
                        node.set(
                            key,
                            value.replace("2030-04-", f"2030-{month_number}-").replace(
                                ".04.2030", f".{month_number}.2030"
                            ),
                        )
            filename = f"Брокерский {account} (01.{month_number}.30-{'30' if later else '31'}.{month_number}.30).xml"
            with database.session_factory() as session:
                save_intake(
                    session,
                    document=ET.tostring(tree, encoding="utf-8"),
                    filename=filename,
                    request_id=f"month-{account}-{later}",
                )
        with database.session_factory() as session:
            crosswalk.relink(session)
        app = create_app(database, static_dir=root / "frontend/dist")

        class SyntheticProvider:
            def __init__(self):
                self.requests = []

            def fetch_payouts(self, request):
                self.requests.append(request)
                kind = (
                    PayoutEventKind.DIVIDEND
                    if request.instrument_uid.startswith("5555")
                    else PayoutEventKind.COUPON
                )
                return PayoutFetchResult(
                    provider=T_INVEST_PROVIDER,
                    instrument_uid=request.instrument_uid,
                    events=tuple(
                        PayoutEvent(
                            provider=T_INVEST_PROVIDER,
                            instrument_uid=request.instrument_uid,
                            event_kind=kind,
                            identity_key=f"month-{kind.value}-{day}",
                            status=PayoutEventStatus.OK,
                            payment_date=day,
                            per_unit_amount=Decimal("2.50"),
                            currency="RUB",
                            source_method="synthetic-existing-provider",
                            provider_filter_basis="record_date",
                            provider_filter_date=day,
                        )
                        for day in (
                            date(2030, 5, 15),
                            date(2030, 6, 15),
                            date(2030, 7, 15),
                        )
                    ),
                )

        provider = SyntheticProvider()
        app.state.payout_provider = provider

        @app.middleware("http")
        async def read_only(request, call_next):
            if request.method not in {"GET", "HEAD"} and not (
                request.method == "POST"
                and request.url.path == "/api/source-returns/payout-preview"
            ):
                return JSONResponse(
                    {"detail": "synthetic reader is read-only"}, status_code=405
                )
            return await call_next(request)

        def state():
            return {
                "snapshot_sha256": hashlib.sha256(
                    repr(snapshot(database)).encode()
                ).hexdigest()
            }

        app.add_api_route("/api/synthetic-bond-state", state, methods=["GET"])
        app.router.routes.insert(0, app.router.routes.pop())

        def month_state():
            return {
                **state(),
                "provider_requests": [
                    {
                        "uid": item.instrument_uid,
                        "from": item.calendar_from,
                        "to": item.calendar_to,
                    }
                    for item in provider.requests
                ],
            }

        app.add_api_route("/api/synthetic-month-state", month_state, methods=["GET"])
        app.router.routes.insert(0, app.router.routes.pop())
        try:
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=int(os.environ.get("HERMES_BOND_TEST_PORT", "18791")),
                access_log=False,
            )
        finally:
            database.engine.dispose()


if __name__ == "__main__":
    main()
