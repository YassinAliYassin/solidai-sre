"""Tests for alert cooldown logic and model health computation."""

import time
from unittest.mock import patch, AsyncMock

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitor


@pytest.fixture(autouse=True)
def reset_alert_state():
    """Reset alert tracking state before each test."""
    monitor._last_status.clear()
    monitor._last_alert_time.clear()
    monitor._last_recovery_time.clear()
    yield
    monitor._last_status.clear()
    monitor._last_alert_time.clear()
    monitor._last_recovery_time.clear()


class TestShouldAlert:
    """Tests for _should_alert."""

    def test_should_alert_when_no_previous_alert(self):
        """Should alert when there's no previous alert."""
        assert monitor._should_alert("svc", "down") is True

    def test_should_not_alert_during_cooldown(self):
        """Should not alert during the cooldown period."""
        monitor._last_alert_time["svc"] = time.monotonic()
        assert monitor._should_alert("svc", "down") is False

    def test_should_alert_after_cooldown(self):
        """Should alert after cooldown expires."""
        monitor._last_alert_time["svc"] = (
            time.monotonic() - monitor.ALERT_COOLDOWN - 1
        )
        assert monitor._should_alert("svc", "down") is True

    def test_independent_per_service(self):
        """Alert cooldown should be independent per service."""
        monitor._last_alert_time["svc-a"] = time.monotonic()
        assert monitor._should_alert("svc-a", "down") is False
        assert monitor._should_alert("svc-b", "down") is True


class TestShouldNotifyRecovery:
    """Tests for _should_notify_recovery."""

    def test_should_notify_when_no_previous_recovery(self):
        """Should notify recovery when there's no previous notification."""
        assert monitor._should_notify_recovery("svc") is True

    def test_should_not_notify_during_cooldown(self):
        """Should not notify recovery during cooldown."""
        monitor._last_recovery_time["svc"] = time.monotonic()
        assert monitor._should_notify_recovery("svc") is False

    def test_should_notify_after_cooldown(self):
        """Should notify recovery after cooldown expires."""
        monitor._last_recovery_time["svc"] = (
            time.monotonic() - monitor.ALERT_COOLDOWN - 1
        )
        assert monitor._should_notify_recovery("svc") is True


class TestAlertCooldownConstants:
    """Verify alert cooldown constants."""

    def test_cooldown_is_positive(self):
        assert monitor.ALERT_COOLDOWN > 0

    def test_cooldown_is_reasonable(self):
        """Cooldown should be between 60s and 3600s."""
        assert 60 <= monitor.ALERT_COOLDOWN <= 3600


class TestComputeModelOverall:
    """Tests for _compute_model_overall."""

    def test_all_healthy(self):
        results = [
            {"status": "healthy"},
            {"status": "healthy"},
        ]
        assert monitor._compute_model_overall(results) == "healthy"

    def test_some_healthy(self):
        results = [
            {"status": "healthy"},
            {"status": "degraded"},
        ]
        assert monitor._compute_model_overall(results) == "degraded"

    def test_no_healthy_some_timeout(self):
        results = [
            {"status": "timeout"},
            {"status": "unreachable"},
        ]
        assert monitor._compute_model_overall(results) == "timeout"

    def test_no_healthy_some_no_credits(self):
        results = [
            {"status": "no_credits"},
            {"status": "unreachable"},
        ]
        assert monitor._compute_model_overall(results) == "no_credits"

    def test_all_down(self):
        results = [
            {"status": "unreachable"},
            {"status": "degraded"},
        ]
        assert monitor._compute_model_overall(results) == "all_down"

    def test_empty_list(self):
        """Empty list returns 'healthy' because all() on empty iterable is True.

        This is acceptable behavior — if there are no models to check,
        there's nothing wrong. The model list is always populated in production.
        """
        assert monitor._compute_model_overall([]) == "healthy"

    def test_no_credits_takes_priority_over_timeout(self):
        """no_credits should take priority over timeout when no healthy."""
        results = [
            {"status": "timeout"},
            {"status": "no_credits"},
        ]
        assert monitor._compute_model_overall(results) == "no_credits"


class TestModelList:
    """Tests for model list configuration."""

    def test_model_list_not_empty(self):
        assert len(monitor._MODEL_LIST) > 0

    def test_model_list_has_expected_count(self):
        """Should have 6 models in the fallback chain."""
        assert len(monitor._MODEL_LIST) == 6

    def test_models_are_strings(self):
        for model in monitor._MODEL_LIST:
            assert isinstance(model, str)
            assert len(model) > 0

    def test_no_duplicate_models(self):
        assert len(set(monitor._MODEL_LIST)) == len(monitor._MODEL_LIST)

    def test_refresh_interval_is_positive(self):
        assert monitor.MODEL_HEALTH_REFRESH_INTERVAL > 0

    def test_refresh_interval_is_reasonable(self):
        """Refresh interval should be between 30s and 3600s."""
        assert 30 <= monitor.MODEL_HEALTH_REFRESH_INTERVAL <= 3600


class TestServiceDefinitions:
    """Tests for service configuration."""

    def test_services_not_empty(self):
        assert len(monitor.SERVICES) > 0

    def test_service_has_required_fields(self):
        for svc in monitor.SERVICES:
            assert "name" in svc
            assert "type" in svc
            assert svc["type"] in ("http", "tcp", "telegram_bot")

    def test_http_services_have_url(self):
        for svc in monitor.SERVICES:
            if svc["type"] == "http":
                assert "url" in svc

    def test_tcp_services_have_host_port(self):
        for svc in monitor.SERVICES:
            if svc["type"] == "tcp":
                assert "host" in svc
                assert "port" in svc

    def test_public_endpoints_defined(self):
        assert len(monitor.PUBLIC_ENDPOINTS) > 0

    def test_integrations_defined(self):
        assert len(monitor.INTEGRATIONS) > 0
