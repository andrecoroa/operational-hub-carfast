from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.email import EmailTemplate


def ranked_supplier_email_templates(
    db: Session,
    *,
    supplier_id: int | None = None,
    supplier_type_ids: set[int] | None = None,
    module_code: str | None = None,
    context_code: str | None = None,
    channel_id: int | None = None,
) -> list[EmailTemplate]:
    """Return only templates applicable to a new use, most specific first.

    A template bound to another supplier/type/module is never leaked as a
    fallback. Inactive records remain queryable by historical email snapshots,
    but are intentionally excluded from new composition.
    """

    type_ids = supplier_type_ids or set()
    statement = select(EmailTemplate).where(EmailTemplate.active.is_(True))
    if channel_id is not None:
        statement = statement.where(
            or_(EmailTemplate.channel_id.is_(None), EmailTemplate.channel_id == channel_id)
        )
    candidates = list(db.scalars(statement))
    applicable = [
        item
        for item in candidates
        if (item.supplier_id is None or item.supplier_id == supplier_id)
        and (item.supplier_type_id is None or item.supplier_type_id in type_ids)
        and (item.module_code is None or item.module_code == module_code)
        and (item.context_code is None or item.context_code == context_code)
    ]

    def rank(item: EmailTemplate) -> tuple[int, int, str]:
        if supplier_id is not None and item.supplier_id == supplier_id:
            specificity = 0
        elif item.supplier_type_id is not None:
            specificity = 1
        elif module_code and item.module_code == module_code:
            specificity = 2
        elif context_code and item.context_code == context_code:
            specificity = 3
        else:
            specificity = 4
        channel_rank = 0 if channel_id is not None and item.channel_id == channel_id else 1
        return specificity, channel_rank, item.name.casefold()

    return sorted(applicable, key=rank)


def email_template_snapshot(
    template: EmailTemplate | None,
    *,
    rendered_subject: str | None = None,
    rendered_body: str | None = None,
) -> dict | None:
    if template is None:
        return None
    return {
        "code": template.code,
        "name": template.name,
        "version": template.version,
        "subject_template": template.subject_template,
        "body_template": template.body_template,
        "allowed_variables": list(template.allowed_variables_json or []),
        "channel_id": template.channel_id,
        "category_id": template.category_id,
        "subcategory_id": template.subcategory_id,
        "supplier_id": template.supplier_id,
        "supplier_type_id": template.supplier_type_id,
        "module_code": template.module_code,
        "context_code": template.context_code,
        "rendered_subject": rendered_subject,
        "rendered_body": rendered_body,
    }
