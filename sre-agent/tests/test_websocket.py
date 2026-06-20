"""
Tests for WebSocket bidirectional agent communication.

Covers:
- WebSocket connection and acceptance
- Investigation request via WebSocket
- Event streaming via WebSocket
- Ping/pong keepalive
- Error handling
- Subscription cleanup
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def reset_state():
    """Reset all global state before each test."""
    import server
    server._background_tasks.clear()
    server._message_queues.clear()
    server._response_queues.clear()
    yield
    server._background_tasks.clear()
    server._message_queues.clear()
    server._response_queues.clear()


class MockWebSocket:
    """Mock FastAPI WebSocket for testing."""

    def __init__(self):
        self.sent_messages = []
        self._receive_queue = asyncio.Queue()
        self._closed = False
        self._accept_called = False

    async def accept(self):
        self._accept_called = True

    async def send_json(self, data):
        self.sent_messages.append(data)

    async def receive_text(self):
        return await self._receive_queue.get()

    async def close(self):
        self._closed = True

    def add_message(self, msg):
        """Add a message to the receive queue."""
        if isinstance(msg, dict):
            self._receive_queue.put_nowait(json.dumps(msg))
        else:
            self._receive_queue.put_nowait(msg)


@pytest.fixture
def mock_ws():
    return MockWebSocket()


@pytest.mark.anyio
async def test_websocket_accepts_connection(mock_ws):
    """WebSocket should accept connection on connect."""
    from server import ws_investigate

    mock_ws.add_message({"type": "close"})

    await ws_investigate(mock_ws)

    assert mock_ws._accept_called


@pytest.mark.anyio
async def test_websocket_ping_pong(mock_ws):
    """WebSocket should respond to ping with pong."""
    from server import ws_investigate

    mock_ws.add_message({"type": "ping"})
    mock_ws.add_message({"type": "close"})

    await ws_investigate(mock_ws)

    pong_messages = [m for m in mock_ws.sent_messages if m.get("type") == "pong"]
    assert len(pong_messages) == 1
    assert "timestamp" in pong_messages[0]


@pytest.mark.anyio
async def test_websocket_invalid_json(mock_ws):
    """WebSocket should return error for invalid JSON."""
    from server import ws_investigate

    mock_ws._receive_queue.put_nowait("not valid json{{{")
    mock_ws.add_message({"type": "close"})

    await ws_investigate(mock_ws)

    error_messages = [m for m in mock_ws.sent_messages if m.get("type") == "error"]
    assert len(error_messages) >= 1
    assert "Invalid JSON" in error_messages[0]["data"]["message"]


@pytest.mark.anyio
async def test_websocket_missing_prompt(mock_ws):
    """WebSocket should return error when prompt is missing."""
    from server import ws_investigate

    mock_ws.add_message({"type": "request"})
    mock_ws.add_message({"type": "close"})

    await ws_investigate(mock_ws)

    error_messages = [m for m in mock_ws.sent_messages if m.get("type") == "error"]
    assert len(error_messages) >= 1
    assert "Missing" in error_messages[0]["data"]["message"]


@pytest.mark.anyio
async def test_websocket_investigation_creates_thread(mock_ws):
    """WebSocket should create background thread for investigation."""
    import server
    from server import ws_investigate

    # Patch _record_run_start to avoid network calls
    with patch('server._record_run_start', new_callable=AsyncMock):
        async def run_ws():
            mock_ws.add_message({
                "prompt": "Test investigation",
                "thread_id": "test-ws-001",
            })
            await asyncio.sleep(0.3)
            mock_ws.add_message({"type": "close"})
            try:
                await ws_investigate(mock_ws)
            except Exception:
                pass

        try:
            await asyncio.wait_for(run_ws(), timeout=10.0)
        except asyncio.TimeoutError:
            pass

    assert mock_ws._accept_called
    assert "test-ws-001" in server._background_tasks


@pytest.mark.anyio
async def test_websocket_generates_thread_id(mock_ws):
    """WebSocket should generate thread_id if not provided."""
    import server
    from server import ws_investigate

    with patch('server._record_run_start', new_callable=AsyncMock):
        async def run_ws():
            mock_ws.add_message({"prompt": "Test without thread_id"})
            await asyncio.sleep(0.3)
            mock_ws.add_message({"type": "close"})
            try:
                await ws_investigate(mock_ws)
            except Exception:
                pass

        try:
            await asyncio.wait_for(run_ws(), timeout=10.0)
        except asyncio.TimeoutError:
            pass

    assert mock_ws._accept_called
    assert len(server._background_tasks) >= 1


@pytest.mark.anyio
async def test_websocket_closes_cleanly(mock_ws):
    """WebSocket should close cleanly on close message."""
    from server import ws_investigate

    mock_ws.add_message({"type": "close"})

    await ws_investigate(mock_ws)

    assert mock_ws._accept_called


@pytest.mark.anyio
async def test_websocket_events_forwarded(mock_ws):
    """WebSocket should forward events from response queue to client."""
    import server as srv
    from server import ws_investigate

    test_thread_id = "test-ws-events"
    response_queue = asyncio.Queue()
    srv._response_queues[test_thread_id] = response_queue
    srv._message_queues[test_thread_id] = asyncio.Queue()

    # Create a mock background task
    async def noop_bg_task(thread_id):
        await asyncio.sleep(999)

    bg_task = asyncio.create_task(noop_bg_task(test_thread_id))
    srv._background_tasks[test_thread_id] = bg_task

    async def inject_events():
        """Inject events into the response queue after WS subscription is ready."""
        # Wait long enough for ws_investigate to receive the prompt,
        # create the subscribe_and_forward task, and start awaiting the queue.
        await asyncio.sleep(0.5)
        await response_queue.put({
            "event": "thought",
            "data": {"text": "Hello from test", "agent_name": "test-agent"},
        })
        await response_queue.put(None)  # Completion

    with patch('server._record_run_start', new_callable=AsyncMock):
        async def run_ws():
            mock_ws.add_message({
                "prompt": "Test events",
                "thread_id": test_thread_id,
            })
            # Wait longer than inject_events so events arrive before close
            await asyncio.sleep(1.0)
            mock_ws.add_message({"type": "close"})
            try:
                await ws_investigate(mock_ws)
            except Exception:
                pass

        try:
            await asyncio.wait_for(
                asyncio.gather(inject_events(), run_ws()),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            pass

    # Check that events were forwarded
    thought_messages = [m for m in mock_ws.sent_messages if m.get("type") == "thought"]
    done_messages = [m for m in mock_ws.sent_messages if m.get("type") == "done"]
    assert len(thought_messages) >= 1
    assert len(done_messages) >= 1

    # Cleanup
    bg_task.cancel()


class TestWSCleanup:
    """Tests for subscription cleanup."""

    def test_cleanup_removes_finished(self):
        """_cleanup_ws_subscriptions should remove finished tasks."""
        import server as srv

        async def run_cleanup():
            # Create a task that completes immediately
            task = asyncio.create_task(asyncio.sleep(0))
            await asyncio.sleep(0.1)  # Let it complete

            pending_task = asyncio.create_task(asyncio.sleep(100))

            subscriptions = {
                "finished": task,
                "pending": pending_task,
            }

            srv._cleanup_ws_subscriptions(subscriptions)

            assert "finished" not in subscriptions
            assert "pending" in subscriptions

            # Cleanup
            pending_task.cancel()

        asyncio.run(run_cleanup())

    def test_cleanup_empty_dict(self):
        """_cleanup_ws_subscriptions should handle empty dict."""
        import server as srv
        srv._cleanup_ws_subscriptions({})
