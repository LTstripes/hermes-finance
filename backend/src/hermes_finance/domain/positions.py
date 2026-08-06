from enum import StrEnum


class PriceSource(StrEnum):
    MANUAL = "manual"
    MOEX = "moex"
    ALFA_PDF = "alfa_pdf"
