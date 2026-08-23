"""Export the Phase 9 compatibility inventory without inspecting operational data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.platform.legacy_catalog import legacy_inventory_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(legacy_inventory_payload(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
