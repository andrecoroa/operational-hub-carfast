from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from starlette.responses import HTMLResponse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


EXPECTED_STATIC_HTML_SURFACES = (
    "/v2-clean",
    "/v2-clean/admin",
    "/v2-clean/admin/audit",
    "/v2-clean/admin/evolution",
    "/v2-clean/admin/integrations",
    "/v2-clean/admin/operations",
    "/v2-clean/admin/organization",
    "/v2-clean/admin/overview",
    "/v2-clean/admin/roles",
    "/v2-clean/admin/security",
    "/v2-clean/admin/settings",
    "/v2-clean/admin/setup",
    "/v2-clean/admin/suppliers",
    "/v2-clean/admin/users",
    "/v2-clean/admin/work-classification",
    "/v2-clean/admin/workshop-models",
    "/v2-clean/diagnostics",
    "/v2-clean/documentation",
    "/v2-clean/documentation/archive",
    "/v2-clean/documentation/by-vehicle",
    "/v2-clean/documentation/extraction-models",
    "/v2-clean/documentation/financial-plans",
    "/v2-clean/documentation/imports",
    "/v2-clean/documentation/invoices",
    "/v2-clean/documentation/treatment",
    "/v2-clean/documentation/triage",
    "/v2-clean/documents",
    "/v2-clean/documents/new",
    "/v2-clean/documents/ocr-validation",
    "/v2-clean/email",
    "/v2-clean/fleet",
    "/v2-clean/fleet/financial-audit",
    "/v2-clean/fleet/sales",
    "/v2-clean/fleet/sales-access",
    "/v2-clean/fleet/sales/opportunities",
    "/v2-clean/fleet/sales/proposals",
    "/v2-clean/fleet/sales/publications",
    "/v2-clean/processes",
    "/v2-clean/stock",
    "/v2-clean/stock/articles",
    "/v2-clean/stock/current",
    "/v2-clean/stock/inventory",
    "/v2-clean/stock/invoices",
    "/v2-clean/stock/movements",
    "/v2-clean/stock/orders",
    "/v2-clean/stock/receipts",
    "/v2-clean/stock/suppliers",
    "/v2-clean/stock/workshop-requests",
    "/v2-clean/suppliers",
    "/v2-clean/tasks",
    "/v2-clean/tasks/recurring",
    "/v2-clean/workshop",
    "/v2-clean/workshop-entry",
)


def static_html_surface_paths(app: FastAPI) -> tuple[str, ...]:
    paths = {
        route.path
        for route in app.routes
        if route.path.startswith("/v2-clean")
        and "GET" in getattr(route, "methods", set())
        and "{" not in route.path
        and getattr(route, "response_class", None) is HTMLResponse
    }
    return tuple(sorted(paths))


def main() -> int:
    from app.main import app

    paths = static_html_surface_paths(app)
    if paths != EXPECTED_STATIC_HTML_SURFACES:
        missing = sorted(set(EXPECTED_STATIC_HTML_SURFACES) - set(paths))
        extra = sorted(set(paths) - set(EXPECTED_STATIC_HTML_SURFACES))
        raise SystemExit(f"NO-GO: visual surface drift; missing={missing}; extra={extra}")
    print(f"visual_surface_inventory={len(paths)}")
    print("\n".join(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
