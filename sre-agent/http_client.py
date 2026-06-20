"""
Shared HTTP client for SolidAI SRE services.

Provides singleton httpx clients with connection pooling
so all internal service calls reuse TCP connections instead of
creating a new client per request.

Usage:
    from http_client import get_client, get_sync_client

    # Async (preferred for FastAPI endpoints):
    client = get_client()
    resp = await client.get("http://localhost:8081/health")

    # Sync (for background tasks / non-async contexts):
    sync_client = get_sync_client()
    with sync_client.stream("GET", url, headers=headers) as resp:
        ...

    # Or use convenience functions:
    from http_client import http_get, http_post
    resp = await http_get("http://localhost:8081/health")
"""

import httpx
import logging
import os

logger = logging.getLogger(__name__)

# Connection pool settings
_POOL_MAX_CONNECTIONS = int(os.getenv("HTTPX_POOL_MAX_CONNECTIONS", "20"))
_POOL_MAX_KEEPALIVE = int(os.getenv("HTTPX_POOL_MAX_KEEPALIVE", "10"))
_DEFAULT_TIMEOUT = float(os.getenv("HTTPX_DEFAULT_TIMEOUT", "10.0"))

# Singleton clients (lazy init)
_async_client: httpx.AsyncClient | None = None
_sync_client: httpx.Client | None = None


def get_client() -> httpx.AsyncClient:
    """Get the shared async httpx client (connection-pooled)."""
    global _async_client
    if _async_client is None or _async_client.is_closed:
        limits = httpx.Limits(
            max_connections=_POOL_MAX_CONNECTIONS,
            max_keepalive_connections=_POOL_MAX_KEEPALIVE,
            keepalive_expiry=60,
        )
        timeout = httpx.Timeout(
            connect=5.0,
            read=_DEFAULT_TIMEOUT,
            write=10.0,
            pool=5.0,
        )
        _async_client = httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            http2=True,
        )
        logger.info(
            f"Async HTTP client initialized: pool={_POOL_MAX_CONNECTIONS}, "
            f"keepalive={_POOL_MAX_KEEPALIVE}, timeout={_DEFAULT_TIMEOUT}s"
        )
    return _async_client


def get_sync_client() -> httpx.Client:
    """Get the shared sync httpx client (connection-pooled)."""
    global _sync_client
    if _sync_client is None or _sync_client.is_closed:
        limits = httpx.Limits(
            max_connections=_POOL_MAX_CONNECTIONS,
            max_keepalive_connections=_POOL_MAX_KEEPALIVE,
            keepalive_expiry=60,
        )
        timeout = httpx.Timeout(
            connect=5.0,
            read=300.0,  # longer for file downloads
            write=10.0,
            pool=5.0,
        )
        _sync_client = httpx.Client(
            limits=limits,
            timeout=timeout,
            http2=True,
        )
        logger.info(
            f"Sync HTTP client initialized: pool={_POOL_MAX_CONNECTIONS}, "
            f"keepalive={_POOL_MAX_KEEPALIVE}, timeout=300s"
        )
    return _sync_client


async def close_client():
    """Close the shared client. Called on app shutdown."""
    global _async_client, _sync_client
    if _async_client is not None and not _async_client.is_closed:
        await _async_client.aclose()
        _async_client = None
    if _sync_client is not None and not _sync_client.is_closed:
        _sync_client.close()
        _sync_client = None
    logger.info("HTTP client closed")


# Convenience functions
async def http_get(url: str, **kwargs) -> httpx.Response:
    """GET using the shared pooled client."""
    return await get_client().get(url, **kwargs)


async def http_post(url: str, **kwargs) -> httpx.Response:
    """POST using the shared pooled client."""
    return await get_client().post(url, **kwargs)


async def http_put(url: str, **kwargs) -> httpx.Response:
    """PUT using the shared pooled client."""
    return await get_client().put(url, **kwargs)


async def http_patch(url: str, **kwargs) -> httpx.Response:
    """PATCH using the shared pooled client."""
    return await get_client().patch(url, **kwargs)
