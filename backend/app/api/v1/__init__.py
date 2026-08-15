from fastapi import APIRouter

from app.api.v1 import auth, connections, health

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(
    connections.router, prefix="/connections", tags=["connections"]
)

__all__ = ["api_router"]
