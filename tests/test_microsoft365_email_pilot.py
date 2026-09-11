from __future__ import annotations

from urllib.parse import parse_qs, urlparse
import json

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import app.web.microsoft365 as microsoft_web
import app.services.microsoft365_oauth as microsoft_oauth
from app.core.config import Settings
from app.main import app
from app.models.email import EmailChannel, EmailChannelTransport
from app.services import email_transport
from app.services.microsoft365_oauth import (
    GRAPH_DELEGATED_SCOPES,
    authorization_url,
    begin_authorization,
    consume_authorization,
    create_pkce_pair,
    send_shared_mailbox_message,
)


def test_callback_route_is_exact_and_get_only():
    matches = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/v2-clean/integrations/microsoft/callback"
    ]
    assert len(matches) == 1
    assert matches[0].methods == {"GET"}


def test_transport_migration_is_the_single_additive_head():
    config = Config("alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["ffff34ae102b"]
    assert scripts.get_revision("fffc017b8d9e").down_revision == "fffbf06a7c8d"


def test_microsoft365_is_disabled_by_default_and_redirect_is_green():
    settings = Settings(_env_file=None)
    assert settings.microsoft365_email_enabled is False
    assert settings.microsoft365_oauth_setup_enabled is False
    assert settings.microsoft365_redirect_uri == (
        "https://carfast-green.onrender.com/v2-clean/integrations/microsoft/callback"
    )


def test_pilot_initial_sync_window_defaults_to_five_days():
    assert EmailChannelTransport.__table__.c.initial_sync_days.default.arg == 5


def test_admin_can_configure_fixed_mailbox_without_enabling_transport(
    authenticated_client, db_session, monkeypatch
):
    monkeypatch.setattr(
        microsoft_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    response = authenticated_client.post(
        "/v2-clean/integrations/microsoft/configure-disabled",
        data={
            "mailbox_address": "email@carfast.pt",
            "tenant_id": "tenant-id",
            "client_id": "client-id",
            "delegated_user_principal_name": "andrecoroa@daccordinvest.pt",
        },
    )
    assert response.status_code == 200
    channel = db_session.scalar(
        select(EmailChannel).where(EmailChannel.address == "email@carfast.pt")
    )
    transport = db_session.scalar(
        select(EmailChannelTransport).where(EmailChannelTransport.channel_id == channel.id)
    )
    assert channel.active is False
    assert transport.enabled is False
    assert transport.provider == "microsoft365"
    assert transport.client_credential_reference == "env://MICROSOFT365_CLIENT_SECRET"
    assert transport.token_reference.startswith("db://microsoft365/transport/")
    assert transport.initial_sync_days == 5


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
    def __init__(self, *, enabled: bool, provider: str, **values):
        self.enabled = enabled
        self.provider = provider
        for key, value in values.items():
            setattr(self, key, value)


def test_transport_defaults_to_postmark_for_legacy_or_disabled_config():
    assert email_transport.provider_for_channel(_FakeDb(None), 1) == "postmark"
    config = _Config(enabled=False, provider="microsoft365")
    assert email_transport.provider_for_channel(_FakeDb(config), 1) == "postmark"


def test_transport_switch_is_scoped_to_enabled_mailbox_config():
    config = _Config(enabled=True, provider="microsoft365")
    assert email_transport.provider_for_channel(_FakeDb(config), 1) == "microsoft365"


def test_microsoft365_transport_uses_only_the_configured_mailbox(monkeypatch):
    monkeypatch.setattr(email_transport.settings, "microsoft365_email_enabled", True)
    config = _Config(
        enabled=True,
        provider="microsoft365",
        mailbox_address="frota@carfast.pt",
        tenant_id="tenant",
        client_id="client",
        client_credential_reference="env://MICROSOFT365_CLIENT_SECRET",
        token_reference="db://microsoft365/transport/7/tokens",
    )
    message = type("Message", (), {})()
    calls = []
    result = email_transport.send_channel_message(
        _FakeDb(config),
        type("Channel", (), {"id": 7})(),
        message,
        '"Frota" <frota@carfast.pt>',
        reply_to="frota@carfast.pt",
        microsoft365_sender=lambda supplied, **kwargs: calls.append((supplied, kwargs)) or {"Provider": "microsoft365"},
    )
    assert result == {"Provider": "microsoft365"}
    assert calls[0][1]["mailbox_address"] == "frota@carfast.pt"


def test_microsoft365_transport_rejects_a_different_sender(monkeypatch):
    monkeypatch.setattr(email_transport.settings, "microsoft365_email_enabled", True)
    config = _Config(
        enabled=True,
        provider="microsoft365",
        mailbox_address="frota@carfast.pt",
        tenant_id="tenant",
        client_id="client",
        client_credential_reference="env://secret",
        token_reference="db://tokens",
    )
    try:
        email_transport.send_channel_message(
            _FakeDb(config), type("Channel", (), {"id": 7})(), object(),
            '"Central" <central@carfast.pt>', reply_to="central@carfast.pt",
        )
    except RuntimeError as exc:
        assert "não corresponde" in str(exc)
    else:
        raise AssertionError("Expected mismatched Microsoft 365 sender to be rejected")


def test_graph_send_uses_shared_mailbox_endpoint_and_saves_sent_copy(monkeypatch):
    monkeypatch.setattr(microsoft_oauth, "_delegated_access_token", lambda **kwargs: "token")
    captured = {}

    class _Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.data)
        return _Response()

    monkeypatch.setattr(microsoft_oauth.urllib.request, "urlopen", fake_urlopen)
    message = type(
        "Message",
        (),
        {
            "subject": "Teste CarFast 365",
            "text_body": "Teste",
            "html_body": None,
            "recipients_json": [{"Email": "andrecoroa@daccordinvest.pt"}],
            "cc_json": [],
            "bcc_json": [],
        },
    )()
    result = send_shared_mailbox_message(
        message,
        tenant_id="tenant",
        client_id="client",
        client_credential_reference="env://secret",
        token_reference="db://token",
        mailbox_address="frota@carfast.pt",
        reply_to="frota@carfast.pt",
    )
    assert result["Provider"] == "microsoft365"
    assert captured["url"].endswith("/users/frota%40carfast.pt/sendMail")
    assert captured["authorization"] == "Bearer token"
    assert captured["body"]["saveToSentItems"] is True
    assert captured["body"]["message"]["toRecipients"] == [
        {"emailAddress": {"address": "andrecoroa@daccordinvest.pt"}}
    ]


def test_frota_activation_requires_an_existing_connected_source(
    authenticated_client, db_session, monkeypatch
):
    monkeypatch.setattr(
        microsoft_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
    )
    response = authenticated_client.post(
        "/v2-clean/integrations/microsoft/activate-frota"
    )
    assert response.status_code == 409
    assert response.json() == {"error": "connected_source_not_found"}
