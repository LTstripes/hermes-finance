"""Complete investment-report Money narrative variants; identity, never cash.

Separate source grammar from the existing accepted depository Apply grammar.
Registration is corroborated against the entire PDF payout group by the caller.
"""

import re
from datetime import datetime

from hermes_finance.domain.money_security import MoneySecurity, parse_money_security

_REG = (
    r"(?a:(?:[0-9][A-Z][0-9]{2}|[0-9])-[0-9]{2,3}-[0-9]{5}-[A-Z](?:-[0-9]{3}[A-Z])?|[0-9]{8}[A-Z])"
)
_ISSUER = r'(?:МКПАО|ПАО|АО|ОАО) (?:МКК )?(?:"[^"()\r\n]+"|[^"()\r\n]+)'
_COUPON = re.compile(
    rf"погашение купона (?P<reg>{_REG}) \((?:Биржевые )?облигации (?P<issuer>{_ISSUER})\) д\.ф\.(?P<date>[0-9]{{2}}\.[0-9]{{2}}\.[0-9]{{2}})",
    re.IGNORECASE,
)
_DIVIDEND = re.compile(
    rf"Дивиденды за (?:[1-4] кв |[1-9] месяцев )?[0-9]{{4}} г\. по акциям (?P<issuer>{_ISSUER}) \((?P<reg>{_REG})\)\. \(Удержан налог [0-9]+(?:[.,][0-9]{{1,2}})? руб\.\)",
    re.IGNORECASE,
)


def parse_investment_money_security(narrative: str) -> MoneySecurity | None:
    original = parse_money_security(narrative)
    if original is not None:
        return original
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
        if not re.sub(r"^(?:МКПАО|ПАО|АО|ОАО)\s*", "", match["issuer"]).strip('" '):
            return None
        return MoneySecurity(match["reg"].upper(), match["issuer"], kind)
    return None
