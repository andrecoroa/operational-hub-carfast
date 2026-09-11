from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.email import EmailSecretReference
from app.models.email import EmailAttachment, EmailMessage
from app.services.audit import record_audit

GRAPH_DELEGATED_SCOPES = (
    "openid",
    "profile",
    "offline_access",
    "User.Read",
    "Mail.ReadWrite.Shared",
    "Mail.Send.Shared",
)
OAUTH_ATTEMPT_TTL = timedelta(minutes=10)


class SecretReferenceStore(Protocol):
    """A secret manager addressed only through opaque references."""

    def read(self, reference: str) -> str: ...

    def write(self, reference: str, value: str, *, expires_at: datetime | None = None) -> None: ...


class UnconfiguredSecretReferenceStore:
    def read(self, reference: str) -> str:
        raise RuntimeError("O cofre de credenciais Microsoft 365 não está configurado.")

    def write(self, reference: str, value: str, *, expires_at: datetime | None = None) -> None:
        raise RuntimeError("O cofre de credenciais Microsoft 365 não está configurado.")


class EnvironmentAndDatabaseSecretReferenceStore:
    """Read deployment credentials from env and persist encrypted OAuth tokens."""

    def __init__(self, encryption_key: str, *, session_factory=SessionLocal) -> None:
        try:
            keys = [
                Fernet(item.strip().encode("ascii"))
                for item in encryption_key.split(",")
                if item.strip()
            ]
            if not keys:
                raise ValueError
            self._fernet = MultiFernet(keys)
        except (ValueError, UnicodeEncodeError) as exc:
            raise RuntimeError(
                "MICROSOFT365_TOKEN_ENCRYPTION_KEY não é uma chave Fernet válida."
            ) from exc
        self._session_factory = session_factory

    def read(self, reference: str) -> str:
        if reference.startswith("env://"):
            name = reference.removeprefix("env://")
            value = os.environ.get(name)
            if not name or not value:
                raise RuntimeError(
                    f"Credencial Microsoft 365 não configurada: {name or 'referência vazia'}."
                )
            return value
        if reference.startswith("db://"):
            with self._session_factory() as db:
                item = db.scalar(
                    select(EmailSecretReference).where(EmailSecretReference.reference == reference)
                )
                if item is None:
                    raise RuntimeError("Token Microsoft 365 ainda não configurado.")
                if item.expires_at:
                    expires_at = item.expires_at
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=UTC)
                    if expires_at <= datetime.now(UTC):
                        raise RuntimeError("O token Microsoft 365 guardado expirou.")
                try:
                    return self._fernet.decrypt(item.ciphertext.encode("ascii")).decode("utf-8")
                except (InvalidToken, UnicodeDecodeError) as exc:
                    raise RuntimeError("Não foi possível decifrar o token Microsoft 365.") from exc
        raise RuntimeError("Referência de segredo Microsoft 365 inválida.")

    def write(self, reference: str, value: str, *, expires_at: datetime | None = None) -> None:
        if not reference.startswith("db://"):
            raise RuntimeError("Apenas referências db:// podem ser gravadas.")
        ciphertext = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        with self._session_factory() as db:
            item = db.scalar(
                select(EmailSecretReference).where(EmailSecretReference.reference == reference)
            )
            if item is None:
                item = EmailSecretReference(
                    reference=reference, ciphertext=ciphertext, expires_at=expires_at
                )
                db.add(item)
                operation = "created"
            else:
                item.ciphertext = ciphertext
                item.expires_at = expires_at
                item.rotated_at = datetime.now(UTC)
                operation = "rotated"
            record_audit(
                db,
                f"microsoft365.secret.{operation}",
                "email_secret_reference",
                reference,
                after_json={
                    "reference": reference,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
            )
            db.commit()

    def rotate_encryption(self, reference: str) -> None:
        """Re-encrypt a stored value with the first key in the configured key ring."""
        value = self.read(reference)
        with self._session_factory() as db:
            item = db.scalar(
                select(EmailSecretReference).where(EmailSecretReference.reference == reference)
            )
            expires_at = item.expires_at if item else None
        self.write(reference, value, expires_at=expires_at)


@dataclass(frozen=True)
class PendingAuthorization:
    user_id: int
    transport_id: int
    verifier: str
    expires_at: datetime


_pending: dict[str, PendingAuthorization] = {}
_pending_lock = threading.Lock()
_secret_store: SecretReferenceStore = UnconfiguredSecretReferenceStore()


def configure_secret_reference_store(store: SecretReferenceStore) -> None:
    global _secret_store
    _secret_store = store


def create_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorization_url(
    *, tenant_id: str, client_id: str, redirect_uri: str, state: str, challenge: str
) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(GRAPH_DELEGATED_SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?{query}"


def begin_authorization(*, user_id: int, transport_id: int) -> tuple[str, str]:
    verifier, challenge = create_pkce_pair()
    state = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    with _pending_lock:
        expired = [key for key, item in _pending.items() if item.expires_at <= now]
        for key in expired:
            _pending.pop(key, None)
        _pending[state] = PendingAuthorization(
            user_id=user_id,
            transport_id=transport_id,
            verifier=verifier,
            expires_at=now + OAUTH_ATTEMPT_TTL,
        )
    return state, challenge


def consume_authorization(state: str, *, user_id: int) -> PendingAuthorization | None:
    with _pending_lock:
        attempt = _pending.get(state)
        if not attempt or attempt.user_id != user_id:
            return None
        _pending.pop(state, None)
    if attempt.expires_at <= datetime.now(UTC):
        return None
    return attempt


def exchange_authorization_code(
    *,
    tenant_id: str,
    client_id: str,
    client_credential_reference: str,
    token_reference: str,
    redirect_uri: str,
    code: str,
    verifier: str,
) -> dict[str, object]:
    client_secret = _secret_store.read(client_credential_reference)
    payload = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "scope": " ".join(GRAPH_DELEGATED_SCOPES),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            token_payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Microsoft identity devolveu HTTP {exc.code}.") from exc
    if not token_payload.get("access_token") or not token_payload.get("refresh_token"):
        raise RuntimeError("A resposta OAuth Microsoft não contém os tokens esperados.")
    obtained_at = datetime.now(UTC)
    expires_in = int(token_payload.get("expires_in") or 0)
    token_payload["obtained_at"] = obtained_at.isoformat()
    if expires_in > 0:
        token_payload["access_expires_at"] = (
            obtained_at + timedelta(seconds=expires_in)
        ).isoformat()
    refresh_expires_in = int(token_payload.get("refresh_token_expires_in") or 0)
    expires_at = (
        obtained_at + timedelta(seconds=refresh_expires_in) if refresh_expires_in > 0 else None
    )
    _secret_store.write(token_reference, json.dumps(token_payload), expires_at=expires_at)
    return {
        "scope": token_payload.get("scope", ""),
        "expires_in": token_payload.get("expires_in"),
    }


def _delegated_access_token(
    *, tenant_id: str, client_id: str, client_credential_reference: str,
    token_reference: str, force_refresh: bool = False,
) -> str:
    """Return a current delegated token, refreshing it through its opaque store."""
    token_payload = json.loads(_secret_store.read(token_reference))
    expires_at_raw = token_payload.get("access_expires_at")
    expires_at = datetime.fromisoformat(expires_at_raw) if expires_at_raw else None
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if not force_refresh and token_payload.get("access_token") and (
        expires_at is None or expires_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        return str(token_payload["access_token"])
    client_secret = _secret_store.read(client_credential_reference)
    payload = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": token_payload.get("refresh_token", ""),
        "scope": " ".join(GRAPH_DELEGATED_SCOPES),
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            refreshed = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Microsoft identity devolveu HTTP {exc.code}.") from exc
    if not refreshed.get("access_token"):
        raise RuntimeError("A renovação OAuth Microsoft 365 não devolveu access token.")
    refreshed.setdefault("refresh_token", token_payload.get("refresh_token"))
    obtained_at = datetime.now(UTC)
    refreshed["obtained_at"] = obtained_at.isoformat()
    refreshed["access_expires_at"] = (
        obtained_at + timedelta(seconds=int(refreshed.get("expires_in") or 0))
    ).isoformat()
    _secret_store.write(token_reference, json.dumps(refreshed))
    return str(refreshed["access_token"])


def move_shared_mailbox_message_to_junk(
    *, tenant_id: str, client_id: str, client_credential_reference: str,
    token_reference: str, mailbox_address: str, message_id: str,
) -> None:
    token = _delegated_access_token(
        tenant_id=tenant_id,
        client_id=client_id,
        client_credential_reference=client_credential_reference,
        token_reference=token_reference,
    )
    mailbox = urllib.parse.quote(mailbox_address, safe="")
    message = urllib.parse.quote(message_id, safe="")
    request = urllib.request.Request(
        f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages/{message}/move",
        data=json.dumps({"destinationId": "junkemail"}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status not in {200, 201}:
                raise RuntimeError(f"Microsoft Graph devolveu HTTP {response.status}.")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Microsoft Graph devolveu HTTP {exc.code}.") from exc


def _graph_recipient(value: object) -> dict[str, dict[str, str]] | None:
    address = value.get("Email") if isinstance(value, dict) else str(value or "")
    address = str(address or "").strip()
    if not address:
        return None
    return {"emailAddress": {"address": address}}


def send_shared_mailbox_message(
    message: EmailMessage,
    *,
    tenant_id: str,
    client_id: str,
    client_credential_reference: str,
    token_reference: str,
    mailbox_address: str,
    reply_to: str,
    attachments: list[EmailAttachment] | None = None,
) -> dict[str, object]:
    """Send through a configured shared mailbox using delegated Graph access."""
    token_kwargs = {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_credential_reference": client_credential_reference,
        "token_reference": token_reference,
    }
    token = _delegated_access_token(
        **token_kwargs,
    )

    recipients = [
        recipient
        for value in (message.recipients_json or [])
        if (recipient := _graph_recipient(value)) is not None
    ]
    if not recipients:
        raise RuntimeError("A mensagem Microsoft 365 não tem destinatário.")

    graph_message: dict[str, object] = {
        "subject": message.subject,
        "body": {
            "contentType": "HTML" if message.html_body else "Text",
            "content": message.html_body or message.text_body or "",
        },
        "toRecipients": recipients,
        "replyTo": [{"emailAddress": {"address": reply_to}}],
    }
    for source, target in ((message.cc_json, "ccRecipients"), (message.bcc_json, "bccRecipients")):
        values = [
            recipient
            for value in (source or [])
            if (recipient := _graph_recipient(value)) is not None
        ]
        if values:
            graph_message[target] = values

    if attachments:
        try:
            graph_message["attachments"] = [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": attachment.file_name,
                    "contentType": attachment.content_type or "application/octet-stream",
                    "contentBytes": base64.b64encode(
                        Path(attachment.storage_path).read_bytes()
                    ).decode("ascii"),
                }
                for attachment in attachments
            ]
        except OSError as exc:
            raise RuntimeError("Um anexo da resposta já não está disponível.") from exc

    mailbox = urllib.parse.quote(mailbox_address, safe="")
    body = json.dumps({"message": graph_message, "saveToSentItems": True}).encode("utf-8")

    def submit(access_token: str) -> None:
        request = urllib.request.Request(
            f"https://graph.microsoft.com/v1.0/users/{mailbox}/sendMail",
            data=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 202:
                raise RuntimeError(f"Microsoft Graph devolveu HTTP {response.status}.")

    try:
        submit(token)
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise RuntimeError(f"Microsoft Graph devolveu HTTP {exc.code}.") from exc
        refreshed_token = _delegated_access_token(**token_kwargs, force_refresh=True)
        try:
            submit(refreshed_token)
        except urllib.error.HTTPError as retry_exc:
            raise RuntimeError(
                f"Microsoft Graph devolveu HTTP {retry_exc.code} após renovar a autenticação."
            ) from retry_exc
    return {"Provider": "microsoft365", "MessageID": None}
