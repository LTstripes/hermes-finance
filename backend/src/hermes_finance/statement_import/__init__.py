"""Provider-neutral read-only Alfa depository income-report import (R06-07).

Split boundary:
1. bounded PDF text-layer extraction (no OCR, no network);
2. deterministic parser/normalizer;
3. read-only preview against Hermes account/instrument views.

Importing this package does not open a network, write persistence, mutate
investment cash flows, or expose API/UI.
"""

from hermes_finance.statement_import.dto import (
    ALFA_DEPOSITORY_INCOME_PROVIDER,
    REPORT_TITLE,
    AccountMappingInput,
    DuplicateClass,
    ExtractedDocument,
    ExtractStatus,
    HermesAccountView,
    HermesInstrumentView,
    IncomeReportPreview,
    InstrumentMappingInput,
    ParsedReport,
    ParsedRow,
    PreviewRow,
    PriorEventView,
    ReportStatus,
    RowStatus,
)
from hermes_finance.statement_import.extract import extract_pdf_text_layer
from hermes_finance.statement_import.parse import parse_income_report
from hermes_finance.statement_import.preview import preview_income_report

__all__ = [
    "ALFA_DEPOSITORY_INCOME_PROVIDER",
    "REPORT_TITLE",
    "AccountMappingInput",
    "DuplicateClass",
    "ExtractStatus",
    "ExtractedDocument",
    "HermesAccountView",
    "HermesInstrumentView",
    "IncomeReportPreview",
    "InstrumentMappingInput",
    "ParsedReport",
    "ParsedRow",
    "PreviewRow",
    "PriorEventView",
    "ReportStatus",
    "RowStatus",
    "extract_pdf_text_layer",
    "parse_income_report",
    "preview_income_report",
]
