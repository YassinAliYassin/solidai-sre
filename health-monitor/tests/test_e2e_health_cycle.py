"""
End-to-end tests for the full health check cycle (run_health_check).

Tests the complete flow: check_all_services -> process_results -> _record_history,
as well as the health summary API and model health cache.

These tests verify that the health monitor's core loop works correctly
end-to-end, including state transitions (healthy -> down -> recovery).
"""

import asyncio
import json
import os
import sys
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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
    monitor._model_health_cache = {"status": "pending", "models": [], "timestamp": None}
    yield
    monitor._last_status.clear()
    monitor._last_alert_time.clear()
    monitor._last_recovery_time.clear()
    monitor._circuit_breaker_counts.clear()
    monitor._circuit_breaker_opened.clear()


@pytest.fixture
def temp_history(tmp_path):
    """Use a temporary history file for test isolation."""
    old_path = monitor.HISTORY_FILE
    monitor.HISTORY_FILE = str(tmp_path / "test_health_history.json")
    yield monitor.HISTORY_FILE
    monitor.HISTORY_FILE = old_path


class TestRunHealthCheck:
    """Tests for the run_health_check() full cycle."""

    @pytest.mark.asyncio
    async def test_all_services_healthy(self, temp_history):
        """When all services are healthy, run_health_check should complete without errors."""
        now = _now_iso()
        mock_results = [
            {"name": "Config Service", "status": "healthy", "latency_ms": 10,
             "timestamp": now},
            {"name": "LiteLLM Proxy", "status": "healthy", "latency_ms": 15,
             "timestamp": now},
            {"name": "SRE Agent", "status": "healthy", "latency_ms": 20,
             "timestamp": now},
            {"name": "Web UI", "status": "healthy", "latency_ms": 5,
             "timestamp": now},
            {"name": "PostgreSQL", "status": "healthy", "latency_ms": 2,
             "timestamp": now},
            {"name": "Neo4j", "status": "healthy", "latency_ms": 3,
             "timestamp": now},
        ]

        with patch.object(monitor, "check_all_services", new_callable=AsyncMock) as mock_internal, \
             patch.object(monitor, "check_public_endpoints", new_callable=AsyncMock) as mock_public, \
             patch.object(monitor, "check_integrations", new_callable=AsyncMock) as mock_integrations, \
             patch.object(monitor, "send_telegram", new_callable=AsyncMock):
            mock_internal.return_value = mock_results
            mock_public.return_value = []
            mock_integrations.return_value = []

            await monitor.run_health_check()

        # Verify history was recorded
        history = monitor._load_history()
        assert len(history) == 6
        for result in mock_results:
            assert result["name"] in history
            assert len(history[result["name"]]) == 1
            assert history[result["name"]][0]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_service_down_triggers_alert(self, temp_history):
        """A service going down should trigger an alert via process_results."""
        now = _now_iso()
        mock_results = [
            {"name": "Config Service", "status": "down", "error": "Connection refused",
             "timestamp": now},
        ]

        with patch.object(monitor, "check_all_services", new_callable=AsyncMock) as mock_internal, \
             patch.object(monitor, "check_public_endpoints", new_callable=AsyncMock) as mock_public, \
             patch.object(monitor, "check_integrations", new_callable=AsyncMock) as mock_integrations, \
             patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
            mock_internal.return_value = mock_results
            mock_public.return_value = []
            mock_integrations.return_value = []

            await monitor.run_health_check()

        # Alert should have been sent
        mock_telegram.assert_called_once()
        call_args = mock_telegram.call_args
        message = call_args[0][0]
        assert "Config Service" in message
        assert "DOWN" in message

    @pytest.mark.asyncio
    async def test_recovery_triggers_notification(self, temp_history):
        """A service recovering from down to healthy should trigger a recovery notification."""
        now = _now_iso()
        # First cycle: service is down
        down_results = [
            {"name": "SRE Agent", "status": "down", "error": "Timeout",
             "timestamp": now},
        ]
        # Second cycle: service recovered
        healthy_results = [
            {"name": "SRE Agent", "status": "healthy", "latency_ms": 20,
             "timestamp": now},
        ]

        with patch.object(monitor, "check_all_services", new_callable=AsyncMock) as mock_internal, \
             patch.object(monitor, "check_public_endpoints", new_callable=AsyncMock) as mock_public, \
             patch.object(monitor, "check_integrations", new_callable=AsyncMock) as mock_integrations, \
             patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
            mock_public.return_value = []
            mock_integrations.return_value = []

            # First check: service goes down
            mock_internal.return_value = down_results
            await monitor.run_health_check()

            # Reset alert cooldown to allow recovery notification
            monitor._last_alert_time.clear()
            monitor._last_recovery_time.clear()

            # Second check: service recovers
            mock_internal.return_value = healthy_results
            await monitor.run_health_check()

        # Should have 2 calls: one for down, one for recovery
        assert mock_telegram.call_count == 2
        recovery_message = mock_telegram.call_args_list[1][0][0]
        assert "Recovery" in recovery_message or "HEALTHY" in recovery_message

    @pytest.mark.asyncio
    async def test_history_recorded_for_all_result_types(self, temp_history):
        """History should include internal, public, and integration results."""
        now = _now_iso()
        internal = [
            {"name": "Config Service", "status": "healthy", "latency_ms": 10,
             "timestamp": now},
        ]
        public = [
            {"name": "Solid Solutions", "status": "healthy", "latency_ms": 100,
             "timestamp": now},
        ]
        integrations = [
            {"name": "Telegram Bot", "status": "healthy", "latency_ms": 50,
             "details": "Bot @test_bot",
             "timestamp": now},
        ]

        with patch.object(monitor, "check_all_services", new_callable=AsyncMock) as mock_internal, \
             patch.object(monitor, "check_public_endpoints", new_callable=AsyncMock) as mock_public, \
             patch.object(monitor, "check_integrations", new_callable=AsyncMock) as mock_integrations, \
             patch.object(monitor, "send_telegram", new_callable=AsyncMock):
            mock_internal.return_value = internal
            mock_public.return_value = public
            mock_integrations.return_value = integrations

            await monitor.run_health_check()

        history = monitor._load_history()
        assert "Config Service" in history
        assert "Solid Solutions" in history
        assert "Telegram Bot" in history

    @pytest.mark.asyncio
    async def test_alert_cooldown_prevents_spam(self, temp_history):
        """Multiple consecutive down checks should not send multiple alerts."""
        now = _now_iso()
        down_results = [
            {"name": "Web UI", "status": "down", "error": "503",
             "timestamp": now},
        ]

        with patch.object(monitor, "check_all_services", new_callable=AsyncMock) as mock_internal, \
             patch.object(monitor, "check_public_endpoints", new_callable=AsyncMock) as mock_public, \
             patch.object(monitor, "check_integrations", new_callable=AsyncMock) as mock_integrations, \
             patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
            mock_public.return_value = []
            mock_integrations.return_value = []

            # Run 3 cycles with the same down service
            for i in range(3):
                mock_internal.return_value = [
                    {"name": "Web UI", "status": "down", "error": "503",
                     "timestamp": now},
                ]
                await monitor.run_health_check()

        # Only 1 alert should have been sent (cooldown prevents the other 2)
        assert mock_telegram.call_count == 1


def _now_iso():
    """Return current time in ISO format for test data."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _hours_ago_iso(hours):
    """Return ISO timestamp N hours ago."""
    import datetime
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    return t.isoformat()


class TestHealthSummary:
    """Tests for the /api/health-summary endpoint logic."""

    def test_get_uptime_stats_empty_history(self):
        """Uptime stats for unknown service should return None values."""
        stats = monitor.get_uptime_stats({}, "Nonexistent", 24)
        assert stats["uptime_pct"] is None
        assert stats["total_checks"] == 0

    def test_get_uptime_stats_all_healthy(self):
        """100% uptime when all entries are healthy."""
        now = _now_iso()
        history = {
            "Test Service": [
                {"timestamp": now, "status": "healthy"},
            ]
        }
        stats = monitor.get_uptime_stats(history, "Test Service", 24)
        assert stats["uptime_pct"] == 100.0
        assert stats["total_checks"] == 1
        assert stats["healthy_count"] == 1

    def test_get_uptime_stats_mixed(self):
        """Uptime should reflect ratio of healthy to total."""
        h1 = _hours_ago_iso(3)
        h2 = _hours_ago_iso(2)
        h3 = _hours_ago_iso(1)
        h4 = _now_iso()
        history = {
            "Test Service": [
                {"timestamp": h1, "status": "healthy"},
                {"timestamp": h2, "status": "down"},
                {"timestamp": h3, "status": "healthy"},
                {"timestamp": h4, "status": "down"},
            ]
        }
        stats = monitor.get_uptime_stats(history, "Test Service", 24)
        assert stats["uptime_pct"] == 50.0
        assert stats["total_checks"] == 4
        assert stats["healthy_count"] == 2

    def test_get_latency_stats_basic(self):
        """Latency stats should compute avg, min, max, percentiles."""
        now = _now_iso()
        history = {
            "Test Service": [
                {"timestamp": now, "status": "healthy", "latency_ms": 10},
            ]
        }
        stats = monitor.get_latency_stats(history, "Test Service", 24)
        assert stats["avg_ms"] == 10.0
        assert stats["min_ms"] == 10
        assert stats["max_ms"] == 10
        assert stats["count"] == 1

    def test_get_latency_stats_excludes_failed(self):
        """Failed checks should not contribute to latency stats."""
        h1 = _hours_ago_iso(2)
        h2 = _hours_ago_iso(1)
        h3 = _now_iso()
        history = {
            "Test Service": [
                {"timestamp": h1, "status": "healthy", "latency_ms": 10},
                {"timestamp": h2, "status": "down"},
                {"timestamp": h3, "status": "healthy", "latency_ms": 30},
            ]
        }
        stats = monitor.get_latency_stats(history, "Test Service", 24)
        assert stats["count"] == 2
        assert stats["avg_ms"] == 20.0


class TestModelHealthCache:
    """Tests for the model health cache and background refresh."""

    def test_compute_model_overall_all_healthy(self):
        """All healthy models should yield 'healthy' overall."""
        results = [
            {"model": "a", "status": "healthy"},
            {"model": "b", "status": "healthy"},
        ]
        assert monitor._compute_model_overall(results) == "healthy"

    def test_compute_model_overall_any_healthy(self):
        """Mix of healthy and degraded should yield 'degraded' overall."""
        results = [
            {"model": "a", "status": "healthy"},
            {"model": "b", "status": "timeout"},
        ]
        assert monitor._compute_model_overall(results) == "degraded"

    def test_compute_model_overall_all_down(self):
        """All unreachable models should yield 'all_down' overall."""
        results = [
            {"model": "a", "status": "unreachable"},
            {"model": "b", "status": "unreachable"},
        ]
        assert monitor._compute_model_overall(results) == "all_down"

    def test_compute_model_overall_no_credits(self):
        """No-credits status should be prioritized over timeout."""
        results = [
            {"model": "a", "status": "no_credits"},
            {"model": "b", "status": "timeout"},
        ]
        assert monitor._compute_model_overall(results) == "no_credits"

    def test_compute_model_overall_timeout_priority(self):
        """Timeout should be reported when no credits issue exists."""
        results = [
            {"model": "a", "status": "timeout"},
            {"model": "b", "status": "unreachable"},
        ]
        assert monitor._compute_model_overall(results) == "timeout"

    def test_model_list_matches_litellm_config(self):
        """_MODEL_LIST should contain all 6 models from the fallback chain."""
        assert len(monitor._MODEL_LIST) == 6
        expected = [
            "owl-alpha",
            "openai/gpt-oss-20b:free",
            "cohere/north-mini-code:free",
            "openai/gpt-oss-120b:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
        ]
        assert monitor._MODEL_LIST == expected

    def test_model_list_all_free_tier(self):
        """All models in _MODEL_LIST should be free-tier."""
        for model in monitor._MODEL_LIST:
            assert ":free" in model or model == "owl-alpha", (
                f"Model '{model}' is not free-tier"
            )


class TestProcessResults:
    """Tests for the process_results alerting logic."""

    @pytest.mark.asyncio
    async def test_degraded_status_triggers_alert(self, temp_history):
        """A service becoming degraded should trigger an alert."""
        results = [
            {"name": "LiteLLM Proxy", "status": "degraded", "http_status": 503,
             "latency_ms": 5000, "timestamp": _now_iso()},
        ]

        with patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
            await monitor.process_results(results)

        mock_telegram.assert_called_once()
        message = mock_telegram.call_args[0][0]
        assert "DEGRADED" in message

    @pytest.mark.asyncio
    async def test_healthy_no_alert(self, temp_history):
        """A healthy service should not trigger any alert."""
        results = [
            {"name": "Config Service", "status": "healthy", "latency_ms": 10,
             "timestamp": "2026-01-01T00:00:00+00:00"},
        ]

        with patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
            await monitor.process_results(results)

        mock_telegram.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_configured_no_alert(self, temp_history):
        """A not_configured integration should not trigger an alert."""
        results = [
            {"name": "Telegram Bot", "status": "not_configured",
             "error": "TELEGRAM_BOT_TOKEN not set",
             "timestamp": "2026-01-01T00:00:00+00:00"},
        ]

        with patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
            await monitor.process_results(results)

        mock_telegram.assert_not_called()

    @pytest.mark.asyncio
    async def test_latency_included_in_alert_message(self, temp_history):
        """Alert message should include latency when available."""
        results = [
            {"name": "SRE Agent", "status": "down", "error": "Timeout",
             "latency_ms": 10000, "timestamp": "2026-01-01T00:00:00+00:00"},
        ]

        with patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
            await monitor.process_results(results)

        message = mock_telegram.call_args[0][0]
        assert "10000ms" in message

    @pytest.mark.asyncio
    async def test_error_details_in_alert(self, temp_history):
        """Alert message should include error details."""
        results = [
            {"name": "PostgreSQL", "status": "down",
             "error": "Connection refused: postgres:5432",
             "timestamp": "2026-01-01T00:00:00+00:00"},
        ]

        with patch.object(monitor, "send_telegram", new_callable=AsyncMock) as mock_telegram:
            await monitor.process_results(results)

        message = mock_telegram.call_args[0][0]
        assert "Connection refused" in message
