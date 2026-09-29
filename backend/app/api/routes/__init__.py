"""路由聚合。"""

from fastapi import APIRouter

from . import analyze, data, meta, settings

api_router = APIRouter(prefix="/api")
api_router.include_router(meta.router)
api_router.include_router(analyze.router)
api_router.include_router(data.router)
api_router.include_router(settings.router)

__all__ = ["api_router"]
