from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.email import EmailAttachment, EmailChannel, EmailChannelTransport, EmailMessage
from app.core.config import settings
from app.services.email_postmark import send_message as send_postmark_message
from app.services.microsoft365_oauth import send_shared_mailbox_message

POSTMARK = "postmark"
MICROSOFT365 = "microsoft365"


def channel_transport(db: Session, channel_id: int) -> EmailChannelTransport | None:
    return db.scalar(
        select(EmailChannelTransport).where(
            EmailChannelTransport.channel_id == channel_id
        )
    )


def provider_for_channel(db: Session, channel_id: int) -> str:
    config = channel_transport(db, channel_id)
    if not config or not config.enabled:
        return POSTMARK
    return config.provider


def send_channel_message(
    db: Session,
    channel: EmailChannel,
    message: EmailMessage,
    sender: str,
    *,
    reply_to: str,
    parent_message_id: str | None = None,
    references: list[str] | None = None,
    attachments: list[EmailAttachment] | None = None,
    postmark_sender: Callable[..., dict[str, Any]] = send_postmark_message,
    microsoft365_sender: Callable[..., dict[str, Any]] = send_shared_mailbox_message,
) -> dict[str, Any]:
    config = channel_transport(db, channel.id)
    provider = POSTMARK if not config or not config.enabled else config.provider
    if provider == POSTMARK:
        return postmark_sender(
            message,
            sender,
            reply_to=reply_to,
            parent_message_id=parent_message_id,
            references=references,
            attachments=attachments,
        )
    if provider == MICROSOFT365:
        if not settings.microsoft365_email_enabled:
            raise RuntimeError("O envio Microsoft 365 está desligado neste ambiente.")
        required = (
            config.mailbox_address,
            config.tenant_id,
            config.client_id,
            config.client_credential_reference,
            config.token_reference,
        )
        if not all(required):
            raise RuntimeError("A configuração protegida Microsoft 365 desta caixa está incompleta.")
        configured_mailbox = str(config.mailbox_address).strip().casefold()
        sender_address = sender.rsplit("<", 1)[-1].rstrip(">").strip().casefold()
        if configured_mailbox != sender_address:
            raise RuntimeError("O remetente não corresponde à caixa Microsoft 365 configurada.")
        return microsoft365_sender(
            message,
            tenant_id=str(config.tenant_id),
            client_id=str(config.client_id),
            client_credential_reference=str(config.client_credential_reference),
            token_reference=str(config.token_reference),
            mailbox_address=str(config.mailbox_address),
            reply_to=reply_to,
            attachments=attachments,
        )
    raise RuntimeError(f"Fornecedor de email não suportado: {provider}.")
