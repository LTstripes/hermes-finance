"""Retained synthetic 1.1/1.2 (shared 0044 schema) -> current-head compatibility.

Released migrations 0001-0044 are unchanged in both tags and the pinned baseline;
see docs/release-preparation-1.3.0.md for exact source identities. No Owner DB.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tomllib
from pathlib import Path

import pytest
from _migration_helpers import BACKEND_ROOT, REVISION, revision_rows, run_alembic
from alembic.config import Config
from alembic.script import ScriptDirectory

RELEASED_HEAD = "0044_observed_valuation_material_signature"


def test_released_migration_sources_are_exact_v11_v12_shared_chain():
    paths = sorted((BACKEND_ROOT / "migrations").glob("*.*"))
    paths += [BACKEND_ROOT / "migrations" / "README"]
    paths += [
        p for p in (BACKEND_ROOT / "migrations" / "versions").glob("*.py") if int(p.name[:4]) <= 44
    ]
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.relative_to(BACKEND_ROOT.parent).as_posix()):
        name = path.relative_to(BACKEND_ROOT.parent).as_posix()
        digest.update(name.encode() + b"\0" + path.read_bytes().replace(b"\r\n", b"\n"))
    assert len(paths) == 47
    assert digest.hexdigest() == "154be96b42969e9eb56397476f4a38ca88a585b1f2f9f2e089c4e67a0fdc00c2"


def _upgrade(path: Path, target: str) -> None:
    result = run_alembic(path, "upgrade", target)
    assert result.returncode == 0, result.stderr
    assert revision_rows(path) == [REVISION if target == "head" else target]


def _seed_released_database(path: Path) -> None:
    _upgrade(path, RELEASED_HEAD)
    with sqlite3.connect(path) as c:
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("INSERT INTO accounts(id,name,account_type) VALUES(1,'Synthetic','brokerage')")
        c.execute("INSERT INTO instruments(id,name,instrument_type) VALUES(1,'Synthetic','bond')")
        for month, status in ((1, "closed"), (2, "draft")):
            c.execute(
                "INSERT INTO reporting_months(id,year,month,period_start,period_end,"
                "snapshot_date,status,source,created_at,updated_at) "
                "VALUES(?,2030,?,?,?,?,?,'manual',"
                "'2030-02-01','2030-02-01')",
                (
                    month,
                    month,
                    f"2030-{month:02d}-01",
                    f"2030-{month:02d}-{'31' if month == 1 else '28'}",
                    f"2030-{month:02d}-{'31' if month == 1 else '28'}",
                    status,
                ),
            )
            # Preserve deliberately non-price-derived totals, exact minor units,
            # unknown NKD and both CLOSED/DRAFT. Never recalculate during upgrade.
            c.execute(
                "INSERT INTO position_snapshots(id,reporting_month_id,account_id,instrument_id,"
                "quantity,average_cost_per_unit_kopecks,market_price_per_unit_kopecks,"
                "market_value_kopecks,cost_basis_kopecks,unrealized_result_kopecks,"
                "price_date,updated_at) VALUES(?,?,1,1,3,123,124,373,369,4,"
                "'2030-01-31','2030-02-01')",
                (month, month),
            )
            c.execute(
                "INSERT INTO investment_cash_flows(id,reporting_month_id,account_id,"
                "instrument_id,flow_type,event_date,gross_amount_kopecks,tax_amount_kopecks,"
                "commission_amount_kopecks,net_amount_kopecks,source) "
                "VALUES(?,?,1,1,'coupon','2030-01-15',100,13,0,87,'manual')",
                (month, month),
            )
        c.execute(
            "INSERT INTO applied_statement_events(id,provider,account_id,instrument_id,"
            "event_kind,isin,record_date,natural_identity,material_fingerprint,"
            "investment_cash_flow_id,document_sha256,link_mode,created_at,updated_at) "
            "VALUES(1,'alfa_depository_income_report',1,1,'coupon','RU000SYN0001',"
            "'2030-01-15','synthetic-coupon',?,1,?,'linked_existing',"
            "'2030-02-01','2030-02-01')",
            ("a" * 64, "b" * 64),
        )
        c.execute(
            "INSERT INTO broker_baseline_applies(id,provider,reporting_month_id,baseline_date,"
            "source_as_of,captured_at,confirmed_at,apply_fingerprint) "
            "VALUES(1,'synthetic',1,'2030-01-31','2030-01-31','2030-02-01','2030-02-01',?)",
            ("c" * 64,),
        )
        _integrity(c)


def _snapshot(c: sqlite3.Connection) -> dict:
    """Keep every original table/column/row, including empty evidence tables."""
    result = {}
    for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        if table.startswith("sqlite_") or table == "alembic_version":
            continue
        columns = [r[1] for r in c.execute(f'PRAGMA table_info("{table}")')]
        rows = c.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
        result[table] = (columns, rows)
    return result


def _assert_original_rows(c: sqlite3.Connection, before: dict) -> None:
    for table, (columns, rows) in before.items():
        projection = ",".join(f'"{column}"' for column in columns)
        assert c.execute(f'SELECT {projection} FROM "{table}" ORDER BY rowid').fetchall() == rows


def _integrity(c: sqlite3.Connection) -> None:
    assert c.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def _backup(source: Path, destination: Path) -> None:
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        _integrity(dst)


@pytest.mark.parametrize("route", ["direct", "each_revision"])
def test_released_0044_upgrade_preserves_closed_provenance_and_duplicates(tmp_path, route):
    path = tmp_path / "synthetic-released.db"
    backup = tmp_path / "synthetic-backup.db"
    _seed_released_database(path)
    with sqlite3.connect(path) as c:
        before = _snapshot(c)
    _backup(path, backup)

    scripts = ScriptDirectory.from_config(Config(str(BACKEND_ROOT / "alembic.ini")))
    revisions = list(reversed(list(scripts.iterate_revisions(REVISION, RELEASED_HEAD))))
    assert [int(r.revision[:4]) for r in revisions] == list(range(45, 68))
    for target in ["head"] if route == "direct" else [r.revision for r in revisions]:
        _upgrade(path, target)
        with sqlite3.connect(path) as c:
            _integrity(c)
            _assert_original_rows(c, before)

    with sqlite3.connect(path) as c:
        _assert_original_rows(c, before)
        assert c.execute(
            "SELECT historical_instrument_type FROM position_snapshots"
        ).fetchall() == [(None,), (None,)]
        assert c.execute("SELECT bond_nkd_basis FROM position_snapshots").fetchall() == [
            ("unknown",),
            ("unknown",),
        ]
        new_tables = set(_snapshot(c)) - set(before)
        assert {"mybroker_imports", "broker_month_applies", "broker_money_occurrence_owners"} <= (
            new_tables
        )
        for table in new_tables:
            assert c.execute(f'SELECT count(*) FROM "{table}"').fetchone() == (0,)
        after = _snapshot(c)
        # Existing uniqueness still rejects duplicate financial identities.
        for table in ("reporting_months", "position_snapshots", "applied_statement_events"):
            columns = [r[1] for r in c.execute(f'PRAGMA table_info("{table}")') if r[1] != "id"]
            projection = ",".join(f'"{column}"' for column in columns)
            with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint"):
                c.execute(
                    f'INSERT INTO "{table}" ({projection}) '
                    f'SELECT {projection} FROM "{table}" WHERE id=1'
                )
            c.rollback()
        assert _snapshot(c) == after
    _upgrade(path, "head")
    with sqlite3.connect(path) as c:
        assert _snapshot(c) == after
        _integrity(c)

    # Recovery is a separate consistent copy, never a lossy downgrade.
    restored = tmp_path / "synthetic-restored.db"
    _backup(backup, restored)
    assert revision_rows(restored) == [RELEASED_HEAD]
    with sqlite3.connect(restored) as c:
        assert _snapshot(c) == before
    _upgrade(restored, "head")
    with sqlite3.connect(restored) as c:
        assert _snapshot(c) == after


@pytest.mark.parametrize("failure", ["ddl_collision", "invalid_fk"])
def test_released_upgrade_failure_rolls_back_schema_and_backup_remains_recoverable(
    tmp_path, failure
):
    path = tmp_path / "synthetic-failure.db"
    backup = tmp_path / "synthetic-backup.db"
    _seed_released_database(path)
    _backup(path, backup)
    with sqlite3.connect(path) as c:
        if failure == "ddl_collision":
            c.execute("CREATE TABLE mybroker_imports (synthetic_collision INTEGER)")
        else:
            c.execute("PRAGMA foreign_keys=OFF")
            c.execute("UPDATE investment_cash_flows SET account_id=999 WHERE id=1")
        c.commit()
        before = _snapshot(c)
        schema = c.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    failed = run_alembic(path, "upgrade", "head")
    assert failed.returncode != 0
    assert (
        "already exists" if failure == "ddl_collision" else "0066_foreign_key_check_failed"
    ) in (failed.stderr)
    assert revision_rows(path) == [RELEASED_HEAD]
    with sqlite3.connect(path) as c:
        assert _snapshot(c) == before
        assert c.execute(
            "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
        ).fetchall() == (schema)
    restored = tmp_path / "synthetic-restored.db"
    _backup(backup, restored)
    _upgrade(restored, "head")
    with sqlite3.connect(restored) as c:
        _integrity(c)


def test_release_identity_agrees_with_locked_package_and_health_version():
    from hermes_finance import __version__

    project = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((BACKEND_ROOT / "uv.lock").read_text(encoding="utf-8"))
    package = next(p for p in lock["package"] if p["name"] == project["project"]["name"])
    assert project["project"]["version"] == package["version"] == __version__ == "1.7.1"

    frontend = BACKEND_ROOT.parent / "frontend"
    manifest = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
    npm_lock = json.loads((frontend / "package-lock.json").read_text(encoding="utf-8"))
    assert (
        manifest["version"]
        == npm_lock["version"]
        == npm_lock["packages"][""]["version"]
        == __version__
    )
    notes = BACKEND_ROOT.parent / "docs" / f"release-notes-{__version__}.md"
    assert notes.is_file() and notes.stat().st_size > 0
