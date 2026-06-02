from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "CarFast v2"
    app_env: str = "local"
    app_secret_key: str = Field(default="change-me")
    database_url: str = "postgresql+psycopg://carfast:carfast@localhost:5432/carfast_v2"

    @property
    def enable_docs(self) -> bool:
        return self.app_env.lower() in {"local", "dev", "development"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

