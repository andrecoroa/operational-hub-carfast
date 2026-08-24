"""Closed, role-aware configuration contract for an integral transfer."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping

SCHEMA_VERSION = 1
SHARED_ENV = {
    "bundle_id": "INTEGRAL_BUNDLE_ID",
    "bundle_timeout_seconds": "INTEGRAL_BUNDLE_TIMEOUT_SECONDS",
    "client_timeout_seconds": "INTEGRAL_CLIENT_TIMEOUT_SECONDS",
    "cutoff_id": "INTEGRAL_CUTOFF_ID",
    "destination_host": "INTEGRAL_DESTINATION_HOST",
    "destination_port": "INTEGRAL_DESTINATION_PORT",
    "destination_service": "INTEGRAL_DESTINATION_SERVICE",
    "expected_destination_host": "INTEGRAL_EXPECTED_DESTINATION_HOST",
    "expected_destination_port": "INTEGRAL_EXPECTED_DESTINATION_PORT",
    "expected_hmac_snapshot_sha256": "INTEGRAL_EXPECTED_HMAC_SNAPSHOT_SHA256",
    "external_integrations_enabled": "EXTERNAL_INTEGRATIONS_ENABLED",
    "hmac_snapshot_sha256": "INTEGRAL_HMAC_SNAPSHOT_SHA256",
    "max_stream_bytes": "INTEGRAL_MAX_STREAM_BYTES",
    "real_data_allowed": "REAL_DATA_ALLOWED",
    "release_sha": "INTEGRAL_RELEASE_SHA",
    "source_service": "INTEGRAL_SOURCE_SERVICE",
}
ROLE_ENV = {
    "sender": {
        "database_phase": "INTEGRAL_DATABASE_DUMP_PHASE",
        "expected_database_host": "INTEGRAL_EXPECTED_DATABASE_HOST",
        "expected_database_name": "INTEGRAL_EXPECTED_DATABASE_NAME",
    },
    "receiver": {
        "database_phase": "INTEGRAL_DATABASE_DESTINATION_PHASE",
        "declared_bundle_bytes": "INTEGRAL_DECLARED_BUNDLE_BYTES",
        "expected_database_host": "INTEGRAL_EXPECTED_DATABASE_HOST",
        "expected_database_name": "INTEGRAL_EXPECTED_DATABASE_NAME",
        "source_revision": "INTEGRAL_SOURCE_REVISION",
        "spool_root": "INTEGRAL_SPOOL_ROOT",
    },
}


def canonical_manifest(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def manifest_sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_manifest(value).encode()).hexdigest()


def validate_integral_config(role: str, environment: Mapping[str, str] | None = None) -> str:
    env = environment or os.environ
    if role not in ROLE_ENV:
        raise RuntimeError("integral config role must be sender or receiver")
    raw = env.get("INTEGRAL_CONFIG_MANIFEST", "")
    expected_fingerprint = env.get("INTEGRAL_CONFIG_SHA256", "")
    if not raw or not expected_fingerprint:
        raise RuntimeError("integral config manifest and fingerprint are required")
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("integral config manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or set(manifest) != {
        "receiver", "schema_version", "sender", "shared"
    }:
        raise RuntimeError("integral config manifest has unknown or missing sections")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise RuntimeError("integral config schema version mismatch")
    if not isinstance(manifest["shared"], dict) or set(manifest["shared"]) != set(SHARED_ENV):
        raise RuntimeError("integral config shared claims are not closed")
    for item_role, claims in ROLE_ENV.items():
        if not isinstance(manifest[item_role], dict) or set(manifest[item_role]) != set(claims):
            raise RuntimeError(f"integral config {item_role} claims are not closed")
    observed_fingerprint = manifest_sha256(manifest)
    if len(expected_fingerprint) != 64 or observed_fingerprint != expected_fingerprint:
        raise RuntimeError("integral config fingerprint mismatch")
    for claim, env_name in SHARED_ENV.items():
        if not env.get(env_name) or str(manifest["shared"][claim]) != env[env_name]:
            raise RuntimeError(f"integral config claim mismatch: {env_name}")
    for claim, env_name in ROLE_ENV[role].items():
        if not env.get(env_name) or str(manifest[role][claim]) != env[env_name]:
            raise RuntimeError(f"integral config claim mismatch: {env_name}")
    if (
        manifest["shared"]["hmac_snapshot_sha256"]
        != manifest["shared"]["expected_hmac_snapshot_sha256"]
    ):
        raise RuntimeError("integral config HMAC snapshots differ")
    if manifest["shared"]["destination_host"] != manifest["shared"]["expected_destination_host"]:
        raise RuntimeError("integral config destination hosts differ")
    if manifest["shared"]["destination_port"] != manifest["shared"]["expected_destination_port"]:
        raise RuntimeError("integral config destination ports differ")
    if manifest["shared"]["source_service"] == manifest["shared"]["destination_service"]:
        raise RuntimeError("integral config services must differ")
    if (
        manifest["shared"]["real_data_allowed"] != "false"
        or manifest["shared"]["external_integrations_enabled"] != "false"
    ):
        raise RuntimeError("integral config safety switches must be false")
    return observed_fingerprint
