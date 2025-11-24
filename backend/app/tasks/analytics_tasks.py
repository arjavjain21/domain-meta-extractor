"""
Celery tasks for analytics data aggregation and monitoring
"""

from celery import current_app
from app.celery import celery_app
from app.core.database import AsyncSessionLocal
from app.services.analytics_service import MetricsCollector, AlertManager
from app.models.analytics import SystemMetricCreate
from datetime import datetime, timedelta
import asyncio


@celery_app.task(bind=True)
def collect_system_metrics(self):
    """Collect and store system metrics"""
    async def collect():
        async with AsyncSessionLocal() as db:
            metrics_collector = MetricsCollector()

            # Collect system metrics
            metrics = await metrics_collector.collect_system_metrics()

            # Store in database
            from app.models.analytics import SystemMetric
            system_metric = SystemMetric(**metrics.dict())
            db.add(system_metric)
            await db.commit()

            # Also store in Redis for real-time access
            from app.core.redis_client import get_redis
            redis = await get_redis()
            await redis.setex(
                "system:metrics:current",
                300,  # 5 minutes TTL
                metrics.json()
            )

            return metrics.dict()

    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(collect())
        return result
    finally:
        loop.close()


@celery_app.task(bind=True)
def aggregate_hourly_stats(self):
    """Aggregate hourly statistics from raw metrics"""
    async def aggregate():
        async with AsyncSessionLocal() as db:
            from app.models.analytics import RequestMetric, ExtractionMetric, DomainStat
            from sqlalchemy import select, func, and_

            # Calculate the hour to aggregate
            now = datetime.utcnow()
            hour_start = now.replace(minute=0, second=0, microsecond=0)
            hour_end = hour_start + timedelta(hours=1)

            # Aggregate request metrics
            request_query = select(
                func.count(RequestMetric.id).label('total_requests'),
                func.avg(RequestMetric.response_time).label('avg_response_time'),
                func.count(RequestMetric.id).filter(
                    RequestMetric.status_code >= 400
                ).label('error_count'),
                func.count(RequestMetric.id).filter(
                    RequestMetric.cache_hit == True
                ).label('cache_hits')
            ).where(
                and_(
                    RequestMetric.timestamp >= hour_start,
                    RequestMetric.timestamp < hour_end
                )
            )

            # Aggregate extraction metrics
            extraction_query = select(
                func.count(ExtractionMetric.id).label('total_extractions'),
                func.count(func.distinct(ExtractionMetric.domain)).label('unique_domains'),
                func.count(ExtractionMetric.id).filter(
                    ExtractionMetric.status == 'success'
                ).label('successful'),
                func.count(ExtractionMetric.id).filter(
                    ExtractionMetric.status == 'failed'
                ).label('failed'),
                func.count(ExtractionMetric.id).filter(
                    ExtractionMetric.cache_hit == True
                ).label('cache_hits'),
                func.avg(ExtractionMetric.extraction_time).filter(
                    ExtractionMetric.extraction_time.isnot(None)
                ).label('avg_extraction_time')
            ).where(
                and_(
                    ExtractionMetric.timestamp >= hour_start,
                    ExtractionMetric.timestamp < hour_end
                )
            )

            # Execute queries
            request_result = await db.execute(request_query)
            extraction_result = await db.execute(extraction_query)

            request_stats = request_result.first()
            extraction_stats = extraction_result.first()

            # Get top domains
            top_domains_query = select(
                ExtractionMetric.domain,
                func.count(ExtractionMetric.id).label('count')
            ).where(
                and_(
                    ExtractionMetric.timestamp >= hour_start,
                    ExtractionMetric.timestamp < hour_end
                )
            ).group_by(
                ExtractionMetric.domain
            ).order_by(
                func.count(ExtractionMetric.id).desc()
            ).limit(10)

            top_domains_result = await db.execute(top_domains_query)
            top_domains = [
                {"domain": row.domain, "count": row.count}
                for row in top_domains_result
            ]

            # Get error types
            error_types_query = select(
                ExtractionMetric.error_message,
                func.count(ExtractionMetric.id).label('count')
            ).where(
                and_(
                    ExtractionMetric.timestamp >= hour_start,
                    ExtractionMetric.timestamp < hour_end,
                    ExtractionMetric.status == 'failed',
                    ExtractionMetric.error_message.isnot(None)
                )
            ).group_by(
                ExtractionMetric.error_message
            ).order_by(
                func.count(ExtractionMetric.id).desc()
            )

            error_types_result = await db.execute(error_types_query)
            error_types = [
                {"type": row.error_message, "count": row.count}
                for row in error_types_result
            ]

            # Store aggregated data in Redis
            from app.core.redis_client import get_redis
            redis = await get_redis()

            aggregation_data = {
                "hour": hour_start.isoformat(),
                "requests": {
                    "total": request_stats.total_requests,
                    "avg_response_time": float(request_stats.avg_response_time or 0),
                    "errors": request_stats.error_count,
                    "cache_hits": request_stats.cache_hits
                },
                "extractions": {
                    "total": extraction_stats.total_extractions,
                    "unique_domains": extraction_stats.unique_domains,
                    "successful": extraction_stats.successful,
                    "failed": extraction_stats.failed,
                    "cache_hits": extraction_stats.cache_hits,
                    "avg_time": float(extraction_stats.avg_extraction_time or 0)
                },
                "top_domains": top_domains,
                "error_types": error_types,
                "timestamp": now.isoformat()
            }

            # Store with TTL
            await redis.setex(
                f"aggregated:hourly:{hour_start.strftime('%Y%m%d%H')}",
                86400 * 7,  # Keep for 7 days
                json.dumps(aggregation_data)
            )

            return aggregation_data

    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(aggregate())
        return result
    finally:
        loop.close()


@celery_app.task(bind=True)
def aggregate_daily_stats(self):
    """Aggregate daily statistics and update domain_stats table"""
    async def aggregate():
        async with AsyncSessionLocal() as db:
            from app.models.analytics import ExtractionMetric, DomainStat
            from sqlalchemy import select, func, and_

            # Calculate the day to aggregate
            now = datetime.utcnow()
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            # Aggregate extraction metrics for the day
            query = select(
                func.count(ExtractionMetric.id).label('total_domains_extracted'),
                func.count(ExtractionMetric.id).filter(
                    ExtractionMetric.status == 'success'
                ).label('successful_extractions'),
                func.count(ExtractionMetric.id).filter(
                    ExtractionMetric.status == 'failed'
                ).label('failed_extractions'),
                func.count(ExtractionMetric.id).filter(
                    ExtractionMetric.cache_hit == True
                ).label('cache_hits'),
                func.count(ExtractionMetric.id).filter(
                    ExtractionMetric.cache_hit == False
                ).label('cache_misses'),
                func.avg(ExtractionMetric.extraction_time).filter(
                    ExtractionMetric.extraction_time.isnot(None)
                ).label('avg_extraction_time'),
                func.count(func.distinct(ExtractionMetric.domain)).label('unique_domains')
            ).where(
                and_(
                    ExtractionMetric.timestamp >= day_start,
                    ExtractionMetric.timestamp < day_end
                )
            )

            result = await db.execute(query)
            stats = result.first()

            # Create or update domain_stats record
            domain_stat = await db.get(DomainStat, day_start.date())
            if not domain_stat:
                domain_stat = DomainStat(date=day_start.date())

            domain_stat.total_domains_extracted = stats.total_domains_extracted
            domain_stat.successful_extractions = stats.successful_extractions
            domain_stat.failed_extractions = stats.failed_extractions
            domain_stat.cache_hits = stats.cache_hits
            domain_stat.cache_misses = stats.cache_misses
            domain_stat.avg_extraction_time = stats.avg_extraction_time
            domain_stat.unique_domains = stats.unique_domains
            domain_stat.timestamp = day_start

            # Get top domains for the day
            top_domains_query = select(
                ExtractionMetric.domain,
                func.count(ExtractionMetric.id).label('count')
            ).where(
                and_(
                    ExtractionMetric.timestamp >= day_start,
                    ExtractionMetric.timestamp < day_end
                )
            ).group_by(
                ExtractionMetric.domain
            ).order_by(
                func.count(ExtractionMetric.id).desc()
            ).limit(10)

            top_domains_result = await db.execute(top_domains_query)
            domain_stat.top_domains = [
                {"domain": row.domain, "count": row.count}
                for row in top_domains_result
            ]

            # Get error types
            error_types_query = select(
                ExtractionMetric.error_message,
                func.count(ExtractionMetric.id).label('count')
            ).where(
                and_(
                    ExtractionMetric.timestamp >= day_start,
                    ExtractionMetric.timestamp < day_end,
                    ExtractionMetric.status == 'failed',
                    ExtractionMetric.error_message.isnot(None)
                )
            ).group_by(
                ExtractionMetric.error_message
            ).order_by(
                func.count(ExtractionMetric.id).desc()
            )

            error_types_result = await db.execute(error_types_query)
            domain_stat.error_types = [
                {"type": row.error_message, "count": row.count}
                for row in error_types_result
            ]

            await db.commit()
            await db.refresh(domain_stat)

            return {
                "date": day_start.date().isoformat(),
                "total_domains_extracted": stats.total_domains_extracted,
                "successful_extractions": stats.successful_extractions,
                "failed_extractions": stats.failed_extractions,
                "cache_hit_rate": (stats.cache_hits / stats.total_domains_extracted * 100) if stats.total_domains_extracted > 0 else 0,
                "unique_domains": stats.unique_domains,
                "avg_extraction_time": float(stats.avg_extraction_time or 0)
            }

    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(aggregate())
        return result
    finally:
        loop.close()


@celery_app.task(bind=True)
def check_alert_conditions(self):
    """Check system conditions and create alerts if necessary"""
    async def check():
        async with AsyncSessionLocal() as db:
            alert_manager = AlertManager(db)

            # Check various alert conditions
            await alert_manager.check_and_create_alerts()

            # Additional checks can be added here
            await _check_high_error_rate(db)
            await _check_resource_usage(db)
            await _check_queue_buildup(db)

            return {"alerts_checked": True, "timestamp": datetime.utcnow().isoformat()}

    async def _check_high_error_rate(db):
        """Check for high API error rates"""
        from app.models.analytics import RequestMetric
        from sqlalchemy import select, func, and_
        from app.models.analytics import AlertCreate, AlertSeverity

        # Check last hour error rate
        since = datetime.utcnow() - timedelta(hours=1)
        query = select(
            func.count(RequestMetric.id).label('total'),
            func.count(RequestMetric.id).filter(
                RequestMetric.status_code >= 400
            ).label('errors')
        ).where(RequestMetric.timestamp >= since)

        result = await db.execute(query)
        stats = result.first()

        if stats.total > 0:
            error_rate = (stats.errors / stats.total) * 100
            if error_rate > 10:  # Alert if error rate > 10%
                alert_manager = AlertManager(db)
                await alert_manager.create_alert(
                    AlertCreate(
                        severity=AlertSeverity.HIGH,
                        alert_type="high_error_rate",
                        message=f"High error rate detected: {error_rate:.2f}%",
                        details={
                            "error_rate": error_rate,
                            "total_requests": stats.total,
                            "errors": stats.errors,
                            "time_window": "1 hour"
                        }
                    )
                )

    async def _check_resource_usage(db):
        """Check for high resource usage"""
        from app.models.analytics import SystemMetric, AlertCreate, AlertSeverity

        # Get latest system metrics
        query = select(SystemMetric).order_by(
            SystemMetric.timestamp.desc()
        ).limit(1)

        result = await db.execute(query)
        latest_metric = result.scalar_one_or_none()

        if latest_metric:
            alert_manager = AlertManager(db)

            # Check CPU usage
            if latest_metric.cpu_usage and latest_metric.cpu_usage > 90:
                await alert_manager.create_alert(
                    AlertCreate(
                        severity=AlertSeverity.CRITICAL,
                        alert_type="high_cpu_usage",
                        message=f"High CPU usage: {latest_metric.cpu_usage:.2f}%",
                        details={"cpu_usage": latest_metric.cpu_usage}
                    )
                )

            # Check memory usage
            if latest_metric.memory_usage and latest_metric.memory_usage > 90:
                await alert_manager.create_alert(
                    AlertCreate(
                        severity=AlertSeverity.HIGH,
                        alert_type="high_memory_usage",
                        message=f"High memory usage: {latest_metric.memory_usage:.2f}%",
                        details={"memory_usage": latest_metric.memory_usage}
                    )
                )

    async def _check_queue_buildup(db):
        """Check for queue buildup"""
        from app.models.analytics import AlertCreate, AlertSeverity

        try:
            from app.celery import celery_app
            inspect = celery_app.control.inspect()
            active_tasks = inspect.active()

            total_active = 0
            if active_tasks:
                for worker, tasks in active_tasks.items():
                    total_active += len(tasks)

            if total_active > 100:  # Alert if more than 100 active tasks
                alert_manager = AlertManager(db)
                await alert_manager.create_alert(
                    AlertCreate(
                        severity=AlertSeverity.MEDIUM,
                        alert_type="queue_buildup",
                        message=f"Queue buildup detected: {total_active} active tasks",
                        details={"active_tasks": total_active}
                    )
                )

        except Exception:
            pass  # Don't let monitoring errors affect the system

    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(check())
        return result
    finally:
        loop.close()


@celery_app.task(bind=True)
def cleanup_old_metrics(self):
    """Clean up old analytics data to prevent database bloat"""
    async def cleanup():
        async with AsyncSessionLocal() as db:
            from app.models.analytics import RequestMetric, ExtractionMetric, SystemMetric
            from sqlalchemy import delete, and_

            # Define retention periods
            request_retention = datetime.utcnow() - timedelta(days=30)
            extraction_retention = datetime.utcnow() - timedelta(days=30)
            system_retention = datetime.utcnow() - timedelta(days=7)

            # Clean up old request metrics
            delete_request = delete(RequestMetric).where(
                RequestMetric.timestamp < request_retention
            )
            await db.execute(delete_request)

            # Clean up old extraction metrics
            delete_extraction = delete(ExtractionMetric).where(
                ExtractionMetric.timestamp < extraction_retention
            )
            await db.execute(delete_extraction)

            # Clean up old system metrics
            delete_system = delete(SystemMetric).where(
                SystemMetric.timestamp < system_retention
            )
            await db.execute(delete_system)

            await db.commit()

            return {
                "cleanup_completed": True,
                "timestamp": datetime.utcnow().isoformat(),
                "retention_days": {
                    "request_metrics": 30,
                    "extraction_metrics": 30,
                    "system_metrics": 7
                }
            }

    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(cleanup())
        return result
    finally:
        loop.close()


# Scheduled tasks using Celery Beat
from celery.schedules import crontab

# Schedule periodic tasks
celery_app.conf.beat_schedule = {
    'collect-system-metrics': {
        'task': 'app.tasks.analytics_tasks.collect_system_metrics',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
    'aggregate-hourly-stats': {
        'task': 'app.tasks.analytics_tasks.aggregate_hourly_stats',
        'schedule': crontab(minute=0),  # Every hour at the top of the hour
    },
    'aggregate-daily-stats': {
        'task': 'app.tasks.analytics_tasks.aggregate_daily_stats',
        'schedule': crontab(hour=0, minute=30),  # Daily at 00:30
    },
    'check-alerts': {
        'task': 'app.tasks.analytics_tasks.check_alert_conditions',
        'schedule': crontab(minute='*/10'),  # Every 10 minutes
    },
    'cleanup-old-metrics': {
        'task': 'app.tasks.analytics_tasks.cleanup_old_metrics',
        'schedule': crontab(hour=2, minute=0),  # Daily at 02:00
    },
}