from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from hermes_finance.database import create_database

BACKEND_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_CONFIG_PATH = BACKEND_ROOT / "alembic.ini"


def _alembic_config(database_path: Path) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.attributes["database_path"] = str(database_path.expanduser().resolve())
    return config


def _database_heads(database_path: Path, config: Config) -> tuple[str, ...]:
    database = create_database(database_path)
    try:
        with database.engine.connect() as connection:
            current_heads = MigrationContext.configure(connection).get_current_heads()
    finally:
        database.engine.dispose()

    expected_heads = ScriptDirectory.from_config(config).get_heads()
    if tuple(current_heads) != tuple(expected_heads):
        raise RuntimeError(
            "Database schema is not at Alembic head: "
            f"current={current_heads!r}, expected={expected_heads!r}"
        )
    return tuple(current_heads)


def upgrade_database(database_path: Path) -> None:
    config = _alembic_config(database_path)
    command.upgrade(config, "head")
    _database_heads(database_path, config)
