from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_parse_none_str="")

    data_dir: Path | None = None
    labels_path: Path | None = None
    holdout_path: Path | None = None
    cache_dir: Path = Path(".cache")
    fixtures_dir: Path = Path("fixtures")
    store: Literal["fixtures", "engine", "database"] = "fixtures"
    database_url: SecretStr | None = None
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    mistral_api_key: SecretStr | None = None
    mistral_chat_model: str = "mistral-small-2603"
    mcp_url: str = "http://127.0.0.1:8000/mcp"
    llm_daily_token_limit: int = 1_500_000
    narrator_concurrency: int = 2
