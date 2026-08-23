"""Destination-side validation for an already anonymized JSONL stream."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from app.platform.anonymized_stream import (
    FIELD_MAP,
    UnsafePayload,
    allowed_output_fields,
    validate_payload,
)


def validated_envelopes(lines: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    for number, raw in enumerate(lines, 1):
        if len(raw) > 1_000_000:
            raise UnsafePayload(f"line {number} exceeds the 1 MB safety limit")
        try:
            envelope = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UnsafePayload(f"invalid JSONL at line {number}") from exc
        if (
            set(envelope) != {"schema", "pilot", "table", "data"}
            or envelope["schema"] != 2
            or envelope["pilot"] != "eight-table"
        ):
            raise UnsafePayload(f"invalid envelope at line {number}")
        table = envelope["table"]
        if table not in FIELD_MAP or not isinstance(envelope["data"], dict):
            raise UnsafePayload(f"unapproved table or payload at line {number}")
        unknown = set(envelope["data"]) - allowed_output_fields(table)
        if unknown:
            raise UnsafePayload(f"unapproved output fields at line {number}: {sorted(unknown)}")
        validate_payload(table, envelope["data"])
        yield envelope
