from fastapi import APIRouter

from app.api.v1.endpoints import jobs, domains, stats

api_router = APIRouter()

# Include all routers
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(domains.router, prefix="/domains", tags=["domains"])
api_router.include_router(stats.router, prefix="/stats", tags=["stats"])