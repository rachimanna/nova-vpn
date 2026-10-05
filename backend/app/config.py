"""Application settings. Every secret comes from environment variables / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # Telegram
    bot_token: str = ""
    webapp_url: str = ""  # public HTTPS URL of the Mini App
    initdata_max_age: int = 86400  # seconds

    # Storage
    database_url: str = "sqlite+aiosqlite:///./nova.db"

    # Secrets
    secret_key: str = ""  # signs admin sessions and download links
    encryption_key: str = ""  # Fernet key for client private keys
    admin_password: str = ""
    admin_telegram_ids: str = ""  # comma separated, get /admin link in bot

    # Behaviour
    dev_mode: bool = False  # allows X-Dev-User auth and mock data. NEVER in production
    cors_origins: str = ""  # comma separated, only if frontend is on another origin
    frontend_dist: str = "../frontend/dist"

    # Limits for new users
    default_device_limit: int = 3
    default_traffic_limit_gb: float = 50
    default_access_days: int = 30

    # Background jobs / API protection
    poll_interval: int = 60
    rate_limit_per_minute: int = 90
    online_threshold_seconds: int = 180

    @property
    def admin_ids(self) -> set[int]:
        return {int(x) for x in self.admin_telegram_ids.replace(" ", "").split(",") if x}

    @property
    def cors_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
