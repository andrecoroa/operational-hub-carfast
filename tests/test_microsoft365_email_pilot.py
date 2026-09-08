from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import Settings
from app.main import app
from app.models.email import EmailChannelTransport
from app.services import email_transport
from app.services.microsoft365_oauth import (
    GRAPH_DELEGATED_SCOPES,
    authorization_url,
    begin_authorization,
    consume_authorization,
    create_pkce_pair,
)


def test_callback_route_is_exact_and_get_only():
    matches = [
        route
        for route in app.routes
        if getattr(route, "path", None)
        == "/v2-clean/integrations/microsoft/callback"
    ]
    assert len(matches) == 1
    assert matches[0].methods == {"GET"}


def test_transport_migration_is_the_single_additive_head():
    config = Config("alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["fffd128c9e0f"]
    assert scripts.get_revision("fffc017b8d9e").down_revision == "fffbf06a7c8d"


def test_microsoft365_is_disabled_by_default_and_redirect_is_green():
    settings = Settings(_env_file=None)
    assert settings.microsoft365_email_enabled is False
    assert settings.microsoft365_redirect_uri == (
        "https://carfast-green.onrender.com/v2-clean/integrations/microsoft/callback"
    )


def test_pilot_initial_sync_window_defaults_to_five_days():
    assert EmailChannelTransport.__table__.c.initial_sync_days.default.arg == 5


def test_authorization_url_uses_pkce_and_required_delegated_scopes():
    verifier, challenge = create_pkce_pair()
    assert verifier
    assert challenge
    url = authorization_url(
        tenant_id="tenant",
        client_id="client",
        redirect_uri="https://example.test/callback",
        state="state-value",
        challenge=challenge,
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "login.microsoftonline.com"
    assert parsed.path == "/tenant/oauth2/v2.0/authorize"
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [challenge]
    assert set(query["scope"][0].split()) == set(GRAPH_DELEGATED_SCOPES)


def test_oauth_state_is_bound_to_the_initiating_user_and_single_use():
    state, _ = begin_authorization(user_id=42, transport_id=7)
    assert consume_authorization(state, user_id=99) is None
    attempt = consume_authorization(state, user_id=42)
    assert attempt is not None
    assert attempt.transport_id == 7
    assert consume_authorization(state, user_id=42) is None


class _FakeDb:
    def __init__(self, config):
        self.config = config

    def scalar(self, statement):
        return self.config


class _Config:
    def __init__(self, *, enabled: bool, provider: str):
        self.enabled = enabled
        self.provider = provider


def test_transport_defaults_to_postmark_for_legacy_or_disabled_config():
    assert email_transport.provider_for_channel(_FakeDb(None), 1) == "postmark"
    config = _Config(enabled=False, provider="microsoft365")
    assert email_transport.provider_for_channel(_FakeDb(config), 1) == "postmark"


def test_transport_switch_is_scoped_to_enabled_mailbox_config():
    config = _Config(enabled=True, provider="microsoft365")
    assert email_transport.provider_for_channel(_FakeDb(config), 1) == "microsoft365"
