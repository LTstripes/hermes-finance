"""Deterministic parser/normalizer over extracted structural content."""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal

from hermes_finance.statement_import.dto import (
    ExtractedDocument,
    ExtractStatus,
    ParsedReport,
    ParsedRow,
    ReportStatus,
    RowStatus,
)
from hermes_finance.statement_import.identity import (
    material_fingerprint,
    normalize_isin,
    source_identity_key,
)
from hermes_finance.statement_import.money import (
    INVALID,
    fold_text,
    is_dash_cell,
    kopecks,
    normalize_currency,
    parse_decimal,
    parse_report_date,
    split_amount_and_currency,
)
from hermes_finance.statement_import.schema import (
    ALIAS_PAIRS,
    DROP_COLUMNS,
    REASON_ARITHMETIC,
    REASON_ENCRYPTED,
    REASON_EXTRACT_BOUNDED,
    REASON_IDENTITY_COLLISION,
    REASON_INVALID_AMOUNT,
    REASON_INVALID_PAYMENT_DATE,
    REASON_INVALID_RECORD_DATE,
    REASON_MISSING_ACCOUNT_REF,
    REASON_MISSING_AMOUNT,
    REASON_MISSING_PAYMENT_DATE,
    REASON_MISSING_RECORD_DATE,
    REASON_MISSING_SCHEMA,
    REASON_NO_TEXT,
    REASON_NON_RUB,
    REASON_ROW_CAP,
    REASON_TOO_LARGE,
    REASON_TOO_MANY_PAGES,
    REASON_UNKNOWN_KIND,
    REASON_UNREADABLE,
    REASON_WRONG_FAMILY,
    REQUIRED_COLUMNS,
    classify_payment_kind,
    classify_unsupported_context,
    looks_like_title,
)

MAX_ROWS = 2_000
MAX_HEADER_LINES = 3
MAX_HEADER_SCAN_LINES = 6
MIN_ANCHORED_HEADER_LINES = 5
MAX_ANCHORED_HEADER_LINES = 6
LAYOUT_COLUMN_TOLERANCE = 2
MIN_LAYOUT_HEADER_FRAGMENTS = 4
_ANCHORED_LAYOUT_SEMANTICS = (
    "seq",
    "depo_account",
    "agreement",
    "upstream",
    "payment_kind",
    "isin",
    "security_name",
    "record_date",
    "quantity",
    "per_unit",
    "gross",
    "gross_currency",
    "d1",
    "d2",
    "tax_rate",
    "tax",
    "net",
    "net_currency",
    "payment_date",
    "beneficiary_account",
    "beneficiary_bank",
)
_CURRENT_ALFA_HEADER_FRAGMENT_COLUMNS = (
    (12, 13, 18),
    (0, 2, 3, 7, 8, 9, 10, 12, 13, 14, 15, 16, 18, 20),
    tuple(range(21)),
    (7, 9, 10, 12, 13, 15, 16, 18),
    (12, 13),
)
_ANCHOR_SEQUENCE = tuple(str(index) for index in range(1, len(_ANCHORED_LAYOUT_SEMANTICS) + 1))
_EXTRACT_STATUS = {
    ExtractStatus.ENCRYPTED: (ReportStatus.MALFORMED, REASON_ENCRYPTED),
    ExtractStatus.UNREADABLE: (ReportStatus.MALFORMED, REASON_UNREADABLE),
    ExtractStatus.TOO_LARGE: (ReportStatus.MALFORMED, REASON_TOO_LARGE),
    ExtractStatus.TOO_MANY_PAGES: (ReportStatus.MALFORMED, REASON_TOO_MANY_PAGES),
    ExtractStatus.NO_TEXT_LAYER: (ReportStatus.MALFORMED, REASON_NO_TEXT),
    ExtractStatus.EXTRACT_BOUNDED: (ReportStatus.MALFORMED, REASON_EXTRACT_BOUNDED),
}


def _iter_lines(extracted: ExtractedDocument) -> list[str]:
    lines: list[str] = []
    for page in extracted.pages:
        lines.extend(page.lines)
    return lines


def _match_header_cell(cell: str) -> str | None:
    folded = fold_text(cell)
    if not folded:
        return None
    compact = folded.replace(" ", "")
    for alias, semantic in ALIAS_PAIRS:
        if folded == alias or compact == alias.replace(" ", ""):
            return semantic
    return None


def _pipe_semantics(header_line: str) -> list[str | None] | None:
    if "|" not in header_line:
        return None
    cells = [cell.strip() for cell in header_line.split("|")]
    mapped = [_match_header_cell(cell) for cell in cells]
    if "payment_kind" in mapped and "isin" in mapped:
        return mapped
    return None


def _multi_line_pipe_header(lines: list[str], start: int) -> tuple[list[str | None], int] | None:
    """Recognize one bounded, vertically wrapped table header.

    Current Alfa PDFs may emit a table heading as two or three consecutive
    pipe-delimited lines. Only equal-width adjacent rows are joined cell by
    cell; data rows, arbitrary free text and unbounded reconstruction are not
    accepted as a schema.
    """
    first = [cell.strip() for cell in lines[start].split("|")]
    if len(first) < 2:
        return None
    header_rows = [first]
    for end in range(start, min(start + MAX_HEADER_SCAN_LINES, len(lines))):
        if end > start:
            if not lines[end].strip():
                continue
            if "|" not in lines[end]:
                break
            candidate = [cell.strip() for cell in lines[end].split("|")]
            if len(candidate) != len(first):
                break
            header_rows.append(candidate)
        joined = [
            " ".join(row[index] for row in header_rows if row[index]) for index in range(len(first))
        ]
        mapped = [_match_header_cell(cell) for cell in joined]
        if _schema_complete({item for item in mapped if item}):
            return mapped, end
        if len(header_rows) == MAX_HEADER_LINES:
            break
    return None


def _layout_fragments(line: str) -> list[tuple[int, str]]:
    """Return positioned text fragments separated by layout-sized gaps."""
    return [
        (match.start(), match.group().strip())
        for match in re.finditer(r"\S.*?(?=(?: {2,}|$))", line)
    ]


def _column_number_positions(line: str) -> tuple[int, ...] | None:
    """Return physical columns only for the exact supported ``1..21`` anchor."""
    fragments = _layout_fragments(line)
    if tuple(text for _start, text in fragments) != _ANCHOR_SEQUENCE:
        return None
    positions = tuple(start for start, _text in fragments)
    if len(set(positions)) != len(_ANCHOR_SEQUENCE):
        return None
    return positions


def _anchored_header_cell_matches(cell: str, expected: str) -> bool:
    """Validate one physical band of the fixed Alfa 21-column layout.

    The two currency headings are deliberately accepted as plain ``Валюта``
    only at their known gross/net positions; they are never inferred from
    arbitrary free text.
    """
    folded = fold_text(cell)
    if expected in {"gross_currency", "net_currency"}:
        return folded == "валюта" or _match_header_cell(cell) == expected
    if expected in {"d1", "d2"}:
        return expected in folded or "значение показателя" in folded
    if expected == "seq":
        return "п/п" in folded
    if expected == "agreement":
        return "соглашения" in folded
    if expected == "beneficiary_bank":
        return folded == "банк получателя доход" or _match_header_cell(cell) == expected
    return _match_header_cell(cell) == expected


def _anchored_columns_from_parts(
    parts: list[list[str]], positions: tuple[int, ...]
) -> list[tuple[int, str]] | None:
    columns: list[tuple[int, str]] = []
    for index, semantic in enumerate(_ANCHORED_LAYOUT_SEMANTICS):
        header = " ".join(parts[index])
        if not _anchored_header_cell_matches(header, semantic):
            return None
        columns.append((positions[index], semantic))
    return columns


def _anchored_layout_columns(
    header_lines: list[str], positions: tuple[int, ...]
) -> list[tuple[int, str]] | None:
    """Reconstruct a fixed schema from header fragments inside anchor bands."""
    fragment_columns = _CURRENT_ALFA_HEADER_FRAGMENT_COLUMNS
    if tuple(len(_layout_fragments(line)) for line in header_lines) == tuple(
        len(columns) for columns in fragment_columns
    ):
        parts: list[list[str]] = [[] for _semantic in _ANCHORED_LAYOUT_SEMANTICS]
        for line, columns in zip(header_lines, fragment_columns, strict=True):
            for column, (_start, text) in zip(columns, _layout_fragments(line), strict=True):
                parts[column].append(text)
        return _anchored_columns_from_parts(parts, positions)

    parts: list[list[str]] = [[] for _semantic in _ANCHORED_LAYOUT_SEMANTICS]
    for line in header_lines:
        for start, text in _layout_fragments(line):
            if start < positions[0]:
                return None
            column = max(index for index, boundary in enumerate(positions) if boundary <= start)
            parts[column].append(text)

    return _anchored_columns_from_parts(parts, positions)


def _anchored_layout_header(lines: list[str], anchor_index: int) -> list[tuple[int, str]] | None:
    """Recognize the bounded current Alfa 21-column graphical-table schema."""
    positions = _column_number_positions(lines[anchor_index])
    if positions is None:
        return None
    preceding: list[str] = []
    scan_start = max(0, anchor_index - 2 * MAX_ANCHORED_HEADER_LINES)
    for index in range(anchor_index - 1, scan_start - 1, -1):
        line = lines[index]
        if not line.strip():
            continue
        if "|" in line or looks_like_title(line):
            break
        preceding.append(line)
        if len(preceding) == MAX_ANCHORED_HEADER_LINES:
            break
    preceding.reverse()
    for count in range(MIN_ANCHORED_HEADER_LINES, len(preceding) + 1):
        header_lines = preceding[-count:]
        columns = _anchored_layout_columns(header_lines, positions)
        if columns is not None:
            return columns
    return None


def _find_anchored_layout_header(lines: list[str]) -> tuple[list[tuple[int, str]], int] | None:
    """Find the exact 21-column anchor and a complete supported header above it."""
    for index, line in enumerate(lines):
        if _column_number_positions(line) is None:
            continue
        columns = _anchored_layout_header(lines, index)
        if columns is not None:
            return columns, index
    return None


def _layout_header_columns(
    header_rows: list[list[tuple[int, str]]],
) -> list[tuple[int, str]] | None:
    """Join wrapped header cells only when their column positions stay stable."""
    first_starts = [start for start, _text in header_rows[0]]
    if len(first_starts) < MIN_LAYOUT_HEADER_FRAGMENTS:
        return None

    parts: dict[int, list[str]] = {start: [] for start in first_starts}
    shared_positions = 0
    for row_index, fragments in enumerate(header_rows):
        matched_starts: set[int] = set()
        for start, text in fragments:
            closest = min(first_starts, key=lambda candidate: abs(candidate - start))
            if abs(closest - start) > LAYOUT_COLUMN_TOLERANCE:
                return None
            parts[closest].append(text)
            matched_starts.add(closest)
        if row_index:
            shared_positions = max(shared_positions, len(matched_starts))
    if shared_positions < MIN_LAYOUT_HEADER_FRAGMENTS:
        return None

    columns: list[tuple[int, str]] = []
    seen_semantics: set[str] = set()
    for start in first_starts:
        semantic = _match_header_cell(" ".join(parts[start]))
        if semantic is None or semantic in seen_semantics:
            continue
        columns.append((start, semantic))
        seen_semantics.add(semantic)
    columns.sort()
    return columns if _schema_complete(seen_semantics) else None


def _multi_line_layout_header(
    lines: list[str], start: int
) -> tuple[list[tuple[int, str]], int] | None:
    """Recognize a bounded 2–3 line layout header without table delimiters.

    pypdf layout extraction preserves horizontal positions but not graphical table
    borders. This accepts only adjacent non-pipe lines with stable fragment
    positions and an exact complete semantic schema.
    """
    header_rows: list[list[tuple[int, str]]] = []
    for end in range(start, min(start + MAX_HEADER_SCAN_LINES, len(lines))):
        line = lines[end]
        if not line.strip():
            continue
        if "|" in line:
            break
        fragments = _layout_fragments(line)
        if len(fragments) < MIN_LAYOUT_HEADER_FRAGMENTS:
            break
        header_rows.append(fragments)
        if len(header_rows) >= 2:
            columns = _layout_header_columns(header_rows)
            if columns is not None:
                return columns, end
        if len(header_rows) == MAX_HEADER_LINES:
            break
    return None


def _layout_columns(header_line: str) -> list[tuple[int, str]] | None:
    haystack = header_line.replace("ё", "е").replace("Ё", "Е").lower()
    if "вид выплаты" not in haystack or "isin" not in haystack:
        return None
    used = [False] * len(haystack)
    found: list[tuple[int, str]] = []
    seen_semantic: set[str] = set()
    for alias, semantic in ALIAS_PAIRS:
        if semantic in seen_semantic:
            continue
        idx = haystack.find(alias)
        if idx < 0:
            continue
        if any(used[idx : idx + len(alias)]):
            continue
        for pos in range(idx, idx + len(alias)):
            used[pos] = True
        found.append((idx, semantic))
        seen_semantic.add(semantic)
    found.sort()
    if "payment_kind" in seen_semantic and "isin" in seen_semantic:
        return found
    return None


def _cells_from_layout(line: str, columns: list[tuple[int, str]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for index, (start, semantic) in enumerate(columns):
        end = columns[index + 1][0] if index + 1 < len(columns) else len(line)
        values[semantic] = line[start:end].strip()
    return values


def _cells_from_pipe(line: str, semantics: list[str | None]) -> dict[str, str] | None:
    cells = [cell.strip() for cell in line.split("|")]
    if len(cells) != len(semantics):
        if abs(len(cells) - len(semantics)) > 2:
            return None
    values: dict[str, str] = {}
    for semantic, cell in zip(semantics, cells, strict=False):
        if semantic:
            values[semantic] = cell
    return values


def _report_has_title(lines: list[str]) -> bool:
    return any(looks_like_title(line) for line in lines[:40])


def _schema_complete(present: set[str]) -> bool:
    return all(column in present for column in REQUIRED_COLUMNS)


def _currency_of(
    *,
    dedicated: str | None,
    split_currency: str | None,
    fallback: str | None,
) -> str | None:
    for candidate in (dedicated, split_currency, fallback):
        if candidate:
            normalized = normalize_currency(candidate)
            if normalized:
                return normalized
    return None


def _malformed_row(**kwargs: object) -> ParsedRow:
    return ParsedRow(
        status=RowStatus.MALFORMED,
        event_kind=kwargs.get("event_kind"),  # type: ignore[arg-type]
        provider_account_ref=kwargs.get("provider_account_ref"),  # type: ignore[arg-type]
        isin=kwargs.get("isin"),  # type: ignore[arg-type]
        record_date=kwargs.get("record_date"),  # type: ignore[arg-type]
        event_date=kwargs.get("event_date"),  # type: ignore[arg-type]
        quantity=kwargs.get("quantity"),  # type: ignore[arg-type]
        per_unit=kwargs.get("per_unit"),  # type: ignore[arg-type]
        gross_amount=kwargs.get("gross_amount"),  # type: ignore[arg-type]
        gross_currency=kwargs.get("gross_currency"),  # type: ignore[arg-type]
        tax_amount=kwargs.get("tax_amount"),  # type: ignore[arg-type]
        tax_available=bool(kwargs.get("tax_available", False)),
        tax_rate=kwargs.get("tax_rate"),  # type: ignore[arg-type]
        net_amount=kwargs.get("net_amount"),  # type: ignore[arg-type]
        net_currency=kwargs.get("net_currency"),  # type: ignore[arg-type]
        source_identity=None,
        material_fingerprint=None,
        reason=str(kwargs.get("reason")),
    )


def _unsupported_row(**kwargs: object) -> ParsedRow:
    row = _malformed_row(**kwargs)
    return ParsedRow(
        status=RowStatus.UNSUPPORTED,
        event_kind=row.event_kind,
        provider_account_ref=row.provider_account_ref,
        isin=row.isin,
        record_date=row.record_date,
        event_date=row.event_date,
        quantity=row.quantity,
        per_unit=row.per_unit,
        gross_amount=row.gross_amount,
        gross_currency=row.gross_currency,
        tax_amount=row.tax_amount,
        tax_available=row.tax_available,
        tax_rate=row.tax_rate,
        net_amount=row.net_amount,
        net_currency=row.net_currency,
        source_identity=None,
        material_fingerprint=None,
        reason=row.reason,
    )


def _normalize_row(cells: dict[str, str], *, section_reason: str | None) -> ParsedRow:
    # Explicitly drop private/report-only fields by never copying DROP_COLUMNS.
    for dropped in DROP_COLUMNS:
        cells.pop(dropped, None)

    kind_cell = cells.get("payment_kind", "")
    event_kind, kind_reason = (
        classify_payment_kind(kind_cell)
        if kind_cell.strip()
        else (
            None,
            REASON_UNKNOWN_KIND,
        )
    )
    isin = normalize_isin(cells.get("isin"))
    depo = (cells.get("depo_account") or "").strip()
    agreement = (cells.get("agreement") or "").strip()
    provider_account_ref = depo or agreement or None

    record_date = parse_report_date(cells.get("record_date"))
    event_date = parse_report_date(cells.get("payment_date"))
    quantity = parse_decimal(cells.get("quantity"))
    per_unit = parse_decimal(cells.get("per_unit"))
    gross_raw, gross_ccy_from_amount = split_amount_and_currency(cells.get("gross"))
    net_raw, net_ccy_from_amount = split_amount_and_currency(cells.get("net"))
    tax_cell = cells.get("tax")
    tax_available = not is_dash_cell(tax_cell)
    tax_raw = parse_decimal(tax_cell) if tax_available else None
    tax_rate = parse_decimal(cells.get("tax_rate")) if cells.get("tax_rate") else None

    gross_currency = _currency_of(
        dedicated=cells.get("gross_currency"),
        split_currency=gross_ccy_from_amount,
        fallback=None,
    )
    net_currency = _currency_of(
        dedicated=cells.get("net_currency"),
        split_currency=net_ccy_from_amount,
        fallback=gross_currency,
    )

    common = {
        "event_kind": event_kind,
        "provider_account_ref": provider_account_ref,
        "isin": isin,
        "record_date": record_date if record_date is not INVALID else None,
        "event_date": event_date if event_date is not INVALID else None,
        "quantity": quantity if isinstance(quantity, Decimal) else None,
        "per_unit": per_unit if isinstance(per_unit, Decimal) else None,
        "gross_amount": gross_raw if isinstance(gross_raw, Decimal) else None,
        "gross_currency": gross_currency,
        "tax_amount": tax_raw if isinstance(tax_raw, Decimal) else None,
        "tax_available": bool(tax_available and isinstance(tax_raw, Decimal)),
        "tax_rate": tax_rate if isinstance(tax_rate, Decimal) else None,
        "net_amount": net_raw if isinstance(net_raw, Decimal) else None,
        "net_currency": net_currency,
    }

    if section_reason:
        return _unsupported_row(**common, reason=section_reason)
    if event_kind is None:
        return _unsupported_row(**common, reason=kind_reason or REASON_UNKNOWN_KIND)
    if event_date is None:
        return _malformed_row(**common, reason=REASON_MISSING_PAYMENT_DATE)
    if event_date is INVALID:
        return _malformed_row(**common, reason=REASON_INVALID_PAYMENT_DATE)
    if record_date is None:
        return _malformed_row(**common, reason=REASON_MISSING_RECORD_DATE)
    if record_date is INVALID:
        return _malformed_row(**common, reason=REASON_INVALID_RECORD_DATE)
    if not provider_account_ref:
        return _malformed_row(**common, reason=REASON_MISSING_ACCOUNT_REF)
    for parsed in (quantity, per_unit, gross_raw, net_raw):
        if parsed is None:
            return _malformed_row(**common, reason=REASON_MISSING_AMOUNT)
        if parsed is INVALID:
            return _malformed_row(**common, reason=REASON_INVALID_AMOUNT)
    if tax_available and tax_raw is INVALID:
        return _malformed_row(**common, reason=REASON_INVALID_AMOUNT)
    if tax_rate is INVALID:
        tax_rate = None
        common["tax_rate"] = None

    assert isinstance(quantity, Decimal)
    assert isinstance(per_unit, Decimal)
    assert isinstance(gross_raw, Decimal)
    assert isinstance(net_raw, Decimal)
    tax_amount = tax_raw if isinstance(tax_raw, Decimal) else None
    tax_is_numeric = tax_available and tax_amount is not None

    currencies = {gross_currency, net_currency}
    if None in currencies or any(code != "RUB" for code in currencies if code):
        return _unsupported_row(**common, reason=REASON_NON_RUB)
    if gross_currency != "RUB" or net_currency != "RUB":
        return _unsupported_row(**common, reason=REASON_NON_RUB)

    if tax_is_numeric:
        expected_net = kopecks(gross_raw) - kopecks(tax_amount)
        if expected_net != kopecks(net_raw):
            return _malformed_row(**common, reason=REASON_ARITHMETIC)
    if kopecks(quantity * per_unit) != kopecks(gross_raw):
        return _malformed_row(**common, reason=REASON_ARITHMETIC)

    fingerprint = material_fingerprint(
        event_date=event_date,
        quantity=quantity,
        per_unit=per_unit,
        gross_amount=gross_raw,
        gross_currency=gross_currency,
        tax_available=tax_is_numeric,
        tax_amount=tax_amount if tax_is_numeric else None,
        tax_rate=common["tax_rate"],
        net_amount=net_raw,
        net_currency=net_currency,
    )
    identity = source_identity_key(
        provider_account_ref=provider_account_ref,
        event_kind=event_kind,
        isin=isin,
        record_date=record_date,
    )
    return ParsedRow(
        status=RowStatus.MATCHED,
        event_kind=event_kind,
        provider_account_ref=provider_account_ref,
        isin=isin,
        record_date=record_date,
        event_date=event_date,
        quantity=quantity,
        per_unit=per_unit,
        gross_amount=gross_raw,
        gross_currency=gross_currency,
        tax_amount=tax_amount if tax_is_numeric else None,
        tax_available=tax_is_numeric,
        tax_rate=common["tax_rate"],
        net_amount=net_raw,
        net_currency=net_currency,
        source_identity=identity,
        material_fingerprint=fingerprint,
        reason=None,
    )


def _apply_collisions(rows: list[ParsedRow]) -> list[ParsedRow]:
    groups: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        if row.status is RowStatus.MATCHED and row.source_identity:
            groups[row.source_identity].append(index)
    updated = list(rows)
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        for index in indexes:
            row = updated[index]
            updated[index] = ParsedRow(
                status=RowStatus.AMBIGUOUS,
                event_kind=row.event_kind,
                provider_account_ref=row.provider_account_ref,
                isin=row.isin,
                record_date=row.record_date,
                event_date=row.event_date,
                quantity=row.quantity,
                per_unit=row.per_unit,
                gross_amount=row.gross_amount,
                gross_currency=row.gross_currency,
                tax_amount=row.tax_amount,
                tax_available=row.tax_available,
                tax_rate=row.tax_rate,
                net_amount=row.net_amount,
                net_currency=row.net_currency,
                source_identity=row.source_identity,
                material_fingerprint=row.material_fingerprint,
                reason=REASON_IDENTITY_COLLISION,
            )
    return updated


def parse_income_report(extracted: ExtractedDocument) -> ParsedReport:
    digest = extracted.document_sha256
    if extracted.status is not ExtractStatus.OK:
        status, reason = _EXTRACT_STATUS[extracted.status]
        return ParsedReport(
            status=status, document_sha256=digest, rows=(), warnings=(), reason=reason
        )

    lines = _iter_lines(extracted)
    if not _report_has_title(lines):
        return ParsedReport(
            status=ReportStatus.NON_APPLICABLE,
            document_sha256=digest,
            rows=(),
            warnings=(),
            reason=REASON_WRONG_FAMILY,
        )

    pipe_semantics: list[str | None] | None = None
    layout_cols: list[tuple[int, str]] | None = None
    header_index: int | None = None
    anchored_layout_header = _find_anchored_layout_header(lines)
    if anchored_layout_header is not None:
        layout_cols, header_index = anchored_layout_header
    else:
        for index, line in enumerate(lines):
            multi_line_header = _multi_line_pipe_header(lines, index) if "|" in line else None
            if multi_line_header is not None:
                pipe_semantics, header_index = multi_line_header
                break
            multi_line_layout_header = (
                _multi_line_layout_header(lines, index) if "|" not in line else None
            )
            if multi_line_layout_header is not None:
                layout_cols, header_index = multi_line_layout_header
                break
            layout_cols = _layout_columns(line)
            if layout_cols is not None:
                header_index = index
                break
    if header_index is None:
        return ParsedReport(
            status=ReportStatus.MALFORMED,
            document_sha256=digest,
            rows=(),
            warnings=(),
            reason=REASON_MISSING_SCHEMA,
        )

    present: set[str] = set()
    if pipe_semantics is not None:
        present = {item for item in pipe_semantics if item}
    elif layout_cols is not None:
        present = {item[1] for item in layout_cols}
    if not _schema_complete(present):
        return ParsedReport(
            status=ReportStatus.MALFORMED,
            document_sha256=digest,
            rows=(),
            warnings=(),
            reason=REASON_MISSING_SCHEMA,
        )

    warnings: list[str] = []
    rows: list[ParsedRow] = []
    section_reason: str | None = None
    for line in lines[: header_index + 1]:
        context = classify_unsupported_context(line)
        if context:
            section_reason = context
    for line in lines[header_index + 1 :]:
        if looks_like_title(line):
            continue
        context = classify_unsupported_context(line)
        if context:
            section_reason = context
            continue
        if pipe_semantics is not None:
            if "|" not in line:
                context = classify_unsupported_context(line)
                if context:
                    section_reason = context
                continue
            if _pipe_semantics(line) is not None:
                continue
            cells = _cells_from_pipe(line, pipe_semantics)
            if cells is None:
                continue
        else:
            assert layout_cols is not None
            cells = _cells_from_layout(line, layout_cols)
        if not cells.get("payment_kind") and not cells.get("isin"):
            continue
        if len(rows) >= MAX_ROWS:
            warnings.append(REASON_ROW_CAP)
            break
        rows.append(_normalize_row(cells, section_reason=section_reason))

    rows = _apply_collisions(rows)
    allowlisted = any(row.event_kind is not None for row in rows)
    unsupported_only = bool(rows) and all(row.status is RowStatus.UNSUPPORTED for row in rows)
    if unsupported_only and not allowlisted:
        report_status = ReportStatus.UNSUPPORTED
    else:
        report_status = ReportStatus.APPLICABLE
    return ParsedReport(
        status=report_status,
        document_sha256=digest,
        rows=tuple(rows),
        warnings=tuple(warnings),
        reason=None,
    )
