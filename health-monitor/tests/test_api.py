"""Tests for the health monitor HTTP API endpoints."""

import json
import datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitor


@pytest.fixture
def sample_history():
    """Return a sample history dict."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "Config Service": [
            {
                "timestamp": (now - datetime.timedelta(minutes=i * 5)).isoformat(),
                "status": "healthy",
                "latency_ms": 100 + i * 10,
            }
            for i in range(10)
        ],
        "SRE Agent": [
            {
                "timestamp": (now - datetime.timedelta(minutes=i * 5)).isoformat(),
                "status": "down",
                "error": "Connection refused",
            }
            for i in range(3)
        ],
    }


@pytest.fixture
def mock_history(sample_history):
    """Patch the history functions to return sample data."""
    with patch.object(monitor, "_load_history", return_value=sample_history):
        with patch.object(monitor, "_save_history"):
            yield sample_history


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
class TestHealthEndpoint:
    """Tests for GET /health."""

    async def test_returns_200(self):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_returns_healthy_status(self):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "health-monitor"


@pytest.mark.anyio
class TestHealthHistoryEndpoint:
    """Tests for GET /api/health-history."""

    async def test_returns_200(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-history")
        assert resp.status_code == 200

    async def test_returns_all_services(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-history")
        data = resp.json()
        assert "Config Service" in data
        assert "SRE Agent" in data

    async def test_includes_uptime_stats(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-history")
        data = resp.json()
        assert "uptime" in data["Config Service"]
        assert data["Config Service"]["uptime"]["uptime_pct"] == 100.0

    async def test_includes_recent_entries(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-history")
        data = resp.json()
        assert "recent" in data["Config Service"]
        # Should return last 20 entries max
        assert len(data["Config Service"]["recent"]) <= 20

    async def test_includes_latency_for_healthy(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-history")
        data = resp.json()
        # Config Service is all healthy, should have latency
        assert "latency" in data["Config Service"]

    async def test_no_latency_for_all_down(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-history")
        data = resp.json()
        # SRE Agent is all down, should not have latency
        assert "latency" not in data["SRE Agent"]

    async def test_empty_history(self):
        with patch.object(monitor, "_load_history", return_value={}):
            transport = ASGITransport(app=monitor._api_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/health-history")
            assert resp.status_code == 200
            assert resp.json() == {}


@pytest.mark.anyio
class TestServiceHistoryEndpoint:
    """Tests for GET /api/health-history/{service_name}."""

    async def test_returns_200_for_known_service(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-history/Config%20Service")
        assert resp.status_code == 200

    async def test_returns_404_for_unknown_service(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-history/Nonexistent")
        assert resp.status_code == 404

    async def test_includes_service_name(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-history/Config%20Service")
        data = resp.json()
        assert data["name"] == "Config Service"

    async def test_includes_history(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-history/Config%20Service")
        data = resp.json()
        assert "history" in data
        assert len(data["history"]) == 10


@pytest.mark.anyio
class TestHealthSummaryEndpoint:
    """Tests for GET /api/health-summary."""

    async def test_returns_200(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-summary")
        assert resp.status_code == 200

    async def test_returns_overall_status(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-summary")
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("healthy", "degraded", "down")

    async def test_returns_services_list(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-summary")
        data = resp.json()
        assert "services" in data
        assert len(data["services"]) == 2

    async def test_includes_counts(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-summary")
        data = resp.json()
        assert "total_services" in data
        assert "healthy_count" in data
        assert "degraded_count" in data
        assert "down_count" in data

    async def test_includes_timestamp(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-summary")
        data = resp.json()
        assert "timestamp" in data

    async def test_service_has_status(self, mock_history):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health-summary")
        data = resp.json()
        for svc in data["services"]:
            assert "name" in svc
            assert "status" in svc
            assert "uptime_24h" in svc

    async def test_summary_alias(self, mock_history):
        """The /health/summary alias should also work."""
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health/summary")
        assert resp.status_code == 200


@pytest.mark.anyio
class TestModelHealthEndpoint:
    """Tests for GET /api/model-health."""

    async def test_returns_200(self):
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/model-health")
        assert resp.status_code == 200

    async def test_returns_cached_status(self):
        """Should return the cached model health status."""
        transport = ASGITransport(app=monitor._api_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/model-health")
        data = resp.json()
        assert "status" in data
        assert "models" in data

    async def test_default_cache_is_pending(self):
        """Initial cache should have 'pending' status."""
        old_cache = monitor._model_health_cache
        monitor._model_health_cache = {"status": "pending", "models": [], "timestamp": None}
        try:
            transport = ASGITransport(app=monitor._api_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/model-health")
            data = resp.json()
            assert data["status"] == "pending"
        finally:
            monitor._model_health_cache = old_cache
