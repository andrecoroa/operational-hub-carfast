from scripts.validate_isolated_environment import validate_environment


def safe_environment() -> dict[str, str]:
    return {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+psycopg://test:test@localhost/carfast_test",
        "EMAIL_INBOUND_ENABLED": "false",
        "EMAIL_OUTBOUND_ENABLED": "false",
        "WEBHOOKS_ENABLED": "false",
        "SCHEDULED_JOBS_ENABLED": "false",
        "PORTALS_ENABLED": "false",
        "EXTERNAL_INTEGRATIONS_ENABLED": "false",
        "POSTMARK_SERVER_TOKEN": "",
        "INTEGRATION_API_KEY": "",
        "WEBHOOK_SIGNING_SECRET": "",
        "DOCUMENT_FIXTURES_ONLY": "true",
        "REAL_DATA_ALLOWED": "false",
    }


def test_empty_environment_passes_only_with_all_side_effects_disabled() -> None:
    assert validate_environment(safe_environment()) == []


def test_production_remote_data_and_each_side_effect_fail_closed() -> None:
    cases = {
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql+psycopg://user:secret@production.example/carfast",
        "EMAIL_OUTBOUND_ENABLED": "true",
        "WEBHOOKS_ENABLED": "true",
        "SCHEDULED_JOBS_ENABLED": "true",
        "PORTALS_ENABLED": "true",
        "EXTERNAL_INTEGRATIONS_ENABLED": "true",
        "POSTMARK_SERVER_TOKEN": "secret",
        "DOCUMENT_FIXTURES_ONLY": "false",
        "REAL_DATA_ALLOWED": "true",
    }
    for name, unsafe_value in cases.items():
        environment = safe_environment()
        environment[name] = unsafe_value
        assert validate_environment(environment), name
