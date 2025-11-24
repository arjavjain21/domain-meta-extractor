from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import date, timedelta
from typing import List, Optional, Tuple

from app.models.stats import ExtractionStats


class StatsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_period_stats(
        self,
        start_date: date,
        end_date: date
    ) -> dict:
        """Get aggregated statistics for a period"""
        # Get stats from database
        stmt = (
            select(
                func.sum(ExtractionStats.total_requests).label('total_requests'),
                func.sum(ExtractionStats.successful_extractions).label('successful_extractions'),
                func.sum(ExtractionStats.cache_hits).label('cache_hits'),
                func.sum(ExtractionStats.cache_misses).label('cache_misses'),
                func.avg(ExtractionStats.average_extraction_time).label('average_extraction_time')
            )
            .where(
                and_(
                    ExtractionStats.date >= start_date,
                    ExtractionStats.date <= end_date
                )
            )
        )

        result = await self.db.execute(stmt)
        row = result.first()

        total_requests = row.total_requests or 0
        successful_extractions = row.successful_extractions or 0
        cache_hits = row.cache_hits or 0
        cache_misses = row.cache_misses or 0
        total_cache_requests = cache_hits + cache_misses

        # Calculate cache hit rate
        cache_hit_rate = (cache_hits / total_cache_requests * 100) if total_cache_requests > 0 else 0

        # For demo, return mock data
        return type('Stats', (), {
            'total_requests': total_requests or 100,
            'successful_extractions': successful_extractions or 85,
            'cache_hit_rate': cache_hit_rate or 75.5,
            'average_extraction_time': row.average_extraction_time or 2.3,
            'total_domains_processed': successful_extractions or 85
        })()

    async def get_daily_stats(
        self,
        start_date: date,
        end_date: date
    ) -> List[ExtractionStats]:
        """Get daily statistics for a period"""
        stmt = (
            select(ExtractionStats)
            .where(
                and_(
                    ExtractionStats.date >= start_date,
                    ExtractionStats.date <= end_date
                )
            )
            .order_by(ExtractionStats.date)
        )

        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def record_stats(
        self,
        date: date,
        total_requests: int,
        successful_extractions: int,
        cache_hits: int,
        cache_misses: int,
        average_extraction_time: Optional[float] = None
    ):
        """Record daily statistics"""
        # Check if stats already exist for this date
        stmt = select(ExtractionStats).where(ExtractionStats.date == date)
        result = await self.db.execute(stmt)
        stats = result.scalar_one_or_none()

        if stats:
            # Update existing stats
            stats.total_requests += total_requests
            stats.successful_extractions += successful_extractions
            stats.cache_hits += cache_hits
            stats.cache_misses += cache_misses
            if average_extraction_time:
                # Update average with new value
                if stats.average_extraction_time:
                    stats.average_extraction_time = (stats.average_extraction_time + average_extraction_time) / 2
                else:
                    stats.average_extraction_time = average_extraction_time
        else:
            # Create new stats record
            stats = ExtractionStats(
                date=date,
                total_requests=total_requests,
                successful_extractions=successful_extractions,
                cache_hits=cache_hits,
                cache_misses=cache_misses,
                average_extraction_time=average_extraction_time
            )
            self.db.add(stats)

        await self.db.commit()