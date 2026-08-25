"""Create a mode-0600 integral secret envelope without printing secret material."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--role", choices=("sender", "receiver"), required=True)
    args = parser.parse_args()
    database_url = os.environ.pop("INTEGRAL_ENVELOPE_DATABASE_URL_INPUT", "")
    transfer_key = os.environ.pop("INTEGRAL_ENVELOPE_TRANSFER_KEY_INPUT", "")
    if not database_url or not transfer_key:
        raise SystemExit("integral envelope inputs are required")
    raw = json.dumps(
        {
            "database_url_b64": encoded(database_url),
            "role": args.role,
            "transfer_key_b64": encoded(transfer_key),
            "version": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    descriptor = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(raw)
    print(hashlib.sha256(raw).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
