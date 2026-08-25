"""Write an integral storage archive to stdout without logging object paths."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.platform.integral_storage_stream import pack_storage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    pack_storage(args.root, sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
