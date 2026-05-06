import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def secret_client(monkeypatch):
    monkeypatch.setenv("OCTO_SHARED_SECRET", "test-secret")
    # Re-import to pick up new settings
    import importlib
    import config
    importlib.reload(config)
    import auth
    importlib.reload(auth)
    import main
    importlib.reload(main)
    return TestClient(main.app)


def test_missing_auth_header(secret_client):
    resp = secret_client.get("/amazon/health")
    assert resp.status_code == 401


def test_wrong_secret(secret_client):
    resp = secret_client.get("/amazon/health", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 403


def test_correct_secret(secret_client):
    resp = secret_client.get("/amazon/health", headers={"Authorization": "Bearer test-secret"})
    assert resp.status_code == 200
