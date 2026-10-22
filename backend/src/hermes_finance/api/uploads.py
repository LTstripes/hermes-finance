"""Bounded multipart parsing before FastAPI resolves UploadFile dependencies.

Originals stay in memory. Limits apply before buffer writes even without a
Content-Length, and every buffer/file is released on failure or disconnect.
"""

from io import BytesIO

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from starlette.datastructures import FormData, Headers, UploadFile

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_FILES = 32
MAX_FIELDS = 32
MAX_FIELD_BYTES = 1024 * 1024
MAX_HEADER_BYTES = 16 * 1024
MAX_WIRE_BYTES = (
    MAX_TOTAL_BYTES
    + MAX_FIELDS * MAX_FIELD_BYTES
    + (MAX_FILES + MAX_FIELDS) * (MAX_HEADER_BYTES + 2048)
)


class _Multipart:
    def __init__(self):
        self.items = []
        self.files = 0
        self.fields = 0
        self.total = 0
        self.complete = False
        self.buffer = None

    def on_part_begin(self):
        self.headers = {}
        self.header_bytes = 0
        self.buffer = BytesIO()
        self.filename = None
        self.size = 0

    def on_header_begin(self):
        self.header_name = bytearray()
        self.header_value = bytearray()

    def _header(self, target, data, start, end):
        self.header_bytes += end - start
        if self.header_bytes > MAX_HEADER_BYTES:
            raise HTTPException(413, "upload_headers_too_large")
        target.extend(data[start:end])

    def on_header_field(self, data, start, end):
        self._header(self.header_name, data, start, end)

    def on_header_value(self, data, start, end):
        self._header(self.header_value, data, start, end)

    def on_header_end(self):
        name = bytes(self.header_name).lower()
        if name in self.headers or not name:
            raise HTTPException(422, "upload_multipart_invalid")
        self.headers[name] = bytes(self.header_value)

    def on_headers_finished(self):
        kind, options = parse_options_header(self.headers.get(b"content-disposition"))
        if kind != b"form-data" or not options.get(b"name"):
            raise HTTPException(422, "upload_multipart_invalid")
        self.name = options[b"name"].decode("utf-8")
        if b"filename" in options:
            self.filename = options[b"filename"].decode("utf-8")
            self.files += 1
            if self.files > MAX_FILES:
                raise HTTPException(413, "upload_file_count_exceeded")
        else:
            self.fields += 1
            if self.fields > MAX_FIELDS:
                raise HTTPException(413, "upload_field_count_exceeded")

    def on_part_data(self, data, start, end):
        size = end - start
        limit = MAX_FILE_BYTES if self.filename is not None else MAX_FIELD_BYTES
        if self.size + size > limit or self.total + size > MAX_TOTAL_BYTES:
            raise HTTPException(413, "document_size_invalid")
        self.size += size
        self.total += size
        self.buffer.write(data[start:end])

    def on_part_end(self):
        self.buffer.seek(0)
        if self.filename is None:
            value = self.buffer.read().decode("utf-8")
            self.buffer.close()
        else:
            value = UploadFile(
                self.buffer,
                size=self.size,
                filename=self.filename,
                headers=Headers(raw=list(self.headers.items())),
            )
        self.items.append((self.name, value))

    def on_end(self):
        self.complete = True

    def close(self):
        if self.buffer is not None:
            self.buffer.close()
        for _, value in self.items:
            if isinstance(value, UploadFile):
                value.file.close()


async def _read_form(request: Request) -> FormData:
    kind, options = parse_options_header(request.headers.get("content-type"))
    boundary = options.get(b"boundary", b"")
    if kind != b"multipart/form-data" or not 1 <= len(boundary) <= 200:
        raise HTTPException(422, "upload_multipart_invalid")
    lengths = request.headers.getlist("content-length")
    if lengths:
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal():
            raise HTTPException(422, "upload_multipart_invalid")
        if int(lengths[0]) > MAX_WIRE_BYTES:
            raise HTTPException(413, "document_size_invalid")
    upload = _Multipart()
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
    wire_bytes = 0
    try:
        async for chunk in request.stream():
            wire_bytes += len(chunk)
            if wire_bytes > MAX_WIRE_BYTES:
                raise HTTPException(413, "document_size_invalid")
            for offset in range(0, len(chunk), 64 * 1024):
                parser.write(chunk[offset : offset + 64 * 1024])
        parser.finalize()
        if not upload.complete:
            raise HTTPException(422, "upload_multipart_invalid")
        return FormData(upload.items)
    except (UnicodeError, ValueError, MultipartParseError):
        upload.close()
        raise HTTPException(422, "upload_multipart_invalid") from None
    except BaseException:
        upload.close()
        raise


class BoundedUploadRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request: Request):
            form = None
            try:
                if request.headers.get("content-type", "").lower().startswith("multipart/"):
                    form = await _read_form(request)
                    # Request.form() uses this cached FormData. FastAPI keeps its
                    # normal field validation and OpenAPI UploadFile contract.
                    request._form = form
                return await handler(request)
            finally:
                if form is not None:
                    await form.close()

        return bounded
