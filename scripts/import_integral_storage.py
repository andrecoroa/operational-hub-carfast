"""Read an integral storage archive from stdin into an empty staging root."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.platform.integral_storage_stream import unpack_storage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-root", type=Path, required=True)
    args = parser.parse_args()
    count, size = unpack_storage(sys.stdin.buffer, args.staging_root)
    print(json.dumps({"objects": count, "bytes": size, "validated": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
