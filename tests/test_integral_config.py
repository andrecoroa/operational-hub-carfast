from __future__ import annotations

import json

import pytest

from app.platform.integral_config import (
    ROLE_ENV,
    SHARED_ENV,
    manifest_sha256,
    validate_integral_config,
)


def valid_environment() -> dict[str, str]:
    shared = {
        "bundle_id": "bundle-one",
        "bundle_timeout_seconds": "900",
        "client_timeout_seconds": "1200",
        "cutoff_id": "cut-one",
        "destination_host": "private-worker",
        "destination_port": "10001",
        "destination_service": "srv-destination",
        "expected_destination_host": "private-worker",
        "expected_destination_port": "10001",
        "expected_hmac_snapshot_sha256": "a" * 64,
        "external_integrations_enabled": "false",
        "hmac_snapshot_sha256": "a" * 64,
        "max_stream_bytes": "2147483648",
        "real_data_allowed": "false",
        "release_sha": "e" * 40,
        "source_service": "srv-source",
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
    manifest = {"schema_version": 1, "shared": shared, "sender": sender, "receiver": receiver}
    env = {
        env_name: str(shared[claim]) for claim, env_name in SHARED_ENV.items()
    }
    env.update({env_name: str(sender[claim]) for claim, env_name in ROLE_ENV["sender"].items()})
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
    env = valid_environment()
    env["INTEGRAL_CONFIG_SHA256"] = "0" * 64
    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        validate_integral_config("sender", env)
