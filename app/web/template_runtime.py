from __future__ import annotations

from fastapi.templating import Jinja2Templates

from app.core.config import settings


def configure_visual_template_runtime(templates: Jinja2Templates) -> Jinja2Templates:
    """Apply the visual shell contract once per Jinja environment.

    Route handlers may still pass page-specific values, but the global shell
    must never depend on every endpoint remembering the feature flag.
    """

    templates.env.globals["foundation_ui_enabled"] = settings.visual_foundation_enabled
    templates.env.globals["visual_asset_version"] = "20260825-convergence1"
    return templates
