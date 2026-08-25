from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.platform.integral_config import (
    AUTHORIZATION_ENV,
    ROLE_ENV,
    SHARED_ENV,
    manifest_sha256,
    sign_authorization,
    validate_integral_config,
)


def valid_environment() -> dict[str, str]:
    shared = {
        "authorization_state_root": "/tmp/integral-auth",
        "bundle_id": "bundle-one",
        "bundle_timeout_seconds": "900",
        "client_timeout_seconds": "1200",
        "cutoff_id": "cut-one",
        "cutover_requested": "false",
        "destination_host": "private-worker",
        "destination_port": "10001",
        "destination_service": "srv-destination",
        "email_enabled": "false",
        "expected_destination_host": "private-worker",
        "expected_destination_port": "10001",
        "expected_hmac_snapshot_sha256": "a" * 64,
        "external_integrations_enabled": "false",
        "hmac_snapshot_sha256": "a" * 64,
        "jobs_enabled": "false",
        "max_stream_bytes": "2147483648",
        "mode": "synthetic",
        "portals_enabled": "false",
        "production_deploy_requested": "false",
        "real_data_allowed": "false",
        "release_sha": "e" * 40,
        "source_service": "srv-source",
        "webhooks_enabled": "false",
    }
    sender = {
        "database_phase": "source-staging",
        "expected_database_host": "dpg-source-private",
        "expected_database_name": "carfast_v2",
    }
    receiver = {
        "database_phase": "staging",
        "declared_bundle_bytes": "1400000000",
        "expected_database_host": "127.0.0.1",
        "expected_database_name": "carfast_integral_staging_final",
        "source_revision": "ffae1f2a3b4c",
        "spool_root": "/var/data/spool",
    }
    authorization = {
        "authorization_id": "none", "issued_at": "none",
        "expires_at": "none", "signature": "none",
    }
    manifest = {
        "schema_version": 2, "shared": shared, "authorization": authorization,
        "sender": sender, "receiver": receiver,
    }
    env = {
        env_name: str(shared[claim]) for claim, env_name in SHARED_ENV.items()
    }
    env.update({env_name: str(sender[claim]) for claim, env_name in ROLE_ENV["sender"].items()})
    env.update(
        {
            env_name: str(authorization[claim])
            for claim, env_name in AUTHORIZATION_ENV.items()
        }
    )
    env["INTEGRAL_TRANSFER_KEY"] = "test-signing-key"
    env["INTEGRAL_CONFIG_MANIFEST"] = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    env["INTEGRAL_CONFIG_SHA256"] = manifest_sha256(manifest)
    return env


def test_sender_closed_manifest_is_valid() -> None:
    assert len(validate_integral_config("sender", valid_environment())) == 64


@pytest.mark.parametrize(
    "missing", sorted(set(SHARED_ENV.values()) | set(ROLE_ENV["sender"].values()))
)
def test_sender_rejects_every_missing_claim(missing: str) -> None:
    env = valid_environment()
    env.pop(missing)
    with pytest.raises(RuntimeError, match="claim mismatch"):
        validate_integral_config("sender", env)


@pytest.mark.parametrize(
    "changed", sorted(set(SHARED_ENV.values()) | set(ROLE_ENV["sender"].values()))
)
def test_sender_rejects_every_divergent_claim(changed: str) -> None:
    env = valid_environment()
    env[changed] += "-drift"
    with pytest.raises(RuntimeError, match="claim mismatch"):
        validate_integral_config("sender", env)


def test_receiver_uses_same_manifest_snapshot_with_role_specific_database() -> None:
    env = valid_environment()
    manifest = json.loads(env["INTEGRAL_CONFIG_MANIFEST"])
    for claim, env_name in ROLE_ENV["receiver"].items():
        env[env_name] = str(manifest["receiver"][claim])
    assert validate_integral_config("receiver", env) == env["INTEGRAL_CONFIG_SHA256"]


def test_unknown_claim_and_fingerprint_drift_fail_closed() -> None:
    env = valid_environment()
    manifest = json.loads(env["INTEGRAL_CONFIG_MANIFEST"])
    manifest["shared"]["unexpected"] = "no"
    env["INTEGRAL_CONFIG_MANIFEST"] = json.dumps(manifest)
    with pytest.raises(RuntimeError, match="claims are not closed"):
        validate_integral_config("sender", env)


def real_environment(tmp_path, *, now: datetime | None = None) -> dict[str, str]:
    current = now or datetime.now(UTC)
    env = valid_environment()
    manifest = json.loads(env["INTEGRAL_CONFIG_MANIFEST"])
    manifest["shared"].update(
        mode="real_rehearsal", real_data_allowed="true",
        authorization_state_root=str(tmp_path),
    )
    manifest["authorization"] = {
        "authorization_id": "auth-final-unique-0001",
        "issued_at": current.isoformat(),
        "expires_at": (current + timedelta(minutes=10)).isoformat(),
        "signature": "pending",
    }
    manifest["authorization"]["signature"] = sign_authorization(
        manifest, env["INTEGRAL_TRANSFER_KEY"]
    )
    env.update({name: str(manifest["shared"][claim]) for claim, name in SHARED_ENV.items()})
    env.update(
        {
            name: str(manifest["authorization"][claim])
            for claim, name in AUTHORIZATION_ENV.items()
        }
    )
    env["INTEGRAL_CONFIG_MANIFEST"] = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    env["INTEGRAL_CONFIG_SHA256"] = manifest_sha256(manifest)
    return env


def test_synthetic_never_accepts_real_data() -> None:
    env = valid_environment()
    manifest = json.loads(env["INTEGRAL_CONFIG_MANIFEST"])
    manifest["shared"]["real_data_allowed"] = "true"
    env["REAL_DATA_ALLOWED"] = "true"
    env["INTEGRAL_CONFIG_MANIFEST"] = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    env["INTEGRAL_CONFIG_SHA256"] = manifest_sha256(manifest)
    with pytest.raises(RuntimeError, match="synthetic mode cannot allow real data"):
        validate_integral_config("sender", env)


def test_authorized_real_rehearsal_passes_and_replay_fails(tmp_path) -> None:
    now = datetime.now(UTC)
    env = real_environment(tmp_path, now=now)
    assert len(validate_integral_config("sender", env, now=now)) == 64
    validate_integral_config("sender", env, now=now, consume_authorization=True)
    with pytest.raises(RuntimeError, match="replay rejected"):
        validate_integral_config("sender", env, now=now, consume_authorization=True)


@pytest.mark.parametrize(
    "claim", [
        "external_integrations_enabled", "email_enabled", "jobs_enabled",
        "webhooks_enabled", "portals_enabled", "cutover_requested",
        "production_deploy_requested",
    ]
)
def test_real_rehearsal_rejects_effects_and_cutover(tmp_path, claim: str) -> None:
    env = real_environment(tmp_path)
    manifest = json.loads(env["INTEGRAL_CONFIG_MANIFEST"])
    manifest["shared"][claim] = "true"
    env[SHARED_ENV[claim]] = "true"
    manifest["authorization"]["signature"] = sign_authorization(
        manifest, env["INTEGRAL_TRANSFER_KEY"]
    )
    env["INTEGRAL_CONFIG_MANIFEST"] = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    env["INTEGRAL_CONFIG_SHA256"] = manifest_sha256(manifest)
    with pytest.raises(RuntimeError, match="effects and cutover"):
        validate_integral_config("sender", env)


def test_real_rehearsal_rejects_missing_expired_and_drifted_authorization(tmp_path) -> None:
    now = datetime.now(UTC)
    env = real_environment(tmp_path, now=now)
    env.pop("INTEGRAL_AUTHORIZATION_ID")
    with pytest.raises(RuntimeError, match="authorization claim mismatch"):
        validate_integral_config("sender", env, now=now)
    env = real_environment(tmp_path, now=now - timedelta(minutes=20))
    with pytest.raises(RuntimeError, match="not currently valid"):
        validate_integral_config("sender", env, now=now)
    env = real_environment(tmp_path, now=now)
    manifest = json.loads(env["INTEGRAL_CONFIG_MANIFEST"])
    manifest["shared"]["bundle_id"] = "drifted"
    env["INTEGRAL_CONFIG_MANIFEST"] = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    env["INTEGRAL_CONFIG_SHA256"] = manifest_sha256(manifest)
    env["INTEGRAL_BUNDLE_ID"] = "drifted"
    with pytest.raises(RuntimeError, match="signature mismatch"):
        validate_integral_config("sender", env, now=now)
    env = valid_environment()
    env["INTEGRAL_CONFIG_SHA256"] = "0" * 64
    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        validate_integral_config("sender", env)
