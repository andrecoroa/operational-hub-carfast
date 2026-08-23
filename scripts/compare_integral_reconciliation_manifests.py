"""Compare source/target rehearsal evidence with zero tolerance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.platform.integral_reconciliation import compare_manifests, load_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    source = load_manifest(args.source)
    target = load_manifest(args.target)
    differences = compare_manifests(source, target)
    print(json.dumps({"reconciled": not differences, "differences": differences}, indent=2))
    if differences:
        raise SystemExit("integral reconciliation failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
