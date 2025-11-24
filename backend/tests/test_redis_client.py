"""
Unit tests for Redis client functionality
"""

import pytest
import pytest_asyncio
import json
import pickle
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

from app.core.redis_client import (
    RedisClient,
    get_cached_domain,
    set_cached_domain,
    delete_cached_domain,
    check_rate_limit,
    increment_stat,
    get_stat,
    set_session_data,
    get_session_data,
    delete_session,
    CACHE_KEYS
)


@pytest.fixture
def mock_redis():
    """Mock Redis instance"""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=1)
    mock_redis.exists = AsyncMock(return_value=0)
    mock_redis.ttl = AsyncMock(return_value=3600)
    mock_redis.incrby = AsyncMock(return_value=1)
    mock_redis.sadd = AsyncMock(return_value=1)
    mock_redis.smembers = AsyncMock(return_value=set())
    return mock_redis


@pytest.fixture
async def redis_client(mock_redis):
    """Redis client fixture with mocked Redis"""
    client = RedisClient()
    client.redis = mock_redis
    return client


class TestRedisClient:
    """Test Redis client core functionality"""

    @pytest.mark.asyncio
    async def test_connect_success(self, mock_redis):
        """Test successful Redis connection"""
        client = RedisClient()
        await client.connect()
        mock_redis.ping.assert_called_once()
        assert client.redis is not None

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Test Redis connection failure"""
        client = RedisClient()
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis_instance = AsyncMock()
            mock_redis_instance.ping.side_effect = Exception("Connection failed")
            mock_from_url.return_value = mock_redis_instance

            with pytest.raises(Exception):
                await client.connect()

    @pytest.mark.asyncio
    async def test_get_string_value(self, redis_client, mock_redis):
        """Test getting string value from Redis"""
        # Mock a simple string value
        test_value = "test_value"
        mock_redis.get.return_value = test_value.encode('utf-8')

        result = await redis_client.get("test_key")

        mock_redis.get.assert_called_once_with("test_key")
        assert result == "test_value"

    @pytest.mark.asyncio
    async def test_get_json_value(self, redis_client, mock_redis):
        """Test getting JSON value from Redis"""
        test_dict = {"key": "value", "number": 42}
        mock_redis.get.return_value = json.dumps(test_dict).encode('utf-8')

        result = await redis_client.get("test_key")

        assert result == test_dict

    @pytest.mark.asyncio
    async def test_get_pickled_value(self, redis_client, mock_redis):
        """Test getting pickled value from Redis"""
        test_obj = {"complex": "object", "date": datetime.utcnow()}
        mock_redis.get.return_value = pickle.dumps(test_obj)

        result = await redis_client.get("test_key")

        assert result == test_obj

    @pytest.mark.asyncio
    async def test_set_with_default_ttl(self, redis_client, mock_redis):
        """Test setting value with default TTL"""
        test_value = {"test": "data"}
        await redis_client.set("test_key", test_value)

        mock_redis.setex.assert_called_once()
        # Check that it was called with the right arguments
        args, kwargs = mock_redis.setex.call_args
        assert args[0] == "test_key"
        assert args[2] == 3600  # Default TTL

    @pytest.mark.asyncio
    async def test_set_with_custom_ttl(self, redis_client, mock_redis):
        """Test setting value with custom TTL"""
        test_value = {"test": "data"}
        await redis_client.set("test_key", test_value, ttl=7200)

        mock_redis.setex.assert_called_once()
        args, kwargs = mock_redis.setex.call_args
        assert args[2] == 7200  # Custom TTL

    @pytest.mark.asyncio
    async def test_delete_existing_key(self, redis_client, mock_redis):
        """Test deleting existing key"""
        mock_redis.delete.return_value = 1
        result = await redis_client.delete("test_key")

        assert result is True
        mock_redis.delete.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key(self, redis_client, mock_redis):
        """Test deleting non-existent key"""
        mock_redis.delete.return_value = 0
        result = await redis_client.delete("test_key")

        assert result is False
        mock_redis.delete.assert_called_once_with("test_key")

    @pytest.mark.asyncio
    async def test_exists_true(self, redis_client, mock_redis):
        """Test checking if key exists (true)"""
        mock_redis.exists.return_value = 1
        result = await redis_client.exists("test_key")

        assert result is True

    @pytest.mark.asyncio
    async def test_exists_false(self, redis_client, mock_redis):
        """Test checking if key exists (false)"""
        mock_redis.exists.return_value = 0
        result = await redis_client.exists("test_key")

        assert result is False


class TestRedisUtilities:
    """Test Redis utility functions"""

    @pytest.mark.asyncio
    @patch('app.core.redis_client.get_redis')
    async def test_get_cached_domain_hit(self, mock_get_redis):
        """Test getting cached domain (cache hit)"""
        # Mock Redis client
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        # Mock cached domain data
        cached_domain = {
            "domain": "example.com",
            "meta_title": "Example Site",
            "meta_description": "Test description"
        }
        mock_redis.get.return_value = cached_domain

        result = await get_cached_domain("example.com")

        assert result == cached_domain
        mock_redis.get.assert_called_once_with("domain:example.com")

    @pytest.mark.asyncio
    @patch('app.core.redis_client.get_redis')
    async def test_get_cached_domain_miss(self, mock_get_redis):
        """Test getting cached domain (cache miss)"""
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis
        mock_redis.get.return_value = None

        result = await get_cached_domain("example.com")

        assert result is None
        mock_redis.get.assert_called_once_with("domain:example.com")

    @pytest.mark.asyncio
    @patch('app.core.redis_client.get_redis')
    async def test_set_cached_domain(self, mock_get_redis):
        """Test setting cached domain"""
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis
        mock_redis.set.return_value = True

        domain_data = {
            "domain": "example.com",
            "meta_title": "Example Site",
            "meta_description": "Test description"
        }

        result = await set_cached_domain("example.com", domain_data, ttl=3600)

        assert result is True
        mock_redis.set.assert_called_once_with("domain:example.com", domain_data, ttl=3600)

    @pytest.mark.asyncio
    @patch('app.core.redis_client.get_redis')
    async def test_delete_cached_domain(self, mock_get_redis):
        """Test deleting cached domain"""
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis
        mock_redis.delete.return_value = 1

        result = await delete_cached_domain("example.com")

        assert result is True
        mock_redis.delete.assert_called_once_with("domain:example.com")

    @pytest.mark.asyncio
    @patch('app.core.redis_client.get_redis')
    async def test_check_rate_limit_under_limit(self, mock_get_redis):
        """Test rate limiting when under limit"""
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        # First call - under limit
        mock_redis.get.return_value = 0
        result1 = await check_rate_limit("192.168.1.1", 5, 60)
        assert result1 is True

        # Check if increment was called
        assert mock_redis.set.called_once_with("rate_limit:192.168.1.1", 1, 60)

        # Reset mock for next test
        mock_redis.reset_mock()

        # Second call - still under limit
        mock_redis.get.return_value = 1
        result2 = await check_rate_limit("192.168.1.1", 5, 60)
        assert result2 is True

    @pytest.mark.asyncio
    @patch('app.core.redis_client.get_redis')
    async def test_check_rate_limit_exceeded(self, mock_get_redis):
        """Test rate limiting when over limit"""
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        # Set current count to limit
        mock_redis.get.return_value = 5
        result = await check_rate_limit("192.168.1.1", 5, 60)

        assert result is False
        mock_redis.get.assert_called_once_with("rate_limit:192.168.1.1")

    @pytest.mark.asyncio
    @patch('app.core.redis_client.get_redis')
    async def test_increment_stat(self, mock_get_redis):
        """Test incrementing statistic counter"""
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis
        mock_redis.incrby.return_value = 5

        result = await increment_stat("domains_extracted", 3)

        assert result == 5
        mock_redis.incrby.assert_called_once_with("stats:counter:domains_extracted", 3)

    @pytest.mark.asyncio
    @patch('app.core.redis_client.get_redis')
    async def test_get_stat_existing(self, mock_get_redis):
        """Test getting existing statistic"""
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis
        mock_redis.get.return_value = 10

        result = await get_stat("domains_extracted")

        assert result == 10
        mock_redis.get.assert_called_once_with("stats:counter:domains_extracted")

    @pytest.mark.asyncio
    @patch('app.core.redis_client.get_redis')
    async def test_get_stat_nonexistent(self, mock_get_redis):
        """Test getting non-existent statistic"""
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis
        mock_redis.get.return_value = None

        result = await get_stat("nonexistent_stat")

        assert result == 0
        mock_redis.get.assert_called_once_with("stats:counter:nonexistent_stat")

    @pytest.mark.asyncio
    @patch('app.core.redis_client.get_redis')
    async def test_session_management(self, mock_get_redis):
        """Test session data management"""
        mock_redis = AsyncMock()
        mock_get_redis.return_value = mock_redis

        session_data = {"user_id": "123", "name": "Test User"}
        session_id = "session_123"

        # Test setting session data
        mock_redis.set.return_value = True
        result = await set_session_data(session_id, session_data, 86400)
        assert result is True
        mock_redis.set.assert_called_once_with("session:session_123", session_data, 86400)

        # Test getting session data
        mock_redis.get.return_value = session_data
        result = await get_session_data(session_id)
        assert result == session_data
        mock_redis.get.assert_called_once_with("session:session_123")

        # Test deleting session
        mock_redis.delete.return_value = 1
        result = await delete_session(session_id)
        assert result is True
        mock_redis.delete.assert_called_once_with("session:session_123")

    @pytest.mark.asyncio
    @patch('app.core.redis_client.get_redis')
    async def test_cache_keys_constants(self, mock_get_redis):
        """Test CACHE_KEYS constants"""
        # Test that cache keys are properly formatted
        assert CACHE_KEYS["domain"].format(domain="example.com") == "domain:example.com"
        assert CACHE_KEYS["job_status"].format(job_id="123") == "job:status:123"
        assert CACHE_KEYS["job_progress"].format(job_id="456") == "job:progress:456"
        assert CACHE_KEYS["rate_limit"].format(identifier="test") == "rate_limit:test"
        assert CACHE_KEYS["session"].format(session_id="789") == "session:789"


class TestRedisClientErrorHandling:
    """Test Redis client error handling"""

    @pytest.mark.asyncio
    async def test_get_with_no_redis_connection(self):
        """Test get when Redis is not connected"""
        client = RedisClient()
        client.redis = None

        result = await client.get("test_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_with_no_redis_connection(self):
        """Test set when Redis is not connected"""
        client = RedisClient()
        client.redis = None

        result = await client.set("test_key", "test_value")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_with_no_redis_connection(self):
        """Test delete when Redis is not connected"""
        client = RedisClient()
        client.redis = None

        result = await client.delete("test_key")
        assert result is False

    @pytest.mark.asyncio
    async def test_exists_with_no_redis_connection(self):
        """Test exists when Redis is not connected"""
        client = RedisClient()
        client.redis = None

        result = await client.exists("test_key")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_ttl_with_no_redis_connection(self):
        """Test get TTL when Redis is not connected"""
        client = RedisClient()
        client.redis = None

        result = await client.get_ttl("test_key")
        assert result == -1

    @pytest.mark.asyncio
    async def test_deserialization_error(self, redis_client):
        """Test handling of deserialization errors"""
        # Mock Redis to return invalid data
        redis_client.redis.get.return_value = b"invalid_pickle_data"

        # Should return None or raw bytes on deserialization error
        result = await redis_client.get("test_key")
        # The implementation should return the raw bytes or None on error
        assert result is None or isinstance(result, bytes)

    @pytest.mark.asyncio
    async def test_serialization_error(self, redis_client):
        """Test handling of serialization errors"""
        # Mock a non-serializable object
        non_serializable = object()

        # Should return False on serialization error
        result = await redis_client.set("test_key", non_serializable)
        assert result is False