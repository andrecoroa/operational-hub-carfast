from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def record_audit(
    db: Session,
    action: str,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    detail: str | None = None,
    user_id: int | None = None,
    before_json: dict | None = None,
    after_json: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        detail=detail,
        before_json=before_json,
        after_json=after_json,
    )
    db.add(entry)
    return entry
