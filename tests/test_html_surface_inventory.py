import json
from pathlib import Path

from scripts.inventory_html_surfaces import inventory


def test_all_html_surfaces_are_classified_and_inventory_is_current():
    actual = inventory()
    assert actual
    assert all(row["classification"] in {"canonical", "detail", "overlay", "portal", "adapter", "legacy_blocked"} for row in actual)
    artifact = json.loads((Path(__file__).parents[1] / "docs/architecture/HTML_SURFACE_INVENTORY.json").read_text(encoding="utf-8"))
    assert artifact["baseline_surface_count"] == 136
    assert set(artifact["approved_additions"]) == {"/v2-clean/admin/task-process-models"}
    assert artifact["surface_count"] == len(actual)
    assert artifact["surfaces"] == actual
