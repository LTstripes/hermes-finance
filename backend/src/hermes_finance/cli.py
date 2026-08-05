import uvicorn

from hermes_finance.database import create_database
from hermes_finance.main import app
from hermes_finance.settings import Settings


def main() -> None:
    settings = Settings()
    database = create_database(settings.database_path)
    try:
        app.state.database = database
        uvicorn.run(
            "hermes_finance.main:app",
            host=settings.host,
            port=settings.port,
            reload=settings.reload,
        )
    finally:
        database.engine.dispose()
