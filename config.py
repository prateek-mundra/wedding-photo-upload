"""
Centralized, typed configuration for the backend.

Loads from environment variables / a .env file. Using pydantic-settings
(instead of raw os.environ.get calls scattered across the codebase) gives
us validation at startup — the app fails fast with a clear error if a
required setting is missing, instead of failing later mid-request.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    app_base_url: str = "http://localhost:8000"
    max_upload_mb: int = 200

    google_oauth_credentials_file: str = Field(default="credentials.json", alias="GOOGLE_OAUTH_CREDENTIALS_FILE")
    google_oauth_token_file: str = Field(default="token.json", alias="GOOGLE_OAUTH_TOKEN_FILE")
    drive_root_folder_id: str = Field(default="", alias="DRIVE_ROOT_FOLDER_ID")

    # Simple shared-secret auth for the admin gallery. Guests never need this;
    # only you/photographer need it to view/list uploads.
    admin_token: str = Field(default="", alias="ADMIN_TOKEN", description="Set a real value in .env before deploying")

    allowed_origins: str = "*"  # comma-separated list in production, e.g. "https://photos.example.com"

    @property
    def allowed_origins_list(self) -> list[str]:
        if self.allowed_origins == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
