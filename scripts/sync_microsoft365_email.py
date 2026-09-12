"""Synchronize enabled Microsoft 365 inboxes once; safe to call from a scheduler."""

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.microsoft365_inbound import sync_enabled_inboxes
from app.services.microsoft365_oauth import (
    EnvironmentAndDatabaseSecretReferenceStore,
    configure_secret_reference_store,
)


def main() -> None:
    if not settings.microsoft365_token_encryption_key:
        raise RuntimeError("MICROSOFT365_TOKEN_ENCRYPTION_KEY não está configurada.")
    configure_secret_reference_store(
        EnvironmentAndDatabaseSecretReferenceStore(
            settings.microsoft365_token_encryption_key
        )
    )
    with SessionLocal() as db:
        result = sync_enabled_inboxes(db)
    print(
        "Microsoft 365 inbox sync complete: "
        f"{sum(item['seen'] for item in result.values())} seen, "
        f"{sum(item['created'] for item in result.values())} created."
    )


if __name__ == "__main__":
    main()
