"""Tests for the circuit breaker mechanism in health-monitor.

The circuit breaker prevents repeated checks of flaky external endpoints
by opening after N consecutive failures and staying open for a cooldown period.
"""

import asyncio
import time
from unittest.mock import patch

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitor


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    """Reset circuit breaker state before each test."""
    monitor._circuit_breaker_counts.clear()
    monitor._circuit_breaker_opened.clear()
    yield
    monitor._circuit_breaker_counts.clear()
    monitor._circuit_breaker_opened.clear()


class TestCircuitBreakerOpen:
    """Tests for _is_circuit_open."""

    def test_not_open_initially(self):
        """Circuit breaker should not be open for a fresh service."""
        assert monitor._is_circuit_open("test-service") is False

    def test_opens_after_threshold_failures(self):
        """Circuit should open after CIRCUIT_BREAKER_THRESHOLD consecutive failures."""
        name = "flaky-service"
        for _ in range(monitor.CIRCUIT_BREAKER_THRESHOLD):
            monitor._record_failure(name)
        assert monitor._is_circuit_open(name) is True

    def test_does_not_open_below_threshold(self):
        """Circuit should stay closed below the threshold."""
        name = "mostly-ok-service"
        for _ in range(monitor.CIRCUIT_BREAKER_THRESHOLD - 1):
            monitor._record_failure(name)
        assert monitor._is_circuit_open(name) is False

    def test_closes_after_cooldown(self):
        """Circuit should close after the cooldown period expires."""
        name = "recovering-service"
        for _ in range(monitor.CIRCUIT_BREAKER_THRESHOLD):
            monitor._record_failure(name)
        assert monitor._is_circuit_open(name) is True

        # Simulate cooldown expiry
        monitor._circuit_breaker_opened[name] = (
            time.monotonic() - monitor.CIRCUIT_BREAKER_COOLDOWN - 1
        )
        assert monitor._is_circuit_open(name) is False

    def test_counts_reset_after_cooldown(self):
        """Failure counts should be cleaned up after cooldown expires."""
        name = "service"
        for _ in range(monitor.CIRCUIT_BREAKER_THRESHOLD):
            monitor._record_failure(name)

        # Expire cooldown
        monitor._circuit_breaker_opened[name] = (
            time.monotonic() - monitor.CIRCUIT_BREAKER_COOLDOWN - 1
        )
        monitor._is_circuit_open(name)

        assert name not in monitor._circuit_breaker_counts
        assert name not in monitor._circuit_breaker_opened


class TestCircuitBreakerRecordSuccess:
    """Tests for _record_success."""

    def test_resets_failure_count(self):
        """Success should reset the failure count."""
        name = "service"
        monitor._record_failure(name)
        monitor._record_failure(name)
        monitor._record_success(name)
        assert name not in monitor._circuit_breaker_counts

    def test_resets_circuit_breaker(self):
        """Success should clear an open circuit breaker."""
        name = "service"
        for _ in range(monitor.CIRCUIT_BREAKER_THRESHOLD):
            monitor._record_failure(name)
        assert monitor._is_circuit_open(name) is True

        monitor._record_success(name)
        assert monitor._is_circuit_open(name) is False

    def test_no_error_on_unknown_service(self):
        """Recording success for unknown service should not error."""
        monitor._record_success("nonexistent-service")  # Should not raise


class TestCircuitBreakerRecordFailure:
    """Tests for _record_failure."""

    def test_increments_count(self):
        """Each call should increment the failure count."""
        name = "service"
        monitor._record_failure(name)
        assert monitor._circuit_breaker_counts[name] == 1
        monitor._record_failure(name)
        assert monitor._circuit_breaker_counts[name] == 2

    def test_opens_at_threshold(self):
        """Circuit should open exactly at the threshold."""
        name = "service"
        for _ in range(monitor.CIRCUIT_BREAKER_THRESHOLD - 1):
            monitor._record_failure(name)
        assert name not in monitor._circuit_breaker_opened

        monitor._record_failure(name)
        assert name in monitor._circuit_breaker_opened

    def test_independent_per_service(self):
        """Circuit breaker state should be independent per service."""
        monitor._record_failure("svc-a")
        monitor._record_failure("svc-a")
        monitor._record_failure("svc-b")

        assert monitor._circuit_breaker_counts["svc-a"] == 2
        assert monitor._circuit_breaker_counts["svc-b"] == 1


class TestCircuitBreakerConstants:
    """Verify circuit breaker constants are sane."""

    def test_threshold_is_positive(self):
        assert monitor.CIRCUIT_BREAKER_THRESHOLD > 0

    def test_cooldown_is_positive(self):
        assert monitor.CIRCUIT_BREAKER_COOLDOWN > 0

    def test_threshold_is_reasonable(self):
        """Threshold should be between 2 and 10."""
        assert 2 <= monitor.CIRCUIT_BREAKER_THRESHOLD <= 10

    def test_cooldown_is_reasonable(self):
        """Cooldown should be between 60s and 3600s."""
        assert 60 <= monitor.CIRCUIT_BREAKER_COOLDOWN <= 3600
