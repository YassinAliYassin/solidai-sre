"""
Tests for error rate tracking and latency degradation alerting.

Covers:
- get_error_rate() calculation
- check_latency_degradation() threshold detection
- _check_error_rates_and_latency() alerting logic
- /api/error-rates endpoint
"""

import datetime
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitor


@pytest.fixture(autouse=True)
def reset_state():
    """Reset all global state before each test."""
    monitor._last_status.clear()
    monitor._last_alert_time.clear()
    monitor._last_recovery_time.clear()
    monitor._circuit_breaker_counts.clear()
    monitor._circuit_breaker_opened.clear()
    yield
    monitor._last_status.clear()
    monitor._last_alert_time.clear()
    monitor._last_recovery_time.clear()
    monitor._circuit_breaker_counts.clear()
    monitor._circuit_breaker_opened.clear()


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _hours_ago_iso(hours):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    return t.isoformat()


class TestGetErrorRate:
    """Tests for the get_error_rate() function."""

    def test_empty_history(self):
        """Error rate for unknown service should return None."""
        result = monitor.get_error_rate({}, "Nonexistent", 1)
        assert result["error_rate"] is None
        assert result["total_checks"] == 0
        assert result["failed_count"] == 0

    def test_all_healthy(self):
        """Error rate should be 0.0 when all entries are healthy."""
        now = _now_iso()
        history = {
            "Test Service": [
                {"timestamp": now, "status": "healthy"},
                {"timestamp": now, "status": "healthy"},
            ]
        }
        result = monitor.get_error_rate(history, "Test Service", 1)
        assert result["error_rate"] == 0.0
        assert result["total_checks"] == 2
        assert result["failed_count"] == 0

    def test_all_down(self):
        """Error rate should be 1.0 when all entries are down."""
        h1 = _hours_ago_iso(0.5)
        h2 = _hours_ago_iso(0.25)
        history = {
            "Test Service": [
                {"timestamp": h1, "status": "down"},
                {"timestamp": h2, "status": "down"},
            ]
        }
        result = monitor.get_error_rate(history, "Test Service", 1)
        assert result["error_rate"] == 1.0
        assert result["total_checks"] == 2
        assert result["failed_count"] == 2

    def test_mixed_status(self):
        """Error rate should reflect ratio of failed to total."""
        h1 = _hours_ago_iso(0.5)
        h2 = _hours_ago_iso(0.25)
        h3 = _now_iso()
        history = {
            "Test Service": [
                {"timestamp": h1, "status": "healthy"},
                {"timestamp": h2, "status": "down"},
                {"timestamp": h3, "status": "healthy"},
            ]
        }
        result = monitor.get_error_rate(history, "Test Service", 1)
        assert result["error_rate"] == pytest.approx(0.333, abs=0.01)
        assert result["total_checks"] == 3
        assert result["failed_count"] == 1

    def test_degraded_counts_as_failure(self):
        """Degraded status should count as a failure in error rate."""
        h1 = _hours_ago_iso(0.5)
        h2 = _hours_ago_iso(0.25)
        history = {
            "Test Service": [
                {"timestamp": h1, "status": "healthy"},
                {"timestamp": h2, "status": "degraded"},
            ]
        }
        result = monitor.get_error_rate(history, "Test Service", 1)
        assert result["error_rate"] == 0.5
        assert result["failed_count"] == 1

    def test_timeout_counts_as_failure(self):
        """Timeout status should count as a failure."""
        h1 = _hours_ago_iso(0.5)
        history = {
            "Test Service": [
                {"timestamp": h1, "status": "timeout"},
            ]
        }
        result = monitor.get_error_rate(history, "Test Service", 1)
        assert result["error_rate"] == 1.0

    def test_unreachable_counts_as_failure(self):
        """Unreachable status should count as a failure."""
        h1 = _hours_ago_iso(0.5)
        history = {
            "Test Service": [
                {"timestamp": h1, "status": "unreachable"},
            ]
        }
        result = monitor.get_error_rate(history, "Test Service", 1)
        assert result["error_rate"] == 1.0

    def test_window_excludes_old_entries(self):
        """Entries outside the window should not count."""
        h_old = _hours_ago_iso(3)
        h_recent = _now_iso()
        history = {
            "Test Service": [
                {"timestamp": h_old, "status": "down"},
                {"timestamp": h_recent, "status": "healthy"},
            ]
        }
        # 1-hour window should exclude the 3-hour-old entry
        result = monitor.get_error_rate(history, "Test Service", 1)
        assert result["total_checks"] == 1
        assert result["error_rate"] == 0.0

    def test_default_window_uses_config(self):
        """When window_hours is None, should use ERROR_RATE_WINDOW config."""
        now = _now_iso()
        history = {
            "Test Service": [
                {"timestamp": now, "status": "healthy"},
            ]
        }
        result = monitor.get_error_rate(history, "Test Service")
        assert result["window_hours"] == monitor.ERROR_RATE_WINDOW

    def test_not_configured_not_counted_as_failure(self):
        """not_configured status should not count as a failure."""
        h1 = _hours_ago_iso(0.5)
        history = {
            "Test Service": [
                {"timestamp": h1, "status": "not_configured"},
            ]
        }
        result = monitor.get_error_rate(history, "Test Service", 1)
        assert result["error_rate"] == 0.0
        assert result["failed_count"] == 0


class TestCheckLatencyDegradation:
    """Tests for the check_latency_degradation() function."""

    def test_no_data(self):
        """Should return degraded=False when no history exists."""
        result = monitor.check_latency_degradation({}, "Nonexistent")
        assert result["degraded"] is False
        assert result["p95_ms"] is None

    def test_latency_below_threshold(self):
        """Should return degraded=False when p95 is below threshold."""
        now = _now_iso()
        history = {
            "Test Service": [
                {"timestamp": now, "status": "healthy", "latency_ms": 100},
            ]
        }
        result = monitor.check_latency_degradation(history, "Test Service")
        assert result["degraded"] is False
        assert result["reason"] == "ok"

    def test_latency_above_threshold(self):
        """Should return degraded=True when p95 exceeds threshold."""
        now = _now_iso()
        # Create entries with high latency
        history = {
            "Test Service": [
                {"timestamp": now, "status": "healthy", "latency_ms": 10000},
            ]
        }
        result = monitor.check_latency_degradation(history, "Test Service", threshold_ms=5000)
        assert result["degraded"] is True
        assert result["p95_ms"] == 10000
        assert "exceeds threshold" in result["reason"]

    def test_custom_threshold(self):
        """Should respect custom threshold parameter."""
        now = _now_iso()
        history = {
            "Test Service": [
                {"timestamp": now, "status": "healthy", "latency_ms": 500},
            ]
        }
        # Below default 5000ms threshold
        result = monitor.check_latency_degradation(history, "Test Service")
        assert result["degraded"] is False

        # Above custom 100ms threshold
        result = monitor.check_latency_degradation(history, "Test Service", threshold_ms=100)
        assert result["degraded"] is True

    def test_excludes_failed_entries(self):
        """Failed entries should not contribute to latency stats."""
        h1 = _hours_ago_iso(0.5)
        now = _now_iso()
        history = {
            "Test Service": [
                {"timestamp": h1, "status": "down"},
                {"timestamp": now, "status": "healthy", "latency_ms": 100},
            ]
        }
        result = monitor.check_latency_degradation(history, "Test Service")
        assert result["degraded"] is False
        assert result["p95_ms"] == 100


class TestCheckErrorRatesAndLatency:
    """Tests for the _check_error_rates_and_latency() alerting function."""

    @pytest.mark.asyncio
    async def test_high_error_rate_triggers_alert(self, tmp_path):
        """A service with high error rate should trigger an alert."""
        old_path = monitor.HISTORY_FILE
        monitor.HISTORY_FILE = str(tmp_path / "test_history.json")
        try:
            # Build history with high error rate
            h1 = _hours_ago_iso(0.5)
            h2 = _hours_ago_iso(0.25)
            now = _now_iso()
            history = {
                "SRE Agent": [
                    {"timestamp": h1, "status": "down"},
                    {"timestamp": h2, "status": "down"},
                    {"timestamp": now, "status": "healthy"},
                ]
            }
            monitor._save_history(history)

            current_results = [
                {"name": "SRE Agent", "status": "healthy", "latency_ms": 20, "timestamp": now},
            ]

            with patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
                await monitor._check_error_rates_and_latency(current_results)

            mock_telegram.assert_called_once()
            message = mock_telegram.call_args[0][0]
            assert "Error Rate" in message
            assert "SRE Agent" in message
        finally:
            monitor.HISTORY_FILE = old_path

    @pytest.mark.asyncio
    async def test_low_error_rate_no_alert(self, tmp_path):
        """A service with low error rate should not trigger an alert."""
        old_path = monitor.HISTORY_FILE
        monitor.HISTORY_FILE = str(tmp_path / "test_history.json")
        try:
            now = _now_iso()
            history = {
                "Config Service": [
                    {"timestamp": now, "status": "healthy", "latency_ms": 10},
                ]
            }
            monitor._save_history(history)

            current_results = [
                {"name": "Config Service", "status": "healthy", "latency_ms": 10, "timestamp": now},
            ]

            with patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
                await monitor._check_error_rates_and_latency(current_results)

            mock_telegram.assert_not_called()
        finally:
            monitor.HISTORY_FILE = old_path

    @pytest.mark.asyncio
    async def test_latency_degradation_triggers_alert(self, tmp_path):
        """A service with degraded latency should trigger an alert."""
        old_path = monitor.HISTORY_FILE
        monitor.HISTORY_FILE = str(tmp_path / "test_history.json")
        try:
            now = _now_iso()
            history = {
                "Web UI": [
                    {"timestamp": now, "status": "healthy", "latency_ms": 10000},
                ]
            }
            monitor._save_history(history)

            current_results = [
                {"name": "Web UI", "status": "healthy", "latency_ms": 10000, "timestamp": now},
            ]

            with patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
                await monitor._check_error_rates_and_latency(current_results)

            mock_telegram.assert_called_once()
            message = mock_telegram.call_args[0][0]
            assert "Latency" in message or "latency" in message
        finally:
            monitor.HISTORY_FILE = old_path

    @pytest.mark.asyncio
    async def test_down_service_skipped(self, tmp_path):
        """Services already down should be skipped (handled by process_results)."""
        old_path = monitor.HISTORY_FILE
        monitor.HISTORY_FILE = str(tmp_path / "test_history.json")
        try:
            now = _now_iso()
            history = {
                "SRE Agent": [
                    {"timestamp": now, "status": "down", "error": "Timeout"},
                ]
            }
            monitor._save_history(history)

            current_results = [
                {"name": "SRE Agent", "status": "down", "error": "Timeout", "timestamp": now},
            ]

            with patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
                await monitor._check_error_rates_and_latency(current_results)

            mock_telegram.assert_not_called()
        finally:
            monitor.HISTORY_FILE = old_path

    @pytest.mark.asyncio
    async def test_error_rate_cooldown(self, tmp_path):
        """Error rate alerts should respect cooldown."""
        old_path = monitor.HISTORY_FILE
        monitor.HISTORY_FILE = str(tmp_path / "test_history.json")
        try:
            h1 = _hours_ago_iso(0.5)
            now = _now_iso()
            history = {
                "SRE Agent": [
                    {"timestamp": h1, "status": "down"},
                    {"timestamp": now, "status": "healthy"},
                ]
            }
            monitor._save_history(history)

            # Set a recent alert to trigger cooldown
            monitor._last_alert_time["SRE Agent:error_rate"] = __import__("time").monotonic()

            current_results = [
                {"name": "SRE Agent", "status": "healthy", "latency_ms": 20, "timestamp": now},
            ]

            with patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
                await monitor._check_error_rates_and_latency(current_results)

            mock_telegram.assert_not_called()
        finally:
            monitor.HISTORY_FILE = old_path


class TestErrorRatesEndpoint:
    """Tests for GET /api/error-rates."""

    @pytest.mark.anyio
    async def test_returns_200(self, tmp_path):
        from httpx import AsyncClient, ASGITransport
        old_path = monitor.HISTORY_FILE
        monitor.HISTORY_FILE = str(tmp_path / "test_history.json")
        try:
            now = _now_iso()
            history = {
                "Config Service": [
                    {"timestamp": now, "status": "healthy", "latency_ms": 100},
                ]
            }
            monitor._save_history(history)

            with patch.object(monitor, "_load_history", return_value=history):
                transport = ASGITransport(app=monitor._api_app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/error-rates")
            assert resp.status_code == 200
        finally:
            monitor.HISTORY_FILE = old_path

    @pytest.mark.anyio
    async def test_includes_error_rate(self, tmp_path):
        from httpx import AsyncClient, ASGITransport
        old_path = monitor.HISTORY_FILE
        monitor.HISTORY_FILE = str(tmp_path / "test_history.json")
        try:
            now = _now_iso()
            history = {
                "Config Service": [
                    {"timestamp": now, "status": "healthy", "latency_ms": 100},
                ]
            }

            with patch.object(monitor, "_load_history", return_value=history):
                transport = ASGITransport(app=monitor._api_app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/error-rates")
            data = resp.json()
            assert "Config Service" in data
            assert "error_rate" in data["Config Service"]
            assert "latency_degradation" in data["Config Service"]
        finally:
            monitor.HISTORY_FILE = old_path

    @pytest.mark.anyio
    async def test_empty_history(self):
        from httpx import AsyncClient, ASGITransport
        with patch.object(monitor, "_load_history", return_value={}):
            transport = ASGITransport(app=monitor._api_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/error-rates")
            assert resp.status_code == 200
            assert resp.json() == {}

    @pytest.mark.anyio
    async def test_custom_window_param(self, tmp_path):
        from httpx import AsyncClient, ASGITransport
        old_path = monitor.HISTORY_FILE
        monitor.HISTORY_FILE = str(tmp_path / "test_history.json")
        try:
            now = _now_iso()
            history = {
                "Config Service": [
                    {"timestamp": now, "status": "healthy", "latency_ms": 100},
                ]
            }

            with patch.object(monitor, "_load_history", return_value=history):
                transport = ASGITransport(app=monitor._api_app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get("/api/error-rates?window_hours=6")
            assert resp.status_code == 200
        finally:
            monitor.HISTORY_FILE = old_path
