"""
Analytics API endpoints for Phase 3 Dashboard
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis_client import get_redis
from app.services.analytics_service import AnalyticsService, MetricsCollector, AlertManager
from app.models.analytics import (
    OverviewStats, PerformanceMetrics, TopDomains, ErrorAnalysis,
    DailyStats, AlertResponse, AlertCreate, AlertUpdate, AlertSeverity,
    AnalyticsQuery
)
from app.core.websocket_manager import get_websocket_manager
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/analytics", tags=["analytics"])
metrics_collector = MetricsCollector()


@router.get("/overview", response_model=OverviewStats)
async def get_analytics_overview(
    hours: int = Query(default=24, ge=1, le=168),  # 1 hour to 1 week
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get analytics overview statistics"""
    analytics_service = AnalyticsService(db)
    overview = await analytics_service.get_overview_stats(hours)
    return OverviewStats(**overview)


@router.get("/performance")
async def get_performance_metrics(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    granularity: str = Query(default="hour", regex="^(minute|hour|day)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get performance metrics over time"""
    # Set default time range if not provided
    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=1)

    analytics_service = AnalyticsService(db)
    metrics = await analytics_service.get_performance_metrics(
        start_date, end_date, granularity
    )

    return {
        "metrics": metrics,
        "start_date": start_date,
        "end_date": end_date,
        "granularity": granularity
    }


@router.get("/extractions/daily")
async def get_daily_extraction_stats(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get daily extraction statistics"""
    analytics_service = AnalyticsService(db)
    stats = await analytics_service.get_daily_stats(days)

    return {
        "stats": stats,
        "period_days": days
    }


@router.get("/domains/top")
async def get_top_domains(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get most frequently extracted domains"""
    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=7)

    analytics_service = AnalyticsService(db)
    domains = await analytics_service.get_top_domains(start_date, end_date, limit)

    return {
        "domains": domains,
        "start_date": start_date,
        "end_date": end_date,
        "limit": limit
    }


@router.get("/errors/analysis")
async def get_error_analysis(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get error analysis and trends"""
    if not end_date:
        end_date = datetime.utcnow()
    if not start_date:
        start_date = end_date - timedelta(days=7)

    analytics_service = AnalyticsService(db)
    errors = await analytics_service.get_error_analysis(start_date, end_date)

    return {
        "errors": errors,
        "start_date": start_date,
        "end_date": end_date
    }


@router.get("/system/metrics")
async def get_system_metrics(
    hours: int = Query(default=1, ge=1, le=24),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get system performance metrics"""
    # Get current metrics
    current_metrics = await metrics_collector.collect_system_metrics()

    # Get historical metrics from database
    from app.models.analytics import SystemMetric
    from sqlalchemy import select

    since = datetime.utcnow() - timedelta(hours=hours)
    query = select(SystemMetric).where(
        SystemMetric.timestamp >= since
    ).order_by(SystemMetric.timestamp.desc())

    result = await db.execute(query)
    historical_metrics = result.scalars().all()

    return {
        "current": current_metrics.dict(),
        "historical": [
            {
                "timestamp": m.timestamp,
                "cpu_usage": m.cpu_usage,
                "memory_usage": m.memory_usage,
                "disk_usage": m.disk_usage,
                "active_connections": m.active_connections,
                "queue_length": m.queue_length,
                "workers_active": m.workers_active,
                "workers_total": m.workers_total
            }
            for m in historical_metrics
        ],
        "period_hours": hours
    }


@router.get("/cache/performance")
async def get_cache_performance(
    hours: int = Query(default=24, ge=1, le=168),
    current_user: User = Depends(get_current_user)
):
    """Get Redis cache performance metrics"""
    try:
        redis = await get_redis()
        info = await redis.info()

        # Get cache hit/miss stats from Redis
        keyspace_info = info.get('keyspace_hits', 0) + info.get('keyspace_misses', 0)
        hit_rate = (info.get('keyspace_hits', 0) / keyspace_info * 100) if keyspace_info > 0 else 0

        # Get memory usage
        memory_info = info.get('used_memory', 0)
        max_memory = info.get('maxmemory', 0)
        memory_usage = (memory_info / max_memory * 100) if max_memory > 0 else 0

        return {
            "hit_rate": round(hit_rate, 2),
            "total_keys": info.get('db0', {}).get('keys', 0),
            "memory_usage_bytes": memory_info,
            "memory_usage_percentage": round(memory_usage, 2),
            "connected_clients": info.get('connected_clients', 0),
            "expired_keys": info.get('expired_keys', 0),
            "evicted_keys": info.get('evicted_keys', 0),
            "keyspace_hits": info.get('keyspace_hits', 0),
            "keyspace_misses": info.get('keyspace_misses', 0),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting cache metrics: {str(e)}")


@router.get("/queue/status")
async def get_queue_status(
    current_user: User = Depends(get_current_user)
):
    """Get Celery queue status"""
    try:
        from app.celery import celery_app

        # Get inspector
        inspect = celery_app.control.inspect()

        # Get active tasks
        active_tasks = inspect.active()
        scheduled_tasks = inspect.scheduled()
        reserved_tasks = inspect.reserved()

        # Get queue lengths
        try:
            with celery_app.connection() as conn:
                channel = conn.channel()
                queue_info = channel.queue_declare(queue='default', passive=True)
                queue_length = queue_info.message_count
        except:
            queue_length = 0

        return {
            "active_tasks": active_tasks,
            "scheduled_tasks": scheduled_tasks,
            "reserved_tasks": reserved_tasks,
            "queue_length": queue_length,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting queue status: {str(e)}")


# Alerts endpoints
@router.get("/alerts", response_model=List[AlertResponse])
async def get_alerts(
    severity: Optional[AlertSeverity] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get system alerts"""
    from app.models.analytics import Alert
    from sqlalchemy import select

    query = select(Alert)

    if severity:
        query = query.where(Alert.severity == severity)
    if status:
        query = query.where(Alert.status == status)

    query = query.order_by(Alert.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    alerts = result.scalars().all()

    return alerts


@router.post("/alerts", response_model=AlertResponse)
async def create_alert(
    alert_data: AlertCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new alert"""
    alert_manager = AlertManager(db)
    alert = await alert_manager.create_alert(alert_data)
    return alert


@router.put("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Acknowledge an alert"""
    alert_manager = AlertManager(db)
    alert = await alert_manager.acknowledge_alert(alert_id, current_user.username)

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    return {"message": "Alert acknowledged", "alert": alert}


@router.put("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Resolve an alert"""
    alert_manager = AlertManager(db)
    alert = await alert_manager.resolve_alert(alert_id, current_user.username)

    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    return {"message": "Alert resolved", "alert": alert}


# WebSocket endpoint for real-time updates
@router.websocket("/stream")
async def websocket_analytics_stream(
    websocket: WebSocket
):
    """WebSocket endpoint for real-time analytics updates"""
    await websocket.accept()
    ws_manager = get_websocket_manager()

    try:
        # Add to analytics stream
        client_id = await ws_manager.connect(websocket, "analytics_stream")

        while True:
            try:
                # Wait for client messages (ping/pong)
                message = await websocket.receive_text()

                if message == "ping":
                    await websocket.send_text("pong")
                elif message == "subscribe":
                    # Send current stats immediately
                    async with get_db() as db:
                        analytics_service = AnalyticsService(db)
                        overview = await analytics_service.get_overview_stats(1)
                        await websocket.send_json({
                            "type": "overview_update",
                            "data": overview
                        })

            except WebSocketDisconnect:
                break
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })

    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(client_id)


# Export endpoints
@router.get("/export/extractions")
async def export_extraction_data(
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
    format: str = Query(default="json", regex="^(json|csv)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export extraction data for a time range"""
    from app.models.analytics import ExtractionMetric
    from sqlalchemy import select
    import csv
    from io import StringIO

    query = select(ExtractionMetric).where(
        ExtractionMetric.timestamp.between(start_date, end_date)
    ).order_by(ExtractionMetric.timestamp.desc())

    result = await db.execute(query)
    extractions = result.scalars().all()

    if format == "csv":
        output = StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            "timestamp", "job_id", "domain", "status", "extraction_time",
            "cache_hit", "extraction_method", "error_message"
        ])

        # Data
        for ext in extractions:
            writer.writerow([
                ext.timestamp, ext.job_id, ext.domain, ext.status,
                ext.extraction_time, ext.cache_hit, ext.extraction_method,
                ext.error_message
            ])

        return {
            "data": output.getvalue(),
            "filename": f"extractions_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv",
            "content_type": "text/csv"
        }
    else:
        return {
            "data": [
                {
                    "timestamp": ext.timestamp,
                    "job_id": ext.job_id,
                    "domain": ext.domain,
                    "status": ext.status,
                    "extraction_time": ext.extraction_time,
                    "cache_hit": ext.cache_hit,
                    "extraction_method": ext.extraction_method,
                    "error_message": ext.error_message
                }
                for ext in extractions
            ],
            "filename": f"extractions_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.json",
            "content_type": "application/json"
        }


@router.get("/export/requests")
async def export_request_data(
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
    format: str = Query(default="json", regex="^(json|csv)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export API request data for a time range"""
    from app.models.analytics import RequestMetric
    from sqlalchemy import select

    query = select(RequestMetric).where(
        RequestMetric.timestamp.between(start_date, end_date)
    ).order_by(RequestMetric.timestamp.desc())

    result = await db.execute(query)
    requests = result.scalars().all()

    # Similar export logic as above
    if format == "csv":
        # CSV export implementation
        pass
    else:
        # JSON export implementation
        pass

    return {
        "data": len(requests),  # Placeholder
        "message": "Export functionality to be implemented"
    }


# Custom metrics endpoint
@router.post("/metrics/custom")
async def record_custom_metric(
    metric_name: str,
    metric_value: float,
    tags: Optional[Dict[str, str]] = None,
    current_user: User = Depends(get_current_user)
):
    """Record a custom metric"""
    try:
        redis = await get_redis()
        now = datetime.utcnow()
        key = f"custom_metric:{metric_name}:{now.strftime('%Y%m%d%H%M')}"

        # Store metric with timestamp
        metric_data = {
            "value": metric_value,
            "timestamp": now.isoformat(),
            "tags": tags or {},
            "user": current_user.username
        }

        await redis.lpush(key, json.dumps(metric_data))
        await redis.expire(key, 86400)  # Keep for 24 hours

        return {"message": "Metric recorded", "metric": metric_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error recording metric: {str(e)}")