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

settings = Settings()
