from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.partners.compat import PartnerRecord
from app.partners.contracts import PartnerReference, PartnerSummary


class PartnersFacade:
    """Query/application facade over the compatibility storage.

    The facade owns partner identity and summaries. Module-specific relationships
    remain owned by their modules and refer to ``PartnerReference`` IDs.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_record(self, reference: PartnerReference | int) -> PartnerRecord | None:
        partner_id = reference.id if isinstance(reference, PartnerReference) else reference
        return self.db.get(PartnerRecord, partner_id)

    def require_record(self, reference: PartnerReference | int) -> PartnerRecord:
        record = self.get_record(reference)
        if record is None:
            raise LookupError("Partner not found")
        return record

    def list_records(self, *, query: str = "", active: bool | None = None) -> list[PartnerRecord]:
        statement = select(PartnerRecord).order_by(PartnerRecord.name)
        if active is not None:
            statement = statement.where(PartnerRecord.active.is_(active))
        if query.strip():
            token = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    PartnerRecord.name.ilike(token),
                    PartnerRecord.legal_name.ilike(token),
                    PartnerRecord.tax_id.ilike(token),
                    PartnerRecord.email.ilike(token),
                )
            )
        return list(self.db.scalars(statement))

    def summaries(self, partner_ids: Iterable[int]) -> dict[int, PartnerSummary]:
        ids = {int(item) for item in partner_ids if int(item) > 0}
        if not ids:
            return {}
        records = self.db.scalars(select(PartnerRecord).where(PartnerRecord.id.in_(ids)))
        return {record.id: self.summary(record) for record in records}

    @staticmethod
    def summary(record: PartnerRecord) -> PartnerSummary:
        return PartnerSummary(
            reference=PartnerReference(record.id),
            display_name=record.name,
            legal_name=record.legal_name,
            tax_id=record.tax_id,
            primary_email=record.email,
            primary_phone=record.phone,
            active=record.active,
        )

    @staticmethod
    def historical_summary(
        snapshot: dict[str, object] | None, *, can_read_partners: bool
    ) -> PartnerSummary | None:
        """Restore an authorized minimal snapshot without a live module lookup."""

        if not can_read_partners or not snapshot:
            return None
        try:
            reference = PartnerReference.parse(str(snapshot["reference"]))
            return PartnerSummary(
                reference=reference,
                display_name=str(snapshot["display_name"]),
                legal_name=_optional_text(snapshot.get("legal_name")),
                tax_id=_optional_text(snapshot.get("tax_id")),
                primary_email=_optional_text(snapshot.get("primary_email")),
                primary_phone=_optional_text(snapshot.get("primary_phone")),
                active=bool(snapshot.get("active", False)),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _optional_text(value: object) -> str | None:
    return str(value) if value not in (None, "") else None
