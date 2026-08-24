"""Build the canonical, non-secret transfer configuration manifest from explicit env."""

from __future__ import annotations

import os

from app.platform.integral_config import (
    AUTHORIZATION_ENV,
    ROLE_ENV,
    SCHEMA_VERSION,
    SHARED_ENV,
    canonical_manifest,
    sign_authorization,
)
from app.platform.integral_secrets import bootstrap_integral_secrets


def need(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"missing manifest input: {name}")
    return value


def main() -> int:
    bootstrap_integral_secrets()
    shared = {claim: need(env_name) for claim, env_name in SHARED_ENV.items()}
    sender = {
        claim: need(f"INTEGRAL_MANIFEST_SENDER_{env_name.removeprefix('INTEGRAL_')}")
        for claim, env_name in ROLE_ENV["sender"].items()
    }
    receiver = {
        claim: need(f"INTEGRAL_MANIFEST_RECEIVER_{env_name.removeprefix('INTEGRAL_')}")
        for claim, env_name in ROLE_ENV["receiver"].items()
    }
    authorization = {claim: need(env_name) for claim, env_name in AUTHORIZATION_ENV.items()}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "shared": shared,
        "authorization": {**authorization, "signature": "none"},
        "sender": sender,
        "receiver": receiver,
    }
    if shared["mode"] == "real_rehearsal":
        manifest["authorization"]["signature"] = sign_authorization(
            manifest, need("INTEGRAL_TRANSFER_KEY")
        )
    print(canonical_manifest(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
