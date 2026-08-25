from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_devcontainer_is_fail_closed_and_uses_isolated_postgres() -> None:
    compose = yaml.safe_load(
        (ROOT / ".devcontainer" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    app = compose["services"]["app"]
    environment = app["environment"]

    assert environment["APP_ENV"] == "test"
    assert environment["DATABASE_URL"].split("@", 1)[1].startswith("postgres:5432/")
    for name in (
        "EMAIL_INBOUND_ENABLED",
        "EMAIL_OUTBOUND_ENABLED",
        "WEBHOOKS_ENABLED",
        "SCHEDULED_JOBS_ENABLED",
        "PORTALS_ENABLED",
        "EXTERNAL_INTEGRATIONS_ENABLED",
        "REAL_DATA_ALLOWED",
    ):
        assert environment[name] == "false"
    assert environment["DOCUMENT_FIXTURES_ONLY"] == "true"
    for name in ("POSTMARK_SERVER_TOKEN", "INTEGRATION_API_KEY", "WEBHOOK_SIGNING_SECRET"):
        assert environment[name] == ""

    postgres = compose["services"]["postgres"]
    assert postgres["image"] == "postgres:17-bookworm"
    assert "ports" not in postgres


def test_post_create_validates_safety_before_migrations() -> None:
    script = (ROOT / ".devcontainer" / "post-create.sh").read_text(encoding="utf-8")
    safety = script.index("python -m scripts.validate_isolated_environment")
    migrations = script.index("python -m alembic upgrade head")
    assert safety < migrations


def test_sandbox_branch_runs_both_ci_workflows() -> None:
    branch = "codex/development-sandbox-clean-install"
    for workflow in ("ci.yml", "isolated-empty-rehearsal.yml"):
        text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        assert branch in text
