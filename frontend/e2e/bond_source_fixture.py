"""Synthetic two-account source bonds. Normal services seed; HTTP viewing is read-only."""

import hashlib
import os
import sys
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
    from hermes_finance.services import security_reg_isin_mappings as crosswalk
    from hermes_finance.services.instruments import create_instrument
    from hermes_finance.services.source_intake import save_intake
    from test_source_monthly_returns_service import snapshot
    from test_statement_import_broker_statement_provisional import _free_database

    with TemporaryDirectory(prefix="hermes-bond-source-synthetic-") as temporary:
        database = _free_database(Path(temporary))
        with database.session_factory() as session:
            create_instrument(
                session,
                name="Синтетическая облигация",
                instrument_type="bond",
                isin=ISIN,
            )
            crosswalk.set_mapping(session, REG, ISIN, "synthetic test bridge")
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
        with database.session_factory() as session:
            crosswalk.relink(session)
        app = create_app(database, static_dir=root / "frontend/dist")

        @app.middleware("http")
        async def read_only(request, call_next):
            if request.method not in {"GET", "HEAD"}:
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
