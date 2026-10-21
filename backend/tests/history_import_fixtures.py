"""Fabricated long/overlapping MyBroker originals; never load external statements."""

from copy import deepcopy
from datetime import date
from hashlib import sha256
from xml.etree import ElementTree as ET

from test_statement_import_broker_statement_provisional import _add_money, provisional_xml
from test_statement_import_mybroker import ACCOUNT, ISIN, node

from hermes_finance.statement_import.mybroker import NS

BOND = "RU000A000001"
ACCOUNTS = (ACCOUNT, "2345678-000", "3456789-000", "4567890-000")
LONG_START = date(2024, 3, 25)
LONG_END = date(2026, 10, 5)


def history_trade(day, token, *, isin=ISIN, qty="1", price="100", amount="100", nkd=None, repo=""):
    return {
        "trade_no": f"100000{token}\n200000{token}",
        "db_time": f"{day:%d.%m.%Y} 09:00:00\n{day:%d.%m.%Y} 09:00:00",
        "save_settlement_date": f"{day:%d.%m.%Y}",
        "save_depo_settlement_date": f"{day:%d.%m.%Y}",
        "settlement_time": f"{day:%d.%m.%Y} 10:00:00",
        "isin_reg": isin,
        "qty": qty,
        "Price": price,
        "summ_trade": amount,
        "curr_calc": "RUB",
        "bank_tax": "1",
        **({"summ_nkd": nkd} if nkd is not None else {}),
        **({"repo_no": repo} if repo else {}),
    }


def history_xml(
    *,
    account=ACCOUNT,
    start=LONG_START,
    end=LONG_END,
    trades=(),
    money=(),
    empty=False,
    native_structure=False,
):
    """Reuse the native fixture builders; period exists exclusively in the filename.

    native_structure adds opaque operation summaries/connection metadata. Tests
    retain their existing source gaps rather than granting these trees authority.
    """
    root = ET.fromstring(provisional_xml(candidate_count=0))
    root.set("Textbox6", "Уполномоченное лицо")
    root.set("synthetic_original", sha256(f"{account}/{start}/{end}".encode()).hexdigest())
    positions = root.find(
        "m:Positions/m:Report/m:Tablix1/m:active_type_Collection/"
        "m:active_type/m:Details_Collection",
        NS,
    )
    stock = positions.find("m:Details[@ISIN1]", NS)
    stock.attrib.update(
        active_name="Synthetic stock",
        active_type="Акции",
        income_rest="10",
        real_rest="11",
        forward_rest="11",
        income_volume="1000",
        real_volume="1200",
    )
    bond = deepcopy(stock)
    bond.attrib.update(
        ISIN1=BOND,
        active_name="Synthetic bond",
        active_type="Облигации",
        income_rest="2",
        real_rest="3",
        forward_rest="3",
        income_volume="2000",
        real_volume="3150",
    )
    positions.append(bond)
    collection = root.find("m:Trades/m:Report/m:Tablix2/m:Details_Collection", NS)
    collection[:] = []
    for attrs in trades:
        node(collection, "Details", **attrs)
    movements = root.find("m:Trades2/m:Report", NS)
    movements[:] = []
    for day, operation, narrative, amount in money:
        _add_money(root, operation, narrative, amount, day=day.isoformat())
    if empty:
        positions[:] = []
        collection[:] = []
        movements[:] = []
    for row in root.iter():
        if "acc_code" in row.attrib or "trade_no" in row.attrib:
            row.set("acc_code", account)
    if native_structure:
        node(root.find("m:Trades3/m:Report", NS), "Tablix1")
        table = node(root.find("m:Trades4/m:Report", NS), "Tablix1", Textbox4="Подключен")
        node(
            node(table, "Details_Collection"),
            "Details",
            sys_start_time="25.03.2024 09:00",
            sys_end_time="-",
        )
        if not empty:
            summary = node(node(movements, "Tablix7"), "oper_group_Collection")
            for label in ("Внесено по распоряжению Клиента", "Списано по тарифам Банка", "НДФЛ"):
                group = node(summary, "oper_group", oper_group=label)
                node(node(group, "p_code6_Collection"), "p_code6", p_code6="RUB", volume6="0")
    filename = f"Брокерский {account.split('-')[0]} ({start:%d.%m.%y}-{end:%d.%m.%y}).xml"
    return filename, ET.tostring(root, encoding="utf-8")
