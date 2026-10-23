"""Generate fabricated MyBroker cases; never reads an external data directory."""

import json
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

from test_statement_import_broker_statement_provisional import _add_money, provisional_xml

from hermes_finance.statement_import.mybroker import NS

ROOT = Path(__file__).resolve().parents[2] / "tests/fixtures/astra_hunt"
FILENAME = "Брокерский 1234567 (01.04.30-30.04.30).xml"


def generate():
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = []

    def base():
        root = ET.fromstring(provisional_xml(closing="9900", candidate_count=0))
        root.find("m:Trades/m:Report", NS).clear()
        root.find("m:Trades/m:Report", NS).set("Name", "2_Trades")
        root.set("synthetic_only", "astra-hunt-generated-no-owner-data")
        return root

    def save(case, root, description, filename=FILENAME):
        root.set("synthetic_case", case)
        ET.indent(root)
        path = ROOT / f"{case}.xml"
        path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))
        manifest.append(dict(case=case, filename=filename, description=description))

    def money(case, operation, amount, description, narrative="Synthetic event"):
        root = base()
        _add_money(root, operation, narrative, amount)
        save(case, root, description)
        return root

    save("01_control", base(), "Complete RUB statement, no flows: 9% period growth")
    money("02_unknown", "Космическая проводка", "1000", "Unknown operation must block")
    root = base()
    root.find(".//m:Details[@ISIN1]", NS).set("real_volume", "8000")
    _add_money(root, "Вывoд дивидендов", "Synthetic withdrawal; Latin o typo", "-1000")
    save("03_typo_withdrawal", root, "Misspelled withdrawal containing dividend keyword")
    root = base()
    root.find(".//m:Details[@ISIN1]", NS).set("real_volume", "8000")
    _add_money(root, "Внутренний перевод", "На другой счет 7654321-000", "-1000")
    save("04_account_transfer", root, "Outgoing transfer to another account; account return is 0%")
    root = base()
    _add_money(root, "Пополнение", "Synthetic USD funding", "10")
    root.find(".//m:p_code[@volume]", NS).set("p_code", "USD")
    root.find(".//m:p_code[@volume]", NS).set("exchange_rate", "90")
    save("05_usd_deposit", root, "USD deposit without accepted dated RUB conversion")
    root = base()
    _add_money(root, "Конвертация валюты", "Synthetic FX USD/RUB rate=0", "-900")
    rn = _add_money(root, "Конвертация валюты", "Synthetic FX USD/RUB rate=0", "10")
    rn.find(".//m:p_code[@volume]", NS).set("p_code", "USD")
    rn.find(".//m:p_code[@volume]", NS).set("exchange_rate", "0")
    save("06_fx_zero_rate", root, "Two FX legs, unusable zero exchange rate")
    root = base()
    report = root.find("m:Trades2/m:Report", NS)
    report.clear()
    report.set("Name", "3_BrokerMoneyMove")
    save("07_empty_money", root, "Explicitly present empty Money section")
    root = base()
    root.remove(root.find("m:Trades2", NS))
    save("08_missing_money", root, "Absent required Money section")
    root = base()
    report = root.find("m:Positions/m:Report", NS)
    report.clear()
    report.set("Name", "1_Positions")
    save("09_empty_positions", root, "Empty positions and cash; no valuation evidence")
    root = base()
    rn = _add_money(root, "Пополнение", "Synthetic identical occurrence", "100")
    root.find(".//m:rn_Collection", NS).append(deepcopy(rn))
    save(
        "10_duplicate_money", root, "Two identical Money occurrences; preserve native multiplicity"
    )
    root = base()
    root.find(".//m:Details_Collection", NS).append(deepcopy(root.find(".//m:Details[@ISIN1]", NS)))
    save("11_duplicate_position", root, "Duplicate same-account same-ISIN endpoint row")
    save(
        "12_partial_month",
        base(),
        "Starts on April 10, no calendar opening EOD",
        "Брокерский 1234567 (10.04.30-30.04.30).xml",
    )
    money("13_negative_deposit", "Пополнение", "-100", "Deposit sign contradicts operation")
    money("14_zero_deposit", "Пополнение", "0", "Zero external deposit is invalid")
    money("15_negative_withdrawal", "Вывод", "-100", "Valid signed withdrawal")
    money("16_zero_fee", "Комиссия", "0", "Known zero fee must remain zero")
    for case, qty, amount in (("17_nkd_buy", "2", "-5"), ("18_nkd_sell", "-2", "5")):
        root = base()
        original = ET.fromstring(provisional_xml(candidate_count=0))
        trade = deepcopy(original.find(".//m:Details[@trade_no]", NS))
        trade.attrib.update(
            qty=qty,
            Price="10",
            summ_trade="200",
            summ_nkd="5",
            nominal="1000",
            active_type="Облигации",
            p_name="Synthetic bond",
        )
        table = ET.SubElement(root.find("m:Trades/m:Report", NS), "{MyBroker}Tablix2")
        ET.SubElement(table, "{MyBroker}Details_Collection").append(trade)
        security = root.find(".//m:Details[@ISIN1]", NS)
        security.set("active_type", "Облигации")
        security.set("active_name", "Synthetic bond")
        security.set("nominal", "1000")
        security.set("income_rest", "8" if qty == "2" else "12")
        _add_money(
            root,
            "НКД по сделке 10000000001",
            "Synthetic accrued interest",
            amount,
            day="2030-04-17",
        )
        save(case, root, "Bond accrued interest on " + ("purchase" if qty == "2" else "sale"))
    root = base()
    security = root.find(".//m:Details[@ISIN1]", NS)
    security.set("active_type", "Облигации")
    security.set("nominal", "800")
    _add_money(root, "Частичное погашение номинала", "Synthetic principal redemption", "200")
    save("19_partial_redemption", root, "Partial principal redemption is not coupon income")
    root = base()
    security = root.find(".//m:Details[@ISIN1]", NS)
    security.set("ISIN1", "ZZ000UNKNOWN")
    security.set("active_type", "Synthetic unknown asset class")
    save("20_unknown_security", root, "Unknown instrument/class with explicit native RUB endpoints")
    root = base()
    _add_money(root, "Пополнение", "Synthetic out-of-range posting", "1000", day="2030-05-01")
    save("21_outside_period", root, "April statement contains a May cash event")
    root = base()
    rn = _add_money(root, "Комиссия", "Synthetic visible zero fee plus misplaced amount", "0")
    ET.SubElement(
        rn.find("m:oper_type/m:comment", NS), "{MyBroker}p_code", volume="1000", p_code="RUB"
    )
    save("22_hidden_amount", root, "Extra Money amount leaf outside the supported path")
    root = base()
    ET.SubElement(root.find("m:Trades2", NS), "{MyBroker}rn", volume="1000", p_code="RUB")
    save("23_hidden_wrapper", root, "Financial row beside Money Report in the known wrapper")
    root = base()
    ET.SubElement(
        root.find("m:Trades3/m:Report", NS),
        "{MyBroker}Transfer",
        amount="-1000",
        source="1234567-000",
        target="7654321-000",
    )
    save("24_transfer_section", root, "Opaque Transfers section must propagate a blocker")
    root = base()
    root.find(".//m:settlement_date", NS).set("settlement_date", "2030-06-15T00:00:00")
    save(
        "25_june_gap",
        root,
        "June statement; pair with 01 to leave May uncovered",
        "Брокерский 1234567 (01.06.30-30.06.30).xml",
    )
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    generate()
