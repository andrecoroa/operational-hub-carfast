"""Fail closed unless the empty rehearsal environment has no external side effects."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

FALSE_VALUES = {"0", "false", "off", "no", ""}
DISABLED_FLAGS = (
    "EMAIL_INBOUND_ENABLED",
    "EMAIL_OUTBOUND_ENABLED",
    "WEBHOOKS_ENABLED",
    "SCHEDULED_JOBS_ENABLED",
    "PORTALS_ENABLED",
    "EXTERNAL_INTEGRATIONS_ENABLED",
)
FORBIDDEN_SECRET_NAMES = (
    "POSTMARK_SERVER_TOKEN",
    "INTEGRATION_API_KEY",
    "WEBHOOK_SIGNING_SECRET",
)


def _database_host_is_isolated(hostname: str | None, environment: dict[str, str]) -> bool:
    if hostname in {"localhost", "127.0.0.1", "postgres", "rehearsal-postgres"}:
        return True
    # Render internal PostgreSQL hostnames are technical, private-network names.
    # They are accepted only for the explicitly gated empty rehearsal runtime.
    expected_render_host = environment.get("REHEARSAL_DATABASE_HOST", "").strip().lower()
    return (
        environment.get("RENDER", "").strip().lower() == "true"
        and environment.get("RENDER_EMPTY_REHEARSAL", "").strip().lower() == "true"
        and bool(hostname)
        and bool(expected_render_host)
        and hostname.lower() == expected_render_host
        and expected_render_host.startswith("dpg-")
    )


def validate_environment(environment: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if environment.get("APP_ENV") != "test":
        errors.append("APP_ENV must be test")
    database_url = environment.get("DATABASE_URL", "")
    parsed = urlsplit(database_url.replace("postgresql+psycopg", "postgresql", 1))
    if not _database_host_is_isolated(parsed.hostname, environment):
        errors.append("database must be isolated on the runner")
    if not parsed.path.lstrip("/").endswith("_test"):
        errors.append("database name must end in _test")
    for name in DISABLED_FLAGS:
        if environment.get(name, "").strip().lower() not in FALSE_VALUES:
            errors.append(f"{name} must be disabled")
    for name in FORBIDDEN_SECRET_NAMES:
        if environment.get(name, "").strip():
            errors.append(f"{name} must be empty")
    if environment.get("DOCUMENT_FIXTURES_ONLY", "").strip().lower() != "true":
        errors.append("DOCUMENT_FIXTURES_ONLY must be true")
    if environment.get("REAL_DATA_ALLOWED", "").strip().lower() not in FALSE_VALUES:
        errors.append("REAL_DATA_ALLOWED must be false")
    return errors


def main() -> int:
    errors = validate_environment(dict(os.environ))
    if errors:
        raise SystemExit("Unsafe isolated environment: " + "; ".join(errors))
    print("Isolated empty-environment safety configuration verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
