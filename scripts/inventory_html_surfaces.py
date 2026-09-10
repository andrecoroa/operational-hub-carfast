"""Inventory user-facing HTML routes without importing the application.

The inventory is intentionally AST-based: it includes static and dynamic routes,
portal surfaces and legacy adapters while excluding POST actions and fragment-only
responses. CI compares the generated artefact, preventing an unclassified route.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "app" / "web", ROOT / "app" / "api" / "routes"]


def _literal(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _category(path: str, source: Path) -> str:
    if path.startswith("/portal"):
        return "portal"
    if "/preview" in path or "/modal" in path or path.endswith("/body"):
        return "overlay"
    if source.name == "workshop_ui.py" or path.startswith("/workshop/"):
        return "legacy_blocked"
    if path in {"/", "/new"} or path.endswith("/current"):
        return "adapter"
    if "{" in path:
        return "detail"
    return "canonical"


def inventory() -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for source_root in SOURCES:
        for source in sorted(source_root.glob("*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in node.decorator_list:
                    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute) or dec.func.attr != "get" or not dec.args:
                        continue
                    path = _literal(dec.args[0])
                    if not path:
                        continue
                    response_html = any(
                        kw.arg == "response_class" and isinstance(kw.value, ast.Name) and kw.value.id == "HTMLResponse"
                        for kw in dec.keywords
                    )
                    if not response_html:
                        continue
                    # Tiny attachment/body fragments are overlays, but raw file/media
                    # download endpoints are not HTML application surfaces.
                    if any(token in path for token in ("/download", "/file", "/image")):
                        continue
                    result.append({
                        "path": path,
                        "handler": node.name,
                        "source": source.relative_to(ROOT).as_posix(),
                        "classification": _category(path, source),
                    })
    return sorted(result, key=lambda row: (row["path"], row["source"], row["handler"]))


def main() -> None:
    rows = inventory()
    output = ROOT / "docs" / "architecture" / "HTML_SURFACE_INVENTORY.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "baseline_surface_count": 136,
        "surface_count": len(rows),
        "approved_additions": ["/v2-clean/admin/task-process-models"],
        "surfaces": rows,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(rows)} HTML surfaces -> {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
