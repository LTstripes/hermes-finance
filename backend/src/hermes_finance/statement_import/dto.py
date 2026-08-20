"""Immutable read-only statement-import DTOs (R06-07).

No persistence, network, API or UI. Normalized events must not retain
beneficiary bank details, D1/D2, security names, raw PDF bytes or extracted
report text.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

ALFA_DEPOSITORY_INCOME_PROVIDER = "alfa_depository_income_report"
REPORT_TITLE = "Отчет о произведенных выплатах доходов по ценным бумагам"


class ReportStatus(StrEnum):
    APPLICABLE = "applicable"
    NON_APPLICABLE = "non_applicable"
    MALFORMED = "malformed"
    UNSUPPORTED = "unsupported"


class RowStatus(StrEnum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    MALFORMED = "malformed"


class DuplicateClass(StrEnum):
    DUPLICATE = "duplicate"
    CORRECTION = "correction"


class ExtractStatus(StrEnum):
    OK = "ok"
    ENCRYPTED = "encrypted"
    UNREADABLE = "unreadable"
    TOO_LARGE = "too_large"
    TOO_MANY_PAGES = "too_many_pages"
    NO_TEXT_LAYER = "no_text_layer"
    EXTRACT_BOUNDED = "extract_bounded"


@dataclass(frozen=True, slots=True)
class HermesAccountView:
    account_id: int
    account_type: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class HermesInstrumentView:
    instrument_id: int
    isin: str | None
    name: str | None = None
    ticker: str | None = None


@dataclass(frozen=True, slots=True)
class AccountMappingInput:
    """Explicit owner mapping: report depository-account ref -> Hermes account.

    Never inferred from IIS markers, names, beneficiary bank or heuristics.
    """

    hermes_account_id: int
    provider_account_ref: str


@dataclass(frozen=True, slots=True)
class InstrumentMappingInput:
    """Explicit owner mapping by normalized ISIN. Ticker/name are not identity."""

    hermes_instrument_id: int
    isin: str


@dataclass(frozen=True, slots=True)
class PriorEventView:
    """In-memory prior-preview/history row for deterministic duplicate tests.

    Persistence is out of scope; callers supply this view explicitly.
    """

    natural_identity: str
    material_fingerprint: str


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    status: ExtractStatus
    document_sha256: str
    page_count: int
    pages: tuple[ExtractedPage, ...]
    reason: str | None


@dataclass(frozen=True, slots=True)
class ParsedRow:
    status: RowStatus
    event_kind: str | None
    provider_account_ref: str | None
    isin: str | None
    record_date: date | None
    event_date: date | None
    quantity: Decimal | None
    per_unit: Decimal | None
    gross_amount: Decimal | None
    gross_currency: str | None
    tax_amount: Decimal | None
    tax_available: bool
    tax_rate: Decimal | None
    net_amount: Decimal | None
    net_currency: str | None
    source_identity: str | None
    material_fingerprint: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class ParsedReport:
    status: ReportStatus
    document_sha256: str
    rows: tuple[ParsedRow, ...]
    warnings: tuple[str, ...]
    reason: str | None


@dataclass(frozen=True, slots=True)
class PreviewRow:
    status: RowStatus
    event_kind: str | None
    hermes_account_id: int | None
    hermes_instrument_id: int | None
    provider_account_ref: str | None
    isin: str | None
    record_date: date | None
    event_date: date | None
    quantity: Decimal | None
    per_unit: Decimal | None
    gross_amount: Decimal | None
    gross_currency: str | None
    tax_amount: Decimal | None
    tax_available: bool
    tax_rate: Decimal | None
    net_amount: Decimal | None
    net_currency: str | None
    natural_identity: str | None
    material_fingerprint: str | None
    duplicate_class: DuplicateClass | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class IncomeReportPreview:
    status: ReportStatus
    provider: str
    document_sha256: str
    rows: tuple[PreviewRow, ...]
    warnings: tuple[str, ...]
    reason: str | None
