"""Tests for health check functions: TCP, HTTP, and Telegram checks."""

import asyncio
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitor


class TestCheckTcp:
    """Tests for _check_tcp."""

    def test_successful_tcp_check(self, unused_tcp_port):
        """Should return healthy for a reachable TCP port."""
        # Start a simple TCP listener
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.listen(1)

        try:
            result = monitor._check_tcp("127.0.0.1", port, timeout=3.0)
            assert result["status"] == "healthy"
            assert "latency_ms" in result
            assert result["latency_ms"] >= 0
        finally:
            sock.close()

    def test_tcp_connection_refused(self):
        """Should return down for a port with no listener."""
        result = monitor._check_tcp("127.0.0.1", 1, timeout=1.0)
        assert result["status"] == "down"
        assert "error" in result

    def test_tcp_timeout(self):
        """Should return down for an unreachable host."""
        # Use a non-routable address that will timeout
        result = monitor._check_tcp("192.0.2.1", 9999, timeout=0.5)
        assert result["status"] == "down"
        assert "error" in result

    def test_tcp_error_truncated(self):
        """Error message should be truncated to 200 chars."""
        # Force a long error message
        with patch("socket.create_connection", side_effect=Exception("x" * 500)):
            result = monitor._check_tcp("127.0.0.1", 9999, timeout=1.0)
            assert len(result["error"]) <= 200


class TestCheckHttp:
    """Tests for _check_http."""

    @pytest.mark.asyncio
    async def test_successful_http_check(self):
        """Should return healthy for a 200 response."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await monitor._check_http("http://example.com/health", timeout=5.0)

        assert result["status"] == "healthy"
        assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_degraded_http_500(self):
        """Should return degraded for a 500 response."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await monitor._check_http("http://example.com/health", timeout=5.0)

        assert result["status"] == "degraded"
        assert result["http_status"] == 500

    @pytest.mark.asyncio
    async def test_degraded_http_503(self):
        """Should return degraded for a 503 response."""
        mock_response = MagicMock()
        mock_response.status_code = 503

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await monitor._check_http("http://example.com/health", timeout=5.0)

        assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_down_on_connection_error(self):
        """Should return down when connection fails."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await monitor._check_http("http://example.com/health", timeout=5.0)

        assert result["status"] == "down"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_down_on_timeout(self):
        """Should return down on timeout."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await monitor._check_http("http://example.com/health", timeout=5.0)

        assert result["status"] == "down"

    @pytest.mark.asyncio
    async def test_error_truncated(self):
        """Error message should be truncated to 200 chars."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("x" * 500))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await monitor._check_http("http://example.com/health", timeout=5.0)

        assert len(result["error"]) <= 200


class TestCheckTelegramBot:
    """Tests for _check_telegram_bot."""

    @pytest.mark.asyncio
    async def test_healthy_bot(self):
        """Should return healthy for a valid bot."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"username": "test_bot"}
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        old_token = monitor.TELEGRAM_BOT_TOKEN
        monitor.TELEGRAM_BOT_TOKEN = "test-token"
        try:
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await monitor._check_telegram_bot(timeout=10.0)
            assert result["status"] == "healthy"
            assert "Bot @test_bot" in result["details"]
        finally:
            monitor.TELEGRAM_BOT_TOKEN = old_token

    @pytest.mark.asyncio
    async def test_not_configured(self):
        """Should return not_configured when token is missing."""
        old_token = monitor.TELEGRAM_BOT_TOKEN
        monitor.TELEGRAM_BOT_TOKEN = ""
        try:
            result = await monitor._check_telegram_bot(timeout=10.0)
            assert result["status"] == "not_configured"
        finally:
            monitor.TELEGRAM_BOT_TOKEN = old_token

    @pytest.mark.asyncio
    async def test_degraded_on_api_error(self):
        """Should return degraded when Telegram API returns ok=false."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": False}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        old_token = monitor.TELEGRAM_BOT_TOKEN
        monitor.TELEGRAM_BOT_TOKEN = "test-token"
        try:
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await monitor._check_telegram_bot(timeout=10.0)
            assert result["status"] == "degraded"
        finally:
            monitor.TELEGRAM_BOT_TOKEN = old_token

    @pytest.mark.asyncio
    async def test_down_on_exception(self):
        """Should return down on network error."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("fail"))

        old_token = monitor.TELEGRAM_BOT_TOKEN
        monitor.TELEGRAM_BOT_TOKEN = "test-token"
        try:
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await monitor._check_telegram_bot(timeout=10.0)
            assert result["status"] == "down"
        finally:
            monitor.TELEGRAM_BOT_TOKEN = old_token
