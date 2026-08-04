import uvicorn

from hermes_finance.settings import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "hermes_finance.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )
