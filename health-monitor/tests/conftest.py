"""Shared fixtures for health-monitor tests."""

import pytest


@pytest.fixture
def unused_tcp_port():
    """Return an unused TCP port for testing."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port
