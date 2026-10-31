from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from hermes_finance import __version__

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPOSITORY_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HERMES_FINANCE_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8-sig",
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
    reviewed_bond_valuation_path: Path | None = None
    returns_account_display_names: dict[str, str] = Field(default_factory=dict)
    t_invest_read_only_token: SecretStr | None = None

    @field_validator("host")
    @classmethod
    def validate_local_host(cls, value: str) -> str:
        if value != "127.0.0.1":
            raise ValueError("host must be exactly 127.0.0.1")
        return value

    @field_validator("returns_account_display_names")
    @classmethod
    def validate_return_labels(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            not key.startswith("source:")
            or len(key) <= 7
            or any(c.isspace() for c in key)
            or not label.strip()
            or len(label) > 80
            or any(ord(c) < 32 for c in label)
            for key, label in value.items()
        ):
            raise ValueError(
                "return display labels require exact source scopes and nonempty short labels"
            )
        return {key: label.strip() for key, label in value.items()}

    @field_validator("t_invest_read_only_token", mode="before")
    @classmethod
    def _empty_secret_is_missing(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value
