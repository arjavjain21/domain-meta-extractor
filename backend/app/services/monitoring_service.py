"""
Comprehensive monitoring service for Phase 3
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from dataclasses import dataclass
from enum import Enum

from app.core.database import get_db_session
from app.core.redis_client import get_redis
from app.services.analytics_service import AnalyticsService, AlertManager
from app.models.analytics import AlertSeverity


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    DEGRADED = "degraded"
    CRITICAL = "critical"


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus
    message: str
    details: Dict[str, Any]
    last_check: datetime


@dataclass
class SystemHealth:
    overall_status: HealthStatus
    components: List[ComponentHealth]
    timestamp: datetime
    uptime: float


class MonitoringService:
    """Comprehensive monitoring service for all system components"""

    def __init__(self):
        self.redis_client = None
        self.component_checks = {
            "database": self._check_database_health,
            "redis": self._check_redis_health,
            "celery": self._check_celery_health,
            "disk_space": self._check_disk_space,
            "memory": self._check_memory_usage,
            "error_rate": self._check_error_rate,
            "response_time": self._check_response_time,
            "queue_length": self._check_queue_length
        }

    async def get_system_health(self) -> SystemHealth:
        """Get comprehensive system health status"""
        components = []
        overall_status = HealthStatus.HEALTHY

        # Check each component
        for component_name, check_func in self.component_checks.items():
            try:
                health = await check_func()
                components.append(health)

                # Update overall status based on component health
                if health.status == HealthStatus.CRITICAL:
                    overall_status = HealthStatus.CRITICAL
                elif health.status == HealthStatus.DEGRADED and overall_status != HealthStatus.CRITICAL:
                    overall_status = HealthStatus.DEGRADED
                elif health.status == HealthStatus.WARNING and overall_status == HealthStatus.HEALTHY:
                    overall_status = HealthStatus.WARNING

            except Exception as e:
                # If a check fails, mark component as critical
                components.append(ComponentHealth(
                    name=component_name,
                    status=HealthStatus.CRITICAL,
                    message=f"Health check failed: {str(e)}",
                    details={"error": str(e)},
                    last_check=datetime.utcnow()
                ))
                overall_status = HealthStatus.CRITICAL

        # Calculate system uptime
        uptime = await self._get_system_uptime()

        return SystemHealth(
            overall_status=overall_status,
            components=components,
            timestamp=datetime.utcnow(),
            uptime=uptime
        )

    async def _check_database_health(self) -> ComponentHealth:
        """Check database connectivity and performance"""
        try:
            async with get_db_session() as db:
                # Test basic connectivity
                result = await db.execute(text("SELECT 1"))
                await result.first()

                # Check connection pool
                pool_query = text("""
                    SELECT count(*) as connections
                    FROM pg_stat_activity
                    WHERE state = 'active'
                """)
                pool_result = await db.execute(pool_query)
                active_connections = pool_result.scalar()

                # Check database size
                size_query = text("""
                    SELECT pg_database_size(current_database()) as size
                """)
                size_result = await db.execute(size_query)
                db_size = size_result.scalar()

                # Check recent query performance
                perf_query = text("""
                    SELECT avg(exec_time) as avg_time
                    FROM (
                        SELECT extract(epoch FROM (now() - query_start)) as exec_time
                        FROM pg_stat_activity
                        WHERE state = 'active'
                        AND query_start > now() - interval '5 minutes'
                    ) subquery
                """)
                perf_result = await db.execute(perf_query)
                avg_query_time = perf_result.scalar()

                # Determine health status
                status = HealthStatus.HEALTHY
                message = "Database is healthy"

                if active_connections > 80:
                    status = HealthStatus.WARNING
                    message = "High number of active connections"

                if avg_query_time and avg_query_time > 5:
                    status = HealthStatus.DEGRADED
                    message = "Slow query performance detected"

                return ComponentHealth(
                    name="database",
                    status=status,
                    status_message=message,
                    details={
                        "active_connections": active_connections,
                        "database_size_bytes": db_size,
                        "average_query_time": avg_query_time
                    },
                    last_check=datetime.utcnow()
                )

        except Exception as e:
            return ComponentHealth(
                name="database",
                status=HealthStatus.CRITICAL,
                status_message=f"Database connection failed: {str(e)}",
                details={"error": str(e)},
                last_check=datetime.utcnow()
            )

    async def _check_redis_health(self) -> ComponentHealth:
        """Check Redis connectivity and memory usage"""
        try:
            redis = await get_redis()

            # Test connectivity
            await redis.ping()

            # Get Redis info
            info = await redis.info()

            # Check memory usage
            used_memory = info.get('used_memory', 0)
            max_memory = info.get('maxmemory', 0)
            memory_usage = (used_memory / max_memory * 100) if max_memory > 0 else 0

            # Check connected clients
            clients = info.get('connected_clients', 0)

            # Check key count
            keyspace = info.get('db0', {})
            key_count = keyspace.get('keys', 0)

            # Determine health status
            status = HealthStatus.HEALTHY
            message = "Redis is healthy"

            if memory_usage > 90:
                status = HealthStatus.CRITICAL
                message = "Redis memory usage critical"
            elif memory_usage > 80:
                status = HealthStatus.WARNING
                message = "Redis memory usage high"

            if clients > 100:
                if status == HealthStatus.HEALTHY:
                    status = HealthStatus.WARNING
                    message = "High number of Redis clients"

            return ComponentHealth(
                name="redis",
                status=status,
                status_message=message,
                details={
                    "memory_usage_percent": memory_usage,
                    "used_memory_bytes": used_memory,
                    "connected_clients": clients,
                    "total_keys": key_count
                },
                last_check=datetime.utcnow()
            )

        except Exception as e:
            return ComponentHealth(
                name="redis",
                status=HealthStatus.CRITICAL,
                status_message=f"Redis connection failed: {str(e)}",
                details={"error": str(e)},
                last_check=datetime.utcnow()
            )

    async def _check_celery_health(self) -> ComponentHealth:
        """Check Celery worker health"""
        try:
            from app.celery import celery_app

            # Get worker stats
            inspect = celery_app.control.inspect()
            stats = inspect.stats()

            if not stats:
                return ComponentHealth(
                    name="celery",
                    status=HealthStatus.CRITICAL,
                    status_message="No active Celery workers",
                    details={"workers": []},
                    last_check=datetime.utcnow()
                )

            # Check active workers
            active_workers = inspect.active()
            total_workers = len(stats)
            total_active_tasks = sum(len(tasks) for tasks in (active_workers or {}).values())

            # Determine health status
            status = HealthStatus.HEALTHY
            message = f"{total_workers} Celery workers active"

            if total_workers == 0:
                status = HealthStatus.CRITICAL
                message = "No Celery workers running"
            elif total_active_tasks > 100:
                status = HealthStatus.WARNING
                message = "High number of active tasks"

            return ComponentHealth(
                name="celery",
                status=status,
                status_message=message,
                details={
                    "total_workers": total_workers,
                    "active_tasks": total_active_tasks,
                    "worker_stats": stats
                },
                last_check=datetime.utcnow()
            )

        except Exception as e:
            return ComponentHealth(
                name="celery",
                status=HealthStatus.CRITICAL,
                status_message=f"Celery check failed: {str(e)}",
                details={"error": str(e)},
                last_check=datetime.utcnow()
            )

    async def _check_disk_space(self) -> ComponentHealth:
        """Check available disk space"""
        try:
            import psutil
            disk = psutil.disk_usage('/')

            usage_percent = (disk.used / disk.total) * 100
            free_gb = disk.free / (1024**3)

            status = HealthStatus.HEALTHY
            message = f"{free_gb:.1f}GB free disk space"

            if usage_percent > 95:
                status = HealthStatus.CRITICAL
                message = "Critically low disk space"
            elif usage_percent > 90:
                status = HealthStatus.DEGRADED
                message = "Low disk space"
            elif usage_percent > 80:
                status = HealthStatus.WARNING
                message = "Disk space getting low"

            return ComponentHealth(
                name="disk_space",
                status=status,
                status_message=message,
                details={
                    "total_gb": disk.total / (1024**3),
                    "used_gb": disk.used / (1024**3),
                    "free_gb": free_gb,
                    "usage_percent": usage_percent
                },
                last_check=datetime.utcnow()
            )

        except Exception as e:
            return ComponentHealth(
                name="disk_space",
                status=HealthStatus.CRITICAL,
                status_message=f"Disk check failed: {str(e)}",
                details={"error": str(e)},
                last_check=datetime.utcnow()
            )

    async def _check_memory_usage(self) -> ComponentHealth:
        """Check system memory usage"""
        try:
            import psutil
            memory = psutil.virtual_memory()

            usage_percent = memory.percent
            available_gb = memory.available / (1024**3)

            status = HealthStatus.HEALTHY
            message = f"{available_gb:.1f}GB memory available"

            if usage_percent > 95:
                status = HealthStatus.CRITICAL
                message = "Critically low memory"
            elif usage_percent > 90:
                status = HealthStatus.DEGRADED
                message = "Low memory"
            elif usage_percent > 80:
                status = HealthStatus.WARNING
                message = "Memory usage high"

            return ComponentHealth(
                name="memory",
                status=status,
                status_message=message,
                details={
                    "total_gb": memory.total / (1024**3),
                    "used_gb": memory.used / (1024**3),
                    "available_gb": available_gb,
                    "usage_percent": usage_percent
                },
                last_check=datetime.utcnow()
            )

        except Exception as e:
            return ComponentHealth(
                name="memory",
                status=HealthStatus.CRITICAL,
                status_message=f"Memory check failed: {str(e)}",
                details={"error": str(e)},
                last_check=datetime.utcnow()
            )

    async def _check_error_rate(self) -> ComponentHealth:
        """Check recent API error rate"""
        try:
            async with get_db_session() as db:
                from app.models.analytics import RequestMetric

                # Get error rate in last hour
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
                else:
                    error_rate = 0

                status = HealthStatus.HEALTHY
                message = f"Error rate: {error_rate:.1f}%"

                if error_rate > 20:
                    status = HealthStatus.CRITICAL
                    message = "Critical error rate"
                elif error_rate > 10:
                    status = HealthStatus.DEGRADED
                    message = "High error rate"
                elif error_rate > 5:
                    status = HealthStatus.WARNING
                    message = "Elevated error rate"

                return ComponentHealth(
                    name="error_rate",
                    status=status,
                    status_message=message,
                    details={
                        "error_rate_percent": error_rate,
                        "total_requests": stats.total,
                        "error_count": stats.errors,
                        "time_window": "1 hour"
                    },
                    last_check=datetime.utcnow()
                )

        except Exception as e:
            return ComponentHealth(
                name="error_rate",
                status=HealthStatus.WARNING,
                status_message=f"Could not calculate error rate: {str(e)}",
                details={"error": str(e)},
                last_check=datetime.utcnow()
            )

    async def _check_response_time(self) -> ComponentHealth:
        """Check average API response time"""
        try:
            async with get_db_session() as db:
                from app.models.analytics import RequestMetric

                # Get average response time in last hour
                since = datetime.utcnow() - timedelta(hours=1)
                query = select(
                    func.avg(RequestMetric.response_time).label('avg_time'),
                    func.percentile_cont(0.95).within_group(
                        RequestMetric.response_time
                    ).label('p95_time')
                ).where(RequestMetric.timestamp >= since)

                result = await db.execute(query)
                stats = result.first()

                avg_time = float(stats.avg_time or 0)
                p95_time = float(stats.p95_time or 0)

                status = HealthStatus.HEALTHY
                message = f"Avg response time: {avg_time:.0f}ms"

                if avg_time > 5000 or p95_time > 10000:
                    status = HealthStatus.DEGRADED
                    message = "Slow response times"
                elif avg_time > 2000 or p95_time > 5000:
                    status = HealthStatus.WARNING
                    message = "Elevated response times"

                return ComponentHealth(
                    name="response_time",
                    status=status,
                    status_message=message,
                    details={
                        "average_response_time_ms": avg_time,
                        "p95_response_time_ms": p95_time,
                        "time_window": "1 hour"
                    },
                    last_check=datetime.utcnow()
                )

        except Exception as e:
            return ComponentHealth(
                name="response_time",
                status=HealthStatus.WARNING,
                status_message=f"Could not calculate response time: {str(e)}",
                details={"error": str(e)},
                last_check=datetime.utcnow()
            )

    async def _check_queue_length(self) -> ComponentHealth:
        """Check Celery queue length"""
        try:
            from app.celery import celery_app

            # Get queue length
            with celery_app.connection() as conn:
                channel = conn.channel()
                queue_info = channel.queue_declare(queue='default', passive=True)
                queue_length = queue_info.message_count

            status = HealthStatus.HEALTHY
            message = f"Queue length: {queue_length}"

            if queue_length > 500:
                status = HealthStatus.CRITICAL
                message = "Queue is critically backed up"
            elif queue_length > 200:
                status = HealthStatus.DEGRADED
                message = "Queue is backed up"
            elif queue_length > 50:
                status = HealthStatus.WARNING
                message = "Queue length elevated"

            return ComponentHealth(
                name="queue_length",
                status=status,
                status_message=message,
                details={
                    "queue_length": queue_length,
                    "queue_name": "default"
                },
                last_check=datetime.utcnow()
            )

        except Exception as e:
            return ComponentHealth(
                name="queue_length",
                status=HealthStatus.WARNING,
                status_message=f"Could not check queue: {str(e)}",
                details={"error": str(e)},
                last_check=datetime.utcnow()
            )

    async def _get_system_uptime(self) -> float:
        """Get system uptime in seconds"""
        try:
            import psutil
            return psutil.boot_time()
        except:
            return 0

    async def get_metrics_summary(self) -> Dict[str, Any]:
        """Get a summary of all system metrics"""
        try:
            redis = await get_redis()

            # Get various metrics from Redis
            metrics = {}

            # Request metrics (last hour)
            for key in await redis.keys("stats:req:*"):
                hour = key.split(":")[-1]
                data = await redis.hgetall(key)
                metrics[f"requests_{hour}"] = {
                    k: int(v) if v.isdigit() else v
                    for k, v in data.items()
                }

            # Extraction metrics (last hour)
            for key in await redis.keys("stats:ext:*"):
                hour = key.split(":")[-1]
                data = await redis.hgetall(key)
                metrics[f"extractions_{hour}"] = {
                    k: int(v) if v.isdigit() else v
                    for k, v in data.items()
                }

            # Current system metrics
            current_metrics = await redis.get("system:metrics:current")
            if current_metrics:
                metrics["system_current"] = json.loads(current_metrics)

            # Active users
            active_users = await redis.smembers("stats:active_users")
            metrics["active_users"] = len(active_users)

            # Recent errors
            errors = await redis.lrange("errors:recent", 0, 9)
            metrics["recent_errors"] = [json.loads(e) for e in errors]

            return metrics

        except Exception as e:
            return {"error": f"Failed to get metrics: {str(e)}"}

    async def broadcast_health_update(self):
        """Broadcast health update via WebSocket"""
        try:
            from app.core.websocket_manager import get_websocket_manager

            health = await self.get_system_health()
            ws_manager = get_websocket_manager()

            await ws_manager.broadcast_to_job(
                "system_health",
                {
                    "type": "health_update",
                    "data": {
                        "overall_status": health.overall_status,
                        "components": [
                            {
                                "name": c.name,
                                "status": c.status,
                                "message": c.status_message,
                                "details": c.details
                            }
                            for c in health.components
                        ],
                        "timestamp": health.timestamp.isoformat()
                    }
                }
            )

        except Exception as e:
            print(f"Failed to broadcast health update: {e}")