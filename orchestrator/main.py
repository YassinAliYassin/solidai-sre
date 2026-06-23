#!/usr/bin/env python3
"""
SolidAI SRE Orchestrator

Polls the config service for due scheduled jobs and executes them.
Currently supports health check monitoring jobs that can send alerts when services go down.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = structlog.get_logger(__name__)

# Configuration
CONFIG_SERVICE_URL = os.getenv("CONFIG_SERVICE_URL", "http://config-service:8080")
HEALTH_MONITOR_URL = os.getenv("HEALTH_MONITOR_URL", "http://health-monitor:8090")
ORCHESTRATOR_ID = os.getenv("ORCHESTRATOR_ID", "solidai-sre-orchestrator")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))  # seconds
MAX_JOBS_PER_POLL = int(os.getenv("MAX_JOBS_PER_POLL", "10"))

# Global state
_running = True


async def poll_and_execute_jobs() -> None:
    """Poll config service for due jobs and execute them."""
    logger.info("Starting orchestrator job polling", 
                config_service_url=CONFIG_SERVICE_URL,
                poll_interval=POLL_INTERVAL,
                max_jobs_per_poll=MAX_JOBS_PER_POLL)
    
    while _running:
        try:
            # Get due jobs from config service
            jobs = await _get_due_jobs()
            if not jobs:
                logger.debug("No due jobs found")
                await asyncio.sleep(POLL_INTERVAL)
                continue
            
            logger.info("Found due jobs", count=len(jobs))
            
            # Execute each job
            for job in jobs:
                try:
                    await _execute_job(job)
                except Exception as e:
                    logger.error("Failed to execute job", 
                               job_id=job["id"], 
                               error=str(e))
                    # Mark job as failed
                    await _mark_job_failed(job["id"], str(e))
                
                # Small delay between job executions
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error("Error in polling loop", error=str(e))
        
        await asyncio.sleep(POLL_INTERVAL)


async def _get_due_jobs() -> list[dict]:
    """Get due jobs from config service."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{CONFIG_SERVICE_URL}/api/v1/internal/scheduled-jobs/due",
                headers={"X-Internal-Service": ORCHESTRATOR_ID},
                params={"limit": MAX_JOBS_PER_POLL}
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get("jobs", [])
            else:
                logger.error("Failed to get due jobs", 
                           status_code=response.status_code)
                return []
                
    except Exception as e:
        logger.error("Error fetching due jobs", error=str(e))
        return []


async def _execute_job(job: dict) -> None:
    """Execute a scheduled job."""
    job_id = job["id"]
    job_type = job["job_type"]
    job_name = job["name"]
    
    logger.info("Executing job", job_id=job_id, job_type=job_type, job_name=job_name)
    
    if job_type == "health_check_monitoring":
        await _execute_health_check_job(job)
    else:
        logger.warning("Unknown job type", job_type=job_type)
        await _mark_job_failed(job_id, f"Unknown job type: {job_type}")


async def _execute_health_check_job(job: dict) -> None:
    """Execute a health check monitoring job."""
    job_id = job["id"]
    config = job.get("config", {})
    
    # Extract job configuration
    alert_threshold = config.get("alert_threshold", "down")  # "down", "degraded", or "any"
    check_interval = config.get("check_interval", 60)  # seconds
    webhook_url = config.get("webhook_url")
    telegram_chat_id = config.get("telegram_chat_id")
    
    logger.info("Executing health check job", 
               job_id=job_id,
               alert_threshold=alert_threshold,
               check_interval=check_interval,
               webhook_url=webhook_url is not None,
               telegram_chat_id=telegram_chat_id is not None)
    
    try:
        # Get current health status
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{HEALTH_MONITOR_URL}/health")
            response.raise_for_status()
            health_data = response.json()
        
        # Analyze health status
        services = health_data.get("services", [])
        healthy_count = sum(1 for s in services if s.get("status") == "healthy")
        degraded_count = sum(1 for s in services if s.get("status") == "degraded")
        down_count = sum(1 for s in services if s.get("status") == "down")
        total_services = len(services)
        
        logger.info("Health check results", 
                   total_services=total_services,
                   healthy=healthy_count,
                   degraded=degraded_count,
                   down=down_count)
        
        # Determine if we should alert
        should_alert = False
        alert_message = ""
        
        if alert_threshold == "down" and down_count > 0:
            should_alert = True
            alert_message = f"🚨 CRITICAL: {down_count} service(s) down!"
        elif alert_threshold == "degraded" and (degraded_count > 0 or down_count > 0):
            should_alert = True
            alert_message = f"⚠️ WARNING: {degraded_count} degraded, {down_count} down"
        elif alert_threshold == "any" and total_services > 0:
            should_alert = True
            alert_message = f"📊 Health status: {healthy_count} healthy, {degraded_count} degraded, {down_count} down"
        
        if should_alert:
            alert_details = {
                "job_id": job_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_services": total_services,
                "healthy_count": healthy_count,
                "degraded_count": degraded_count,
                "down_count": down_count,
                "alert_threshold": alert_threshold,
                "services": services
            }
            
            # Send webhook if configured
            if webhook_url:
                await _send_webhook_alert(webhook_url, alert_message, alert_details)
            
            # Send Telegram alert if configured
            if telegram_chat_id:
                await _send_telegram_alert(telegram_chat_id, alert_message, alert_details)
            
            logger.info("Alert sent for job", job_id=job_id, alert_message=alert_message)
        
        # Mark job as completed successfully
        await _mark_job_completed(job_id)
        
    except Exception as e:
        logger.error("Health check job failed", job_id=job_id, error=str(e))
        await _mark_job_failed(job_id, str(e))


async def _send_webhook_alert(webhook_url: str, message: str, details: dict) -> None:
    """Send alert to webhook URL."""
    try:
        payload = {
            "text": message,
            "details": details,
            "source": "solidai-sre-orchestrator"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            
        logger.info("Webhook alert sent successfully", webhook_url=webhook_url)
        
    except Exception as e:
        logger.error("Failed to send webhook alert", 
                   webhook_url=webhook_url, 
                   error=str(e))


async def _send_telegram_alert(chat_id: str, message: str, details: dict) -> None:
    """Send alert to Telegram chat."""
    try:
        # Get Telegram bot token from environment
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            logger.warning("Telegram bot token not configured")
            return
        
        # Format detailed message
        details_text = "\n\n".join([
            f"**Job ID:** {details['job_id']}",
            f"**Timestamp:** {details['timestamp']}",
            f"**Total Services:** {details['total_services']}",
            f"**Healthy:** {details['healthy_count']}",
            f"**Degraded:** {details['degraded_count']}",
            f"**Down:** {details['down_count']}",
            f"**Threshold:** {details['alert_threshold']}"
        ])
        
        full_message = f"{message}\n\n{details_text}"
        
        # Send to Telegram
        telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": full_message,
            "parse_mode": "Markdown"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(telegram_url, data=data)
            response.raise_for_status()
            
        logger.info("Telegram alert sent successfully", chat_id=chat_id)
        
    except Exception as e:
        logger.error("Failed to send Telegram alert", 
                   chat_id=chat_id, 
                   error=str(e))


async def _mark_job_completed(job_id: str) -> None:
    """Mark a job as completed successfully."""
    await _mark_job_status(job_id, "success", None)


async def _mark_job_failed(job_id: str, error: str) -> None:
    """Mark a job as failed."""
    await _mark_job_status(job_id, "error", error)


async def _mark_job_status(job_id: str, status: str, error: Optional[str]) -> None:
    """Mark a job with completion status."""
    try:
        completion_data = {
            "status": status,
            "error": error
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{CONFIG_SERVICE_URL}/api/v1/internal/scheduled-jobs/{job_id}/complete",
                headers={"X-Internal-Service": ORCHESTRATOR_ID},
                json=completion_data
            )
            response.raise_for_status()
            
        logger.info("Job status updated", 
                   job_id=job_id, 
                   status=status, 
                   error=error)
        
    except Exception as e:
        logger.error("Failed to update job status", 
                   job_id=job_id, 
                   status=status, 
                   error=str(e))


async def shutdown() -> None:
    """Graceful shutdown."""
    global _running
    logger.info("Shutting down orchestrator")
    _running = False


def main() -> None:
    """Main entry point."""
    logger.info("Starting SolidAI SRE Orchestrator")
    
    # Set up signal handlers for graceful shutdown
    import signal
    
    def handle_signal(signum, frame):
        asyncio.create_task(shutdown())
    
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    try:
        asyncio.run(poll_and_execute_jobs())
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        logger.info("Orchestrator stopped")


if __name__ == "__main__":
    main()