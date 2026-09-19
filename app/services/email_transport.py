from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.email import (
    EmailAttachment,
    EmailChannel,
    EmailChannelAlias,
    EmailChannelTransport,
    EmailMessage,
    EmailThread,
)
from app.core.config import settings
from app.services.email_postmark import send_message as send_postmark_message
from app.services.email_postmark import outbound_identity
from app.services.microsoft365_oauth import send_shared_mailbox_message

POSTMARK = "postmark"
MICROSOFT365 = "microsoft365"


class OutboundIdentityError(ValueError):
    """A configured channel cannot safely resolve its outbound identity."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResolvedOutboundIdentity:
    sender_address: str
    transport_sender: str
    reply_to_address: str


def resolve_outbound_identity(
    db: Session,
    channel: EmailChannel,
    thread: EmailThread | None,
) -> ResolvedOutboundIdentity:
    """Resolve a mailbox or inbound-alias identity, failing closed.

    ``original`` is intentionally only valid for replies to an inbound thread.
    The original recipient must still be an active alias of the same channel;
    technical forwarding addresses and aliases owned by another channel never
    qualify as outbound identities.
    """
    if channel.reply_policy == "original":
        original = (
            str(thread.original_recipient_address if thread else "")
            .strip()
            .casefold()
        )
        if not original:
            raise OutboundIdentityError(
                "original_sender_unavailable",
                "A conversa não tem um endereço original de entrada.",
            )
        alias = db.scalar(
            select(EmailChannelAlias).where(
                EmailChannelAlias.channel_id == channel.id,
                EmailChannelAlias.active.is_(True),
                func.lower(EmailChannelAlias.address) == original,
            )
        )
        if not alias:
            raise OutboundIdentityError(
                "original_sender_not_authorized",
                "O endereço original não é um alias ativo desta caixa.",
            )
        sender_address = str(alias.address).strip().casefold()
        reply_to_address = sender_address
    else:
        sender_address = str(channel.from_address or "").strip().casefold()
        reply_to_address = str(channel.reply_to_address or "").strip().casefold()

    try:
        transport_sender, reply_to_address = outbound_identity(
            channel.from_name,
            sender_address,
            reply_to_address,
        )
    except ValueError as exc:
        raise OutboundIdentityError("sender_not_configured", str(exc)) from exc

    config = channel_transport(db, channel.id, sender_address=sender_address)
    if config and config.enabled and config.provider == MICROSOFT365:
        required = (
            config.mailbox_address,
            config.tenant_id,
            config.client_id,
            config.client_credential_reference,
            config.token_reference,
        )
        if not all(required):
            raise OutboundIdentityError(
                "sender_not_configured",
                "A configuração protegida Microsoft 365 desta caixa está incompleta.",
            )
        mailbox = str(config.mailbox_address).strip().casefold()
        if channel.reply_policy == "mailbox" and mailbox != sender_address:
            raise OutboundIdentityError(
                "sender_not_configured",
                "O remetente não corresponde à caixa Microsoft 365 configurada.",
            )

    return ResolvedOutboundIdentity(
        sender_address=sender_address,
        transport_sender=transport_sender,
        reply_to_address=reply_to_address,
    )


def channel_transport(
    db: Session, channel_id: int, *, sender_address: str | None = None
) -> EmailChannelTransport | None:
    normalized_sender = str(sender_address or "").strip().casefold()
    query = select(EmailChannelTransport).where(
        EmailChannelTransport.channel_id == channel_id
    )
    if normalized_sender:
        exact = db.scalar(
            query.where(
                func.lower(EmailChannelTransport.mailbox_address) == normalized_sender
            )
        )
        if exact:
            return exact
    return db.scalar(
        query.order_by(EmailChannelTransport.enabled.desc(), EmailChannelTransport.id)
    )


def provider_for_channel(db: Session, channel_id: int) -> str | None:
    config = db.scalar(
        select(EmailChannelTransport).where(
            EmailChannelTransport.channel_id == channel_id,
            EmailChannelTransport.provider == MICROSOFT365,
            EmailChannelTransport.enabled.is_(True),
        ).order_by(EmailChannelTransport.id)
    )
    if config and config.enabled:
        return config.provider
    explicit = db.scalar(
        select(EmailChannelTransport).where(
            EmailChannelTransport.channel_id == channel_id,
            EmailChannelTransport.enabled.is_(True),
        ).order_by(EmailChannelTransport.id)
    )
    return explicit.provider if explicit else None


def outbound_enabled_for_channel(db: Session, channel_id: int) -> bool:
    """Keep the legacy master switch while allowing explicitly enabled M365 channels."""
    if settings.email_outbound_enabled:
        return True
    return (
        settings.microsoft365_email_enabled
        and provider_for_channel(db, channel_id) == MICROSOFT365
    )


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
    for attachment in attachments or []:
        if (
            attachment.ingest_state != "stored"
            or not attachment.storage_path
            or not Path(attachment.storage_path).is_file()
        ):
            raise RuntimeError(
                f"O anexo {attachment.file_name!r} não está disponível; "
                "a mensagem não foi enviada."
            )
    sender_address = sender.rsplit("<", 1)[-1].rstrip(">").strip().casefold()
    config = channel_transport(db, channel.id, sender_address=sender_address)
    if not config or not config.enabled:
        raise RuntimeError(
            "A caixa não tem um transporte de envio ativo. "
            "O sistema não recorrerá automaticamente ao Postmark."
        )
    provider = config.provider
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
        if configured_mailbox != sender_address:
            if getattr(channel, "reply_policy", "mailbox") != "original":
                raise RuntimeError(
                    "O remetente não corresponde à caixa Microsoft 365 configurada."
                )
            alias = db.scalar(
                select(EmailChannelAlias).where(
                    EmailChannelAlias.channel_id == channel.id,
                    EmailChannelAlias.active.is_(True),
                    func.lower(EmailChannelAlias.address) == sender_address,
                )
            )
            if not alias:
                raise RuntimeError(
                    "O remetente não corresponde à caixa Microsoft 365 configurada "
                    "nem a um alias autorizado."
                )
        return microsoft365_sender(
            message,
            tenant_id=str(config.tenant_id),
            client_id=str(config.client_id),
            client_credential_reference=str(config.client_credential_reference),
            token_reference=str(config.token_reference),
            mailbox_address=str(config.mailbox_address),
            sender_address=sender_address,
            reply_to=reply_to,
            attachments=attachments,
        )
    raise RuntimeError(f"Fornecedor de email não suportado: {provider}.")
