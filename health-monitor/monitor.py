#!/usr/bin/env python3
"""
SolidAI SRE Health Monitor

Periodically checks all core services and sends Telegram alerts when
services go down or recover. Designed to run as a sidecar container
in the Docker Compose stack.

Environment variables (from .env or docker-compose):
    TELEGRAM_BOT_TOKEN   - Bot token for sending alerts
    TELEGRAM_CHAT_ID     - Chat ID to send alerts to
    CHECK_INTERVAL       - Seconds between health checks (default: 60)
    ALERT_COOLDOWN       - Seconds before re-alerting on same service (default: 300)
    HISTORY_FILE         - Path to health history JSON file (default: /tmp/health_history.json)
    HISTORY_MAX_ENTRIES  - Max history entries per service (default: 288 = 24h at 5min intervals)
    LATENCY_THRESHOLD_MS - p95 latency threshold in ms for degradation alerts (default: 5000)
    ERROR_RATE_THRESHOLD - Error rate (0.0-1.0) that triggers a warning alert (default: 0.3)
    ERROR_RATE_WINDOW    - Hours for error rate rolling window (default: 1)
"""

import asyncio
import datetime
import json
import logging
import os
import socket
import sys
import time
from typing import Optional

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("health-monitor")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))
ALERT_COOLDOWN = int(os.getenv("ALERT_COOLDOWN", "300"))
HISTORY_FILE = os.getenv("HISTORY_FILE", "/tmp/health_history.json")
HISTORY_MAX_ENTRIES = int(os.getenv("HISTORY_MAX_ENTRIES", "288"))

# Latency degradation threshold (ms) — p95 above this triggers a degradation alert
LATENCY_THRESHOLD_MS = int(os.getenv("LATENCY_THRESHOLD_MS", "5000"))
# Error rate threshold (0.0–1.0) — rolling window error rate above this triggers alert
ERROR_RATE_THRESHOLD = float(os.getenv("ERROR_RATE_THRESHOLD", "0.3"))
# Rolling window for error rate calculation (hours)
ERROR_RATE_WINDOW = int(os.getenv("ERROR_RATE_WINDOW", "1"))

# Service definitions: name -> check function config
# Uses Docker Compose service names for internal checks
SERVICES = [
    {
        "name": "Config Service",
        "type": "http",
        "url": "http://config-service:8080/health",
        "timeout": 5.0,
    },
    {
        "name": "LiteLLM Proxy",
        "type": "http",
        "url": "http://litellm:4000/health/readiness",
        "timeout": 5.0,
    },
    {
        "name": "SRE Agent",
        "type": "http",
        "url": "http://sre-agent:8000/health",
        "timeout": 10.0,
    },
    {
        "name": "Web UI",
        "type": "http",
        "url": "http://web-ui:3000/api/health",
        "timeout": 5.0,
    },
    {
        "name": "PostgreSQL",
        "type": "tcp",
        "host": "postgres",
        "port": 5432,
        "timeout": 3.0,
    },
    {
        "name": "Neo4j",
        "type": "tcp",
        "host": "neo4j",
        "port": 7474,
        "timeout": 3.0,
    },
]

# Public endpoints to check (external-facing)
PUBLIC_ENDPOINTS = [
    {
        "name": "Solid Solutions",
        "type": "http",
        "url": "https://solidsolutions.africa",
        "timeout": 10.0,
    },
    {
        "name": "SolidAI",
        "type": "http",
        "url": "https://solidai.africa",
        "timeout": 10.0,
    },
]

# Integration health checks
INTEGRATIONS = [
    {
        "name": "Telegram Bot",
        "type": "telegram_bot",
        "timeout": 10.0,
    },
]

# ---------------------------------------------------------------------------
# State tracking
# ---------------------------------------------------------------------------

# service_name -> last known status ("healthy", "degraded", "down")
_last_status: dict[str, str] = {}
# service_name -> timestamp of last alert sent
_last_alert_time: dict[str, float] = {}
# service_name -> timestamp of last recovery notification
_last_recovery_time: dict[str, float] = {}


def _check_tcp(host: str, port: int, timeout: float) -> dict:
    """Check TCP connectivity."""
    try:
        start = time.monotonic()
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        latency_ms = int((time.monotonic() - start) * 1000)
        return {"status": "healthy", "latency_ms": latency_ms}
    except Exception as e:
        return {"status": "down", "error": str(e)[:200]}


async def _check_http(url: str, timeout: float) -> dict:
    """Check HTTP endpoint."""
    try:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            resp = await client.get(url)
        latency_ms = int((time.monotonic() - start) * 1000)
        if 200 <= resp.status_code < 300:
            return {"status": "healthy", "latency_ms": latency_ms}
        return {
            "status": "degraded",
            "http_status": resp.status_code,
            "latency_ms": latency_ms,
        }
    except Exception as e:
        return {"status": "down", "error": str(e)[:200]}


async def _check_telegram_bot(timeout: float) -> dict:
    """Check Telegram bot connectivity by calling getMe API."""
    if not TELEGRAM_BOT_TOKEN:
        return {"status": "not_configured", "error": "TELEGRAM_BOT_TOKEN not set"}

    try:
        start = time.monotonic()
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe"
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            resp = await client.get(url)
        latency_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                bot_info = data.get("result", {})
                bot_name = bot_info.get("username", "unknown")
                return {
                    "status": "healthy",
                    "latency_ms": latency_ms,
                    "details": f"Bot @{bot_name}",
                }
            return {
                "status": "degraded",
                "latency_ms": latency_ms,
                "error": "Telegram API returned ok=false",
            }
        return {
            "status": "degraded",
            "http_status": resp.status_code,
            "latency_ms": latency_ms,
            "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
        }
    except Exception as e:
        return {"status": "down", "error": str(e)[:200]}


async def check_service(service: dict) -> dict:
    """Run a single service health check."""
    name = service["name"]
    try:
        if service["type"] == "http":
            result = await _check_http(service["url"], service["timeout"])
        elif service["type"] == "tcp":
            result = _check_tcp(service["host"], service["port"], service["timeout"])
        elif service["type"] == "telegram_bot":
            result = await _check_telegram_bot(service["timeout"])
        else:
            result = {"status": "unknown", "error": f"Unknown check type: {service['type']}"}
    except Exception as e:
        result = {"status": "down", "error": str(e)[:200]}

    result["name"] = name
    result["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return result


async def check_all_services() -> list[dict]:
    """Check all services concurrently."""
    tasks = [check_service(s) for s in SERVICES]
    return await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# Circuit breaker for flaky external endpoints
# ---------------------------------------------------------------------------

# service_name -> consecutive failure count
_circuit_breaker_counts: dict[str, int] = {}
# service_name -> timestamp when circuit was opened
_circuit_breaker_opened: dict[str, float] = {}
# After N consecutive failures, skip checks for COOLDOWN seconds
CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_COOLDOWN = 300  # 5 minutes


def _is_circuit_open(service_name: str) -> bool:
    """Check if the circuit breaker is open for a service (skipping checks)."""
    if service_name not in _circuit_breaker_opened:
        return False
    opened_at = _circuit_breaker_opened[service_name]
    if time.monotonic() - opened_at > CIRCUIT_BREAKER_COOLDOWN:
        # Cooldown expired, reset circuit
        del _circuit_breaker_opened[service_name]
        _circuit_breaker_counts.pop(service_name, None)
        return False
    return True


def _record_success(service_name: str):
    """Reset circuit breaker on success."""
    _circuit_breaker_counts.pop(service_name, None)
    _circuit_breaker_opened.pop(service_name, None)


def _record_failure(service_name: str):
    """Increment circuit breaker failure count, open if threshold reached."""
    count = _circuit_breaker_counts.get(service_name, 0) + 1
    _circuit_breaker_counts[service_name] = count
    if count >= CIRCUIT_BREAKER_THRESHOLD:
        _circuit_breaker_opened[service_name] = time.monotonic()
        logger.info(
            f"[CIRCUIT] Opened breaker for {service_name} "
            f"after {count} consecutive failures "
            f"(cooldown: {CIRCUIT_BREAKER_COOLDOWN}s)"
        )


async def check_public_endpoints() -> list[dict]:
    """Check public-facing endpoints with circuit breaker support."""
    results = []
    for svc in PUBLIC_ENDPOINTS:
        name = svc["name"]
        if _is_circuit_open(name):
            results.append({
                "name": name,
                "status": "skipped",
                "error": "Circuit breaker open (endpoint consistently failing)",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
            continue
        result = await check_service(svc)
        if result["status"] == "healthy":
            _record_success(name)
        else:
            _record_failure(name)
        results.append(result)
    return results


async def check_integrations() -> list[dict]:
    """Check integration connectivity."""
    tasks = [check_service(s) for s in INTEGRATIONS]
    return await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# Health history (persisted to JSON file)
# ---------------------------------------------------------------------------

def _load_history() -> dict:
    """Load health history from disk."""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load health history: {e}")
    return {}


def _save_history(history: dict):
    """Save health history to disk, trimming old entries."""
    try:
        # Trim entries per service to max allowed count
        for name in history:
            if len(history[name]) > HISTORY_MAX_ENTRIES:
                history[name] = history[name][-HISTORY_MAX_ENTRIES:]

        # Age-based cleanup: remove entries older than HISTORY_MAX_AGE_HOURS
        # Default: 48 hours (2 days) — prevents unbounded file growth
        max_age_hours = int(os.getenv("HISTORY_MAX_AGE_HOURS", "48"))
        cutoff = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=max_age_hours)
        ).isoformat()
        for name in history:
            history[name] = [
                e for e in history[name]
                if e.get("timestamp", "") >= cutoff
            ]
        # Remove services with no remaining entries
        history = {k: v for k, v in history.items() if v}

        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save health history: {e}")


def _record_history(results: list[dict]):
    """Record health check results to history file."""
    history = _load_history()
    for result in results:
        name = result["name"]
        if name not in history:
            history[name] = []
        entry = {
            "timestamp": result["timestamp"],
            "status": result["status"],
        }
        if result.get("latency_ms") is not None:
            entry["latency_ms"] = result["latency_ms"]
        if result.get("error"):
            entry["error"] = result["error"]
        history[name].append(entry)
    _save_history(history)


def get_uptime_stats(history: dict, service_name: str, window_hours: int = 24) -> dict:
    """Calculate uptime percentage for a service over a time window."""
    entries = history.get(service_name, [])
    if not entries:
        return {"uptime_pct": None, "total_checks": 0, "healthy_count": 0}

    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=window_hours)
    ).isoformat()

    recent = [e for e in entries if e["timestamp"] >= cutoff]
    if not recent:
        return {"uptime_pct": None, "total_checks": 0, "healthy_count": 0}

    healthy = sum(1 for e in recent if e["status"] == "healthy")
    total = len(recent)
    uptime_pct = round(healthy / total * 100, 1) if total > 0 else None

    return {
        "uptime_pct": uptime_pct,
        "total_checks": total,
        "healthy_count": healthy,
        "window_hours": window_hours,
    }

def get_incidents(history: dict, window_hours: int = 24) -> list:
    """
    Detect incidents (periods of down/degraded status) from service history.
    Returns a list of incident objects sorted by start time descending.
    Each incident: {
        service_name: str,
        status: str,  # worst status during incident ('down' or 'degraded')
        start_time: str,  # ISO timestamp
        end_time: str | None,  # ISO timestamp or None if ongoing
        duration_seconds: float | None,  # None if ongoing
    }
    """
    incidents = []
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=window_hours)
    ).isoformat()

    for name, entries in history.items():
        if not entries:
            continue
        # Ensure entries are sorted by timestamp ascending
        sorted_entries = sorted(entries, key=lambda e: e["timestamp"])
        # Filter entries within window
        windowed = [e for e in sorted_entries if e["timestamp"] >= cutoff]
        if not windowed:
            continue

        incident_start = None
        incident_statuses = []  # collect statuses during incident to determine worst

        for entry in windowed:
            status = entry["status"]
            is_non_healthy = status in ("down", "degraded")
            ts = entry["timestamp"]

            if is_non_healthy and incident_start is None:
                # Start new incident
                incident_start = ts
                incident_statuses = [status]
            elif not is_non_healthy and incident_start is not None:
                # End incident
                incident_end = ts
                # Determine worst status: down > degraded
                worst_status = "down" if "down" in incident_statuses else "degraded"
                duration = (
                    datetime.datetime.fromisoformat(incident_end)
                    - datetime.datetime.fromisoformat(incident_start)
                ).total_seconds()
                incidents.append(
                    {
                        "service_name": name,
                        "status": worst_status,
                        "start_time": incident_start,
                        "end_time": incident_end,
                        "duration_seconds": duration,
                    }
                )
                incident_start = None
                incident_statuses = []
            elif is_non_healthy and incident_start is not None:
                # Continue incident
                incident_statuses.append(status)

        # If incident still open at end of windowed entries
        if incident_start is not None:
            # Incident ongoing at the end of the window
            incident_end = None  # ongoing
            worst_status = "down" if "down" in incident_statuses else "degraded"
            incidents.append(
                {
                    "service_name": name,
                    "status": worst_status,
                    "start_time": incident_start,
                    "end_time": None,
                    "duration_seconds": None,
                }
            )

    # Sort by start_time descending (most recent first)
    incidents.sort(
        key=lambda i: i["start_time"],
        reverse=True,
    )
    return incidents

def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Compute the given percentile from a sorted list using linear interpolation."""
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_vals):
        return sorted_vals[-1]
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return round(d0 + d1, 1)


def get_latency_stats(history: dict, service_name: str, window_hours: int = 24) -> dict:
    """Calculate latency statistics for a service over a time window.

    Returns avg, min, max, p50, p95, p99 for entries that have latency_ms.
    Only includes healthy-status entries (failed checks don't have meaningful latency).
    """
    entries = history.get(service_name, [])
    if not entries:
        return {}

    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=window_hours)
    ).isoformat()

    latencies = [
        e["latency_ms"]
        for e in entries
        if e["timestamp"] >= cutoff
        and e.get("status") == "healthy"
        and e.get("latency_ms") is not None
    ]

    if not latencies:
        return {}

    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)

    return {
        "count": n,
        "avg_ms": round(sum(latencies_sorted) / n, 1),
        "min_ms": latencies_sorted[0],
        "max_ms": latencies_sorted[-1],
        "p50_ms": _percentile(latencies_sorted, 50),
        "p95_ms": _percentile(latencies_sorted, 95),
        "p99_ms": _percentile(latencies_sorted, 99),
        "window_hours": window_hours,
    }


# ---------------------------------------------------------------------------
# Error rate tracking
# ---------------------------------------------------------------------------

def get_error_rate(history: dict, service_name: str, window_hours: int = None) -> dict:
    """Calculate error rate for a service over a rolling time window.

    Error rate = (number of non-healthy entries) / (total entries).

    Returns:
        dict with error_rate (0.0-1.0), total_checks, failed_count, window_hours.
        Returns None values if no data is available.
    """
    if window_hours is None:
        window_hours = ERROR_RATE_WINDOW

    entries = history.get(service_name, [])
    if not entries:
        return {"error_rate": None, "total_checks": 0, "failed_count": 0, "window_hours": window_hours}

    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=window_hours)
    ).isoformat()

    recent = [e for e in entries if e["timestamp"] >= cutoff]
    if not recent:
        return {"error_rate": None, "total_checks": 0, "failed_count": 0, "window_hours": window_hours}

    failed = sum(1 for e in recent if e["status"] in ("down", "degraded", "timeout", "unreachable"))
    total = len(recent)
    error_rate = round(failed / total, 3) if total > 0 else None

    return {
        "error_rate": error_rate,
        "total_checks": total,
        "failed_count": failed,
        "window_hours": window_hours,
    }


def check_latency_degradation(history: dict, service_name: str, threshold_ms: int = None) -> dict:
    """Check if a service's p95 latency exceeds the degradation threshold.

    Returns:
        dict with degraded (bool), p95_ms, threshold_ms, and details.
    """
    if threshold_ms is None:
        threshold_ms = LATENCY_THRESHOLD_MS

    latency = get_latency_stats(history, service_name, window_hours=ERROR_RATE_WINDOW)
    if not latency:
        return {"degraded": False, "p95_ms": None, "threshold_ms": threshold_ms, "reason": "no data"}

    p95 = latency.get("p95_ms")
    if p95 is None:
        return {"degraded": False, "p95_ms": None, "threshold_ms": threshold_ms, "reason": "no latency data"}
    degraded = p95 > threshold_ms

    return {
        "degraded": degraded,
        "p95_ms": p95,
        "threshold_ms": threshold_ms,
        "avg_ms": latency.get("avg_ms"),
        "reason": f"p95 latency {p95}ms exceeds threshold {threshold_ms}ms" if degraded else "ok",
    }


def predict_latency_trend(history: dict, service_name: str, threshold_ms: int = None, window_hours: int = 2) -> dict:
    """Predict when a service's avg latency will cross the degradation threshold.

    Uses simple linear regression on recent latency data points to forecast
    the time (in minutes) until latency exceeds the configured threshold.
    This enables proactive alerting before degradation actually occurs.

    Args:
        history: Health history dict (from _load_history).
        service_name: Name of the service to analyze.
        threshold_ms: Latency threshold (defaults to LATENCY_THRESHOLD_MS).
        window_hours: Hours of recent data to use for trend analysis.

    Returns:
        dict with trend data: slope, current_avg, threshold, minutes_to_threshold,
        prediction_confidence, trend_direction.
    """
    if threshold_ms is None:
        threshold_ms = LATENCY_THRESHOLD_MS

    entries = history.get(service_name, [])
    if not entries:
        return {"trend_direction": "unknown", "minutes_to_threshold": None, "prediction_confidence": 0.0}

    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(hours=window_hours)
    ).isoformat()

    # Get recent healthy entries with latency data
    recent = [
        e for e in entries
        if e["timestamp"] >= cutoff
        and e.get("status") == "healthy"
        and e.get("latency_ms") is not None
    ]

    if len(recent) < 3:
        return {
            "trend_direction": "stable",
            "current_avg": get_latency_stats(history, service_name, window_hours).get("avg_ms"),
            "threshold_ms": threshold_ms,
            "minutes_to_threshold": None,
            "prediction_confidence": 0.0,
            "reason": "insufficient data for trend prediction",
        }

    # Simple linear regression: y = mx + b
    # x = minutes from first data point, y = latency_ms
    first_ts = datetime.datetime.fromisoformat(recent[0]["timestamp"])
    x_vals = []
    y_vals = []

    for entry in recent:
        ts = datetime.datetime.fromisoformat(entry["timestamp"])
        delta_minutes = (ts - first_ts).total_seconds() / 60.0
        x_vals.append(delta_minutes)
        y_vals.append(entry["latency_ms"])

    n = len(x_vals)
    sum_x = sum(x_vals)
    sum_y = sum(y_vals)
    sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))
    sum_x2 = sum(x * x for x in x_vals)

    denominator = n * sum_x2 - sum_x * sum_x
    if denominator == 0:
        slope = 0.0
    else:
        slope = (n * sum_xy - sum_x * sum_y) / denominator

    intercept = (sum_y - slope * sum_x) / n

    current_avg = round(sum_y / n, 1)

    # Determine trend direction
    # Use slope relative to average latency to detect meaningful trends.
    # A trend is significant if the slope would change avg latency by >2% per data point interval.
    avg_latency = sum_y / n
    if avg_latency > 0:
        slope_pct_per_interval = slope / avg_latency
    else:
        slope_pct_per_interval = 0.0

    # Also check absolute slope for low-latency services (where % is misleading)
    # 2ms per minute is significant regardless of baseline
    if slope_pct_per_interval > 0.02 or slope >= 2.0:
        trend_direction = "increasing"
    elif slope_pct_per_interval < -0.02 or slope <= -2.0:
        trend_direction = "decreasing"
    else:
        trend_direction = "stable"

    # Calculate confidence based on R² (coefficient of determination)
    y_mean = sum_y / n
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_vals, y_vals))
    ss_tot = sum((y - y_mean) ** 2 for y in y_vals)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    confidence = round(max(0.0, min(1.0, r_squared)), 2)

    # Predict minutes to threshold
    minutes_to_threshold = None
    if slope > 0 and confidence >= 0.5 and trend_direction == "increasing":
        # y = mx + b → solve for x when y = threshold
        minutes_at_threshold = (threshold_ms - intercept) / slope if slope != 0 else None
        if minutes_at_threshold is not None:
            elapsed_minutes = x_vals[-1] if x_vals else 0
            remaining = minutes_at_threshold - elapsed_minutes
            if remaining > 0:
                minutes_to_threshold = round(remaining, 1)
            else:
                minutes_to_threshold = 0  # Already at/past threshold

    # Reason string
    if minutes_to_threshold is not None and minutes_to_threshold > 0:
        reason = (
            f"Latency trending UP at {slope:.2f}min/min — "
            f"will cross {threshold_ms}ms threshold in ~{minutes_to_threshold:.0f}min "
            f"(confidence: {confidence:.0%})"
        )
    elif trend_direction == "increasing":
        reason = f"Increasing trend ({slope:.2f}min/min) but below threshold prediction line"
    elif trend_direction == "decreasing":
        reason = f"Improving ({slope:.2f}min/min)"
    else:
        reason = "Stable"

    return {
        "trend_direction": trend_direction,
        "slope_per_minute": round(slope, 4),
        "current_avg_ms": current_avg,
        "threshold_ms": threshold_ms,
        "minutes_to_threshold": minutes_to_threshold,
        "prediction_confidence": confidence,
        "data_points": n,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Telegram alerting
# ---------------------------------------------------------------------------

async def send_telegram(message: str) -> bool:
    """Send a message via Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured, skipping alert")
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("Telegram alert sent successfully")
                return True
            else:
                logger.error(f"Telegram API error: {resp.status_code} {resp.text[:200]}")
                return False
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")
        return False


def _should_alert(service_name: str, status: str) -> bool:
    """Determine if we should send an alert (respect cooldown)."""
    now = time.monotonic()
    last_alert = _last_alert_time.get(service_name, 0)
    if now - last_alert < ALERT_COOLDOWN:
        return False
    return True


def _should_notify_recovery(service_name: str) -> bool:
    """Determine if we should send a recovery notification."""
    now = time.monotonic()
    last_recovery = _last_recovery_time.get(service_name, 0)
    if now - last_recovery < ALERT_COOLDOWN:
        return False
    return True


async def process_results(results: list[dict], is_public: bool = False):
    """Process health check results and send alerts if needed."""
    prefix = "🌐" if is_public else "🔧"

    for result in results:
        name = result["name"]
        status = result["status"]

        # Skip circuit-breaker-opened endpoints — no alerts needed
        if status == "skipped":
            _last_status[name] = "skipped"
            continue

        prev_status = _last_status.get(name, "unknown")

        # Status changed to down/degraded
        if status in ("down", "degraded") and prev_status not in ("down", "degraded"):
            if _should_alert(name, status):
                latency_info = ""
                if result.get("latency_ms"):
                    latency_info = f" (latency: {result['latency_ms']}ms)"
                error_info = ""
                if result.get("error"):
                    error_info = f"\n<pre>{result['error'][:300]}</pre>"

                emoji = "🔴" if status == "down" else "🟡"
                message = (
                    f"{emoji} <b>SolidAI SRE Alert</b>\n\n"
                    f"{prefix} <b>{name}</b> is <code>{status.upper()}</code>{latency_info}\n"
                    f"Time: {result['timestamp'][:19]} UTC"
                    f"{error_info}"
                )
                await send_telegram(message)
                _last_alert_time[name] = time.monotonic()

        # Status recovered
        elif status == "healthy" and prev_status in ("down", "degraded"):
            if _should_notify_recovery(name):
                latency_info = ""
                if result.get("latency_ms"):
                    latency_info = f" (latency: {result['latency_ms']}ms)"

                message = (
                    f"🟢 <b>SolidAI SRE Recovery</b>\n\n"
                    f"{prefix} <b>{name}</b> is back to <code>HEALTHY</code>{latency_info}\n"
                    f"Time: {result['timestamp'][:19]} UTC"
                )
                await send_telegram(message)
                _last_recovery_time[name] = time.monotonic()

        # Update last known status
        _last_status[name] = status


async def _check_error_rates_and_latency(current_results: list[dict]):
    """After recording history, check error rates and latency degradation.

    This catches gradual degradation patterns that a single-check threshold might miss:
    - Rolling error rate exceeding ERROR_RATE_THRESHOLD over the configured window
    - p95 latency exceeding LATENCY_THRESHOLD_MS over the configured window

    Alerts are subject to the same cooldown as regular status-change alerts.
    Uses _last_alert_time with a special key suffix to avoid conflicting with
    regular status-change alert cooldowns.
    """
    history = _load_history()
    now = time.monotonic()

    for result in current_results:
        name = result["name"]
        status = result["status"]

        # Skip services that are already down/degraded — those are handled by process_results
        if status in ("down", "degraded"):
            continue

        # Skip circuit-breaker-opened or not_configured
        if status in ("skipped", "not_configured"):
            continue

        # --- Error rate check ---
        error_rate_key = f"{name}:error_rate"
        last_error_alert = _last_alert_time.get(error_rate_key, 0)
        if now - last_error_alert >= ALERT_COOLDOWN:
            error_rate = get_error_rate(history, name)
            if error_rate["error_rate"] is not None and error_rate["error_rate"] >= ERROR_RATE_THRESHOLD:
                message = (
                    f"⚠️ <b>SolidAI SRE Error Rate Alert</b>\n\n"
                    f"🔧 <b>{name}</b> error rate is "
                    f"<code>{error_rate['error_rate'] * 100:.1f}%</code> "
                    f"({error_rate['failed_count']}/{error_rate['total_checks']} checks "
                    f"in last {error_rate['window_hours']}h)\n"
                    f"Time: {result['timestamp'][:19]} UTC\n"
                    f"Threshold: {ERROR_RATE_THRESHOLD * 100:.0f}%"
                )
                await send_telegram(message)
                _last_alert_time[error_rate_key] = now

        # --- Latency degradation check ---
        latency_key = f"{name}:latency"
        last_latency_alert = _last_alert_time.get(latency_key, 0)
        if now - last_latency_alert >= ALERT_COOLDOWN:
            degradation = check_latency_degradation(history, name)
            if degradation["degraded"]:
                message = (
                    f"🐌 <b>SolidAI SRE Latency Degradation</b>\n\n"
                    f"🔧 <b>{name}</b> p95 latency is "
                    f"<code>{degradation['p95_ms']}ms</code> "
                    f"(avg: {degradation.get('avg_ms', '?')}ms)\n"
                    f"Threshold: {degradation['threshold_ms']}ms\n"
                    f"Time: {result['timestamp'][:19]} UTC"
                )
                await send_telegram(message)
                _last_alert_time[latency_key] = now

        # --- Latency trend prediction (proactive alerting) ---
        trend_key = f"{name}:trend"
        last_trend_alert = _last_alert_time.get(trend_key, 0)
        if now - last_trend_alert >= ALERT_COOLDOWN:
            trend = predict_latency_trend(history, name)
            if (
                trend.get("minutes_to_threshold") is not None
                and trend["minutes_to_threshold"] > 0
                and trend["minutes_to_threshold"] <= 30
                and trend.get("prediction_confidence", 0) >= 0.6
            ):
                message = (
                    f"🔮 <b>SolidAI SRE Predictive Alert</b>\n\n"
                    f"🔧 <b>{name}</b> latency is trending UP "
                    f"(slope: {trend['slope_per_minute']}/min)\n"
                    f"Current avg: {trend['current_avg_ms']}ms\n"
                    f"Predicted to cross {trend['threshold_ms']}ms threshold "
                    f"in ~{trend['minutes_to_threshold']:.0f}min\n"
                    f"Confidence: {trend['prediction_confidence']:.0%}\n"
                    f"Time: {result['timestamp'][:19]} UTC"
                )
                await send_telegram(message)
                _last_alert_time[trend_key] = now


# Cycle counter for slow-poll integrations (e.g. Telegram bot)
# Integrations are checked every N cycles to avoid excessive API calls
_integration_check_interval = int(os.getenv("INTEGRATION_CHECK_INTERVAL", "300"))  # 5 minutes
_integration_check_counter: int = 0
_integration_last_results: list = []


async def run_health_check():
    """Run a single health check cycle."""
    global _integration_check_counter, _integration_last_results
    logger.info("Running health checks...")

    # Check internal services
    internal_results = await check_all_services()
    await process_results(internal_results, is_public=False)

    # Check public endpoints
    public_results = await check_public_endpoints()
    await process_results(public_results, is_public=True)

    # Check integrations on a slower interval (default: every 5 minutes)
    # This avoids excessive API calls to external services like Telegram
    _integration_check_counter += 1
    cycle_interval = max(1, _integration_check_interval // CHECK_INTERVAL)
    if _integration_check_counter >= cycle_interval:
        _integration_check_counter = 0
        _integration_last_results = await check_integrations()
        await process_results(_integration_last_results, is_public=False)
    else:
        logger.debug(
            f"Skipping integration checks (next in {cycle_interval - _integration_check_counter} cycles)"
        )

    # Record history for all results
    all_results = internal_results + public_results + _integration_last_results
    _record_history(all_results)

    # Check error rates and latency degradation for all services
    await _check_error_rates_and_latency(all_results)

    # Log summary
    healthy = sum(1 for r in all_results if r["status"] == "healthy")
    total = len(all_results)
    degraded = sum(1 for r in all_results if r["status"] == "degraded")
    down = sum(1 for r in all_results if r["status"] == "down")

    logger.info(
        f"Health check complete: {healthy}/{total} healthy, "
        f"{degraded} degraded, {down} down"
    )

    # Print detailed status
    for r in all_results:
        status_emoji = {"healthy": "✅", "degraded": "⚠️", "down": "❌", "not_configured": "⚪"}.get(r["status"], "❓")
        latency = f" ({r['latency_ms']}ms)" if r.get("latency_ms") is not None else ""
        details = f" [{r['details']}]" if r.get("details") else ""
        logger.info(f"  {status_emoji} {r['name']}: {r['status']}{latency}{details}")


# ---------------------------------------------------------------------------
# Health history HTTP API (lightweight, runs in same process)
# ---------------------------------------------------------------------------

from fastapi import FastAPI as _FastAPI
from fastapi.responses import JSONResponse as _JSONResponse

_api_app = _FastAPI(title="SolidAI SRE Health Monitor API", version="0.3.0")


@_api_app.get("/health")
async def health_check():
    """Health check endpoint for Docker and load balancers."""
    return _JSONResponse({"status": "healthy", "service": "health-monitor"})


@_api_app.get("/health/summary")
async def health_summary_alias():
    """Alias for /api/health-summary — convenience endpoint."""
    return await get_health_summary()


@_api_app.get("/api/health-history")
async def get_health_history(window_hours: int = 24):
    """Get health history with uptime and latency stats for all services."""
    history = _load_history()
    response = {}
    for name, entries in history.items():
        stats = get_uptime_stats(history, name, window_hours)
        latency = get_latency_stats(history, name, window_hours)
        recent_entries = entries[-20:]  # Last 20 entries for detail
        response[name] = {
            "uptime": stats,
            "recent": recent_entries,
        }
        if latency:
            response[name]["latency"] = latency
    return _JSONResponse(response)


@_api_app.get("/api/health-history/{service_name}")
async def get_service_history(service_name: str, window_hours: int = 24):
    """Get health history for a specific service."""
    history = _load_history()
    if service_name not in history:
        return _JSONResponse(
            {"error": f"No history for service: {service_name}"}, status_code=404
        )
    stats = get_uptime_stats(history, service_name, window_hours)
    latency = get_latency_stats(history, service_name, window_hours)
    result = {
        "name": service_name,
        "uptime": stats,
        "history": history[service_name][-100:],  # Last 100 entries
    }
    if latency:
        result["latency"] = latency
    return _JSONResponse(result)


@_api_app.get("/api/health-summary")
async def get_health_summary():
    """Get a dashboard-friendly summary of all service health.

    Returns current status, uptime stats, and latency percentiles
    for all monitored services — designed for dashboard consumption.
    """
    history = _load_history()
    services_summary = []
    all_healthy = True
    any_down = False

    # Build a combined list of all monitored names
    all_names = set(history.keys())

    for name in sorted(all_names):
        uptime = get_uptime_stats(history, name, 24)
        latency = get_latency_stats(history, name, 24)
        current_status = _last_status.get(name, "unknown")

        if current_status in ("down", "degraded"):
            all_healthy = False
        if current_status == "down":
            any_down = True

        svc = {
            "name": name,
            "status": current_status,
            "uptime_24h": uptime.get("uptime_pct"),
        }
        if latency:
            svc["latency"] = {
                "avg_ms": latency["avg_ms"],
                "p95_ms": latency["p95_ms"],
                "p99_ms": latency["p99_ms"],
            }
        services_summary.append(svc)

    overall = "healthy" if all_healthy else ("down" if any_down else "degraded")

    return _JSONResponse({
        "status": overall,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "services": services_summary,
        "total_services": len(services_summary),
        "healthy_count": sum(1 for s in services_summary if s["status"] == "healthy"),
        "degraded_count": sum(1 for s in services_summary if s["status"] == "degraded"),
        "down_count": sum(1 for s in services_summary if s["status"] == "down"),
        "skipped_count": sum(1 for s in services_summary if s["status"] == "skipped"),
    })


@_api_app.get("/api/error-rates")
async def get_error_rates(window_hours: int = None):
    """Get error rates and latency degradation status for all services.

    Returns per-service error rate (rolling window) and whether latency
    is degraded beyond the configured threshold.
    """
    if window_hours is None:
        window_hours = ERROR_RATE_WINDOW
    history = _load_history()
    response = {}
    for name, entries in history.items():
        error_rate = get_error_rate(history, name, window_hours)
        latency_deg = check_latency_degradation(history, name)
        recent_entries = entries[-5:]  # Last 5 entries for quick context
        response[name] = {
            "error_rate": error_rate,
            "latency_degradation": {
                "degraded": latency_deg["degraded"],
                "p95_ms": latency_deg["p95_ms"],
                "threshold_ms": latency_deg["threshold_ms"],
                "reason": latency_deg["reason"],
            },
            "recent": recent_entries,
        }
    return _JSONResponse(response)


@_api_app.get("/api/latency-trends")
async def get_latency_trends(window_hours: int = 2):
    """Get latency trend predictions for all services.

    Uses linear regression on recent latency data to forecast when a service
    will cross the degradation threshold. Enables proactive alerting.
    """
    history = _load_history()
    response = {}
    for name, entries in history.items():
        if not entries:
            continue
        trend = predict_latency_trend(history, name, window_hours=window_hours)
        response[name] = trend
    return _JSONResponse(response)


@_api_app.get("/api/latency-trends/{service_name}")
async def get_service_latency_trend(service_name: str, window_hours: int = 2):
    """Get latency trend prediction for a specific service."""
    history = _load_history()
    if service_name not in history:
        return _JSONResponse(
            {"error": f"No history for service: {service_name}"}, status_code=404
        )
    trend = predict_latency_trend(history, service_name, window_hours=window_hours)
    return _JSONResponse(trend)


async def _check_litellm_model(model_name: str, timeout: float = 25.0) -> dict:
    """Test a single litellm model by sending a minimal completion request.

    Uses a short max_tokens to keep the check fast. If the model times out,
    reports it as degraded rather than waiting indefinitely.

    Note: timeout is 25s because OpenRouter can take 15-20s from some VPS
    network locations. The litellm proxy adds overhead on top, and fallback
    chains can add additional latency. 25s ensures we don't falsely report
    healthy models as down during transient network slowdowns while keeping
    the total background refresh cycle manageable (6 models × 25s parallel ≈ 25s).

    The model_name should be an OpenRouter model ID (e.g. "openai/gpt-oss-20b:free").
    This function sends directly to OpenRouter's API, bypassing litellm, to
    avoid litellm's model routing complexity. We're testing provider reachability,
    not litellm's internal routing.
    """
    # Send directly to OpenRouter API, not through litellm
    openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return {"model": model_name, "status": "not_configured", "error": "OPENROUTER_API_KEY not set"}
    try:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            resp = await client.post(
                openrouter_url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model_name,
                    "messages": [{"role": "user", "content": "OK"}],
                    "max_tokens": 3,
                },
            )
        latency_ms = int((time.monotonic() - start) * 1000)
        if resp.status_code == 200:
            return {"model": model_name, "status": "healthy", "latency_ms": latency_ms}
        # 402 = credit exhaustion (needs user action to refill)
        if resp.status_code == 402:
            return {
                "model": model_name,
                "status": "no_credits",
                "latency_ms": latency_ms,
                "http_status": 402,
                "error": "Insufficient credits — add more at https://openrouter.ai/settings/credits",
            }
        # 429 rate limit or 503 service unavailable = degraded, not unreachable
        if resp.status_code in (429, 503, 502):
            return {
                "model": model_name,
                "status": "degraded",
                "latency_ms": latency_ms,
                "http_status": resp.status_code,
                "error": resp.text[:200],
            }
        return {
            "model": model_name,
            "status": "degraded",
            "latency_ms": latency_ms,
            "http_status": resp.status_code,
            "error": resp.text[:200],
        }
    except httpx.TimeoutException:
        return {
            "model": model_name,
            "status": "timeout",
            "error": f"Request timed out after {timeout}s (provider may be slow or network latency high)",
        }
    except Exception as e:
        return {"model": model_name, "status": "unreachable", "error": str(e)[:200]}


# ---------------------------------------------------------------------------
# Model health cache — background refresh so the API endpoint never blocks
# ---------------------------------------------------------------------------

_model_health_cache: dict = {"status": "pending", "models": [], "timestamp": None}
_model_health_lock = asyncio.Lock()
_model_health_task: Optional[asyncio.Task] = None

# All models from the litellm fallback chain (6 models)
# Ordered by priority: primary → fallbacks → last resort
# NOTE: These are OpenRouter model IDs (without "openrouter/" prefix) since
# _check_litellm_model sends directly to OpenRouter's API, not through litellm.
_MODEL_LIST = [
    "owl-alpha",                                            # llm-primary
    "openai/gpt-oss-20b:free",                              # llm-fallback1
    "cohere/north-mini-code:free",                            # llm-fallback2
    "openai/gpt-oss-120b:free",                             # llm-fallback3
    "nvidia/nemotron-3-ultra-550b-a55b:free",               # llm-fallback4
    "nvidia/nemotron-3-super-120b-a12b:free",               # llm-last-resort
]

# How often to refresh model health in the background (seconds)
MODEL_HEALTH_REFRESH_INTERVAL = 120  # 2 minutes


def _compute_model_overall(results: list[dict]) -> str:
    """Compute overall status from individual model results."""
    all_healthy = all(r["status"] == "healthy" for r in results)
    any_healthy = any(r["status"] == "healthy" for r in results)
    any_no_credits = any(r["status"] == "no_credits" for r in results)
    any_timeout = any(r["status"] == "timeout" for r in results)

    if all_healthy:
        return "healthy"
    elif any_healthy:
        return "degraded"
    elif any_no_credits:
        return "no_credits"
    elif any_timeout:
        return "timeout"
    else:
        return "all_down"


async def _refresh_model_health_cache():
    """Run model health checks in the background and update the cache."""
    global _model_health_cache
    tasks = [_check_litellm_model(m) for m in _MODEL_LIST]
    results = await asyncio.gather(*tasks)
    overall = _compute_model_overall(results)
    _model_health_cache = {
        "status": overall,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "models": results,
    }
    logger.info(f"Model health cache refreshed: overall={overall}")


async def _model_health_background_loop():
    """Background task that periodically refreshes model health cache."""
    # Initial refresh
    try:
        await _refresh_model_health_cache()
    except Exception as e:
        logger.error(f"Initial model health refresh failed: {e}")

    while True:
        await asyncio.sleep(MODEL_HEALTH_REFRESH_INTERVAL)
        try:
            await _refresh_model_health_cache()
        except Exception as e:
            logger.error(f"Model health background refresh failed: {e}")


@_api_app.get("/api/model-health")
async def get_model_health(force: bool = False):
    """Check health of all configured litellm models.

    Returns cached results from background refresh (updated every 2 minutes).
    This ensures the endpoint responds quickly without blocking on slow model checks.
    Use ?force=true to trigger an immediate refresh (may take 30-60s).
    """
    if force:
        try:
            await asyncio.wait_for(_refresh_model_health_cache(), timeout=90.0)
        except asyncio.TimeoutError:
            return _JSONResponse({
                **(_model_health_cache if _model_health_cache["timestamp"] else {"status": "pending", "models": [], "timestamp": None}),
                "refreshing": True,
                "warning": "Force refresh timed out after 90s, showing last cached result",
            })
    return _JSONResponse(_model_health_cache)

@_api_app.get("/api/incidents")
async def get_incidents_endpoint(window_hours: int = 24):
    """Get incident timeline for all services.

    Returns a list of incident objects (downtime/degradation periods) for all
    monitored services within the specified time window (default 24 hours).
    Each incident includes service name, status, start/end times, and duration.
    """
    history = _load_history()
    incidents = get_incidents(history, window_hours)
    return _JSONResponse(incidents)


async def _run_api_server():
    """Run the health history API server on port 8090."""
    import uvicorn

    config = uvicorn.Config(
        _api_app,
        host="0.0.0.0",
        port=8090,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    """Main loop."""
    logger.info("=" * 60)
    logger.info("SolidAI SRE Health Monitor starting")
    logger.info(f"  Check interval: {CHECK_INTERVAL}s")
    logger.info(f"  Alert cooldown: {ALERT_COOLDOWN}s")
    logger.info(f"  Services monitored: {len(SERVICES)}")
    logger.info(f"  Public endpoints: {len(PUBLIC_ENDPOINTS)}")
    logger.info(f"  Integrations: {len(INTEGRATIONS)}")
    logger.info(f"  Telegram alerts: {'enabled' if TELEGRAM_BOT_TOKEN else 'disabled'}")
    logger.info(f"  History file: {HISTORY_FILE}")
    logger.info("=" * 60)

    # Wait for services to stabilize before starting checks
    startup_delay = int(os.getenv("STARTUP_DELAY", "15"))
    logger.info(f"Waiting {startup_delay}s for services to stabilize...")
    await asyncio.sleep(startup_delay)

    # Run initial check immediately
    await run_health_check()

    # Run health check loop and API server concurrently
    await asyncio.gather(
        _health_check_loop(),
        _run_api_server(),
        _model_health_background_loop(),
    )


async def _health_check_loop():
    """Background loop for periodic health checks."""
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            await run_health_check()
        except Exception as e:
            logger.error(f"Health check cycle failed: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
