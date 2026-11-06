"""Synthetic tests for Windows sharing; never open Owner data."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_finance.services.uat_private_leaf import create_private_leaf


def test_handle_closed_if_transfer_is_interrupted(tmp_path: Path, monkeypatch):
    import ctypes

    class FakeCall:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    closed = []
    kernel = SimpleNamespace(
        CreateFileW=FakeCall(lambda *args: 42),
        CloseHandle=FakeCall(lambda handle: closed.append(handle) or 1),
    )
    runtime = SimpleNamespace(
        open_osfhandle=lambda *args: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "win32")
        patch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
        patch.setitem(sys.modules, "msvcrt", runtime)
        with pytest.raises(KeyboardInterrupt):
            create_private_leaf(tmp_path / "synthetic.db")
    assert closed == [42]


def test_non_windows_refuses(tmp_path: Path):
    if sys.platform == "win32":
        pytest.skip("requires non-Windows")
    with pytest.raises(OSError, match="Windows"):
        create_private_leaf(tmp_path / "synthetic.db")
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(sys.platform != "win32", reason="actual Windows file-sharing semantics")
def test_windows_denies_read_write_delete_and_never_overwrites(tmp_path: Path):
    target = tmp_path / "synthetic.db"
    fd = create_private_leaf(target)
    try:
        os.write(fd, b"synthetic")
        os.fsync(fd)
        for mode in ("rb", "r+b"):
            with pytest.raises(OSError):
                target.open(mode)
        with pytest.raises(OSError):
            target.unlink()
        with pytest.raises(OSError):
            create_private_leaf(target)
    finally:
        os.close(fd)
    assert target.read_bytes() == b"synthetic"
    with pytest.raises(OSError):
        create_private_leaf(target)
