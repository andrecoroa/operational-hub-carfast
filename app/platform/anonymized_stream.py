"""Fail-closed, fixture-testable preparation for an anonymized rehearsal stream."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

Action = Literal["preserve", "synthetic", "omit", "document_fixture"]


@dataclass(frozen=True)
class FieldRule:
    action: Action
    kind: str = "token"


FIELD_MAP: dict[str, dict[str, FieldRule]] = {
    "users": {
        "id": FieldRule("preserve"),
        "active": FieldRule("preserve"),
        "email": FieldRule("synthetic", "email"),
        "name": FieldRule("synthetic", "person"),
        "password_hash": FieldRule("omit"),
    },
    "stock_suppliers": {
        "id": FieldRule("preserve"),
        "active": FieldRule("preserve"),
        "name": FieldRule("synthetic", "company"),
        "tax_id": FieldRule("synthetic", "tax_id"),
        "email": FieldRule("synthetic", "email"),
        "phone": FieldRule("synthetic", "phone"),
        "address": FieldRule("omit"),
        "address_line2": FieldRule("omit"),
        "postal_code": FieldRule("omit"),
        "city": FieldRule("omit"),
        "legal_name": FieldRule("synthetic", "company"),
        "registration_number": FieldRule("synthetic"),
        "website": FieldRule("omit"),
        "contact_name": FieldRule("synthetic", "person"),
        "secondary_email": FieldRule("synthetic", "email"),
        "secondary_phone": FieldRule("synthetic", "phone"),
        "notes": FieldRule("omit"),
    },
    "vehicles": {
        "id": FieldRule("preserve"),
        "active": FieldRule("preserve"),
        "lifecycle_status": FieldRule("preserve"),
        "operational_status": FieldRule("preserve"),
        "plate": FieldRule("synthetic", "plate"),
        "vin": FieldRule("synthetic", "vin"),
        "notes": FieldRule("omit"),
    },
    "tasks": {
        "id": FieldRule("preserve"),
        "status": FieldRule("preserve"),
        "assigned_to_id": FieldRule("preserve"),
        "parent_task_id": FieldRule("preserve"),
        "team_id": FieldRule("preserve"),
        "created_by_id": FieldRule("preserve"),
        "title": FieldRule("omit"),
        "description": FieldRule("omit"),
        "customer_name": FieldRule("synthetic", "person"),
        "customer_contact": FieldRule("synthetic", "person"),
        "customer_email": FieldRule("synthetic", "email"),
        "customer_phone": FieldRule("synthetic", "phone"),
        "plate": FieldRule("synthetic", "plate"),
    },
    "management_processes": {
        "id": FieldRule("preserve"),
        "status": FieldRule("preserve"),
        "process_type_id": FieldRule("preserve"),
        "phase": FieldRule("preserve"),
        "priority": FieldRule("preserve"),
        "internal_reference": FieldRule("synthetic"),
        "plate": FieldRule("synthetic", "plate"),
        "customer_name": FieldRule("synthetic", "person"),
        "driver_name": FieldRule("synthetic", "person"),
        "title": FieldRule("omit"),
        "pending_detail": FieldRule("omit"),
        "raw_summary_json": FieldRule("omit"),
    },
    "email_messages": {
        "id": FieldRule("preserve"),
        "thread_id": FieldRule("preserve"),
        "sender": FieldRule("synthetic", "email"),
        "recipients_json": FieldRule("omit"),
        "cc_json": FieldRule("omit"),
        "bcc_json": FieldRule("omit"),
        "subject": FieldRule("omit"),
        "text_body": FieldRule("omit"),
        "html_body": FieldRule("omit"),
        "headers_json": FieldRule("omit"),
        "template_snapshot_json": FieldRule("omit"),
    },
    "documents": {
        "id": FieldRule("preserve"),
        "status": FieldRule("preserve"),
        "document_type": FieldRule("preserve"),
        "classification": FieldRule("preserve"),
        "vehicle_id": FieldRule("preserve"),
        "task_id": FieldRule("preserve"),
        "workshop_process_id": FieldRule("preserve"),
        "incident_id": FieldRule("preserve"),
        "title": FieldRule("omit"),
        "source_sender": FieldRule("synthetic", "email"),
        "source_subject": FieldRule("omit"),
        "original_name": FieldRule("document_fixture"),
        "file_name": FieldRule("document_fixture"),
        "file_size": FieldRule("document_fixture"),
        "storage_path": FieldRule("document_fixture"),
        "storage_key": FieldRule("omit"),
        "external_url": FieldRule("omit"),
        "folder_path": FieldRule("omit"),
        "file_hash": FieldRule("document_fixture"),
        "plate": FieldRule("synthetic", "plate"),
        "customer_name": FieldRule("synthetic", "person"),
        "supplier_name": FieldRule("synthetic", "company"),
    },
    "audit_log": {
        "id": FieldRule("preserve"),
        "user_id": FieldRule("preserve"),
        "action": FieldRule("preserve"),
        "entity_type": FieldRule("preserve"),
        "entity_id": FieldRule("preserve"),
        "detail": FieldRule("omit"),
        "before_json": FieldRule("omit"),
        "after_json": FieldRule("omit"),
    },
}

FORBIDDEN_FIELD_PARTS = ("body", "text", "ocr", "password", "secret", "token", "path", "notes")
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE = re.compile(r"(?<!\d)(?:\+?351)?[29]\d{8}(?!\d)")
NIF = re.compile(r"(?<!\d)[1235689]\d{8}(?!\d)")
PLATE = re.compile(
    r"\b(?:[A-Z]{2}-\d{2}-[A-Z]{2}|\d{2}-[A-Z]{2}-\d{2}|[A-Z]{2}-\d{2}-\d{2})\b",
    re.I,
)
SAFE_TECHNICAL = re.compile(r"^[A-Z0-9_.:/@+-]{1,200}$", re.I)
SYNTHETIC_TOKEN = re.compile(r"^(?:Person-|Company-|S-|X|T|P-|V-)[0-9a-f]{12}$")
SYNTHETIC_EMAIL = re.compile(r"^user-[0-9a-f]{12}@invalid\.example$")


class UnsafePayload(ValueError):
    pass


class EphemeralSynthesizer:
    def __init__(self, key: bytes):
        if len(key) < 32:
            raise ValueError("ephemeral key must contain at least 32 bytes")
        self._key = key

    def token(self, kind: str, value: object) -> str:
        digest = hmac.new(self._key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()
        suffix = digest[:12]
        return {
            "email": f"user-{suffix}@invalid.example",
            "person": f"Person-{suffix}",
            "company": f"Company-{suffix}",
            "tax_id": f"X{suffix}",
            "phone": f"T{suffix}",
            "plate": f"P-{suffix}",
            "vin": f"V-{suffix}",
        }.get(kind, f"S-{suffix}")


def transform_row(
    table: str, row: Mapping[str, Any], synth: EphemeralSynthesizer
) -> dict[str, Any]:
    rules = FIELD_MAP.get(table)
    if rules is None:
        raise UnsafePayload(f"table is not allowlisted: {table}")
    unknown = set(row) - set(rules)
    if unknown:
        raise UnsafePayload(f"unclassified fields in {table}: {sorted(unknown)}")
    output: dict[str, Any] = {}
    has_document_fixture = False
    for field, value in row.items():
        rule = rules[field]
        if rule.action == "preserve":
            output[field] = value
        elif rule.action == "synthetic":
            output[field] = None if value is None else synth.token(rule.kind, value)
        elif rule.action == "document_fixture":
            has_document_fixture = True
    if has_document_fixture:
        fixture = b"CarFast synthetic document fixture\n"
        output["fixture_object_count"] = 1
        output["fixture_bytes"] = len(fixture)
        output["fixture_sha256"] = hashlib.sha256(fixture).hexdigest()
    validate_payload(table, output)
    return output


def validate_payload(table: str, payload: Mapping[str, Any]) -> None:
    for field, value in payload.items():
        lower = field.lower()
        if any(part in lower for part in FORBIDDEN_FIELD_PARTS):
            raise UnsafePayload(f"forbidden field escaped transformation: {table}.{field}")
        if isinstance(value, str) and (
            SYNTHETIC_TOKEN.fullmatch(value) or SYNTHETIC_EMAIL.fullmatch(value)
        ):
            continue
        if isinstance(value, str) and any(
            pattern.search(value) for pattern in (PHONE, NIF, PLATE)
        ):
            raise UnsafePayload(f"recognizable identifier in {table}.{field}")
        if (
            isinstance(value, str)
            and EMAIL.search(value)
            and not value.endswith("@invalid.example")
        ):
            raise UnsafePayload(f"recognizable email in {table}.{field}")
        if isinstance(value, str) and not SAFE_TECHNICAL.fullmatch(value):
            raise UnsafePayload(f"free text or unsafe characters in {table}.{field}")


def allowed_output_fields(table: str) -> set[str]:
    fields = {
        field
        for field, rule in FIELD_MAP[table].items()
        if rule.action in {"preserve", "synthetic"}
    }
    if any(rule.action == "document_fixture" for rule in FIELD_MAP[table].values()):
        fields.update({"fixture_object_count", "fixture_bytes", "fixture_sha256"})
    return fields


def stream_jsonl(
    records: Iterable[tuple[str, Mapping[str, Any]]], synth: EphemeralSynthesizer
) -> Iterator[bytes]:
    for table, row in records:
        envelope = {"schema": 1, "table": table, "data": transform_row(table, row, synth)}
        yield (json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode()
