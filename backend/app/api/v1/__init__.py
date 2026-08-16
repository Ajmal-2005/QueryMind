from fastapi import APIRouter

from app.api.v1 import auth, connections, dashboards, health, query

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(
    connections.router, prefix="/connections", tags=["connections"]
)
api_router.include_router(query.router, prefix="/query", tags=["query"])
api_router.include_router(dashboards.router, prefix="/dashboards", tags=["dashboards"])

__all__ = ["api_router"]
