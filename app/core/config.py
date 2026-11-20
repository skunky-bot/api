from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SkunkScrape API"
    app_env: str = "development"
    api_v1_prefix: str = ""
    secret_key: str = "change-this-to-a-long-random-secret"
    access_token_expire_minutes: int = 1440
    cors_origins: list[str] = [
        "https://skunkscrape.com",
        "https://www.skunkscrape.com",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    database_url: str = "sqlite:///./skunkscrape_api.db"
    collector_enabled: bool = Field(default=False, validation_alias="SKUNKY_COLLECTOR_ENABLED")

    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "change-me-now"
    bootstrap_admin_email: str = "admin@skunkscrape.com"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def reject_production_example_credentials(self):
        if self.app_env.casefold() in {"production", "prod"}:
            if len(self.secret_key) < 32 or self.secret_key.startswith("change-"):
                raise ValueError("Production SECRET_KEY must be a strong, non-example value")
            if len(self.bootstrap_admin_password) < 16 or self.bootstrap_admin_password == "change-me-now":
                raise ValueError("Production bootstrap administrator password must be configured securely")
            if self.bootstrap_admin_username == "admin":
                raise ValueError("Production bootstrap administrator username must be configured")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
