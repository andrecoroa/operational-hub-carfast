"""Fail closed on the invariant, browser-observed UI Contract evidence."""

from __future__ import annotations

import json
from pathlib import Path
import re
import struct

from PIL import Image, ImageChops


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "ui-contract-transversal"
VIEWPORTS = {
    "1440x731": (1440, 731),
    "1024x900": (1024, 900),
    "390x844": (390, 844),
}
PAGES = ("dashboard", "tasks", "processes", "email", "documents", "admin", "partners")
CONTRACT_CSS = ROOT / "app" / "static" / "css" / "ui-contract-v1.css"


def _assert_contract_tokens() -> None:
    """Keep the visual language fail-closed instead of trusting screenshots alone."""
    css = CONTRACT_CSS.read_text(encoding="utf-8")
    required = {
        "--visual-sidebar-width": "208px",
        "--visual-topbar-height": "52px",
        "--ui-control-compact": "32px",
        "--ui-row-height": "40px",
    }
    for token, expected in required.items():
        match = re.search(rf"{re.escape(token)}\s*:\s*([^;]+);", css)
        assert match and match.group(1).strip() == expected, (token, match, expected)
    required_contracts = (
        "grid-template-columns: 250px minmax(0,1fr) 350px",
        "grid-template-columns: 280px minmax(0,1fr)",
        "grid-template-columns: 260px minmax(0,1fr) 300px",
        ".visual-document-review-tabs a[aria-current=\"page\"]",
        "height: 44px; max-height: 44px",
    )
    for contract in required_contracts:
        assert contract in css, contract


def _jpeg_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        raise AssertionError(f"not a JPEG: {path}")
    offset = 2
    while offset + 9 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        length = struct.unpack(">H", data[offset : offset + 2])[0]
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            return width, height
        offset += length
    raise AssertionError(f"JPEG dimensions not found: {path}")


def _changed_pixel_ratio(actual_path: Path, golden_path: Path) -> float:
    """Pixel gate for the deterministic synthetic fixtures reviewed by a human."""
    with Image.open(actual_path).convert("RGB") as actual, Image.open(golden_path).convert("RGB") as golden:
        assert actual.size == golden.size, (actual_path, actual.size, golden.size)
        diff = ImageChops.difference(actual, golden)
        changed = sum(1 for pixel in diff.getdata() if max(pixel) > 12)
        return changed / (actual.width * actual.height) * 100


def main() -> None:
    _assert_contract_tokens()
    rows = json.loads((EVIDENCE / "metrics.json").read_text(encoding="utf-8"))
    by_key = {(row["page"], row["viewport"]["name"]): row for row in rows}
    assert len(by_key) == len(PAGES) * len(VIEWPORTS), len(by_key)

    for page in PAGES:
        for viewport, expected_size in VIEWPORTS.items():
            row = by_key[(page, viewport)]
            assert row["overflowGlobal"] is False, (page, viewport, "global overflow")
            image_width, image_height = _jpeg_size(EVIDENCE / f"{page}-{viewport}.jpg")
            expected_width, expected_height = expected_size
            assert image_width in {expected_width, row["clientWidth"]}, (
                page,
                viewport,
                image_width,
            )
            # The in-app browser capture excludes its native scrollbars/chrome while
            # the emulated page viewport (recorded in metrics.json) keeps the exact gate size.
            assert expected_height - 40 <= image_height <= expected_height, (
                page,
                viewport,
                image_height,
            )
            visual_delta = _changed_pixel_ratio(
                EVIDENCE / f"{page}-{viewport}.jpg",
                EVIDENCE / "golden" / f"{page}-{viewport}.jpg",
            )
            assert visual_delta < 2.0, (page, viewport, "pixel drift", visual_delta)

    deltas: list[float] = []

    def exact(actual: float, expected: float, label: str) -> None:
        delta = abs(actual - expected) / expected * 100
        deltas.append(delta)
        assert abs(actual - expected) <= 2, (label, actual, expected)

    for page in PAGES:
        desktop = by_key[(page, "1440x731")]
        exact(desktop["sidebar"]["width"], 208, f"{page} sidebar")
        exact(desktop["topbar"]["height"], 52, f"{page} topbar")

    tasks = by_key[("tasks", "1440x731")]
    assert tasks["fullRows"] >= 6, tasks
    assert all(abs(height - 44) <= 2 for height in tasks["rowHeights"]), tasks

    processes = by_key[("processes", "1440x731")]["zones"]
    exact(processes["catalog"]["width"], 260, "process catalog")
    exact(processes["context"]["width"], 300, "process context")

    email = by_key[("email", "1440x731")]["zones"]
    exact(email["list"]["width"], 250, "email list")
    exact(email["triage"]["width"], 350, "email triage")

    documents = by_key[("documents", "1440x731")]["zones"]
    exact(documents["queue"]["width"], 250, "document queue")
    exact(documents["review"]["width"], 350, "document review")
    for viewport in VIEWPORTS:
        tabs = by_key[("documents", viewport)]["reviewTabs"]
        assert abs(tabs["height"] - 34) <= 2, (viewport, tabs)
        assert [item["text"] for item in tabs["labels"]] == [
            "Dados extraídos",
            "Classificação",
            "Associações",
        ]
        assert all(item["display"] == "flex" and item["whiteSpace"] == "nowrap" for item in tabs["labels"])

    admin = by_key[("admin", "1440x731")]["zones"]
    exact(admin["roleMaster"]["width"], 280, "admin master")

    for page, zone_names in {
        "email": ("list", "conversation", "triage"),
        "documents": ("queue", "preview", "review"),
    }.items():
        for viewport in VIEWPORTS:
            row = by_key[(page, viewport)]
            for zone_name in zone_names:
                zone = row["zones"][zone_name]
                assert zone and zone["width"] > 0 and zone["height"] > 0, (
                    page,
                    viewport,
                    zone_name,
                )
                assert zone["x"] >= -4, (page, viewport, zone_name, zone)
                assert zone["x"] + zone["width"] <= row["clientWidth"] + 4, (
                    page,
                    viewport,
                    zone_name,
                    zone,
                )

    maximum = max(deltas, default=0.0)
    assert maximum < 2.0, maximum
    print(
        "UI Contract evidence PASS: 21 viewports; pixel drift <2%; exact token/hierarchy contract; "
        f"maximum invariant geometry diff {maximum:.2f}%"
    )


if __name__ == "__main__":
    main()
