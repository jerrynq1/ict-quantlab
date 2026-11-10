from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", env_prefix="ICTQL_", extra="ignore")

    app_name: str = "ICT QuantLab API"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_path: str = "./data/ict_quantlab.sqlite3"
    encryption_key: str = ""
    session_secret: str = ""
    admin_username: str = "admin"
    admin_password: str = ""
    session_ttl_hours: int = 12
    public_app_url: str = "http://localhost:5500"
    public_api_url: str = ""
    cors_origins: str = "http://localhost:5500,http://127.0.0.1:5500"
    trusted_hosts: str = "*"
    max_bars_per_symbol: int = 2_000_000

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip().rstrip("/") for x in self.cors_origins.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
