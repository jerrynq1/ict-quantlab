from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    admin_username: str = ""
    admin_password: str = ""
    session_secret: str = ""
    encryption_key: str = ""
    database_path: str = "./.data/ictql.sqlite3"
    # Full static site URL including the GitHub Pages project path, e.g.
    # https://owner.github.io/ict-quantlab/
    public_app_url: str = "http://localhost:3000/"
    cors_origins: list[str] = ["http://localhost:3000"]
    ctrader_token_url: str = "https://openapi.ctrader.com/apps/token"

    model_config = SettingsConfigDict(env_prefix="ICTQL_", env_file=".env", extra="ignore")


settings = Settings()
