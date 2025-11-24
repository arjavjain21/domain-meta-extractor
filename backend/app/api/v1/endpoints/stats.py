from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, timedelta

from app.core.database import get_db
from app.services.stats_service import StatsService

router = APIRouter()


@router.get("/")
async def get_stats(
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """Get system statistics"""
    stats_service = StatsService(db)

    # Calculate date range
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    stats = await stats_service.get_period_stats(start_date, end_date)

    return {
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": days
        },
        "total_requests": stats.total_requests,
        "successful_extractions": stats.successful_extractions,
        "cache_hit_rate": stats.cache_hit_rate,
        "average_extraction_time": float(stats.average_extraction_time) if stats.average_extraction_time else None,
        "total_domains_processed": stats.total_domains_processed
    }


@router.get("/daily")
async def get_daily_stats(
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """Get daily statistics"""
    stats_service = StatsService(db)

    # Calculate date range
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    daily_stats = await stats_service.get_daily_stats(start_date, end_date)

    return [stat.to_dict() for stat in daily_stats]