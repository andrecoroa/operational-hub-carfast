"""Fail-closed contracts for the eight-table anonymization pilot."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

Action = Literal["surrogate", "synthetic", "canonical", "scalar", "omit", "document_fixture"]


@dataclass(frozen=True)
class FieldRule:
    action: Action
    kind: str = "token"
    nullable: bool = True
    max_length: int = 200
    namespace: str | None = None
    canonical: str | None = None


def _id(ns: str, nullable: bool = False) -> FieldRule:
    return FieldRule("surrogate", namespace=ns, nullable=nullable, max_length=48)


def _canon(pattern: str, nullable: bool = True, maximum: int = 64) -> FieldRule:
    return FieldRule("canonical", nullable=nullable, max_length=maximum, canonical=pattern)


FIELD_MAP: dict[str, dict[str, FieldRule]] = {
    "users": {
        "id": _id("user"),
        "active": FieldRule("scalar", "bool", False),
        "email": FieldRule("synthetic", "email", max_length=64),
        "name": FieldRule("synthetic", "person", max_length=64),
        "password_hash": FieldRule("omit"),
    },
    "stock_suppliers": {
        "id": _id("supplier"),
        "active": FieldRule("scalar", "bool", False),
        "name": FieldRule("synthetic", "company", max_length=64),
        "tax_id": FieldRule("synthetic", "tax_id", max_length=32),
        "email": FieldRule("synthetic", "email", max_length=64),
        "phone": FieldRule("synthetic", "phone", max_length=32),
        "address": FieldRule("omit"),
        "address_line2": FieldRule("omit"),
        "postal_code": FieldRule("omit"),
        "city": FieldRule("omit"),
        "legal_name": FieldRule("synthetic", "company", max_length=64),
        "registration_number": FieldRule("synthetic", max_length=32),
        "website": FieldRule("omit"),
        "contact_name": FieldRule("synthetic", "person", max_length=64),
        "secondary_email": FieldRule("synthetic", "email", max_length=64),
        "secondary_phone": FieldRule("synthetic", "phone", max_length=32),
        "notes": FieldRule("omit"),
    },
    "vehicles": {
        "id": _id("vehicle"),
        "active": FieldRule("scalar", "bool", False),
        "lifecycle_status": _canon(r"^(?:active|inactive|sold|disposed|archived|draft)$"),
        "operational_status": _canon(
            r"^(?:available|in_use|workshop|maintenance|immobilized|sold|inactive)$"
        ),
        "plate": FieldRule("synthetic", "plate", max_length=32),
        "vin": FieldRule("synthetic", "vin", max_length=32),
        "notes": FieldRule("omit"),
    },
    "tasks": {
        "id": _id("task"),
        "status": _canon(
            r"^(?:open|pending|in_progress|blocked|completed|cancelled|closed|done)$", False
        ),
        "assigned_to_id": _id("user", True),
        "parent_task_id": _id("task", True),
        "team_id": _id("team", True),
        "created_by_id": _id("user", True),
        "title": FieldRule("omit"),
        "description": FieldRule("omit"),
        "customer_name": FieldRule("synthetic", "person", max_length=64),
        "customer_contact": FieldRule("synthetic", "person", max_length=64),
        "customer_email": FieldRule("synthetic", "email", max_length=64),
        "customer_phone": FieldRule("synthetic", "phone", max_length=32),
        "plate": FieldRule("synthetic", "plate", max_length=32),
    },
    "management_processes": {
        "id": _id("management_process"),
        "status": _canon(
            r"^(?:draft|open|pending|in_progress|blocked|completed|cancelled|closed)$", False
        ),
        "process_type_id": _id("process_type", True),
        "phase": _canon(r"^[a-z][a-z0-9_]{0,31}$"),
        "priority": _canon(r"^(?:low|normal|medium|high|urgent|critical)$"),
        "internal_reference": FieldRule("synthetic", max_length=32),
        "plate": FieldRule("synthetic", "plate", max_length=32),
        "customer_name": FieldRule("synthetic", "person", max_length=64),
        "driver_name": FieldRule("synthetic", "person", max_length=64),
        "title": FieldRule("omit"),
        "pending_detail": FieldRule("omit"),
        "raw_summary_json": FieldRule("omit"),
    },
    "email_messages": {
        "id": _id("email_message"),
        "thread_id": _id("email_thread"),
        "sender": FieldRule("synthetic", "email", max_length=64),
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
        "id": _id("document"),
        "status": _canon(
            r"^(?:received|pending|processing|classified|approved|rejected|archived|active|inactive)$",
            False,
        ),
        "document_type": _canon(r"^[a-z][a-z0-9_.-]{0,47}$"),
        "classification": _canon(r"^[a-z][a-z0-9_.-]{0,47}$"),
        "vehicle_id": _id("vehicle", True),
        "task_id": _id("task", True),
        "workshop_process_id": _id("workshop_process", True),
        "incident_id": _id("incident", True),
        "title": FieldRule("omit"),
        "source_sender": FieldRule("synthetic", "email", max_length=64),
        "source_subject": FieldRule("omit"),
        "original_name": FieldRule("document_fixture"),
        "file_name": FieldRule("document_fixture"),
        "file_size": FieldRule("document_fixture"),
        "storage_path": FieldRule("document_fixture"),
        "storage_key": FieldRule("document_fixture"),
        "external_url": FieldRule("document_fixture"),
        "folder_path": FieldRule("omit"),
        "file_hash": FieldRule("document_fixture"),
        "plate": FieldRule("synthetic", "plate", max_length=32),
        "customer_name": FieldRule("synthetic", "person", max_length=64),
        "supplier_name": FieldRule("synthetic", "company", max_length=64),
    },
    "audit_log": {
        "id": _id("audit"),
        "user_id": _id("user", True),
        "action": _canon(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,3}$", False),
        "entity_type": _canon(
            r"^(?:user|supplier|vehicle|task|management_process|email_message|document)$"
        ),
        "entity_id": FieldRule("surrogate", namespace="typed_entity", max_length=48),
        "detail": FieldRule("omit"),
        "before_json": FieldRule("omit"),
        "after_json": FieldRule("omit"),
    },
}
ENTITY_NAMESPACE = {
    "user": "user",
    "supplier": "supplier",
    "vehicle": "vehicle",
    "task": "task",
    "management_process": "management_process",
    "email_message": "email_message",
    "document": "document",
}
FORBIDDEN_FIELD_PARTS = ("body", "text", "ocr", "password", "secret", "token", "path", "notes")
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE = re.compile(r"(?<!\d)(?:\+?351)?[29]\d{8}(?!\d)")
NIF = re.compile(r"(?<!\d)[1235689]\d{8}(?!\d)")
PLATE = re.compile(
    r"\b(?:[A-Z]{2}-\d{2}-[A-Z]{2}|\d{2}-[A-Z]{2}-\d{2}|[A-Z]{2}-\d{2}-\d{2})\b", re.I
)
SYNTHETIC_TOKEN = re.compile(r"^(?:Person-|Company-|S-|X|T|P-|V-)[0-9a-f]{12}$")
SYNTHETIC_EMAIL = re.compile(r"^user-[0-9a-f]{12}@invalid\.example$")
SURROGATE = re.compile(r"^R-[a-z_]{2,24}-[0-9a-f]{16}$")


class UnsafePayload(ValueError):
    pass


class EphemeralSynthesizer:
    def __init__(self, key: bytes):
        if len(key) < 32:
            raise ValueError("ephemeral key must contain at least 32 bytes")
        self._key = key

    def _digest(self, ns: str, value: object, size: int = 12) -> str:
        return hmac.new(self._key, f"{ns}:{value}".encode(), hashlib.sha256).hexdigest()[:size]

    def reference(self, ns: str, value: object) -> str:
        return f"R-{ns}-{self._digest(ns, value, 16)}"

    def token(self, kind: str, value: object) -> str:
        s = self._digest(kind, value)
        return {
            "email": f"user-{s}@invalid.example",
            "person": f"Person-{s}",
            "company": f"Company-{s}",
            "tax_id": f"X{s}",
            "phone": f"T{s}",
            "plate": f"P-{s}",
            "vin": f"V-{s}",
        }.get(kind, f"S-{s}")


def _reference(
    rule: FieldRule, field: str, value: Any, row: Mapping[str, Any], synth: EphemeralSynthesizer
) -> str | None:
    if value is None:
        if not rule.nullable:
            raise UnsafePayload(f"required reference is null: {field}")
        return None
    ns = rule.namespace or "unknown"
    if ns == "typed_entity":
        ns = ENTITY_NAMESPACE.get(str(row.get("entity_type")), "")
        if not ns:
            return None
    if isinstance(value, (dict, list, bool)) or not isinstance(value, (str, int)):
        raise UnsafePayload(f"invalid reference type: {field}")
    return synth.reference(ns, value)


def transform_row(
    table: str, row: Mapping[str, Any], synth: EphemeralSynthesizer
) -> dict[str, Any]:
    rules = FIELD_MAP.get(table)
    if rules is None:
        raise UnsafePayload(f"table is not allowlisted: {table}")
    unknown = set(row) - set(rules)
    if unknown:
        raise UnsafePayload(f"unclassified fields in {table}: {sorted(unknown)}")
    out = {}
    object_present = False
    for field, value in row.items():
        rule = rules[field]
        if rule.action == "surrogate":
            out[field] = _reference(rule, field, value, row, synth)
        elif rule.action == "synthetic":
            out[field] = None if value is None else synth.token(rule.kind, value)
        elif rule.action in {"canonical", "scalar"}:
            out[field] = value
        elif rule.action == "document_fixture" and value not in (None, "", 0, False):
            object_present = True
    if table == "documents":
        fixture = b"CarFast synthetic document fixture\n" if object_present else b""
        out.update(
            fixture_object_count=int(object_present),
            fixture_bytes=len(fixture),
            fixture_sha256=hashlib.sha256(fixture).hexdigest() if fixture else None,
        )
    validate_payload(table, out)
    return out


def _validate_field(table: str, field: str, value: Any, rule: FieldRule) -> None:
    if value is None:
        if not rule.nullable:
            raise UnsafePayload(f"non-nullable field is null: {table}.{field}")
        return
    if rule.action == "surrogate":
        if not isinstance(value, str) or not SURROGATE.fullmatch(value):
            raise UnsafePayload(f"raw or malformed reference: {table}.{field}")
        return
    if rule.action == "scalar":
        if rule.kind == "bool" and type(value) is not bool:
            raise UnsafePayload(f"invalid boolean: {table}.{field}")
        return
    if not isinstance(value, str) or not value or len(value) > rule.max_length:
        raise UnsafePayload(f"invalid string shape: {table}.{field}")
    if rule.action == "canonical" and not re.fullmatch(rule.canonical or r"(?!)", value):
        raise UnsafePayload(f"non-canonical value: {table}.{field}")
    if rule.action == "synthetic" and not (
        SYNTHETIC_TOKEN.fullmatch(value) or SYNTHETIC_EMAIL.fullmatch(value)
    ):
        raise UnsafePayload(f"non-synthetic value: {table}.{field}")


def validate_payload(table: str, payload: Mapping[str, Any]) -> None:
    if table not in FIELD_MAP or not isinstance(payload, Mapping):
        raise UnsafePayload("unapproved table or payload")
    unknown = set(payload) - allowed_output_fields(table)
    if unknown:
        raise UnsafePayload(f"unapproved output fields: {sorted(unknown)}")
    required = {
        f
        for f, r in FIELD_MAP[table].items()
        if r.action in {"surrogate", "synthetic", "canonical", "scalar"} and not r.nullable
    }
    missing = required - set(payload)
    if missing:
        raise UnsafePayload(f"missing required fields: {sorted(missing)}")
    for field, value in payload.items():
        if isinstance(value, (dict, list)):
            raise UnsafePayload(f"nested value rejected: {table}.{field}")
        if any(p in field.lower() for p in FORBIDDEN_FIELD_PARTS):
            raise UnsafePayload(f"forbidden field escaped transformation: {table}.{field}")
        if field.startswith("fixture_"):
            if field in {"fixture_object_count", "fixture_bytes"} and (
                type(value) is not int or not 0 <= value <= 10_000_000
            ):
                raise UnsafePayload(f"invalid fixture metric: {field}")
            if (
                field == "fixture_sha256"
                and value is not None
                and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value))
            ):
                raise UnsafePayload("invalid fixture hash")
            continue
        _validate_field(table, field, value, FIELD_MAP[table][field])
        if (
            isinstance(value, str)
            and not (
                SYNTHETIC_TOKEN.fullmatch(value)
                or SYNTHETIC_EMAIL.fullmatch(value)
                or SURROGATE.fullmatch(value)
            )
            and any(p.search(value) for p in (EMAIL, PHONE, NIF, PLATE))
        ):
            raise UnsafePayload(f"recognizable identifier in {table}.{field}")


def allowed_output_fields(table: str) -> set[str]:
    fields = {
        f
        for f, r in FIELD_MAP[table].items()
        if r.action in {"surrogate", "synthetic", "canonical", "scalar"}
    }
    if table == "documents":
        fields.update({"fixture_object_count", "fixture_bytes", "fixture_sha256"})
    return fields


def stream_jsonl(
    records: Iterable[tuple[str, Mapping[str, Any]]], synth: EphemeralSynthesizer
) -> Iterator[bytes]:
    for table, row in records:
        envelope = {
            "schema": 2,
            "pilot": "eight-table",
            "table": table,
            "data": transform_row(table, row, synth),
        }
        yield (
            json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
        ).encode("ascii")
