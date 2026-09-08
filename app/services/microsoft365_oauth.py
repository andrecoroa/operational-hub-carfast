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

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.email import EmailSecretReference
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
