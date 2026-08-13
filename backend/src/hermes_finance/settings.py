from pathlib import Path

from pydantic import Field, SecretStr, field_validator
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
    t_invest_read_only_token: SecretStr | None = None

    @field_validator("t_invest_read_only_token", mode="before")
    @classmethod
    def _empty_secret_is_missing(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value
