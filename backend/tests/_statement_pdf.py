"""In-memory synthetic PDF builder for statement-import tests.

Produces a PDF 1.4 text layer with Identity-H + ToUnicode so Cyrillic
headers survive pypdf extraction. No files are written. Tests only.
No OCR, no owner samples, no disk fonts.
"""

from __future__ import annotations

import io

from pypdf import PdfWriter

from hermes_finance.statement_import.dto import REPORT_TITLE

REPORT_COLUMNS: tuple[str, ...] = (
    "№",
    "Счет депо",
    "Номер договора",
    "Вышестоящий депозитарий",
    "Вид выплаты",
    "ISIN",
    "Наименование ценной бумаги",
    "Дата составления списка",
    "Количество",
    "Сумма выплаты на 1 ЦБ",
    "Сумма начисленного дохода",
    "Валюта начисления",
    "D1",
    "D2",
    "Ставка налога",
    "Сумма налога",
    "Сумма дохода к перечислению",
    "Валюта перечисления",
    "Дата перечисления средств клиенту",
    "Счет получателя",
    "Банк получателя",
)

CURRENT_ALFA_LAYOUT_HEADER: tuple[tuple[str, ...], ...] = (
    (
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "Значение показателя",
        "Значение показателя",
        "",
        "",
        "",
        "",
        "Дата",
        "",
        "",
    ),
    (
        "№",
        "",
        "ген.",
        "Вышестоящий",
        "",
        "",
        "",
        "Дата",
        "Число ц/б,",
        "Размер",
        "Общая сумма",
        "",
        "Д1, предоставленное",
        "Д2, предоставленное",
        "Налоговая",
        "Удержанная сумма",
        "Сумма",
        "",
        "перечисления",
        "",
        "Банк получателя",
    ),
    (
        "п/п",
        "№ счета депо",
        "соглашения",
        "депозитарий",
        "Вид выплаты",
        "ISIN",
        "Наименование ценной бумаги",
        "фиксации",
        "шт.",
        "выплаты",
        "начисленной",
        "Валюта",
        "эмитентом для расчета",
        "эмитентом для расчета",
        "ставка, %",
        "налога,",
        "перечисленного",
        "Валюта",
        "средств",
        "Счет получателя дохода",
        "доход",
    ),
    (
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "реестра",
        "",
        "на 1 ц.б.",
        "выплаты",
        "",
        "суммы налога на",
        "суммы налога на",
        "",
        "руб.",
        "дохода",
        "",
        "клиенту",
        "",
        "",
    ),
    (
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "дивиденды (сноска 0)",
        "дивиденды (сноска 0)",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    ),
)

LAYOUT_COLUMN_START = 40.0
LAYOUT_COLUMN_STEP = 126.0
LAYOUT_PAGE_WIDTH = LAYOUT_COLUMN_START + LAYOUT_COLUMN_STEP * len(REPORT_COLUMNS) + 80.0

_SEMANTIC_TO_COLUMN = {
    "seq": "№",
    "depo_account": "Счет депо",
    "agreement": "Номер договора",
    "upstream": "Вышестоящий депозитарий",
    "payment_kind": "Вид выплаты",
    "isin": "ISIN",
    "security_name": "Наименование ценной бумаги",
    "record_date": "Дата составления списка",
    "quantity": "Количество",
    "per_unit": "Сумма выплаты на 1 ЦБ",
    "gross": "Сумма начисленного дохода",
    "gross_currency": "Валюта начисления",
    "d1": "D1",
    "d2": "D2",
    "tax_rate": "Ставка налога",
    "tax": "Сумма налога",
    "net": "Сумма дохода к перечислению",
    "net_currency": "Валюта перечисления",
    "payment_date": "Дата перечисления средств клиенту",
    "beneficiary_account": "Счет получателя",
    "beneficiary_bank": "Банк получателя",
}


def utf16_hex(text: str) -> str:
    return text.encode("utf-16-be").hex().upper()


def _content_stream(fragments: list[tuple[float, float, str]], font_size: float) -> bytes:
    parts: list[str] = []
    for x, y, text in fragments:
        if not text:
            continue
        hex_text = utf16_hex(text)
        parts.append(f"BT /F1 {font_size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm <{hex_text}> Tj ET")
    return ("\n".join(parts) + "\n").encode("ascii")


def _to_unicode_cmap() -> bytes:
    return b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
1 beginbfrange
<0000> <FFFF> <0000>
endbfrange
endcmap
CMapName currentdict /CMap defineresource pop
end
end
"""


def _wrap_objects(objects: list[bytes]) -> bytes:
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    body = header
    offsets = [0]
    for obj in objects:
        offsets.append(len(body))
        body += f"{len(offsets) - 1} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"
    xref_at = len(body)
    xref = [f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"]
    xref.extend(f"{offset:010d} 00000 n \n" for offset in offsets[1:])
    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    return body + "".join(xref).encode("ascii") + trailer.encode("ascii")


def build_text_pdf(
    pages: list[list[tuple[float, float, str]]],
    *,
    width: float = 2400.0,
    height: float = 842.0,
    font_size: float = 8.0,
) -> bytes:
    if not pages:
        pages = [[]]
    to_unicode = _to_unicode_cmap()
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"placeholder-pages",
    ]
    page_ids: list[int] = []
    for fragments in pages:
        stream = _content_stream(fragments, font_size)
        page_ids.append(len(objects) + 1)
        objects.append(b"placeholder-page")
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"endstream"
        )

    font_id = len(objects) + 1
    descendant_id = font_id + 1
    cidinfo_id = font_id + 2
    tounicode_id = font_id + 3
    descriptor_id = font_id + 4
    objects.append(
        (
            f"<< /Type /Font /Subtype /Type0 /BaseFont /SyntheticUni "
            f"/Encoding /Identity-H /DescendantFonts [{descendant_id} 0 R] "
            f"/ToUnicode {tounicode_id} 0 R >>"
        ).encode("ascii")
    )
    objects.append(
        (
            f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /SyntheticUni "
            f"/CIDSystemInfo {cidinfo_id} 0 R /FontDescriptor {descriptor_id} 0 R "
            f"/DW 500 >>"
        ).encode("ascii")
    )
    objects.append(b"<< /Registry (Adobe) /Ordering (Identity) /Supplement 0 >>")
    objects.append(
        f"<< /Length {len(to_unicode)} >>\nstream\n".encode("ascii") + to_unicode + b"endstream"
    )
    objects.append(
        b"<< /Type /FontDescriptor /FontName /SyntheticUni /Flags 4 "
        b"/FontBBox [0 -200 1000 800] /ItalicAngle 0 /Ascent 800 "
        b"/Descent -200 /CapHeight 700 /StemV 80 >>"
    )
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")
    for page_id in page_ids:
        content_id = page_id + 1
        objects[page_id - 1] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        ).encode("ascii")
    return _wrap_objects(objects)


def build_blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def build_encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("synthetic-test-password")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _default_row() -> dict[str, str]:
    return {
        "seq": "1",
        "depo_account": "SYN-DEPO-001",
        "agreement": "SYN-AGR-001",
        "upstream": "SYN-NSD",
        "payment_kind": "выплата дивидендов",
        "isin": "RU000SYN00001",
        "security_name": "Synthetic Equity One",
        "record_date": "15.01.2026",
        "quantity": "10",
        "per_unit": "1,15",
        "gross": "11,50",
        "gross_currency": "RUB",
        "d1": "12,00",
        "d2": "11,50",
        "tax_rate": "13",
        "tax": "1,50",
        "net": "10,00",
        "net_currency": "RUB",
        "payment_date": "20.01.2026",
        "beneficiary_account": "40817810100000000000",
        "beneficiary_bank": "SYNTHETIC BANK",
    }


def build_income_report_pdf(
    rows: list[dict[str, str]] | None = None,
    *,
    title: str = REPORT_TITLE,
    extra_lines: tuple[str, ...] = (),
    include_header: bool = True,
    header_rows: tuple[tuple[str, ...], ...] | None = None,
) -> bytes:
    payload_rows = rows if rows is not None else [_default_row()]
    fragments: list[tuple[float, float, str]] = [(40.0, 800.0, title)]
    y = 770.0
    for extra in extra_lines:
        fragments.append((40.0, y, extra))
        y -= 16.0
    if include_header:
        rows_for_header = header_rows or (REPORT_COLUMNS,)
        for header_row in rows_for_header:
            if len(header_row) != len(REPORT_COLUMNS):
                raise ValueError("synthetic header must match report column count")
            fragments.append((40.0, y, " | ".join(header_row)))
            y -= 18.0
    for index, raw in enumerate(payload_rows, start=1):
        merged = _default_row()
        merged["seq"] = str(index)
        merged.update(raw)
        cells = [merged.get(_column_key(column), "") for column in REPORT_COLUMNS]
        fragments.append((40.0, y, " | ".join(cells)))
        y -= 16.0
    return build_text_pdf([fragments])


def _layout_fragments(
    cells: tuple[str, ...], y: float, *, x_offset: float = 0.0
) -> list[tuple[float, float, str]]:
    if len(cells) != len(REPORT_COLUMNS):
        raise ValueError("synthetic layout row must match report column count")
    return [
        (LAYOUT_COLUMN_START + index * LAYOUT_COLUMN_STEP + x_offset, y, cell)
        for index, cell in enumerate(cells)
        if cell
    ]


def build_layout_income_report_pdf(
    rows: list[dict[str, str]] | None = None,
    *,
    title: str = REPORT_TITLE,
    header_rows: tuple[tuple[str, ...], ...],
) -> bytes:
    """Build a synthetic graphical-table text layer without pipe delimiters."""
    payload_rows = rows if rows is not None else [_default_row()]
    fragments: list[tuple[float, float, str]] = [(LAYOUT_COLUMN_START, 800.0, title)]
    y = 770.0
    for header_row in header_rows:
        fragments.extend(_layout_fragments(header_row, y))
        y -= 18.0
    for index, raw in enumerate(payload_rows, start=1):
        merged = _default_row()
        merged["seq"] = str(index)
        merged.update(raw)
        cells = tuple(merged.get(_column_key(column), "") for column in REPORT_COLUMNS)
        fragments.extend(_layout_fragments(cells, y))
        y -= 16.0
    return build_text_pdf([fragments], width=LAYOUT_PAGE_WIDTH)


def build_current_alfa_layout_income_report_pdf(
    rows: list[dict[str, str]] | None = None,
    *,
    title: str = REPORT_TITLE,
    header_rows: tuple[tuple[str, ...], ...] = CURRENT_ALFA_LAYOUT_HEADER,
    column_numbers: tuple[str, ...] | None = None,
    security_name_continuation: str | None = None,
    header_x_offsets: tuple[float, ...] | None = None,
) -> bytes:
    """Build the current five-line Alfa layout with its 21-column number row.

    This is wholly synthetic structural evidence. It deliberately uses no pipe
    delimiters, keeps sparse wrapped header lines, and optionally places a
    security-name-only continuation below a data row.
    """
    payload_rows = rows if rows is not None else [_default_row()]
    if len(header_rows) != 5:
        raise ValueError("current Alfa header must have five layout lines")
    offsets = header_x_offsets or (0.0,) * len(header_rows)
    if len(offsets) != len(header_rows):
        raise ValueError("current Alfa header offsets must match header line count")
    anchor = column_numbers or tuple(str(index) for index in range(1, 22))
    if len(anchor) != len(REPORT_COLUMNS):
        raise ValueError("synthetic column-number row must have 21 cells")

    fragments: list[tuple[float, float, str]] = [(LAYOUT_COLUMN_START, 800.0, title)]
    y = 770.0
    for header_row, x_offset in zip(header_rows, offsets, strict=True):
        fragments.extend(_layout_fragments(header_row, y, x_offset=x_offset))
        y -= 18.0
    fragments.extend(_layout_fragments(anchor, y))
    y -= 18.0
    for index, raw in enumerate(payload_rows, start=1):
        merged = _default_row()
        merged["seq"] = str(index)
        merged.update(raw)
        cells = tuple(merged.get(_column_key(column), "") for column in REPORT_COLUMNS)
        fragments.extend(_layout_fragments(cells, y))
        y -= 16.0
        if security_name_continuation:
            fragments.append(
                (LAYOUT_COLUMN_START + 6 * LAYOUT_COLUMN_STEP, y, security_name_continuation)
            )
            y -= 16.0
    return build_text_pdf([fragments], width=LAYOUT_PAGE_WIDTH)


def _column_key(column: str) -> str:
    for semantic, header in _SEMANTIC_TO_COLUMN.items():
        if header == column:
            return semantic
    raise KeyError(column)


def build_wrong_report_pdf() -> bytes:
    return build_text_pdf(
        [
            [
                (40.0, 800.0, "Инвестиционный отчёт"),
                (40.0, 760.0, "ISIN | Сумма | Дата"),
                (40.0, 740.0, "RU000SYN00001 | 10,00 | 20.01.2026"),
            ]
        ]
    )
