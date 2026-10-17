from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator


class Settings(BaseSettings):
    PROJECT_NAME: str = "DevDB"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    COOKIE_SECURE: bool = False
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/devdb"
    TMDB_API_KEY: str = ""

    # Comma-separated usernames promoted to admin on next successful login
    ADMIN_USERNAMES: str = ""

    # Single username that is always admin and can never be demoted
    SUPER_ADMIN: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.ENVIRONMENT.strip().lower() == "production" and not self.COOKIE_SECURE:
            raise ValueError("COOKIE_SECURE must be true when ENVIRONMENT=production")
        if self.ENVIRONMENT.strip().lower() == "production" and self.DEBUG:
            raise ValueError("DEBUG must be false when ENVIRONMENT=production")
        return self

    @property
    def admin_username_set(self) -> set[str]:
        return {
            name.strip().casefold()
            for name in self.ADMIN_USERNAMES.split(",")
            if name.strip()
        }

    @property
    def super_admin_username(self) -> str | None:
        name = (self.SUPER_ADMIN or "").strip()
        return name.casefold() if name else None

    def is_super_admin(self, username: str | None) -> bool:
        if not username or not self.super_admin_username:
            return False
        return username.strip().casefold() == self.super_admin_username


settings = Settings()
