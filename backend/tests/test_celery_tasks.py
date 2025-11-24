"""
Unit tests for Celery task functionality
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from celery.exceptions import Retry

from app.tasks import (
    process_domains_task,
    extract_domain_task,
    batch_extract_task,
    cleanup_expired_cache_task,
    update_statistics_task,
    health_check_task
)
from app.models.job import Job, JobStatus
from app.models.domain import Domain


class MockAsyncResult:
    """Mock Celery AsyncResult"""
    def __init__(self, id, state="PENDING", result=None, traceback=None):
        self.id = id
        self.state = state
        self.result = result
        self.traceback = traceback
        self.status = state

    def ready(self):
        return self.state in ["SUCCESS", "FAILURE"]

    def successful(self):
        return self.state == "SUCCESS"

    def failed(self):
        return self.state == "FAILURE"

    def get(self):
        if self.state == "SUCCESS":
            return self.result
        elif self.state == "FAILURE":
            raise Exception(self.result)


class TestProcessDomainsTask:
    """Test process_domains_task functionality"""

    @pytest.fixture
    def mock_task(self):
        """Mock Celery task instance"""
        task = MagicMock()
        task.request.id = "test_task_123"
        task.update_state = MagicMock()
        task.retry = MagicMock(side_effect=Retry)
        return task

    @pytest.fixture
    def mock_db_session(self):
        """Mock database session"""
        session = AsyncMock(spec=AsyncSession)
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.close = AsyncMock()
        return session

    @pytest.fixture
    def mock_job(self):
        """Mock job instance"""
        job = MagicMock()
        job.id = "job_123"
        job.status = JobStatus.PENDING
        job.file_path = "/uploads/test.csv"
        job.total_domains = 100
        job.processed_domains = 0
        job.failed_domains = 0
        job.progress_percentage = 0.0
        job.status_message = "Starting processing..."
        job.started_at = None
        job.completed_at = None
        job.error_message = None
        job.results = {}
        return job

    @patch('app.tasks.AsyncSessionLocal')
    @patch('app.tasks.ExtractionService')
    @patch('app.tasks.process_domains_task.request')
    async def test_process_domains_success(self, mock_request, mock_extraction_service_class, mock_session_local, mock_task, mock_job, mock_db_session):
        """Test successful domain processing"""
        # Setup mocks
        mock_request.id = "test_task_123"
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        mock_extraction_service = AsyncMock()
        mock_extraction_service_class.return_value = mock_extraction_service

        # Mock successful processing
        mock_extraction_service.process_file.return_value = None

        # Create task with bound=True
        task_instance = process_domains_task
        task_instance.request = mock_request
        task_instance.update_state = mock_task.update_state
        task_instance.retry = mock_task.retry

        # Execute task
        result = task_instance.apply(args=["job_123"]).get()

        # Verify calls
        mock_session_local.assert_called_once()
        mock_extraction_service_class.assert_called_once_with(mock_db_session)
        mock_extraction_service.process_file.assert_called_once_with("job_123")
        mock_db_session.commit.assert_called()

    @patch('app.tasks.AsyncSessionLocal')
    @patch('app.tasks.ExtractionService')
    async def test_process_domains_with_retry(self, mock_extraction_service_class, mock_session_local, mock_task, mock_db_session):
        """Test domain processing with retry on failure"""
        # Setup mocks
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        mock_extraction_service = AsyncMock()
        mock_extraction_service_class.return_value = mock_extraction_service

        # Mock processing failure
        mock_extraction_service.process_file.side_effect = Exception("Database connection failed")

        # Create task with bound=True
        task_instance = process_domains_task
        task_instance.request = MagicMock()
        task_instance.request.id = "test_task_123"
        task_instance.update_state = MagicMock()
        task_instance.retry = MagicMock(side_effect=Retry)

        # Execute task (should retry)
        with pytest.raises(Retry):
            task_instance.apply(args=["job_123"]).get()

        # Verify retry was called
        task_instance.retry.assert_called_once()

    @patch('app.tasks.AsyncSessionLocal')
    @patch('app.tasks.ExtractionService')
    async def test_process_domains_invalid_job_id(self, mock_extraction_service_class, mock_session_local):
        """Test processing with invalid job ID"""
        # Setup mocks
        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        mock_extraction_service = AsyncMock()
        mock_extraction_service_class.return_value = mock_extraction_service

        # Mock job not found
        mock_extraction_service.process_file.side_effect = ValueError("Job not found")

        # Create task
        task_instance = process_domains_task
        task_instance.request = MagicMock()
        task_instance.request.id = "test_task_123"
        task_instance.update_state = MagicMock()

        # Execute task
        with pytest.raises(ValueError, match="Job not found"):
            task_instance.apply(args=["invalid_job"]).get()

        # Verify session was closed
        mock_db_session.close.assert_called_once()


class TestExtractDomainTask:
    """Test extract_domain_task functionality"""

    @patch('app.tasks.AsyncSessionLocal')
    @patch('app.tasks.DomainService')
    async def test_extract_domain_success(self, mock_domain_service_class, mock_session_local):
        """Test successful domain extraction"""
        # Setup mocks
        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        mock_domain_service = AsyncMock()
        mock_domain_service_class.return_value = mock_domain_service

        # Mock successful extraction
        mock_domain = MagicMock()
        mock_domain.to_dict.return_value = {
            "domain": "example.com",
            "meta_title": "Example Site",
            "meta_description": "Test description"
        }
        mock_domain_service.extract_domain.return_value = mock_domain

        # Execute task
        result = extract_domain_task.apply(args=["example.com"]).get()

        # Verify result
        assert result == {
            "domain": "example.com",
            "meta_title": "Example Site",
            "meta_description": "Test description"
        }

        # Verify calls
        mock_domain_service_class.assert_called_once_with(mock_db_session)
        mock_domain_service.extract_domain.assert_called_once_with("example.com")

    @patch('app.tasks.AsyncSessionLocal')
    @patch('app.tasks.DomainService')
    async def test_extract_domain_not_found(self, mock_domain_service_class, mock_session_local):
        """Test extracting non-existent domain"""
        # Setup mocks
        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        mock_domain_service = AsyncMock()
        mock_domain_service_class.return_value = mock_domain_service

        # Mock domain not found
        mock_domain_service.extract_domain.return_value = None

        # Execute task
        result = extract_domain_task.apply(args=["nonexistent.com"]).get()

        # Verify result
        assert result is None

    @patch('app.tasks.AsyncSessionLocal')
    @patch('app.tasks.DomainService')
    async def test_extract_domain_with_error(self, mock_domain_service_class, mock_session_local):
        """Test domain extraction with error"""
        # Setup mocks
        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        mock_domain_service = AsyncMock()
        mock_domain_service_class.return_value = mock_domain_service

        # Mock extraction error
        mock_domain_service.extract_domain.side_effect = Exception("Network error")

        # Execute task
        with pytest.raises(Exception, match="Network error"):
            extract_domain_task.apply(args=["example.com"]).get()


class TestBatchExtractTask:
    """Test batch_extract_task functionality"""

    @pytest.fixture
    def mock_task(self):
        """Mock Celery task instance"""
        task = MagicMock()
        task.request.id = "batch_task_123"
        task.update_state = MagicMock()
        task.retry = MagicMock(side_effect=Retry)
        return task

    @patch('app.tasks.AsyncSessionLocal')
    @patch('app.tasks.DomainService')
    async def test_batch_extract_success(self, mock_domain_service_class, mock_session_local, mock_task):
        """Test successful batch extraction"""
        domains = ["example1.com", "example2.com", "example3.com"]

        # Setup mocks
        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        mock_domain_service = AsyncMock()
        mock_domain_service_class.return_value = mock_domain_service

        # Mock successful batch extraction
        extracted_domains = []
        for domain in domains:
            mock_domain_obj = MagicMock()
            mock_domain_obj.to_dict.return_value = {
                "domain": domain,
                "meta_title": f"Title for {domain}",
                "status": "success"
            }
            extracted_domains.append(mock_domain_obj)

        mock_domain_service.extract_domains_batch.return_value = extracted_domains

        # Create task
        task_instance = batch_extract_task
        task_instance.request = mock_task
        task_instance.update_state = mock_task.update_state

        # Execute task
        result = task_instance.apply(args=[domains, 10]).get()

        # Verify result
        assert len(result) == 3
        for i, domain_result in enumerate(result):
            assert domain_result["domain"] == domains[i]
            assert domain_result["status"] == "success"

        # Verify calls
        mock_domain_service.extract_domains_batch.assert_called_once_with(domains, 10)
        mock_db_session.commit.assert_called_once()

    @patch('app.tasks.AsyncSessionLocal')
    @patch('app.tasks.DomainService')
    async def test_batch_extract_empty_list(self, mock_domain_service_class, mock_session_local):
        """Test batch extraction with empty domain list"""
        # Setup mocks
        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        mock_domain_service = AsyncMock()
        mock_domain_service_class.return_value = mock_domain_service

        # Execute task with empty list
        result = batch_extract_task.apply(args=[[], 10]).get()

        # Verify result
        assert result == []

        # Verify service was not called
        mock_domain_service.extract_domains_batch.assert_not_called()

    @patch('app.tasks.AsyncSessionLocal')
    @patch('app.tasks.DomainService')
    async def test_batch_extract_with_retry(self, mock_domain_service_class, mock_session_local, mock_task):
        """Test batch extraction with retry on failure"""
        domains = ["example1.com", "example2.com"]

        # Setup mocks
        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        mock_domain_service = AsyncMock()
        mock_domain_service_class.return_value = mock_domain_service

        # Mock extraction failure
        mock_domain_service.extract_domains_batch.side_effect = Exception("Service unavailable")

        # Create task
        task_instance = batch_extract_task
        task_instance.request = MagicMock()
        task_instance.request.id = "batch_task_123"
        task_instance.update_state = MagicMock()
        task_instance.retry = MagicMock(side_effect=Retry)

        # Execute task (should retry)
        with pytest.raises(Retry):
            task_instance.apply(args=[domains, 10]).get()

        # Verify retry was called
        task_instance.retry.assert_called_once()


class TestScheduledTasks:
    """Test scheduled/maintenance tasks"""

    @patch('app.tasks.get_redis')
    async def test_cleanup_expired_cache_task_success(self, mock_get_redis):
        """Test successful cache cleanup task"""
        # Setup mocks
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        # Mock Redis scan for expired keys
        mock_redis.scan_iter.return_value = [
            "domain:expired1",
            "job:status:expired2",
            "session:expired3"
        ]

        # Mock successful deletion
        mock_redis.delete.return_value = 1

        # Execute task
        result = cleanup_expired_cache_task.apply().get()

        # Verify result
        assert result["deleted_keys"] == 3
        assert result["errors"] == 0
        assert "execution_time" in result

        # Verify Redis calls
        mock_redis.scan_iter.assert_called()
        assert mock_redis.delete.call_count == 3

    @patch('app.tasks.get_redis')
    async def test_cleanup_expired_cache_task_with_errors(self, mock_get_redis):
        """Test cache cleanup task with errors"""
        # Setup mocks
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        # Mock Redis to raise an exception during deletion
        mock_redis.scan_iter.return_value = ["domain:expired1"]
        mock_redis.delete.side_effect = Exception("Redis connection error")

        # Execute task
        result = cleanup_expired_cache_task.apply().get()

        # Verify result
        assert result["deleted_keys"] == 0
        assert result["errors"] == 1
        assert "execution_time" in result

    @patch('app.tasks.get_redis')
    @patch('app.tasks.AsyncSessionLocal')
    async def test_update_statistics_task_success(self, mock_session_local, mock_get_redis):
        """Test successful statistics update task"""
        # Setup mocks
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        # Mock Redis statistics
        mock_redis.get.return_value = 100

        # Execute task
        result = update_statistics_task.apply().get()

        # Verify result
        assert result["domains_extracted"] == 100
        assert result["jobs_completed"] == 100
        assert result["cache_hit_rate"] >= 0
        assert "execution_time" in result

        # Verify Redis calls
        assert mock_redis.get.call_count >= 2  # At least 2 stats
        mock_redis.set.assert_called()  # Statistics should be updated

    @patch('app.tasks.get_redis')
    @patch('app.tasks.AsyncSessionLocal')
    async def test_update_statistics_task_with_db_query(self, mock_session_local, mock_get_redis):
        """Test statistics update with database queries"""
        # Setup mocks
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        # Mock database query results
        mock_result = MagicMock()
        mock_result.scalar.return_value = 50
        mock_db_session.execute.return_value = mock_result

        # Mock Redis statistics
        mock_redis.get.return_value = 75

        # Execute task
        result = update_statistics_task.apply().get()

        # Verify result contains database statistics
        assert result["total_domains_in_db"] == 50
        assert result["active_jobs"] == 50

    async def test_health_check_task_success(self):
        """Test successful health check task"""
        # Execute task
        result = health_check_task.apply().get()

        # Verify result structure
        assert "status" in result
        assert "timestamp" in result
        assert "checks" in result

        # Verify individual checks
        checks = result["checks"]
        assert "celery" in checks
        assert "database" in checks
        assert "redis" in checks

        # All checks should be passing
        for check_name, check_result in checks.items():
            assert "status" in check_result
            assert "response_time" in check_result

    @patch('app.tasks.current_app')
    async def test_health_check_celery_unavailable(self, mock_current_app):
        """Test health check when Celery is unavailable"""
        # Mock Celery control failure
        mock_current_app.control.inspect.return_value.stats.side_effect = Exception("Celery unavailable")

        # Execute task
        result = health_check_task.apply().get()

        # Verify Celery check failed
        assert result["checks"]["celery"]["status"] == "error"
        assert "error" in result["checks"]["celery"]


class TestTaskErrorHandling:
    """Test task error handling and edge cases"""

    @patch('app.tasks.AsyncSessionLocal')
    async def test_database_session_cleanup_on_error(self, mock_session_local):
        """Test that database sessions are properly cleaned up on errors"""
        # Setup mock to raise exception
        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.side_effect = Exception("Database connection failed")

        # Execute task (should handle exception gracefully)
        with pytest.raises(Exception, match="Database connection failed"):
            process_domains_task.apply(args=["job_123"]).get()

        # Verify session cleanup was attempted
        mock_db_session.close.assert_called_once()

    async def test_task_id_tracking(self):
        """Test that task IDs are properly tracked"""
        # Create task with specific ID
        task_id = "custom_task_123"

        with patch('app.tasks.process_domains_task.request') as mock_request:
            mock_request.id = task_id

            # Mock the rest of the task execution
            with patch('app.tasks.AsyncSessionLocal') as mock_session_local:
                mock_db_session = AsyncMock(spec=AsyncSession)
                mock_session_local.return_value.__aenter__.return_value = mock_db_session

                with patch('app.tasks.ExtractionService') as mock_extraction_service:
                    mock_extraction_service_instance = AsyncMock()
                    mock_extraction_service.return_value = mock_extraction_service_instance

                    # Execute task
                    try:
                        process_domains_task.apply(args=["job_123"]).get()
                    except:
                        pass  # Expected due to mocking

                    # Verify task ID was used
                    assert mock_request.id == task_id

    @patch('app.tasks.AsyncSessionLocal')
    @patch('app.tasks.DomainService')
    async def test_task_timeout_handling(self, mock_domain_service_class, mock_session_local):
        """Test task timeout handling"""
        # Setup mocks
        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        mock_domain_service = AsyncMock()
        mock_domain_service_class.return_value = mock_domain_service

        # Mock slow extraction that times out
        async def slow_extract(*args, **kwargs):
            await asyncio.sleep(5)  # Simulate slow operation
            return MagicMock()

        mock_domain_service.extract_domain.side_effect = slow_extract

        # Execute with short timeout (should timeout)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                extract_domain_task.apply(args=["example.com"]).get(),
                timeout=1.0
            )

    @patch('app.tasks.AsyncSessionLocal')
    @patch('app.tasks.DomainService')
    async def test_task_memory_cleanup(self, mock_domain_service_class, mock_session_local):
        """Test that tasks clean up memory properly"""
        # Setup mocks
        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        mock_domain_service = AsyncMock()
        mock_domain_service_class.return_value = mock_domain_service

        # Mock successful extraction
        mock_domain = MagicMock()
        mock_domain.to_dict.return_value = {"domain": "example.com"}
        mock_domain_service.extract_domain.return_value = mock_domain

        # Execute multiple tasks
        for i in range(10):
            result = extract_domain_task.apply(args=[f"example{i}.com"]).get()
            assert result is not None

        # Verify database sessions were properly managed
        assert mock_session_local.call_count == 10
        assert mock_db_session.commit.call_count == 10
        assert mock_db_session.close.call_count == 10


class TestTaskPerformance:
    """Test task performance and optimization"""

    @patch('app.tasks.AsyncSessionLocal')
    @patch('app.tasks.DomainService')
    async def test_batch_vs_individual_performance(self, mock_domain_service_class, mock_session_local):
        """Test that batch extraction is more efficient than individual"""
        domains = ["example1.com", "example2.com", "example3.com"]

        # Setup mocks
        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        mock_domain_service = AsyncMock()
        mock_domain_service_class.return_value = mock_domain_service

        # Mock batch extraction
        mock_domains = []
        for domain in domains:
            mock_domain_obj = MagicMock()
            mock_domain_obj.to_dict.return_value = {"domain": domain}
            mock_domains.append(mock_domain_obj)

        mock_domain_service.extract_domains_batch.return_value = mock_domains
        mock_domain_service.extract_domain.return_value = MagicMock()

        # Measure batch extraction time
        start_time = asyncio.get_event_loop().time()
        batch_result = batch_extract_task.apply(args=[domains, 10]).get()
        batch_time = asyncio.get_event_loop().time() - start_time

        # Measure individual extraction times
        individual_times = []
        for domain in domains:
            start_time = asyncio.get_event_loop().time()
            result = extract_domain_task.apply(args=[domain]).get()
            individual_times.append(asyncio.get_event_loop().time() - start_time)

        # Batch should be more efficient (fewer database round trips)
        assert batch_time < sum(individual_times)
        assert len(batch_result) == len(domains)

    @patch('app.tasks.AsyncSessionLocal')
    @patch('app.tasks.DomainService')
    async def test_concurrent_task_execution(self, mock_domain_service_class, mock_session_local):
        """Test concurrent task execution"""
        domains = ["example1.com", "example2.com", "example3.com"]

        # Setup mocks
        mock_db_session = AsyncMock(spec=AsyncSession)
        mock_session_local.return_value.__aenter__.return_value = mock_db_session

        mock_domain_service = AsyncMock()
        mock_domain_service_class.return_value = mock_domain_service

        # Mock extraction
        mock_domain_service.extract_domain.return_value = MagicMock()

        # Execute tasks concurrently
        tasks = []
        for domain in domains:
            task = extract_domain_task.apply_async(args=[domain])
            tasks.append(task)

        # Wait for all tasks to complete
        results = [task.get() for task in tasks]

        # Verify all tasks completed successfully
        assert len(results) == len(domains)
        assert all(result is not None for result in results)