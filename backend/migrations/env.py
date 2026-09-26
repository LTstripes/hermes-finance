from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import URL

from hermes_finance.database import create_database
from hermes_finance.persistence import Base
from hermes_finance.settings import Settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    configured_path = config.attributes.get("database_path")
    database_path = Settings().database_path if configured_path is None else Path(configured_path)
    database_path = database_path.expanduser().resolve()
    return URL.create("sqlite+pysqlite", database=database_path.as_posix()).render_as_string(
        hide_password=False
    )


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configured_path = config.attributes.get("database_path")
    database_path = Settings().database_path if configured_path is None else Path(configured_path)
    database = create_database(database_path)
    try:
        with database.engine.connect() as connection:
            # SQLite batch table replacement temporarily drops referenced
            # parents. Scope FK suspension to this migration connection only;
            # validate the complete graph before committing and restore ON.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 0:
                raise RuntimeError("migration connection could not suspend SQLite FK checks")
            connection.commit()
            try:
                with connection.begin():
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                    context.configure(
                        connection=connection,
                        target_metadata=target_metadata,
                        transactional_ddl=True,
                    )
                    with context.begin_transaction():
                        context.run_migrations()
                    if connection.exec_driver_sql("PRAGMA foreign_key_check").all():
                        raise RuntimeError("migration left an invalid SQLite FK graph")
            finally:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
                    raise RuntimeError("migration connection could not restore SQLite FK checks")
    finally:
        database.engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
