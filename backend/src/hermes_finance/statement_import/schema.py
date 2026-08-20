"""Structural schema and fail-closed allowlists for the Alfa depository
income-payment report family.

Unknown payment types are never inferred from security name or free text.
"""

from __future__ import annotations

from hermes_finance.domain import InvestmentCashFlowType
from hermes_finance.statement_import.dto import REPORT_TITLE
from hermes_finance.statement_import.money import fold_text

PROVIDER = "alfa_depository_income_report"

TITLE_FOLDED = fold_text(REPORT_TITLE)

PAYMENT_KIND_ALLOWLIST = {
    "выплата дивидендов": InvestmentCashFlowType.DIVIDEND.value,
    "погашение купона": InvestmentCashFlowType.COUPON.value,
    "полное погашение номинала": InvestmentCashFlowType.REDEMPTION.value,
}

# Semantic column -> header aliases (folded). Longest match wins.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "seq": ("№", "n", "номер п/п"),
    "depo_account": ("счет депо", "номер счета депо", "счет депо клиента"),
    "agreement": ("номер договора", "договор"),
    "upstream": ("вышестоящий депозитарий",),
    "payment_kind": ("вид выплаты",),
    "isin": ("isin",),
    "security_name": (
        "наименование ценной бумаги",
        "наименование цб",
        "наименование",
    ),
    "record_date": (
        "дата составления списка",
        "дата фиксации прав",
        "дата фиксации реестра",
        "дата фиксации",
    ),
    "quantity": (
        "количество ценных бумаг",
        "количество цб",
        "количество",
    ),
    "per_unit": (
        "сумма выплаты на 1 цб",
        "выплата на 1 цб",
        "сумма на одну цб",
        "на одну цб",
    ),
    "gross": (
        "сумма начисленного дохода",
        "начисленный доход",
        "сумма начисления",
    ),
    "gross_currency": ("валюта начисления", "валюта дохода"),
    "d1": ("d1",),
    "d2": ("d2",),
    "tax_rate": ("ставка налога", "ставка"),
    "tax": ("сумма налога", "удержанный налог", "налог"),
    "net": (
        "сумма дохода к перечислению",
        "сумма перечисленного дохода",
        "сумма к перечислению",
        "перечислено клиенту",
    ),
    "net_currency": ("валюта перечисления",),
    "payment_date": (
        "дата перечисления средств клиенту",
        "дата перечисления клиенту",
        "дата перечисления",
    ),
    "beneficiary_account": ("счет получателя", "банковский счет"),
    "beneficiary_bank": ("банк получателя", "банк"),
}

REQUIRED_COLUMNS = (
    "payment_kind",
    "isin",
    "record_date",
    "quantity",
    "per_unit",
    "gross",
    "net",
    "payment_date",
)

DROP_COLUMNS = frozenset(
    {"d1", "d2", "beneficiary_account", "beneficiary_bank", "security_name", "upstream", "seq"}
)

REASON_WRONG_FAMILY = "wrong_report_family"
REASON_ENCRYPTED = "encrypted_pdf"
REASON_UNREADABLE = "unreadable_pdf"
REASON_TOO_LARGE = "pdf_exceeds_size_bound"
REASON_TOO_MANY_PAGES = "pdf_exceeds_page_bound"
REASON_NO_TEXT = "pdf_has_no_usable_text_layer"
REASON_EXTRACT_BOUNDED = "pdf_exceeds_extract_bounds"
REASON_MISSING_SCHEMA = "missing_required_schema"
REASON_MISSING_PAYMENT_DATE = "missing_payment_date"
REASON_INVALID_PAYMENT_DATE = "invalid_payment_date"
REASON_MISSING_RECORD_DATE = "missing_record_date"
REASON_INVALID_RECORD_DATE = "invalid_record_date"
REASON_UNKNOWN_KIND = "unknown_payment_kind"
REASON_FOREIGN = "unsupported_foreign"
REASON_DECREE_665 = "unsupported_decree_665"
REASON_PARTIAL_AMORT = "unsupported_partial_amortization"
REASON_NON_RUB = "unsupported_non_rub_currency"
REASON_ARITHMETIC = "arithmetic_contradiction"
REASON_IDENTITY_COLLISION = "natural_identity_collision"
REASON_ACCOUNT_UNMAPPED = "account_unmapped"
REASON_ACCOUNT_AMBIGUOUS = "account_mapping_ambiguous"
REASON_INSTRUMENT_UNMATCHED = "instrument_unmatched"
REASON_INSTRUMENT_AMBIGUOUS = "instrument_ambiguous"
REASON_MISSING_ISIN = "missing_isin"
REASON_MISSING_AMOUNT = "missing_required_amount"
REASON_INVALID_AMOUNT = "invalid_amount"
REASON_MISSING_ACCOUNT_REF = "missing_provider_account_ref"
REASON_ROW_CAP = "row_cap_reached"


def looks_like_title(line: str) -> bool:
    folded = fold_text(line)
    return TITLE_FOLDED in folded


def classify_unsupported_context(line: str) -> str | None:
    folded = fold_text(line)
    if "указ" in folded and "665" in folded:
        return REASON_DECREE_665
    if "decree" in folded and "665" in folded:
        return REASON_DECREE_665
    if "иностранн" in folded and ("ценн" in folded or "securit" in folded):
        return REASON_FOREIGN
    if "foreign" in folded and "securit" in folded:
        return REASON_FOREIGN
    return None


def classify_payment_kind(cell: str) -> tuple[str | None, str | None]:
    """Return (event_kind, unsupported_reason). Unknown kinds fail closed."""

    folded = fold_text(cell)
    folded = folded.replace(".", "")
    if folded in PAYMENT_KIND_ALLOWLIST:
        return PAYMENT_KIND_ALLOWLIST[folded], None
    if "частичн" in folded and "погашен" in folded:
        return None, REASON_PARTIAL_AMORT
    if "амортизац" in folded:
        return None, REASON_PARTIAL_AMORT
    if "665" in folded:
        return None, REASON_DECREE_665
    return None, REASON_UNKNOWN_KIND


def alias_to_semantic() -> list[tuple[str, str]]:
    """(alias, semantic) pairs, longest alias first."""

    pairs: list[tuple[str, str]] = []
    for semantic, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            pairs.append((fold_text(alias), semantic))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return pairs


ALIAS_PAIRS = alias_to_semantic()
