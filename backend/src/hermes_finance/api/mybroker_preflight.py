"""Ephemeral multi-original Preview; no Apply or ReportingMonth intent."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from sqlalchemy.orm import Session

from hermes_finance.api.mybroker_import import IdentityAccountBinding
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.mybroker_preflight import MAX_BATCH_BYTES, MAX_DOCUMENTS, preview_batch
from hermes_finance.statement_import.mybroker import MAX_BYTES, MyBrokerError

router = APIRouter(prefix="/api/mybroker-preflight", tags=["mybroker-preflight"])
MAX_HEADER_BYTES = 16 * 1024
MAX_INTENT_BYTES = 64 * 1024


class BatchIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_bindings: list[IdentityAccountBinding] = Field(default_factory=list, max_length=100)
    requested_from: date | None = None
    requested_to: date | None = None


class _MemoryUpload:
    """Streaming multipart callbacks with limits BEFORE any buffer extension.

    Do not use Request.form or UploadFile: Starlette may spool originals to disk
    before a route with those parameters gets a chance to enforce its bounds.
    """

    def __init__(self):
        self.originals = []
        self.intent = "{}"
        self.intent_seen = False
        self.file_count = 0
        self.file_bytes = 0
        self.complete = False

    def on_part_begin(self):
        self.headers = {}
        self.header_bytes = 0
        self.buffer = bytearray()
        self.filename = None

    def on_header_begin(self):
        self.header_name = bytearray()
        self.header_value = bytearray()

    def _header(self, target, data, start, end):
        self.header_bytes += end - start
        if self.header_bytes > MAX_HEADER_BYTES:
            raise HTTPException(413, "preflight_headers_too_large")
        target.extend(data[start:end])

    def on_header_field(self, data, start, end):
        self._header(self.header_name, data, start, end)

    def on_header_value(self, data, start, end):
        self._header(self.header_value, data, start, end)

    def on_header_end(self):
        name = bytes(self.header_name).lower()
        if name in self.headers:
            raise HTTPException(422, "preflight_multipart_invalid")
        self.headers[name] = bytes(self.header_value)

    def on_headers_finished(self):
        kind, options = parse_options_header(self.headers.get(b"content-disposition"))
        if kind != b"form-data":
            raise HTTPException(422, "preflight_multipart_invalid")
        name = options.get(b"name")
        if name == b"files" and b"filename" in options:
            self.file_count += 1
            if self.file_count > MAX_DOCUMENTS:
                raise HTTPException(422, "preflight_batch_size_invalid")
            self.filename = options[b"filename"].decode("utf-8")
        elif name == b"intent" and b"filename" not in options and not self.intent_seen:
            self.intent_seen = True
        else:
            raise HTTPException(422, "preflight_multipart_invalid")

    def on_part_data(self, data, start, end):
        size = end - start
        limit = MAX_BYTES if self.filename is not None else MAX_INTENT_BYTES
        if len(self.buffer) + size > limit:
            raise HTTPException(
                413,
                "document_size_invalid"
                if self.filename is not None
                else "preflight_intent_too_large",
            )
        if self.filename is not None:
            self.file_bytes += size
            if self.file_bytes > MAX_BATCH_BYTES:
                raise HTTPException(413, "document_size_invalid")
        self.buffer.extend(data[start:end])

    def on_part_end(self):
        if self.filename is None:
            self.intent = self.buffer.decode("utf-8")
        else:
            self.originals.append((self.filename, bytes(self.buffer)))
        self.buffer = bytearray()

    def on_end(self):
        self.complete = True


async def _read_upload(request: Request) -> _MemoryUpload:
    kind, options = parse_options_header(request.headers.get("content-type"))
    boundary = options.get(b"boundary", b"")
    if kind != b"multipart/form-data" or not 1 <= len(boundary) <= 200:
        raise HTTPException(422, "preflight_multipart_invalid")
    upload = _MemoryUpload()
    parser = MultipartParser(
        boundary,
        {
            name: getattr(upload, name)
            for name in (
                "on_part_begin",
                "on_header_begin",
                "on_header_field",
                "on_header_value",
                "on_header_end",
                "on_headers_finished",
                "on_part_data",
                "on_part_end",
                "on_end",
            )
        },
    )
    wire_limit = MAX_BATCH_BYTES + (MAX_DOCUMENTS + 1) * MAX_HEADER_BYTES + MAX_INTENT_BYTES + 2048
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            size = int(content_length)
        except ValueError:
            raise HTTPException(422, "preflight_multipart_invalid") from None
        if size < 0 or size > wire_limit:
            raise HTTPException(413, "document_size_invalid")
    wire_bytes = 0
    try:
        async for chunk in request.stream():
            wire_bytes += len(chunk)
            if wire_bytes > wire_limit:
                raise HTTPException(413, "document_size_invalid")
            for offset in range(0, len(chunk), 64 * 1024):
                parser.write(chunk[offset : offset + 64 * 1024])
        parser.finalize()
    except (UnicodeError, MultipartParseError, ValueError):
        raise HTTPException(422, "preflight_multipart_invalid") from None
    if not upload.complete:
        raise HTTPException(422, "preflight_multipart_invalid")
    if not upload.originals:
        raise HTTPException(422, "preflight_batch_size_invalid")
    return upload


@router.post(
    "/preview",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["files"],
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                                "maxItems": MAX_DOCUMENTS,
                            },
                            "intent": {"type": "string", "default": "{}"},
                        },
                    }
                }
            },
        }
    },
)
async def preview(request: Request, session: Session = Depends(session_for_request)):
    upload = await _read_upload(request)
    try:
        requested = BatchIntent.model_validate_json(upload.intent)
    except ValidationError:
        raise HTTPException(422, "preflight_intent_invalid") from None
    try:
        return preview_batch(
            session,
            originals=upload.originals,
            account_bindings=[b.model_dump() for b in requested.account_bindings],
            requested_from=requested.requested_from,
            requested_to=requested.requested_to,
        )
    except MyBrokerError as error:
        raise HTTPException(422, str(error)) from None
