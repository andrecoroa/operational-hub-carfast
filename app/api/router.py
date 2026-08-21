from fastapi import APIRouter

from app.api.routes import (
    admin,
    auth,
    classification_proposals,
    health,
    imports,
    integrations,
    organization,
    settings,
    stock,
    tasks,
    vehicles,
    workshop,
    workshop_ui,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(admin.router, tags=["admin"])
api_router.include_router(classification_proposals.router, tags=["classification-proposals"])
api_router.include_router(
    classification_proposals.router, prefix="/api", tags=["classification-proposals"]
)
api_router.include_router(organization.router, tags=["organization"])
api_router.include_router(settings.router, tags=["settings"])
api_router.include_router(stock.router)
api_router.include_router(vehicles.router, tags=["vehicles"])
api_router.include_router(imports.router, tags=["imports"])
api_router.include_router(tasks.router, tags=["tasks"])
api_router.include_router(tasks.router, prefix="/api", tags=["tasks"])
api_router.include_router(workshop.router, prefix="/api", tags=["workshop"])
api_router.include_router(workshop_ui.router, tags=["workshop"])
api_router.include_router(integrations.router, tags=["integrations"])
api_router.include_router(integrations.router, prefix="/api", tags=["integrations"])
