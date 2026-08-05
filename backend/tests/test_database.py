from pathlib import Path
from tempfile import TemporaryDirectory

from hermes_finance.database import create_database


def test_database_uses_temporary_file_and_session_factory() -> None:
    with TemporaryDirectory() as temporary_directory:
        temporary_root = Path(temporary_directory)
        database_path = temporary_root / "nested-data" / "synthetic-finance.db"

        database = create_database(database_path)
        try:
            assert database_path.parent.is_dir()
            with database.session_factory() as session:
                result = session.connection().exec_driver_sql("SELECT 1").scalar_one()
            assert result == 1
            assert database_path.is_file()
        finally:
            database.engine.dispose()

    assert not temporary_root.exists()


def test_database_enables_sqlite_foreign_keys() -> None:
    with TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "foreign-keys.db"
        database = create_database(database_path)
        try:
            with database.engine.connect() as connection:
                foreign_keys_enabled = connection.exec_driver_sql(
                    "PRAGMA foreign_keys"
                ).scalar_one()
        finally:
            database.engine.dispose()

    assert foreign_keys_enabled == 1
