"""Resource budgets checked before opening any archive member."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile


def read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        if path.stat().st_size > limit:
            raise ValueError("archive input size limit exceeded")
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("archive input size limit exceeded")
    return payload


def validate_members(
    archive: ZipFile,
    *,
    max_members: int,
    max_member: int,
    max_total: int,
    stored_only: bool = False,
    max_ratio: int = 1000,
) -> None:
    members = archive.infolist()
    if len(members) > max_members or len({item.filename for item in members}) != len(members):
        raise ValueError("archive member count or duplicate limit exceeded")
    total = 0
    for item in members:
        total += item.file_size
        allowed = (ZIP_STORED,) if stored_only else (ZIP_STORED, ZIP_DEFLATED)
        if (
            item.compress_type not in allowed
            or item.flag_bits & 1
            or item.file_size < 0
            or item.compress_size < 0
            or item.file_size > max_member
            or total > max_total
            or item.file_size > max(1, item.compress_size) * max_ratio
            or (item.compress_type == ZIP_STORED and item.compress_size != item.file_size)
        ):
            raise ValueError("archive member resource budget exceeded")


def read_member(archive: ZipFile, name: str, limit: int) -> bytes:
    with archive.open(name) as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("archive member size limit exceeded")
    return payload
