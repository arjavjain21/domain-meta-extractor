"""
Analytics service for Phase 3 - Collects and processes metrics
"""

import asyncio
import psutil
import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, and_, or_
from sqlalchemy.orm import selectinload

from app.core.database import get_db_session
from app.core.redis_client import get_redis
from app.models.analytics import (
    RequestMetric, ExtractionMetric, SystemMetric, DomainStat,
    UserActivity, Alert, AlertSeverity, AlertStatus,
    RequestMetricCreate, ExtractionMetricCreate, SystemMetricCreate,
    UserActivityCreate, AlertCreate
)
from app.models.job import Job, JobStatus
from app.models.domain import Domain


class MetricsCollector:
    """Collects various system and application metrics"""

    def __init__(self):
        self.redis_client = None

    async def collect_system_metrics(self) -> SystemMetricCreate:
        """Collect current system performance metrics"""
        try:
            # System resource usage
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            # Get Redis metrics
            redis_metrics = await self._get_redis_metrics()

            # Get database metrics
            db_metrics = await self._get_database_metrics()

            return SystemMetricCreate(
                cpu_usage=cpu_percent,
                memory_usage=memory.percent,
                disk_usage=disk.percent,
                redis_memory_usage=redis_metrics.get('memory_usage'),
                redis_connected_clients=redis_metrics.get('connected_clients'),
                database_connections=db_metrics.get('connections'),
                database_size=db_metrics.get('size')
            )
        except Exception as e:
            print(f"Error collecting system metrics: {e}")
            return SystemMetricCreate()

    async def _get_redis_metrics(self) -> Dict[str, Any]:
        """Get Redis connection and memory metrics"""
        try:
            redis = await get_redis()
            info = await redis.info()

            return {
                'memory_usage': info.get('used_memory'),
                'connected_clients': info.get('connected_clients')
            }
        except Exception:
            return {}

    async def _get_database_metrics(self) -> Dict[str, Any]:
        """Get database connection and size metrics"""
        try:
            async with get_db_session() as db:
                # Get database size
                size_query = text("""
                    SELECT pg_database_size(current_database()) as size
                """)
                result = await db.execute(size_query)
                size = result.scalar()

                # Get active connections
                conn_query = text("""
                    SELECT count(*) as connections
                    FROM pg_stat_activity
                    WHERE state = 'active'
                """)
                result = await db.execute(conn_query)
                connections = result.scalar()

                return {
                    'size': size,
                    'connections': connections
                }
        except Exception:
            return {}

    async def record_request_metric(self, metric_data: RequestMetricCreate):
        """Record an API request metric"""
        async with get_db_session() as db:
            metric = RequestMetric(**metric_data.dict())
            db.add(metric)
            await db.commit()

            # Update real-time stats in Redis
            await self._update_request_stats(metric_data)

    async def _update_request_stats(self, metric: RequestMetricCreate):
        """Update real-time request statistics in Redis"""
        try:
            redis = await get_redis()
            now = datetime.utcnow()
            minute_key = f"stats:req:{now.strftime('%Y%m%d%H%M')}"

            # Increment counters
            await redis.hincrby(minute_key, "total", 1)

            if metric.status_code >= 400:
                await redis.hincrby(minute_key, "errors", 1)

            if metric.cache_hit:
                await redis.hincrby(minute_key, "cache_hits", 1)

            # Update response time stats
            await redis.lpush(f"{minute_key}:response_times", metric.response_time)
            await redis.ltrim(f"{minute_key}:response_times", 0, 999)  # Keep last 1000

            # Set expiry (keep for 1 hour)
            await redis.expire(minute_key, 3600)
            await redis.expire(f"{minute_key}:response_times", 3600)

        except Exception as e:
            print(f"Error updating request stats: {e}")

    async def record_extraction_metric(self, metric_data: ExtractionMetricCreate):
        """Record a domain extraction metric"""
        async with get_db_session() as db:
            metric = ExtractionMetric(**metric_data.dict())
            db.add(metric)
            await db.commit()

            # Update real-time stats
            await self._update_extraction_stats(metric_data)

    async def _update_extraction_stats(self, metric: ExtractionMetricCreate):
        """Update real-time extraction statistics"""
        try:
            redis = await get_redis()
            now = datetime.utcnow()
            minute_key = f"stats:ext:{now.strftime('%Y%m%d%H%M')}"

            # Increment counters
            await redis.hincrby(minute_key, "total", 1)

            if metric.status == 'success':
                await redis.hincrby(minute_key, "successful", 1)
            else:
                await redis.hincrby(minute_key, "failed", 1)

            if metric.cache_hit:
                await redis.hincrby(minute_key, "cache_hits", 1)

            # Update extraction time if available
            if metric.extraction_time:
                await redis.lpush(f"{minute_key}:extraction_times", metric.extraction_time)
                await redis.ltrim(f"{minute_key}:extraction_times", 0, 999)

            # Set expiry
            await redis.expire(minute_key, 3600)
            await redis.expire(f"{minute_key}:extraction_times", 3600)

        except Exception as e:
            print(f"Error updating extraction stats: {e}")

    async def record_user_activity(self, activity_data: UserActivityCreate):
        """Record a user activity event"""
        async with get_db_session() as db:
            activity = UserActivity(**activity_data.dict())
            db.add(activity)
            await db.commit()


class AnalyticsService:
    """Service for retrieving and processing analytics data"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_overview_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get overview statistics for the last N hours"""
        since = datetime.utcnow() - timedelta(hours=hours)

        # Domain extraction stats
        extraction_stats = await self._get_extraction_overview(since)

        # API performance stats
        api_stats = await self._get_api_overview(since)

        # Current system status
        system_stats = await self._get_current_system_stats()

        # Calculate combined stats
        total_extractions = extraction_stats['total']
        successful = extraction_stats['successful']
        failed = extraction_stats['failed']

        return {
            'total_domains_extracted': total_extractions,
            'successful_extractions': successful,
            'failed_extractions': failed,
            'cache_hit_rate': extraction_stats.get('cache_hit_rate', 0),
            'avg_extraction_time': extraction_stats.get('avg_time', 0),
            'active_jobs': system_stats.get('active_jobs', 0),
            'queue_length': system_stats.get('queue_length', 0),
            'system_health': self._calculate_health_status(extraction_stats, api_stats, system_stats),
            'timestamp': datetime.utcnow().isoformat()
        }

    async def _get_extraction_overview(self, since: datetime) -> Dict[str, Any]:
        """Get extraction overview statistics"""
        query = select(
            func.count(ExtractionMetric.id).label('total'),
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
            ).label('avg_time')
        ).where(ExtractionMetric.timestamp >= since)

        result = await self.db.execute(query)
        row = result.first()

        if row and row.total > 0:
            return {
                'total': row.total,
                'successful': row.successful,
                'failed': row.failed,
                'cache_hits': row.cache_hits,
                'cache_hit_rate': (row.cache_hits / row.total) * 100,
                'avg_time': row.avg_time or 0
            }

        return {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'cache_hits': 0,
            'cache_hit_rate': 0,
            'avg_time': 0
        }

    async def _get_api_overview(self, since: datetime) -> Dict[str, Any]:
        """Get API performance overview"""
        query = select(
            func.count(RequestMetric.id).label('total_requests'),
            func.avg(RequestMetric.response_time).label('avg_response_time'),
            func.count(RequestMetric.id).filter(
                RequestMetric.status_code >= 400
            ).label('error_count')
        ).where(RequestMetric.timestamp >= since)

        result = await self.db.execute(query)
        row = result.first()

        if row:
            return {
                'total_requests': row.total_requests,
                'avg_response_time': row.avg_response_time or 0,
                'error_count': row.error_count,
                'error_rate': (row.error_count / row.total_requests * 100) if row.total_requests > 0 else 0
            }

        return {
            'total_requests': 0,
            'avg_response_time': 0,
            'error_count': 0,
            'error_rate': 0
        }

    async def _get_current_system_stats(self) -> Dict[str, Any]:
        """Get current system statistics"""
        try:
            # Get latest system metrics
            query = select(SystemMetric).order_by(
                SystemMetric.timestamp.desc()
            ).limit(1)
            result = await self.db.execute(query)
            latest_metric = result.scalar_one_or_none()

            stats = {}
            if latest_metric:
                stats.update({
                    'cpu_usage': latest_metric.cpu_usage,
                    'memory_usage': latest_metric.memory_usage,
                    'queue_length': latest_metric.queue_length,
                    'workers_active': latest_metric.workers_active
                })

            # Get active jobs count
            jobs_query = select(func.count(Job.id)).where(
                Job.status.in_([JobStatus.PENDING, JobStatus.PROCESSING])
            )
            jobs_result = await self.db.execute(jobs_query)
            stats['active_jobs'] = jobs_result.scalar() or 0

            return stats

        except Exception as e:
            print(f"Error getting system stats: {e}")
            return {}

    def _calculate_health_status(self, extraction: Dict, api: Dict, system: Dict) -> str:
        """Calculate overall system health status"""
        # Health scoring algorithm
        score = 100

        # Deduct for high error rates
        if api.get('error_rate', 0) > 10:
            score -= 30
        elif api.get('error_rate', 0) > 5:
            score -= 15

        # Deduct for high resource usage
        if system.get('cpu_usage', 0) > 90:
            score -= 20
        elif system.get('cpu_usage', 0) > 80:
            score -= 10

        if system.get('memory_usage', 0) > 90:
            score -= 20
        elif system.get('memory_usage', 0) > 80:
            score -= 10

        # Deduct for queue buildup
        if system.get('queue_length', 0) > 100:
            score -= 15
        elif system.get('queue_length', 0) > 50:
            score -= 5

        # Determine status
        if score >= 90:
            return "healthy"
        elif score >= 70:
            return "warning"
        elif score >= 50:
            return "degraded"
        else:
            return "critical"

    async def get_performance_metrics(
        self,
        start_date: datetime,
        end_date: datetime,
        granularity: str = 'hour'
    ) -> List[Dict[str, Any]]:
        """Get performance metrics for a time range"""
        # Use appropriate time bucket based on granularity
        bucket_interval = {
            'minute': '1 minute',
            'hour': '1 hour',
            'day': '1 day'
        }.get(granularity, '1 hour')

        query = text(f"""
            SELECT
                time_bucket('{bucket_interval}', timestamp) as time_bucket,
                AVG(response_time) as avg_response_time,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY response_time) as p95_response_time,
                COUNT(*) as total_requests,
                COUNT(*) FILTER (WHERE status_code >= 400) as error_count
            FROM analytics.request_metrics
            WHERE timestamp BETWEEN :start AND :end
            GROUP BY time_bucket
            ORDER BY time_bucket
        """)

        result = await self.db.execute(
            query,
            {'start': start_date, 'end': end_date}
        )

        metrics = []
        for row in result:
            metrics.append({
                'timestamp': row.time_bucket,
                'avg_response_time': float(row.avg_response_time or 0),
                'p95_response_time': float(row.p95_response_time or 0),
                'requests_per_second': row.total_requests / 3600 if granularity == 'hour' else row.total_requests / 60,
                'error_rate': (row.error_count / row.total_requests * 100) if row.total_requests > 0 else 0
            })

        return metrics

    async def get_top_domains(
        self,
        start_date: datetime,
        end_date: datetime,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get most frequently extracted domains"""
        query = select(
            ExtractionMetric.domain,
            func.count(ExtractionMetric.id).label('extraction_count'),
            func.count(ExtractionMetric.id).filter(
                ExtractionMetric.status == 'success'
            ).label('successful_count'),
            func.avg(ExtractionMetric.extraction_time).filter(
                ExtractionMetric.extraction_time.isnot(None)
            ).label('avg_time')
        ).where(
            and_(
                ExtractionMetric.timestamp >= start_date,
                ExtractionMetric.timestamp <= end_date
            )
        ).group_by(
            ExtractionMetric.domain
        ).order_by(
            func.count(ExtractionMetric.id).desc()
        ).limit(limit)

        result = await self.db.execute(query)

        domains = []
        for row in result:
            success_rate = (row.successful_count / row.extraction_count * 100) if row.extraction_count > 0 else 0
            domains.append({
                'domain': row.domain,
                'extraction_count': row.extraction_count,
                'success_rate': success_rate,
                'avg_extraction_time': float(row.avg_time or 0)
            })

        return domains

    async def get_error_analysis(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Get error analysis and trends"""
        # Get extraction errors
        extraction_errors_query = select(
            ExtractionMetric.error_message,
            func.count(ExtractionMetric.id).label('count')
        ).where(
            and_(
                ExtractionMetric.timestamp >= start_date,
                ExtractionMetric.timestamp <= end_date,
                ExtractionMetric.status == 'failed',
                ExtractionMetric.error_message.isnot(None)
            )
        ).group_by(
            ExtractionMetric.error_message
        ).order_by(
            func.count(ExtractionMetric.id).desc()
        )

        result = await self.db.execute(extraction_errors_query)

        errors = []
        total_errors = sum(row.count for row in result)

        for row in result:
            errors.append({
                'error_type': row.error_message or 'Unknown error',
                'count': row.count,
                'percentage': (row.count / total_errors * 100) if total_errors > 0 else 0,
                'trend': 'stable'  # TODO: Calculate trend based on historical data
            })

        return errors

    async def get_daily_stats(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily statistics for the last N days"""
        query = select(
            func.date(ExtractionMetric.timestamp).label('date'),
            func.count(func.distinct(ExtractionMetric.domain)).label('unique_domains'),
            func.count(ExtractionMetric.id).label('total_extractions'),
            func.count(ExtractionMetric.id).filter(
                ExtractionMetric.status == 'success'
            ).label('successful'),
            func.avg(ExtractionMetric.extraction_time).filter(
                ExtractionMetric.extraction_time.isnot(None)
            ).label('avg_time')
        ).where(
            ExtractionMetric.timestamp >= datetime.utcnow() - timedelta(days=days)
        ).group_by(
            func.date(ExtractionMetric.timestamp)
        ).order_by(
            func.date(ExtractionMetric.timestamp).desc()
        )

        result = await self.db.execute(query)

        stats = []
        for row in result:
            stats.append({
                'date': row.date,
                'unique_domains': row.unique_domains,
                'total_extractions': row.total_extractions,
                'successful': row.successful,
                'avg_extraction_time': float(row.avg_time or 0)
            })

        return stats


class AlertManager:
    """Manages system alerts and notifications"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_alert(self, alert_data: AlertCreate) -> Alert:
        """Create a new alert"""
        alert = Alert(**alert_data.dict())
        alert.status = AlertStatus.ACTIVE
        self.db.add(alert)
        await self.db.commit()
        await self.db.refresh(alert)
        return alert

    async def acknowledge_alert(self, alert_id: int, acknowledged_by: str) -> Optional[Alert]:
        """Acknowledge an alert"""
        query = select(Alert).where(Alert.id == alert_id)
        result = await self.db.execute(query)
        alert = result.scalar_one_or_none()

        if alert and alert.status == AlertStatus.ACTIVE:
            alert.status = AlertStatus.ACKNOWLEDGED
            alert.acknowledged_by = acknowledged_by
            alert.acknowledged_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(alert)

        return alert

    async def resolve_alert(self, alert_id: int, resolved_by: str) -> Optional[Alert]:
        """Resolve an alert"""
        query = select(Alert).where(Alert.id == alert_id)
        result = await self.db.execute(query)
        alert = result.scalar_one_or_none()

        if alert and alert.status != AlertStatus.RESOLVED:
            alert.status = AlertStatus.RESOLVED
            alert.resolved_by = resolved_by
            alert.resolved_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(alert)

        return alert

    async def get_active_alerts(self, severity: Optional[AlertSeverity] = None) -> List[Alert]:
        """Get active alerts"""
        query = select(Alert).where(Alert.status == AlertStatus.ACTIVE)

        if severity:
            query = query.where(Alert.severity == severity)

        query = query.order_by(Alert.created_at.desc())

        result = await self.db.execute(query)
        return result.scalars().all()

    async def check_and_create_alerts(self):
        """Check system conditions and create alerts if necessary"""
        # Check for high error rates
        await self._check_error_rate_alert()

        # Check for high resource usage
        await self._check_resource_alerts()

        # Check for queue buildup
        await self._check_queue_alert()

        # Check for extraction failures
        await self._check_extraction_alerts()

    async def _check_error_rate_alert(self):
        """Check for high API error rates"""
        # Implementation for error rate checking
        pass

    async def _check_resource_alerts(self):
        """Check for high resource usage"""
        # Implementation for resource usage checking
        pass

    async def _check_queue_alert(self):
        """Check for queue buildup"""
        # Implementation for queue checking
        pass

    async def _check_extraction_alerts(self):
        """Check for extraction failure patterns"""
        # Implementation for extraction failure checking
        pass