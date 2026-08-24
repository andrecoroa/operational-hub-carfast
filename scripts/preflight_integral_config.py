"""Validate the closed transfer configuration without touching any database or stream."""

from __future__ import annotations

import argparse

from app.platform.integral_config import validate_integral_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("sender", "receiver"), required=True)
    parser.add_argument("--consume-authorization", action="store_true")
    args = parser.parse_args()
    fingerprint = validate_integral_config(
        args.role, consume_authorization=args.consume_authorization
    )
    print(f"integral_config_role={args.role} fingerprint={fingerprint} valid=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
