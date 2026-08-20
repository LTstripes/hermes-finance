"""Deterministic parser/normalizer over extracted structural content."""

from __future__ import annotations

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
    for index, line in enumerate(lines):
        pipe_semantics = _pipe_semantics(line)
        if pipe_semantics is not None:
            header_index = index
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
