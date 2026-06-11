"""Application configuration loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All app configuration, read from .env file and environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Gemini AI ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash-lite"

    # --- Playwright ---
    playwright_headless: bool = True

    # --- Pinterest API ---
    pinterest_app_id: str = ""
    pinterest_app_secret: str = ""
    pinterest_access_token: str = ""
    pinterest_refresh_token: str = ""
    pinterest_board_id: str = ""

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Database ---
    database_url: str = "sqlite:///./pinterest_automation.db"

    # --- Storage ---
    downloads_dir: str = "./downloads"

    # --- Scheduling ---
    pins_per_day_min: int = 5
    pins_per_day_max: int = 15
    schedule_start_hour: int = 8
    schedule_end_hour: int = 22
    timezone: str = "Asia/Manila"

    # --- Compliance ---
    ftc_disclosure: str = "As an Amazon Associate I earn from qualifying purchases."

    # --- Server ---
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def downloads_path(self) -> Path:
        """Resolved absolute path for video downloads directory."""
        path = Path(self.downloads_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path.resolve()


# Singleton — import this everywhere
settings = Settings()
