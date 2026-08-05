from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL

from hermes_finance.database import create_database
from hermes_finance.settings import Settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The first revision is an Alembic service baseline. A later domain-model
# task will introduce declarative metadata together with the first schema.
target_metadata = None


def database_url() -> str:
    database_path = Settings().database_path.expanduser().resolve()
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
    database = create_database(Settings().database_path)
    try:
        with database.engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()
    finally:
        database.engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
