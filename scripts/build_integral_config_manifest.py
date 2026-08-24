"""Build the canonical, non-secret transfer configuration manifest from explicit env."""

from __future__ import annotations

import os

from app.platform.integral_config import ROLE_ENV, SHARED_ENV, canonical_manifest


def need(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"missing manifest input: {name}")
    return value


def main() -> int:
    shared = {claim: need(env_name) for claim, env_name in SHARED_ENV.items()}
    sender = {
        claim: need(f"INTEGRAL_MANIFEST_SENDER_{env_name.removeprefix('INTEGRAL_')}")
        for claim, env_name in ROLE_ENV["sender"].items()
    }
    receiver = {
        claim: need(f"INTEGRAL_MANIFEST_RECEIVER_{env_name.removeprefix('INTEGRAL_')}")
        for claim, env_name in ROLE_ENV["receiver"].items()
    }
    print(
        canonical_manifest(
            {
                "schema_version": 1,
                "shared": shared,
                "sender": sender,
                "receiver": receiver,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
