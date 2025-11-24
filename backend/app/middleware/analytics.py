"""
Middleware for automatic analytics collection
"""

import time
import json
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.services.analytics_service import MetricsCollector
from app.core.redis_client import get_redis
from app.models.analytics import RequestMetricCreate


class AnalyticsMiddleware(BaseHTTPMiddleware):
    """Middleware to automatically collect request metrics"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.metrics_collector = MetricsCollector()
        self.exclude_paths = {
            "/health", "/metrics", "/favicon.ico", "/static",
            "/docs", "/redoc", "/openapi.json"
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip analytics for certain paths
        if request.url.path in self.exclude_paths or request.url.path.startswith("/docs"):
            return await call_next(request)

        # Record start time
        start_time = time.time()

        # Get request details
        method = request.method
        path = request.url.path
        user_agent = request.headers.get("user-agent")
        ip_address = self._get_client_ip(request)

        # Get user ID if available
        user_id = None
        if hasattr(request.state, 'user'):
            user_id = getattr(request.state.user, 'id', None)

        # Process request
        response = await call_next(request)

        # Calculate response time
        response_time = (time.time() - start_time) * 1000  # Convert to milliseconds

        # Record metric
        metric_data = RequestMetricCreate(
            endpoint=path,
            method=method,
            status_code=response.status_code,
            response_time=response_time,
            user_id=str(user_id) if user_id else None,
            user_agent=user_agent,
            ip_address=ip_address,
            request_size=request.headers.get("content-length"),
            response_size=response.headers.get("content-length"),
            cache_hit=response.headers.get("x-cache") == "HIT",
            error_message=None if response.status_code < 400 else f"HTTP {response.status_code}"
        )

        # Record metric asynchronously (don't block response)
        import asyncio
        asyncio.create_task(self.metrics_collector.record_request_metric(metric_data))

        # Add custom headers
        response.headers["X-Response-Time"] = f"{response_time:.2f}ms"

        return response

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request"""
        # Check for forwarded IP first
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        return request.client.host if request.client else "unknown"


class RealTimeMetricsMiddleware(BaseHTTPMiddleware):
    """Middleware for real-time metrics updates"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Process request
        response = await call_next(request)

        # Update real-time stats in Redis
        import asyncio
        asyncio.create_task(self._update_real_time_stats(request, response))

        return response

    async def _update_real_time_stats(self, request: Request, response: Response):
        """Update real-time statistics in Redis"""
        try:
            redis = await get_redis()
            now = time.time()

            # Update request counter
            await redis.incr("stats:requests:total")
            await redis.incr(f"stats:requests:{response.status_code}")

            # Update endpoint-specific stats
            endpoint_key = f"stats:endpoints:{request.method}:{request.url.path}"
            await redis.hincrby(endpoint_key, "count", 1)
            await redis.hset(endpoint_key, "last_access", now)
            await redis.expire(endpoint_key, 86400)  # Keep for 24 hours

            # Track active users
            if hasattr(request.state, 'user'):
                user_id = getattr(request.state.user, 'id', None)
                if user_id:
                    await redis.sadd("stats:active_users", str(user_id))
                    await redis.expire("stats:active_users", 300)  # 5 minutes

        except Exception as e:
            # Don't let metrics errors affect the main application
            print(f"Error updating real-time stats: {e}")


class ErrorTrackingMiddleware(BaseHTTPMiddleware):
    """Middleware to track errors and exceptions"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except Exception as e:
            # Log the error
            import asyncio
            asyncio.create_task(self._track_error(request, e))

            # Re-raise to let FastAPI handle it
            raise

    async def _track_error(self, request: Request, error: Exception):
        """Track error occurrence"""
        try:
            redis = await get_redis()
            error_data = {
                "timestamp": time.time(),
                "path": request.url.path,
                "method": request.method,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "user_agent": request.headers.get("user-agent"),
                "ip_address": request.client.host if request.client else None
            }

            # Store in error log
            await redis.lpush("errors:recent", json.dumps(error_data))
            await redis.ltrim("errors:recent", 0, 999)  # Keep last 1000 errors

            # Update error counters
            await redis.incr("stats:errors:total")
            await redis.incr(f"stats:errors:{type(error).__name__}")

        except Exception:
            # Don't let error tracking errors cause more errors
            pass