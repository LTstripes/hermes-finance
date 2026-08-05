from enum import StrEnum


class ReportingMonthStatus(StrEnum):
    DRAFT = "draft"
    CLOSED = "closed"


class ReportingMonthSource(StrEnum):
    MANUAL = "manual"
    EXCEL_MIGRATION = "excel_migration"
    ALFA_PDF = "alfa_pdf"
