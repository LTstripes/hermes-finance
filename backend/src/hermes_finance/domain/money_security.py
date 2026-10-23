"""Strict MyBroker payout narrative identities; no amount or classification policy."""

import re
from datetime import datetime
from typing import Literal, NamedTuple

InstrumentLinkStatus = Literal[
    "linked",
    "unresolved_no_match",
    "unresolved_ambiguous",
    "not_parsed",
    "kind_mismatch",
    "not_applicable",
]


class MoneySecurity(NamedTuple):
    reg_number: str
    issuer_name: str
    kind: Literal["coupon", "dividend"]


# Deliberately bounded registration grammars, not arbitrary parenthesized tokens.
_REG = r"(?a:(?:(?:[0-9][A-Z][0-9]{2}|[0-9])-[0-9]{2}-[0-9]{5}-[A-Z](?:-[0-9]{3}[A-Z])?|[0-9]{8}[A-Z]))"
_ISSUER = r'(?:ПАО|АО|ООО) (?:"[^"()\r\n]+"|«[^«»()\r\n]+»|[^"«»()\r\n]+)'
_COUPON = re.compile(
    rf"погашение купона (?P<reg>{_REG}) \(облигации (?P<issuer>{_ISSUER})\) "
    r"д\.ф\.(?P<date>[0-9]{2}\.[0-9]{2}\.[0-9]{2})",
    re.IGNORECASE,
)
_DIVIDEND = re.compile(
    rf"Дивиденды за [0-9]{{4}} г\. по акциям (?P<issuer>{_ISSUER}) \((?P<reg>{_REG})\)\."
    r" \(Удержан налог [0-9]+(?:[.,][0-9]{1,2})? руб\.\)\."
    r"(?: Эмитентом уменьшена НОБ)?",
    re.IGNORECASE,
)


def parse_money_security(narrative: str) -> MoneySecurity | None:
    """Extract only the complete supported shapes. Refunds/extra text fail closed.

    Amount/sign and effective classification are checked by the caller, so a
    syntactically identical negative row yields the same textual identity here.
    """
    if "\r" in narrative or "\n" in narrative:
        return None
    for pattern, kind in ((_COUPON, "coupon"), (_DIVIDEND, "dividend")):
        match = pattern.fullmatch(narrative)
        if match is None:
            continue
        if kind == "coupon":
            try:
                datetime.strptime(match["date"], "%d.%m.%y")
            except ValueError:
                return None
        issuer = match["issuer"].strip()
        # Legal-form prefixes and empty quotes are not an issuer name.
        name = re.sub(r"^(?:ПАО|АО|ООО)\s*", "", issuer, flags=re.IGNORECASE)
        if not name.strip('"«»').strip():
            return None
        return MoneySecurity(match["reg"].upper(), issuer, kind)
    return None
