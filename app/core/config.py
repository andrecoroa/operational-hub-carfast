from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Operational Hub Carfast"
    app_env: str = "local"
    app_secret_key: str = Field(default="change-me")
    integration_api_key: str | None = None
    database_url: str = "postgresql+psycopg://carfast:carfast@localhost:5432/carfast_v2"
    document_archive_root: str | None = None
    document_invoice_inbox_path: str | None = None
    vehicle_sale_media_root: str | None = None
    vehicle_sales_public_base_url: str | None = None
    email_inbound_enabled: bool = False
    email_outbound_enabled: bool = False
    email_public_base_url: str | None = None
    email_storage_root: str | None = None
    email_max_attachment_bytes: int = 15_000_000
    email_initial_address: str = "hub@carfast.pt"
    postmark_server_token: str | None = None
    postmark_message_stream: str = "outbound"
    postmark_inbound_basic_user: str | None = None
    postmark_inbound_basic_password: str | None = None
    modular_composer_enabled: bool = False
    visual_foundation_enabled: bool = False
    task_cases_enabled: bool = False
    task_decisions_enabled: bool = False

    @property
    def enable_docs(self) -> bool:
        return self.app_env.lower() in {"local", "dev", "development"}

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
