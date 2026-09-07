"""Safely repair one document-to-vehicle assignment.

Dry-run is the default. Applying requires all expected identity values so the
command fails closed if production data has changed since review.
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.documents import Document, DocumentEvent, DocumentLink
from app.models.vehicles import Vehicle
from app.services.audit import record_audit


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser()
    command.add_argument("--document-id", type=int, required=True)
    command.add_argument("--expected-current-plate", required=True)
    command.add_argument("--target-plate", required=True)
    command.add_argument("--expected-document-number", required=True)
    command.add_argument("--expected-vin", required=True)
    command.add_argument("--apply", action="store_true")
    return command


def main() -> None:
    args = parser().parse_args()
    with SessionLocal() as db:
        document = db.get(Document, args.document_id)
        if document is None:
            raise SystemExit(f"document {args.document_id} not found")

        target = db.scalar(select(Vehicle).where(Vehicle.plate == args.target_plate))
        if target is None:
            raise SystemExit(f"target vehicle {args.target_plate} not found")
        if target.vin and target.vin != args.expected_vin:
            raise SystemExit("target vehicle VIN does not match expected VIN")

        links = db.scalars(
            select(DocumentLink).where(DocumentLink.document_id == document.id)
        ).all()
        snapshot = {
            "document_id": document.id,
            "title": document.title,
            "plate": document.plate,
            "vehicle_id": document.vehicle_id,
            "target_vehicle_id": target.id,
            "target_plate": target.plate,
            "target_vin": target.vin,
            "document_links": [
                {"id": link.id, "entity_type": link.entity_type, "entity_id": link.entity_id}
                for link in links
            ],
        }
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))

        if document.plate != args.expected_current_plate:
            raise SystemExit("document plate does not match expected current plate")
        searchable = " ".join(
            str(value or "")
            for value in (document.title, document.original_name, document.file_name)
        )
        if args.expected_document_number not in searchable:
            raise SystemExit("document number is not present in document metadata")
        if any(link.entity_type == "workshop_phased_process" for link in links):
            raise SystemExit("document has workshop process links; explicit process migration required")
        if not args.apply:
            print("DRY_RUN_OK")
            return

        before = {"plate": document.plate, "vehicle_id": document.vehicle_id}
        document.plate = target.plate
        document.vehicle_id = target.id
        document.status = "associated"
        after = {"plate": document.plate, "vehicle_id": document.vehicle_id}
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="corrected.vehicle_assignment",
                old_value=json.dumps(before, ensure_ascii=False),
                new_value=json.dumps(after, ensure_ascii=False),
                user_id=None,
            )
        )
        record_audit(
            db,
            action="document.vehicle_assignment_corrected",
            entity_type="document",
            entity_id=document.id,
            detail=(
                f"Authorized correction: {args.expected_current_plate} -> {args.target_plate}; "
                f"invoice {args.expected_document_number}; VIN {args.expected_vin}"
            ),
            before_json=before,
            after_json=after,
        )
        db.commit()
        print("APPLIED_OK")


if __name__ == "__main__":
    main()
