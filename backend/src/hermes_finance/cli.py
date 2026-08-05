import uvicorn

from hermes_finance.database import create_database
from hermes_finance.settings import Settings


def main() -> None:
    settings = Settings()
    database = create_database(settings.database_path)
    try:
        uvicorn.run(
            "hermes_finance.main:app",
            host=settings.host,
            port=settings.port,
            reload=settings.reload,
        )
    finally:
        database.engine.dispose()
