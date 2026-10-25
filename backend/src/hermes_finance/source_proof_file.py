"""Read-only physical DB incarnation for source proof; no path or mtime authority."""

import ctypes
import hashlib
import os
import stat
import sys
from pathlib import Path


def file_incarnation(path: Path) -> str | None:
    """Require file ID AND birth time: reused inode numbers cannot revive proof.

    Supported restore replaces/creates a file under maintenance admission. A
    pooled connection is separately stamped at connect and compared on reads.
    Missing birth-time capability fails closed, never falls back to mtime/ctime.
    """
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not info.st_ino:
            return None
        birth = getattr(info, "st_birthtime_ns", None)
        if birth is None and sys.platform.startswith("linux"):
            library = ctypes.CDLL(None, use_errno=True)
            call = library.statx
            call.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_void_p,
            ]
            call.restype = ctypes.c_int
            result = ctypes.create_string_buffer(256)
            # AT_EMPTY_PATH on our opened fd; STATX_BTIME must actually be returned.
            if call(descriptor, b"", 0x1000, 0x800, result) != 0:
                return None
            data = result.raw
            if not int.from_bytes(data[:4], sys.byteorder) & 0x800:
                return None
            seconds = int.from_bytes(data[80:88], sys.byteorder, signed=True)
            nanos = int.from_bytes(data[88:92], sys.byteorder)
            birth = seconds * 1_000_000_000 + nanos
        if birth is None or birth <= 0:
            return None
        current = path.stat()
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            return None
        return hashlib.sha256(f"{info.st_dev}:{info.st_ino}:{birth}".encode()).hexdigest()
    except (OSError, AttributeError, ValueError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
