"""Compare the preserved 162 relations and storage after migration to 166."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.platform.integral_migration_contract import ADDITIVE_RELATIONS
from app.platform.integral_reconciliation import compare_migrated_manifests, load_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    differences = compare_migrated_manifests(
        load_manifest(args.source), load_manifest(args.target), ADDITIVE_RELATIONS
    )
    print(json.dumps({"reconciled": not differences, "differences": differences}, indent=2))
    if differences:
        raise SystemExit("integral migration reconciliation failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
