from __future__ import annotations

import json
from pathlib import Path

from scripts.build_ui_surface_family_manifest import build


ROOT = Path(__file__).resolve().parents[1]


def test_all_137_surfaces_have_exactly_one_visual_family() -> None:
    payload = build()
    rows = payload["surfaces"]
    assert payload["surface_count"] == 137
    assert len(rows) == 137
    assert len({row["path"] for row in rows}) == 137
    assert all(row["family"] in payload["family_counts"] for row in rows)
    assert sum(payload["family_counts"].values()) == 137


def test_checked_in_manifest_matches_inventory() -> None:
    checked_in = json.loads(
        (ROOT / "docs/architecture/UI_SURFACE_FAMILY_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert checked_in == build()


def test_independent_goldens_cover_pilots_and_breakpoints() -> None:
    root = ROOT / "docs/evidence/ui-contract-transversal/canonical-golden"
    pages = {"dashboard", "tasks", "processes", "email", "documents", "admin", "partners"}
    sizes = {"1440x731", "1024x900", "390x844"}
    missing = [str(root / f"{page}-{size}.jpg") for page in pages for size in sizes
               if not (root / f"{page}-{size}.jpg").is_file()]
    assert not missing
