"""Tests for health history persistence, uptime stats, and latency stats."""

import json
import os
import tempfile
import datetime
from unittest.mock import patch

import pytest
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitor


@pytest.fixture
def temp_history_file(tmp_path):
    """Use a temporary file for history during tests."""
    old_path = monitor.HISTORY_FILE
    monitor.HISTORY_FILE = str(tmp_path / "test_history.json")
    yield monitor.HISTORY_FILE
    monitor.HISTORY_FILE = old_path


@pytest.fixture
def sample_history():
    """Return a sample history dict with multiple services."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "Config Service": [
            {
                "timestamp": (now - datetime.timedelta(minutes=i * 5)).isoformat(),
                "status": "healthy" if i % 5 != 0 else "down",
                "latency_ms": 100 + i * 10,
            }
            for i in range(20)
        ],
        "SRE Agent": [
            {
                "timestamp": (now - datetime.timedelta(minutes=i * 5)).isoformat(),
                "status": "healthy",
                "latency_ms": 200 + i * 5,
            }
            for i in range(10)
        ],
        "Down Service": [
            {
                "timestamp": (now - datetime.timedelta(minutes=i)).isoformat(),
                "status": "down",
                "error": "Connection refused",
            }
            for i in range(5)
        ],
    }


class TestLoadHistory:
    """Tests for _load_history."""

    def test_load_nonexistent_file(self, temp_history_file):
        """Should return empty dict when file doesn't exist."""
        result = monitor._load_history()
        assert result == {}

    def test_load_valid_file(self, temp_history_file):
        """Should load valid JSON history."""
        data = {"service1": [{"timestamp": "2024-01-01T00:00:00+00:00", "status": "healthy"}]}
        with open(temp_history_file, "w") as f:
            json.dump(data, f)

        result = monitor._load_history()
        assert result == data

    def test_load_corrupt_file(self, temp_history_file):
        """Should return empty dict for corrupt JSON."""
        with open(temp_history_file, "w") as f:
            f.write("not valid json{{{")
        # Suppress the warning log
        import logging
        logging.disable(logging.WARNING)
        result = monitor._load_history()
        logging.disable(logging.NOTSET)
        assert result == {}


class TestSaveHistory:
    """Tests for _save_history."""

    def test_save_creates_file(self, temp_history_file):
        """Should create the history file."""
        history = {"svc": [{"timestamp": "2024-01-01T00:00:00+00:00", "status": "healthy"}]}
        monitor._save_history(history)
        assert os.path.exists(temp_history_file)

    def test_save_trims_old_entries(self, temp_history_file):
        """Should trim entries exceeding HISTORY_MAX_ENTRIES."""
        old_max = monitor.HISTORY_MAX_ENTRIES
        monitor.HISTORY_MAX_ENTRIES = 5
        try:
            entries = [
                {"timestamp": f"2024-01-01T00:{i:02d}:00+00:00", "status": "healthy"}
                for i in range(20)
            ]
            monitor._save_history({"svc": entries})

            loaded = monitor._load_history()
            assert len(loaded["svc"]) == 5
            # Should keep the most recent entries
            assert loaded["svc"][-1]["timestamp"] == "2024-01-01T00:19:00+00:00"
        finally:
            monitor.HISTORY_MAX_ENTRIES = old_max

    def test_save_preserves_all_services(self, temp_history_file):
        """Should preserve all services in the history."""
        history = {
            "svc-a": [{"timestamp": "2024-01-01T00:00:00+00:00", "status": "healthy"}],
            "svc-b": [{"timestamp": "2024-01-01T00:00:00+00:00", "status": "down"}],
        }
        monitor._save_history(history)
        loaded = monitor._load_history()
        assert "svc-a" in loaded
        assert "svc-b" in loaded


class TestRecordHistory:
    """Tests for _record_history."""

    def test_record_new_service(self, temp_history_file):
        """Should create a new entry for a new service."""
        results = [
            {
                "name": "New Service",
                "timestamp": "2024-01-01T00:00:00+00:00",
                "status": "healthy",
                "latency_ms": 50,
            }
        ]
        monitor._record_history(results)
        history = monitor._load_history()
        assert "New Service" in history
        assert len(history["New Service"]) == 1
        assert history["New Service"][0]["latency_ms"] == 50

    def test_record_appends(self, temp_history_file):
        """Should append to existing entries."""
        results = [
            {
                "name": "Service",
                "timestamp": f"2024-01-01T00:{i:02d}:00+00:00",
                "status": "healthy",
            }
            for i in range(3)
        ]
        monitor._record_history(results)
        history = monitor._load_history()
        assert len(history["Service"]) == 3

    def test_record_includes_error(self, temp_history_file):
        """Should include error field when present."""
        results = [
            {
                "name": "Failing Service",
                "timestamp": "2024-01-01T00:00:00+00:00",
                "status": "down",
                "error": "Connection refused",
            }
        ]
        monitor._record_history(results)
        history = monitor._load_history()
        assert history["Failing Service"][0]["error"] == "Connection refused"

    def test_record_omits_none_latency(self, temp_history_file):
        """Should not include latency_ms when it's None."""
        results = [
            {
                "name": "Service",
                "timestamp": "2024-01-01T00:00:00+00:00",
                "status": "down",
            }
        ]
        monitor._record_history(results)
        history = monitor._load_history()
        assert "latency_ms" not in history["Service"][0]


class TestUptimeStats:
    """Tests for get_uptime_stats."""

    def test_all_healthy(self, sample_history):
        """Should report 100% uptime for all-healthy service."""
        stats = monitor.get_uptime_stats(sample_history, "SRE Agent", window_hours=24)
        assert stats["uptime_pct"] == 100.0
        assert stats["total_checks"] == 10
        assert stats["healthy_count"] == 10

    def test_partial_uptime(self, sample_history):
        """Should calculate correct uptime percentage."""
        stats = monitor.get_uptime_stats(sample_history, "Config Service", window_hours=24)
        # 20 entries, every 5th is down (indices 0, 5, 10, 15) = 4 down, 16 healthy
        # Wait: i % 5 == 0 means i=0,5,10,15 are "down" = 4 down, 16 healthy
        assert stats["healthy_count"] == 16
        assert stats["total_checks"] == 20
        assert stats["uptime_pct"] == 80.0

    def test_no_history(self):
        """Should return None uptime for unknown service."""
        stats = monitor.get_uptime_stats({}, "nonexistent", window_hours=24)
        assert stats["uptime_pct"] is None
        assert stats["total_checks"] == 0

    def test_all_down(self, sample_history):
        """Should report 0% uptime for all-down service."""
        stats = monitor.get_uptime_stats(sample_history, "Down Service", window_hours=24)
        assert stats["uptime_pct"] == 0.0

    def test_window_filtering(self, sample_history):
        """Should only include entries within the time window."""
        stats = monitor.get_uptime_stats(sample_history, "Config Service", window_hours=0)
        # 0-hour window should include nothing (or almost nothing)
        assert stats["total_checks"] == 0


class TestLatencyStats:
    """Tests for get_latency_stats."""

    def test_basic_stats(self, sample_history):
        """Should calculate avg, min, max correctly."""
        stats = monitor.get_latency_stats(sample_history, "SRE Agent", window_hours=24)
        assert stats["count"] == 10
        assert stats["min_ms"] == 200
        assert stats["max_ms"] == 245  # 200 + 9*5
        assert stats["avg_ms"] > 0

    def test_percentiles(self, sample_history):
        """Should calculate percentile values."""
        stats = monitor.get_latency_stats(sample_history, "SRE Agent", window_hours=24)
        assert stats["p50_ms"] > 0
        assert stats["p95_ms"] > 0
        assert stats["p99_ms"] > 0
        assert stats["p50_ms"] <= stats["p95_ms"] <= stats["p99_ms"]

    def test_excludes_failed_checks(self, sample_history):
        """Should only include healthy entries with latency."""
        stats = monitor.get_latency_stats(sample_history, "Down Service", window_hours=24)
        assert stats == {}  # No healthy entries

    def test_no_history(self):
        """Should return empty dict for unknown service."""
        stats = monitor.get_latency_stats({}, "nonexistent", window_hours=24)
        assert stats == {}

    def test_excludes_degraded(self, temp_history_file):
        """Should exclude degraded entries from latency stats."""
        now = datetime.datetime.now(datetime.timezone.utc)
        history = {
            "Service": [
                {
                    "timestamp": now.isoformat(),
                    "status": "degraded",
                    "latency_ms": 5000,
                },
                {
                    "timestamp": (now - datetime.timedelta(minutes=1)).isoformat(),
                    "status": "healthy",
                    "latency_ms": 100,
                },
            ]
        }
        stats = monitor.get_latency_stats(history, "Service", window_hours=24)
        assert stats["count"] == 1
        assert stats["avg_ms"] == 100.0


class TestPercentile:
    """Tests for _percentile helper."""

    def test_single_value(self):
        assert monitor._percentile([42.0], 50) == 42.0
        assert monitor._percentile([42.0], 99) == 42.0

    def test_median_of_two(self):
        result = monitor._percentile([10.0, 20.0], 50)
        assert result == 15.0

    def test_p50(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert monitor._percentile(vals, 50) == 3.0

    def test_empty_list(self):
        assert monitor._percentile([], 50) == 0.0

    def test_p99_uses_interpolation(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = monitor._percentile(vals, 99)
        assert result > 4.0
        assert result <= 5.0
