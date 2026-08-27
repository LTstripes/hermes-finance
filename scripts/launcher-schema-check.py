"""Read-only SQLite/Alembic compatibility probe used by the Windows launcher."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import RangeNotAncestorError


def result(status: str, message: str) -> int:
    print(json.dumps({"status": status, "message": message}, ensure_ascii=False))
    return 0


def revision_is_ancestor(script: ScriptDirectory, current: str, heads: tuple[str, ...]) -> bool:
    for head in heads:
        try:
            if any(
                revision.revision == current for revision in script.iterate_revisions(head, current)
            ):
                return True
        except RangeNotAncestorError:
            continue
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    database = args.database.resolve()
    if not database.is_file():
        return result("missing", "database file is missing")

    try:
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        with connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                return result("invalid", "SQLite integrity_check did not return ok")
            rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    except sqlite3.Error as error:
        return result("invalid", f"SQLite cannot be read: {error}")

    current = tuple(row[0] for row in rows)
    config = Config(str(Path(__file__).resolve().parents[1] / "backend" / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = tuple(script.get_heads())
    if not current:
        return result(
            "behind", "database has no Alembic revision and may be upgraded by guarded startup"
        )
    if any(script.get_revision(revision) is None for revision in current):
        return result("unknown", "database revision is unknown to this checkout")
    if tuple(current) == heads:
        return result("at_head", "database schema is at this checkout's Alembic head")
    if all(revision_is_ancestor(script, revision, heads) for revision in current):
        return result(
            "behind",
            "database schema is behind this checkout and may be upgraded by guarded startup",
        )
    return result("ahead", "database was migrated by different or newer code")


if __name__ == "__main__":
    sys.exit(main())
