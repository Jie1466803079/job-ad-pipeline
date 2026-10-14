"""Settings from environment variables, and from .env when running locally."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
DEFAULT_WEB_DIR = Path(__file__).resolve().parents[2] / "web" / "dist"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://jobpipe:jobpipe@127.0.0.1:5433/jobpipe"
    machine_api_key: str | None = None
    session_secret: str | None = None
    session_cookie_secure: bool = False
    config_dir: str = str(DEFAULT_CONFIG_DIR)
    web_dir: str = str(DEFAULT_WEB_DIR)
    llm_provider: Literal["gemini", "claude", "fake"] = "fake"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    gemini_thinking_level: str | None = None
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "low"
    review_url: str = "http://127.0.0.1:8000"
    webhook_secret: str | None = None
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_secure: bool = False

    @property
    def config_path(self) -> Path:
        return Path(self.config_dir)
