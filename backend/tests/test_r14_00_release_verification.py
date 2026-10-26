"""Synthetic published 0058 -> current preservation; no Owner data or production restore."""

import hashlib
import sqlite3
import subprocess

import pytest
from _migration_helpers import BACKEND_ROOT, revision_rows
from test_r13_00_release_verification import (
    _assert_original_rows,
    _backup,
    _integrity,
    _seed_released_database,
    _snapshot,
    _upgrade,
)

PUBLISHED_HEAD = "0058_broker_money_ownership"
TRANSITION = (
    "0059_source_intake",
    "0060_source_money_classifications",
    "0061_money_instrument_links",
    "0062_security_reg_isin_mappings",
    "0063_intentional_empty_close",
    "0064_month_template_provenance",
    "0065_source_return_proofs",
    "0066_actual_payout_links",
)


def test_published_v13_migration_sources_remain_exact():
    # Independently derived from all 61 migration files in published v1.3.0,
    # peeled commit a9c88266fffe26e83688c52fc8f425b04fa14812, including README.
    paths = list((BACKEND_ROOT / "migrations").glob("*.*"))
    paths += [BACKEND_ROOT / "migrations" / "README"]
    paths += [
        p for p in (BACKEND_ROOT / "migrations" / "versions").glob("*.py") if int(p.name[:4]) <= 58
    ]
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.relative_to(BACKEND_ROOT.parent).as_posix()):
        name = path.relative_to(BACKEND_ROOT.parent).as_posix()
        digest.update(name.encode() + b"\0" + path.read_bytes().replace(b"\r\n", b"\n"))
    assert len(paths) == 61
    assert digest.hexdigest() == "9865c0e1929cfdee5bffab36e01b60cc09e07ac59b43b4383f1ba48e49b87213"


def test_recovery_graph_accepts_published_0058_to_selected_0062():
    from hermes_finance.services.recovery_rehearsal import _compatibility

    # This is a synthetic producer identity; work in shallow CI checkouts too.
    producer = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=BACKEND_ROOT.parent, text=True
    ).strip()
    proof = _compatibility(
        BACKEND_ROOT.parent,
        (PUBLISHED_HEAD,),
        producer,
    )
    assert proof.relationship == "forward_upgrade"
    assert proof.source_revisions == (PUBLISHED_HEAD,)
    assert proof.selected_heads == (TRANSITION[-1],)


@pytest.mark.parametrize("route", ["direct", "each_revision"])
def test_published_0058_upgrade_preserves_every_existing_row_and_recovery_pair(tmp_path, route):
    path = tmp_path / "synthetic-published.db"
    backup = tmp_path / "synthetic-online-backup.db"
    _seed_released_database(path)
    _upgrade(path, PUBLISHED_HEAD)
    with sqlite3.connect(path) as connection:
        before = _snapshot(connection)
    _backup(path, backup)
    for target in ["head"] if route == "direct" else TRANSITION:
        _upgrade(path, target)
        with sqlite3.connect(path) as connection:
            _integrity(connection)
            _assert_original_rows(connection, before)
    with sqlite3.connect(path) as connection:
        after = _snapshot(connection)
        assert set(after) > set(before)
        for table in set(after) - set(before):
            assert connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone() == (0,)
        assert connection.execute("SELECT status FROM reporting_months ORDER BY id").fetchall() == [
            ("closed",),
            ("draft",),
        ]
    _upgrade(path, "head")
    with sqlite3.connect(path) as connection:
        assert _snapshot(connection) == after
    # Online-backup readback is evidence for the old pair, never replacement of Stable.
    assert revision_rows(backup) == [PUBLISHED_HEAD]
    with sqlite3.connect(backup) as connection:
        _integrity(connection)
        assert _snapshot(connection) == before
    recovered = tmp_path / "synthetic-isolated-recovered.db"
    _backup(backup, recovered)
    _upgrade(recovered, "head")
    with sqlite3.connect(recovered) as connection:
        _integrity(connection)
        assert _snapshot(connection) == after
