"""Windows-only private file creation for a future isolated UAT handoff.

The descriptor must remain open while the caller depends on exclusivity. Closing
it relinquishes the protection. The caller must validate and pin the parent;
this primitive does not validate paths, prepare a copy, or start UAT.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def create_private_leaf(path: Path) -> int:
    """Create a new regular leaf with no read, write, or delete sharing."""
    if sys.platform != "win32":
        raise OSError("Windows file sharing is required")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000 | 0x40000000, 0, None, 1, 0x00200000, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_last_error(), "private file creation failed")
    try:
        return msvcrt.open_osfhandle(int(handle), os.O_RDWR | getattr(os, "O_BINARY", 0))
    except BaseException:
        close(handle)
        raise
