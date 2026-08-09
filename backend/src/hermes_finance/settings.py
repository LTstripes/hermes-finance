from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from hermes_finance import __version__

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HERMES_FINANCE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Hermes Finance API"
    app_version: str = __version__
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    reload: bool = False
    database_path: Path = REPOSITORY_ROOT / "data" / "finance.db"
    frontend_dist: Path = REPOSITORY_ROOT / "frontend" / "dist"
