"""Bounded Alfa investment-PDF evidence adapter for the existing source Preview.

No import/Apply, ledger, inferred tax or forecast cash. Text is request-local.
"""

import re
from dataclasses import dataclass
from datetime import date

from hermes_finance.statement_import.dto import ExtractedDocument, ExtractStatus
from hermes_finance.statement_import.money import kopecks, parse_decimal
from hermes_finance.statement_import.mybroker import MyBrokerError


@dataclass(frozen=True)
class InvestmentPayout:
    account: str
    isin: str
    kind: str
    date: date
    currency: str
    net_kopecks: int
    reference: str


@dataclass(frozen=True)
class InvestmentReport:
    sha256: str
    start: date
    end: date
    payouts: tuple[InvestmentPayout, ...]
    closing: dict[str, int]
    reported_pnl: dict[str, int]
    positions: dict[tuple[str, str], tuple[str, int]]
    closed_isins: frozenset[tuple[str, str]]
    payout_accounts: frozenset[str]
    issues: tuple[tuple[str, str], ...]
    instrument_issues: tuple[tuple[str, str, str], ...] = ()


def _day(value):
    return date.fromisoformat("-".join(reversed(value.split("."))))


def _minor(value):
    value = value.replace("\xa0", " ").replace("\u202f", " ").strip()
    if re.fullmatch(r"\+[0-9][0-9 .,]*", value):
        value = value[1:]
    parsed = parse_decimal(value)
    if parsed is None or not hasattr(parsed, "is_finite") or not parsed.is_finite():
        raise ValueError("invalid PDF money")
    scaled = parsed * 100
    if scaled != scaled.to_integral_value() or abs(scaled) > 2**63 - 1:
        raise ValueError("invalid PDF precision")
    return kopecks(parsed)


def parse_investment_report(extracted: ExtractedDocument, accounts: set[str]) -> InvestmentReport:
    """Only explicit account/date/ISIN/net cells in actual Денежный поток tables.

    Foreign accounts are excluded before interpreting their financial cells.
    Future-flow tables and broker's simple headline percentage are never cash.
    """
    if extracted.status != ExtractStatus.OK:
        raise MyBrokerError("investment_pdf_" + str(extracted.status))
    cover = " ".join(" ".join(extracted.pages[0].lines).split()) if extracted.pages else ""
    period = re.search(r"Период [cс] (\d{2}\.\d{2}\.\d{4}) по (\d{2}\.\d{2}\.\d{4})", cover)
    if not cover.startswith("Инвестиционный отчёт ") or period is None:
        raise MyBrokerError("investment_pdf_family_unsupported")
    try:
        start, end = _day(period[1]), _day(period[2])
        if start > end:
            raise ValueError
    except ValueError:
        raise MyBrokerError("investment_pdf_period_invalid") from None
    payouts, closing, pnl, positions, closed, seen, issues = [], {}, {}, {}, set(), set(), []
    instrument_issues = []
    position_dates = set()
    account, section, kind, header = None, None, None, False
    isin_pattern = r"[A-Z]{2}[A-Z0-9]{9}[0-9]"
    for page_number, page in enumerate(extracted.pages, 1):
        lines = page.lines
        for line_number, original in enumerate(lines):
            line = original.replace("\xa0", " ").replace("\u202f", " ").strip()
            folded = " ".join(line.split())
            title = re.fullmatch(
                r"Счёт ([0-9]{1,32})(?: на (\d{2}\.\d{2}\.\d{4})(?: В долларах.*)?| за период с (\d{2}\.\d{2}\.\d{4}) по (\d{2}\.\d{2}\.\d{4}))",
                folded,
            )
            if title:
                if title[1] != account:
                    section, kind, header = None, None, False
                account = title[1]
                if account in accounts and title[3]:
                    try:
                        if (_day(title[3]), _day(title[4])) != (start, end):
                            raise ValueError
                    except ValueError:
                        issues.append((account, "pdf_account_period_invalid"))
                if account in accounts and title[2]:
                    try:
                        if _day(title[2]) != end:
                            raise ValueError
                        capital = lines[line_number + 1].replace("\xa0", " ")
                        gain = next(x for x in lines[line_number + 2 : line_number + 6] if "₽" in x)
                        v = _minor(capital.split("₽")[0])
                        g = _minor(gain.split("₽")[0])
                        if account in closing and (closing[account], pnl[account]) != (v, g):
                            raise ValueError
                        closing[account], pnl[account] = v, g
                    except (ValueError, StopIteration, IndexError):
                        issues.append((account, "pdf_account_summary_invalid"))
                continue
            if folded.startswith("Счёт "):
                # An unsupported next-account heading must never inherit the
                # previous account's section and accidentally consume its rows.
                account, section, kind, header = None, None, None, False
                continue
            if account not in accounts:
                continue
            if folded in {
                "Денежный поток",
                "Оценка портфеля",
                "Закрытые сделки",
                "Будущий денежный поток",
                "Движение денег",
            }:
                section, kind, header = folded, None, False
                if section == "Денежный поток":
                    seen.add(account)
                continue
            if section == "Денежный поток":
                if all(
                    x in folded for x in ("Инструмент", "ISIN", "Дата выплаты", "Сумма в валюте")
                ):
                    header = True
                elif folded in {"Акции", "Облигации"}:
                    kind = "DIVIDEND" if folded == "Акции" else "COUPON"
                elif re.search(isin_pattern, line) or re.search(
                    r"\b[A-Z]{3}\s+\d{2}\.\d{2}\.\d{4}\s+", line
                ):
                    match = re.fullmatch(
                        rf".*?\b({isin_pattern})\s+([A-Z]{{3}})\s+(\d{{2}}\.\d{{2}}\.\d{{4}})\s+(.+)",
                        line,
                    )
                    try:
                        if (
                            not match
                            or not header
                            or kind is None
                            or len(set(re.findall(isin_pattern, line))) != 1
                        ):
                            raise ValueError
                        amount = _minor(re.split(r"\s{2,}", match[4])[-1])
                        day = _day(match[3])
                        if not start <= day <= end or amount <= 0:
                            raise ValueError
                        payouts.append(
                            InvestmentPayout(
                                account,
                                match[1],
                                kind,
                                day,
                                match[2],
                                amount,
                                f"{extracted.document_sha256}:p{page_number}:l{line_number}",
                            )
                        )
                    except ValueError:
                        identities = set(re.findall(isin_pattern, line))
                        if len(identities) == 1:
                            instrument_issues.append(
                                (account, next(iter(identities)), "pdf_payout_row_invalid")
                            )
                        else:
                            issues.append((account, "pdf_payout_row_invalid"))
            elif section == "Оценка портфеля":
                # The report also lists a typed RUB cash row, without an ISIN.
                # Recognize only its exact grammar; an unidentified security
                # row must still produce an account-wide issue.
                if line.startswith("Российский рубль "):
                    try:
                        cells = re.split(r"\s{2,}", line)
                        if (
                            len(cells) != 7
                            or cells[0] != "Российский рубль"
                            or not re.fullmatch(rf"{account}-[0-9]{{3}}", cells[1])
                            or cells[2] != "RUB"
                            or not re.fullmatch(r"[-+]?[0-9]+(?:[.,][0-9]+)?%", cells[6])
                        ):
                            raise ValueError
                        for value in cells[3:6]:
                            _minor(value)
                    except ValueError:
                        issues.append((account, "pdf_position_invalid"))
                    continue
                as_of = re.fullmatch(r"на (\d{2}\.\d{2}\.\d{4})", folded)
                if as_of:
                    try:
                        if _day(as_of[1]) != end:
                            raise ValueError
                        position_dates.add(account)
                    except ValueError:
                        issues.append((account, "pdf_position_date_invalid"))
                match = re.fullmatch(
                    rf".*?\b({isin_pattern})\s+({account}-[0-9]{{3}})\s+.+?\s+([A-Z]{{3}})\s+(.+)",
                    line,
                )
                if match:
                    try:
                        if len(set(re.findall(isin_pattern, line))) != 1:
                            raise ValueError
                        cells = re.split(r"\s{2,}", match[4])
                        quantity = parse_decimal(cells[0])
                        value = _minor(cells[4])
                        if not hasattr(quantity, "is_finite") or not quantity.is_finite():
                            raise ValueError
                        key, observation = (account, match[1]), (str(quantity), value)
                        if key in positions:
                            raise ValueError
                        positions[key] = observation
                    except (ValueError, IndexError):
                        if len(set(re.findall(isin_pattern, line))) == 1:
                            instrument_issues.append((account, match[1], "pdf_position_invalid"))
                        else:
                            issues.append((account, "pdf_position_invalid"))
                elif re.search(isin_pattern, line) or re.search(rf"\b{account}-[0-9]{{3}}\b", line):
                    identities = set(re.findall(isin_pattern, line))
                    if len(identities) == 1:
                        instrument_issues.append(
                            (account, next(iter(identities)), "pdf_position_invalid")
                        )
                    else:
                        issues.append((account, "pdf_position_invalid"))
            elif section == "Закрытые сделки":
                match = re.search(rf"\b({isin_pattern})\s+{account}-[0-9]{{3}}\b", line)
                if match:
                    closed.add((account, match[1]))
            if len(payouts) > 2000:
                raise MyBrokerError("investment_pdf_row_limit")
    return InvestmentReport(
        extracted.document_sha256,
        start,
        end,
        tuple(payouts),
        closing,
        pnl,
        positions,
        frozenset(closed),
        frozenset(seen),
        tuple(
            sorted(
                set(issues)
                | {
                    (a, "pdf_position_date_missing")
                    for a, _ in positions
                    if a not in position_dates
                }
            )
        ),
        tuple(sorted(set(instrument_issues))),
    )
