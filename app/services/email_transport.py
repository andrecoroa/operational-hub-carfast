from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.email import EmailAttachment, EmailChannel, EmailChannelTransport, EmailMessage
from app.services.email_postmark import send_message as send_postmark_message

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
) -> dict[str, Any]:
    provider = provider_for_channel(db, channel.id)
    if provider == POSTMARK:
        return send_postmark_message(
            message,
            sender,
            reply_to=reply_to,
            parent_message_id=parent_message_id,
            references=references,
            attachments=attachments,
        )
    if provider == MICROSOFT365:
        raise RuntimeError(
            "O transporte Microsoft 365 desta caixa ainda não está ligado a credenciais protegidas."
        )
    raise RuntimeError(f"Fornecedor de email não suportado: {provider}.")
