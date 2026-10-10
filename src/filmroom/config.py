from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_parse_none_str="")

    data_dir: Path | None = None
    labels_path: Path | None = None
    holdout_path: Path | None = None
    cache_dir: Path = Path(".cache")
    fixtures_dir: Path = Path("fixtures")
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
