"""
Unit tests for WebSocket manager functionality
"""

import pytest
import pytest_asyncio
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from typing import Dict, List

from app.core.websocket_manager import (
    WebSocketManager,
    ConnectionManager,
    get_websocket_manager,
    get_connection_manager
)


class MockWebSocket:
    """Mock WebSocket for testing"""

    def __init__(self, client_id: str = None):
        self.client_id = client_id or f"client_{id(self)}"
        self.messages_sent = []
        self.closed = False
        self.accept_called = False
        self.close_code = None
        self.close_reason = None

    async def accept(self):
        """Mock accept method"""
        self.accept_called = True

    async def send_text(self, data: str):
        """Mock send_text method"""
        if self.closed:
            raise ConnectionError("WebSocket is closed")
        self.messages_sent.append(data)

    async def close(self, code: int = 1000, reason: str = None):
        """Mock close method"""
        self.closed = True
        self.close_code = code
        self.close_reason = reason

    def __repr__(self):
        return f"MockWebSocket(id={self.client_id}, closed={self.closed})"


@pytest.fixture
def websocket_manager():
    """Create WebSocket manager instance"""
    return WebSocketManager()


@pytest.fixture
def connection_manager():
    """Create connection manager instance"""
    return ConnectionManager()


@pytest.fixture
def mock_websocket():
    """Create mock WebSocket"""
    return MockWebSocket()


@pytest.fixture
def multiple_mock_websockets():
    """Create multiple mock WebSockets"""
    return [MockWebSocket(f"client_{i}") for i in range(5)]


class TestWebSocketManager:
    """Test WebSocket manager core functionality"""

    @pytest.mark.asyncio
    async def test_connect_single_client(self, websocket_manager, mock_websocket):
        """Test connecting a single client"""
        job_id = "test_job_123"
        client_id = "client_456"

        # Connect client
        actual_client_id = await websocket_manager.connect(mock_websocket, job_id, client_id)

        # Verify connection
        assert actual_client_id == client_id
        assert mock_websocket.accept_called
        assert client_id in websocket_manager.connections
        assert websocket_manager.connections[client_id] == {
            'websocket': mock_websocket,
            'job_id': job_id,
            'connected_at': mock_websocket.connected_at
        }
        assert client_id in websocket_manager.job_connections[job_id]

    @pytest.mark.asyncio
    async def test_connect_without_client_id(self, websocket_manager, mock_websocket):
        """Test connecting without providing client_id"""
        job_id = "test_job_123"

        # Connect without client_id
        client_id = await websocket_manager.connect(mock_websocket, job_id)

        # Verify generated client_id
        assert client_id is not None
        assert len(client_id) == 36  # UUID length
        assert mock_websocket.accept_called

    @pytest.mark.asyncio
    async def test_connect_multiple_clients_same_job(self, websocket_manager, multiple_mock_websockets):
        """Test connecting multiple clients to the same job"""
        job_id = "test_job_123"

        # Connect multiple clients
        client_ids = []
        for i, ws in enumerate(multiple_mock_websockets):
            client_id = f"client_{i}"
            await websocket_manager.connect(ws, job_id, client_id)
            client_ids.append(client_id)

        # Verify all connections
        assert len(websocket_manager.job_connections[job_id]) == 5
        for client_id in client_ids:
            assert client_id in websocket_manager.connections
            assert websocket_manager.connections[client_id]['job_id'] == job_id

    @pytest.mark.asyncio
    async def test_connect_multiple_clients_different_jobs(self, websocket_manager, multiple_mock_websockets):
        """Test connecting multiple clients to different jobs"""
        job_ids = ["job_1", "job_2", "job_3"]

        # Connect clients to different jobs
        client_ids = []
        for i, ws in enumerate(multiple_mock_websockets):
            job_id = job_ids[i % len(job_ids)]
            client_id = f"client_{i}"
            await websocket_manager.connect(ws, job_id, client_id)
            client_ids.append(client_id)

        # Verify job connections
        for job_id in job_ids:
            assert job_id in websocket_manager.job_connections
            assert len(websocket_manager.job_connections[job_id]) >= 1

    @pytest.mark.asyncio
    async def test_disconnect_existing_client(self, websocket_manager, mock_websocket):
        """Test disconnecting an existing client"""
        job_id = "test_job_123"
        client_id = "client_456"

        # Connect first
        await websocket_manager.connect(mock_websocket, job_id, client_id)

        # Disconnect
        await websocket_manager.disconnect(client_id)

        # Verify disconnection
        assert client_id not in websocket_manager.connections
        assert client_id not in websocket_manager.job_connections[job_id]

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_client(self, websocket_manager):
        """Test disconnecting a non-existent client"""
        nonexistent_client_id = "nonexistent_client"

        # Should not raise an exception
        await websocket_manager.disconnect(nonexistent_client_id)

        # State should remain unchanged
        assert len(websocket_manager.connections) == 0
        assert len(websocket_manager.job_connections) == 0

    @pytest.mark.asyncio
    async def test_disconnect_cleanup_empty_job(self, websocket_manager, multiple_mock_websockets):
        """Test that job connections are cleaned up when empty"""
        job_id = "test_job_123"

        # Connect clients
        client_ids = []
        for i, ws in enumerate(multiple_mock_websockets[:2]):
            client_id = f"client_{i}"
            await websocket_manager.connect(ws, job_id, client_id)
            client_ids.append(client_id)

        # Verify job exists
        assert job_id in websocket_manager.job_connections

        # Disconnect all clients
        for client_id in client_ids:
            await websocket_manager.disconnect(client_id)

        # Job should be cleaned up
        assert job_id not in websocket_manager.job_connections

    @pytest.mark.asyncio
    async def test_send_message_to_client(self, websocket_manager, mock_websocket):
        """Test sending a message to a specific client"""
        job_id = "test_job_123"
        client_id = "client_456"
        test_message = {"type": "test", "data": "hello"}

        # Connect client
        await websocket_manager.connect(mock_websocket, job_id, client_id)

        # Send message
        await websocket_manager.send_message_to_client(client_id, test_message)

        # Verify message was sent
        assert len(mock_websocket.messages_sent) == 1
        sent_data = json.loads(mock_websocket.messages_sent[0])
        assert sent_data["type"] == test_message["type"]
        assert sent_data["data"] == test_message["data"]

    @pytest.mark.asyncio
    async def test_send_message_to_nonexistent_client(self, websocket_manager):
        """Test sending a message to a non-existent client"""
        nonexistent_client_id = "nonexistent_client"
        test_message = {"type": "test", "data": "hello"}

        # Should not raise an exception
        await websocket_manager.send_message_to_client(nonexistent_client_id, test_message)

    @pytest.mark.asyncio
    async def test_send_message_to_closed_websocket(self, websocket_manager, mock_websocket):
        """Test sending a message to a closed WebSocket"""
        job_id = "test_job_123"
        client_id = "client_456"
        test_message = {"type": "test", "data": "hello"}

        # Connect client
        await websocket_manager.connect(mock_websocket, job_id, client_id)

        # Close the WebSocket
        mock_websocket.closed = True

        # Send message (should handle gracefully)
        await websocket_manager.send_message_to_client(client_id, test_message)

        # Should remove the closed connection
        assert client_id not in websocket_manager.connections

    @pytest.mark.asyncio
    async def test_broadcast_to_job(self, websocket_manager, multiple_mock_websockets):
        """Test broadcasting a message to all clients in a job"""
        job_id = "test_job_123"
        test_message = {"type": "progress", "data": {"progress": 50}}

        # Connect multiple clients to the job
        client_ids = []
        for i, ws in enumerate(multiple_mock_websockets[:3]):
            client_id = f"client_{i}"
            await websocket_manager.connect(ws, job_id, client_id)
            client_ids.append(client_id)

        # Broadcast message
        await websocket_manager.broadcast_to_job(job_id, test_message)

        # Verify all clients received the message
        for ws in multiple_mock_websockets[:3]:
            assert len(ws.messages_sent) == 1
            sent_data = json.loads(ws.messages_sent[0])
            assert sent_data["type"] == test_message["type"]
            assert sent_data["data"] == test_message["data"]

    @pytest.mark.asyncio
    async def test_broadcast_to_nonexistent_job(self, websocket_manager):
        """Test broadcasting to a non-existent job"""
        nonexistent_job_id = "nonexistent_job"
        test_message = {"type": "test", "data": "hello"}

        # Should not raise an exception
        await websocket_manager.broadcast_to_job(nonexistent_job_id, test_message)

    @pytest.mark.asyncio
    async def test_broadcast_with_mixed_closed_connections(self, websocket_manager, multiple_mock_websockets):
        """Test broadcasting with some closed connections"""
        job_id = "test_job_123"
        test_message = {"type": "progress", "data": {"progress": 75}}

        # Connect multiple clients
        client_ids = []
        for i, ws in enumerate(multiple_mock_websockets[:3]):
            client_id = f"client_{i}"
            await websocket_manager.connect(ws, job_id, client_id)
            client_ids.append(client_id)

        # Close one of the WebSockets
        multiple_mock_websockets[1].closed = True

        # Broadcast message
        await websocket_manager.broadcast_to_job(job_id, test_message)

        # Only active connections should receive the message
        assert len(multiple_mock_websockets[0].messages_sent) == 1
        assert len(multiple_mock_websockets[1].messages_sent) == 0  # Closed
        assert len(multiple_mock_websockets[2].messages_sent) == 1

        # Closed connection should be removed
        closed_client_id = client_ids[1]
        assert closed_client_id not in websocket_manager.connections

    @pytest.mark.asyncio
    async def test_get_job_connections(self, websocket_manager, multiple_mock_websockets):
        """Test getting all connections for a job"""
        job_id = "test_job_123"
        another_job_id = "job_456"

        # Connect clients to different jobs
        for i, ws in enumerate(multiple_mock_websockets):
            job = job_id if i < 3 else another_job_id
            client_id = f"client_{i}"
            await websocket_manager.connect(ws, job, client_id)

        # Get connections for job_id
        connections = websocket_manager.get_job_connections(job_id)
        assert len(connections) == 3

        # Get connections for another_job_id
        connections = websocket_manager.get_job_connections(another_job_id)
        assert len(connections) == 2

        # Get connections for non-existent job
        connections = websocket_manager.get_job_connections("nonexistent")
        assert len(connections) == 0

    @pytest.mark.asyncio
    async def test_get_connection_count(self, websocket_manager, multiple_mock_websockets):
        """Test getting connection count for a job"""
        job_id = "test_job_123"

        # Initially no connections
        assert websocket_manager.get_connection_count(job_id) == 0

        # Add connections
        for i, ws in enumerate(multiple_mock_websockets[:3]):
            client_id = f"client_{i}"
            await websocket_manager.connect(ws, job_id, client_id)

        # Check count
        assert websocket_manager.get_connection_count(job_id) == 3

        # Disconnect one
        await websocket_manager.disconnect("client_1")
        assert websocket_manager.get_connection_count(job_id) == 2

    @pytest.mark.asyncio
    async def test_update_job_progress_realtime(self, websocket_manager, multiple_mock_websockets):
        """Test updating job progress in real-time"""
        job_id = "test_job_123"
        test_progress = {
            "current": 5,
            "total": 10,
            "percentage": 50.0,
            "status": "processing",
            "message": "Processing domain 5 of 10"
        }

        # Connect clients
        client_ids = []
        for i, ws in enumerate(multiple_mock_websockets[:2]):
            client_id = f"client_{i}"
            await websocket_manager.connect(ws, job_id, client_id)
            client_ids.append(client_id)

        # Update progress
        await websocket_manager.update_job_progress_realtime(job_id, test_progress)

        # Verify all clients received progress update
        for ws in multiple_mock_websockets[:2]:
            assert len(ws.messages_sent) == 1
            sent_data = json.loads(ws.messages_sent[0])
            assert sent_data["type"] == "progress_update"
            assert sent_data["data"]["progress"] == test_progress

    @pytest.mark.asyncio
    async def test_update_job_progress_realtime_no_connections(self, websocket_manager):
        """Test updating progress when no clients are connected"""
        job_id = "test_job_123"
        test_progress = {"current": 1, "total": 10}

        # Should not raise an exception
        await websocket_manager.update_job_progress_realtime(job_id, test_progress)

    @pytest.mark.asyncio
    async def test_cleanup_expired_connections(self, websocket_manager, multiple_mock_websockets):
        """Test cleaning up expired connections"""
        job_id = "test_job_123"

        # Connect clients
        client_ids = []
        for i, ws in enumerate(multiple_mock_websockets[:3]):
            client_id = f"client_{i}"
            await websocket_manager.connect(ws, job_id, client_id)
            client_ids.append(client_id)

        # Manually set one connection as expired (connected more than 1 hour ago)
        expired_client_id = client_ids[1]
        websocket_manager.connections[expired_client_id]['connected_at'] = (
            datetime.utcnow() - timedelta(hours=2)
        )

        # Run cleanup
        await websocket_manager.cleanup_expired_connections(max_age_hours=1)

        # Expired connection should be removed
        assert expired_client_id not in websocket_manager.connections
        assert expired_client_id not in websocket_manager.job_connections[job_id]

        # Other connections should remain
        for client_id in client_ids[0:1] + client_ids[2:]:
            assert client_id in websocket_manager.connections

    @pytest.mark.asyncio
    async def test_get_websocket_manager_singleton(self):
        """Test getting WebSocket manager singleton"""
        manager1 = get_websocket_manager()
        manager2 = get_websocket_manager()
        assert manager1 is manager2


class TestConnectionManager:
    """Test connection manager for rate limiting and validation"""

    @pytest.mark.asyncio
    async def test_check_rate_limit_under_limit(self, connection_manager):
        """Test rate limiting when under limit"""
        identifier = "test_client"
        max_connections = 5
        time_window = 60

        # First connection - should be allowed
        allowed = await connection_manager.check_rate_limit(identifier, max_connections, time_window)
        assert allowed is True

    @pytest.mark.asyncio
    async def test_check_rate_limit_exceeded(self, connection_manager):
        """Test rate limiting when limit is exceeded"""
        identifier = "test_client"
        max_connections = 2
        time_window = 60

        # Add connections up to limit
        await connection_manager.check_rate_limit(identifier, max_connections, time_window)
        await connection_manager.check_rate_limit(identifier, max_connections, time_window)

        # Next connection should be denied
        allowed = await connection_manager.check_rate_limit(identifier, max_connections, time_window)
        assert allowed is False

    @pytest.mark.asyncio
    async def test_is_valid_job_id_valid(self, connection_manager):
        """Test valid job ID validation"""
        valid_job_ids = [
            "job_123",
            "job_abc-123_def",
            "job_12345678901234567890123456789012"  # 32 chars
        ]

        for job_id in valid_job_ids:
            assert connection_manager.is_valid_job_id(job_id) is True

    @pytest.mark.asyncio
    async def test_is_valid_job_id_invalid(self, connection_manager):
        """Test invalid job ID validation"""
        invalid_job_ids = [
            "",
            "job",
            "job_123!",  # Invalid character
            "job_123@#$",  # Invalid characters
            "a" * 51,  # Too long
            None
        ]

        for job_id in invalid_job_ids:
            assert connection_manager.is_valid_job_id(job_id) is False

    @pytest.mark.asyncio
    async def test_get_connection_stats(self, connection_manager):
        """Test getting connection statistics"""
        # Add some mock connections
        connection_manager.active_connections = 10
        connection_manager.rate_limit_violations = 5

        stats = connection_manager.get_connection_stats()

        assert stats["active_connections"] == 10
        assert stats["rate_limit_violations"] == 5
        assert "timestamp" in stats

    @pytest.mark.asyncio
    async def test_reset_stats(self, connection_manager):
        """Test resetting connection statistics"""
        # Set some stats
        connection_manager.active_connections = 10
        connection_manager.rate_limit_violations = 5

        # Reset stats
        connection_manager.reset_stats()

        # Verify reset
        stats = connection_manager.get_connection_stats()
        assert stats["active_connections"] == 0
        assert stats["rate_limit_violations"] == 0

    @pytest.mark.asyncio
    async def test_get_connection_manager_singleton(self):
        """Test getting connection manager singleton"""
        manager1 = get_connection_manager()
        manager2 = get_connection_manager()
        assert manager1 is manager2


class TestWebSocketIntegration:
    """Test WebSocket manager integration scenarios"""

    @pytest.mark.asyncio
    async def test_concurrent_connections(self, websocket_manager):
        """Test handling multiple concurrent connections"""
        job_id = "concurrent_job"
        num_connections = 10

        # Create multiple mock WebSockets
        mock_websockets = [MockWebSocket(f"client_{i}") for i in range(num_connections)]

        # Connect all concurrently
        connect_tasks = []
        for i, ws in enumerate(mock_websockets):
            task = websocket_manager.connect(ws, job_id, f"client_{i}")
            connect_tasks.append(task)

        # Wait for all connections
        await asyncio.gather(*connect_tasks)

        # Verify all connections
        assert len(websocket_manager.job_connections[job_id]) == num_connections
        assert len(websocket_manager.connections) == num_connections

    @pytest.mark.asyncio
    async def test_concurrent_broadcasts(self, websocket_manager, multiple_mock_websockets):
        """Test handling multiple concurrent broadcasts"""
        job_id = "broadcast_job"
        num_messages = 5

        # Connect clients
        client_ids = []
        for i, ws in enumerate(multiple_mock_websockets[:3]):
            client_id = f"client_{i}"
            await websocket_manager.connect(ws, job_id, client_id)
            client_ids.append(client_id)

        # Create multiple broadcast tasks
        broadcast_tasks = []
        for i in range(num_messages):
            message = {
                "type": "progress",
                "data": {"current": i + 1, "total": num_messages}
            }
            task = websocket_manager.broadcast_to_job(job_id, message)
            broadcast_tasks.append(task)

        # Wait for all broadcasts
        await asyncio.gather(*broadcast_tasks)

        # Verify all clients received all messages
        for ws in multiple_mock_websockets[:3]:
            assert len(ws.messages_sent) == num_messages

    @pytest.mark.asyncio
    async def test_rapid_connect_disconnect(self, websocket_manager):
        """Test rapid connect/disconnect operations"""
        job_id = "rapid_job"
        num_operations = 20

        for i in range(num_operations):
            # Connect
            ws = MockWebSocket(f"temp_client_{i}")
            client_id = await websocket_manager.connect(ws, job_id, f"temp_client_{i}")

            # Immediately disconnect
            await websocket_manager.disconnect(client_id)

        # Verify no connections remain
        assert len(websocket_manager.connections) == 0
        assert len(websocket_manager.job_connections) == 0

    @pytest.mark.asyncio
    async def test_large_message_broadcast(self, websocket_manager, mock_websocket):
        """Test broadcasting large messages"""
        job_id = "large_message_job"
        client_id = "large_client"

        # Connect client
        await websocket_manager.connect(mock_websocket, job_id, client_id)

        # Create a large message (simulating a large progress update)
        large_message = {
            "type": "progress",
            "data": {
                "progress": {
                    "current": 1000,
                    "total": 2000,
                    "percentage": 50.0,
                    "domains": [{"domain": f"example{i}.com"} for i in range(1000)],
                    "errors": [{"error": f"Error {i}"} for i in range(100)]
                }
            }
        }

        # Broadcast the large message
        await websocket_manager.broadcast_to_job(job_id, large_message)

        # Verify message was sent
        assert len(mock_websocket.messages_sent) == 1
        sent_data = json.loads(mock_websocket.messages_sent[0])
        assert sent_data["type"] == "progress"
        assert len(sent_data["data"]["progress"]["domains"]) == 1000
        assert len(sent_data["data"]["progress"]["errors"]) == 100

    @pytest.mark.asyncio
    async def test_websocket_error_handling(self, websocket_manager, mock_websocket):
        """Test WebSocket error handling"""
        job_id = "error_job"
        client_id = "error_client"

        # Connect client
        await websocket_manager.connect(mock_websocket, job_id, client_id)

        # Mock WebSocket to raise an exception on send
        async def send_text_error(data):
            raise ConnectionError("Connection reset by peer")

        mock_websocket.send_text = send_text_error

        # Send message (should handle the error)
        message = {"type": "test", "data": "error test"}
        await websocket_manager.send_message_to_client(client_id, message)

        # Connection should be removed due to error
        assert client_id not in websocket_manager.connections

    @pytest.mark.asyncio
    async def test_memory_cleanup_on_disconnect(self, websocket_manager, multiple_mock_websockets):
        """Test that memory is properly cleaned up on disconnect"""
        job_ids = ["job_1", "job_2", "job_3"]

        # Connect clients to different jobs
        client_ids = []
        for i, ws in enumerate(multiple_mock_websockets):
            job_id = job_ids[i % len(job_ids)]
            client_id = f"client_{i}"
            await websocket_manager.connect(ws, job_id, client_id)
            client_ids.append(client_id)

        # Verify initial state
        assert len(websocket_manager.connections) == 5
        for job_id in job_ids:
            assert job_id in websocket_manager.job_connections

        # Disconnect all clients
        for client_id in client_ids:
            await websocket_manager.disconnect(client_id)

        # Verify complete cleanup
        assert len(websocket_manager.connections) == 0
        assert len(websocket_manager.job_connections) == 0
        assert len(websocket_manager._connection_locks) == 0  # Locks should also be cleaned