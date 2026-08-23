"""Exercise the anonymized export boundary with JSONL fixtures only."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.platform.anonymized_stream import EphemeralSynthesizer, stream_jsonl


def fixture_records(path: Path):
    with path.open(encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            yield record["table"], record["data"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("REAL_DATA_ALLOWED", "").lower() not in {"", "0", "false", "no", "off"}:
        raise SystemExit("fixture rehearsal requires REAL_DATA_ALLOWED=false")
    # Per-process only: never serialized, logged or placed in an environment variable.
    synth = EphemeralSynthesizer(os.urandom(32))
    for chunk in stream_jsonl(fixture_records(args.fixture), synth):
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
