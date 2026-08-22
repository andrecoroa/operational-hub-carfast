"""Capture the compatibility baseline used by the Phase 2 foundation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute

from app.main import WEB_PERMISSION_RULES, app
from app.services.authorization import PERMISSION_ALIASES
from app.services.navigation import (
    NAVIGATION_FUNCTIONAL_SOURCES,
    NAVIGATION_PATH_RULES,
    NAVIGATION_PERMISSIONS,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = PROJECT_ROOT / "docs" / "architecture" / "baselines" / "phase2_baseline.json"


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (set, frozenset)):
        return sorted(_canonical(item) for item in value)
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def _routes() -> list[dict[str, Any]]:
    rows = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            rows.append(
                {"path": route.path, "methods": sorted(route.methods or ()), "name": route.name}
            )
    return sorted(rows, key=lambda row: (row["path"], row["methods"], row["name"]))


def _source_baseline() -> dict[str, Any]:
    redirects: Counter[str] = Counter()
    form_actions: Counter[str] = Counter()
    redirect_pattern = re.compile(r"RedirectResponse\(\s*(?:url\s*=\s*)?[f]?['\"]([^'\"]+)")
    form_pattern = re.compile(r"(?:action|formaction)\s*=\s*['\"]([^'\"]*)", re.IGNORECASE)
    for path in sorted((PROJECT_ROOT / "app").rglob("*")):
        if path.suffix not in {".py", ".html"}:
            continue
        content = path.read_text(encoding="utf-8")
        redirects.update(redirect_pattern.findall(content))
        form_actions.update(form_pattern.findall(content))
    redirect_rows = sorted(redirects.items())
    form_rows = sorted(form_actions.items())
    return {
        "redirect_destination_count": len(redirect_rows),
        "redirect_occurrence_count": sum(redirects.values()),
        "redirect_destinations_sha256": _digest(redirect_rows),
        "form_action_count": len(form_rows),
        "form_action_occurrence_count": sum(form_actions.values()),
        "form_actions_sha256": _digest(form_rows),
    }


def build_snapshot() -> dict[str, Any]:
    routes = _routes()
    aliases = {key: sorted(value) for key, value in sorted(PERMISSION_ALIASES.items())}
    navigation_sources = {
        key: sorted(value) for key, value in sorted(NAVIGATION_FUNCTIONAL_SOURCES.items())
    }
    method_counts = Counter(method for route in routes for method in route["methods"])
    table_count = len(__import__("app.models", fromlist=["Base"]).Base.metadata.tables)
    return {
        "schema_version": 1,
        "source_base": "integration/modular-architecture@0491b84d",
        "routes": {
            "count": len(routes),
            "by_method": dict(sorted(method_counts.items())),
            "sha256": _digest(routes),
        },
        "permissions": {
            "web_rule_groups": len(WEB_PERMISSION_RULES),
            "web_rules_sha256": _digest(_canonical(WEB_PERMISSION_RULES)),
            "legacy_alias_roots": len(aliases),
            "legacy_aliases_sha256": _digest(aliases),
        },
        "composition": {
            "navigation_permissions": len(NAVIGATION_PERMISSIONS),
            "navigation_permission_codes_sha256": _digest(sorted(NAVIGATION_PERMISSIONS)),
            "navigation_source_groups": len(navigation_sources),
            "navigation_sources_sha256": _digest(navigation_sources),
            "navigation_path_rules": len(NAVIGATION_PATH_RULES),
            "navigation_paths_sha256": _digest(_canonical(NAVIGATION_PATH_RULES)),
        },
        "post_actions": _source_baseline(),
        "invariants": {
            "sqlalchemy_table_count_after_additive_catalogue": table_count,
            "legacy_composer_default": True,
            "effective_permission_semantics": "legacy_set_membership",
            "operational_data_read": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build_snapshot(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not BASELINE_PATH.exists() or BASELINE_PATH.read_text(encoding="utf-8") != rendered:
            raise SystemExit(
                "Phase 2 architecture baseline drifted; review and regenerate explicitly"
            )
        print("Architecture baseline matches")
        return
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(rendered, encoding="utf-8")
    print("Architecture baseline written")


if __name__ == "__main__":
    main()
