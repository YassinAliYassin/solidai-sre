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
        "url": "http://litellm:4000/health",
        "timeout": 10.0,
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


async def check_service(service: dict) -> dict:
    """Run a single service health check."""
    name = service["name"]
    try:
        if service["type"] == "http":
            result = await _check_http(service["url"], service["timeout"])
        elif service["type"] == "tcp":
            result = _check_tcp(service["host"], service["port"], service["timeout"])
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


async def check_public_endpoints() -> list[dict]:
    """Check public-facing endpoints."""
    tasks = [check_service(s) for s in PUBLIC_ENDPOINTS]
    return await asyncio.gather(*tasks)


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


async def run_health_check():
    """Run a single health check cycle."""
    logger.info("Running health checks...")

    # Check internal services
    internal_results = await check_all_services()
    await process_results(internal_results, is_public=False)

    # Check public endpoints
    public_results = await check_public_endpoints()
    await process_results(public_results, is_public=True)

    # Log summary
    healthy = sum(1 for r in internal_results + public_results if r["status"] == "healthy")
    total = len(internal_results) + len(public_results)
    degraded = sum(1 for r in internal_results + public_results if r["status"] == "degraded")
    down = sum(1 for r in internal_results + public_results if r["status"] == "down")

    logger.info(
        f"Health check complete: {healthy}/{total} healthy, "
        f"{degraded} degraded, {down} down"
    )

    # Print detailed status
    for r in internal_results + public_results:
        status_emoji = {"healthy": "✅", "degraded": "⚠️", "down": "❌"}.get(r["status"], "❓")
        latency = f" ({r['latency_ms']}ms)" if r.get("latency_ms") else ""
        logger.info(f"  {status_emoji} {r['name']}: {r['status']}{latency}")


async def main():
    """Main loop."""
    logger.info("=" * 60)
    logger.info("SolidAI SRE Health Monitor starting")
    logger.info(f"  Check interval: {CHECK_INTERVAL}s")
    logger.info(f"  Alert cooldown: {ALERT_COOLDOWN}s")
    logger.info(f"  Services monitored: {len(SERVICES)}")
    logger.info(f"  Public endpoints: {len(PUBLIC_ENDPOINTS)}")
    logger.info(f"  Telegram alerts: {'enabled' if TELEGRAM_BOT_TOKEN else 'disabled'}")
    logger.info("=" * 60)

    # Wait for services to stabilize before starting checks
    startup_delay = int(os.getenv("STARTUP_DELAY", "15"))
    logger.info(f"Waiting {startup_delay}s for services to stabilize...")
    await asyncio.sleep(startup_delay)

    # Run initial check immediately
    await run_health_check()

    # Then loop
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            await run_health_check()
        except Exception as e:
            logger.error(f"Health check cycle failed: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
