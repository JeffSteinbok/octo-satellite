"""Tests for localhost-only middleware."""

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def localhost_client(monkeypatch):
    """Client with localhost_only enabled."""
    monkeypatch.delenv("OCTO_SHARED_SECRET", raising=False)
    monkeypatch.setenv("OCTO_LOCALHOST_ONLY", "true")
    import octo_satellite.auth
    import octo_satellite.config
    import octo_satellite.main

    importlib.reload(octo_satellite.config)
    importlib.reload(octo_satellite.auth)
    importlib.reload(octo_satellite.main)
    return TestClient(
        octo_satellite.main.app,
        root_path="",
    )


def test_middleware_allows_loopback_ips():
    """Verify loopback IP detection logic."""
    from octo_satellite.localhost import LOOPBACK_PREFIXES

    # Should be allowed
    for ip in ("127.0.0.1", "127.0.1.1", "::1", "::ffff:127.0.0.1"):
        assert ip.startswith(LOOPBACK_PREFIXES), f"{ip} should be loopback"

    # Should be rejected
    for ip in ("192.168.1.100", "10.0.0.1", "2001:db8::1", "0.0.0.0"):
        assert not ip.startswith(LOOPBACK_PREFIXES), f"{ip} should NOT be loopback"


def test_middleware_rejects_testclient_when_enabled(localhost_client):
    """TestClient uses 'testclient' as host, which is not loopback — should be rejected."""
    resp = localhost_client.get("/health")
    assert resp.status_code == 403
    assert "localhost" in resp.json()["detail"]


def test_middleware_disabled(client):
    """With localhost_only=false, any client is allowed."""
    resp = client.get("/health")
    assert resp.status_code == 200
