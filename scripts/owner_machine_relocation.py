"""One same-volume Windows rename using the existing cleanup identity guards.

This primitive grants no relocation authority. Callers must enforce the exact
independently reviewed Owner package, approval, expiry, quiescence and rollback.
It never copies data, overwrites a destination, deletes a source or edits refs.
"""

import ctypes
import os
from ctypes import wintypes

import owner_workspace_cleanup as cleanup
import owner_workspace_inventory as inventory


class RelocationAfterMoveError(cleanup.Hold):
    """The native rename succeeded; its postcondition is not yet proven.

    Callers must treat the object as potentially moved and verify rollback,
    never report an unchanged source or a completed rollback from this error.
    """


def rename_bound(source, target, expected):
    source = inventory.absolute(str(source))
    target = inventory.absolute(str(target))
    if (
        source == target
        or inventory.within(source, target)
        or inventory.within(target, source)
    ):
        raise cleanup.Hold("overlapping_roots")
    inventory.plain(source, directory=True)
    inventory.plain(target.parent, directory=True)
    if source.stat().st_dev != target.parent.stat().st_dev:
        raise cleanup.Hold("cross_volume_unsupported")
    if os.name != "nt":
        raise cleanup.Hold("windows_apply_required")
    with cleanup.Pins() as pins:
        pins.ancestors(source)
        pins.ancestors(target)
        if cleanup.identity(inventory.plain(source)) != expected or target.exists():
            raise cleanup.Hold("path_changed")
        pins.pin(source, delete=True)
        if cleanup.identity(inventory.plain(source)) != expected:
            raise cleanup.Hold("path_changed")

        class RenameInfo(ctypes.Structure):
            _fields_ = [
                ("ReplaceIfExists", wintypes.BOOLEAN),
                ("RootDirectory", wintypes.HANDLE),
                ("FileNameLength", wintypes.DWORD),
                ("FileName", wintypes.WCHAR * 1),
            ]

        class IoStatus(ctypes.Structure):
            _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

        encoded = target.name.encode("utf-16-le")
        buffer = ctypes.create_string_buffer(
            RenameInfo.FileName.offset + len(encoded) + 2
        )
        info = ctypes.cast(buffer, ctypes.POINTER(RenameInfo)).contents
        info.ReplaceIfExists = False
        info.RootDirectory = pins.handles[target.parent]
        info.FileNameLength = len(encoded)
        ctypes.memmove(
            ctypes.addressof(buffer) + RenameInfo.FileName.offset, encoded, len(encoded)
        )
        api = ctypes.WinDLL("ntdll")
        api.NtSetInformationFile.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(IoStatus),
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.c_int,
        ]
        api.NtSetInformationFile.restype = ctypes.c_long
        status = api.NtSetInformationFile(
            pins.handles[source], ctypes.byref(IoStatus()), buffer, len(buffer), 10
        )
        if status < 0:
            raise cleanup.Hold("busy_or_inaccessible")
        try:
            if cleanup.identity(inventory.plain(target)) != expected or source.exists():
                raise cleanup.Hold("path_changed")
        except (cleanup.Hold, inventory.InventoryError, OSError) as error:
            raise RelocationAfterMoveError(
                "relocation_postcondition_unproven"
            ) from error
