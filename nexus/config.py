"""Central configuration via environment variables (12-factor, no hard-coded secrets)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEXUS_", env_file=".env", extra="ignore")

    # Storage
    database_url: str = "sqlite:///./nexus.db"

    # Logging
    log_level: str = "INFO"
    log_file: str | None = None

    # Data provider: "demo" | "rpc"
    data_provider: str = "demo"
    rpc_url: str | None = None
    etherscan_api_key: str | None = None

    # LLM provider: echo | openai | anthropic | ollama
    llm_provider: str = "echo"
    llm_model: str | None = None

    # Alerts
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    alert_email_to: str | None = None
    slack_webhook_url: str | None = None

    # Artifacts
    artifacts_dir: str = "./artifacts"

    @property
    def artifacts_path(self) -> Path:
        p = Path(self.artifacts_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
