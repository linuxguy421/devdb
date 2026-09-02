from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "DevDB"
    DEBUG: bool = False

    # No default: a real secret must come from the environment/.env. A
    # startup crash here is intentional -- it beats silently signing every
    # session with a value that's sitting in public source control.
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Set true once the app is served over HTTPS (e.g. behind a reverse
    # proxy doing TLS termination) so the session cookie is never sent in
    # the clear. Defaults false to match plain-HTTP LAN/local deployments.
    COOKIE_SECURE: bool = False

    # Database configuration defaults to asyncpg. docker-compose.yml
    # supplies the real value; this is only a fallback for running outside
    # Docker.
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/devdb"

    # TMDB API configuration
    TMDB_API_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
