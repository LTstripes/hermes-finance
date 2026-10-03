"""Windows identity-bound move/rollback checks with synthetic data only."""

import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import owner_machine_relocation as relocation  # noqa: E402
import owner_workspace_cleanup as cleanup  # noqa: E402

pytestmark = [
    pytest.mark.ci_runtime_release,
    pytest.mark.skipif(os.name != "nt", reason="Windows handles required"),
]


def test_failure_after_move_and_reference_update_rolls_back(tmp_path):
    source = tmp_path / "old"
    target = tmp_path / "new"
    source.mkdir()
    database = source / "synthetic.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE synthetic (id INTEGER PRIMARY KEY)")
    connection.close()
    before = database.read_bytes()
    reference = tmp_path / "reference.txt"
    reference.write_text(str(source))
    original = reference.read_bytes()
    identity = cleanup.identity(source.stat())
    relocation.rename_bound(source, target, identity)
    reference.write_text(str(target))
    # Inject readiness failure after both changes. Restore references before
    # reversing the SAME directory identity; never restore a DB over live work.
    reference.write_bytes(original)
    relocation.rename_bound(target, source, identity)
    assert cleanup.identity(source.stat()) == identity
    assert (source / database.name).read_bytes() == before
    assert reference.read_bytes() == original
    assert not target.exists()


def test_existing_destination_and_wrong_identity_never_move(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    identity = cleanup.identity(source.stat())
    with pytest.raises(cleanup.Hold, match="path_changed"):
        relocation.rename_bound(source, target, identity)
    with pytest.raises(cleanup.Hold, match="path_changed"):
        relocation.rename_bound(source, tmp_path / "absent", [0] * 6)
    assert source.is_dir() and target.is_dir()


def test_busy_database_keeps_original_directory(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    connection = sqlite3.connect(source / "synthetic.sqlite3")
    try:
        connection.execute("CREATE TABLE synthetic (id INTEGER PRIMARY KEY)")
        connection.commit()
        identity = cleanup.identity(source.stat())
        with pytest.raises(cleanup.Hold, match="busy_or_inaccessible"):
            relocation.rename_bound(source, tmp_path / "target", identity)
        assert source.is_dir()
        assert not (tmp_path / "target").exists()
    finally:
        connection.close()


def test_cross_parent_rename_and_reverse_preserve_nested_files(tmp_path):
    before_parent = tmp_path / "before"
    after_parent = tmp_path / "after"
    before_parent.mkdir()
    after_parent.mkdir()
    source = before_parent / "runtime"
    target = after_parent / "runtime"
    source.mkdir()
    nested = source / "data"
    nested.mkdir()
    (nested / "synthetic.txt").write_bytes(b"synthetic-only")
    identity = cleanup.identity(source.stat())
    relocation.rename_bound(source, target, identity)
    assert (target / "data" / "synthetic.txt").read_bytes() == b"synthetic-only"
    relocation.rename_bound(target, source, identity)
    assert cleanup.identity(source.stat()) == identity
    assert (nested / "synthetic.txt").read_bytes() == b"synthetic-only"
