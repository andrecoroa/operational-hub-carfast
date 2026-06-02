from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.api.routes import health, workshop, workshop_ui

api_router = APIRouter()


@api_router.get("/", include_in_schema=False)
def home() -> RedirectResponse:
    return RedirectResponse(url="/workshop/processes-ui")


api_router.include_router(health.router, tags=["health"])
api_router.include_router(workshop.router)
api_router.include_router(workshop_ui.router)
