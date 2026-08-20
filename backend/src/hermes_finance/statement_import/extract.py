"""Bounded PDF text-layer extraction. OCR is out of scope.

Does not persist bytes or extracted text. Does not open a network.
"""

from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from hermes_finance.statement_import.dto import (
    ExtractedDocument,
    ExtractedPage,
    ExtractStatus,
)
from hermes_finance.statement_import.identity import document_sha256
from hermes_finance.statement_import.schema import (
    REASON_ENCRYPTED,
    REASON_EXTRACT_BOUNDED,
    REASON_NO_TEXT,
    REASON_TOO_LARGE,
    REASON_TOO_MANY_PAGES,
    REASON_UNREADABLE,
)

MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_PDF_PAGES = 40
MAX_EXTRACT_CHARS = 400_000
MAX_LINE_LENGTH = 4_000


def _empty(
    *,
    digest: str,
    status: ExtractStatus,
    reason: str,
    page_count: int = 0,
) -> ExtractedDocument:
    return ExtractedDocument(
        status=status,
        document_sha256=digest,
        page_count=page_count,
        pages=(),
        reason=reason,
    )


def extract_pdf_text_layer(document: bytes) -> ExtractedDocument:
    if not isinstance(document, (bytes, bytearray)):
        raise TypeError("document must be bytes")
    payload = bytes(document)
    digest = document_sha256(payload)
    if len(payload) > MAX_PDF_BYTES:
        return _empty(digest=digest, status=ExtractStatus.TOO_LARGE, reason=REASON_TOO_LARGE)
    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
    except (PdfReadError, OSError, ValueError):
        return _empty(digest=digest, status=ExtractStatus.UNREADABLE, reason=REASON_UNREADABLE)
    if getattr(reader, "is_encrypted", False):
        return _empty(digest=digest, status=ExtractStatus.ENCRYPTED, reason=REASON_ENCRYPTED)
    try:
        page_count = len(reader.pages)
    except (PdfReadError, OSError, ValueError):
        return _empty(digest=digest, status=ExtractStatus.UNREADABLE, reason=REASON_UNREADABLE)
    if page_count > MAX_PDF_PAGES:
        return _empty(
            digest=digest,
            status=ExtractStatus.TOO_MANY_PAGES,
            reason=REASON_TOO_MANY_PAGES,
            page_count=page_count,
        )
    pages: list[ExtractedPage] = []
    total_chars = 0
    any_text = False
    try:
        for page in reader.pages:
            try:
                raw = page.extract_text(extraction_mode="layout") or ""
            except (PdfReadError, OSError, ValueError, TypeError, KeyError):
                try:
                    raw = page.extract_text() or ""
                except (PdfReadError, OSError, ValueError, TypeError, KeyError):
                    raw = ""
            if total_chars + len(raw) > MAX_EXTRACT_CHARS:
                return _empty(
                    digest=digest,
                    status=ExtractStatus.EXTRACT_BOUNDED,
                    reason=REASON_EXTRACT_BOUNDED,
                    page_count=page_count,
                )
            total_chars += len(raw)
            lines: list[str] = []
            for line in raw.splitlines():
                clipped = line[:MAX_LINE_LENGTH]
                if clipped.strip():
                    any_text = True
                lines.append(clipped)
            pages.append(ExtractedPage(lines=tuple(lines)))
    except (PdfReadError, OSError, ValueError):
        return _empty(digest=digest, status=ExtractStatus.UNREADABLE, reason=REASON_UNREADABLE)
    if not any_text:
        return ExtractedDocument(
            status=ExtractStatus.NO_TEXT_LAYER,
            document_sha256=digest,
            page_count=page_count,
            pages=tuple(pages),
            reason=REASON_NO_TEXT,
        )
    return ExtractedDocument(
        status=ExtractStatus.OK,
        document_sha256=digest,
        page_count=page_count,
        pages=tuple(pages),
        reason=None,
    )
