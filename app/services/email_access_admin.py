from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.email import EmailChannelRole

EMAIL_ACCESS_FIELDS = (
    "can_read",
    "can_reply",
    "can_send_direct",
    "can_approve",
    "can_assume",
    "can_assign",
    "can_manage_sla",
    "can_manage",
    "can_change_sender",
    "can_edit_recipients",
    "can_use_cc_bcc",
)

EMAIL_ACCESS_PRESETS = {
    "consult": {"can_read"},
    "triage_reply": {"can_read", "can_reply", "can_assume"},
    "full_management": set(EMAIL_ACCESS_FIELDS),
}


@dataclass
class EmailAccessChange:
    channel_id: int
    role_id: int
    before: dict[str, object]
    after: dict[str, object]
    grant: EmailChannelRole | None


def grant_snapshot(grant: EmailChannelRole | None) -> dict[str, object]:
    if not grant:
        return {**{field: False for field in EMAIL_ACCESS_FIELDS}, "visibility_mode": "scope_all"}
    return {
        **{field: bool(getattr(grant, field)) for field in EMAIL_ACCESS_FIELDS},
        "visibility_mode": grant.visibility_mode,
    }


def normalize_actions(actions: set[str], preset: str) -> set[str]:
    if preset:
        if preset not in EMAIL_ACCESS_PRESETS:
            raise ValueError("invalid_preset")
        actions = set(EMAIL_ACCESS_PRESETS[preset])
    if not actions or not actions.issubset(EMAIL_ACCESS_FIELDS):
        raise ValueError("invalid_actions")
    return actions


def plan_email_role_batch(
    db: Session,
    *,
    role_ids: set[int],
    channel_ids: set[int],
    operation: str,
    actions: set[str],
    preset: str = "",
    visibility_mode: str = "scope_all",
    source_role_id: int | None = None,
    source_channel_id: int | None = None,
) -> list[EmailAccessChange]:
    if not role_ids or not channel_ids:
        raise ValueError("empty_selection")
    if operation not in {"apply", "revoke", "copy_role", "copy_channel"}:
        raise ValueError("invalid_operation")
    if visibility_mode not in {"scope_all", "direct_only", "consult"}:
        raise ValueError("invalid_scope")
    actions = normalize_actions(actions, preset) if operation in {"apply", "revoke"} else set()
    if operation == "copy_role" and not source_role_id:
        raise ValueError("missing_copy_source")
    if operation == "copy_channel" and not source_channel_id:
        raise ValueError("missing_copy_source")

    grants = list(
        db.scalars(
            select(EmailChannelRole).where(
                EmailChannelRole.channel_id.in_(
                    channel_ids | ({source_channel_id} if source_channel_id else set())
                ),
                EmailChannelRole.role_id.in_(
                    role_ids | ({source_role_id} if source_role_id else set())
                ),
            )
        )
    )
    existing = {(item.channel_id, item.role_id): item for item in grants}
    changes: list[EmailAccessChange] = []
    for channel_id in sorted(channel_ids):
        for role_id in sorted(role_ids):
            grant = existing.get((channel_id, role_id))
            before = grant_snapshot(grant)
            after = dict(before)
            if operation in {"apply", "revoke"}:
                enabled = operation == "apply"
                for field in actions:
                    after[field] = enabled
                if operation == "apply":
                    after["visibility_mode"] = visibility_mode
            elif operation == "copy_role":
                after = grant_snapshot(existing.get((channel_id, int(source_role_id))))
            else:
                after = grant_snapshot(existing.get((int(source_channel_id), role_id)))

            if (
                any(after[field] for field in EMAIL_ACCESS_FIELDS if field != "can_read")
                and not after["can_read"]
            ):
                raise ValueError("read_required")
            if before != after:
                changes.append(
                    EmailAccessChange(
                        channel_id=channel_id,
                        role_id=role_id,
                        before=before,
                        after=after,
                        grant=grant,
                    )
                )
    return changes


def apply_email_role_batch(db: Session, changes: list[EmailAccessChange]) -> None:
    for change in changes:
        grant = change.grant or EmailChannelRole(
            channel_id=change.channel_id,
            role_id=change.role_id,
        )
        for field in EMAIL_ACCESS_FIELDS:
            setattr(grant, field, bool(change.after[field]))
        grant.visibility_mode = str(change.after["visibility_mode"])
        db.add(grant)
