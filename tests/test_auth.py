import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def secret_client(monkeypatch):
    monkeypatch.setenv("OCTO_SHARED_SECRET", "test-secret")
    import octo_satellite.auth
    import octo_satellite.config
    import octo_satellite.main

    importlib.reload(octo_satellite.config)
    importlib.reload(octo_satellite.auth)
    importlib.reload(octo_satellite.main)
    return TestClient(octo_satellite.main.app)


def test_missing_auth_header(secret_client):
    resp = secret_client.get("/amazon/health")
    assert resp.status_code == 401


def test_wrong_secret(secret_client):
    resp = secret_client.get("/amazon/health", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 403


def test_correct_secret(secret_client):
    resp = secret_client.get("/amazon/health", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
