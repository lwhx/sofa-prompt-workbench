from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.assets import router as assets_router
from app.api.v1.auth import router as auth_router
from app.api.v1.events import router as events_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.results import router as results_router
from app.api.v1.rows import router as rows_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(events_router)
api_router.include_router(rows_router)
api_router.include_router(assets_router)
api_router.include_router(jobs_router)
api_router.include_router(results_router)
