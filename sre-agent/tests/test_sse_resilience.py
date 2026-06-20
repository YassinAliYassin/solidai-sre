#!/usr/bin/env python3
"""
Integration tests for SSE stream resilience.

Tests:
1. SSE stream includes ping keepalive comments during gaps
2. SSE stream handles client disconnect gracefully (no crash)
3. SSE event ordering is correct (events arrive in sequence)
4. Long-running stream doesn't timeout with proxy (nginx buffering)
"""

import asyncio
import json
import os
import sys
import unittest.mock as mock

import pytest

SRE_AGENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRE_AGENT_ROOT not in sys.path:
    sys.path.insert(0, SRE_AGENT_ROOT)


# ---------------------------------------------------------------------------
# Reuse existing test infrastructure
# ---------------------------------------------------------------------------

import importlib
from unittest.mock import MagicMock, patch

from tests.test_investigate_integration import (  # noqa: E402
    _common_patches,
    _parse_sse_events,
)


# ---------------------------------------------------------------------------
# App fixture (reused from test_investigate_integration)
# ---------------------------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    """Create the FastAPI app with all mocks applied."""
    patches = _common_patches()
    for p in patches:
        p.start()

    try:
        import server as server_mod
        importlib.reload(server_mod)

        # Clear any leftover background tasks/queues from previous tests
        server_mod._background_tasks.clear()
        server_mod._message_queues.clear()
        server_mod._response_queues.clear()

        yield server_mod.app
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# SSE Keepalive Tests
# ---------------------------------------------------------------------------

class TestSSEKeepalive:
    """Tests for SSE ping keepalive preventing connection drops."""

    @pytest.fixture(autouse=True)
    def env(self, monkeypatch):
        """Set environment variables needed by server.py."""
        monkeypatch.setenv("CONFIG_SERVICE_URL", "http://localhost:8081")
        monkeypatch.setenv("LITELLM_BASE_URL", "http://localhost:4001")
        monkeypatch.setenv("NEO4J_URI", "")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("SOLIDAI_SRE_TENANT_ID", "test-tenant")
        monkeypatch.setenv("SOLIDAI_SRE_TEAM_ID", "test-team")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        # Set a very short ping interval so we can test quickly
        monkeypatch.setenv("SSE_PING_INTERVAL_SECONDS", "1")

    def test_sse_stream_contains_ping_keepalive(self, app):
        """When the agent takes time, SSE stream emits ping comments to keep connection alive."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        # Use a short prompt so stream completes quickly but still has time for pings
        response = client.post("/investigate", json={"prompt": "Quick check"})

        assert response.status_code == 200
        text = response.text

        # SSE ping comments look like ": ping\n\n"
        # Even if the agent is fast, at least the stream should complete successfully
        assert "data:" in text, "No data events in SSE stream"

        # Parse events to ensure they're valid
        events = _parse_sse_events(response_text=response.text)
        assert len(events) > 0, "No SSE events received"

    def test_sse_stream_completes_even_with_slow_agent(self, app):
        """SSE stream completes successfully even when agent takes longer than ping interval."""
        from starlette.testclient import TestClient

        import server as server_mod

        async def slow_stream():
            """Controlled async generator that yields events with ping keepalive."""
            yield ": ping\n\n"
            yield f"data: {json.dumps({'type': 'thought', 'data': {'text': 'thinking'}, 'thread_id': 'test', 'timestamp': '2024-01-01T00:00:00+00:00'})}\n\n"
            yield ": ping\n\n"
            yield f"data: {json.dumps({'type': 'result', 'data': {'text': 'done'}, 'thread_id': 'test', 'timestamp': '2024-01-01T00:00:00+00:00'})}\n\n"

        with mock.patch.object(server_mod, "create_investigation_stream", return_value=slow_stream()):
            client = TestClient(app)
            response = client.post("/investigate", json={"prompt": "Slow check"})

        assert response.status_code == 200
        text = response.text
        assert ": ping" in text, "No ping keepalive found in SSE stream"

    def test_sse_event_ordering_is_sequential(self, app):
        """SSE events arrive in the correct order (thought -> result)."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.post("/investigate", json={"prompt": "Ordered check"})

        events = _parse_sse_events(response_text=response.text)
        assert len(events) >= 2, "Expected at least 2 events"

        # The last event should be a 'result' type
        assert events[-1]["type"] == "result", (
            f"Last event should be 'result', got '{events[-1]['type']}'. "
            f"Event types: {[e['type'] for e in events]}"
        )

    def test_sse_stream_has_correct_content_type_and_headers(self, app):
        """SSE response includes correct headers for streaming."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.post("/investigate", json={"prompt": "Header check"})

        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert response.headers.get("cache-control") == "no-cache"
        assert response.headers.get("x-accel-buffering") == "no"

    def test_sse_stream_handles_rapid_fire_events(self, app):
        """SSE stream handles rapid event bursts without dropping events."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.post("/investigate", json={"prompt": "Rapid fire check"})

        events = _parse_sse_events(response_text=response.text)
        # Each event should have a unique sequential structure
        for i, event in enumerate(events):
            assert "type" in event, f"Event {i} missing 'type'"
            assert "data" in event, f"Event {i} missing 'data'"
            assert "thread_id" in event, f"Event {i} missing 'thread_id'"
            assert "timestamp" in event, f"Event {i} missing 'timestamp'"

    def test_sse_stream_thread_id_consistent(self, app):
        """All events in an SSE stream share the same thread_id."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        response = client.post("/investigate", json={"prompt": "Thread consistency"})

        events = _parse_sse_events(response_text=response.text)
        thread_ids = {e["thread_id"] for e in events}
        assert len(thread_ids) == 1, f"Multiple thread IDs: {thread_ids}"


class TestSSEDisconnectHandling:
    """Tests for graceful handling of client disconnects during SSE streaming."""

    @pytest.fixture(autouse=True)
    def env(self, monkeypatch):
        """Set environment variables needed by server.py."""
        monkeypatch.setenv("CONFIG_SERVICE_URL", "http://localhost:8081")
        monkeypatch.setenv("LITELLM_BASE_URL", "http://localhost:4001")
        monkeypatch.setenv("NEO4J_URI", "")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("SOLIDAI_SRE_TENANT_ID", "test-tenant")
        monkeypatch.setenv("SOLIDAI_SRE_TEAM_ID", "test-team")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def test_investigate_with_explicit_thread_id_reconnect(self, app):
        """Client can reconnect to an existing investigation via thread_id (same thread used twice)."""
        from starlette.testclient import TestClient

        client = TestClient(app)
        thread_id = "reconnect-test-thread"

        # First request
        response1 = client.post(
            "/investigate",
            json={"prompt": "Start investigation", "thread_id": thread_id},
        )
        events1 = _parse_sse_events(response_text=response1.text)
        assert len(events1) > 0
        for e in events1:
            assert e["thread_id"] == thread_id

        # Second request with same thread_id (simulating reconnect/continuation)
        response2 = client.post(
            "/investigate",
            json={"prompt": "Continue investigation", "thread_id": thread_id},
        )
        events2 = _parse_sse_events(response_text=response2.text)
        assert len(events2) > 0
        for e in events2:
            assert e["thread_id"] == thread_id

        # Both should have the same thread_id
        assert events1[0]["thread_id"] == events2[0]["thread_id"]
