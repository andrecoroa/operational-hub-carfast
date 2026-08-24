"""Closed, role-aware configuration and authorization contract."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA_VERSION = 2
MAX_AUTHORIZATION_LIFETIME = timedelta(minutes=15)
SHARED_ENV = {
    "authorization_state_root": "INTEGRAL_AUTHORIZATION_STATE_ROOT",
    "bundle_id": "INTEGRAL_BUNDLE_ID",
    "bundle_timeout_seconds": "INTEGRAL_BUNDLE_TIMEOUT_SECONDS",
    "client_timeout_seconds": "INTEGRAL_CLIENT_TIMEOUT_SECONDS",
    "cutoff_id": "INTEGRAL_CUTOFF_ID",
    "cutover_requested": "INTEGRAL_CUTOVER_REQUESTED",
    "destination_host": "INTEGRAL_DESTINATION_HOST",
    "destination_port": "INTEGRAL_DESTINATION_PORT",
    "destination_service": "INTEGRAL_DESTINATION_SERVICE",
    "email_enabled": "EMAIL_ENABLED",
    "expected_destination_host": "INTEGRAL_EXPECTED_DESTINATION_HOST",
    "expected_destination_port": "INTEGRAL_EXPECTED_DESTINATION_PORT",
    "expected_hmac_snapshot_sha256": "INTEGRAL_EXPECTED_HMAC_SNAPSHOT_SHA256",
    "external_integrations_enabled": "EXTERNAL_INTEGRATIONS_ENABLED",
    "hmac_snapshot_sha256": "INTEGRAL_HMAC_SNAPSHOT_SHA256",
    "jobs_enabled": "JOBS_ENABLED",
    "max_stream_bytes": "INTEGRAL_MAX_STREAM_BYTES",
    "mode": "INTEGRAL_MODE",
    "portals_enabled": "PORTALS_ENABLED",
    "production_deploy_requested": "INTEGRAL_PRODUCTION_DEPLOY_REQUESTED",
    "real_data_allowed": "REAL_DATA_ALLOWED",
    "release_sha": "INTEGRAL_RELEASE_SHA",
    "source_service": "INTEGRAL_SOURCE_SERVICE",
    "webhooks_enabled": "WEBHOOKS_ENABLED",
}
AUTHORIZATION_ENV = {
    "authorization_id": "INTEGRAL_AUTHORIZATION_ID",
    "issued_at": "INTEGRAL_AUTHORIZATION_ISSUED_AT",
    "expires_at": "INTEGRAL_AUTHORIZATION_EXPIRES_AT",
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


def authorization_claims(manifest: Mapping[str, object]) -> dict[str, str]:
    shared = manifest["shared"]
    authorization = manifest["authorization"]
    assert isinstance(shared, Mapping) and isinstance(authorization, Mapping)
    return {
        "authorization_id": str(authorization["authorization_id"]),
        "bundle_id": str(shared["bundle_id"]),
        "cutoff_id": str(shared["cutoff_id"]),
        "destination_host": str(shared["destination_host"]),
        "destination_port": str(shared["destination_port"]),
        "destination_database_host": str(manifest["receiver"]["expected_database_host"]),
        "destination_service": str(shared["destination_service"]),
        "expires_at": str(authorization["expires_at"]),
        "issued_at": str(authorization["issued_at"]),
        "mode": str(shared["mode"]),
        "release_sha": str(shared["release_sha"]),
        "source_service": str(shared["source_service"]),
        "source_database_host": str(manifest["sender"]["expected_database_host"]),
    }


def sign_authorization(manifest: Mapping[str, object], key: str) -> str:
    if not key:
        raise RuntimeError("integral authorization signing key is required")
    payload = canonical_manifest(authorization_claims(manifest)).encode()
    return hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()


def _timestamp(value: str, claim: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"integral authorization {claim} is invalid") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"integral authorization {claim} must be timezone-aware")
    return parsed.astimezone(UTC)


def validate_integral_config(
    role: str,
    environment: Mapping[str, str] | None = None,
    *,
    now: datetime | None = None,
    consume_authorization: bool = False,
) -> str:
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
        "authorization", "receiver", "schema_version", "sender", "shared"
    }:
        raise RuntimeError("integral config manifest has unknown or missing sections")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise RuntimeError("integral config schema version mismatch")
    if not isinstance(manifest["shared"], dict) or set(manifest["shared"]) != set(SHARED_ENV):
        raise RuntimeError("integral config shared claims are not closed")
    if not isinstance(manifest["authorization"], dict) or set(manifest["authorization"]) != {
        *AUTHORIZATION_ENV, "signature"
    }:
        raise RuntimeError("integral authorization claims are not closed")
    for item_role, claims in ROLE_ENV.items():
        if not isinstance(manifest[item_role], dict) or set(manifest[item_role]) != set(claims):
            raise RuntimeError(f"integral config {item_role} claims are not closed")
    observed_fingerprint = manifest_sha256(manifest)
    if len(expected_fingerprint) != 64 or observed_fingerprint != expected_fingerprint:
        raise RuntimeError("integral config fingerprint mismatch")
    for claim, env_name in SHARED_ENV.items():
        if not env.get(env_name) or str(manifest["shared"][claim]) != env[env_name]:
            raise RuntimeError(f"integral config claim mismatch: {env_name}")
    for claim, env_name in AUTHORIZATION_ENV.items():
        if not env.get(env_name) or str(manifest["authorization"][claim]) != env[env_name]:
            raise RuntimeError(f"integral authorization claim mismatch: {env_name}")
    for claim, env_name in ROLE_ENV[role].items():
        if not env.get(env_name) or str(manifest[role][claim]) != env[env_name]:
            raise RuntimeError(f"integral config claim mismatch: {env_name}")
    shared = manifest["shared"]
    if shared["hmac_snapshot_sha256"] != shared["expected_hmac_snapshot_sha256"]:
        raise RuntimeError("integral config HMAC snapshots differ")
    if shared["destination_host"] != shared["expected_destination_host"]:
        raise RuntimeError("integral config destination hosts differ")
    if shared["destination_port"] != shared["expected_destination_port"]:
        raise RuntimeError("integral config destination ports differ")
    if shared["source_service"] == shared["destination_service"]:
        raise RuntimeError("integral config services must differ")
    forced_off = (
        "cutover_requested", "email_enabled", "external_integrations_enabled",
        "jobs_enabled", "portals_enabled", "production_deploy_requested", "webhooks_enabled",
    )
    if any(shared[name] != "false" for name in forced_off):
        raise RuntimeError("integral config effects and cutover switches must be false")
    mode = shared["mode"]
    authorization = manifest["authorization"]
    if mode == "synthetic":
        if shared["real_data_allowed"] != "false":
            raise RuntimeError("synthetic mode cannot allow real data")
        if authorization != {
            "authorization_id": "none", "issued_at": "none",
            "expires_at": "none", "signature": "none"
        }:
            raise RuntimeError("synthetic mode cannot carry a real authorization")
        if consume_authorization:
            raise RuntimeError("synthetic mode has no authorization to consume")
    elif mode == "real_rehearsal":
        if shared["real_data_allowed"] != "true":
            raise RuntimeError("real rehearsal must explicitly allow real data")
        authorization_id = str(authorization["authorization_id"])
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{15,127}", authorization_id):
            raise RuntimeError("integral authorization id is invalid")
        issued_at = _timestamp(str(authorization["issued_at"]), "issued_at")
        expires_at = _timestamp(str(authorization["expires_at"]), "expires_at")
        current = (now or datetime.now(UTC)).astimezone(UTC)
        if issued_at > current + timedelta(seconds=60) or expires_at <= current:
            raise RuntimeError("integral authorization is not currently valid")
        if expires_at <= issued_at or expires_at - issued_at > MAX_AUTHORIZATION_LIFETIME:
            raise RuntimeError("integral authorization lifetime is invalid")
        expected_signature = sign_authorization(manifest, env.get("INTEGRAL_TRANSFER_KEY", ""))
        if not hmac.compare_digest(str(authorization["signature"]), expected_signature):
            raise RuntimeError("integral authorization signature mismatch")
        if consume_authorization:
            root = Path(str(shared["authorization_state_root"])).resolve()
            root.mkdir(parents=True, exist_ok=True)
            marker = root / f"{role}-{hashlib.sha256(authorization_id.encode()).hexdigest()}.used"
            try:
                descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError as exc:
                raise RuntimeError("integral authorization replay rejected") from exc
            os.close(descriptor)
    else:
        raise RuntimeError("integral config mode must be synthetic or real_rehearsal")
    return observed_fingerprint
