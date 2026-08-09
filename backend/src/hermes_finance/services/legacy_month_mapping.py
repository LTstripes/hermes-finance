"""Validate the explicit mapping between legacy Excel sheets and months."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from json import JSONDecodeError
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

DEFAULT_LEGACY_MAPPING_FILENAME = "legacy_month_mapping.json"


class _ReportingMonth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int = Field(ge=1900, le=9999)
    month: int = Field(ge=1, le=12)


class _MappingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sheet_name: str = Field(min_length=1, max_length=128)
    reporting_month: _ReportingMonth
    snapshot_date: date
    import_flag: bool

    @field_validator("sheet_name")
    @classmethod
    def normalize_sheet_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("sheet_name must not be empty")
        return normalized


class LegacyMonthMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_ref: str | None = Field(default=None, alias="$schema")
    schema_version: Literal[1]
    source_file: str = Field(min_length=1, max_length=260)
    mappings: list[_MappingEntry]


@dataclass(frozen=True, slots=True)
class LegacyMonthMappingResult:
    source_file: str
    total_mappings: int
    importable_mappings: int
    skipped_mappings: int


def _parse_mapping(path: Path) -> LegacyMonthMapping:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("legacy month mapping file is not available") from error

    try:
        payload = json.loads(raw)
        document = LegacyMonthMapping.model_validate(payload)
    except (JSONDecodeError, TypeError, ValidationError) as error:
        raise ValueError("legacy month mapping validation failed") from error

    sheet_names = [entry.sheet_name for entry in document.mappings]
    if len(sheet_names) != len(set(sheet_names)):
        raise ValueError("legacy month mapping contains duplicate sheet names")

    periods = [
        (entry.reporting_month.year, entry.reporting_month.month) for entry in document.mappings
    ]
    if len(periods) != len(set(periods)):
        raise ValueError("legacy month mapping contains duplicate reporting periods")
    return document


def read_legacy_month_mapping(path: Path) -> LegacyMonthMapping:
    """Read and validate the explicit mapping document for local import work."""
    return _parse_mapping(path)


def load_legacy_month_mapping(path: Path) -> LegacyMonthMappingResult:
    """Validate a local mapping without reading or modifying the source workbook."""
    document = _parse_mapping(path)
    importable = sum(entry.import_flag for entry in document.mappings)
    return LegacyMonthMappingResult(
        source_file=document.source_file,
        total_mappings=len(document.mappings),
        importable_mappings=importable,
        skipped_mappings=len(document.mappings) - importable,
    )
