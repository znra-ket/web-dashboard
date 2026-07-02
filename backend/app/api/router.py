from fastapi import APIRouter

from app.api.v1.folders import router as folders_router
from app.api.v1.health import router as health_router
from app.api.v1.onboarding import router as onboarding_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(folders_router, prefix="/folders", tags=["folders"])
api_router.include_router(onboarding_router, prefix="/onboarding", tags=["onboarding"])
