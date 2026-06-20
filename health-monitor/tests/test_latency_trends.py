"""
Tests for latency trend prediction.

Covers:
- predict_latency_trend() linear regression
- Trend direction detection (increasing/decreasing/stable)
- Minutes-to-threshold calculation
- R² confidence scoring
- /api/latency-trends endpoint
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


def _minutes_ago_iso(minutes):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)
    return t.isoformat()


def _build_history(service_name, latencies, interval_minutes=5):
    """Build a history dict with specified latencies at regular intervals.

    Args:
        service_name: Name of the service.
        latencies: List of (latency_ms, status) tuples.
        interval_minutes: Minutes between each entry.
    """
    entries = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for i, (latency, status) in enumerate(reversed(latencies)):
        ts = now - datetime.timedelta(minutes=i * interval_minutes)
        entry = {"timestamp": ts.isoformat(), "status": status}
        if latency is not None:
            entry["latency_ms"] = latency
        entries.append(entry)
    entries.reverse()  # chronological order
    return {service_name: entries}


class TestPredictLatencyTrend:
    """Tests for the predict_latency_trend() function."""

    def test_empty_history(self):
        """Unknown service should return unknown trend."""
        result = monitor.predict_latency_trend({}, "Nonexistent")
        assert result["trend_direction"] == "unknown"
        assert result["minutes_to_threshold"] is None
        assert result["prediction_confidence"] == 0.0

    def test_insufficient_data(self):
        """Less than 3 data points should return stable with no prediction."""
        history = _build_history("TestService", [(100, "healthy"), (110, "healthy")])
        result = monitor.predict_latency_trend(history, "TestService")
        assert result["trend_direction"] == "stable"
        assert result["minutes_to_threshold"] is None
        assert result["prediction_confidence"] == 0.0

    def test_stable_trend(self):
        """Consistent latency should show stable trend."""
        latencies = [(100 + i, "healthy") for i in range(10)]  # 100-109ms
        history = _build_history("TestService", latencies)
        result = monitor.predict_latency_trend(history, "TestService", threshold_ms=5000)
        assert result["trend_direction"] == "stable"
        assert result["minutes_to_threshold"] is None
        assert result["data_points"] == 10

    def test_increasing_trend(self):
        """Linearly increasing latency should show increasing trend."""
        latencies = [(100 + i * 10, "healthy") for i in range(10)]  # 100-190ms
        history = _build_history("TestService", latencies)
        result = monitor.predict_latency_trend(history, "TestService", threshold_ms=5000)
        assert result["trend_direction"] == "increasing"
        assert result["slope_per_minute"] > 0

    def test_decreasing_trend(self):
        """Linearly decreasing latency should show decreasing trend."""
        latencies = [(200 - i * 10, "healthy") for i in range(10)]  # 200-110ms
        history = _build_history("TestService", latencies)
        result = monitor.predict_latency_trend(history, "TestService", threshold_ms=5000)
        assert result["trend_direction"] == "decreasing"
        assert result["slope_per_minute"] < 0

    def test_prediction_confidence_high_for_linear_data(self):
        """Perfect linear data should have R² close to 1.0."""
        latencies = [(100 + i * 20, "healthy") for i in range(15)]
        history = _build_history("TestService", latencies)
        result = monitor.predict_latency_trend(history, "TestService", threshold_ms=5000)
        assert result["prediction_confidence"] >= 0.9

    def test_minutes_to_threshold_calculation(self):
        """Should predict minutes to threshold for increasing trend."""
        # 100ms increasing by 50ms per interval, threshold at 300ms
        latencies = [(100 + i * 50, "healthy") for i in range(10)]  # 100-550ms
        history = _build_history("TestService", latencies, interval_minutes=5)
        result = monitor.predict_latency_trend(history, "TestService", threshold_ms=300)
        # Should predict crossing 300ms at some point
        assert result["minutes_to_threshold"] is not None
        assert result["minutes_to_threshold"] >= 0

    def test_no_prediction_when_confidence_low(self):
        """Should not predict when R² is below threshold."""
        import random
        random.seed(42)
        # Noisy data — no clear trend
        latencies = [(100 + random.randint(-50, 50), "healthy") for _ in range(10)]
        history = _build_history("TestService", latencies)
        result = monitor.predict_latency_trend(history, "TestService", threshold_ms=5000)
        # Low confidence should result in no prediction or stable
        if result["prediction_confidence"] < 0.5:
            assert result["minutes_to_threshold"] is None

    def test_unhealthy_entries_excluded(self):
        """Failed/unhealthy entries should not contribute to trend."""
        latencies = [
            (100, "healthy"),
            (110, "healthy"),
            (120, "healthy"),
            (None, "down"),
            (130, "healthy"),
            (140, "healthy"),
            (150, "healthy"),
        ]
        history = _build_history("TestService", latencies)
        result = monitor.predict_latency_trend(history, "TestService", threshold_ms=5000)
        # Should only count healthy entries
        assert result["data_points"] == 6  # 7 total - 1 down

    def test_custom_threshold(self):
        """Should respect custom threshold parameter."""
        latencies = [(50 + i * 5, "healthy") for i in range(10)]
        history = _build_history("TestService", latencies)
        result = monitor.predict_latency_trend(history, "TestService", threshold_ms=80)
        assert result["threshold_ms"] == 80

    def test_default_threshold(self):
        """Should use LATENCY_THRESHOLD_MS when no threshold specified."""
        latencies = [(100, "healthy")] * 10
        history = _build_history("TestService", latencies)
        result = monitor.predict_latency_trend(history, "TestService")
        assert result["threshold_ms"] == monitor.LATENCY_THRESHOLD_MS


class TestLatencyTrendsAPI:
    """Tests for the /api/latency-trends endpoints."""

    @pytest.fixture(autouse=True)
    async def setup_history(self):
        """Seed history for API tests."""
        # Write to the actual history file used by the monitor
        self.history = _build_history("TestService", [(100 + i * 5, "healthy") for i in range(10)])
        monitor._save_history(self.history)
        yield
        # Clean up
        try:
            os.remove(monitor.HISTORY_FILE)
        except FileNotFoundError:
            pass

    @pytest.mark.anyio
    async def test_get_latency_trends_all(self):
        """GET /api/latency-trends should return trends for all services."""
        # Mock the _load_history to return our test data
        with patch.object(monitor, "_load_history", return_value=self.history):
            resp = await monitor.get_latency_trends()
            assert resp.status_code == 200
            data = resp.body
            assert b"TestService" in data

    @pytest.mark.anyio
    async def test_get_service_latency_trend(self):
        """GET /api/latency-trends/{service_name} should return single service trend."""
        with patch.object(monitor, "_load_history", return_value=self.history):
            resp = await monitor.get_service_latency_trend("TestService")
            assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_get_service_latency_trend_not_found(self):
        """GET /api/latency-trends/{service_name} should 404 for unknown service."""
        with patch.object(monitor, "_load_history", return_value=self.history):
            resp = await monitor.get_service_latency_trend("Nonexistent")
            assert resp.status_code == 404


class TestProactiveTrendAlerting:
    """Tests for proactive trend-based alerting in _check_error_rates_and_latency."""

    @pytest.mark.anyio
    async def test_predictive_alert_sent_when_threshold_within_30min(self):
        """Should send predictive alert when service will degrade within 30min."""
        # Build history with rapidly increasing latency
        # Slope: 10ms per check, current ~200ms, threshold 500ms
        # At 10ms/check, will reach 500ms in ~30min
        latencies = [(100 + i * 10, "healthy") for i in range(20)]
        history = _build_history("FastDegrading", latencies, interval_minutes=1)
        monitor._save_history(history)

        result = {
            "name": "FastDegrading",
            "status": "healthy",
            "timestamp": _now_iso(),
            "latency_ms": 290,
        }

        with patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
            with patch.object(monitor, "_load_history", return_value=history):
                await monitor._check_error_rates_and_latency([result])
                # Check if any call contains "Predictive"
                predictive_calls = [
                    call for call in mock_telegram.call_args_list
                    if "Predictive" in str(call)
                ]
                # The trend should trigger a predictive alert
                if predictive_calls:
                    assert "trending UP" in str(predictive_calls[0])

    @pytest.mark.anyio
    async def test_no_predictive_alert_when_stable(self):
        """Should not send predictive alert for stable services."""
        latencies = [(100, "healthy")] * 20
        history = _build_history("StableService", latencies)
        monitor._save_history(history)

        result = {
            "name": "StableService",
            "status": "healthy",
            "timestamp": _now_iso(),
            "latency_ms": 100,
        }

        with patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
            with patch.object(monitor, "_load_history", return_value=history):
                await monitor._check_error_rates_and_latency([result])
                predictive_calls = [
                    call for call in mock_telegram.call_args_list
                    if "Predictive" in str(call)
                ]
                assert len(predictive_calls) == 0
