from fastapi import APIRouter

from app.api.v1.endpoints import jobs, domains, stats, analytics, websocket, celery

api_router = APIRouter()

# Include all routers
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(domains.router, prefix="/domains", tags=["domains"])
api_router.include_router(stats.router, prefix="/stats", tags=["stats"])
api_router.include_router(analytics.router, tags=["analytics"])  # Analytics endpoints have their own prefix
api_router.include_router(websocket.router, tags=["websocket"])  # WebSocket endpoints have their own paths
api_router.include_router(celery.router, tags=["celery"])  # Celery management endpoints