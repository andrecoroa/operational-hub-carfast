"""Classify the canonical HTML inventory into reusable visual families.

The classification is deterministic and deliberately separate from rendered
application screenshots.  It prevents route-count inflation from turning into
137 bespoke designs while still requiring nominal coverage of every surface.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "architecture" / "HTML_SURFACE_INVENTORY.json"
TARGET = ROOT / "docs" / "architecture" / "UI_SURFACE_FAMILY_MANIFEST.json"


def family_for(surface: dict[str, str]) -> str:
    path = surface["path"].lower()
    classification = surface["classification"]
    if classification in {"adapter", "portal", "legacy_blocked"}:
        return "special_states"
    if path in {"/", "/v2-clean", "/admin"} or path.endswith("/dashboard"):
        return "dashboard"
    if "/email" in path or "/document" in path:
        return "list_preview_treatment"
    if "/admin" in path or "/supplier" in path or "/partner" in path:
        return "master_detail"
    if "/process" in path or "/workshop" in path:
        return "process_workbench"
    if classification == "overlay" or path.endswith("/new") or path.endswith("/edit"):
        return "form_modal"
    if classification == "detail" or "{" in path:
        return "form_modal"
    return "list_table"


def build() -> dict[str, object]:
    inventory = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = [dict(surface, family=family_for(surface)) for surface in inventory["surfaces"]]
    counts: dict[str, int] = {name: 0 for name in (
        "dashboard", "list_table", "list_preview_treatment", "master_detail",
        "process_workbench", "form_modal", "special_states",
    )}
    for row in rows:
        counts[row["family"]] += 1
    return {
        "version": 1,
        "shell_family": "shell",
        "surface_count": len(rows),
        "family_counts": counts,
        "surfaces": rows,
    }


if __name__ == "__main__":
    TARGET.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(TARGET)
