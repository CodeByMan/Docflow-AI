from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated application, security, storage, and parser configuration."""

    app_name: str = "DocFlow-AI"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    deployment_mode: Literal["local", "hosted"] = "local"
    docflow_api_key: SecretStr | None = None

    database_url: str = "sqlite+aiosqlite:///./app.db"
    cors_allow_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    log_level: str = "INFO"
    request_id_header: str = "X-Request-ID"

    storage_dir: Path = Path("storage/uploads")
    max_upload_size_mb: int = Field(default=10, ge=1, le=100)
    max_extracted_text_chars: int = Field(default=500_000, ge=1_000, le=5_000_000)
    max_text_bytes: int = Field(default=2_000_000, ge=1_000, le=100_000_000)
    max_pdf_pages: int = Field(default=100, ge=1, le=5_000)
    max_office_uncompressed_bytes: int = Field(
        default=50_000_000, ge=100_000, le=500_000_000
    )
    max_office_compression_ratio: int = Field(default=100, ge=2, le=1_000)
    max_worksheets: int = Field(default=25, ge=1, le=1_000)
    max_rows: int = Field(default=20_000, ge=1, le=1_000_000)
    max_cells: int = Field(default=200_000, ge=1, le=10_000_000)
    allowed_extensions: str = ".txt,.md,.csv,.json,.pdf,.docx,.xlsx"

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.production"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        if self.cors_allow_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_allow_origins.split(",") if item.strip()]

    @property
    def hosts(self) -> list[str]:
        value = self.trusted_hosts.strip()
        if not value or value == "*":
            return ["*"]
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def extensions(self) -> set[str]:
        return {item.strip().lower() for item in self.allowed_extensions.split(",") if item.strip()}

    @property
    def upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @model_validator(mode="after")
    def validate_hosted_mode(self) -> Settings:
        if self.deployment_mode != "hosted":
            return self

        key = self.docflow_api_key.get_secret_value() if self.docflow_api_key else ""
        if len(key) < 32:
            raise ValueError("DOCFLOW_API_KEY must contain at least 32 characters in hosted mode")
        if self.cors_origins == ["*"]:
            raise ValueError("CORS_ALLOW_ORIGINS cannot be '*' in hosted mode")
        if self.hosts == ["*"]:
            raise ValueError("TRUSTED_HOSTS cannot be '*' in hosted mode")
        if self.database_url.startswith("sqlite"):
            raise ValueError("Hosted mode requires a PostgreSQL DATABASE_URL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configure_logging() -> None:
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    os.environ["TZ"] = "UTC"
